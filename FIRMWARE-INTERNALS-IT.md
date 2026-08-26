# Interni del firmware AGTEF: layout kernel/squashfs, header del blob kernel, generazione di `network`, nuovi servizi

Analisi a livello di byte del contenuto dell'immagine flash da 80 MiB (il payload `0xB0` in chiaro descritto in [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §2.3), che [`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) descrive come contenuto di **un intero bank**. Questo file complementa gli altri: dove `MEMORY-ARCHITECTURE` descrive le partizioni NAND e `RBI-FORMAT` il contenitore `.rbi`, qui si guarda **dentro** l'immagine decifrata — dove finisce il kernel e inizia lo squashfs, com'è fatto l'header proprietario del blob kernel, da dove viene generato `etc/config/network` nelle build recenti, e cosa fanno davvero i servizi comparsi in 2.4.5.

Le sezioni 1, 3 e 4 sono ricavate per confronto diretto tra due immagini raw decifrate: **la build 2.2.1 stock** (`AGTEF_2.2.1_CLOSED.rbi`, di seguito "221") e **la build 2.4.5 CLOSED** (`AGTEF_2.4.5_CLOSED.rbi`, di seguito "245"). La sezione 2 (header/decompressione del blob kernel) è invece estesa a tutte e cinque le build ufficiali disponibili, `1.0.3` → `2.4.5`. Gli offset citati sono relativi all'inizio del payload raw da 83.886.080 byte (80 MiB, `0x5000000`), non al file `.rbi`.

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

## 2. Header del blob kernel (decodificato) e decompressione — risolta

> **Aggiornamento.** Una versione precedente di questo documento non aveva individuato un **mini-header di 12 byte** interposto tra l'header esterno da 26 byte e lo stream compresso, e concludeva quindi che la decompressione del corpo kernel fosse un vicolo cieco. Quell'affermazione era errata ed è **superata**: un'analisi successiva, estesa a tutte le versioni ufficiali disponibili (`1.0.3`, `2.2.0`, `2.2.1`, `2.4.1`, `2.4.5`), ha individuato il layout reale e ha recuperato il banner `Linux version` di ogni versione. Il dettaglio del formato è in §2.3.

Entrambe le build iniziano il blob kernel con un header proprietario fisso di **0x1a (26) byte**, seguito dal mini-header e dallo stream compresso (§2.3). Decodifica campo per campo dell'header esterno (offset relativi all'inizio del blob):

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

- `0x0c`–`0x0f`: il valore BE a 2 byte cambia con la versione. Con i dati ora disponibili su 5 versioni ufficiali, in ordine cronologico i valori sono **408, 441, 443, 560, 564** (1.0.3, 2.2.0, 2.2.1, 2.4.1, 2.4.5): strettamente **non decrescenti**. Ma `2.4.1` e `2.4.5` hanno un corpo kernel **identico** (stesso sha256, §2.3) e tuttavia valori **diversi** (560 vs 564): questo dimostra che il campo **non** è un hash né una lunghezza derivati dal contenuto del kernel. Ipotesi più probabile: un contatore interno di build/revisione del vendor. Provate e scartate le ipotesi di checksum, XOR dei byte del payload, e divisore della block-size del payload. Scopo esatto ancora **non identificato**.
- `0x11`–`0x15`: il tag `LINU\n` è identico in entrambe le build, ma il quinto byte è un line-feed `0x0a`, non `X` (`0x58`). Il motivo del troncamento/terminazione a line-feed **non è identificato** semanticamente (probabile tag fisso emesso dallo strumento di build Broadcom, non un campo interpretato).

### 2.3 Decompressione del corpo — risolta (LZMA_ALONE + mini-header)

Il pezzo mancante che aveva fatto naufragare i tentativi precedenti è un **mini sub-header di 12 byte** interposto tra l'header esterno da 26 byte e lo stream compresso vero e proprio. Il bruteforce `FORMAT_RAW` falliva **immediatamente** proprio perché assumeva che lo stream iniziasse subito dopo il byte `0x1a`: in realtà lì c'è ancora una struttura, e lo stream è un container **LZMA_ALONE** standard (non un LZMA raw). Layer per layer, identico su tutte le 5 versioni ufficiali testate:

