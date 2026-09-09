"""uart_netboot.py - responder BOOTP + server TFTP per il recovery di rete
del bootloader CFE (Technicolor VBNT-K e simili).

Riferimento: script scapy fornito dalla sessione "uart modem recovery
technicolor", verificato funzionante su hardware reale. Punti critici
riportati da quel test (rispettati qui):
  - siaddr nel BOOTREPLY va sempre impostato esplicitamente, altrimenti il
    router non sa a chi chiedere il TFTP e ripete la BOOTREQUEST all'infinito.
  - l'interfaccia di rete va sempre scelta esplicitamente (mai un default che
    ascolti su tutte le interfacce): un tool precedente in ascolto su
    0.0.0.0 ha fatto leak DHCP/BOOTP su un hotspot WiFi collegato allo
    stesso PC, togliendo internet a dispositivi di un'altra rete.

Scapy viene importato in modo lazy (dentro le funzioni che ne hanno
bisogno) cosi' il resto del tool funziona anche su una macchina senza
scapy/Npcap installati.
"""

import os
import shutil
import socket
import struct
import threading
import time

import uart_core


class NetbootError(Exception):
    pass


def _require_scapy():
    try:
        from scapy.all import get_if_list, get_if_hwaddr, sendp, AsyncSniffer  # noqa: F401
        from scapy.layers.l2 import Ether, ARP  # noqa: F401
        from scapy.layers.inet import IP, UDP  # noqa: F401
        from scapy.layers.dhcp import BOOTP  # noqa: F401
    except ImportError as e:
        raise NetbootError(
            "scapy non disponibile. Installa con: pip install scapy\n"
            "Serve anche il driver Npcap (https://npcap.com) per catturare "
            f"pacchetti su Windows. Dettaglio errore: {e}"
        )


def prepare_named_copy(src_path, board_name, dest_dir):
    """Copia `src_path` in `dest_dir` rinominandolo esattamente come
    `board_name` (il "Board Mnemonic" richiesto dal bootloader, es.
    "VBNT-K" - un nome esatto, senza estensione aggiunta). Sovrascrive
    una copia precedente. Ritorna il path della copia pronta per il TFTP.
    """
    if not os.path.isfile(src_path):
        raise NetbootError(f"file firmware non trovato: {src_path}")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, board_name)
    shutil.copyfile(src_path, dest_path)
    return dest_path


def list_interfaces():
    """Ritorna la lista dei nomi di interfaccia disponibili per scapy.

    Su Windows preferisce i nomi "amichevoli" (es. "Ethernet", "Wi-Fi")
    invece dei device path grezzi (\\Device\\NPF_{GUID...}) restituiti da
    get_if_list(): con la selezione dell'interfaccia obbligatoria per
    sicurezza (vedi modulo), un GUID illeggibile vanificherebbe lo scopo,
    l'utente non potrebbe capire quale sia la scheda giusta. scapy accetta
    il nome amichevole in sniff()/sendp(iface=...) su Windows.
    """
    _require_scapy()
    try:
        import re
        from scapy.arch.windows import get_windows_if_list
        # get_windows_if_list() include anche i binding interni dei driver
        # (filtri WFP, Npcap Packet Driver, QoS Scheduler...), non vere
        # interfacce selezionabili: hanno tutti un nome tipo
        # "Ethernet-Npcap Packet Driver (NPCAP)-0000" (suffisso -NNNN).
        # Escludili per non affogare la scelta reale in decine di doppioni.
        names = [i["name"] for i in get_windows_if_list() if i.get("name")]
        names = [n for n in names if not re.search(r"-\d{4}$", n)]
        if names:
            return names
    except Exception:
        pass
    from scapy.all import get_if_list
    return list(get_if_list())


