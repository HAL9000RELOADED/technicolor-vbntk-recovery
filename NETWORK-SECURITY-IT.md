# Audit dei servizi di rete e postura firewall — VBNT-K live (2026-09-09)

Fotografia della **superficie di rete** e della configurazione dei servizi di
un Technicolor VBNT-K reale, letta in sola lettura via SSH root da un'unità
fisica rootata (firmware community della famiglia AGTEF 2.4.5, kernel 4.1.52 —
la **stessa unità** di
[`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) §4.2 e
[`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §6).

Questo file è distinto dal resto del repo (che analizza **formato/layout e
reverse engineering statico** del firmware): qui si documenta la **postura di
sicurezza live** di un'unità in esercizio — quali porte sono esposte, come
sono autenticate, quali servizi sono attivi e quali dormienti. Tutto ricavato
da `uci show`, tabelle firewall e stato dei servizi sull'unità; **niente è
stato modificato**.

> **Ambito e limiti.** È uno snapshot puntuale di **una** unità, con la sua
> configurazione (in parte modificata dal firmware community, vedi §3). Non è
> una valutazione dello stock TIM di fabbrica, né vale automaticamente per
> altre varianti/versioni. Dati sensibili (IP LAN interni, IP pubblico WAN,
> SSID/password, credenziali PPPoE/SIP/DDNS, byte di chiavi/certificati)
> **non sono riportati**; gli hostname ACS dell'operatore sono endpoint
> pubblici e vengono riportati (coerente con la convenzione già usata nel
> repo per la fonia/ACS).

## 1. Firewall — default deny/reject solido su WAN (Osservato)

La policy di default verso la WAN è **chiusa**: i servizi di gestione sono
tutti bloccati esplicitamente dall'esterno.

| Servizio | Porta | Esposizione WAN |
|---|---|---|
| SSH (dropbear) | 22 | bloccato |
| Web UI | 80 / 443 (+ porte accessorie) | bloccato |
| SMB / CIFS | 445 / 139 | bloccato |
| CUPS (stampa) | 631 | bloccato |

Nessuno di questi è raggiungibile dalla WAN nella configurazione osservata.
L'unica eccezione rilevante è il canale di gestione remota dell'operatore
(CWMP/TR-069), trattato in §2.

## 2. CWMP / TR-069 — unica superficie WAN reale (Osservato)

La porta **7170/tcp** (Connection Request TR-069) è **aperta a tutta la WAN**:

```
connectionrequest_allowedips = '0.0.0.0/0,::/0'
```

Non è però un accesso libero: è protetta da **HTTP Digest Authentication**
(`connectionrequest_auth = '2'`) con **throttling** (limite osservato: ~200
tentativi / 60 s). La superficie di attacco reale è quindi un **brute-force
contro il digest**, non un bypass di autenticazione — l'endpoint richiede
credenziali valide prima di fare alcunché.

Il canale verso l'ACS in uscita è invece **TLS forzato con verifica completa
del certificato**:

```
enforce_https = 1
ssl_verifypeer = 1        (certificati in /etc/ssl/acs-cert/)
```

**Due profili ACS** configurati:

| Profilo | Endpoint | Uso | Polling |
|---|---|---|---|
| Primario | `regman-tl.interbusiness.it:10700` | TIM business | no polling periodico, solo push |
| Secondario | `mobile.acs.tim.it:11201` | TIM mobile / LTE | polling attivo |

## 3. Gate anti-OTA automatico del firmware community (Osservato)

Scoperta rilevante specifica di **questa** build community: un flag custom
intercetta le richieste di upgrade push dell'ACS e **non** esegue
l'aggiornamento automaticamente.

```
modgui.var.disable_cwmp_update = '1'
```

Con questo flag attivo, un push OTA dall'operatore **non** produce un flash
silenzioso: l'upgrade richiede approvazione manuale dal pannello Modgui.
Questo cambia la valutazione del rischio "l'operatore mi reflasha da remoto e
perdo il root": su questa unità quel percorso è disinnescato a livello di
firmware. (Si collega alla verifica firma lato device di
[`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §6: anche il path `sysupgrade` verrebbe
comunque sottoposto ai controlli di firma/header lì descritti.)

## 4. UPnP attivo (Osservato)

Il demone **`miniupnpd-igdv2`** è attivo e, al momento dell'audit, aveva
forward dinamici verso host della LAN interna (IP specifici **non riportati**
— si generalizzano come "host LAN interni"). Nessun controllo aggiuntivo
osservato oltre a quelli standard IGDv2. Da tenere presente come superficie
LAN-side: un'app/host interno compromesso può aprire forward automaticamente.

## 5. Servizi già noti — confermati spenti/disabilitati (Osservato)

Servizi già citati in sessioni precedenti, ricontrollati qui e confermati
**disabilitati**: `iperf`, `urlfilterd`, `dnsfilterd`, `gre-hotspotd`. Nessuno
di questi è in ascolto.

**Nessun log o telemetria verso server esterni** è stato rilevato in questa
sessione (oltre al canale ACS legittimo di §2 e al broker MQTT locale di §6,
che è locale).

## 6. Sezioni UCI mai documentate prima nel repo (Osservato)

### 6.1 `wifi_doctor_agent`

Agente cloud di terze parti per la diagnostica WiFi, con OAuth2 verso
`device-auth-ap.wifi-doctor.org`. **Attualmente `enabled = '0'`** — presente
nel firmware ma disattivato. Segnalato perché è un canale di telemetria
cloud-side che, se abilitato, invierebbe dati diagnostici a un terzo: da
tenere d'occhio su unità dove risultasse attivo.

### 6.2 `mosquitto`

Broker MQTT **locale** con TLS mutual-cert su `:8883` (il certificato client
corrispondente è l'infoblock `/proc/rip/011a.cert`, vedi
[`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) §4.3).

**Consumatore identificato (2026-09-11)**: è **`wifi_doctor_agent`**, lo
stesso componente di §6.1. La libreria `/usr/lib/libwifidoctoragent.so`
contiene un client MQTT completo (linka `libmosquitto`, stringhe come
`[fhc] Established connection to MQTT broker`, `Using secure MQTT
connection`, `chain.pem`) che referenzia esattamente lo stesso percorso
`/tmp/certs/` usato dal listener TLS di mosquitto. Il plugin di
autenticazione lato server (`/usr/lib/mosquitto/wd_auth_plugin.so`) contiene
la stringa `wd_auth` — stesso prefisso "WD" (WiFi Doctor). La UCI di
`wifi_doctor_agent` conferma la relazione: la sezione `app_support` si
autodichiara `is_broker='1'`.

**Ma sull'unità osservata l'intera catena risulta dormiente**, nonostante
alcuni flag UCI individualmente accesi (`app_support.enable='1'`,
`fhc.enable='1'`, `fhc_master.enable='1'`, mentre il toggle cloud principale
`wifi_doctor_agent.config.enabled` resta `'0'` come già in §6.1): `/tmp/certs/`
non esiste, **nessun processo su tutto il sistema ha `libwifidoctoragent.so`
mappato in memoria** (verificato scansionando `/proc/*/maps` per ogni PID),
nessuno script `/etc/init.d/` la referenzia, e mosquitto stesso non ha né un
PID reale né una porta in ascolto (`8883`/`1883` assenti da `ss -tln`) —
nonostante `/etc/init.d/mosquitto status` risponda "running" (falso
positivo: il controllo di stato non verifica la liveness reale del
processo). In sintesi: il broker esiste come infrastruttura pronta all'uso,
ma su questa unità non c'è attualmente nulla che lo avvii né nulla che vi si
connetta.

### 6.3 Dropbear — profili `wan` (WAN, dormiente) e `afg` (LAN, attivo)

La configurazione dropbear contiene due profili distinti con root-login
abilitato, da non confondere:

- **`afg`** — limitato a `Interface='lan'`: non raggiungibile da
  Internet/WAN. È il profilo **attivo**, usato per l'accesso amministrativo
  SSH documentato in [`GUIDA-ROOT-IT.md`](GUIDA-ROOT-IT.md) (sezione
  "Aggiornamento 2026-09-09: root ottenuto per via indiretta") — quindi non
  rilevante per l'esposizione WAN che è l'oggetto di questo audit.
- **`wan`** — il profilo che, in astratto, conterebbe per un'esposizione SSH
  su Internet, risulta **disabilitato**:

```
dropbear.wan.enable = '0'
```

Quindi **nessuna esposizione SSH sulla WAN è attiva** — ma la capacità è
**dormiente** nella configurazione del profilo `wan` (basterebbe un
`enable='1'` per attivarla). Vale la pena saperlo: un attaccante che
ottenesse accesso in scrittura alla config potrebbe riattivare SSH WAN senza
aggiungere nulla di nuovo. Coerente con l'evoluzione dropbear documentata in
[`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §3.2.

## 7. Broadpeak nanoCDN / MABR, il redirector IPTV — conflitto di bind tra due istanze (Osservato, 2026-09-09)

`system.mabr.enabled = '1'`. `/etc/init.d/nanocdn` (procd) avvia **due**
binari distinti dallo **stesso** file di configurazione condiviso
(`/etc/broadpeak/nanocdn.conf`): `nanocdn-core` e `nanocdn-rr` ("Request
Router"). Poiché entrambi leggono tutte le righe dello stesso file, ciascuno
logga `unknown option` per i flag CLI che non riconosce (le opzioni
dell'altro binario) — rumore atteso, non un errore.

**`nanocdn-core` funziona correttamente**: stabile, build brandizzata TIM
(`v2.6.2@5365-tim`), in ascolto su `18081`, risponde a `/nanocdnstatus.xml`,
`/crossdomain.xml` e `/clientaccesspolicy.xml` con contenuto valido.

**BkStbA**
`BkStbA` è la libreria client Broadpeak per la ricezione IPTV multicast
(versione `BkStbA 2.2.0`, modulo `msync_bkstba`), integrata staticamente in
`nanocdn-core`.
**`BkStbA_SetNewLiveChannel` e `BkStbA_CreateLiveStream` sono funzioni di
libreria C interne** (viste nelle stringhe come riferimenti a
`BkStbA.c:<riga>`, mai come percorsi HTTP) — gestiscono il join/leave del
gruppo multicast, il **Fast Channel Change (FCC)**, il **retry RTP in
unicast** per i pacchetti multicast persi, e il **FEC** (correzione errori
in avanti). Non risultano raggiungibili da rete come endpoint HTTP in questo
binario — sono l'API con cui il *resto* del codice di `nanocdn-core`
comanda la libreria, non qualcosa che uno STB esterno invoca direttamente.

Dalle stringhe emergono anche altri percorsi in stile URL, la cui direzione
(esposti da `nanocdn-core` in ingresso su `18081`, oppure template usati da
`nanocdn-core` stesso per richieste in uscita) **non è confermata solo dalle
stringhe** — coerente col fatto che il file serve già `crossdomain.xml`/
`clientaccesspolicy.xml` in ingresso, il che rende plausibile ma non certa
un'esposizione lato server: `/QualityLevels(`, `/Fragments(`, `/Segment`,
`/Level`, `/Alter` — sintassi di richiesta **Microsoft Smooth Streaming** per
manifest/segmenti ABR (conferma precisa dell'ipotesi precedente "pattern in
stile Flash/Silverlight", ora identificata come sintassi MSS standard) — e
`/nservices/metricsReceiver` (nome coerente con un endpoint di raccolta
metriche, verosimilmente ricevuto piuttosto che richiesto, ma non verificato).
Stesso livello di incertezza per `/GetBkeServerList`, che compare come
stringa isolata; la direzione (se è `nanocdn-core` a
richiederlo a un backend Broadpeak/operatore, o se lo espone lui stesso) non
è determinabile dalle sole stringhe e non è stata testata.

Il quadro complessivo è quindi quello di un **redirector/relay IPTV
multicast standard per i canali lineari inclusi nell'abbonamento**
(join multicast + FCC + retry RTP + ABR via Smooth Streaming) — una
tecnologia telco-IPTV comune.

**`nanocdn-rr` va in crash-loop continuo** (`ERROR could not bind to any
interface`, rilanciato da `procd` ogni ~5s, `respawn 3600 5 0`). Escluse come
cause, ciascuna verificata indipendentemente sull'unità live:
- **Non** è il kill-switch anti-root dell'operatore:
  `env.var.unlockedstatus = '0'` (questo metodo di root non fa scattare quel
  flag, quindi la logica firmware `nanocdn stop`-su-unlock, presente altrove
  negli uci-defaults di questa build, non si attiva mai).
- **Non** sono certificati TLS mancanti: `/etc/broadpeak/certs/` ha una
  bundle CA completa e intatta.
- **Non** è irraggiungibilità del backend CDN: l'host CDN dell'operatore
  referenziato in `smartlib-conf` è raggiungibile e risponde in HTTPS.
- **Non** è un conflitto di porta TCP sul valore di `rr-nano-addr`:
  cambiarlo (`18081` → `18082`) e riavviare il servizio non ha avuto
  **alcun effetto** sull'errore — questo esclude che `rr-nano-addr` sia la
  porta di ascolto propria di `nanocdn-rr`; è più probabile che sia
  l'indirizzo con cui `nanocdn-rr` raggiunge `nanocdn-core` come upstream,
  non qualcosa su cui fa bind.

**Ipotesi residua meglio supportata**: entrambi i binari provano ad aprire il
proprio "control channel multicast receiver" (stringa nel binario: `Control
channel multicast receiver started on multicast '%s:%s'`) sull'identico
valore `controlchannel-multicast=239.200.0.0:5004`, sulla stessa interfaccia
(`br-lan`). `nanocdn-core` parte per primo (ordine nello script) e vince il
bind; il tentativo successivo di `nanocdn-rr` fallisce, e il binario riporta
un messaggio generico "any interface" invece di uno specifico "indirizzo già
in uso" — plausibile se il socket multicast in ricezione non viene aperto con
`SO_REUSEADDR`/`SO_REUSEPORT`. Questo è coerente con la suddivisione di ruoli
documentata da Broadpeak stessa (`nanocdn-rr` è il "Request Router" di
bilanciamento **tra più** istanze `nanocdn-core`, un pattern reale da
CDN a scala) — su una CPE domestica single-box con esattamente una
`nanocdn-core`, i due sono strutturalmente ridondanti e non sembrano
progettati/testati per coesistere sullo stesso host/interfaccia.

**Fix applicato su questa unità**: il blocco istanza `nanocdn-rr` è stato
rimosso da `/etc/init.d/nanocdn` (`procd_open_instance nanocdn-rr` ...
`procd_close_instance`), il blocco di `nanocdn-core` lasciato intatto (backup
dello script originale conservato accanto). Confermato dopo il riavvio:
`nanocdn-core` resta stabile e in ascolto su `18081`, nessun altro
crash-loop, nessuna regressione funzionale osservata (il ruolo di redirector
IPTV — quello effettivamente utile — non dipende dalla presenza di
`nanocdn-rr`).

### Aggiornamento (2026-09-12, seconda unità stessa famiglia) — `nanocdn-rr` avviato con successo dal vivo: causa del bind-fail ridefinita

Su una seconda unità della stessa famiglia (DGA4130/VBNT-K), `nanocdn-rr` non
era in crash-loop ma **sopravviveva come processo orfano** da un avvio
precedente, in ascolto e **funzionante** sulla porta TCP **8000** — non
`18081`/`18082` come nel file di configurazione condiviso. Questo ha permesso
di osservarne per la prima volta il comportamento reale quando riesce a
partire: è un **reverse proxy HTTP trasparente basato sull'header `Host:`**
della richiesta — se combacia con uno degli hostname CDN dell'operatore
elencati in `smartlib-conf`, inoltra la richiesta alla vera CDN (confermato
da header `Via:` con hostname reali della dorsale dell'operatore nella
risposta) oppure la serve dal buffer multicast locale.

Riavviandolo a mano con lo stesso `--conf` condiviso, il fallimento di bind si
riproduce identico (`ERROR could not bind to any interface`) — ma il log,
letto per intero, mostra `unknown option` anche per diverse direttive **nel
proprio namespace** (prefisso `rr-*`, quindi non riconducibili "all'altro
binario" come ipotizzato sopra), assenti da qualsiasi build più vecchia:
segno che il file di configurazione condiviso — aggiornato da remoto
dall'operatore via il canale ACS/CWMP di §2 — è ora scritto per uno
schema/versione del protocollo Broadpeak più recente di quella che il
binario installato su questo firmware riconosce. Avviato invece **senza
alcun file di configurazione** (sui default compilati), il bind su
`0.0.0.0:8000` riesce sempre, e il relay funziona come descritto sopra.

Questo non esclude l'ipotesi originale (bind-race sul control channel
multicast condiviso con `nanocdn-core`) come concausa — non è stato ripetuto
il test specifico su questa seconda unità — ma aggiunge un fattore concreto e
riproducibile, il disallineamento di versione config/binario. Il fix già
documentato sopra (rimuovere l'istanza da `/etc/init.d/nanocdn`) resta valido
come misura di stabilità; per chi ha invece bisogno del relay HTTP di
`nanocdn-rr` (utile ad esempio per bridge UPnP/DLNA di terze parti, vedi
[`XUPNPD-IPTV-IT.md`](XUPNPD-IPTV-IT.md) §6), l'unica modalità osservata
funzionante è avviarlo a parte, senza `--conf`.

## 8. ⚠️ `wifi-nurse-modal.lp` non è una GET di sola lettura sicura (Osservato, 2026-09-09)

Una semplice `GET /modals/wifi-nurse-modal.lp` è stata osservata, su questa
stessa classe di unità, innescare **logica di scrittura lato server** invece
di restituire solo una pagina di stato: quando eseguita mentre la
connettività WAN/ACS non è disponibile (es. durante lavoro di root/recovery
con WAN scollegata di proposito, o qualunque altra condizione in cui i dati
di branding attesi non sono raggiungibili), ha sovrascritto la config UCI
`wireless` **live** — SSID **e** `wpa_psk_key`/`wep_key`/`wps_ap_pin` su tutte
e quattro le sezioni `wifi-iface` — con la stringa placeholder di fabbrica del
firmware `SET_BY_SCRIPT` (confermata hardcoded in `/etc/config/wireless` in
diversi dump firmware studiati per questo repo, pensata per essere
sovrascritta dal branding di prima attivazione). Questo ha fatto cadere ogni
client WiFi associato (hanno visto l'SSID letteralmente rinominato) fino alla
correzione.

**Implicazione pratica per chi scansiona/enumera gli endpoint `.lp` di questa
web UI** (vedi anche le linee guida sul pacing già stabilite per questa
classe di webserver embedded Lua/nginx): trattare `wifi-nurse-modal.lp` — e
per estensione qualunque altro endpoint il cui nome implichi un'azione attiva
di "fix/nurse/diagnose" piuttosto che una visualizzazione passiva di stato —
come un'operazione di **scrittura**, non una lettura sicura.
`cwmpconf-modal.lp` (config CWMP/ACS) porta lo stesso tipo di rischio e
andrebbe escluso dalle scansioni di routine per lo stesso motivo.

## 9. VoIP/SIP: "cliente non raggiungibile" nonostante stato "Registrato" — binding stantio lato SBC dell'operatore (Osservato/Risolto, 2026-09-11)

Sintomo: chiamando il numero fisso (fonia via `mmpbxd`, profilo SIP verso
registrar `telecomitalia.it` / proxy `88.50.251.167:5060`) da un cellulare di
rete terza, l'operatore mobile chiamante rispondeva "il cliente da lei
chiamato non è momentaneamente raggiungibile" — nonostante il pannello Modgui
e lo stato SIP locale mostrassero "Registrato".

Percorso diagnostico (tutto in sola lettura via SSH root, nessuna modifica
fino al fix finale):

1. **Config e stato del servizio** (`uci show mmpbx*`): profilo SIP corretto
   (registrar/proxy/realm popolati, nessun placeholder residuo), processo
   `mmpbxd` in esecuzione, cicli di re-registrazione regolari ogni ~55-58
   minuti visibili in `logread` — nulla di anomalo a prima vista.
2. Trovato un incidente di deregistrazione isolato, la mattina stessa, causato
   da un fallimento di invio UDP (`errno=22`) verso il proxy SIP — durato
   circa 3 minuti, ma **non coincidente** con gli orari reali dei tentativi di
   chiamata falliti segnalati dall'utente: un falso indizio, non la causa.
3. **NAT helper (SIP ALG)**: verificato che i moduli kernel `nf_conntrack_sip`/
   `nf_nat_sip` sono caricati, ma **escluso come causa**:
   `net.netfilter.nf_conntrack_helper=0` disabilita l'auto-attach globale
   degli helper, e l'helper `sip` è assegnato solo alle zone firewall
   `lan`/`loopback`, non `wan` — dove gira il traffico SIP nativo del router,
   con IP pubblico diretto via PPPoE e nessun NAT applicato al proprio
   traffico. Il SIP ALG quindi non tocca la fonia nativa di questa unità.
4. **Test risolutivo**: cattura in diretta di `logread -f` per 60 secondi
   mentre venivano effettuati due tentativi di chiamata reali da un numero
   esterno. Risultato: **zero attività SIP/mmpbx nel log per l'intera
   finestra** — nessun INVITE è mai arrivato al router. Prova diretta che il
   problema non era sul CPE ma **a monte, nella rete/SBC dell'operatore**, che
   aveva un binding di registrazione stantio per quel numero nonostante il
   router si vedesse regolarmente registrato dal proprio lato.

**Fix**: `/etc/init.d/mmpbxd restart` (dopo aver verificato via
`ubus call mmpbxbrcmfxs.state get '{"device":"fxs_dev_N"}'` che nessuna
chiamata fosse in corso su nessuna delle due linee FXS). Questo ha prodotto un
ciclo pulito Deregister → Register Success in meno di 2 secondi, costringendo
l'SBC dell'operatore a scartare il binding obsoleto e crearne uno nuovo.
Chiamata di verifica riuscita subito dopo.

Estratto reale del log del fix (numero telefonico e IP pubblico WAN non
riportati, coerente con la policy di questo file):

```
[...] mmpbxd[9774]: SIP Registration: SIP: <numero> : Deregister
[...] mmpbxd[9774]: SIP Registration: SIP: <numero> : Register Success
```

**Perché è successo — meccanismo verificato nel codice, non solo ipotizzato**:
l'utente ha confermato di aver disabilitato manualmente l'helper SIP nella
scheda "NAT Helper" del pannello Modgui circa un minuto prima che la fonia
diventasse irraggiungibile (azione volontaria, non collegata al lavoro di
questa sessione). Analizzando il codice reale coinvolto
(`/www/docroot/modals/nat-alg-helper-modal.lp` +
`/usr/share/transformer/mappings/uci/firewall_helpers.map`) e i log dello
stesso pomeriggio è stato possibile ricostruire la catena esatta, non solo
un'ipotesi:

1. Il salvataggio del form rimuove `sip` dalla lista `firewall.lan.helper` e
   scrive su UCI (`uci commit firewall`).
2. Nel log reale delle 14:04:52 quel commit è fallito:
   `commit_err=lua-uci: I/O error` (probabile contesa/lock momentaneo — spazio
   disco e `dmesg` risultano puliti, non un problema di storage esaurito).
3. Nonostante l'errore riportato all'utente, il cambiamento è stato comunque
   applicato: `transformer[26159]` ha lanciato **`async run: /etc/init.d/firewall
   restart`** in modo asincrono, e lo ha ripetuto **6 volte** tra le 14:09 e le
   15:39 (non un singolo riavvio pulito, ma una serie di retry su un'ora e
   mezza, poi fermatisi).
4. Un `/etc/init.d/firewall restart` completo ricostruisce da zero **tutte**
   le iptables, incluse le regole dinamiche `Allow_SIP` che `mmpbxfwctl`
   mantiene per lasciar passare il traffico dal proxy TIM (`88.50.251.167`).
   Se durante uno di questi riavvii quella regola sparisce e non viene
   reinserita immediatamente (`mmpbxfwctl` la reinserisce tipicamente in
   reazione a eventi di registrazione, non monitorando proattivamente lo
   stato del firewall), le chiamate in ingresso vengono scartate **dal
   firewall locale del router stesso** — non serve un binding "stantio"
   sull'SBC dell'operatore per spiegare il sintomo.

Questa spiegazione è anche coerente con il secondo episodio della stessa
sessione ("non va più"): l'ultimo dei sei riavvii del firewall registrato è
delle 15:39:27, appena 4 minuti prima che venisse richiesto un secondo
riavvio di `mmpbxd`. Nota: non è stata catturata una finestra di log esatta
con la regola `Allow_SIP` visibilmente assente durante uno di questi riavvii
— il collegamento fra "riavvio firewall" e "finestra di chiamate perse" è
quindi il meccanismo più concreto individuato, non una prova diretta
istante-per-istante.

Resta vero che il modulo SIP ALG (`nf_conntrack_sip`/`nf_nat_sip`, §9 punto 3)
non è la causa diretta — non è assegnato alla zona `wan` e non interviene mai
sul traffico nativo di questa unità. È **il salvataggio del toggle** (con il
conseguente commit UCI fallito e la sequenza di riavvii firewall che ne è
seguita) ad aver innescato l'interruzione, non lo stato acceso/spento
dell'helper in sé — coerente col fatto che l'utente ha poi lasciato l'helper
SIP disabilitato senza che il problema si ripresentasse.

**Come applicare se si ripresenta**: se le chiamate in ingresso falliscono con
"non raggiungibile" mentre il router mostra "Registrato", non perdere tempo a
ricontrollare config SIP locale/NAT/ALG (già escluse come classe di causa) —
passare direttamente a: (1) catturare i log in diretta durante un tentativo di
chiamata reale per confermare che l'INVITE non arriva mai (firma del problema
a monte), (2) `/etc/init.d/mmpbxd restart` come fix rapido self-service, dopo
aver verificato che le linee siano libere, (3) se il restart non risolve,
escalare al supporto TIM (187/191) con il sintomo esatto, perché è uno stato
del loro SBC, non risolvibile da postazione cliente.

## 10. Aperture / da verificare

- ~~Causa interna esatta del binding stantio lato SBC (§9): non determinabile
  dal lato cliente~~ — **risolto**: trigger confermato dall'utente (toggle
  manuale dell'helper SIP nel pannello NAT Helper, ~1 minuto prima del
  sintomo). Resta ipotetico solo il meccanismo interno esatto lato SBC
  (perché un reload conntrack locale produce un binding orfano lato
  operatore) — non verificabile senza visibilità sull'SBC stesso.
- ~~Consumatore esatto del broker MQTT locale (§6.2): ipotizzato pairing app
  companion, non confermato~~ — **risolto**: è `wifi_doctor_agent`, ma
  sull'unità osservata l'intera catena (agente, certificati, broker) è
  dormiente, non un consumatore attivo.
- Non verificato se il throttling CWMP (§2, ~200/60 s) sia applicato
  per-IP o globale — cambia la valutazione della resistenza al brute-force
  distribuito.
- `wifi_doctor_agent` (§6.1): non verificato quali dati esatti invierebbe se
  abilitato, né se lo stock di fabbrica lo abbia attivo di default.
- Snapshot di una sola unità con firmware community: i valori del firewall e
  dei profili ACS potrebbero differire sullo stock TIM di fabbrica —
  non comparato in questa sessione.
- ~~Il protocollo STB-agent `BkStbA` di `nanocdn-core` (§7) non è stato
  decodificato a sufficienza per richiedere e riprodurre davvero un canale
  live~~ — **Analizzato parzialmente**: analisi
  statica delle stringhe ha stabilito che `SetNewLiveChannel` è una funzione
  di libreria C interna (non un endpoint di rete) e ha mappato la vera
  superficie HTTP (`/QualityLevels(`, `/Fragments(`, `/nservices/metricsReceiver`,
  ecc.). **Ulteriormente avanzato** (aggiornamento §7, 2026-09-12, seconda
  unità): confermato che `nanocdn-rr` (non `BkStbA` direttamente) raggiunge
  davvero la CDN dell'operatore per un'entry del catalogo canali live,
  provando il meccanismo di relay HTTP end-to-end — la riproduzione
  effettiva di un canale resta non raggiunta nel test (sessione del catalogo
  scaduta al momento della prova).
- La causa interna esatta dell'effetto collaterale di scrittura config di
  `wifi-nurse-modal.lp` (§8) — sotto quali condizioni scatta, e se sia
  riproducibile deliberatamente — non è stata isolata ulteriormente:
  osservata una volta, empiricamente, non forzata.
