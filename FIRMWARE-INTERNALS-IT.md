# Interni del firmware AGTEF: layout kernel/squashfs, header del blob kernel, generazione di `network`, nuovi servizi

Analisi a livello di byte del contenuto dell'immagine flash da 80 MiB (il payload `0xB0` in chiaro descritto in [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §2.3), che [`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) descrive come contenuto di **un intero bank**. Questo file complementa gli altri: dove `MEMORY-ARCHITECTURE` descrive le partizioni NAND e `RBI-FORMAT` il contenitore `.rbi`, qui si guarda **dentro** l'immagine decifrata — dove finisce il kernel e inizia lo squashfs, com'è fatto l'header proprietario del blob kernel, da dove viene generato `etc/config/network` nelle build recenti, e cosa fanno davvero i servizi comparsi in 2.4.5.

Tutti i valori sono ricavati per confronto diretto tra due immagini raw decifrate: **la build 2.2.1 stock** (`AGTEF_2.2.1_CLOSED.rbi`, di seguito "221") e **la build 2.4.5 CLOSED** (`AGTEF_2.4.5_CLOSED.rbi`, di seguito "245"). Gli offset citati sono relativi all'inizio del payload raw da 83.886.080 byte (80 MiB, `0x5000000`), non al file `.rbi`.

## 1. Layout kernel/squashfs e crescita della partizione riservata

L'immagine da 80 MiB inizia con un blob kernel proprietario (§2) e più avanti contiene il filesystem root squashfs. Il punto di split **non è fisso tra le versioni**:

| Build | Inizio squashfs (`hsqs`) | Fine reale payload kernel (non-padding) | Dimensione payload kernel |
|---|---|---|---|
| 221 stock | `0x210000` (2.162.688) | `0x1ff96a` (2.095.466) | 2.095.440 byte (header escluso) |
| 245 CLOSED | `0x600000` (6.291.456) | `0x221d57` (2.235.735) | 2.235.709 byte (header escluso) |

Il magic squashfs little-endian è `hsqs` (cioè `0x73717368`, "sqsh" byte-swappato) e marca l'inizio del filesystem root all'interno del bank. Tra le due build lo spazio **riservato** al kernel passa da ~2,06 MiB (`0x210000`) a 6 MiB (`0x600000`), quasi triplicando; ma il payload kernel **reale** cresce solo da 2.095.466 a 2.235.735 byte, cioè **circa +6,7%**. Non è quindi un kernel diventato molto più grande, ma un **cambio di layout della flash**: la finestra riservata al kernel prima dello squashfs è stata allargata (e allineata a un confine di 6 MiB), lasciando ampio margine di padding fino al `hsqs`.

