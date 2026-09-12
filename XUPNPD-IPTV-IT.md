# XUPnP / xupnpd — relay UPnP/DLNA IPTV per client senza multicast (es. Fire TV Stick)

Scritto su un'unità DGA4130/VBNT-K già rootata (modgui/Ansuel), con l'obiettivo
di avere un decoder/relay IPTV raggiungibile da un client UPnP/DLNA dietro il
modem (tipicamente una Fire TV Stick, che non supporta nativamente il
multicast IPTV che molti ISP usano per distribuire i canali).

## 1. Il bug del flag "installato" nell'App Store di modgui

Il pannello modgui (`http://<router>:4044/ui/` una volta installato) offre
XUPnP come app installabile dall'"App Store" integrato. Se l'installazione
viene avviata e il download fallisce, **il flag UCI resta comunque impostato
su "installato"** — bug reale, non specifico di questa unità: vedi
[Ansuel/tch-nginx-gui#940](https://github.com/Ansuel/tch-nginx-gui/issues/940)
per un report identico su un altro DGA4130.

Causa: `app_xupnp()` in
`/usr/share/transformer/scripts/appInstallRemoveUtility.sh` esegue
`opkg install xupnpd` e imposta `modgui.app.xupnp_app="1"` **senza controllare
l'esito** del comando. Fix e istruzioni: [`xupnpd-iptv/appInstallRemoveUtility.sh.patch.md`](xupnpd-iptv/appInstallRemoveUtility.sh.patch.md).

## 2. Il pacchetto `xupnpd` non è più ottenibile da nessun feed opkg noto

A differenza di molte altre app di modgui, `xupnpd` **non fa parte del feed
generico Ansuel `GUI_ipk`** (verificato sulle cartelle `base/`, `packages/`,
`routing/`, `telephony/`, `target/packages/` del branch `kernel-4.1`, che
altrimenti combacia con il kernel 4.1.52 di questa famiglia di router). I
repository comunitari che un tempo lo distribuivano
(`repository.ilpuntotecnico(eadsl).com/.../roleo/public/agtef/...`) sono
entrambi offline. Anche il sito ufficiale del progetto (`xupnpd.org`) è
scaduto ed è stato occupato da un sito di terze parti non correlato —
**non fidarsi di link trovati lì**.

L'unica strada rimasta è compilare xupnpd dal sorgente ufficiale:
[clark15b/xupnpd](https://github.com/clark15b/xupnpd) (C++ + Lua 5.3
incorporato, nessuna release pubblicata, solo sorgente).

## 3. Cross-compilazione per l'ABI esatta di questo router

L'ABI del target **non** è quella "ovvia": pur avendo una CPU Cortex-A9
(capace di VFP), questa build OpenWrt/TCH usa **soft-float**, non hard-float.
Verificato scaricando `/bin/busybox` dal router e ispezionandolo con
`readelf -A` / `readelf -h`:

```
ELF 32-bit LSB executable, ARM, EABI5 version 1 (SYSV) ...
Flags: 0x5000200, Version5 EABI, soft-float ABI
```

userland dinamico ma con **glibc 2.27** (vecchia, 2018).

Toolchain e problemi incontrati, in ordine:

1. **Bootlin non distribuisce più un toolchain `armv7-eabi` (soft-float)**
   standalone — solo `armv7-eabihf` (hard-float), che su questo router
   crasherebbe su qualunque operazione floating point (convenzione di
   chiamata diversa). Usato invece il pacchetto Debian
   `gcc-arm-linux-gnueabi` / `g++-arm-linux-gnueabi` / `libc6-dev-armel-cross`
   (armel = soft-float, corretto).
2. Il toolchain Debian porta **glibc 2.41** per il target — troppo recente
   per il linking dinamico contro la 2.27 del router (rischio concreto di
   `GLIBC_2.3x not found` a runtime). **Fix: link statico**
   (`-static -marm -march=armv7-a -mfloat-abi=soft`), che elimina del tutto
   la dipendenza da una glibc runtime — vedi
   [`xupnpd-iptv/Makefile.armel-tim`](xupnpd-iptv/Makefile.armel-tim).
   Effetto collaterale noto: `dlopen`/`gethostbyname` restano fragili in un
   binario glibc statico (warning al link), quindi la risoluzione DNS per
   nome host nel binario potrebbe non essere affidabile — non un problema
   per il relay via IP/multicast, che è l'uso primario.
3. Il `rules.mk` di xupnpd si aspetta che la cartella Lua (`lua-5.3.5/`)
   contenga direttamente i sorgenti `.c` di Lua, non l'estrazione completa
   del tarball con un proprio `src/`. Serve appiattire di un livello:
   `mv lua-5.3.5/src/* lua-5.3.5/ && rmdir lua-5.3.5/src` prima della build,
   altrimenti `make -C lua-5.3.5 a` fallisce con "No rule to make target 'a'".

## 4. Deploy sul router

Copiato l'intero albero runtime — non solo il binario e i file `.lua`
dell'app, ma anche `www/`, `ui/`, `plugins/`, `profiles/`, `config/` dal
repo compilato — su **`/opt/xupnpd`, su storage USB** (non sull'overlay
interno, che su questi router ha tipicamente solo poche decine di MB
liberi).

Attenzione: `xupnpd.lua` deve iniziare con `cfg={}` e terminare con
`dofile('xupnpd_main.lua')` — è quella riga che avvia davvero il server.
Un primo tentativo di configurazione "ritagliata a mano" senza queste due
righe ha prodotto un crash-loop sotto procd
(`xupnpd.lua:2: attempt to index a nil value (global 'cfg')`). Partire
sempre dal template upstream e modificare solo le righe necessarie — vedi
[`xupnpd-iptv/xupnpd.lua.example`](xupnpd-iptv/xupnpd.lua.example) per le
righe che vanno effettivamente cambiate (interfaccia LAN, interfaccia
multicast IPTV, porta HTTP).

Servizio procd: [`xupnpd-iptv/xupnpd.init`](xupnpd-iptv/xupnpd.init)
(`/etc/init.d/xupnpd`, avvio automatico al boot).

Per mantenere coerente l'App Store di modgui con lo stato reale:

```sh
ln -sfn /opt/xupnpd /usr/share/xupnpd   # 04_config.sh rileva l'app da questa dir
uci set modgui.app.xupnp_app=1
uci commit modgui
```

## 5. Verifica

```sh
curl -s -D - -o /dev/null http://<router-ip>:4044/
# HTTP/1.1 301 Moved Permanently
# Server: eXtensible UPnP agent
# Location: ui/
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://<router-ip>:4044/ui/
# HTTP 200
```

Nota: il servizio si lega all'IP della LAN bridge (`br-lan`), non a
`127.0.0.1` — un `curl` da locale sul router va indirizzato all'IP LAN, non
al loopback.

## 6. Dal player vuoto al catalogo canali reale (Broadpeak nanoCDN)

Un xupnpd appena installato è un player UPnP/DLNA senza contenuti: serve un
catalogo canali. Su questo operatore quel catalogo non è una playlist
statica: è generato in tempo reale dallo stesso stack Broadpeak nanoCDN
(`nanocdn-core`/`nanocdn-rr`, vedi
[`NETWORK-SECURITY-IT.md`](NETWORK-SECURITY-IT.md) §7) che il router usa già
per il decoder ufficiale dell'operatore.

### 6.1 Il formato del catalogo live

`nanocdn-core` riceve sullo stesso control channel multicast documentato in
§7 (`239.200.0.0:5004`, sulla VLAN IPTV dedicata) un elenco testuale,
aggiornato periodicamente, con righe in questo schema:

```
<host-cdn-origine>/<path-canale>;mi=<ip-multicast>&mp=<porta>&sri=<nome-flusso>&...&rto=<timeout>
```

`host-cdn-origine` è un hostname della CDN interna dell'operatore (dominio
del tipo `*.cb.<cdn-operatore>.it`, oppure un dominio di terze parti per
contenuti in partnership con provider esterni), `mi`/`mp` sono
indirizzo/porta del flusso multicast corrispondente, `sri` un identificativo
di sessione. Questi parametri hanno una finestra di validità breve: un
catalogo non aggiornato produce entry che raggiungono davvero la CDN
dell'operatore ma rispondono 404, perché quella sessione specifica non
esiste più.

