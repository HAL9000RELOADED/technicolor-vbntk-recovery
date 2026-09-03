# AGTEF 1.1.3 — build NON UFFICIALE (root pre-abilitato) derivata da 1.0.3

> ⚠️ **Disclaimer — leggere prima di tutto.** Questa immagine firmware **non è una release stock genuina Technicolor.** È una **build modificata dalla community**, derivata dallo stock `1.0.3`, con accesso root/shell **deliberatamente pre-abilitato**. È documentata qui solo per completezza e tracciabilità della provenienza: **non** fa parte della linea di versioni ufficiali AGTEF trattata in [`VERSION-CHANGELOG-IT.md`](VERSION-CHANGELOG-IT.md) e in [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md), e non va confusa con essa né inserita in un changelog ufficiale.

Analisi a livello di byte dell'immagine `1.1.3` a confronto con lo stock `1.0.3` da cui deriva. Come per gli altri documenti del repo, ci si riferisce alle immagini solo per numero di versione (`1.0.3`, `1.1.3`), non per percorso di file locale.

## 1. Kernel — identico byte-per-byte a 1.0.3

Il corpo kernel completamente decompresso di `1.1.3` ha lo **stesso sha256** dello stock `1.0.3`. Stesso banner:

`Linux version 3.4.11-rt19 (repowrt-builder@9c0b3ba154ab) (gcc version 4.6.4 (OpenWrt/Linaro GCC 4.6-2013.05 r49389) ) #1 SMP PREEMPT Thu Mar 9 02:50:43 UTC 2017`

Stesso layout header esterno/mini-header documentato in [`FIRMWARE-INTERNALS-IT.md`](FIRMWARE-INTERNALS-IT.md) §2.3 (header 26 byte → mini-header 12 byte con `load_addr = 0xc0008000` → stream LZMA_ALONE, props `0x6d`, dizionario 4 MiB, single-wrapped come tutte le versioni pre-2.4).

Questo dimostra che `1.1.3` **non ha comportato alcun lavoro sul kernel**: l'etichetta di versione "1.1.3" **non corrisponde ad alcuna ricompilazione reale del kernel**, ma solo a una patch del rootfs sopra `1.0.3`.

## 2. Rootfs — quasi identico a 1.0.3

Entrambi i rootfs estraggono a **esattamente 3708 file**. Un diff ricorsivo completo (`diff -rq`, ext4 nativo su WSL, entrambi gli squashfs estratti dalle rispettive immagini raw decifrate) trova solo **due modifiche funzionalmente rilevanti**, più qualche rumore di build-artifact (alcuni mismatch placeholder file-speciale-vs-directory per `etc/cups/certs`, `etc/mtab`, `var` — rumore di packaging/tool di build, non significativo).

### 2.1 `etc/config/dropbear` — accesso SSH root abilitato

| Voce | Stock 1.0.3 | 1.1.3 |
|---|---|---|
| `option enable` | `'0'` | `'1'` |
| `option RootPasswordAuth` | `'off'` | `'on'` |
| `option RootLogin` | *(assente)* | `'1'` *(riga aggiunta)* |

### 2.2 `etc/inittab` — console seriale con shell diretta

La console seriale passa da un prompt `/bin/login` commentato (disabilitato) a una shell diretta attiva e non commentata:

- Stock 1.0.3: `#::askconsole:/bin/login` *(disabilitata)*
- 1.1.3: `::askconsole:/bin/ash` *(abilitata)*

Da notare: punta direttamente a `/bin/ash`, **scavalcando del tutto qualsiasi prompt di login/autenticazione** sulla console seriale — un vettore di accesso più diretto della modifica SSH.

### 2.3 `etc/passwd` e `etc/shadow` — identici allo stock

`etc/passwd` ed `etc/shadow` sono **identici byte-per-byte** allo stock `1.0.3`: la patch **non** imposta alcuna password di root personalizzata.

## 3. Contesto — lo stock 1.0.3 spedisce root senza password

Questo non è un problema specifico di `1.1.3`, ma è ciò che rende la patch così minimale. Lo stock `1.0.3` di suo spedisce nel proprio `/etc/shadow` l'utente root con il **campo hash password vuoto**:

`root::0:0:99999:7:::`  *(il secondo campo separato da `:`, l'hash della password, è vuoto)*

e il suo `/etc/passwd` usa già `/bin/ash` come shell di root (non una shell ristretta). È per questo che la patch `1.1.3` è così minimale: non deve né crackare né impostare una password — abilitare dropbear (il cui `RootPasswordAuth=on`, combinato con un hash shadow vuoto, può accettare una password vuota/qualsiasi a seconda di come dropbear stesso la gestisce) e/o puntare la console direttamente a `/bin/ash` sono già ciascuno sufficienti a raggiungere una shell root, perché non c'è alcuna vera password da superare.

Va detto in modo fattuale e neutro: è una caratteristica documentata di una baseline firmware vecchia di anni e non più corrente, **non** un exploit azionabile contro hardware attuale.

## 4. Conclusione / inquadramento

`1.1.3` si spiega meglio come una **build community di "abilitazione root"** di riferimento per il DGA4130/VBNT-K, concettualmente identica nello scopo alle successive immagini `2.2.1_PATCHED`/`2.4.5_PATCHED` già documentate in questo repo ([`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §3.7) — solo applicata a una base molto più vecchia (`1.0.3`, kernel 3.4.11) e con una tecnica leggermente diversa e più diretta (autologin di console **oltre** a SSH, invece del solo SSH). In più richiede **ancora meno** modifiche delle patch successive, perché lo shadow stock di `1.0.3` è già passwordless.

## 5. Aperture / limiti

- **Provenienza esatta non tracciata**: `1.1.3` è confermata come non-stock per struttura (kernel identico a 1.0.3 + patch di abilitazione root nel rootfs), ma l'origine precisa (autore/thread di community) non è stabilita in questo documento.
- **Comportamento di autenticazione dropbear con hash vuoto**: se `RootPasswordAuth=on` + hash shadow vuoto accetti una password vuota o qualsiasi dipende dalla gestione interna di dropbear su quella build e **non** è stato verificato dal vivo qui — la via d'accesso non ambigua è comunque la console `/bin/ash` di §2.2.