1. **Header esterno da 26 byte** (`0x00`–`0x19`): quello decodificato in §2/§2.1, invariato.
2. **Mini sub-header da 12 byte** (offset file `0x1a`, offset corpo 0): tre word little-endian a 32 bit — `<load_addr> <load_addr ripetuto> <inner_length>`. `inner_length` = dimensione del corpo kernel **meno 12**, esatta su tutte le 5 versioni. `load_addr` = `0xc0008000` per `1.0.3`/`2.2.0`/`2.2.1`, e `0xc0018000` per `2.4.1`/`2.4.5` (indirizzo di load ARM diverso per le due più recenti).
3. **Stream LZMA_ALONE** (offset file `0x26`, offset corpo 12): classico header `.lzma` "LZMA_ALONE" — 1 byte di proprietà, 4 byte little-endian di dimensione dizionario, 8 byte little-endian di dimensione decompressa — seguito da uno stream LZMA1 puro. Decodificabile direttamente con la libreria standard Python:

   ```python
   import lzma
   kernel = lzma.decompress(body[12:], format=lzma.FORMAT_ALONE)
   ```

   Byte di proprietà = `0x6d` (lc=1, lp=2, pb=2), dizionario = 4 MiB — identici su ogni versione testata. È esattamente ciò che aveva sconfitto il tentativo "LZMA1 raw bruteforce": non era mai stato provato il container LZMA_ALONE standard con il suo header proprietà/dimensione embedded, perché si assumeva che lo stream iniziasse subito dopo l'header da 26 byte — il mini-header da 12 byte in mezzo era il pezzo mancante.

Da qui il comportamento diverge tra le versioni:

