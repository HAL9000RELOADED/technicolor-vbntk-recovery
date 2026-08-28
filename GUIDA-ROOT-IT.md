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

**Conclusione**: tre endpoint diversi, stesso esito negativo, è un indizio abbastanza forte che TIM abbia sistemato questa classe di vulnerabilità di command injection nella versione 2.4.5 (le note di rooting originali erano per la 1.0.3, molto più vecchia).

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

Analizzando le pagine del pannello admin (nessun link/pulsante di firmware upgrade risulta esposto da nessuna parte in questa skin TIM — probabilmente rimosso deliberatamente), si è trovato che il tile "Gateway" → tab "Configuration" espone comunque **Export/Import Configuration** nativi:

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

## Vedi anche

[`GUIDA-IT.md`](GUIDA-IT.md) — la guida di recovery firmware che precede questo tentativo di rooting.

[`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) — analisi del formato `.rbi` usato da questi firmware (header, cifratura AES, blocco "firma") e confronto tra le versioni disponibili.
