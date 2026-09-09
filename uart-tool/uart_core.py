"""uart_core.py - logica condivisa tra CLI (uart_tool.py) e GUI (uart_gui.py).

Le funzioni qui sollevano eccezioni invece di uscire dal processo: chi le
usa (CLI o GUI) decide come presentare l'errore.
"""

import collections
import datetime
import json
import os
import queue
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from collections import namedtuple

import psutil
import serial
from serial.tools import list_ports


def get_base_dir():
    """Cartella base per profiles.json e logs/.

    Se il programma gira come exe PyInstaller (sys.frozen), usa la cartella
    dell'eseguibile (cosi' profiles.json resta editabile accanto all'exe e i
    log finiscono li'); altrimenti la cartella dei sorgenti.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- logging

class UartLogger:
    """Logga su file con timestamp e mostra live a schermo.

    `echo` opzionale: callable(text) per la visualizzazione live (usato
    dalla GUI); se None, scrive su stdout (CLI).
    """

    def __init__(self, log_dir, echo=None):
        os.makedirs(log_dir, exist_ok=True)
        name = "uart_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        self.path = os.path.join(log_dir, name)
        self._fh = open(self.path, "a", encoding="utf-8")
        self._lock = threading.Lock()
        self._rx_buf = ""  # buffer per righe RX parziali
        self.echo = echo
        self._emit(f"[log] file: {self.path}\n")

    def _emit(self, text):
        if self.echo:
            self.echo(text)
        else:
            try:
                sys.stdout.write(text)
            except UnicodeEncodeError:
                # fallback difensivo: se stdout non e' stato reconfigurato con
                # errors="replace" (es. uart_tool.py lo fa all'avvio, ma qui
                # copriamo anche eventuali altri chiamanti), non perdere la
                # riga - sostituisci i caratteri non rappresentabili con '?'.
                enc = sys.stdout.encoding or "utf-8"
                sys.stdout.write(text.encode(enc, errors="replace").decode(enc))
            sys.stdout.flush()

    def _write(self, direction, text):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with self._lock:
            self._fh.write(f"[{ts}] {direction}: {text}\n")
            self._fh.flush()

    def rx(self, data):
        """Riceve chunk di testo RX: mostra subito, logga per righe complete."""
        self._emit(data)
        self._rx_buf += data
        while "\n" in self._rx_buf:
            line, self._rx_buf = self._rx_buf.split("\n", 1)
            self._write("RX", line.rstrip("\r"))

    def tx(self, text):
        self._write("TX", text.rstrip("\r\n"))

    def info(self, text):
        self._emit(text + "\n")
        self._write("--", text)

    def close(self):
        if self._rx_buf:
            self._write("RX", self._rx_buf.rstrip("\r"))
            self._rx_buf = ""
        self._fh.close()


# ---------------------------------------------------------------- seriale

def list_serial_ports():
    return list(list_ports.comports())


def _parse_wmi_date(value):
    """DriverDate arriva serializzato da ConvertTo-Json come '/Date(ms)/'
    (epoch in millisecondi): estrai i ms e rendili 'YYYY-MM-DD'. Se il valore
    e' None o non matcha il pattern, restituisci None invariato."""
    if not isinstance(value, str):
        return None
    m = re.search(r"/Date\((-?\d+)\)/", value)
    if not m:
        return None
    ms = int(m.group(1))
    return datetime.datetime.fromtimestamp(
        ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")


def windows_driver_info():
    """Interroga Windows (WMI Win32_PnPSignedDriver via PowerShell) per il
    driver caricato di ogni dispositivo USB con VID/PID, restituendo un dict
    {"VID:PID": {"name","provider","version","date"}} (hex maiuscolo).

    Best-effort diagnostico: qualsiasi errore (non-Windows, powershell
    assente/timeout, JSON malformato) restituisce {} senza mai sollevare.
    Win32_PnPSignedDriver elenca solo i dispositivi attualmente presenti,
    quindi le porte scollegate non compaiono qui."""
    try:
        ps_cmd = ("Get-CimInstance Win32_PnPSignedDriver | "
                  "Where-Object { $_.DeviceID -match 'VID_' } | "
                  "Select-Object DeviceID,DeviceName,DriverProviderName,"
                  "DriverVersion,DriverDate | ConvertTo-Json -Compress")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10)
        data = json.loads(proc.stdout)
        if isinstance(data, dict):
            data = [data]
        result = {}
        for entry in data:
            device_id = entry.get("DeviceID") or ""
            m = re.search(r"VID_([0-9A-Fa-f]{4}).*?PID_([0-9A-Fa-f]{4})",
                          device_id, re.IGNORECASE)
            if not m:
                continue
            key = f"{m.group(1).upper()}:{m.group(2).upper()}"
            result[key] = {
                "name": entry.get("DeviceName"),
                "provider": entry.get("DriverProviderName"),
                "version": entry.get("DriverVersion"),
                "date": _parse_wmi_date(entry.get("DriverDate")),
            }
        return result
    except Exception:
        return {}


