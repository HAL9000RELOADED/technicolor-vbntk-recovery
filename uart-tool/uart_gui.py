#!/usr/bin/env python3
"""uart_gui.py - GUI desktop (Tkinter) per il tool UART.

Avvio: python uart_gui.py
Copre le stesse funzionalita' della CLI: selezione porta (con hotplug live),
monitor RX, invio comandi, flash con profili/bootloader e conferma.
Riusa la logica condivisa di uart_core.py; log su file come la CLI.
"""

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import serial
except ImportError:
    print("Errore: pyserial non installato. Esegui: pip install -r requirements.txt")
    sys.exit(1)

import uart_core as core
import uart_netboot as netboot

BASE_DIR = core.get_base_dir()
PROFILES_PATH = os.path.join(BASE_DIR, "profiles.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
NETBOOT_CACHE_DIR = os.path.join(BASE_DIR, "netboot_cache")

ENCODINGS = {
    "Latin-1": "latin-1",
    "UTF-8": "utf-8",
    "ASCII": "ascii",
}

# --- parametri auto-rilevamento baud
AUTO_CHECK_INTERVAL_MS = 1000   # ogni quanto valutare l'euristica
AUTO_BAD_STREAK_NEEDED = 3      # campioni "cattivi" consecutivi prima di scattare
AUTO_MIN_SAMPLE = 200          # byte minimi nel buffer per valutare
AUTO_COOLDOWN_S = 20           # attesa minima tra due scansioni automatiche
AUTO_MAX_FAILS = 3             # scansioni auto fallite di fila -> stop auto

THEMES = {
    "Chiaro": {
        "bg": "SystemButtonFace",
        "fg": "SystemWindowText",
        "console_bg": "white",
        "console_fg": "black",
        "console_insert_bg": "black",
    },
    "Scuro": {
        "bg": "#2b2b2b",
        "fg": "#e0e0e0",
        "console_bg": "#1e1e1e",
        "console_fg": "#e0e0e0",
        "console_insert_bg": "#e0e0e0",
    },
}


class UartGuiApp:
    def __init__(self, root):
        self.root = root
        root.title("UART Tool")
        root.minsize(900, 480)

        self.ser = None
        self.reader = None
        # hub: SerialHub attivo quando la GUI e' OWNER della porta (condivide
        # la COM con eventuali client 'attach'). attach_client: AttachClient
        # attivo quando la porta e' gia' in mano a un'altra istanza e la GUI
        # si e' agganciata al suo hub invece di aprire la COM in proprio.
        self.hub = None
        self.attach_client = None
        self.flash_running = False
        # stato rilevamento baud
        self.detecting = False
        self._auto_bad_streak = 0
        self._auto_fail_count = 0
        self._last_auto_scan = 0.0
        self._auto_last_rx_count = 0
        self.ui_queue = queue.Queue()
        self.port_map = {}  # label visualizzata ("COM10 - desc") -> device ("COM10")

        # stato boot di rete (BOOTP+TFTP)
        self.netboot_responder = None
        self.netboot_tftp = None
        self.netboot_available = False
        self._netboot_served_name = None
        self._netboot_matcher = core.RxTailMatcher("Market ID")
        self._netboot_last_trigger = 0.0
        self._netboot_trigger_count = 0
        self.NETBOOT_MAX_AUTO_TRIGGERS = 5
        self.netboot_attempts_var = tk.StringVar(
            value=f"Tentativi BOOTP: 0/{self.NETBOOT_MAX_AUTO_TRIGGERS}")

        # Logger: l'echo a schermo passa dalla queue (thread-safe verso Tk)
        self.logger = core.UartLogger(LOG_DIR, echo=self._echo)

        try:
            self.profiles = core.load_profiles(PROFILES_PATH)
        except (FileNotFoundError, ValueError) as e:
            self.profiles = {}
            self.logger.info(f"Errore profili: {e}")

        self._build_ui()
        self.refresh_ports()

        self.watcher = core.PortWatcher(self._on_port_event)
        self.watcher.start()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_queue()
        self.root.after(AUTO_CHECK_INTERVAL_MS, self._auto_detect_tick)
        self._tail_stop = None
        self._tail_mode = False
        self._bring_to_foreground()

    def _bring_to_foreground(self):
        """Forza la finestra in primo piano e visibile. Serve soprattutto
        quando il tool viene aperto da un altro processo (es. l'apertura
        automatica della GUI dalla CLI, vedi maybe_launch_gui in
        uart_tool.py): Windows di norma non da' il fuoco alla finestra di
        un'app avviata in background, lasciandola nascosta dietro al
        terminale/processo che l'ha lanciata - l'utente deve poter vedere
        subito cosa succede sulla console senza dover cercare la finestra."""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(150, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ tail mode

    def start_tail(self, path):
        """Modalita' visualizzatore: segue in tempo reale il file di log
        scritto da un'altra istanza (es. la CLI lanciata da un altro
        processo/sessione) senza aprire la porta seriale in proprio -
        evita conflitti, la porta resta in mano a chi l'ha aperta per primo.
        La finestra e' sola-lettura: i controlli che aprirebbero la porta,
        avvierebbero un flash o il responder di rete sono disabilitati
        (vedi _disable_controls_for_tail)."""
        self.logger.info(f"[tail] visualizzo in tempo reale: {path}")
        self.set_status(f"Modalita' tail (sola lettura): {path}")
        self._tail_mode = True
        self._disable_controls_for_tail()
        self._bring_to_foreground()
        self._tail_stop = threading.Event()

        def worker():
            for _ in range(50):  # attende che il file esista (max ~5s)
                if os.path.isfile(path) or self._tail_stop.is_set():
                    break
                time.sleep(0.1)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    while not self._tail_stop.is_set():
                        line = f.readline()
                        if line:
                            self.ui_queue.put(("console", line))
                        else:
                            time.sleep(0.2)
            except Exception as e:
                self.ui_queue.put(("console", f"[tail] errore: {e}\n"))

        threading.Thread(target=worker, daemon=True).start()

    def _disable_controls_for_tail(self):
        """Modalita' tail = sola visualizzazione: disabilita ogni controllo che
        potrebbe aprire la porta seriale, avviare un flash o avviare il
        responder di rete. La finestra tail e' documentata come display-only
        (README): resta attivo solo il tailing del log."""
        for widget in (self.connect_btn, self.detect_btn, self.auto_detect_chk,
                       self.cmd_entry, self.send_btn, self.flash_btn,
                       self.netboot_start_btn, self.netboot_rearm_btn):
            try:
                widget.config(state="disabled")
            except tk.TclError:
                pass

    # ------------------------------------------------------------ UI

    def _build_ui(self):
        pad = {"padx": 4, "pady": 3}

        # --- riga connessione
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Porta:").pack(side="left")
        self.port_var = tk.StringVar()
        # La listbox del popup segue di norma la width della Combobox su
        # Windows, ma forziamola comunque perche' non risulti mai piu'
        # stretta della entry (label tipiche: "COM10 - Prolific USB-to-
        # -Serial Comm Port" ~42 caratteri).
        self.root.option_add('*TCombobox*Listbox.width', 60)
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var,
                                       width=60, state="readonly")
        self.port_combo.pack(side="left", padx=4)
        ttk.Button(top, text="Aggiorna", command=self.refresh_ports).pack(side="left")
        ttk.Label(top, text="Baud:").pack(side="left", padx=(12, 0))
        self.baud_var = tk.StringVar(value="115200")
        ttk.Entry(top, textvariable=self.baud_var, width=8).pack(side="left", padx=4)
        ttk.Label(top, text="Encoding:").pack(side="left", padx=(12, 0))
        self.encoding_var = tk.StringVar(value="Latin-1")
        self.encoding_combo = ttk.Combobox(top, textvariable=self.encoding_var,
                                           values=list(ENCODINGS.keys()), width=8,
                                           state="readonly")
        self.encoding_combo.pack(side="left", padx=4)
        self.encoding_combo.bind("<<ComboboxSelected>>", self._on_encoding_change)
        self.connect_btn = ttk.Button(top, text="Connetti",
                                      command=self.toggle_connect)
        self.connect_btn.pack(side="left", padx=8)
        ttk.Label(top, text="Tema:").pack(side="left", padx=(12, 0))
        self.theme_var = tk.StringVar(value="Chiaro")
        self.theme_combo = ttk.Combobox(top, textvariable=self.theme_var,
                                        values=list(THEMES.keys()), width=8,
                                        state="readonly")
        self.theme_combo.pack(side="left", padx=4)
        self.theme_combo.bind("<<ComboboxSelected>>", self._on_theme_change)

        # --- riga rilevamento baud
        det = ttk.Frame(self.root)
        det.pack(fill="x", **pad)
        self.detect_btn = ttk.Button(det, text="Rileva baud",
                                     command=self.detect_baud_manual)
        self.detect_btn.pack(side="left")
        self.auto_detect_var = tk.BooleanVar(value=False)
        self.auto_detect_chk = ttk.Checkbutton(
            det, text="Rileva baud automaticamente",
            variable=self.auto_detect_var,
            command=self._on_auto_detect_toggle)
        self.auto_detect_chk.pack(side="left", padx=12)

        # --- console log
        console_row = ttk.Frame(self.root)
        console_row.pack(fill="both", expand=True, **pad)
        self.autoscroll_enabled = True  # flag controllato dal checkbox sotto
        self.lock_scroll_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(console_row, text="Blocca scorrimento",
                        variable=self.lock_scroll_var,
                        command=self._on_lock_scroll_change).pack(
            side="top", anchor="w")
        # Text + scrollbar verticale (sempre visibile) e orizzontale (si
        # mostra solo quando una riga e' piu' larga della finestra, si
        # nasconde da sola altrimenti - via il classico trucco xscrollcommand
        # che chiama grid_remove()/grid() in base al range visibile).
        console_holder = ttk.Frame(console_row)
        console_holder.pack(fill="both", expand=True)
        console_holder.rowconfigure(0, weight=1)
        console_holder.columnconfigure(0, weight=1)
        self.console = tk.Text(console_holder, height=16, state="disabled",
                               font=("Consolas", 9), wrap="none")
        self.console.grid(row=0, column=0, sticky="nsew")
        console_vbar = ttk.Scrollbar(console_holder, orient="vertical",
                                     command=self.console.yview)
        console_vbar.grid(row=0, column=1, sticky="ns")
        console_hbar = ttk.Scrollbar(console_holder, orient="horizontal",
                                     command=self.console.xview)
        console_hbar.grid(row=1, column=0, sticky="ew")

        def _hbar_autohide_set(lo, hi):
            if float(lo) <= 0.0 and float(hi) >= 1.0:
                console_hbar.grid_remove()
            else:
                console_hbar.grid()
            console_hbar.set(lo, hi)

        self.console.config(yscrollcommand=console_vbar.set,
                            xscrollcommand=_hbar_autohide_set)
        # Modalita' terminale: click sulla console per darle il focus, poi
        # ogni tasto premuto va DIRETTAMENTE sulla seriale, senza passare
        # dal campo Comando/Invia (comodo per interagire live con CFE o
        # una shell, non solo per inviare comandi a riga intera).
        self.console.bind("<Key>", self._on_console_keypress)
        self.console.bind("<Button-1>", lambda e: self.console.focus_set())

        # --- riga invio comandi
        send_row = ttk.Frame(self.root)
        send_row.pack(fill="x", **pad)
        ttk.Label(send_row, text="Comando:").pack(side="left")
        self.cmd_var = tk.StringVar()
        self.cmd_entry = ttk.Entry(send_row, textvariable=self.cmd_var)
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.cmd_entry.bind("<Return>", lambda e: self.send_command())
        self.send_btn = ttk.Button(send_row, text="Invia", command=self.send_command)
        self.send_btn.pack(side="left")

        # --- sezione flash
        flash_frame = ttk.LabelFrame(self.root, text="Flash firmware")
        flash_frame.pack(fill="x", **pad)
        row = ttk.Frame(flash_frame)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Profilo:").pack(side="left")
        self.profile_var = tk.StringVar()
        names = sorted(self.profiles)
        self.profile_combo = ttk.Combobox(row, textvariable=self.profile_var,
                                          values=names, width=12, state="readonly")
        if names:
            self.profile_combo.set(names[0])
        self.profile_combo.pack(side="left", padx=4)
        self.profile_combo.bind("<<ComboboxSelected>>",
                                self._update_profile_desc)
        ttk.Label(row, text="File:").pack(side="left", padx=(12, 0))
        self.file_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.file_var).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Sfoglia...", command=self.pick_file).pack(side="left")
        self.profile_desc_var = tk.StringVar()
        ttk.Label(flash_frame, textvariable=self.profile_desc_var,
                  wraplength=620, foreground="gray30").pack(
            fill="x", anchor="w", **pad)
        self._update_profile_desc()
        row2 = ttk.Frame(flash_frame)
        row2.pack(fill="x", **pad)
        self.bootloader_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="Entra in bootloader prima del flash",
                        variable=self.bootloader_var).pack(side="left")
        self.flash_btn = ttk.Button(row2, text="Flash", command=self.start_flash)
        self.flash_btn.pack(side="right")

        # --- sezione boot di rete (BOOTP+TFTP)
        netboot_frame = ttk.LabelFrame(self.root, text="Boot di rete BOOTP+TFTP (VBNT-K)")
        netboot_frame.pack(fill="x", **pad)

        nrow1 = ttk.Frame(netboot_frame)
        nrow1.pack(fill="x", **pad)
        ttk.Label(nrow1, text="Interfaccia:").pack(side="left")
        self.netboot_iface_var = tk.StringVar()
        # Larga abbastanza da non troncare nomi tipici Windows tipo
        # "Local Area Connection* 1" / "OpenVPN Data Channel Offload"; la
        # listbox del popup eredita gia' *TCombobox*Listbox.width=60 impostato
        # sopra per la Porta, quindi non tronca neanche lei.
        self.netboot_iface_combo = ttk.Combobox(nrow1, textvariable=self.netboot_iface_var,
                                                 width=45, state="readonly")
        self.netboot_iface_combo.pack(side="left", padx=4)
        ttk.Label(nrow1, text="Server IP:").pack(side="left", padx=(12, 0))
        self.netboot_server_ip_var = tk.StringVar(value="192.168.1.2")
        ttk.Entry(nrow1, textvariable=self.netboot_server_ip_var, width=14).pack(
            side="left", padx=4)
        ttk.Label(nrow1, text="Offer IP:").pack(side="left", padx=(12, 0))
        self.netboot_offer_ip_var = tk.StringVar(value="192.168.1.50")
        ttk.Entry(nrow1, textvariable=self.netboot_offer_ip_var, width=14).pack(
            side="left", padx=4)
        ttk.Label(nrow1, text="Fallback:").pack(side="left", padx=(12, 0))
        self.netboot_fallback_var = tk.StringVar(value="VBNT-K")
        ttk.Entry(nrow1, textvariable=self.netboot_fallback_var, width=10).pack(
            side="left", padx=4)

        nrow_mac = ttk.Frame(netboot_frame)
        nrow_mac.pack(fill="x", **pad)
        self.netboot_mac_filter_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(nrow_mac, text="Filtra per MAC router",
                        variable=self.netboot_mac_filter_var).pack(side="left")
        ttk.Label(nrow_mac, text="MAC router:").pack(side="left", padx=(12, 0))
        # Vuoto di default: rilevato via ARP (bottone "Rileva") invece di un
        # MAC hardcoded, che varia da device a device e non ha senso come
        # default fisso - vedi netboot.detect_router_mac in uart_netboot.py.
        self.netboot_mac_var = tk.StringVar(value="")
        ttk.Entry(nrow_mac, textvariable=self.netboot_mac_var, width=20).pack(
            side="left", padx=4)
        ttk.Label(nrow_mac, text="Router IP (per rilevamento):").pack(side="left", padx=(12, 0))
        self.netboot_router_ip_var = tk.StringVar(value="192.168.1.1")
        ttk.Entry(nrow_mac, textvariable=self.netboot_router_ip_var, width=14).pack(
            side="left", padx=4)
        ttk.Button(nrow_mac, text="Rileva", command=self.detect_netboot_mac).pack(
            side="left", padx=4)

        nrow2 = ttk.Frame(netboot_frame)
        nrow2.pack(fill="x", **pad)
        ttk.Label(nrow2, text="File:").pack(side="left")
        self.netboot_file_var = tk.StringVar()
        ttk.Entry(nrow2, textvariable=self.netboot_file_var).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(nrow2, text="Sfoglia...", command=self.pick_netboot_file).pack(side="left")

        nrow3 = ttk.Frame(netboot_frame)
        nrow3.pack(fill="x", **pad)
        self.netboot_trigger_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(nrow3, text="Trigger automatico 'b' su 'Market ID'",
                        variable=self.netboot_trigger_var).pack(side="left")
        ttk.Label(nrow3, textvariable=self.netboot_attempts_var,
                  foreground="gray30").pack(side="left", padx=(12, 0))
        self.netboot_rearm_btn = ttk.Button(nrow3, text="Riarma trigger",
                                            command=self.rearm_netboot_trigger)
        self.netboot_rearm_btn.pack(side="left", padx=(12, 0))
        self.netboot_start_btn = ttk.Button(nrow3, text="Avvia responder rete",
                                            command=self.start_netboot_responder)
        self.netboot_start_btn.pack(side="right", padx=4)
        self.netboot_stop_btn = ttk.Button(nrow3, text="Ferma responder rete",
                                           command=self.stop_netboot_responder,
                                           state="disabled")
        self.netboot_stop_btn.pack(side="right")

        self.netboot_status_var = tk.StringVar()
        ttk.Label(netboot_frame, textvariable=self.netboot_status_var,
                  wraplength=620, foreground="gray30").pack(
            fill="x", anchor="w", **pad)
        self._init_netboot_ifaces()

        # --- status bar
        self.status_var = tk.StringVar(value="Pronto")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken",
                  anchor="w").pack(fill="x", side="bottom")

        self._apply_theme(self.theme_var.get())

    # ------------------------------------------------------------ tema

    def _on_theme_change(self, event=None):
        self._apply_theme(self.theme_var.get())

    def _apply_theme(self, name):
        theme = THEMES.get(name, THEMES["Chiaro"])

        # widget ttk: uno style condiviso (unica finestra dell'app)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        for widget in ("TFrame", "TLabel", "TLabelframe", "TCheckbutton"):
            style.configure(widget, background=theme["bg"], foreground=theme["fg"])
        style.configure("TLabelframe.Label", background=theme["bg"],
                        foreground=theme["fg"])
        style.configure("TButton", background=theme["bg"], foreground=theme["fg"])
        style.configure("TCombobox", fieldbackground=theme["console_bg"],
                        foreground=theme["console_fg"])
        style.configure("TEntry", fieldbackground=theme["console_bg"],
                        foreground=theme["console_fg"])
        style.map("TCombobox", fieldbackground=[("readonly", theme["console_bg"])])

        self.root.configure(bg=theme["bg"])

        # console log: il widget lamentato dall'utente, sfondo bianco fisso
        self.console.config(bg=theme["console_bg"], fg=theme["console_fg"],
                            insertbackground=theme["console_insert_bg"])

    # ------------------------------------------------------------ echo/queue

    def _echo(self, text):
        """Chiamato dal logger (anche da altri thread): rimbalza sulla queue."""
        self.ui_queue.put(("console", text))

    def _on_port_event(self, event, device, description):
        self.ui_queue.put(("port_event", event, device, description))

    def _poll_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                if item[0] == "console":
                    self._console_append(item[1])
                elif item[0] == "port_event":
                    _, event, device, description = item
                    verb = "collegata" if event == "added" else "rimossa"
                    self.set_status(f"{device} {verb}")
                    self.logger.info(f"[watch] {device} {verb} ({description})")
                    self.refresh_ports()
                elif item[0] == "flash_done":
                    self.flash_running = False
                    self.flash_btn.config(state="normal")
                    self.detect_btn.config(state="normal")
                    if self.netboot_available and not self.netboot_responder:
                        self.netboot_start_btn.config(state="normal")
                elif item[0] == "detect_done":
                    _, port, orig_baud, result, err, auto = item
                    self._on_detect_done(port, orig_baud, result, err, auto)
                elif item[0] == "netboot_request":
                    _, req_file, resolved_name = item
                    self._handle_netboot_request(req_file, resolved_name)
                elif item[0] == "conn_lost":
                    self._handle_conn_lost(item[1])
                elif item[0] == "netboot_attempts":
                    self.netboot_attempts_var.set(
                        f"Tentativi BOOTP: {item[1]}/{self.NETBOOT_MAX_AUTO_TRIGGERS}")
                elif item[0] == "status":
                    self.set_status(item[1])
                elif item[0] == "netboot_mac_detected":
                    _, mac = item
                    if mac:
                        self.netboot_mac_var.set(mac)
                        self.set_status(f"MAC rilevato: {mac}")
                    else:
                        self.set_status("Rilevamento MAC: nessuna risposta ARP")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _console_append(self, text):
        self.console.config(state="normal")
        self.console.insert("end", text)
        if self.autoscroll_enabled:
            self.console.see("end")
        self.console.config(state="disabled")

    def _on_lock_scroll_change(self):
        self.autoscroll_enabled = not self.lock_scroll_var.get()
        if self.autoscroll_enabled:
            # sblocco: torna subito in fondo e riprende lo scroll automatico
            self.console.see("end")

    def set_status(self, text):
        self.status_var.set(text)

    # ------------------------------------------------------------ porte

    def _selected_device(self):
        """Estrae il device reale (es. COM10) dalla label selezionata."""
        sel = self.port_var.get()
        if not sel:
            return None
        return self.port_map.get(sel, sel.split(" - ")[0])

    def refresh_ports(self):
        current_dev = self._selected_device()
        self.port_map = {}
        labels = []
        for p in core.list_serial_ports():
            label = f"{p.device} - {p.description}"
            self.port_map[label] = p.device
            labels.append(label)
        self.port_combo["values"] = labels
        # se la porta attualmente connessa e' sparita dall'elenco, il reader
        # e' morto (o sta per morire): porta la GUI in stato disconnesso invece
        # di mostrare ancora "Connesso" con un thread di lettura defunto.
        if self.ser and self.ser.port not in self.port_map.values():
            gone = self.ser.port
            self.disconnect()
            self.set_status(f"{gone} scomparsa: disconnesso")
            self.port_combo.set(labels[0] if labels else "")
            return
        # mantieni la selezione se la porta e' ancora presente
        for label, dev in self.port_map.items():
            if dev == current_dev:
                self.port_combo.set(label)
                return
        if not self.ser:
            self.port_combo.set(labels[0] if labels else "")

    def _update_profile_desc(self, event=None):
        name = self.profile_var.get()
        profile = self.profiles.get(name, {})
        self.profile_desc_var.set(
            profile.get("description") or "Nessuna descrizione disponibile")

    def _get_baud(self):
        try:
            return int(self.baud_var.get())
        except ValueError:
            raise ValueError(f"baudrate non valido: {self.baud_var.get()!r}")

    def _get_encoding(self):
        return ENCODINGS.get(self.encoding_var.get(), "latin-1")

    def _on_encoding_change(self, event=None):
        # se un reader e' gia' attivo, aggiorna l'encoding a runtime;
        # altrimenti la scelta verra' usata alla prossima connessione
        # (letta da self.encoding_var al momento della creazione del Reader).
        if self.reader:
            self.reader.encoding = self._get_encoding()

    # ------------------------------------------------------------ connessione

    def _gui_port_conflict(self, resource, holders):
        """on_conflict per la GUI: mostra chi occupa la porta/risorsa e
        chiede conferma prima di terminarlo. Questo tool ha la precedenza:
        se confermato, il processo occupante viene ucciso e l'operazione
        ritentata automaticamente."""
        lines = "\n".join(f"  {core.describe_holder(p)}" for p in holders)
        return messagebox.askyesno(
            "Porta occupata",
            f"Risorsa {resource} occupata da:\n\n{lines}\n\n"
            "Terminare questi processi e riprovare?",
            icon="warning")

    def _start_gui_hub(self, port):
        """Avvia un SerialHub sulla porta appena aperta (GUI owner) cosi' una
        CLI 'attach' puo' vedere/pilotare la porta della GUI. Se la porta hub
        e' occupata (HubPortBusy) la condivisione resta disattiva ma la
        connessione locale prosegue normalmente."""
        hub = core.SerialHub(self.ser, port, on_event=self.logger.info)
        try:
            hub.start()
        except core.HubPortBusy:
            self.logger.info("[hub] porta hub occupata, condivisione non attiva")
            return None
        self.logger.info(f"[hub] altri processi possono agganciarsi: "
                         f"uart_tool attach --port {port}")
        return hub

    def _try_attach(self, port):
        """Se un'altra istanza tiene gia' la porta ed espone un hub, aggancia
        la GUI come client (stream condiviso + TX). Ritorna True se agganciata."""
        client = core.AttachClient(port, self._on_rx_text,
                                   encoding=self._get_encoding(),
                                   on_error=self._on_reader_error)
        try:
            client.connect()
        except OSError:
            return False
        client.start()
        self.attach_client = client
        self.connect_btn.config(text="Disconnetti")
        self.logger.info(f"[attach] {port} gia' in uso: agganciato all'hub "
                         f"condiviso")
        self.set_status(f"Agganciato all'hub di {port}")
        return True

    def toggle_connect(self):
        if self.ser or self.attach_client:
            self.disconnect()
            return
        port = self._selected_device()
        if not port:
            self.set_status("Nessuna porta selezionata")
            return
        try:
            baud = self._get_baud()
        except ValueError as e:
            self.logger.info(f"Errore connessione: {e}")
            self.set_status("Errore connessione")
            return
        # 1) prova ad aprire la COM in proprio (owner), SENZA prompt/kill.
        try:
            self.ser = core.open_port(port, baud)
        except serial.SerialException as e:
            # 2) se e' occupata da un'altra istanza con hub, aggancia come client.
            if core._port_busy_error(e) and self._try_attach(port):
                return
            # 3) altrimenti comportamento storico: prompt per terminare l'holder.
            try:
                self.ser = core.open_port(port, baud,
                                          on_conflict=self._gui_port_conflict)
            except (serial.SerialException, ValueError) as e2:
                self.logger.info(f"Errore connessione: {e2}")
                self.set_status("Errore connessione")
                self.ser = None
                return
        # OWNER: avvia hub di condivisione, poi il reader che gli inoltra i byte.
        self.hub = self._start_gui_hub(port)
        self.reader = core.Reader(self.ser, self._on_rx_text,
                                  encoding=self._get_encoding(),
                                  on_error=self._on_reader_error,
                                  on_bytes=(self.hub.broadcast if self.hub
                                            else None))
        self.reader.start()
        self.connect_btn.config(text="Disconnetti")
        self.logger.info(f"[gui] connesso a {port} @ {baud}")
        self.set_status(f"Connesso a {port} @ {baud}")

    def _on_reader_error(self, exc):
        """on_error del Reader (invocato dal thread di lettura): rimbalza sulla
        queue perche' la transizione di stato UI avvenga nel thread Tk."""
        self.ui_queue.put(("conn_lost", str(exc)))

    def _handle_conn_lost(self, msg):
        """La seriale e' morta sotto il reader (cavo staccato, porta sparita):
        porta la GUI in stato disconnesso invece di restare su 'Connesso' con
        un reader morto."""
        if not self.ser and not self.reader and not self.attach_client:
            return
        self.logger.info(f"[gui] connessione persa: {msg}")
        self.disconnect()
        self.set_status("Connessione persa")

    def disconnect(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
        if self.attach_client:
            try:
                self.attach_client.stop()
            except Exception:
                pass
            self.attach_client = None
            self.logger.info("[attach] sganciato dall'hub")
        if self.hub:
            try:
                self.hub.stop()
            except Exception:
                pass
            self.hub = None
        if self.ser:
            port = self.ser.port
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            self.logger.info(f"[gui] disconnesso da {port}")
        self.connect_btn.config(text="Connetti")
        self.set_status("Disconnesso")

    # ------------------------------------------------------------ boot di rete

    def _init_netboot_ifaces(self):
        try:
            ifaces = netboot.list_interfaces()
        except netboot.NetbootError as e:
            self.netboot_available = False
            self.netboot_iface_combo["values"] = []
            self.netboot_status_var.set(f"Non disponibile: {e}")
            self.netboot_start_btn.config(state="disabled")
            self.netboot_iface_combo.config(state="disabled")
            return
        self.netboot_available = True
        self.netboot_iface_combo["values"] = ifaces
        # Il solo *TCombobox*Listbox.width in option database non basta a
        # evitare il troncamento nel popdown su Windows (dipende dalla
        # patch level di Tk, e qui i nomi interfaccia tipo "Microsoft
        # IP-HTTPS Platform Adapter" restavano tagliati). Fix affidabile:
        # allargare la Combobox stessa in base al nome piu' lungo, cosi'
        # sia il campo che il popdown (che segue la larghezza reale del
        # widget) mostrano tutto per intero.
        if ifaces:
            self.netboot_iface_combo.configure(
                width=max(45, max(len(v) for v in ifaces) + 2))
        if "Ethernet" in ifaces:
            self.netboot_iface_var.set("Ethernet")
            self.netboot_status_var.set(
                "Interfaccia preimpostata su 'Ethernet' (nota funzionante per "
                "questo modem) — verifica prima di avviare il responder.")
        else:
            self.netboot_status_var.set(
                "Seleziona l'interfaccia prima di avviare il responder "
                "(nessuna selezione preimpostata).")

    def pick_netboot_file(self):
        path = filedialog.askopenfilename(
            title="Seleziona firmware da servire via TFTP",
            filetypes=[("Firmware", "*.bin *.rbi *.img"), ("Tutti", "*.*")])
        if path:
            self.netboot_file_var.set(path)

    def detect_netboot_mac(self):
        """Rileva il MAC del router via ARP (netboot.detect_router_mac) in un
        thread separato - l'attesa della risposta ARP (fino a qualche secondo)
        non deve bloccare la UI. Il risultato torna via ui_queue/_poll_queue
        (StringVar.set() da un thread diverso dal main non e' sicuro in
        Tkinter)."""
        iface = self.netboot_iface_var.get()
        ip = self.netboot_router_ip_var.get().strip()
        if not iface:
            self.set_status("Rilevamento MAC: seleziona prima un'interfaccia")
            return
        if not ip:
            self.set_status("Rilevamento MAC: IP router mancante")
            return
        self.set_status(f"Rilevamento MAC in corso (ARP su {ip})...")

        def worker():
            try:
                mac = netboot.detect_router_mac(iface, ip)
            except netboot.NetbootError as e:
                self.ui_queue.put(("status", f"Rilevamento MAC fallito: {e}"))
                return
            self.ui_queue.put(("netboot_mac_detected", mac))

        threading.Thread(target=worker, daemon=True).start()

    def start_netboot_responder(self):
        if self.netboot_responder or self.netboot_tftp:
            return
        self._netboot_trigger_count = 0
        self.netboot_attempts_var.set(
            f"Tentativi BOOTP: 0/{self.NETBOOT_MAX_AUTO_TRIGGERS}")
        if self.flash_running:
            self.set_status("Boot di rete: impossibile avviare durante un flash")
            return
        iface = self.netboot_iface_var.get()
        server_ip = self.netboot_server_ip_var.get().strip()
        offer_ip = self.netboot_offer_ip_var.get().strip()
        firmware = self.netboot_file_var.get().strip()
        fallback = self.netboot_fallback_var.get().strip() or "VBNT-K"
        mac_filter_on = self.netboot_mac_filter_var.get()
        router_mac = self.netboot_mac_var.get().strip() if mac_filter_on else None
        if mac_filter_on and not router_mac:
            self.set_status("Boot di rete: MAC router mancante - premi 'Rileva' "
                             "o disattiva il filtro")
            return
        if not iface:
            self.set_status("Boot di rete: seleziona un'interfaccia")
            return
        if not server_ip or not offer_ip:
            self.set_status("Boot di rete: IP server/offerto mancanti")
            return
        if not firmware:
            self.set_status("Boot di rete: seleziona il file firmware")
            return

        mac_line = (f"Filtro MAC: attivo, solo {router_mac}\n" if router_mac
                    else "Filtro MAC: DISATTIVO - il responder rispondera' a "
                         "QUALSIASI dispositivo sull'interfaccia!\n")
        summary = (f"Interfaccia: {iface}\n"
                   f"Server IP: {server_ip}\n"
                   f"Offer IP: {offer_ip}\n"
                   f"File: {firmware}\n"
                   f"Servito come: {fallback} (copia rinominata)\n"
                   f"{mac_line}\n"
                   "Verra' avviato un responder che risponde a richieste BOOTP "
                   "broadcast su questa interfaccia, piu' un server TFTP.\n"
                   "Procedere?")
        if not messagebox.askyesno("Conferma boot di rete", summary, icon="warning"):
            self.set_status("Boot di rete annullato")
            return

        try:
            served_path = netboot.prepare_named_copy(firmware, fallback,
                                                      NETBOOT_CACHE_DIR)
            self._netboot_served_name = fallback
            self.logger.info(f"[netboot] copia rinominata pronta: {served_path}")
            # bind_ip=server_ip: vincola il TFTP alla sola interfaccia scelta
            # (server_ip e' l'IP di questo PC su quella rete), non a 0.0.0.0 -
            # vedi nota anti-leak in uart_netboot.py.
            self.netboot_tftp = netboot.TftpServer(served_path, bind_ip=server_ip,
                                                    port=69,
                                                    on_event=self.logger.info,
                                                    on_conflict=self._gui_port_conflict)
            self.netboot_tftp.start()
            self.netboot_responder = netboot.BootpResponder(
                iface, server_ip, offer_ip, fallback, on_event=self.logger.info,
                on_request=self._on_netboot_request, router_mac=router_mac)
            self.netboot_responder.start()
        except netboot.NetbootError as e:
            self.logger.info(f"[netboot] errore avvio: {e}")
            self._stop_netboot_internal()
            self.set_status("Boot di rete: errore avvio")
            return

        self.netboot_start_btn.config(state="disabled")
        self.netboot_stop_btn.config(state="normal")
        self.set_status(f"Boot di rete attivo su {iface}")

    def stop_netboot_responder(self):
        self._stop_netboot_internal()
        self.set_status("Boot di rete fermato")

    def rearm_netboot_trigger(self):
        """Azzera il contatore dei tentativi automatici senza toccare il
        responder BOOTP/TFTP (che puo' restare attivo) - utile dopo aver
        cambiato file firmware, o per continuare a riprovare oltre il tetto
        di sicurezza (vedi NETBOOT_MAX_AUTO_TRIGGERS) sapendo cosa si sta
        facendo."""
        self._netboot_trigger_count = 0
        self.netboot_attempts_var.set(
            f"Tentativi BOOTP: 0/{self.NETBOOT_MAX_AUTO_TRIGGERS}")
        self.logger.info("[netboot] trigger riarmato manualmente "
                          f"({self.NETBOOT_MAX_AUTO_TRIGGERS} tentativi disponibili)")

    def _stop_netboot_internal(self):
        if self.netboot_responder:
            self.netboot_responder.stop()
            self.netboot_responder = None
        if self.netboot_tftp:
            self.netboot_tftp.stop()
            self.netboot_tftp = None
        self._netboot_served_name = None
        self.netboot_stop_btn.config(state="disabled")
        if self.netboot_available and not self.flash_running:
            self.netboot_start_btn.config(state="normal")

    def _on_netboot_request(self, req_file, resolved_name):
        """Chiamato (da un altro thread) a ogni BOOTREQUEST reale ricevuta:
        rimbalza sulla queue per aggiornare, se serve, il nome della copia
        servita col nome che il router sta davvero chiedendo."""
        self.ui_queue.put(("netboot_request", req_file, resolved_name))

    def _handle_netboot_request(self, req_file, resolved_name):
        if not req_file:
            # il router non ha specificato un nome in questa richiesta:
            # resta sul fallback gia' configurato, niente da fare.
            return
        if resolved_name == self._netboot_served_name:
            return  # gia' allineato, nessuna copia da rifare
        firmware = self.netboot_file_var.get().strip()
        try:
            served_path = netboot.prepare_named_copy(firmware, resolved_name,
                                                      NETBOOT_CACHE_DIR)
        except netboot.NetbootError as e:
            self.logger.info(f"[netboot] errore aggiornando il nome file: {e}")
            return
        if self.netboot_tftp:
            self.netboot_tftp.filepath = served_path
        self._netboot_served_name = resolved_name
        self.logger.info(
            f"[netboot] il router ha chiesto {resolved_name!r}: copia "
            f"aggiornata automaticamente, servo {served_path}")

    def _check_netboot_trigger(self, text):
        if not self._netboot_matcher.feed(text):
            return
        now = time.time()
        if now - self._netboot_last_trigger < 5:
            return
        # Limite massimo tentativi automatici: se il file viene rifiutato in
        # modo deterministico (es. "not a valid BLI"), il router si riavvia
        # da solo e ripropone "Market ID" - senza un tetto il tool
        # riflasherebbe lo stesso file all'infinito (osservato dal vivo).
        if self._netboot_trigger_count >= self.NETBOOT_MAX_AUTO_TRIGGERS:
            self.logger.info(
                f"[netboot] limite di {self.NETBOOT_MAX_AUTO_TRIGGERS} "
                f"tentativi automatici raggiunto - trigger disattivato per "
                f"evitare un loop infinito, riavvia il responder per riprovare"
            )
            return
        self._netboot_trigger_count += 1
        attempt = self._netboot_trigger_count
        self._netboot_last_trigger = now
        self.ui_queue.put(("netboot_attempts", attempt))
        ser = self.ser
        logger = self.logger

        def worker():
            logger.info(f"[netboot] 'Market ID' rilevato (tentativo "
                        f"{attempt}/{self.NETBOOT_MAX_AUTO_TRIGGERS}), "
                        f"invio raffica 'b'...")
            try:
                netboot.send_boot_trigger_burst(ser, logger=logger)
                logger.info("[netboot] raffica 'b' inviata.")
            except Exception as e:  # noqa: BLE001 - riportato in UI
                logger.info(f"[netboot] errore invio raffica: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_rx_text(self, text):
        """Callback del Reader: logga sempre, e se il trigger di rete e'
        attivo controlla anche la comparsa di 'Market ID'."""
        self.logger.rx(text)
        if self.netboot_trigger_var.get() and self.ser:
            self._check_netboot_trigger(text)

    # ------------------------------------------------------------ comandi

    _KEYSYM_TO_BYTES = {
        "Return": b"\r",
        "KP_Enter": b"\r",
        "BackSpace": b"\x7f",
        "Tab": b"\t",
        "Escape": b"\x1b",
    }

    def _on_console_keypress(self, event):
        """Modalita' terminale: ogni tasto premuto con la console a fuoco
        va DIRETTAMENTE sulla seriale (niente locale echo - lo fa gia' il
        dispositivo remoto rimandandolo su RX, come un terminale seriale
        vero)."""
        if not self.ser and not self.attach_client:
            return "break"
        keysym = event.keysym
        if keysym in self._KEYSYM_TO_BYTES:
            data = self._KEYSYM_TO_BYTES[keysym]
        elif (event.state & 0x4) and len(keysym) == 1 and keysym.isalpha():
            # Ctrl+<lettera> -> codice di controllo (es. Ctrl+C = 0x03)
            data = bytes([ord(keysym.upper()) - 64])
        elif event.char and event.char.isprintable():
            data = event.char.encode("utf-8", errors="ignore")
        else:
            return "break"
        try:
            if self.ser:
                self.ser.write(data)
            else:
                # in attach il TX passa dall'hub verso l'owner
                self.attach_client.send(data)
            self.logger.tx(data.decode("latin-1"))
        except (serial.SerialException, OSError) as e:
            self.logger.info(f"Errore invio tasto: {e}")
        return "break"

    def send_command(self):
        if not self.ser and not self.attach_client:
            self.set_status("Non connesso: premi Connetti prima di inviare")
            return
        text = self.cmd_var.get()
        if not text.strip():
            return
        try:
            if self.ser:
                self.ser.write((text + "\n").encode("utf-8"))
            else:
                # in attach il TX passa dall'hub verso l'owner
                self.attach_client.send(text + "\n")
        except (serial.SerialException, OSError) as e:
            self.logger.info(f"Errore invio: {e}")
            return
        self._console_append(f"> {text}\n")
        self.logger.tx(text)
        self.cmd_var.set("")

    # ------------------------------------------------------------ flash

    def pick_file(self):
        path = filedialog.askopenfilename(
            title="Seleziona firmware",
            filetypes=[("Firmware", "*.bin *.hex *.elf *.img"), ("Tutti", "*.*")])
        if path:
            self.file_var.set(path)

    def start_flash(self):
        if self.flash_running:
            return
        port = self._selected_device()
        profile_name = self.profile_var.get()
        firmware = self.file_var.get()
        use_bootloader = self.bootloader_var.get()
        if not port:
            self.set_status("Nessuna porta selezionata")
            return
        if not profile_name:
            self.set_status("Nessun profilo selezionato")
            return
        try:
            baud = self._get_baud()
            profile = core.get_profile(self.profiles, profile_name)
            flash_cmd = core.build_flash_cmd(profile, profile_name,
                                             port, baud, firmware)
        except (FileNotFoundError, ValueError) as e:
            self.logger.info(f"Errore: {e}")
            self.set_status("Flash non avviato")
            return

        # Conferma riepilogativa: tocca hardware reale, NON rimuovere.
        fields = dict(core.flash_summary_fields(
            profile_name, firmware, port, baud, use_bootloader, flash_cmd))
        summary = (f"Profilo: {fields['profilo']}\n"
                   f"Firmware: {fields['firmware']}\n"
                   f"Porta: {fields['porta']}\n"
                   f"Bootloader: {fields['bootloader']}\n\n"
                   f"Comando:\n{fields['comando']}\n\nProcedere?")
        if not messagebox.askyesno("Conferma flash", summary, icon="warning"):
            self.set_status("Flash annullato")
            return

        if self.ser:
            self.logger.info("[gui] disconnetto la porta per lasciare "
                             "spazio al tool di flash...")
            self.disconnect()

        self.flash_running = True
        self.flash_btn.config(state="disabled")
        self.detect_btn.config(state="disabled")
        self.netboot_start_btn.config(state="disabled")
        self.set_status(f"Flash in corso su {port}...")

        def worker():
            try:
                if use_bootloader:
                    core.enter_bootloader(profile, port, baud, self.logger)
                rc = core.run_flash(flash_cmd, self.logger)
                status = "Flash completato" if rc == 0 else f"Flash FALLITO (rc={rc})"
            except serial.SerialException as e:
                self.logger.info(f"Errore porta seriale: {e}")
                status = "Flash FALLITO (porta)"
            except FileNotFoundError:
                self.logger.info("Errore: comando di flash non trovato "
                                 "(eseguibile non nel PATH?).")
                status = "Flash FALLITO (tool mancante)"
            except ValueError as e:
                self.logger.info(f"Errore: {e}")
                status = "Flash FALLITO"
            finally:
                self.ui_queue.put(("flash_done",))
            self.ui_queue.put(("status", status))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ rilevamento baud

    def _set_detect_busy(self, busy):
        """Blocca/riabilita i controlli sensibili durante una scansione baud."""
        state = "disabled" if busy else "normal"
        self.detect_btn.config(state=state)
        self.connect_btn.config(state=state)
        self.flash_btn.config(state=state)

    def _on_auto_detect_toggle(self):
        # ogni cambio azzera i contatori: ripartire pulito evita che un vecchio
        # streak/fail-count faccia scattare (o bloccare) subito la scansione.
        self._auto_bad_streak = 0
        self._auto_fail_count = 0
        self._auto_last_rx_count = 0
        if self.auto_detect_var.get():
            self.logger.info("[detect] auto-rilevamento baud ATTIVATO.")
        else:
            self.logger.info("[detect] auto-rilevamento baud disattivato.")

    def detect_baud_manual(self):
        self._start_detection(auto=False)

    def _start_detection(self, auto):
        # Vincoli di sicurezza: mai durante un flash/bootloader (flash_running),
        # mai in parallelo a un'altra scansione, solo se connessi in monitor.
        if self.flash_running or self.detecting:
            return
        if not self.ser or not self.reader:
            if not auto:
                self.set_status("Rileva baud: non connesso")
            return
        port = self.ser.port
        try:
            current_baud = self._get_baud()
        except ValueError:
            current_baud = None

        self.detecting = True
        self._set_detect_busy(True)
        origin = "auto" if auto else "manuale"
        self.logger.info(
            f"[detect] scansione baud ({origin}) su {port}, "
            f"baud corrente {current_baud}...")

        # libera la porta: chiudi reader, hub e seriale prima della scansione
        # (detect apre/chiude la COM per ogni candidato: l'hub, legato al vecchio
        # handle, va fermato e verra' riavviato alla riapertura).
        if self.reader:
            self.reader.stop()
            self.reader = None
        if self.hub:
            self.hub.stop()
            self.hub = None
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = None

        def progress(baud, ratio):
            if ratio is None:
                self.ui_queue.put(
                    ("console", f"[detect]   {baud}: porta non apribile\n"))
            else:
                self.ui_queue.put(
                    ("console", f"[detect]   {baud}: {ratio * 100:.1f}% stampabili\n"))

        def worker():
            result, err = None, None
            try:
                result = core.detect_baud(port, sample_time=0.4,
                                          current_baud=current_baud,
                                          progress=progress)
            except Exception as e:  # noqa: BLE001 - riportato in UI
                err = str(e)
            self.ui_queue.put(
                ("detect_done", port, current_baud, result, err, auto))

        threading.Thread(target=worker, daemon=True).start()

    def _on_detect_done(self, port, orig_baud, result, err, auto):
        self.detecting = False
        reopen_baud = orig_baud
        if err:
            self.logger.info(f"[detect] errore durante la scansione: {err}")
        elif result is None:
            self.logger.info("[detect] nessun candidato testabile.")
        elif result.found:
            reopen_baud = result.baud
            self.baud_var.set(str(result.baud))
            self.logger.info(
                f"[detect] baud rilevato: {result.baud} "
                f"({result.ratio * 100:.1f}% stampabili). "
                f"Riprendo la lettura al nuovo baud.")
            self.set_status(f"Baud rilevato: {result.baud}")
            self._auto_fail_count = 0
        else:
            self.logger.info(
                f"[detect] nessun baud alternativo leggibile trovato "
                f"(migliore {result.baud} a {result.ratio * 100:.1f}%). "
                f"Possibile wiring TX/RX invertito o livelli elettrici, non "
                f"baud. Riapro al baud originale {orig_baud}.")
            self.set_status("Nessun baud leggibile trovato")
            if auto:
                self._auto_fail_count += 1

        if reopen_baud is None:
            reopen_baud = orig_baud
        self._reopen_after_detect(port, reopen_baud)
        self._set_detect_busy(False)

        # reset stato euristica + avvio cooldown
        self._auto_bad_streak = 0
        self._auto_last_rx_count = self.reader.rx_count if self.reader else 0
        self._last_auto_scan = time.time()

        if auto and self._auto_fail_count >= AUTO_MAX_FAILS:
            self.auto_detect_var.set(False)
            self.logger.info(
                f"[detect] auto-rilevamento disattivato dopo "
                f"{self._auto_fail_count} tentativi falliti: usa 'Rileva baud' "
                f"manualmente (probabile problema di wiring, non di baud).")
            self._auto_fail_count = 0

    def _reopen_after_detect(self, port, baud):
        try:
            self.ser = core.open_port(port, baud)
        except (serial.SerialException, OSError) as e:
            self.logger.info(
                f"[detect] impossibile riaprire {port} @ {baud}: {e}")
            self.ser = None
            self.connect_btn.config(text="Connetti")
            self.set_status("Disconnesso (riapertura fallita)")
            return
        # riavvia l'hub sulla porta riaperta cosi' la condivisione resta attiva
        self.hub = self._start_gui_hub(port)
        self.reader = core.Reader(self.ser, self._on_rx_text,
                                  encoding=self._get_encoding(),
                                  on_error=self._on_reader_error,
                                  on_bytes=(self.hub.broadcast if self.hub
                                            else None))
        self.reader.start()
        self.connect_btn.config(text="Disconnetti")
        self.logger.info(f"[gui] lettura ripresa su {port} @ {baud}")

    def _auto_detect_tick(self):
        try:
            self._maybe_auto_detect()
        finally:
            self.root.after(AUTO_CHECK_INTERVAL_MS, self._auto_detect_tick)

    def _maybe_auto_detect(self):
        if not self.auto_detect_var.get():
            return
        # mai durante flash/bootloader, scansione in corso, o se non connessi
        if self.flash_running or self.detecting or not self.ser or not self.reader:
            return
        if self._auto_fail_count >= AUTO_MAX_FAILS:
            return
        if time.time() - self._last_auto_scan < AUTO_COOLDOWN_S:
            return
        # valuta solo se sono arrivati byte nuovi (buffer non stantio)
        count = self.reader.rx_count
        if count == self._auto_last_rx_count:
            return
        self._auto_last_rx_count = count
        data = self.reader.recent_bytes()
        if len(data) < AUTO_MIN_SAMPLE:
            return
        ratio = core.estimate_printable_ratio(data)
        if ratio < core.PRINTABLE_LOW_THRESHOLD:
            self._auto_bad_streak += 1
            if self._auto_bad_streak >= AUTO_BAD_STREAK_NEEDED:
                self.logger.info(
                    f"[detect] dati illeggibili sostenuti "
                    f"({ratio * 100:.1f}% stampabili): avvio auto-scansione baud.")
                self._start_detection(auto=True)
        else:
            self._auto_bad_streak = 0

    # ------------------------------------------------------------ chiusura

    def on_close(self):
        try:
            if self._tail_stop:
                self._tail_stop.set()
            if self.watcher:
                self.watcher.stop()
            self.disconnect()
            self._stop_netboot_internal()
            self.logger.close()
        except Exception:
            pass
        self.root.destroy()


def main():
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--tail-log", default=None,
                        help="apri in modalita' visualizzatore live su questo "
                             "file di log invece di connettersi in proprio "
                             "(usato per l'apertura automatica dalla CLI)")
    args, _ = parser.parse_known_args()

    root = tk.Tk()
    app = UartGuiApp(root)
    if args.tail_log:
        app.start_tail(args.tail_log)
    root.mainloop()


if __name__ == "__main__":
    main()