def detect_router_mac(iface, ip, timeout=2.0):
    """Rileva il MAC del router inviando una richiesta ARP "who-has" per
    `ip` sull'interfaccia `iface` e leggendo il MAC sorgente di chi risponde.

    Sostituisce un MAC hardcoded (che cambia da device a device, e non ha
    senso pubblicare/riusare come default fisso): finche' il router e'
    ancora raggiungibile sulla sua IP normale (prima di essere spinto in
    modalita' di recovery), un ARP diretto lo identifica in modo affidabile
    in ~1-2s. Ritorna il MAC (stringa minuscola "aa:bb:cc:dd:ee:ff") oppure
    None se nessuno risponde entro `timeout` secondi (es. il router e' gia'
    in un boot state senza stack IP normale, o l'IP indicato e' sbagliato) -
    in quel caso il chiamante decide come procedere (chiedere il MAC a mano,
    o disattivare esplicitamente il filtro), non c'e' un default silenzioso.
    """
    _require_scapy()
    from scapy.layers.l2 import Ether, ARP
    from scapy.all import srp
    request = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(op=1, pdst=ip)
    try:
        answered, _ = srp(request, iface=iface, timeout=timeout, verbose=False)
    except Exception as e:
        raise NetbootError(f"errore durante la richiesta ARP a {ip} su '{iface}': {e}")
    if not answered:
        return None
    return answered[0][1][Ether].src.lower()


# ------------------------------------------------------------- BOOTP reply

def build_bootp_reply(request_bootp, server_ip, offer_ip, my_mac, client_mac,
                       fallback_filename):
    """Costruisce il pacchetto BOOTREPLY (Ether/IP/UDP/BOOTP) di risposta a
    una BOOTREQUEST. Funzione pura: non tocca la rete, solo packet crafting,
    cosi' e' testabile senza hardware/Npcap.

    `request_bootp` e' il layer BOOTP della richiesta (deve avere op/htype/
    hlen/xid/flags/chaddr/file). `my_mac`/`client_mac` sono stringhe MAC.
    """
    _require_scapy()
    from scapy.layers.l2 import Ether
    from scapy.layers.inet import IP, UDP
    from scapy.layers.dhcp import BOOTP

    raw_file = bytes(request_bootp.file) if request_bootp.file else b""
    req_file = raw_file.split(b"\x00")[0].decode(errors="ignore")
    reply_file_str = req_file if req_file else fallback_filename
    reply_file = reply_file_str.encode()[:128]

    # opzione 1 (subnet mask) + fine opzioni, come nello script di riferimento
    opts = bytes([1, 4]) + socket.inet_aton("255.255.255.0") + bytes([255])

    reply = (
        Ether(dst=client_mac, src=my_mac)
        / IP(src=server_ip, dst="255.255.255.255")
        / UDP(sport=67, dport=68)
        / BOOTP(
            op=2,
            htype=request_bootp.htype,
            hlen=request_bootp.hlen,
            xid=request_bootp.xid,
            secs=0,
            flags=request_bootp.flags,
            ciaddr="0.0.0.0",
            yiaddr=offer_ip,
            siaddr=server_ip,
            giaddr="0.0.0.0",
            chaddr=request_bootp.chaddr,
            sname=b"",
            file=reply_file,
            options=opts,
        )
    )
    return reply, reply_file_str, req_file


# ------------------------------------------------------------- responder