- **`1.0.3`, `2.2.0`, `2.2.1`**: questa singola decompressione LZMA_ALONE produce **direttamente** l'immagine kernel flat completa, con il banner `Linux version ...` leggibile in chiaro al suo interno.
- **`2.4.1` e `2.4.5`**: la prima decompressione produce invece uno **stub zImage ARM Linux self-extracting** (confermato dalla firma canonica di `head.S`: 8× istruzioni NOP, poi un branch, poi la magic word `0x016f2818`, a offset relativo `0x24` nell'output decompresso — la firma standard e ben nota dello stub decompressore zImage ARM). Quello stub contiene un **secondo** stream LZMA_ALONE annidato, a offset relativo `0x41c4` (byte proprietà `0x6d`, dizionario 1 MiB, campo dimensione decompressa impostato al sentinella "lunghezza sconosciuta" `0xFFFFFFFFFFFFFFFF`, cioè "decomprimi finché lo stream stesso non finisce"). Decomprimendo quel secondo stream si ottiene il kernel flat reale e il suo banner. Quindi `2.4.1`/`2.4.5` sono **double-LZMA**: container esterno a livello CFE → zImage self-extracting → kernel reale; le quattro versioni più vecchie sono single-wrapped.

**Banner `Linux version` recuperati** (stringhe esatte, verificate byte-per-byte sui file kernel decompressi):

- **`1.0.3`** (kernel `3.4.11-rt19`):
  `Linux version 3.4.11-rt19 (repowrt-builder@9c0b3ba154ab) (gcc version 4.6.4 (OpenWrt/Linaro GCC 4.6-2013.05 r49389) ) #1 SMP PREEMPT Thu Mar 9 02:50:43 UTC 2017`
- **`2.2.0`** (kernel `4.1.38`):
  `Linux version 4.1.38 (repowrt-builder@ff55a63a23d5) (gcc version 5.3.0 (OpenWrt GCC 5.3.0 unknown) ) #1 SMP PREEMPT Wed Oct 16 15:21:10 UTC 2019`
- **`2.2.1`** (kernel `4.1.38`):
  `Linux version 4.1.38 (repowrt-builder@2d2f3d55d158) (gcc version 5.3.0 (OpenWrt GCC 5.3.0 unknown) ) #1 SMP PREEMPT Fri Apr 24 18:36:14 UTC 2020`
- **`2.4.1`** e **`2.4.5`** (kernel `4.1.52`, **corpo kernel identico byte-per-byte tra le due, confermato via sha256** — 2.4.5 non ha cambiato il kernel rispetto a 2.4.1, solo rootfs/pacchetti, coerente con quanto già documentato altrove nel repo su 2.4.1→2.4.5 come update piccolo e mirato):
  `Linux version 4.1.52 (repowrt-builder@defb8768b1b8) (gcc version 5.5.0 (OpenWrt GCC 5.5.0 r14144-e2ae576c18) ) #0 SMP PREEMPT Fri Oct 28 16:57:49 2022`

**Cross-validazione.** Per ognuna delle 5 versioni, il numero di kernel del banner recuperato combacia esattamente con `/lib/modules/<versione>/` nel rispettivo rootfs estratto — conferma indipendente che si tratta di una decompressione reale e non di un artefatto.

#### Tabella comparativa (sola linea ufficiale)

| Versione | Squashfs @ | Fine payload kernel | Dimensione kernel | Header `0x0c`–`0x0f` | `load_addr` | Kernel | Banner (build hash) |
|---|---|---|---|---|---|---|---|
| 1.0.3 | `0x200000` | `0x1b3d9c` | 1.785.218 byte | `0x0198` (408) | `0xc0008000` | 3.4.11-rt19 | `9c0b3ba154ab` |
| 2.2.0 | `0x210000` | `0x1ff156` | 2.093.372 byte | `0x01b9` (441) | `0xc0008000` | 4.1.38 | `ff55a63a23d5` |
| 2.2.1 | `0x210000` | `0x1ff96a` | 2.095.440 byte | `0x01bb` (443) | `0xc0008000` | 4.1.38 | `2d2f3d55d158` |
| 2.4.1 | `0x600000` | `0x221d57` | 2.235.709 byte | `0x0230` (560) | `0xc0018000` | 4.1.52 | `defb8768b1b8` |
| 2.4.5 | `0x600000` | `0x221d57` | 2.235.709 byte | `0x0234` (564) | `0xc0018000` | 4.1.52 | `defb8768b1b8` (identico a 2.4.1) |

> La build community **non ufficiale** `1.1.3` condivide questo stesso layout e ha kernel identico a `1.0.3`, ma **non** appartiene alla linea ufficiale e non è inclusa qui: vedi [`AGTEF-1.1.3-NON-UFFICIALE-IT.md`](AGTEF-1.1.3-NON-UFFICIALE-IT.md).

Conferma indiretta dal log di boot in [`UART-BOOT-LOG-IT.md`](UART-BOOT-LOG-IT.md) (righe 153–156): il CFE stampa `Decompression OK!` poco prima del salto effettivo (`Starting program at 0x00008000`) — coerente con il fatto che il **CFE stesso** decomprime lo stream LZMA_ALONE esterno e salta all'immagine (o, per `2.4.x`, allo stub zImage che a sua volta si auto-scompatta).

**Conclusione.** Il formato del blob kernel è ora completamente compreso e riproducibile con la sola libreria standard Python: header 26 byte → mini-header 12 byte → LZMA_ALONE (→ per `2.4.x`, zImage → LZMA_ALONE annidato). Dell'header restano ignoti solo lo scopo esatto dei campi `0x0c`–`0x0f` (§2.2) e il motivo del tag `LINU\n`.

### 2.4 Disassemblaggio ARM dei kernel flat recuperati e verifica del campo `load_addr`

Approfondimento della §2.3: disassemblati (capstone, modalità ARM) i primi ~100–200 byte di ciascuno dei 5 kernel flat finali recuperati, partendo dall'indirizzo `load_addr` di ciascuna versione (il campo del mini-header già documentato in §2.3). Tutti e 5 producono codice `head.S` ARM Linux immediatamente riconoscibile — nessun fallback a modalità Thumb necessario.

**`1.0.3` (kernel `3.4.11-rt19`, `load_addr=0xc0008000`)** — entry code "classico" pre-Hyp-stub, tipico dell'epoca kernel 3.x:

```
0xc0008000: msr  cpsr_c, #0xd3          ; forza modalità SVC32, IRQ/FIQ disabilitati
0xc0008004: mrc  p15, 0, sb, c0, c0, 0  ; legge MIDR (ID processore)
0xc0008008: bl   #0xc030aea0            ; __lookup_processor_type
0xc000800c: movs sl, r5
0xc0008010: beq  #0xc030aee4            ; __error_p
0xc0008014: add  r3, pc, #0x2c
0xc0008018: ldm  r3, {r4, r8}
...
0xc0008050: add  r4, r8, #0x4000
```

**`2.2.0`/`2.2.1`/`2.4.1`/`2.4.5` (kernel `4.1.x`)** — codice **byte-per-byte identico** tra i due gruppi (2.2.x a `load_addr=0xc0008000`, 2.4.x a `load_addr=0xc0018000`), differiscono solo per l'indirizzo base stampato:

```
0xc0008000: bl   #0xc000ab80  ; __hyp_stub_install
0xc0008004: mrs  sb, apsr
0xc0008008: eor  sb, sb, #0x1a
0xc000800c: tst  sb, #0x1f
0xc0008010: bic  sb, sb, #0x1f
0xc0008014: orr  sb, sb, #0xd3
0xc0008018: bne  #0xc0008030
0xc000801c: orr  sb, sb, #0x100
0xc0008020: add  lr, pc, #0xc
0xc0008024: msr  spsr_fsxc, sb
0xc0008028: msr  elr_hyp, lr
0xc000802c: eret
0xc0008030: msr  cpsr_c, sb            ; fallback: forza SVC diretto se non in Hyp
0xc0008034: mrc  p15, 0, sb, c0, c0, 0
0xc0008038: bl   #0xc000950c           ; __lookup_processor_type
0xc000803c: movs sl, r5
0xc0008040: beq  #0xc00095a0           ; __error_p
```

**Interpretazione (fatto tecnico genuino, non ipotesi).** Tra il kernel `3.4.11-rt19` (1.0.3) e la linea `4.1.x` (2.2.0 in poi) è comparso il prologo `bl __hyp_stub_install` + `safe_svcmode_maskall` — una macro upstream ARM Linux che tenta di scendere da modalità Hyp a SVC via un trucco `ERET`, con fallback a `msr cpsr_c` diretto se il boot non è avvenuto in Hyp mode. È il supporto a `CONFIG_ARM_VIRT_EXT`, aggiunto upstream tra queste due generazioni di kernel — coerente con l'evoluzione nota della linea (salto di generazione kernel già documentato in §1/§2). Nessuna magic `0x016f2818` né stringhe ASCII nei primi 4 KB di nessuno dei 5 kernel flat finali — a differenza dello stub zImage intermedio di 2.4.x (che quella magic ce l'ha, §2.3) — a conferma che questi 5 file sono davvero i kernel finali, non ulteriori wrapper.

