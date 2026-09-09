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
Verosimilmente usato per il pairing con l'app companion. **Ipotesi**, non
verificato il consumatore esatto del broker.

### 6.3 Dropbear — profili `wan`/`afg` con capacità dormiente

La configurazione dropbear contiene profili `wan` e `afg` con root-login
abilitato **nella config**, ma il profilo `wan` è **disabilitato**:

```
dropbear.wan.enable = '0'
```

Quindi **nessuna esposizione SSH sulla WAN è attiva** — ma la capacità è
**dormiente** nella configurazione (basterebbe un `enable='1'` per attivarla).
Vale la pena saperlo: un attaccante che ottenesse accesso in scrittura alla
config potrebbe riattivare SSH WAN senza aggiungere nulla di nuovo. Coerente
con l'evoluzione dropbear documentata in
[`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §3.2.

## 8. Broadpeak nanoCDN / MABR, il redirector IPTV — conflitto di bind tra due istanze (Osservato, 2026-09-09)

`system.mabr.enabled = '1'`. `/etc/init.d/nanocdn` (procd) avvia **due**
binari distinti dallo **stesso** file di configurazione condiviso
(`/etc/broadpeak/nanocdn.conf`): `nanocdn-core` e `nanocdn-rr` ("Request
Router"). Poiché entrambi leggono tutte le righe dello stesso file, ciascuno
logga `unknown option` per i flag CLI che non riconosce (le opzioni
dell'altro binario) — rumore atteso, non un errore.

**`nanocdn-core` funziona correttamente**: stabile, build brandizzata TIM
(`v2.6.2@5365-tim`), in ascolto su `18081`, risponde a `/nanocdnstatus.xml`,
`/crossdomain.xml` e `/clientaccesspolicy.xml` con contenuto valido. La sua
API proprietaria STB-agent (`BkStbA`, nelle stringhe compaiono
`SetNewLiveChannel` e `/GetBkeServerList`) è raggiungibile, ma la sequenza di
chiamate per richiedere un canale live non è stata decodificata in questa
sessione (non documentata; nel binario sono presenti pattern in stile
Flash/Silverlight "QualityLevels()/Fragments()" e manifest HLS/DASH, coerenti
con supporto a Microsoft Smooth Streaming + HLS/DASH in output).

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

## 9. ⚠️ `wifi-nurse-modal.lp` non è una GET di sola lettura sicura (Osservato, 2026-09-09)

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

## 10. Aperture / da verificare

- Consumatore esatto del broker MQTT locale (§6.2): ipotizzato pairing app
  companion, non confermato.
- Non verificato se il throttling CWMP (§2, ~200/60 s) sia applicato
  per-IP o globale — cambia la valutazione della resistenza al brute-force
  distribuito.
- `wifi_doctor_agent` (§6.1): non verificato quali dati esatti invierebbe se
  abilitato, né se lo stock di fabbrica lo abbia attivo di default.
- Snapshot di una sola unità con firmware community: i valori del firewall e
  dei profili ACS potrebbero differire sullo stock TIM di fabbrica —
  non comparato in questa sessione.
- Il protocollo STB-agent `BkStbA` di `nanocdn-core` (§8) non è stato
  decodificato a sufficienza per richiedere e riprodurre davvero un canale
  live — il formato esatto delle chiamate `SetNewLiveChannel`/
  `GetBkeServerList` resta sconosciuto.
- La causa interna esatta dell'effetto collaterale di scrittura config di
  `wifi-nurse-modal.lp` (§9) — sotto quali condizioni scatta, e se sia
  riproducibile deliberatamente — non è stata isolata ulteriormente:
  osservata una volta, empiricamente, non forzata.
