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

## 7. Aperture / da verificare

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