def _port_busy_error(exc):
    """Euristica: l'eccezione indica che la porta/risorsa e' occupata da
    un altro processo (non un errore di altro tipo, es. porta inesistente)."""
    msg = str(exc)
    # Una porta INESISTENTE (adattatore scollegato) NON e' "occupata": va
    # esclusa per prima. pyserial avvolge anche questo caso in "could not
    # open port '...': FileNotFoundError(2, 'Impossibile trovare il file
    # specificato.', ...)", quindi il solo "could not open port" e' un
    # indicatore ambiguo e non basta a dire "occupata". Senza questa
    # esclusione un semplice "porta non trovata" faceva partire la ricerca
    # holder, che poteva matchare per errore la cmdline del processo/shell
    # che ha lanciato il tool (contiene il nome porta) e proporre di
    # ucciderlo. (osservato dal vivo 2026-08-30, COM10 scollegata).
    not_found_markers = ("FileNotFoundError", "WinError 2",
                         "trovare il file", "file specificato",
                         "The system cannot find")
    if any(s in msg for s in not_found_markers):
        return False
    return any(s in msg for s in (
        "Access is denied", "Accesso negato", "PermissionError",
        "WinError 5", "in uso da un altro processo",
    ))


def find_com_port_holders(port):
    """Trova i processi la cui command line menziona la porta seriale
    indicata (es. 'COM3'). Copre il caso reale piu' comune: un'istanza
    precedente di questo stesso tool (CLI o GUI) rimasta appesa sulla
    porta. Esclude il processo corrente."""
    # match sul nome porta come token intero (word boundary), non come
    # sottostringa: evita che una porta "COM3" combaci con "COM30" o con un
    # "COM3" incastonato in un path/argomento di un processo scorrelato.
    port_re = re.compile(r"\b" + re.escape(port) + r"\b", re.IGNORECASE)
    me = os.getpid()
    # Escludi la catena di antenati del processo corrente (la shell/lanciatore
    # che ha avviato il tool): la loro cmdline contiene tipicamente l'intera
    # riga di comando - incluso il nome della porta - e verrebbe scambiata per
    # un "holder" della COM, proponendo di uccidere la propria shell. Non
    # sono mai il vero detentore dell'handle seriale. (fix 2026-08-30)
    exclude = {me}
    try:
        for anc in psutil.Process(me).parents():
            exclude.add(anc.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        pass
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        if proc.pid in exclude:
            continue
        try:
            cmdline = proc.info.get("cmdline") or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if any(port_re.search(arg or "") for arg in cmdline):
            found.append(proc)
    return found


def find_udp_port_holders(port):
    """Trova i processi in ascolto su una porta UDP locale (es. 69/TFTP)."""
    found = []
    seen = set()
    try:
        conns = psutil.net_connections(kind="udp")
    except (psutil.AccessDenied, PermissionError):
        return found
    for c in conns:
        if c.laddr and c.laddr.port == port and c.pid and c.pid not in seen:
            seen.add(c.pid)
            try:
                found.append(psutil.Process(c.pid))
            except psutil.NoSuchProcess:
                continue
    return found


def describe_holder(proc):
    """Riga descrittiva PID/nome/cmdline per un processo, per messaggi
    all'utente (CLI o GUI)."""
    try:
        name = proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        name = "?"
    try:
        cmdline = " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        cmdline = "(cmdline non accessibile)"
    return f"PID {proc.pid} - {name} - {cmdline}"


def kill_holders(procs, timeout=3):
    """Termina (kill) i processi indicati, uno per uno, ignorando quelli
    gia' usciti nel frattempo. Ritorna la lista di quelli effettivamente
    terminati."""
    killed = []
    for proc in procs:
        try:
            proc.kill()
            proc.wait(timeout=timeout)
            killed.append(proc)
        except psutil.NoSuchProcess:
            killed.append(proc)
        except Exception:
            pass
    return killed


def open_port(port, baud, timeout=0.1, on_conflict=None, dtr=None, rts=None):
    """Apre la porta; solleva serial.SerialException in caso di errore.

    Se la porta risulta occupata da un altro processo e viene passato
    on_conflict(port, holders) -> bool, lo chiama per decidere se questo
    tool ha la precedenza: se ritorna True, i processi occupanti vengono
    terminati e l'apertura viene ritentata.

    dtr/rts: se non None, la porta viene aperta impostando quella linea di
    controllo al valore indicato SENZA passare dal costruttore diretto
    serial.Serial(port, baud) - che su Windows asserisce DTR e RTS alti
    all'apertura. Quell'impulso DTR/RTS, se la linea e' cablata al reset
    della board (caso reale su alcuni router/modem, es. VBNT-K), puo'
    resettare/riavviare il dispositivo alla semplice apertura della porta.
    Passando dtr=False, rts=False si apre la seriale tenendo quelle linee
    deasserite, cioe' in sola lettura non invasiva (nessun reset). Con
    entrambi None il comportamento resta identico a prima (retrocompatibile).
    """
    def _open():
        if dtr is None and rts is None:
            return serial.Serial(port, baud, timeout=timeout)
        # Costruzione "a porta chiusa": si impostano prima le linee di
        # controllo, poi si apre. pyserial applica dtr/rts al momento di
        # open(), evitando la transizione alta->basso del costruttore diretto.
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.timeout = timeout
        if dtr is not None:
            ser.dtr = dtr
        if rts is not None:
            ser.rts = rts
        ser.open()
        return ser
    try:
        return _open()
    except serial.SerialException as e:
        if on_conflict is None or not _port_busy_error(e):
            raise
        holders = find_com_port_holders(port)
        if not holders or not on_conflict(port, holders):
            raise
        kill_holders(holders)
        # Windows puo' impiegare ancora un attimo a rilasciare l'handle della
        # COM dopo che il processo occupante e' gia' uscito: un solo retry
        # immediato spesso fallisce ancora con "Accesso negato", quindi
        # riprova a intervalli per un budget totale di ~5s.
        last_err = None
        for _ in range(10):
            try:
                return _open()
            except serial.SerialException as e:
                last_err = e
                time.sleep(0.5)
        raise last_err


# ---------------------------------------------------------- rilevamento baud

# Baud comuni per il debug UART embedded (Qualcomm/Broadcom su router/modem),
# ordinati per probabilita' d'uso decrescente. detect_baud() esclude a runtime
# il baud gia' in uso al momento del trigger (quello "sbagliato").
DEFAULT_BAUD_CANDIDATES = [
    9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600,
    1000000, 1500000, 2000000, 3000000,
]

# Soglia sotto la quale lo stream e' considerato "probabilmente baud sbagliato".
# Byte casuali (baud errato) hanno ~37% di byte stampabili (95 valori
# stampabili su 256); testo pulito supera il 95%. 0.55 lascia un buon margine
# sopra al rumore e sotto al testo con occasionali byte binari legittimi.
PRINTABLE_LOW_THRESHOLD = 0.55

# Soglia alta di affidabilita' per considerare un candidato "trovato" durante
# la scansione: 0.85 evita di scambiare per valido un baud che produce solo
# rumore parzialmente stampabile, restando sotto al testo reale (>0.95).
PRINTABLE_HIGH_THRESHOLD = 0.85

# byte considerati "stampabili": ASCII visibili 0x20-0x7E + tab/LF/CR
_PRINTABLE_BYTES = frozenset(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}

BaudDetectResult = namedtuple(
    "BaudDetectResult", ["baud", "ratio", "found", "results"])


def estimate_printable_ratio(data):
    """Percentuale [0.0-1.0] di byte 'stampabili' in `data` (bytes).

    Buffer vuoto -> 0.0. Testo ASCII pulito -> vicino a 1.0; rumore da baud
    sbagliato (es. NUL/byte di controllo ripetuti) -> basso.
    """
    if not data:
        return 0.0
    good = sum(1 for b in data if b in _PRINTABLE_BYTES)
    return good / len(data)


def _read_sample(ser, sample_time):
    """Legge dalla porta per ~sample_time secondi e ritorna i byte raccolti."""
    end = time.time() + sample_time
    chunks = []
    while time.time() < end:
        try:
            data = ser.read(4096)
        except (serial.SerialException, OSError):
            break
        if data:
            chunks.append(data)
    return b"".join(chunks)


def detect_baud(port, candidates=None, sample_time=0.4, current_baud=None,
                high_threshold=PRINTABLE_HIGH_THRESHOLD, progress=None):
    """Prova i baud candidati e ritorna il migliore per byte stampabili.

    Apre/chiude la porta internamente per ogni candidato: chi chiama DEVE
    aver liberato la porta prima (chiuso il Reader/Serial in monitor).

    - candidates: lista di baud; default DEFAULT_BAUD_CANDIDATES.
    - current_baud: se dato, viene escluso dai candidati (e' quello sbagliato).
    - sample_time: secondi di lettura per candidato.
    - progress(baud, ratio): callback opzionale per candidato (ratio None se
      la porta non e' apribile a quel baud).

    Ritorna BaudDetectResult(baud, ratio, found, results) col candidato a
    percentuale piu' alta (`found` True solo se ratio >= high_threshold),
    oppure None se nessun candidato e' risultato testabile.
    """
    if candidates is None:
        candidates = DEFAULT_BAUD_CANDIDATES
    if current_baud is not None:
        candidates = [b for b in candidates if b != current_baud]

    best_baud = None
    best_ratio = -1.0
    results = []
    for baud in candidates:
        try:
            ser = open_port(port, baud)
        except (serial.SerialException, OSError):
            if progress:
                progress(baud, None)
            continue
        try:
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            data = _read_sample(ser, sample_time)
        finally:
            ser.close()
        ratio = estimate_printable_ratio(data)
        results.append((baud, ratio, len(data)))
        if progress:
            progress(baud, ratio)
        if ratio > best_ratio:
            best_ratio = ratio
            best_baud = baud

    if best_baud is None:
        return None
    return BaudDetectResult(best_baud, best_ratio,
                            best_ratio >= high_threshold, results)


class Reader:
    """Thread in background: legge dalla seriale e passa il testo a on_text."""

    def __init__(self, ser, on_text, encoding="latin-1", recent_size=500,
                 on_error=None, on_bytes=None):
        self.ser = ser
        self.on_text = on_text
        # on_bytes(data: bytes): callback opzionale invocata col chunk RX
        # GREZZO (prima della decodifica) ad ogni lettura. Serve al
        # "serial hub" (SerialHub) per ritrasmettere i byte cosi' come sono
        # ai client agganciati, senza passare da una decodifica/riconifica
        # che potrebbe alterarli. on_text resta invariato per i chiamanti
        # esistenti.
        self.on_bytes = on_bytes
        # on_error(exc): callback opzionale invocata dal thread di lettura se
        # la porta muore (cavo staccato, SerialException/OSError) prima che il
        # thread esca. Permette a chi usa la classe (CLI o GUI) di accorgersi
        # che la connessione e' caduta invece di restare appeso su un reader
        # morto. `self.error` espone la stessa eccezione per un polling.
        self.on_error = on_error
        self.error = None
        # attributo pubblico mutabile: chi usa la classe puo' cambiarlo a
        # runtime (es. la GUI), anche mentre il thread e' gia' in esecuzione -
        # e' una semplice lettura di attributo ad ogni ciclo, nessuna
        # sincronizzazione aggiuntiva necessaria.
        self.encoding = encoding
        # buffer circolare degli ultimi byte RX grezzi: serve all'euristica
        # di rilevamento baud (percentuale di byte stampabili). deque con
        # maxlen scarta automaticamente i byte piu' vecchi. append/extend e
        # lo snapshot bytes(deque) sono operazioni atomiche in CPython
        # (nessun lock necessario per un consumo best-effort dell'euristica).
        self._recent = collections.deque(maxlen=recent_size)
        # contatore totale di byte ricevuti: chi consuma l'euristica lo usa
        # per capire se sono arrivati dati nuovi dall'ultimo controllo (evita
        # falsi trigger su un buffer stantio quando lo stream si ferma).
        self.rx_count = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()

    def recent_bytes(self):
        """Snapshot dei byte RX recenti (per l'euristica di rilevamento baud)."""
        return bytes(self._recent)

    def _run(self):
        while not self._stop.is_set():
            try:
                data = self.ser.read(4096)
            except (serial.SerialException, OSError) as e:
                # non segnalare come errore una chiusura volontaria: se lo
                # stop e' gia' stato richiesto, l'eccezione e' solo l'effetto
                # collaterale della close() dal thread chiamante.
                if not self._stop.is_set():
                    self.error = e
                    if self.on_error:
                        try:
                            self.on_error(e)
                        except Exception:
                            pass
                break
            if data:
                self._recent.extend(data)
                self.rx_count += len(data)
                # ritrasmetti prima i byte grezzi ai client dell'hub (se
                # presente), poi mostra/logga la versione decodificata. Un
                # errore nella broadcast non deve mai fermare la lettura
                # locale, quindi e' isolato.
                if self.on_bytes:
                    try:
                        self.on_bytes(data)
                    except Exception:
                        pass
                # errors="replace" e' necessario per encoding diversi da
                # latin-1 (utf-8/ascii possono trovare byte non validi o
                # sequenze multi-byte spezzate a cavallo di due letture da
                # 4096 byte); latin-1 non fallisce mai comunque, quindi
                # errors="replace" e' innocuo in quel caso.
                self.on_text(data.decode(self.encoding, errors="replace"))

    def stop(self):
        self._stop.set()
        self._t.join(timeout=1)


# ---------------------------------------------------------- serial hub (locale)

def hub_port(name):
    """Porta TCP localhost deterministica per l'hub di condivisione di una COM.

    Le porte COM di Windows sono ad handle esclusivo: un solo processo puo'
    aprirle. Per permettere ad altri processi di vederle/pilotarle si espone
    un piccolo server TCP SOLO su 127.0.0.1, su una porta ricavata dal numero
    della COM cosi' owner e client la calcolano uguale senza scambiarsela:
    47000 + numero (es. COM10 -> 47010, COM3 -> 47003). Se il nome non
    contiene cifre si usa 47999 come fallback.
    """
    digits = "".join(re.findall(r"\d+", name or ""))
    if not digits:
        return 47999
    n = int(digits)
    port = 47000 + n
    # difesa: numeri COM assurdamente grandi non devono sforare il range
    # valido delle porte TCP.
    if port > 65535:
        port = 47000 + (n % 1000)
    return port


class HubPortBusy(Exception):
    """La porta TCP dell'hub e' gia' occupata: esiste gia' un owner con hub
    per questa COM. Il chiamante puo' decidere di agganciarsi come client
    (AttachClient) invece di avviare un secondo hub."""
    pass


class _HubClient:
    """Un client agganciato all'hub: socket + coda di invio dedicata.

    Ogni client ha la propria coda FIFO e un thread che la svuota verso il
    socket. Questo permette di consegnare in modo ATOMICO e ORDINATO prima lo
    storico (scrollback) e poi il flusso live, senza che un chunk live arrivi
    prima dello storico o si perda nel mezzo (vedi SerialHub._accept_loop)."""
    __slots__ = ("conn", "q")

    def __init__(self, conn):
        self.conn = conn
        self.q = queue.Queue()


class SerialHub:
    """Server TCP locale (solo 127.0.0.1) che condivide UNA seriale aperta.

    Dato un `serial.Serial` gia' aperto dall'owner e il nome della COM,
    ascolta su hub_port(port_name). Ogni chunk RX letto dall'owner va passato
    a broadcast(data) che lo ritrasmette a tutti i client agganciati; i byte
    inviati da un client vengono scritti tal quali su `ser` (TX condivisa).
    Solo localhost: nessuna esposizione sulla LAN.

    SINCRONIZZAZIONE CONSOLE: l'hub mantiene un buffer circolare dello storico
    RX (ultimi `history_max` byte). Quando un nuovo client si aggancia riceve
    subito quello storico e POI il flusso live, cosi' la sua console mostra le
    stesse cose gia' viste dall'owner (le console restano allineate) invece di
    partire vuota dal momento dell'aggancio.
    """

    def __init__(self, ser, port_name, on_event=None, history_max=1 << 20):
        self.ser = ser
        self.port_name = port_name
        self.on_event = on_event
        self.tcp_port = hub_port(port_name)
        self._srv = None
        self._clients = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._accept_t = None
        # buffer circolare dello storico RX per la sincronizzazione dei nuovi
        # client. Cap in byte: oltre, si scartano i byte piu' vecchi da
        # sinistra. 1 MiB e' abbondante come scrollback e resta limitato.
        self._history = bytearray()
        self._history_max = max(0, int(history_max))

    def _emit(self, text):
        if self.on_event:
            try:
                self.on_event(text)
            except Exception:
                pass

    def start(self):
        """Avvia il server. Solleva HubPortBusy se la porta hub e' gia' in uso.

        NON viene impostato SO_REUSEADDR di proposito: su Windows permetterebbe
        a un secondo hub di legarsi alla stessa porta gia' occupata, mentre a
        noi serve proprio che il bind FALLISCA per capire che un owner esiste
        gia' (-> il chiamante si aggancia come client).
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.bind(("127.0.0.1", self.tcp_port))
        except OSError as e:
            srv.close()
            raise HubPortBusy(
                f"porta hub {self.tcp_port} gia' occupata per {self.port_name}: {e}")
        srv.listen(8)
        self._srv = srv
        self._accept_t = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_t.start()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._srv.accept()
            except OSError:
                break
            client = _HubClient(conn)
            # Sotto lock: prima accoda lo storico al nuovo client, POI lo
            # registra tra i client live. Cosi' l'ordine e' garantito - ogni
            # broadcast() successivo (anch'esso sotto lock) accodera' il live
            # DOPO lo storico, e nessun chunk arrivato nel frattempo viene
            # perso o duplicato: o e' gia' dentro lo snapshot dello storico
            # (broadcast girato prima di prendere il lock) o verra' accodato
            # come live subito dopo il rilascio.
            with self._lock:
                if self._stop.is_set():
                    try:
                        conn.close()
                    except OSError:
                        pass
                    break
                if self._history:
                    client.q.put(bytes(self._history))
                self._clients.add(client)
                n = len(self._clients)
            threading.Thread(target=self._sender_loop, args=(client,),
                             daemon=True).start()
            threading.Thread(target=self._client_loop, args=(client,),
                             daemon=True).start()
            self._emit(f"[hub] nuovo client agganciato ({n} attivi) - "
                       f"inviato scrollback {len(self._history)} byte")

    def _sender_loop(self, client):
        """Svuota la coda del client verso il socket, in ordine (storico poi
        live). Un `None` in coda e' il sentinello di chiusura."""
        try:
            while not self._stop.is_set():
                data = client.q.get()
                if data is None:
                    break
                client.conn.sendall(data)
        except OSError:
            pass
        finally:
            self._drop(client)

    def _client_loop(self, client):
        """Riceve i byte TX di un client e li scrive sulla seriale."""
        try:
            while not self._stop.is_set():
                data = client.conn.recv(4096)
                if not data:
                    break
                try:
                    self.ser.write(data)
                except Exception:
                    break
        except OSError:
            pass
        finally:
            self._drop(client)

    def _drop(self, client):
        with self._lock:
            self._clients.discard(client)
        # sblocca il sender_loop se e' fermo su q.get()
        try:
            client.q.put_nowait(None)
        except Exception:
            pass
        try:
            client.conn.close()
        except OSError:
            pass

    def broadcast(self, data):
        """Accoda `data` (bytes) allo storico e a tutti i client live.

        L'invio effettivo avviene nei rispettivi _sender_loop; qui si accoda
        soltanto (sotto lock) cosi' lo storico e il live restano ordinati
        rispetto all'aggancio di un nuovo client."""
        if not data:
            return
        with self._lock:
            # aggiorna lo storico (buffer circolare)
            if self._history_max:
                self._history += data
                extra = len(self._history) - self._history_max
                if extra > 0:
                    del self._history[:extra]
            for client in self._clients:
                client.q.put(data)

    def stop(self):
        self._stop.set()
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.q.put_nowait(None)
            except Exception:
                pass
            try:
                client.conn.close()
            except OSError:
                pass
        if self._accept_t:
            self._accept_t.join(timeout=1)


class AttachClient:
    """Client dell'hub: si aggancia alla COM condivisa da un altro processo.

    Speculare a Reader: un thread legge i byte dal socket, li decodifica con
    `encoding` (errors="replace") e li passa a on_text(str) - stessa strada di
    visualizzazione di Reader, cosi' chi usa la classe non distingue tra
    lettura locale e lettura via hub. send(text_or_bytes) invia TX verso
    l'owner. Se la connessione fallisce, connect() solleva OSError.
    """

    def __init__(self, port_name, on_text, encoding="latin-1", on_error=None):
        self.port_name = port_name
        self.on_text = on_text
        self.encoding = encoding
        self.on_error = on_error
        self.error = None
        self.tcp_port = hub_port(port_name)
        self._sock = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def connect(self):
        """Apre la connessione all'hub. Solleva OSError se nessun hub ascolta."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            sock.connect(("127.0.0.1", self.tcp_port))
        except OSError:
            try:
                sock.close()
            except OSError:
                pass
            raise
        sock.settimeout(None)
        self._sock = sock

    def start(self):
        """Avvia il thread di lettura (connette prima se non gia' connesso)."""
        if self._sock is None:
            self.connect()
        self._t.start()

    def _signal_error(self, exc):
        if self._stop.is_set():
            return
        self.error = exc
        if self.on_error:
            try:
                self.on_error(exc)
            except Exception:
                pass

    def _run(self):
        while not self._stop.is_set():
            try:
                data = self._sock.recv(4096)
            except OSError as e:
                self._signal_error(e)
                break
            if not data:
                # l'hub (owner) ha chiuso la connessione
                self._signal_error(ConnectionResetError("hub chiuso dall'owner"))
                break
            self.on_text(data.decode(self.encoding, errors="replace"))

    def send(self, data):
        """Invia TX all'owner via hub. `data` str (utf-8) o bytes."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        if self._sock is not None:
            self._sock.sendall(data)

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
        self._t.join(timeout=1)


class PortWatcher:
    """Rileva plug/unplug delle porte seriali con polling in un thread.

    callback(event, device, description) con event in {"added", "removed"}.
    La callback viene invocata dal thread del watcher: chi la usa da GUI
    deve rimbalzare sull'event loop (es. con una queue).
    """

    def __init__(self, callback, interval=1.5):
        self.callback = callback
        self.interval = interval
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self.known = {}

    @staticmethod
    def snapshot():
        return {p.device: p.description for p in list_ports.comports()}

    def start(self):
        self.known = self.snapshot()
        self._t.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                current = self.snapshot()
            except Exception:
                continue
            for dev, desc in current.items():
                if dev not in self.known:
                    self.callback("added", dev, desc)
            for dev, desc in self.known.items():
                if dev not in current:
                    self.callback("removed", dev, desc)
            self.known = current

    def stop(self):
        self._stop.set()
        self._t.join(timeout=self.interval + 1)


class RxTailMatcher:
    """Cerca una stringa in uno stream RX letto a chunk arbitrari.

    read(4096) non rispetta i confini di riga: la stringa cercata (es.
    "Market ID") puo' finire spezzata tra due letture consecutive. Accumula
    una coda degli ultimi `tail` caratteri e cerca sul concatenato, cosi' un
    match a cavallo di due chunk non viene perso.
    """

    def __init__(self, needle, tail=50):
        self.needle = needle
        self.tail = tail
        self._buf = ""

    def feed(self, text):
        """Aggiunge `text` e ritorna True se `needle` e' ora presente."""
        combined = self._buf + text
        self._buf = combined[-self.tail:]
        return self.needle in combined


# ---------------------------------------------------------------- profili

def load_profiles(path):
    """Solleva FileNotFoundError o ValueError (JSON invalido)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file profili non trovato: {path}")
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"profiles.json non valido: {e}")


def get_profile(profiles, name):
    if name not in profiles:
        raise ValueError(f"profilo '{name}' non trovato. "
                         f"Disponibili: {', '.join(sorted(profiles))}")
    profile = profiles[name]
    if not isinstance(profile, dict):
        raise ValueError(f"profilo '{name}' malformato in profiles.json: "
                         f"atteso un oggetto, trovato {type(profile).__name__}.")
    return profile


# ---------------------------------------------------------------- bootloader

def enter_bootloader(profile, port, baud, logger):
    """Esegue la sequenza di ingresso bootloader del profilo.

    Apre e chiude la porta internamente (per liberarla al tool di flash).
    Solleva serial.SerialException (porta) o ValueError (metodo sconosciuto).
    """
    bl = profile.get("bootloader")
    if not bl:
        logger.info("[bootloader] nessuna sequenza definita nel profilo, salto.")
        return
    if not isinstance(bl, dict):
        raise ValueError("voce 'bootloader' malformata nel profilo: atteso un "
                         f"oggetto, trovato {type(bl).__name__}.")
    method = bl.get("method")
    ser = open_port(port, baud)
    try:
        if method == "dtr_rts":
            logger.info("[bootloader] eseguo sequenza DTR/RTS...")
            for step in bl.get("sequence", []):
                key, val = step[0], step[1]
                if key == "sleep":
                    time.sleep(float(val))
                elif key == "dtr":
                    ser.dtr = bool(val)
                elif key == "rts":
                    ser.rts = bool(val)
                else:
                    logger.info(f"[bootloader] passo sconosciuto ignorato: {step}")
        elif method == "command":
            cmd = bl.get("command", "")
            logger.info(f"[bootloader] invio comando: {cmd.rstrip()}")
            ser.write(cmd.encode("utf-8"))
            logger.tx(cmd)
            time.sleep(float(bl.get("wait", 1.0)))
        else:
            raise ValueError(f"metodo bootloader sconosciuto: {method}")
    finally:
        ser.close()


# ---------------------------------------------------------------- flash

def flash_summary_fields(profile_name, firmware, port, baud, use_bootloader,
                         flash_cmd):
    """Campi (etichetta, valore) del riepilogo di flash, condivisi tra la
    conferma CLI e quella GUI cosi' il contenuto resta allineato."""
    return [
        ("profilo", profile_name),
        ("firmware", firmware),
        ("porta", f"{port} @ {baud}"),
        ("bootloader", "SI" if use_bootloader else "NO"),
        ("comando", flash_cmd),
    ]


def build_flash_cmd(profile, profile_name, port, baud, firmware):
    """Valida e costruisce il comando di flash. Solleva ValueError/FileNotFoundError."""
    if not isinstance(profile, dict):
        raise ValueError(f"profilo '{profile_name}' malformato in profiles.json: "
                         f"atteso un oggetto, trovato {type(profile).__name__}.")
    if not os.path.isfile(firmware):
        raise FileNotFoundError(f"file firmware non trovato: {firmware}")
    template = profile.get("flash_cmd")
    if not template:
        raise ValueError(f"il profilo '{profile_name}' non ha 'flash_cmd' "
                         f"configurato: modifica profiles.json per definirlo.")
    return template.format(port=port, baud=baud, file=firmware)


def run_flash(flash_cmd, logger):
    """Esegue il comando di flash esterno, streamando l'output nel logger.

    Ritorna l'exit code. Solleva FileNotFoundError se l'eseguibile manca.
    """
    logger.info(f"[flash] eseguo: {flash_cmd}")
    # posix=False: su Windows i path contengono backslash (es. C:\Users\x\fw.bin)
    # che lo split POSIX di default rimuoverebbe silenziosamente, corrompendo
    # il comando. La modalita' non-POSIX li preserva.
    proc = subprocess.Popen(shlex.split(flash_cmd, posix=False),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True, errors="replace")
    try:
        for line in proc.stdout:
            logger.rx(line)
        proc.wait()
    except BaseException:
        # interruzione (Ctrl+C) o eccezione durante lo stream: non lasciare
        # il processo di flash orfano/staccato - terminalo, e uccidilo se non
        # esce entro poco.
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        logger.info("[flash] interrotto, processo di flash terminato.")
        raise
    if proc.returncode == 0:
        logger.info("[flash] completato con successo.")
    else:
        logger.info(f"[flash] FALLITO (exit code {proc.returncode}).")
    return proc.returncode
