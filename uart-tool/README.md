# uart-tool

CLI per monitor, comandi e flash via UART. Installazione:

    pip install -r requirements.txt

## Esempi

    python uart_tool.py ports
    python uart_tool.py watch
    python uart_tool.py monitor --port COM3 --baud 115200
    python uart_tool.py send --port COM3 --cmd "help"
    python uart_tool.py shell --port COM3
    python uart_tool.py flash --port COM3 --profile esp32 --file fw.bin -b
    python uart_tool.py detect-baud --port COM10
    python uart_tool.py profile list

GUI desktop (Tkinter, stesse funzioni + hotplug porte live):

    python uart_gui.py

## Eseguibili precompilati

In `dist/` ci sono `uart_gui.exe` (GUI) e `uart_tool.exe` (CLI), avviabili
direttamente senza installare Python. Tieni `profiles.json` nella stessa
cartella dell'exe: e' li' che viene letto e resta modificabile senza
ricompilare. I log finiscono in `logs/` accanto all'exe.
Rebuild: `pyinstaller --onefile --name uart_tool uart_tool.py` e
`pyinstaller --onefile --windowed --name uart_gui uart_gui.py`.

**Apertura automatica della GUI da CLI**: `monitor`, `send`, `shell`, `flash` e
`netboot` aprono di default anche una finestra GUI in modalita' "tail" sul log
di quella sessione (visualizzazione live, non apre la porta seriale in
proprio - nessun conflitto con la CLI che la tiene aperta). Utile per vedere
cosa succede sulla UART anche quando il tool viene pilotato da script o da
un'altra sessione automatizzata. Disattivabile con `--no-gui`.

`watch` stampa e logga live plug/unplug delle porte seriali (Ctrl+C esce).
`--port` e' opzionale: se omesso il tool elenca le porte e chiede quale
usare (auto-selezione se ce n'e' una sola).
`flash` chiede sempre conferma (y/N). Con `-b`/`--bootloader` esegue prima
la sequenza di ingresso bootloader del profilo; senza flag flasha diretto.
Tutto il traffico va in `logs/uart_YYYYmmdd_HHMMSS.log` e a schermo.

## Rilevamento baud automatico

Quando si monitora un boot log (tipico Qualcomm/Broadcom su router/modem) con
il baud sbagliato, sullo schermo compaiono stringhe di caratteri corrotti
(byte di controllo ripetuti, `^@^A^@...`). Il tool riconosce questa situazione
e prova a determinare il baud corretto.

