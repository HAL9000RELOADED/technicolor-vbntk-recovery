#!/usr/bin/env python3
"""uart_tool.py - CLI per interagire con una porta seriale UART.

Sottocomandi: ports, watch, monitor, send, shell, flash, profile list.
La logica condivisa con la GUI (uart_gui.py) sta in uart_core.py.
I profili di flash/bootloader sono definiti in profiles.json.
"""

import argparse
import os
import re
import subprocess
import sys
import threading
import time

try:
    import serial
except ImportError:
    print("Errore: pyserial non installato. Esegui: pip install -r requirements.txt")
    sys.exit(1)

# I byte grezzi dalla UART sono decodificati anche in latin-1 (default), che
# copre l'intero range 0x00-0xFF: la console Windows, a seconda della
# codepage attiva (es. cp1252), non sa rappresentare tutti quei caratteri e
# senza questo fix un singolo byte del genere in arrivo fa crashare la scrittura
# su stdout con UnicodeEncodeError. errors="replace" sostituisce con '?'
# invece di interrompere il log.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

import uart_core as core
import uart_netboot as netboot
from uart_core import UartLogger

BASE_DIR = core.get_base_dir()
DEFAULT_PROFILES = os.path.join(BASE_DIR, "profiles.json")
DEFAULT_LOG_DIR = os.path.join(BASE_DIR, "logs")


# ------------------------------------------------- helper CLI (errori -> exit)

def print_ports(ports, driver_info=None):
    for i, p in enumerate(ports, 1):
        print(f"  {i}) {p.device:<8} {p.description}  [{p.hwid}]")
        if driver_info is None:
            continue
        m = re.search(r"VID:PID=([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})",
                      p.hwid or "", re.IGNORECASE)
        info = None
        if m:
            key = f"{m.group(1).upper()}:{m.group(2).upper()}"
            info = driver_info.get(key)
        if info:
            name = info.get("name") or "?"
            provider = info.get("provider") or "?"
            version = info.get("version")
            version = f"v{version}" if version else "?"
            date = info.get("date") or "?"
            print(f"      driver: {name}  [{provider}, {version}, {date}]")
        else:
            print("      driver: (non determinato)")


def resolve_port(port):
    """Se port e' None, elenca le porte e chiede una selezione interattiva."""
    if port:
        return port
    ports = core.list_serial_ports()
    if not ports:
        print("Errore: nessuna porta seriale trovata.")
        sys.exit(1)
    if len(ports) == 1:
        print(f"[port] unica porta disponibile, uso {ports[0].device} "
              f"({ports[0].description})")
        return ports[0].device
    print("Porte seriali disponibili:")
    print_ports(ports)
    while True:
        try:
            choice = input("Seleziona porta (numero o nome, es. 1 o COM3): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nNessun input disponibile per la selezione della porta, "
                  "specifica --port.")
            sys.exit(1)
        if not choice:
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(ports):
            return ports[int(choice) - 1].device
        for p in ports:
            if choice.lower() == p.device.lower():
                return p.device
        print(f"Scelta non valida: {choice}")