class BootpResponder:
    """Sniffa BOOTREQUEST su un'interfaccia esplicita e risponde con un
    BOOTREPLY valido (siaddr impostato). Usa AsyncSniffer per poter fermare
    la cattura in modo pulito da GUI/CLI.
    """

    def __init__(self, iface, server_ip, offer_ip, fallback_filename, on_event=None,
                 on_request=None, router_mac=None):
        _require_scapy()
        self.iface = iface
        self.server_ip = server_ip
        self.offer_ip = offer_ip
        self.fallback_filename = fallback_filename
        # router_mac: se impostato, il responder risponde SOLO alle
        # BOOTREQUEST provenienti da questo MAC (il router bersaglio),
        # ignorando qualsiasi altro dispositivo sull'interfaccia. Cosi' su
        # una LAN reale (non un banco di recovery isolato) non si offre un
        # IP/boot file finto a un dispositivo di terzi che manda DHCP/BOOTP.
        # Se None il filtro e' disattivato (risponde a chiunque): scelta da
        # rendere esplicita in CLI/GUI, non un default.
        self.router_mac = router_mac.lower().replace("-", ":") if router_mac else None
        self.on_event = on_event or (lambda text: None)
        # on_request(req_file, resolved_name): chiamato a ogni BOOTREQUEST,
        # PRIMA di inviare la risposta - permette a chi usa la classe di
        # scoprire il nome file che il router sta davvero cercando (il
        # bootloader lo annuncia da solo, non serve indovinarlo a priori) e
        # aggiornare di conseguenza il file servito dal TFTP.
        self.on_request = on_request
        self._sniffer = None
        self._my_mac = None

    def _log(self, text):
        self.on_event(text)

    def _handle_arp(self, pkt):
        """Risponde direttamente (via sendp, stesso meccanismo del BOOTREPLY)
        a qualunque richiesta ARP "who-has" per il nostro server_ip, invece
        di affidarsi al normale stack di rete di Windows per farlo. Il
        bootloader CFE del router ha il proprio stack di rete minimale con
        timeout stretti: se lo stack Windows risponde con un ritardo anche
        piccolo (es. per contesa con il thread di cattura Npcap), CFE puo'
        arrendersi prima di ricevere la risposta e non mandare mai la RRQ
        TFTP - osservato dal vivo (nessuna RRQ mai arrivata nonostante bind
        riuscito e nessun conflitto di porta). Rispondere qui, sullo stesso
        socket raw gia' usato per il BOOTREPLY, elimina questa dipendenza."""
        from scapy.layers.l2 import Ether, ARP
        arp = pkt[ARP]
        if arp.op != 1 or arp.pdst != self.server_ip:
            return
        # Ignora i probe di Address Conflict Detection che WINDOWS STESSO
        # genera per il proprio server_ip (secondario, aggiunto a mano):
        # sorgente 0.0.0.0 (probe ACD) o server_ip stesso, oppure MAC
        # sorgente = il nostro. Rispondere a questi convince Windows che
        # esiste un conflitto di indirizzo IP duplicato in rete, che puo'
        # portare Windows a smettere silenziosamente di consegnare i
        # pacchetti unicast (es. la RRQ TFTP) al proprio socket bindato
        # su quell'IP - osservato dal vivo (RRQ mai arrivata nonostante
        # ARP/BOOTP raw funzionanti).
        if arp.psrc in ("0.0.0.0", self.server_ip) or pkt[Ether].src.lower() == self._my_mac.lower():
            return
        try:
            from scapy.all import sendp
            reply = (
                Ether(dst=pkt[Ether].src, src=self._my_mac)
                / ARP(op=2, hwsrc=self._my_mac, psrc=self.server_ip,
                      hwdst=pkt[Ether].src, pdst=arp.psrc)
            )
            sendp(reply, iface=self.iface, verbose=False)
            self._log(f"[netboot] ARP reply diretta: {self.server_ip} e' a {self._my_mac} "
                      f"(richiesta da {arp.psrc}/{pkt[Ether].src})")
        except Exception as e:
            self._log(f"[netboot] errore invio ARP reply: {e}")

    def _handle(self, pkt):
        from scapy.layers.dhcp import BOOTP
        from scapy.layers.l2 import Ether, ARP
        if pkt.haslayer(ARP):
            self._handle_arp(pkt)
            return
        if not pkt.haslayer(BOOTP):
            return
        bootp = pkt[BOOTP]
        if bootp.op != 1:  # solo BOOTREQUEST
            return
        client_mac = pkt[Ether].src
        if self.router_mac and client_mac.lower().replace("-", ":") != self.router_mac:
            self._log(
                f"[netboot] BOOTREQUEST da {client_mac} ignorato "
                f"(non corrisponde a router_mac={self.router_mac})"
            )
            return
        self._log(f"[netboot] BOOTREQUEST da {client_mac}, xid={bootp.xid:#x}")

        reply, reply_file_str, req_file = build_bootp_reply(
            bootp, self.server_ip, self.offer_ip, self._my_mac, client_mac,
            self.fallback_filename,
        )
        if self.on_request:
            try:
                self.on_request(req_file, reply_file_str)
            except Exception as e:
                self._log(f"[netboot] errore callback on_request: {e}")
        try:
            from scapy.all import sendp
            sendp(reply, iface=self.iface, verbose=False)
            self._log(
                f"[netboot] BOOTREPLY inviata: yiaddr={self.offer_ip} "
                f"siaddr={self.server_ip} file={reply_file_str!r} "
                f"(richiesto dal router: {req_file!r})"
            )
        except Exception as e:
            self._log(f"[netboot] errore invio BOOTREPLY: {e}")

    def start(self):
        from scapy.all import get_if_hwaddr, AsyncSniffer
        try:
            self._my_mac = get_if_hwaddr(self.iface)
        except Exception as e:
            raise NetbootError(f"impossibile leggere il MAC di '{self.iface}': {e}")
        self._log(
            f"[netboot] responder BOOTP avviato su '{self.iface}' "
            f"(MAC {self._my_mac}), server={self.server_ip}, offro={self.offer_ip}"
        )
        if self.router_mac:
            self._log(
                f"[netboot] filtro MAC attivo: rispondo solo al router "
                f"{self.router_mac}"
            )
        else:
            self._log(
                "[netboot] ATTENZIONE: nessun filtro MAC attivo, il responder "
                "rispondera' a QUALSIASI dispositivo sull'interfaccia"
            )
        self._sniffer = AsyncSniffer(
            iface=self.iface,
            filter="(udp and (port 67 or port 68)) or arp",
            prn=self._handle,
            store=False,
        )
        self._sniffer.start()
        self._log(f"[netboot] risposta ARP diretta attiva per {self.server_ip} "
                   f"(evita di dipendere dai tempi dello stack di rete di Windows)")

    def stop(self):
        if self._sniffer is not None:
            try:
                self._sniffer.stop()
            except Exception:
                pass
            self._sniffer = None
        self._log("[netboot] responder BOOTP fermato.")