Un piccolo script che tiene d'occhio quel file e lo traduce in una playlist
M3U (una riga `#EXTINF` più l'URL origine, verbatim) copre il caso semplice:
basta referenziarla nella tabella `playlist={}` del
[`xupnpd.lua.example`](xupnpd-iptv/xupnpd.lua.example) di questo repo. Il
punto delicato è che va rigenerata di continuo, non letta una volta sola al
boot.

### 6.2 Perché quegli URL non funzionano out-of-the-box

Gli hostname del catalogo appartengono alla CDN dell'operatore, raggiungibile
pubblicamente su Internet. Sul decoder ufficiale dell'operatore, questi
stessi hostname vengono risolti localmente all'IP del router tramite
una voce DNS dedicata (`dnsmasq`), invece che verso Internet: il router
stesso li serve tramite il modulo "Request Router" di nanoCDN
(`nanocdn-rr`), che si comporta come un proxy HTTP basato sull'header
`Host:` della richiesta — se combacia con un hostname CDN noto, risponde
dal buffer multicast locale, altrimenti inoltra la richiesta alla vera CDN.

Per usare xupnpd allo stesso modo (dato che gira anch'esso sul router)
serve replicare la stessa voce DNS locale per gli hostname del catalogo, più
una regola NAT che indirizzi le richieste HTTP verso la porta reale su cui
ascolta `nanocdn-rr` (vedi l'aggiornamento in
[`NETWORK-SECURITY-IT.md`](NETWORK-SECURITY-IT.md) §7 sulla vera porta,
diversa da quella nel file di config) — sia sul traffico proveniente dalla
LAN sia su quello generato dal router stesso, dato che xupnpd fa la
richiesta HTTP server-side in locale.

### 6.3 Insidia di versione: config più nuovo del binario

Se si tenta di far ripartire `nanocdn-rr` con il file di configurazione
condiviso attuale (`--conf`), è plausibile un fallimento di bind totale (vedi
l'aggiornamento in §7 di [`NETWORK-SECURITY-IT.md`](NETWORK-SECURITY-IT.md)):
il config viene aggiornato da remoto dall'operatore (canale ACS/CWMP, già
documentato in questo repo), mentre il binario installato sul firmware resta
fermo alla versione con cui il router è stato rootato — un disallineamento
che si manifesta con opzioni `rr-*` sconosciute nei log. In quel caso
l'unico modo osservato per riportarlo in uno stato funzionante è avviarlo
senza `--conf` (sui default compilati): si perdono le impostazioni avanzate
del file, ma il relay HTTP di base — quello che serve a xupnpd — torna
operativo.

## Passi successivi (non coperti qui)

- Configurare un client UPnP/DLNA sul dispositivo che deve riprodurre i
  canali (es. BubbleUPnP o VLC su Fire TV Stick).