def cli_port_conflict_prompt(resource, holders, auto_yes=False):
    """on_conflict per CLI: mostra chi occupa la porta/risorsa e chiede
    conferma prima di terminarlo. Questo tool ha la precedenza: se
    confermato, il processo occupante viene ucciso e l'operazione
    ritentata automaticamente. Con auto_yes conferma senza chiedere."""
    print(f"Risorsa {resource} occupata da:")
    for p in holders:
        print(f"  {core.describe_holder(p)}")
    if auto_yes:
        print(f"Terminare questi processi e riprovare su {resource}? (y/N): "
              f"y (auto, --yes)")
        return True
    try:
        answer = input(
            f"Terminare questi processi e riprovare su {resource}? (y/N): "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nNessun input disponibile, annullato.")
        return False
    return answer == "y"


def cli_open_port(port, baud, auto_yes=False, no_dtr=False):
    # no_dtr: apre la seriale senza asserire DTR/RTS (dtr=False, rts=False),
    # apertura non invasiva che non rischia di resettare la board via impulso
    # sulla linea di controllo - vedi core.open_port. Default False =
    # comportamento storico.
    dtr = False if no_dtr else None
    rts = False if no_dtr else None
    try:
        return core.open_port(
            port, baud, dtr=dtr, rts=rts,
            on_conflict=lambda r, h: cli_port_conflict_prompt(
                r, h, auto_yes=auto_yes))
    except serial.SerialException as e:
        print(f"Errore: impossibile aprire la porta {port}: {e}")
        holders = core.find_com_port_holders(port)
        if holders:
            print(f"Porta {port} occupata da:")
            for p in holders:
                print(f"  {core.describe_holder(p)}")
        avail = [p.device for p in core.list_serial_ports()]
        if avail:
            print("Porte disponibili: " + ", ".join(avail))
        else:
            print("Nessuna porta seriale rilevata.")
        sys.exit(1)


def _start_owner_hub(port, ser, logger):
    """Avvia un SerialHub sulla porta appena aperta cosi' altri processi
    (altre istanze CLI 'attach' o la GUI) possono agganciarsi alla stessa
    COM. Se la porta hub e' gia' occupata (HubPortBusy) logga un avviso e
    continua SENZA hub: il comando non deve fallire per questo."""
    hub = core.SerialHub(ser, port, on_event=logger.info)
    try:
        hub.start()
    except core.HubPortBusy:
        logger.info(f"[hub] porta hub gia' occupata, continuo senza "
                    f"condivisione per {port}")
        return None
    logger.info(f"[hub] altri processi possono agganciarsi: "
                f"uart_tool attach --port {port}")
    return hub


def _open_interactive(port, baud, auto_yes, no_dtr, encoding, logger, tag):
    """Prepara una sessione interattiva condivisa per monitor/shell.

    Decide owner-vs-attach:
      1) prova ad aprire la COM in proprio (OWNER) senza prompt/kill;
      2) se e' occupata da un'altra istanza che espone un hub, si aggancia
         come client (ATTACH) invece di proporre di uccidere l'altro processo;
      3) se non c'e' nessun hub (o l'errore non e' di tipo "occupata"),
         ricade sul comportamento storico di cli_open_port (prompt kill-holder).

    Ritorna un dict: {kind, reader, ser, hub}
      - kind 'owner': reader=core.Reader avviato, ser=serial.Serial,
        hub=core.SerialHub (o None se la porta hub era occupata);
      - kind 'attach': reader=core.AttachClient avviato, ser=None, hub=None.
    """
    on_text = logger.rx
    on_err = lambda e: logger.info(f"[{tag}] connessione persa: {e}")
    dtr = False if no_dtr else None
    rts = False if no_dtr else None

    ser = None
    try:
        # apertura diretta come owner, SENZA on_conflict: se la porta e'
        # occupata vogliamo intercettare noi il caso (per tentare l'attach),
        # non far partire subito il prompt di kill.
        ser = core.open_port(port, baud, dtr=dtr, rts=rts)
    except serial.SerialException as e:
        if core._port_busy_error(e):
            client = core.AttachClient(port, on_text, encoding=encoding,
                                       on_error=on_err)
            try:
                client.connect()
            except OSError:
                pass  # nessun hub in ascolto: si prosegue col fallback storico
            else:
                logger.info(f"[attach] {port} gia' in uso da un'altra istanza: "
                            f"mi aggancio all'hub")
                client.start()
                return {"kind": "attach", "reader": client,
                        "ser": None, "hub": None}
        # nessun hub o errore non-"occupata": comportamento storico (prompt
        # per terminare l'holder, messaggi diagnostici, exit su fallimento).
        ser = cli_open_port(port, baud, auto_yes=auto_yes, no_dtr=no_dtr)

    hub = _start_owner_hub(port, ser, logger)
    reader = core.Reader(ser, on_text, encoding=encoding, on_error=on_err,
                         on_bytes=(hub.broadcast if hub else None))
    reader.start()
    return {"kind": "owner", "reader": reader, "ser": ser, "hub": hub}


def cli_load_profiles(path):
    try:
        return core.load_profiles(path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Errore: {e}")
        sys.exit(1)


def maybe_launch_gui(args, logger):
    """Apre uart_gui.py/.exe in modalita' visualizzatore (--tail-log) sul
    file di log di questa sessione CLI, cosi' si vede live cosa succede
    sulla UART anche pilotando da riga di comando. Non apre la porta
    seriale in proprio (nessun conflitto con la CLI che la tiene aperta).
    Viene SEMPRE lanciata: non esiste un'opzione per disattivarla (scelta
    voluta - da CLI si deve comunque vedere la console live con il testo e
    cosa sta succedendo sulla UART).
    Best-effort: un fallimento non deve interrompere il comando CLI."""
    try:
        if getattr(sys, "frozen", False):
            gui_exe = os.path.join(BASE_DIR, "uart_gui.exe")
            if not os.path.isfile(gui_exe):
                return
            cmd = [gui_exe, "--tail-log", logger.path]
        else:
            gui_script = os.path.join(BASE_DIR, "uart_gui.py")
            if not os.path.isfile(gui_script):
                return
            python_exe = sys.executable
            pythonw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
            if os.path.isfile(pythonw):
                python_exe = pythonw
            cmd = [python_exe, gui_script, "--tail-log", logger.path]
        subprocess.Popen(cmd)
        logger.info(f"[gui] finestra di visualizzazione live avviata.")
    except Exception as e:
        logger.info(f"[gui] impossibile avviare la finestra live: {e}")


def cli_get_profile(profiles, name):
    try:
        return core.get_profile(profiles, name)
    except ValueError as e:
        print(f"Errore: {e}")
        sys.exit(1)


# ---------------------------------------------------------------- comandi

def cmd_ports(args):
    ports = core.list_serial_ports()
    if not ports:
        print("Errore: nessuna porta seriale trovata.")
        sys.exit(1)
    print("Porte seriali disponibili:")
    driver_info = core.windows_driver_info() if args.driver_info else None
    print_ports(ports, driver_info)


def cmd_watch(args):
    logger = UartLogger(args.log_dir)
    ports = core.list_serial_ports()
    if ports:
        logger.info("[watch] porte attuali: "
                    + ", ".join(f"{p.device} ({p.description})" for p in ports))
    else:
        logger.info("[watch] nessuna porta seriale al momento.")

    def on_event(event, device, description):
        verb = "collegata" if event == "added" else "rimossa"
        logger.info(f"[watch] {device} {verb} ({description})")

    watcher = core.PortWatcher(on_event)
    watcher.start()
    logger.info("[watch] in ascolto plug/unplug - Ctrl+C per uscire")
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        logger.close()


def cmd_monitor(args):
    args.port = resolve_port(args.port)
    logger = UartLogger(args.log_dir)
    maybe_launch_gui(args, logger)
    sess = _open_interactive(args.port, args.baud, args.auto_yes,
                             getattr(args, "no_dtr", False), args.encoding,
                             logger, "monitor")
    reader = sess["reader"]
    where = "hub condiviso" if sess["kind"] == "attach" else f"{args.baud}"
    logger.info(f"[monitor] {args.port} @ {where} - Ctrl+C per uscire")
    try:
        while True:
            if reader.error:
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
        if sess["hub"]:
            sess["hub"].stop()
        if sess["ser"]:
            sess["ser"].close()
        logger.close()


def _send_line(ser, logger, text):
    ser.write((text + "\n").encode("utf-8"))
    logger.tx(text)


def _decode_raw_cmd(text):
    """Interpreta escape stile Python in una stringa --cmd con --raw: \\r \\n
    \\t \\xNN e simili, cosi' si possono inviare caratteri di controllo
    (es. Ctrl-H = \\x08) senza il newline automatico di _send_line. Usa
    'unicode_escape' e poi ricodifica in latin-1 per ottenere i byte
    grezzi 0x00-0xFF corretti (unicode_escape produce str, non bytes)."""
    return text.encode("utf-8").decode("unicode_escape").encode("latin-1")


def cmd_send(args):
    if args.cmd is None and not args.break_signal:
        print("Errore: serve almeno --cmd o --break (altrimenti non c'e' "
              "nulla da inviare)")
        sys.exit(1)
    if args.repeat > 1 and not args.wait_for:
        print("Errore: --repeat richiede --wait-for (altrimenti non c'e' un "
              "evento su cui riarmare i cicli successivi)")
        sys.exit(1)
    args.port = resolve_port(args.port)
    logger = UartLogger(args.log_dir)
    maybe_launch_gui(args, logger)
    ser = cli_open_port(args.port, args.baud, auto_yes=args.auto_yes,
                        no_dtr=getattr(args, "no_dtr", False))
    hub = _start_owner_hub(args.port, ser, logger)

    # Stato del matcher/evento incapsulato in un dict cosi' can essere
    # sostituito (nuovo RxTailMatcher, nuovo Event) ad ogni ciclo di
    # --repeat senza dover fermare/riavviare il Reader - la porta resta
    # aperta per tutta la sequenza, niente riavvii manuali tra un
    # power-cycle del router e il successivo (motivazione: con --repeat=1
    # e potenza ciclata a mano, ogni riavvio COMPLETA con successo azzera
    # qualunque contatore di "boot falliti" lato bootloader/kernel - serve
    # invece essere gia' pronti a rispondere al prossimo "wait-for" nella
    # stessa sessione seriale, appena il router si ripresenta).
    state = {"matcher": core.RxTailMatcher(args.wait_for) if args.wait_for else None,
             "event": threading.Event() if args.wait_for else None}

    def on_rx(text):
        logger.rx(text)
        m = state["matcher"]
        ev = state["event"]
        if m is not None and not ev.is_set() and m.feed(text):
            ev.set()

    reader = core.Reader(
        ser, on_rx if args.wait_for else logger.rx, encoding=args.encoding,
        on_error=lambda e: logger.info(f"[send] connessione persa: {e}"),
        on_bytes=(hub.broadcast if hub else None))
    reader.start()
    try:
        for cycle in range(1, args.repeat + 1):
            if args.repeat > 1:
                logger.info(f"[send] ciclo {cycle}/{args.repeat}")
            if args.wait_for:
                logger.info(f"[send] in attesa di {args.wait_for!r} nella RX "
                            f"(timeout {args.wait_for_timeout}s)...")
                if not state["event"].wait(timeout=args.wait_for_timeout):
                    logger.info(f"[send] timeout: {args.wait_for!r} non visto "
                                f"entro {args.wait_for_timeout}s, procedo comunque")
                else:
                    logger.info(f"[send] pattern {args.wait_for!r} rilevato")
                if args.wait_for_delay > 0:
                    time.sleep(args.wait_for_delay)
            if args.break_signal:
                ser.send_break(duration=args.break_duration)
                logger.info(f"[send] BREAK seriale inviato "
                            f"({args.break_duration}s)")
                if args.break_delay > 0:
                    time.sleep(args.break_delay)
            if args.cmd is not None:
                if args.raw:
                    raw = _decode_raw_cmd(args.cmd)
                    ser.write(raw)
                    logger.tx(f"(raw) {raw!r}")
                else:
                    _send_line(ser, logger, args.cmd)
            time.sleep(args.wait)  # finestra per la risposta
            if cycle < args.repeat:
                # riarma per il prossimo ciclo: nuovo matcher/event puliti,
                # cosi' un match vecchio ancora nella coda del precedente
                # non fa scattare subito il ciclo successivo
                state["matcher"] = core.RxTailMatcher(args.wait_for)
                state["event"] = threading.Event()
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
        if hub:
            hub.stop()
        ser.close()
        logger.close()


def cmd_shell(args):
    args.port = resolve_port(args.port)
    logger = UartLogger(args.log_dir)
    maybe_launch_gui(args, logger)
    sess = _open_interactive(args.port, args.baud, args.auto_yes,
                             getattr(args, "no_dtr", False), args.encoding,
                             logger, "shell")
    reader = sess["reader"]
    ser = sess["ser"]
    where = "hub condiviso" if sess["kind"] == "attach" else f"{args.baud}"
    logger.info(f"[shell] {args.port} @ {where} - 'exit' o Ctrl+C per uscire")
    try:
        while True:
            if reader.error:
                logger.info("[shell] connessione persa, esco.")
                break
            line = input()
            if line.strip() == "exit":
                break
            if sess["kind"] == "owner":
                _send_line(ser, logger, line)
            else:
                # in attach il TX passa dall'hub verso l'owner
                reader.send(line + "\n")
                logger.tx(line)
            time.sleep(0.2)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        reader.stop()
        if sess["hub"]:
            sess["hub"].stop()
        if ser:
            ser.close()
        logger.close()


def cmd_attach(args):
    """Si aggancia a una COM gia' aperta da un'altra istanza (owner) tramite
    l'hub locale, comportandosi come 'shell': mostra live il flusso RX
    condiviso e invia in TX le righe da stdin. --baud e' ignorato (la porta
    fisica e' gia' aperta dall'owner al suo baud)."""
    args.port = resolve_port(args.port)
    logger = UartLogger(args.log_dir)
    maybe_launch_gui(args, logger)
    client = core.AttachClient(
        args.port, logger.rx, encoding=args.encoding,
        on_error=lambda e: logger.info(f"[attach] connessione persa: {e}"))
    try:
        client.connect()
    except OSError as e:
        print(f"Errore: nessun hub in ascolto per {args.port}. Apri prima "
              f"un'istanza owner (es. 'uart_tool monitor/shell --port {args.port}') "
              f"o la GUI su quella porta. Dettaglio: {e}")
        sys.exit(1)
    client.start()
    logger.info(f"[attach] agganciato all'hub di {args.port} - "
                f"'exit' o Ctrl+C per uscire")
    try:
        while True:
            if client.error:
                logger.info("[attach] hub chiuso, esco.")
                break
            line = input()
            if line.strip() == "exit":
                break
            client.send(line + "\n")
            logger.tx(line)
            time.sleep(0.2)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        client.stop()
        logger.close()


def cmd_flash(args):
    args.port = resolve_port(args.port)
    profiles = cli_load_profiles(args.profiles)
    profile = cli_get_profile(profiles, args.profile)

    try:
        flash_cmd = core.build_flash_cmd(profile, args.profile,
                                         args.port, args.baud, args.file)
    except (FileNotFoundError, ValueError) as e:
        print(f"Errore: {e}")
        sys.exit(1)

    # Riepilogo + conferma: tocca hardware reale, NON rimuovere.
    print("=" * 50)
    print("Riepilogo flash:")
    for label, value in core.flash_summary_fields(
            args.profile, args.file, args.port, args.baud,
            args.bootloader, flash_cmd):
        print(f"  {label:<10} : {value}")
    print("=" * 50)
    if args.auto_yes:
        print("Procedere? (y/N): y (auto, --yes)")
    else:
        try:
            answer = input("Procedere? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
            print()
        if answer != "y":
            print("Annullato.")
            return

    logger = UartLogger(args.log_dir)
    maybe_launch_gui(args, logger)
    try:
        if args.bootloader:
            core.enter_bootloader(profile, args.port, args.baud, logger)
        rc = core.run_flash(flash_cmd, logger)
        if rc != 0:
            sys.exit(rc)
    except serial.SerialException as e:
        logger.info(f"Errore porta seriale: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.info(f"Errore: {e}")
        sys.exit(1)
    except FileNotFoundError:
        logger.info("Errore: comando di flash non trovato (eseguibile non nel PATH?).")
        sys.exit(1)
    finally:
        logger.close()


def cmd_detect_baud(args):
    args.port = resolve_port(args.port)
    excl = f" (escludo il baud corrente {args.baud})" if args.baud else ""
    print(f"[detect-baud] scansione baud su {args.port}{excl}...")

    def progress(baud, ratio):
        if ratio is None:
            print(f"  {baud:>8}: porta non apribile")
        else:
            print(f"  {baud:>8}: {ratio * 100:5.1f}% stampabili")

    try:
        result = core.detect_baud(args.port, sample_time=args.sample_time,
                                  current_baud=args.baud, progress=progress)
    except serial.SerialException as e:
        print(f"Errore: impossibile usare la porta {args.port}: {e}")
        sys.exit(1)

    if result is None:
        print("Nessun candidato testabile (porta non apribile ad alcun baud).")
        sys.exit(1)
    print()
    if result.found:
        print(f"Baud rilevato: {result.baud} "
              f"({result.ratio * 100:.1f}% stampabili).")
    else:
        print(f"Nessun baud alternativo leggibile trovato "
              f"(migliore: {result.baud} a {result.ratio * 100:.1f}%).")
        print("Possibile problema di wiring TX/RX invertito o livelli "
              "elettrici, non di baud rate.")
        sys.exit(2)


def cmd_netboot(args):
    # Riepilogo + conferma: avvia un responder di rete reale (broadcast
    # sull'interfaccia scelta), NON rimuovere la conferma.
    print("=" * 50)
    print("Riepilogo boot di rete (BOOTP + TFTP):")
    print(f"  interfaccia : {args.iface}")
    print(f"  server IP   : {args.server_ip}")
    print(f"  offer IP    : {args.offer_ip}")
    print(f"  file        : {args.file}")
    print(f"  fallback    : {args.fallback_name}")
    if args.no_mac_filter:
        print("  filtro MAC  : DISATTIVO - rispondera' a QUALSIASI dispositivo!")
    elif args.router_mac:
        print(f"  filtro MAC  : {args.router_mac}")
    else:
        print(f"  filtro MAC  : rilevamento automatico via ARP su {args.router_ip}")
    if args.trigger_b:
        print(f"  trigger 'b' : SI, su porta {args.port or '(selezione interattiva)'}")
    else:
        print("  trigger 'b' : NO (solo responder di rete)")
    print("=" * 50)
    if args.auto_yes:
        print("Procedere? (y/N): y (auto, --yes)")
    else:
        try:
            answer = input("Procedere? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
            print()
        if answer != "y":
            print("Annullato.")
            return

    logger = UartLogger(args.log_dir)
    maybe_launch_gui(args, logger)
    responder = None
    tftp = None
    ser = None
    reader = None
    try:
        cache_dir = os.path.join(BASE_DIR, "netboot_cache")
        served_path = netboot.prepare_named_copy(args.file, args.fallback_name,
                                                  cache_dir)
        logger.info(f"[netboot] copia rinominata pronta: {served_path}")
        # bind_ip=server_ip: vincola il TFTP alla sola interfaccia scelta
        # (l'IP di questo PC su quella rete e' proprio server_ip), non a
        # 0.0.0.0/tutte le interfacce - vedi nota anti-leak in uart_netboot.py.
        tftp = netboot.TftpServer(served_path, bind_ip=args.server_ip, port=69,
                                   on_event=logger.info,
                                   on_conflict=lambda r, h: cli_port_conflict_prompt(
                                       r, h, auto_yes=args.auto_yes))
        tftp.start()

        served_name = {"value": args.fallback_name}

        def on_request(req_file, resolved_name):
            # il router annuncia da solo il nome che sta cercando: se e'
            # diverso da quello gia' servito, rifai la copia col nome giusto
            # invece di richiedere all'utente di indovinarlo in anticipo.
            if not req_file or resolved_name == served_name["value"]:
                return
            try:
                new_path = netboot.prepare_named_copy(args.file, resolved_name,
                                                       cache_dir)
            except netboot.NetbootError as e:
                logger.info(f"[netboot] errore aggiornando il nome file: {e}")
                return
            tftp.filepath = new_path
            served_name["value"] = resolved_name
            logger.info(f"[netboot] il router ha chiesto {resolved_name!r}: "
                       f"copia aggiornata automaticamente, servo {new_path}")

        router_mac = None if args.no_mac_filter else (args.router_mac.strip() if args.router_mac else None)
        if not args.no_mac_filter and not router_mac:
            logger.info(f"[netboot] rilevamento automatico MAC router via ARP "
                        f"su {args.router_ip} ({args.iface})...")
            try:
                router_mac = netboot.detect_router_mac(args.iface, args.router_ip)
            except netboot.NetbootError as e:
                logger.info(f"[netboot] ATTENZIONE: rilevamento MAC fallito: {e}")
            if router_mac:
                logger.info(f"[netboot] MAC rilevato: {router_mac}")
            else:
                logger.info(f"[netboot] ATTENZIONE: nessuna risposta ARP da "
                            f"{args.router_ip} - filtro MAC disattivato per questa "
                            f"sessione (usa --router-mac per impostarlo a mano, o "
                            f"--no-mac-filter per confermare esplicitamente).")
        responder = netboot.BootpResponder(
            args.iface, args.server_ip, args.offer_ip, args.fallback_name,
            on_event=logger.info, on_request=on_request, router_mac=router_mac,
        )
        responder.start()

        if args.trigger_b:
            args.port = resolve_port(args.port)
            ser = cli_open_port(args.port, args.baud, auto_yes=args.auto_yes)
            matcher = core.RxTailMatcher("Market ID")
            last_trigger = {"ts": 0.0}
            trigger_count = {"n": 0}
            # Mutabile (non una costante) cosi' il limite si puo' alzare/abbassare
            # mentre il processo gia' gira, senza doverlo riavviare - vedi
            # max_triggers_control_path sotto, riletto nel loop principale.
            max_triggers_state = {"n": max(1, args.max_triggers)}
            max_triggers_control_path = os.path.join(BASE_DIR, "netboot_max_triggers.txt")
            max_triggers_control_mtime = {"ts": 0.0}

            def refresh_max_triggers():
                """Rilegge netboot_max_triggers.txt se e' cambiato dall'ultima
                lettura, cosi' il tetto di tentativi automatici e' regolabile
                a processo gia' avviato (basta editare il file)."""
                try:
                    mtime = os.path.getmtime(max_triggers_control_path)
                except OSError:
                    return
                if mtime == max_triggers_control_mtime["ts"]:
                    return
                max_triggers_control_mtime["ts"] = mtime
                try:
                    with open(max_triggers_control_path, "r", encoding="utf-8") as f:
                        new_value = int(f.read().strip())
                except (OSError, ValueError):
                    logger.info(f"[netboot] netboot_max_triggers.txt illeggibile, "
                                f"ignorato")
                    return
                new_value = max(1, new_value)
                if new_value != max_triggers_state["n"]:
                    logger.info(f"[netboot] limite tentativi automatici "
                                f"aggiornato a runtime: {max_triggers_state['n']} "
                                f"-> {new_value}")
                    max_triggers_state["n"] = new_value

            def on_text(text):
                logger.rx(text)
                if not matcher.feed(text):
                    return
                # ri-armato con cooldown (stesso pattern della GUI, vedi
                # _check_netboot_trigger in uart_gui.py): un flag "sparato una
                # volta sola" lascerebbe il trigger morto per il resto del
                # processo se il router si riavvia di nuovo (es. TFTP fallito
                # e CFE torna al boot normale) - osservato dal vivo, 'Market
                # ID' e' ricomparso 3 volte dopo il primo trigger senza mai
                # far ripartire la raffica.
                now = time.time()
                if now - last_trigger["ts"] < 5:
                    return
                # Limite massimo: se il file viene rifiutato in modo
                # deterministico (es. "not a valid BLI"), il router si
                # riavvia da solo e ripropone "Market ID" - senza un tetto il
                # tool riflasherebbe lo stesso file all'infinito, osservato
                # dal vivo dopo l'introduzione del ri-armo qui sopra.
                if trigger_count["n"] >= max_triggers_state["n"]:
                    logger.info(
                        f"[netboot] limite di {max_triggers_state['n']} tentativi "
                        f"automatici raggiunto - trigger disattivato per "
                        f"evitare un loop infinito. Per continuare senza "
                        f"riavviare il comando, alza il limite scrivendo un "
                        f"numero piu' alto in "
                        f"{os.path.basename(max_triggers_control_path)}"
                    )
                    return
                trigger_count["n"] += 1
                last_trigger["ts"] = now
                logger.info(f"[netboot] 'Market ID' rilevato (tentativo "
                            f"{trigger_count['n']}/{max_triggers_state['n']}), "
                            f"invio raffica 'b'...")
                netboot.send_boot_trigger_burst(ser, logger=logger)
                logger.info("[netboot] raffica 'b' inviata.")

            reader = core.Reader(ser, on_text, encoding=args.encoding)
            reader.start()
            logger.info(f"[netboot] in ascolto su {args.port} @ {args.baud} "
                        f"per il trigger 'Market ID' - Ctrl+C per uscire")
        else:
            logger.info("[netboot] responder di rete attivo (nessun trigger seriale) "
                        "- Ctrl+C per uscire")

        while True:
            time.sleep(0.5)
            if args.trigger_b:
                refresh_max_triggers()
    except netboot.NetbootError as e:
        logger.info(f"Errore: {e}")
        sys.exit(1)
    except serial.SerialException as e:
        logger.info(f"Errore porta seriale: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    finally:
        if reader:
            reader.stop()
        if ser:
            ser.close()
        if responder:
            responder.stop()
        if tftp:
            tftp.stop()
        logger.close()


def cmd_profile_list(args):
    profiles = cli_load_profiles(args.profiles)
    print(f"Profili in {args.profiles}:")
    for name in sorted(profiles):
        p = profiles[name]
        bl = p.get("bootloader") or {}
        bl_desc = bl.get("method", "-")
        cmd = p.get("flash_cmd") or "(non configurato)"
        print(f"  {name:<10} bootloader={bl_desc:<8} flash_cmd={cmd}")
        desc = p.get("description")
        if desc:
            print(f"             {desc}")


# ---------------------------------------------------------------- main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="uart_tool",
        description="Tool CLI per monitor/comandi/flash su porta seriale UART.")
    parser.add_argument("--profiles", default=DEFAULT_PROFILES,
                        help="percorso del file profiles.json")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR,
                        help="cartella dei log (default: logs/)")

    sub = parser.add_subparsers(dest="command", required=True)

    def add_serial_args(p):
        p.add_argument("--port", default=None,
                       help="porta seriale (es. COM3); se omesso, "
                            "selezione interattiva tra le porte disponibili")
        p.add_argument("--baud", type=int, default=115200,
                       help="baudrate (default 115200)")

    def add_encoding_arg(p):
        p.add_argument("--encoding", choices=["latin-1", "utf-8", "ascii"],
                       default="latin-1",
                       help="encoding di decodifica RX (default latin-1: "
                            "mostra ogni byte grezzo senza mai fallire)")

    def add_yes_arg(p):
        p.add_argument("-y", "--yes", dest="auto_yes", action="store_true",
                       help="rispondi automaticamente 'si' a tutte le conferme "
                            "(conflitto porta, 'Procedere?'), utile per invocazioni "
                            "non interattive/scriptate")

    def add_no_dtr_arg(p):
        p.add_argument("--no-dtr", action="store_true",
                       help="apre la seriale SENZA asserire le linee DTR/RTS "
                            "(le tiene deasserite). Apertura non invasiva: su "
                            "board dove DTR/RTS e' cablato al reset (es. alcuni "
                            "router/modem) evita di resettare/riavviare il "
                            "dispositivo alla semplice apertura della porta. "
                            "Usalo per leggere una console gia' avviata che NON "
                            "deve andare offline.")

    p_ports = sub.add_parser("ports", help="elenca le porte seriali disponibili")
    p_ports.add_argument("-d", "--driver-info", action="store_true",
                         help="interroga anche Windows (WMI) per nome/provider/"
                              "versione/data del driver caricato per ogni porta "
                              "USB - piu' lento, query aggiuntiva")
    p_ports.set_defaults(func=cmd_ports)

    p_watch = sub.add_parser(
        "watch", help="rileva live plug/unplug delle porte (Ctrl+C per uscire)")
    p_watch.set_defaults(func=cmd_watch)

    p_mon = sub.add_parser("monitor", help="lettura/log continuo (Ctrl+C per uscire)")
    add_serial_args(p_mon)
    add_encoding_arg(p_mon)
    add_yes_arg(p_mon)
    add_no_dtr_arg(p_mon)
    p_mon.set_defaults(func=cmd_monitor)

    p_send = sub.add_parser("send", help="invia un comando e stampa la risposta")
    add_serial_args(p_send)
    add_encoding_arg(p_send)
    add_yes_arg(p_send)
    add_no_dtr_arg(p_send)
    p_send.add_argument("--cmd", default=None,
                        help="comando da inviare (non richiesto se usi solo "
                             "--break)")
    p_send.add_argument("--raw", action="store_true",
                        help="invia --cmd come byte grezzi SENZA newline "
                             "automatico, interpretando escape stile Python "
                             "(\\r \\n \\t \\xNN...) - utile per caratteri di "
                             "controllo tipo Ctrl-H (\\x08) o sequenze SysRq "
                             "che non vogliono un invio a capo dopo")
    p_send.add_argument("--break", dest="break_signal", action="store_true",
                        help="invia un segnale BREAK seriale vero (condizione "
                             "di linea RS-232, non un byte) prima di --cmd - "
                             "serve per alcuni meccanismi SysRq/bootfail dei "
                             "bootloader embedded")
    p_send.add_argument("--break-duration", type=float, default=0.25,
                        help="durata del BREAK in secondi (default 0.25)")
    p_send.add_argument("--break-delay", type=float, default=0.15,
                        help="pausa dopo il BREAK prima di inviare --cmd, in "
                             "secondi (default 0.15)")
    p_send.add_argument("--wait-for", default=None,
                        help="aspetta che questa stringa compaia nella RX "
                             "prima di inviare BREAK/--cmd (es. 'Linux "
                             "version' per aspettare l'avvio del kernel "
                             "prima di un trigger SysRq) - senza questo si "
                             "invia subito all'apertura della porta")
    p_send.add_argument("--wait-for-timeout", type=float, default=30.0,
                        help="timeout secondi per --wait-for, poi procede "
                             "comunque (default 30)")
    p_send.add_argument("--wait-for-delay", type=float, default=0.0,
                        help="pausa aggiuntiva dopo aver visto --wait-for, "
                             "prima di inviare BREAK/--cmd (default 0)")
    p_send.add_argument("--wait", type=float, default=2.0,
                        help="secondi di attesa risposta (default 2)")
    p_send.add_argument("--repeat", type=int, default=1,
                        help="ripeti l'intera sequenza wait-for+BREAK+cmd "
                             "N volte, riarmando automaticamente dopo ogni "
                             "ciclo SENZA chiudere/riaprire la porta - utile "
                             "per un trigger che serve su piu' riavvii "
                             "consecutivi (es. bootfail dopo N boot falliti) "
                             "senza dover rilanciare il comando a mano ad "
                             "ogni power-cycle. Richiede --wait-for "
                             "(default 1 = nessuna ripetizione)")
    p_send.set_defaults(func=cmd_send)

    p_shell = sub.add_parser("shell", help="REPL interattivo sulla UART")
    add_serial_args(p_shell)
    add_encoding_arg(p_shell)
    add_yes_arg(p_shell)
    add_no_dtr_arg(p_shell)
    p_shell.set_defaults(func=cmd_shell)

    p_attach = sub.add_parser(
        "attach",
        help="aggancia una COM gia' aperta da un'altra istanza (hub condiviso "
             "locale) e interagisci come 'shell'")
    add_serial_args(p_attach)  # --baud e' ignorato: la porta e' gia' aperta
    add_encoding_arg(p_attach)
    p_attach.set_defaults(func=cmd_attach)

    p_flash = sub.add_parser("flash", help="flasha un firmware secondo un profilo")
    add_serial_args(p_flash)
    add_yes_arg(p_flash)
    p_flash.add_argument("--profile", required=True,
                         help="nome del profilo (vedi 'profile list')")
    p_flash.add_argument("--file", required=True, help="file firmware da flashare")
    p_flash.add_argument("-b", "--bootloader", action="store_true",
                         help="esegui la sequenza di ingresso bootloader prima del flash")
    p_flash.set_defaults(func=cmd_flash)

    p_detect = sub.add_parser(
        "detect-baud",
        help="scansiona i baud comuni e rileva quello leggibile sulla porta")
    p_detect.add_argument("--port", default=None,
                          help="porta seriale (es. COM10); se omesso, "
                               "selezione interattiva")
    p_detect.add_argument("--baud", type=int, default=None,
                          help="baud corrente da escludere dalla scansione "
                               "(quello 'sbagliato'); se omesso, testa tutti")
    p_detect.add_argument("--sample-time", type=float, default=0.4,
                          help="secondi di lettura per candidato (default 0.4)")
    add_yes_arg(p_detect)
    p_detect.set_defaults(func=cmd_detect_baud)

    p_netboot = sub.add_parser(
        "netboot",
        help="boot di rete BOOTP+TFTP per recovery bootloader (es. Technicolor VBNT-K)")
    p_netboot.add_argument("--iface", required=True,
                           help="nome interfaccia di rete (es. 'Ethernet'); "
                                "OBBLIGATORIO, nessun default per evitare di "
                                "rispondere su un'interfaccia sbagliata")
    p_netboot.add_argument("--server-ip", required=True,
                           help="IP di questo PC da annunciare come server (siaddr)")
    p_netboot.add_argument("--offer-ip", required=True,
                           help="IP da offrire al router (yiaddr)")
    p_netboot.add_argument("--file", required=True,
                           help="file firmware da servire via TFTP")
    p_netboot.add_argument("--fallback-name", default="VBNT-K",
                           help="nome file di fallback se la BOOTREQUEST non "
                                "specifica un filename (default: VBNT-K)")
    p_netboot.add_argument("--router-mac", default=None,
                           help="MAC del router bersaglio: il responder risponde "
                                "SOLO a questo MAC. Se omesso (e senza "
                                "--no-mac-filter), viene rilevato automaticamente "
                                "via ARP su --router-ip prima di avviare il "
                                "responder. Su una LAN reale evita di offrire un "
                                "IP/boot file finto ad altri dispositivi. Usa "
                                "--no-mac-filter per disattivarlo esplicitamente.")
    p_netboot.add_argument("--router-ip", default="192.168.1.1",
                           help="IP a cui il router risponde normalmente (prima "
                                "di entrare in recovery), usato SOLO per il "
                                "rilevamento automatico del MAC via ARP quando "
                                "--router-mac e' omesso (default: 192.168.1.1)")
    p_netboot.add_argument("--no-mac-filter", action="store_true",
                           help="disattiva il filtro MAC: il responder rispondera' "
                                "a QUALSIASI dispositivo sull'interfaccia (utile solo "
                                "su un banco isolato o per altre board; reintroduce "
                                "il rischio di rispondere a terzi sulla LAN)")
    p_netboot.add_argument("--port", default=None,
                           help="porta seriale per il trigger 'b' automatico "
                                "(richiede --trigger-b)")
    p_netboot.add_argument("--baud", type=int, default=115200,
                           help="baudrate della porta seriale (default 115200)")
    add_encoding_arg(p_netboot)
    add_yes_arg(p_netboot)
    p_netboot.add_argument("--trigger-b", action="store_true",
                           help="apre la seriale e invia automaticamente una "
                                "raffica di 'b' quando rileva 'Market ID' nel "
                                "boot log; senza questo flag il tool avvia "
                                "solo il responder di rete (utile per i retry "
                                "automatici del bootloader)")
    p_netboot.add_argument("--max-triggers", type=int, default=5,
                           help="numero massimo di raffiche 'b' automatiche "
                                "prima di disattivare il trigger (default 5). "
                                "Regolabile anche a processo gia' avviato: "
                                "scrivi il nuovo valore nel file "
                                "netboot_max_triggers.txt nella cartella del "
                                "tool, viene riletto ogni ciclo.")
    p_netboot.set_defaults(func=cmd_netboot)

    p_prof = sub.add_parser("profile", help="gestione profili")
    prof_sub = p_prof.add_subparsers(dest="profile_command", required=True)
    p_list = prof_sub.add_parser("list", help="elenca i profili disponibili")
    p_list.set_defaults(func=cmd_profile_list)

    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