# ------------------------------------------------------------- TFTP server

class TftpServer:
    """Mini server TFTP (RFC 1350) in Python puro, sola lettura.

    Serve SEMPRE il file configurato (`filepath`), indipendentemente dal
    nome richiesto dal client - evita del tutto i problemi di filename
    mismatch osservati con l'implementazione di riferimento (il router a
    volte manda un nome vuoto, o il "Board Mnemonic" invece del nome file
    reale). Il nome richiesto viene comunque loggato per trasparenza.
    """

    OPCODE_RRQ = 1
    OPCODE_DATA = 3
    OPCODE_ACK = 4
    OPCODE_ERROR = 5
    OPCODE_OACK = 6
    BLOCK_SIZE = 512
    # timeout/retry allineati a tftpd64 (tftpd32.ini: Timeout=3,
    # MaxRetransmit=6), la stessa implementazione TFTP gia' dimostrata
    # funzionante su questo router (32.9MB trasferiti, zero blocchi
    # ritrasmessi). Il nostro server
    # dava per default meno della meta' del budget totale di attesa
    # (7.5s vs 18s) prima di arrendersi su un singolo blocco.
    TIMEOUT = 3.0
    MAX_RETRIES = 6
    MAX_BLKSIZE = 1428  # sotto la MTU Ethernet tipica (1500) con margine per gli header

    def __init__(self, filepath, bind_ip="0.0.0.0", port=69, on_event=None,
                 on_conflict=None):
        if not os.path.isfile(filepath):
            raise NetbootError(f"file firmware non trovato: {filepath}")
        self.filepath = filepath
        self.bind_ip = bind_ip
        self.port = port
        self.on_event = on_event or (lambda text: None)
        # on_conflict(port, holders) -> bool: chiamato se la porta UDP e'
        # gia' occupata (tipicamente un'istanza precedente di questo tool
        # rimasta appesa); se ritorna True i processi occupanti vengono
        # terminati e il bind ritentato una volta sola.
        self.on_conflict = on_conflict
        self._stop = threading.Event()
        self._sock = None
        self._thread = None
        # IP dei client con un trasferimento gia' in corso (vedi _run):
        # una RRQ duplicata dallo stesso client mentre e' gia' attivo un
        # trasferimento viene ignorata invece di aprire una seconda sessione
        # in parallelo, che confonderebbe il client (due porte effimere
        # diverse che gli scrivono dati per la stessa richiesta).
        self._active_clients = set()
        self._active_lock = threading.Lock()

    def _log(self, text):
        self.on_event(text)

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.5)
        try:
            self._sock.bind((self.bind_ip, self.port))
        except OSError as e:
            holders = uart_core.find_udp_port_holders(self.port)
            if not holders or not self.on_conflict or not self.on_conflict(self.port, holders):
                raise
            uart_core.kill_holders(holders)
            self._sock.bind((self.bind_ip, self.port))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._log(f"[tftp] server TFTP avviato su {self.bind_ip}:{self.port}, "
                   f"file servito: {self.filepath}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._sock:
            self._sock.close()
        self._log("[tftp] server TFTP fermato.")

    def _run(self):
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) < 2:
                continue
            opcode = struct.unpack("!H", data[:2])[0]
            if opcode != self.OPCODE_RRQ:
                continue
            client_ip = addr[0]
            with self._active_lock:
                if client_ip in self._active_clients:
                    # RRQ ripetuta dallo stesso client mentre il suo
                    # trasferimento e' gia' in corso (es. il client non ha
                    # ancora visto la nostra risposta e ritrasmette la
                    # richiesta originale, non un blocco) - ignorata, non
                    # apriamo una seconda sessione parallela.
                    self._log(f"[tftp] RRQ duplicata da {addr} ignorata "
                              f"(trasferimento gia' in corso)")
                    continue
                self._active_clients.add(client_ip)
            # Ogni richiesta gira nel proprio thread cosi' questo loop
            # torna subito in ascolto: prima una RRQ lenta (trasferimento
            # di decine di MB, fino a MAX_RETRIES*TIMEOUT per blocco)
            # bloccava qui dentro, e una eventuale nuova RRQ dallo stesso o
            # da un altro client restava non letta nel buffer del socket
            # fino al termine del trasferimento in corso.
            threading.Thread(target=self._run_transfer, args=(data, addr),
                              daemon=True).start()

    def _run_transfer(self, data, addr):
        try:
            self._handle_rrq(data, addr)
        except Exception as e:
            self._log(f"[tftp] errore gestendo richiesta da {addr}: {e}")
        finally:
            with self._active_lock:
                self._active_clients.discard(addr[0])

    @staticmethod
    def _parse_rrq(data):
        """Estrae filename/mode/opzioni da una RRQ. Il formato RFC 1350 e'
        opcode|filename\\0|mode\\0[|opzione\\0|valore\\0]*  - le opzioni
        (RFC 2347: blksize/tsize/timeout) sono usate da molti bootloader
        embedded (CFE incluso). Ignorarle silenziosamente, come faceva la
        prima versione di questo server, e' tecnicamente permesso da RFC 2347
        (il client dovrebbe capire dalla mancata OACK che non sono supportate
        e procedere comunque) ma alcuni client meno tolleranti si bloccano
        se non ricevono ne' un OACK ne' un comportamento coerente - meglio
        negoziarle esplicitamente quando presenti."""
        parts = data[2:].split(b"\x00")
        req_name = parts[0].decode(errors="ignore") if parts else ""
        mode = parts[1].decode(errors="ignore") if len(parts) > 1 else "octet"
        options = {}
        rest = parts[2:]
        for i in range(0, len(rest) - 1, 2):
            name = rest[i].decode(errors="ignore").strip().lower()
            value = rest[i + 1].decode(errors="ignore").strip()
            if name:
                options[name] = value
        return req_name, mode, options

    @staticmethod
    def _recv_from(sock, expected_ip, timeout):
        """recvfrom() che scarta pacchetti non provenienti da `expected_ip`,
        restando pero' entro il budget di tempo assegnato invece di
        ripartire da un timeout pieno a ogni pacchetto estraneo. Senza
        questo controllo, qualunque host sulla LAN (in questo progetto se ne
        e' visto parecchio: telefoni con MAC randomizzati, altri dispositivi
        che generano traffico di rete di fondo) che mandasse per puro caso
        un pacchetto alla stessa porta effimera con la forma di un ACK/ERROR
        TFTP verrebbe accettato come se fosse il vero client."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout()
            sock.settimeout(remaining)
            data, from_addr = sock.recvfrom(65535)
            if from_addr[0] == expected_ip:
                return data, from_addr
            # rumore da un altro host: non consuma il tentativo, si continua
            # ad aspettare la risposta del client vero entro lo stesso budget.

    @staticmethod
    def _send_error(sock, addr, code, message):
        try:
            sock.sendto(
                struct.pack("!HH", TftpServer.OPCODE_ERROR, code)
                + message.encode(errors="ignore") + b"\x00",
                addr,
            )
        except OSError:
            pass

    def _handle_rrq(self, data, addr):
        req_name, mode, options = self._parse_rrq(data)
        self._log(f"[tftp] RRQ da {addr}: file richiesto={req_name!r} "
                   f"modo={mode!r} opzioni={options or '(nessuna)'} "
                   f"-> servo {os.path.basename(self.filepath)}")

        with open(self.filepath, "rb") as f:
            content = f.read()
        total = len(content)

        # socket dedicato alla sessione di trasferimento (porta effimera),
        # come da RFC 1350 - il client dialoga con la nuova porta dal blocco 1 in poi.
        sess = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        block_size = self.BLOCK_SIZE
        sess.settimeout(self.TIMEOUT)
        try:
            if options:
                accepted = {}
                if "blksize" in options:
                    try:
                        requested = int(options["blksize"])
                        block_size = max(8, min(requested, self.MAX_BLKSIZE))
                        accepted["blksize"] = str(block_size)
                    except ValueError:
                        pass
                if "tsize" in options:
                    accepted["tsize"] = str(total)
                if "timeout" in options:
                    try:
                        requested_to = int(options["timeout"])
                        sess.settimeout(max(1, min(requested_to, 10)))
                        accepted["timeout"] = str(int(sess.gettimeout()))
                    except ValueError:
                        pass

                # Il numero di blocco TFTP e' a 16 bit (RFC 1350): oltre
                # 65535 blocchi il contatore si avvolge e il client lo
                # confonde con l'inizio di un nuovo trasferimento -
                # corruzione silenziosa. A blksize=512 il limite e' ~32MB,
                # e alcuni firmware di questo stesso progetto (AGTEF_2.4.5,
                # ~33MB) ci arrivano vicino. Qui il client HA negoziato
                # opzioni, quindi possiamo imporre un blksize piu' grande
                # (entro MAX_BLKSIZE) via OACK per restare sotto il limite.
                min_safe_block_size = -(-total // 65535)  # ceil(total/65535)
                if block_size < min_safe_block_size <= self.MAX_BLKSIZE:
                    block_size = min_safe_block_size
                    accepted["blksize"] = str(block_size)
                    self._log(f"[tftp] blksize alzato a {block_size} per "
                              f"restare sotto il limite di 65535 blocchi "
                              f"({total} byte)")

                if accepted:
                    oack = struct.pack("!H", self.OPCODE_OACK)
                    for name, value in accepted.items():
                        oack += name.encode() + b"\x00" + value.encode() + b"\x00"
                    # Catturato prima del ciclo: _recv_from muta il timeout
                    # del socket internamente (settimeout(remaining) a ogni
                    # giro), quindi rileggere sess.gettimeout() qui dentro
                    # darebbe un budget via via piu' piccolo a ogni tentativo
                    # invece del timeout pieno voluto.
                    ack_timeout = sess.gettimeout()
                    acked0 = False
                    for attempt in range(self.MAX_RETRIES):
                        sess.sendto(oack, addr)
                        try:
                            ack, ack_addr = self._recv_from(sess, addr[0], ack_timeout)
                        except socket.timeout:
                            continue
                        if len(ack) >= 4:
                            ack_op, ack_block = struct.unpack("!HH", ack[:4])
                            if ack_op == self.OPCODE_ACK and ack_block == 0:
                                acked0 = True
                                break
                            if ack_op == self.OPCODE_ERROR:
                                self._log(f"[tftp] il client ha rifiutato le "
                                          f"opzioni negoziate ({addr})")
                                return
                    if not acked0:
                        self._log(f"[tftp] nessun ACK all'OACK da {addr}: "
                                  f"riprovo con i parametri di default (senza opzioni)")
                        block_size = self.BLOCK_SIZE
                        sess.settimeout(self.TIMEOUT)

            if -(-total // block_size) > 65535:
                # Il client non ha negoziato opzioni (altrimenti saremmo
                # gia' passati dal ramo sopra): non c'e' modo RFC-legale di
                # imporre un blksize piu' grande senza il suo consenso. Da
                # qui in poi il conteggio blocchi avvolgera' e il
                # trasferimento corrompera' - segnalato chiaramente invece
                # di corrompersi in silenzio.
                self._log(
                    f"[tftp] ATTENZIONE: {total} byte a blksize={block_size} "
                    f"superano il limite di 65535 blocchi TFTP e il client "
                    f"non ha negoziato opzioni per blksize - il trasferimento "
                    f"probabilmente si corrompera' oltre il blocco 65535"
                )

            # Catturato una volta, non riletto da sess.gettimeout() dentro
            # al ciclo per lo stesso motivo dell'OACK sopra: _recv_from muta
            # il timeout del socket internamente.
            data_timeout = sess.gettimeout()
            block_num = 0
            sent = 0
            while True:
                block_num += 1
                chunk = content[sent:sent + block_size]
                sent += len(chunk)
                packet = struct.pack("!HH", self.OPCODE_DATA, block_num & 0xFFFF) + chunk

                acked = False
                for attempt in range(self.MAX_RETRIES):
                    sess.sendto(packet, addr)
                    try:
                        ack, ack_addr = self._recv_from(sess, addr[0], data_timeout)
                    except socket.timeout:
                        continue
                    if len(ack) >= 4:
                        ack_op, ack_block = struct.unpack("!HH", ack[:4])
                        if ack_op == self.OPCODE_ACK and ack_block == (block_num & 0xFFFF):
                            acked = True
                            break
                if not acked:
                    self._log(f"[tftp] trasferimento fallito verso {addr} "
                               f"(nessun ACK per il blocco {block_num})")
                    self._send_error(sess, addr, 0,
                                      f"timeout: nessun ACK per il blocco {block_num}")
                    return

                if len(chunk) < block_size:
                    self._log(f"[tftp] trasferimento completato verso {addr} "
                              f"({total} byte, {block_num} blocchi)")
                    return
        finally:
            sess.close()


def send_boot_trigger_burst(ser, char="b", count=10, interval=0.05, logger=None):
    """Invia `char` in raffica sulla seriale gia' aperta (`ser`), per innescare
    l'ingresso in BOOT-P (il router ha una finestra di accettazione stretta,
    un singolo invio spesso non basta).

    ATTENZIONE: deve restare una scrittura ASCII via ser.write() - MAI la
    send_break() di pyserial (un vero BREAK, dopo il boot di Linux, scatena
    una tempesta Magic-SysRq che uccide lo userspace: e' il bug storico che
    questo tool esiste per evitare)."""
    data = char.encode("ascii")
    for i in range(count):
        ser.write(data)
        if logger:
            logger.tx(char)
        time.sleep(interval)