Come funziona: su un campione dei byte RX recenti calcola la percentuale di
byte "stampabili" (ASCII 0x20-0x7E piu' tab/CR/LF). Sotto il 55% sostenuto lo
stream e' considerato "probabilmente baud sbagliato". A quel punto scansiona i
baud comuni (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600,
1000000, 1500000, 2000000, 3000000; escluso quello corrente): per ognuno riapre
la porta, legge ~0.4s e ricalcola la percentuale. Tiene il migliore e lo
considera valido solo sopra l'85%. Se nessuno supera la soglia, riapre al baud
originale e segnala che il problema e' probabilmente il wiring TX/RX o i livelli
elettrici, non il baud.

CLI:

    python uart_tool.py detect-baud --port COM10          # testa tutti i baud
    python uart_tool.py detect-baud --port COM10 --baud 115200   # esclude 115200

Stampa la percentuale di ogni candidato e il baud rilevato (o "nessun baud
alternativo leggibile trovato", con exit code 2).

GUI:
- pulsante **Rileva baud** (accanto al campo Baud): avvia la scansione
  on-demand quando si e' connessi in monitor. Disabilitato durante un flash.
- checkbox **Rileva baud automaticamente** (default DISATTIVATO): se attivo e
  in monitor, il tool controlla periodicamente l'euristica e avvia da solo la
  scansione se i dati risultano illeggibili in modo sostenuto. Con cooldown di
  20s tra i tentativi e stop automatico dopo 3 scansioni fallite di fila (poi
  serve un trigger manuale). Mai attivo durante un flash o l'ingresso
  bootloader.

Se viene trovato un baud migliore, il campo Baud viene aggiornato, l'evento e'
loggato con la percentuale di affidabilita' e la lettura riprende al nuovo baud.
Lo switch tocca solo il parametro di lettura (nessun DTR/RTS, nessun comando sul
dispositivo), quindi non richiede conferma; viene comunque sempre loggato.

## Boot di rete BOOTP+TFTP (VBNT-K e simili)

Alcuni bootloader (es. CFE su Technicolor VBNT-K) hanno una modalita' di
recovery che scarica il firmware via rete invece che da seriale: la seriale
serve solo a innescare la modalita' e osservare i log, il trasferimento vero
e' su Ethernet (BOOTP poi TFTP).

**Prerequisiti**: pacchetto `scapy` (in `requirements.txt`) e driver **Npcap**
installato (https://npcap.com) - senza Npcap la sezione "Boot di rete" della
GUI resta disabilitata con un messaggio esplicativo, e il sottocomando
`netboot` della CLI da' errore chiaro invece di un traceback.

**Interfaccia sempre esplicita, mai "tutte le interfacce"**: non si ascolta mai
su 0.0.0.0. Un tool precedente in ascolto su tutte le interfacce ha fatto leak
DHCP/BOOTP su un hotspot WiFi collegato allo stesso PC, togliendo internet a
dispositivi di un'altra rete. Qui il responder BOOTP gira sulla singola
interfaccia scelta e il server TFTP fa bind sull'IP di quell'interfaccia
(il "Server IP" indicato), non su 0.0.0.0. Nella GUI l'interfaccia e'
preimpostata su "Ethernet" quando presente (il target abituale, Technicolor
VBNT-K) ma resta modificabile: verifica sempre che sia quella giusta (es.
"Ethernet", non "Wi-Fi") prima di premere Avvia. Nella CLI `--iface` resta
obbligatorio. Il responder non parte mai da solo: serve sempre la conferma
esplicita (pulsante Avvia nella GUI, prompt y/N nella CLI).

**Filtro per MAC del router (attivo di default)**: il responder risponde SOLO
alle BOOTREQUEST provenienti dal MAC del router bersaglio. Su una LAN reale (non
un banco di recovery isolato) qualsiasi altro dispositivo che manda DHCP/BOOTP
sull'interfaccia scelta riceverebbe altrimenti un IP e un boot file finti - e'
gia' successo dal vivo: il responder ha risposto a un dispositivo estraneo
(192.168.1.137) invece del router. Il MAC non ha un default hardcoded (cambia
da device a device): se omesso (CLI `--router-mac`, GUI campo **"MAC router"**
vuoto), viene **rilevato automaticamente via ARP** (`netboot.detect_router_mac`
in `uart_netboot.py`) interrogando `--router-ip`/campo **"Router IP"** (default
`192.168.1.1`, l'IP a cui il router risponde prima di entrare in recovery) -
CLI in automatico prima di avviare il responder, GUI col pulsante **"Rileva"**.
Se non arriva risposta ARP entro il timeout (es. router gia' in un boot state
senza stack IP), il filtro resta disattivo per quella sessione con un avviso
esplicito, oppure il MAC si puo' impostare a mano. Le richieste da altri MAC
vengono loggate e ignorate. Il filtro si puo' disattivare esplicitamente (CLI
`--no-mac-filter`, GUI checkbox **"Filtra per MAC router"** da deselezionare,
attiva di default): in tal caso il responder torna a rispondere a QUALSIASI
dispositivo sull'interfaccia - reintroduce esattamente il rischio "risponde a
chiunque sulla LAN" descritto sopra, usalo solo su un banco isolato. Sia CLI
che GUI avvisano esplicitamente (log + riepilogo di conferma) quando il filtro
e' disattivo.

**Risposta ARP diretta**: oltre al BOOTREPLY, il responder risponde anche a
qualunque richiesta ARP "who-has" per il proprio Server IP, iniettando la
risposta via `sendp` invece di affidarsi allo stack di rete nativo di
Windows. Osservato dal vivo: la RRQ TFTP a volte non arriva mai (nessuna riga
`[tftp] RRQ da...` nel log, nonostante bind riuscito e nessun conflitto di
porta) mentre nella cache ARP di Windows l'IP temporaneo del router risultava
"Unreachable" - indizio che lo stack ARP nativo di Windows non rispondeva in
tempo per il timeout stretto del CFE (probabile contesa con il thread di
cattura Npcap gia' attivo per il BOOTP). Rispondere direttamente elimina
questa dipendenza. Risponde solo per il proprio Server IP (mai per conto di
altri indirizzi), quindi non e' soggetto al filtro MAC del router - e'
semplicemente l'annuncio veritiero del proprio indirizzo, utile a chiunque
lo chieda.

**Rinomina automatica del file**: il file firmware indicato viene copiato (in
`netboot_cache/`) e rinominato con il "Board Mnemonic" richiesto dal
bootloader (es. "VBNT-K"), cosi' viene servito gia' col nome giusto. Il campo
"Fallback"/`--fallback-name` e' solo un punto di partenza: appena arriva la
prima vera richiesta BOOTP, il tool legge il nome che il router sta
effettivamente chiedendo (lo annuncia da solo nel pacchetto) e rifa' la copia
con quel nome automaticamente, senza bisogno di indovinarlo prima. Il server
TFTP comunque ignora il filename richiesto nella singola richiesta TFTP e
serve sempre l'ultima copia pronta, quindi eventuali discrepanze residue non
bloccano il trasferimento.

GUI: sezione **"Boot di rete BOOTP+TFTP (VBNT-K)"** - interfaccia (preimpostata
su "Ethernet" se presente, modificabile), IP server/offerto, file firmware,
nome fallback (preimpostato "VBNT-K"), checkbox **"Filtra per MAC router"**
(attiva) con campo **"MAC router"** (vuoto di default), campo **"Router IP"**
(preimpostato "192.168.1.1") e pulsante **"Rileva"** per popolare il MAC via
ARP, checkbox **"Trigger automatico 'b' su 'Market ID'"** (osserva il log seriale e invia da
solo una raffica di 10x 'b' a 50ms quando compare la stringa "Market ID",
poco prima del prompt "Press b to enter BOOT-P"), pulsanti **Avvia/Ferma
responder rete** (conferma richiesta prima di avviare, disabilitato durante
un flash).

Il trigger si ri-arma automaticamente (cooldown 5s) se il router si riavvia
di nuovo dopo un tentativo fallito - utile per firmware che vengono rifiutati
in modo intermittente. **Limite di sicurezza**: massimo 5 tentativi automatici
per avvio del responder; oltre quel limite il trigger si disattiva da solo
(loggato chiaramente) per evitare un loop infinito di riflash contro un file
rifiutato in modo deterministico. Nella GUI il conteggio e' visibile live
("Tentativi BOOTP: N/5" accanto al checkbox del trigger) e c'e' un pulsante
**"Riarma trigger"** per azzerarlo senza dover fermare/riavviare l'intero
responder (utile dopo aver cambiato file firmware, o per continuare oltre il
tetto sapendo cosa si sta facendo). Nella CLI ogni tentativo e' numerato nel
log ("tentativo N/5"); per riarmare basta rilanciare il comando (processo
non interattivo, un nuovo avvio riparte gia' da 0/5).

CLI:

    python uart_tool.py netboot --iface Ethernet --server-ip 192.168.1.2 \
        --offer-ip 192.168.1.50 --file firmware.rbi --fallback-name VBNT-K \
        --port COM10 --trigger-b

`--iface` e' obbligatorio. `--router-mac` non ha default: se omesso viene
rilevato via ARP su `--router-ip` (default `192.168.1.1`) prima di avviare il
responder; usa `--no-mac-filter` per rispondere a qualsiasi dispositivo (solo su
banco isolato - vedi avviso sopra). Senza `--port`/`--trigger-b` avvia solo il
responder di rete (utile per i retry automatici: dopo un trasferimento fallito
il bootloader rientra da solo in modalita' BOOTP piu' volte, senza bisogno di
un nuovo trigger seriale).

## Server TFTP: dettagli e limiti

Il server TFTP interno (`uart_netboot.TftpServer`) e' scritto da zero in
Python puro (nessuna dipendenza esterna), sola lettura, RFC 1350 + opzioni
RFC 2347 (blksize/tsize/timeout). Punti da sapere:

- **Ogni richiesta gira nel proprio thread**: il server resta reattivo anche
  durante un trasferimento lungo. Una RRQ ripetuta dallo stesso client
  mentre e' gia' in corso un trasferimento verso di lui viene loggata e
  ignorata (non apre una seconda sessione parallela, che confonderebbe il
  client con due porte effimere diverse per la stessa richiesta).
- **Gli ACK vengono verificati per IP sorgente**: un pacchetto che arriva
  sulla porta effimera della sessione da un IP diverso dal client atteso
  (rumore di altri dispositivi sulla stessa LAN - ne capita parecchio,
  vedi il filtro MAC del responder BOOTP piu' sopra) viene scartato senza
  consumare un tentativo di retry.
- **Limite dei 65535 blocchi TFTP (RFC 1350)**: il numero di blocco e' a 16
  bit. A blksize di default (512 byte) il limite e' ~32MB. Se il client
  negozia le opzioni (blksize/tsize), il server alza automaticamente il
  blksize quanto basta per restare sotto il limite su file piu' grandi
  (fino a `MAX_BLKSIZE`=1428). Se il client NON negozia opzioni (es. il CFE
  Technicolor osservato in questo progetto non lo fa mai) non c'e' modo
  RFC-legale di farlo per lui: il server logga un'ATTENZIONE esplicita
  invece di corrompere il trasferimento in silenzio.
- **Su fallimento invia un pacchetto TFTP ERROR** al client (oltre a
  loggare localmente), cosi' il client puo' accorgersi subito che il
  trasferimento e' fallito invece di aspettare il proprio timeout interno.
- Timeout/retry (`TIMEOUT`=3s, `MAX_RETRIES`=6) allineati a tftpd64, gia'
  dimostrato funzionante su questo router (vedi GUIDA-IT.md Parte D).

## Aggiungere un profilo

Modifica `profiles.json` aggiungendo una chiave con:

    "miotarget": {
      "flash_cmd": "mio_tool --port {port} --baud {baud} {file}",
      "bootloader": {
        "method": "dtr_rts",
        "sequence": [["dtr", 0], ["rts", 1], ["sleep", 0.1], ["rts", 0]]
      }
    }

Metodi bootloader: `dtr_rts` (passi `dtr`/`rts`/`sleep`) oppure `command`
(campi `command` e `wait`). Placeholder in `flash_cmd`: `{port}`, `{baud}`, `{file}`.