**Confronto 2.2.x vs 2.4.x.** Il codice di entry è identico byte-per-byte tra i due gruppi (differisce solo l'indirizzo). **Nessuna differenza strutturale visibile nel codice di ingresso** (spazio riservato, stack, istruzioni extra) che spiegherebbe la necessità dello spostamento di `load_addr` di +64 KiB tra i due gruppi — la spiegazione, se esiste, non è nel codice di entry stesso.

**Cosa rappresenta `load_addr` — confermato, non più solo un valore di campo.** Incrociando con un log UART reale di un'unità in classe `4.1.38` (già presente in questo repo, [`UART-BOOT-LOG-IT.md`](UART-BOOT-LOG-IT.md)), che riporta `Entry Address: 0x00008000` durante il boot reale, l'aritmetica `0xc0008000 − 0xc0000000 (PAGE_OFFSET) = 0x00008000` torna **esattamente**. Questo conferma che `load_addr` nel mini-header è l'indirizzo di link *virtuale* del kernel (`PAGE_OFFSET + TEXT_OFFSET`, convenzione standard ARM Linux), e che l'`Entry Address` fisico visto dal CFE nel log UART reale ne è il corrispondente prima dell'attivazione della MMU. **Nota onesta:** non esiste nel repo un log UART reale di un'unità in classe 4.1.52 (2.4.x) — l'estensione della stessa aritmetica a `0xc0018000 − 0xc0000000 = 0x00018000` per quel gruppo è una conseguenza logica della stessa relazione già confermata, non un'osservazione diretta indipendente. Va segnalato come tale.

**Cosa NON è stato possibile risolvere, nonostante un tentativo reale:**

- **Il motivo dello spostamento di +64 KiB** (`0xc0008000`→`0xc0018000`) tra le due generazioni kernel: non spiegato né dal disassemblaggio (nessuna differenza strutturale nel codice di entry) né dal log UART disponibile. Ipotesi più plausibile offerta (dichiarata esplicitamente come ipotesi, non fatto confermato): una modifica di routine al parametro `TEXT_OFFSET`/`zreladdr` nella configurazione board/BSP tra i build kernel `4.1.38` e `4.1.52`, per riservare più spazio sotto il kernel (DTB/ATAG più grande, area di scratch del decompressore) — non verificata contro alcuna fonte.
- **Ricerca pubblica sul formato header:** nessuna documentazione pubblica trovata per questo specifico header proprietario a 26 byte, per il campo `0x0c`–`0x0f`, o per il tag `LINU\n`. L'unico formato Broadcom-correlato effettivamente documentato pubblicamente è il classico `bcm963xx_tag` a 256 byte (CFE NOR partition ImageTag — es. `linux/bcm963xx_tag.h`, documentazione kernel.org sulle partizioni CFE bcm963xx), che ha un campo concettualmente simile (`image_sequence`, un contatore di build a 4 byte) — un parallelo concettuale debole a sostegno dell'ipotesi "contatore di build vendor" per `0x0c`–`0x0f`, ma il layout è strutturalmente diverso (256 byte, campi `tag_version`/`sig_1`/`chip_id`/`board_id`) dal nostro header proprietario a 26 byte: **non è lo stesso formato**, va presentato solo come analogia concettuale, non come identificazione. Questo header resta **non documentato pubblicamente**.
- **Verifica incrociata negativa** (nuovo controllo, rafforza la caratterizzazione esistente): i 5 valori del campo `0x0c`–`0x0f` (408, 441, 443, 560, 564) sono stati cercati in `etc/banner`, `etc/config/version` e `etc/uci-defaults/tch_5000_versioncusto` di ciascuna delle 5 versioni corrispondenti (build ID tipo `2781008`/`3161014`/`3161018`/`3401135`/`3401200`, timestamp tipo `20170411105953`) — **nessuna corrispondenza in nessun caso**. Il campo non deriva da nessuno di questi identificatori di versione noti nel rootfs. Rafforza (non risolve) la caratterizzazione già esistente come "contatore/campo interno del vendor, non confermato".

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

- **Significato di `load_addr` — confermato; il suo spostamento di +64 KiB — no** (§2.4): il *significato* di `load_addr` è ora confermato (indirizzo di link virtuale = `PAGE_OFFSET + TEXT_OFFSET`, cross-validato contro un log UART reale in classe 4.1.38, `Entry Address: 0x00008000`), non è più solo un valore di campo grezzo. Resta invece **irrisolto** il motivo del suo spostamento di +64 KiB (`0xc0008000`→`0xc0018000`) tra le generazioni kernel `4.1.38` e `4.1.52`, nonostante un tentativo reale basato su disassemblaggio: il codice di entry è byte-per-byte identico tra i due gruppi, senza differenze strutturali che lo giustifichino. Ipotesi più plausibile (non confermata): una modifica di routine a `TEXT_OFFSET`/`zreladdr` nel BSP/board config.
- **Campi header `0x0c`–`0x0f` e tag `LINU\n`** (§2.2, §2.4): decodificati come byte ma non identificati semanticamente. Con 5 versioni ufficiali i valori di `0x0c`–`0x0f` sono non decrescenti (408, 441, 443, 560, 564) ma provatamente **non** derivati dal contenuto del kernel (2.4.1 e 2.4.5 hanno kernel identico e valori diversi) — probabile contatore interno di build del vendor, non confermato. Ora con evidenza più ampia dietro la conclusione "ancora ignoto": i 5 valori sono stati cercati anche negli identificatori di versione del rootfs (`etc/banner`, `etc/config/version`, `etc/uci-defaults/tch_5000_versioncusto`) con **riscontro negativo confermato** in tutti i casi, e confrontati con la documentazione pubblica (il `bcm963xx_tag` è un formato strutturalmente diverso e non correlato — 256 byte, layout differente — non lo stesso header). Restano aperti, ma la conclusione "ancora ignoto" poggia ora su un tentativo esplicito e non su una semplice lacuna non esaminata.
- **Binari `nanocdn-core` / `nanocdn-rr` non trovati** nel filesystem estratto (§4): l'identificazione come Broadpeak nanoCDN è basata su path, vendor dir (`/etc/broadpeak/`), utente dedicato e helper Lua — **non** su stringhe estratte dai binari stessi, che non sono presenti nel listing.