Questo risolve la nota lasciata aperta in [`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) §5, dove si osservava che «l'offset dello squashfs dentro l'immagine da 80MB varia per versione» citando come fonte `RBI-FORMAT-IT.md §3.2`. Quel riferimento era impreciso: la §3.2 di `RBI-FORMAT-IT.md` tratta l'evoluzione della configurazione dropbear/SSH, non gli offset dello squashfs. I valori reali (mai pubblicati finora) sono quelli della tabella qui sopra.

### 1.1 Correzione — le due build NON condividono la stessa base OpenWrt

Va corretta un'affermazione errata secondo cui 221 e 245 condividerebbero la stessa stringa OpenWrt di base (un'ipotesi iniziale di questa stessa analisi, poi corretta con verifica diretta). Verificato direttamente leggendo `etc/openwrt_release` dai rispettivi squashfs:

| Campo | 221 stock | 245 CLOSED |
|---|---|---|
| `DISTRIB_RELEASE` | `'Chaos Calmer'` | `'SNAPSHOT'` |
| `DISTRIB_REVISION` | `'unknown'` | `'r14144-e2ae576c18'` |
| `DISTRIB_TARGET` | `'brcm63xx-tch/VANTW'` | `'brcm6xxx-tch/VBNTJ_502L07p1'` |
| `DISTRIB_DESCRIPTION` | `'OpenWrt Chaos Calmer 15.05.1'` | (non `Chaos Calmer`) |
| `DISTRIB_ARCH` | — | `'arm_cortex-a9'` |

Sono due basi OpenWrt distinte: 221 è ancora su Chaos Calmer 15.05.1, 245 su una SNAPSHOT ricompilata con target e revisione completamente diversi. Questo **conferma a livello di offset/partizione** quanto già documentato in [`VERSION-CHANGELOG-DIFFS-IT.md`](VERSION-CHANGELOG-DIFFS-IT.md) sul rebuild della base OpenWrt avvenuto tra 2.2.1 e 2.3.2 — non lo contraddice: la crescita della finestra kernel e il cambio di `openwrt_release` sono due facce dello stesso rebase di piattaforma.

## 2. Header del blob kernel (decodificato) e tentativo di decompressione

Entrambe le build iniziano il blob kernel con un header proprietario fisso di **0x1a (26) byte**, seguito dal corpo compresso. Decodifica campo per campo (offset relativi all'inizio del blob):

| Offset | Byte | 221 | 245 | Significato |
|---|---|---|---|---|
| `0x00`–`0x03` | 4 | `ff ff ff ff` | `ff ff ff ff` | Sentinella fissa, identica in entrambe |
| `0x04`–`0x0b` | 8 | `00 …00` | `00 …00` | Otto byte a zero, fissi |
| `0x0c`–`0x0f` | 4 | `01 bb 00 00` | `02 34 00 00` | Valore BE a 2 byte version-dipendente + `00 00` di padding — **scopo non identificato** |
| `0x10` | 1 | `b6` | `b6` | Costante in entrambe |
| `0x11`–`0x15` | 5 | `4c 49 4e 55 0a` | `4c 49 4e 55 0a` | ASCII `LINU` + `0x0a` (line-feed) — **non** `LINUX` |
| `0x16`–`0x19` | 4 | `00 1f f9 50` | `00 22 1d 3d` | **Lunghezza payload, BE32 — risolto (§2.1)** |

### 2.1 Campo lunghezza (0x16–0x19) — risolto

Interpretando i 4 byte a `0x16` come intero big-endian:

- 221 → `0x001ff950` = 2.095.440
- 245 → `0x00221d3d` = 2.235.709

Sommando la dimensione dell'header (`0x1a` = 26 byte):

- 221 → `0x1ff950 + 0x1a = 0x1ff96a`
- 245 → `0x221d3d + 0x1a = 0x221d57`

Entrambi combaciano **byte-per-byte** con gli offset di fine payload kernel reale trovati in modo indipendente (§1). Il campo è confermato: **lunghezza del payload compresso che segue l'header**.

### 2.2 Campi ancora non identificati

- `0x0c`–`0x0f`: il valore BE a 2 byte (443 per 221, 564 per 245) cambia con la versione. Provate e scartate le ipotesi di checksum, XOR dei byte del payload, e divisore della block-size del payload: nessuna torna. Scopo **non identificato**.
- `0x11`–`0x15`: il tag `LINU\n` è identico in entrambe le build, ma il quinto byte è un line-feed `0x0a`, non `X` (`0x58`). Il motivo del troncamento/terminazione a line-feed **non è identificato** semanticamente (probabile tag fisso emesso dallo strumento di build Broadcom, non un campo interpretato).

### 2.3 Decompressione del corpo — vicolo cieco documentato

Il corpo (byte da `0x1a` alla fine del payload reale, entrambe le build) è stato attaccato con tutti i formati di compressione plausibili per un kernel Broadcom bcm63xx. **Nessuno funziona.** Documentato qui con l'evidenza, così da non ripetere il lavoro:

- **gzip** (`1f 8b`): nessun match nei primi `0x2000`/`0x4000` byte.
- **zlib/deflate** (header `78 xx` con checksum RFC1950 valido): un solo match casuale (245, `body+0x24`, `78 01`) che alla decompressione non produce output valido — falso positivo.
- **LZMA "alone" legacy** (props byte `0x5d`): nessun match nei primi `0x400` byte.
- **LZMA raw** (`FORMAT_RAW`), bruteforce completo di `lc ∈ 0–3`, `lp ∈ 0–2`, `pb ∈ 0–2`, `dict_size ∈ {1,2,4,8,16 MiB}`, offset di partenza `∈ {0,1,2,4,8,13}`: ogni combinazione fallisce **immediatamente** con dati corrotti, in entrambe le build.
- Nessun magic **uImage** (`27 05 19 56`), **ELF** (`7f 45 4c 46`) o **stub ARM zImage** (`18 28 6f 01`) presente nel corpo.
- **Entropia** del corpo ~7,95–8,0 bit/byte dall'inizio alla fine del payload reale — coerente con dati compressi o cifrati, e in particolare **assenza di uno stub decompressore a bassa entropia** prima dello stream (che ci si aspetterebbe in un `zImage` self-extracting).

Conferma indiretta dal log di boot in [`UART-BOOT-LOG-IT.md`](UART-BOOT-LOG-IT.md) (righe 153–156): il CFE stampa `Decompression OK!` poco prima del salto effettivo (`Starting program at 0x00008000`). Questo conferma che (a) il blob kernel è realmente compresso, e (b) è il **CFE stesso** a decomprimerlo internamente prima del salto.

**Conclusione.** L'header è decodificato quasi completamente: resta ignoto solo lo scopo dei campi `0x0c`–`0x0f` e il motivo esatto del tag `LINU\n`. Il corpo compresso resiste a tutti i metodi standard provati. L'ipotesi più probabile è che il CFE Broadcom usi una **variante LZMA proprietaria/non standard**, con i parametri (props, dizionario, eventuale pre-processing) hardcoded nel bootloader anziché nell'header del blob — il che spiegherebbe sia il fallimento immediato del bruteforce `FORMAT_RAW` sia l'assenza di uno stub in-band. Prossimo passo utile, **non tentato qui**: disassemblare la routine di decompressione del CFE, oppure reperire un GPL source drop Broadcom bcm963xx con il relativo `lzma.c` modificato e confrontarne i parametri.

## 3. Da dove viene generato `etc/config/network` in 2.4.5

In 245 il file `etc/config/network` **non è presente** nello squashfs, mentre in 221 c'è. Non è una regressione né una config persa: il file viene **sintetizzato al primo avvio reale**. Ricostruzione del meccanismo, con l'evidenza.

- **221**: `etc/config/network` è baked-in nello squashfs, ma contiene solo il minimo (`config interface 'loopback'` + `option ula_prefix 'auto'` in `globals`) — **non** una config di rete board-specific completa.
- `/bin/config_generate` (10.111 byte, presente identico in entrambe le build) contiene la funzione `generate_static_network()`, i cui comandi UCI embedded (`set network.loopback=...`, `set network.globals=...`) riproducono **verbatim** il contenuto del file 221. La prima riga dello script è:

  ```sh
  [ -s /etc/config/network -a -s /etc/config/system ] && exit 0
  ```

  cioè è un **no-op se i file esistono già** (è così che in 221, dove il file è presente, `config_generate` non lo tocca).
- `/etc/board.d/02_network` (presente in 245) è uno script Technicolor di board-detection: chiama `ucidef_set_interface_lan` / `ucidef_add_switch` in base al SoC rilevato. Il branch `brcm,bcm963138` corrisponde al DGA4130. È invocato via `board_config_update` / `board_config_flush`, definiti in `/lib/functions/uci-defaults.sh`.
- `/etc/init.d/boot`, funzione `boot()`, esegue in ordine:

  1. `config_generate`
  2. `uci_apply_defaults` — itera su `/etc/uci-defaults/*`, fa il source di ciascuno script e, in caso di successo, lo **autocancella** con `rm -f`
  3. `sync`

- In 245 sono presenti nel listing squashfs (proprio perché si autocancellano dopo la prima esecuzione, quindi non compaiono più su un dispositivo già avviato) gli script Technicolor `etc/uci-defaults/tch_0015-network-globals`, `tch_0020-network-lan`, `tch_0030-network-wan`. Questi completano `network` con le interfacce LAN/WAN/wireless reali (es. `wlnet_b_24`, `wlnet_b_5`) al primo boot.

**Conclusione.** In 245 il file `network` è **deliberatamente assente** dallo squashfs perché viene sintetizzato al primo avvio dalla catena `config_generate` → `board.d/02_network` → script `tch_00NN-network-*` (che si autocancellano, ecco perché non si rivedono dopo il primo boot). In 221 il file baked-in era solo lo **scheletro minimo** prodotto da `config_generate`, senza il livello di personalizzazione board.d/uci-defaults visto sopra. Il meccanismo di generazione esiste **identico** in entrambe le build (stesso `config_generate`, stesso `init.d/boot`) — cambia solo la **scelta di packaging**: includere lo scheletro minimo (221) contro ometterlo del tutto e generare tutto al primo boot (245).

## 4. Nuovi servizi in 2.4.5 — cosa fanno davvero

Servizi comparsi in 245, analizzati a livello di init script e di binario/stringhe (non solo per nome):

| Servizio | Init / attivazione | Binario | Funzione |
|---|---|---|---|
| `multiap_agent` | rc.d **S99**; regola ebtables BROUTE sul MAC di destinazione `01:80:C2:00:00:13` (multicast IEEE 1905.1) | `/usr/bin/multiap_agent` (149 KB) — stringhe `CMDU_TYPE_TOPOLOGY_*`, `lib1905_*` | Agente Wi-Fi Alliance **Multi-AP (EasyMesh)** su IEEE 1905.1 — nodo di discovery/registrazione della topologia mesh |
| `multiap_controller` | rc.d **S95**; stessa infrastruttura 1905.1 | `/usr/bin/multiap_controller` (117 KB) | Controller Multi-AP (EasyMesh) — orchestratore degli agent |
| `nanocdn` | rc.d **S99**; gated su `uci get system.mabr.enabled`; avvia `nanocdn-core` e `nanocdn-rr` via procd; legge `/etc/broadpeak/nanocdn.conf`; utente dedicato `nanocdn` | Binari `nanocdn-core`/`nanocdn-rr` **non trovati** nel listing estratto (solo l'helper Lua `/usr/bin/nanocdnMinMax.lua`, `/root/nanocdn.ipk`, staging `/root/temp_nanoCDN/`) | **Broadpeak nanoCDN** — agente CPE multicast-ABR (conversione multicast→unicast) per IPTV/OTT. `mABR` = Multicast ABR. Identificazione da path/vendor, **non** a livello di stringhe binarie |
| `wlaffinity` | **Nessun symlink rc.d** — non avviato automaticamente al boot; script POSIX puro (27.318 byte) | n/a — usa `/proc/irq/$irq/smp_affinity`, `taskset -p`, `nvram kget/kset` | Utility di **CPU-pinning** per IRQ e thread WiFi (D11 MAC, M2M) per radio — uso manuale/on-demand (header dello script: «configures interrupt & thread affinity regarding to WLAN») |
| `dnsfilter` | rc.d **S80/K10**; regole `iptables`/`ip6tables` mangle che redirigono UDP/TCP porta 53 a **NFQUEUE**; gated su config `parental` con `mode="dns"` | `/usr/sbin/dnsfilterd` (38.532 byte) — stringhe `nfq_bind_pf`, `nfq_create_queue`, `libnetfilter_queue.so.1` | Filtro **DNS parental control** basato su NFQUEUE (blocco per categoria/dominio) |
| `datausaged` / `datausage_notifier` | rc.d **S55** (servizio ubus `datausage`) / **S50** (servizio ubus `datausage_notifier`); gated su config UCI dedicate; notifier con handler Lua `/usr/lib/lua/datausage_notifier/{email,sms,intercept}.lua` | `/usr/bin/datausaged` (14.575 byte), `/usr/bin/datausage_notifier` (4.911 byte) | Coppia di daemon di **monitoraggio consumo dati** + notifica soglia (email/SMS), collegata a `/etc/hotplug.d/ntp/35-datausaged` e alla web UI (`/www/cards/011_datausage.lp`) |

L'infrastruttura 1905.1 condivisa da `multiap_agent`/`multiap_controller` (stesso MAC multicast `01:80:C2:00:00:13`, stesse `lib1905_*`) e la comparsa contemporanea di `nanocdn` sono coerenti con il rebase di piattaforma verso una SNAPSHOT più recente (§1.1): sono feature EasyMesh + IPTV che la base Chaos Calmer di 221 non aveva.

## 5. Aperture / limiti

- **Algoritmo di compressione del corpo kernel non recuperato** (§2.3): tutti i formati standard falliscono; recuperarlo richiederebbe di disassemblare la routine di decompressione del CFE o un GPL source drop Broadcom bcm963xx con il relativo `lzma.c`.
- **Campi header `0x0c`–`0x0f` e tag `LINU\n`** (§2.2): decodificati come byte ma non identificati semanticamente.
- **Binari `nanocdn-core` / `nanocdn-rr` non trovati** nel filesystem estratto (§4): l'identificazione come Broadpeak nanoCDN è basata su path, vendor dir (`/etc/broadpeak/`), utente dedicato e helper Lua — **non** su stringhe estratte dai binari stessi, che non sono presenti nel listing.
