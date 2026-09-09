# Guida root: tentativo di rooting su AGTEF_2.4.5 (fallito) + ripristino configurazione (riuscito)

Seguito diretto di [`GUIDA-IT.md`](GUIDA-IT.md): dopo il recovery del firmware, si è tentato di riottenere l'accesso root perso col reflash (necessario per installare la GUI community "Ansuel"), poi di ripristinare un backup di configurazione. Script in [`root/`](root/).

## Condizioni di partenza

- Modem appena recuperato con `AGTEF_2.4.5_CLOSED.rbi` (vedi guida principale), quindi con firmware "stock" pulito — nessuna modifica di root sopravvive a un reflash completo dei bank.
- Pannello admin web raggiungibile su `192.168.1.1`, credenziali `admin`/`admin`.
- Note di rooting precedenti (proprie, per lo stesso device) scritte per **AGTEF_1.0.3**, molto più vecchio dell'attuale 2.4.5.

## Strumento: AutoFlashGUI

[AutoFlashGUI](https://github.com/mswhirl/autoflashgui) (di Mark Smith / Whirlpool, GPLv3, parte dell'ecosistema [hack-technicolor](https://hack-technicolor.readthedocs.io)) automatizza il rooting dei Technicolor tramite **command injection** in uno dei campi DDNS del pannello admin: il router esegue una `ping`/aggiornamento DDNS internamente senza sanificare correttamente l'input, permettendo di eseguire comandi shell arbitrari passandoli come parte del "dominio"/"indirizzo IP" nella richiesta.

Anziché pilotare la GUI Windows (non scriptabile facilmente), si è richiamata direttamente la libreria Python sottostante (`libautoflashgui.py`) con uno script.

### Dipendenze: tre bug di compatibilità Python3 da aggirare

1. **`robobrowser`** (dipendenza HTTP della libreria) è abbandonato dal 2016 e incompatibile col Werkzeug moderno (`cannot import name 'cached_property' from 'werkzeug'`). Fix: virtualenv dedicato con `werkzeug<1.0` fissato, poi `pip install --no-deps robobrowser` per evitare che reinstalli un Werkzeug recente.
2. **`mysrp.py`** (implementazione locale del protocollo di autenticazione SRP-6, incluso nel repo di AutoFlashGUI) mescola `str` e `bytes` in un punto (`username + six.b(':') + password`), causando un `TypeError` immediato al primo login su Python 3. Fix (senza toccare il file vendorizzato): passare username/password come **bytes** (`b"admin"`, non `"admin"`) allo script chiamante — si propaga correttamente lungo tutta la catena.
3. Bonus: `libautoflashgui.py` chiama `traceback.print_exc()` nel proprio except-handler senza importare `traceback` — se l'autenticazione fallisce per un motivo diverso, questo maschera l'errore reale con un secondo `NameError`. Fix: iniettare `sys.modules`/attributo `traceback` nel modulo prima di chiamarlo (vedi `root/afg_inject_common.py`).

Vedi `root/afg_inject_common.py` per il setup completo.

## Tentativo di rooting: tre varianti, tutte fallite

AutoFlashGUI supporta più "metodi" di injection (endpoint diversi del pannello). Ne sono stati provati tre, in sequenza, ciascuno con l'autenticazione SRP-6 completata con successo (credenziali corrette confermate) ma **nessuno dei tre è arrivato ad abilitare SSH**:

| Script | Metodo/endpoint | Esito |
|---|---|---|
| `root/afg_inject_advancedddns.py` | `AdvancedDDNS` → `/modals/wanservices-modal.lp` (campo `ddns_domain`) | Comandi inviati senza errori di trasporto, porta 22 rimasta chiusa |
| `root/afg_inject_ping.py` | `Ping` → `/modals/diagnostics-ping-modal.lp` (campo `ipAddress`), comando specifico DGA4130/1.0.3 | Stesso esito |
| `root/afg_inject_basicddns.py` | `BasicDDNS` → `/dyndns.lp` (campo `ddns_domain`) | Stesso esito |

**Conclusione**: tre endpoint diversi, stesso esito negativo, è un indizio abbastanza forte che l'operatore abbia sistemato questa classe di vulnerabilità di command injection nella versione 2.4.5 (le note di rooting originali erano per la 1.0.3, molto più vecchia).

### Idea scartata: forzare la modalità BOOTP/TFTP per un downgrade

Prima di arrendersi sul rooting diretto, si è considerato di **scaricare una versione più vecchia del firmware (2.2.1, presumibilmente ancora vulnerabile)** riusando lo stesso meccanismo BOOTP/TFTP a livello di bootloader CFE documentato nella guida principale (che aveva già funzionato per il recovery), tenendo premuto il tasto reset per 8 secondi come da note di rooting.

**Risultato**: su un modem **sano**, tenere premuto reset per 8 secondi non innesca la modalità di recovery BOOTP — quella modalità scatta *automaticamente* solo dopo un vero fallimento di boot su entrambi i bank firmware (verificato: dopo il reset, il firmware restava `AGTEF_2.4.5` invariato e il modem tornava operativo normalmente in ~1 minuto). Forzarla deliberatamente richiederebbe ricreare un vero fallimento di boot — esattamente il rischio che ha causato l'incidente originale — quindi l'idea è stata scartata come non praticabile in sicurezza senza un secondo tentativo volontario di corrompere i bank.

**Aggiornamento 2026-08-27 — la premessa "2.2.1 presumibilmente ancora vulnerabile" è confermata**: su **un'unità fisica diversa** (non quella di questa guida, che qui resta su 2.4.5) trovata già con firmware attivo **AGTEF_2.2.1**, il root via la classica catena "Ansuel GUI"/AutoFlashGUI risulta effettivamente presente e funzionante — confermato leggendo `/etc/init.d/rootdevice` e `/etc/modgui_scripts/*.sh` (Christian Marangi, GUI version `9.6.69-3bd8c3f6`) e la config dropbear live, che mostra una stanza dedicata `dropbear.afg` (solo LAN) attiva. Feed opkg usati per i pacchetti (LuCI ecc.), per riferimento futuro:
```
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/base
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/packages
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/luci
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/routing
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/telephony
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/target/packages
```
Questo **non risolve** il problema pratico descritto sopra (come forzare il
downgrade/BOOTP su un modem sano senza ricreare l'incidente originale) — è
solo una conferma indipendente che, una volta ottenuto un modo sicuro di
arrivare alla 2.2.1, la superficie di vulnerabilità sfruttata da
AutoFlashGUI è ancora presente su quella versione. Vedi anche
`MEMORY-ARCHITECTURE-IT.md` §2.1/§4.1/§5 per altri dati raccolti sulla
stessa unità (mappa partizioni, meccanismo di cifratura del backup config,
un indizio — di terza mano, non confermato — sul targeting del bank via
BOOTP).

## Successo: ripristino configurazione via interfaccia stock (nessun root richiesto)

Analizzando le pagine del pannello admin (nessun link/pulsante di firmware upgrade risulta esposto da nessuna parte in questa skin dell'operatore — probabilmente rimosso deliberatamente), si è trovato che il tile "Gateway" → tab "Configuration" espone comunque **Export/Import Configuration** nativi:

```
POST /modals/system-config-modal.lp?action=import_config
Content-Type: multipart/form-data
campo file: configfile (richiede estensione .bin)
```

Il token CSRF va preso dalla pagina principale (`/`), non dalla pagina del modal stesso (prenderlo da lì restituisce `403 Forbidden`). Script funzionante: `root/import_config.py`. Risposta di successo:

```
{ "success":"true" }
```

seguita da un riavvio automatico del modem (~1 minuto) per applicare la configurazione importata — verificato con ping stabile (4/4, 1-4ms) al ritorno.

## Riepilogo esiti

| Obiettivo | Esito |
|---|---|
| Root / SSH su AGTEF_2.4.5 | ❌ Fallito (3 metodi di injection provati, tutti bloccati) |
| Downgrade forzato a 2.2.1 via reset | ❌ Scartato (non innesca la recovery mode su firmware sano) |
| Ripristino configurazione | ✅ Riuscito, via endpoint stock non documentato pubblicamente altrove |
| Installazione GUI Ansuel | ⏸ Non fatta (richiede root, non ottenuto) |

Vedi però l'aggiornamento sotto: root+GUI su 2.4.5 sono stati comunque
raggiunti, per una via indiretta diversa dall'injection diretta qui sopra.

## Aggiornamento 2026-09-09: root ottenuto per via indiretta (1.0.3 rootato → bank planning → upgrade a 2.4.5 con root preservato)

In una sessione diversa, il tentativo di rooting diretto descritto sopra è
stato aggirato completamente cambiando approccio: **rootare prima il
firmware vulnerabile (1.0.3), poi portare il root nell'upgrade a 2.4.5**,
invece di provare a bucare 2.4.5 direttamente (che qui sopra risulta
patchato).

Condizioni di partenza: modem su AGTEF_1.0.3, SSH chiuso, web UI
renderizzava correttamente HTML/CSRF (nessun problema di Lua grezzo
riscontrato in questo tentativo).

### Passaggi

1. **Injection AutoFlashGUI headless** (stesso `libautoflashgui.mainScript`,
   metodo `Ping`, comando specifico per `DGA4130 TIM AGTEF_1.0.3` dal
   `defaults.ini` di AutoFlashGUI) → root SSH attivato con successo,
   confermato `uid=0`. Su 1.0.3 questa classe di vulnerabilità è ancora
   aperta (coerente con quanto già osservato altrove in questo repo).
2. **Bank planning**: stato reale rilevato via `/proc/banktable/*` —
   `booted=bank_2` (1.0.3 appena rootato), `active=bank_1`, bank_1
   **completamente vuoto** (`0xFF` su tutti i 64 byte controllati).
   Applicata la variante "flash diretto su bank vuoto" invece dello
   swap-then-erase (vedi
   [`dga4130-root` README](https://github.com/HAL9000RELOADED/dga4130-root#bank-planning-quando-saltare-lo-swap-then-erase-variante-più-sicura)):
   niente swap dell'overlay, `bank_2` rootato resta intatto come fallback
   per l'intera procedura.
3. Upload `AGTEF_2.4.5_CLOSED.rbi` (32.876.123 byte) via canale exec SSH
   (`cat > /tmp/new.rbi`, non SFTP — il dropbear di questo firmware non
   espone il subsystem sftp), MD5 verificato identico al file locale.
4. Unseal on-device (`bli_parser`/`bli_unseal | dd bs=4 skip=1 seek=1`) →
   `/tmp/new.bin` esattamente 83.886.080 byte = dimensione di un bank
   (`mtd3`/`mtd4`), confermando l'integrità del container.
5. Staging dello stesso blocco `rc.local` di persistenza root (vedi
   `Root-DGA4130.ps1`) dentro `/overlay/bank_1/etc/rc.local`, MD5
   verificato.
6. `mtd write /tmp/new.bin bank_1` + `echo bank_1 > /proc/banktable/active`
   + reboot.
7. Boot riuscito su `bank_1`: `rc.local` eseguito e autoeliminato come
   previsto, root confermato (`uid=0`).
8. Upload + installazione GUI Ansuel (`GUI.tar.bz2`, MD5 verificato) via
   `bzcat | tar -C / -xvf - && /etc/init.d/rootdevice force`. **Nota
   pratica**: sia l'unseal (passo 4) sia `rootdevice force` (questo passo)
   sono processi lunghi (decine di secondi, il secondo ~70s) che
   sopravvivono alla chiusura del canale SSH che li ha lanciati — se il
   client SSH va in timeout, il comando prosegue comunque lato modem;
   verificarne il completamento via `ps` prima di considerarlo fallito.

### Conferma installazione GUI

```
$ uci show modgui
modgui.gui.gui_version='9.5.38-ba81e28c'
modgui.gui.gui_hash='<md5 del GUI.tar.bz2 caricato>'
modgui.var.version_spoof_mode='enabled'
modgui.var.isp_autodetect='1'
modgui.var.isp='TIM'
```
Stessa "firma" (`modgui` UCI, `rootdevice`/`modgui_scripts` di Christian
Marangi) già documentata per l'unità "martin router king" in
`MEMORY-ARCHITECTURE-IT.md`.

### Scoperta: la label "AGTEF_2.4.5" non corrisponde alla versione interna riportata dal firmware

Il file community `AGTEF_2.4.5_CLOSED.rbi` (sha256
`8fe8eb38531ac3f1cdc58671c5598885204a037d3db530a5230f476398b6a1f8`), una
volta booted, riporta `/etc/config/version`:
```
option version '19.4.1051-3401200-20241119103149-cf49b74e8c88c918fead0a0f9ad052f3283f4ee7'
option marketing_name 'Damson'
option marketing_version '19.4'
```
con `/etc/openwrt_release`: `DISTRIB_REVISION='r14144-e2ae576c18'`,
`DISTRIB_TARGET='brcm6xxx-tch/VBNTJ_502L07p1'`, kernel `4.1.52`. La label
"AGTEF X.Y.Z" usata dalla community/hack-technicolor per catalogare i file
**non coincide** con la stringa di versione interna TIM (stesso fenomeno
già noto per 1.0.3, che internamente si presenta come `16.3.7636`) — utile
saperlo per chiunque cerchi di correlare un file `.rbi` scaricato con
quanto riportato dal pannello/SSH del device dopo il flash.

### Hardening contro il rientro dell'operatore via ACS/CWMP: NON presente di default

Verificato su questa unità (rootata, su 2.4.5/19.4.1051, con VDSL
scollegato come da procedura): il client TR-069 (`cwmpd` + helper Lua
`cwmpevents`) è **attivo e abilitato all'avvio** (`/etc/rc.d/S70cwmpd`), il
rooting/installazione GUI **non lo tocca**. `uci show cwmpd` espone due
profili ACS operativi:

```
cwmpd.cwmpd_config.acs_url='https://regman-tl.interbusiness.it:10700/acs/'
cwmpd.cwmpd_config.acs_user='0018F6-Thomson-AGBasAdv'
cwmpd.cwmpd_config.periodicinform_enable='0'
cwmpd.operationalACS1.acs_url='https://regman-tl.interbusiness.it:10700/acs/'
cwmpd.operationalACS1.acs_user='0018F6-Thomson-AGBasAdv'
cwmpd.operationalACS1.connectionrequest_username='0018F6-Technicolor-CR-AG3play'
cwmpd.operationalACS2.acs_url='https://mobile.acs.tim.it:11201/cwmpWeb/WGCPEMgt'
cwmpd.operationalACS2.acs_user='fwacpedefaultusr'
cwmpd.operationalACS2.connectionrequest_username='fwacpecrdefaultusr'
cwmpd.operationalACS2.periodicinform_enable='1'
cwmpd.operationalACS2.periodicinform_interval='3600'
```
(campi `acs_pass`/`connectionrequest_password` presenti nello stesso
output ma omessi qui deliberatamente — recuperabili con lo stesso comando
`uci show cwmpd` su un'unità rootata, dato che sono salvati in chiaro
nella UCI config del device stesso.)

`operationalACS2` (`mobile.acs.tim.it`) ha `periodicinform_enable='1'` con
intervallo **3600s** — è il profilo TIM "live": una volta ricollegato il
VDSL, il modem tenterà un Inform CWMP verso quell'host ogni ora, di sua
iniziativa (CPE-initiated), indipendentemente da qualunque regola
firewall lato LAN. La porta 7547 (listener ConnectionRequest, per
richieste *in ingresso* dall'ACS) risultava **non in ascolto** al momento
della verifica — quindi l'operatore non poteva forzare una connessione in
quel preciso istante — ma questo non impedisce l'Inform periodico **in
uscita**, dentro il quale l'ACS può comunque emettere gli RPC CWMP
standard (`Download`/upgrade firmware, `SetParameterValues`,
`FactoryReset`, `Reboot`) nella sessione che il CPE stesso ha aperto.

Trovata anche una regola firewall `Deny_CWMP_Conn_Reqs_from_LAN`, che però
protegge da finte ConnectionRequest **lato LAN** — non è hardening verso
l'operatore.

**Conclusione: il device NON è indurito contro il rientro dell'operatore.**
Finché il VDSL resta scollegato (precondizione già richiesta da tutta
questa procedura, vedi guida principale) il punto è moot. Appena la WAN
torna su, l'ACS TIM ha un canale CWMP standard funzionante e potrebbe, a
policy loro, forzare un aggiornamento firmware che silenziosamente rimuove
il root. **Mitigazione non ancora applicata su questa unità**:
`/etc/init.d/cwmpd disable; killall cwmpd cwmpevents` interrompe il client
(perdi però diagnostica/supporto remoto ufficiale ISP) — va resa
persistente allo stesso modo del root (stesso meccanismo
`rc.local`/overlay), altrimenti torna attivo al prossimo boot pulito o
dopo un eventuale Download RPC ricevuto prima di disabilitarlo. In
alternativa, chi vuole tenere il VDSL collegato può bloccare via firewall
il traffico in uscita del CPE verso gli host ACS sopra elencati.

## Vedi anche

[`GUIDA-IT.md`](GUIDA-IT.md) — la guida di recovery firmware che precede questo tentativo di rooting.

[`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) — analisi del formato `.rbi` usato da questi firmware (header, cifratura AES, blocco "firma") e confronto tra le versioni disponibili.

[`dga4130-root` repo](https://github.com/HAL9000RELOADED/dga4130-root) — script `Root-DGA4130.ps1` e la variante di bank planning usata nell'aggiornamento sopra.
