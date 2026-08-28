# Architettura di memoria del Technicolor VBNT-K (DGA4130)

Layout NAND, sistema dual-bank e partizioni rilevanti per chi fa recovery,
downgrade o patching del firmware. Ricavato dal log di boot seriale reale
(kernel Linux, driver `technicolor-nand-tl`) di un'unità fisica, non da
documentazione ufficiale — log completo raccolto il 2026-08-23.

## 1. Hardware

- SoC: Broadcom **BCM63138B0**
- RAM: **512MB**
- Flash: NAND **256MB**, chip **Micron MT29F2G08ABA** (`mfg 2c da`, `dev_id=2cda9095`), block size **128K**, writesize 2048, ECC BCH4 (2K)
- Bootloader: CFE, "Boot Loader Version" tipica `16.11.1013-...`, board mnemonic `VBNT-K`

### 1.1 Datasheet — SoC Broadcom BCM63138B0

Broadcom non pubblica un datasheet ufficiale scaricabile per questa classe
di SoC da gateway (materiale sotto NDA per i licenziatari). I dati sotto
sono divisi in due gruppi: **osservati direttamente** sul log di boot
seriale di questa unità (log completo in `UART-BOOT-LOG-IT.md`), e **noti
pubblicamente** per la famiglia BCM63138 da fonti secondarie (driver open
source OpenWrt/linux-brcm63xx, documentazione hack-technicolor, marketing
collateral Broadcom) — questi ultimi marcati esplicitamente, perché non
verificabili in modo indipendente su questo hardware specifico.

| Parametro | Valore | Fonte |
|---|---|---|
| CPU | Dual-core ARM Cortex-A9 (ARMv7, rev 1), SMP | Osservato: `CPU: ARMv7 Processor [414fc091]`, `Brought up 2 CPUs` |
| Cache L2 | PL310 (L2C-310), 16 way, 512 KB | Osservato: `L2C-310 cache controller enabled, 16 ways, 512 kB` |
| Interrupt controller | Cortex-A9 MPCORE GIC | Osservato: `Cortex A9 MPCORE GIC init` |
| Velocità stimata | ~1319 BogoMIPS/core (`lpj=659968`) — **non è una misura di clock esatta**, solo un ordine di grandezza | Osservato (calibrazione kernel) |
| Clock massimo pubblicizzato per famiglia | fino a ~1 GHz per core | Pubblico, non verificato su questa unità |
| Controller memoria | DDR3/DDR3L, fino a DDR3-1600 | Osservato: `DDR3-1600 CL11 512MB`, `NVRAM memcfg 0x427` |
| Controller NAND | `BrcmNand`, versione **7.0** | Osservato: `Brcm NAND controller version = 7.0` |
| Acceleratore pacchetti | "Runner"/BPM/Packet Flow Cache (offload hardware L2-L4) | Osservato: nomi driver `Broadcom Runner Blog Driver`, `Broadcom Packet Flow Cache` |
| PCIe | 2 core PCIe Gen, 1 lane ciascuno (Rev 3.01) | Osservato: `bcm963xx-pcie: found core [0]`/`[1]` |
| UART | 2x BCM63XX UART (`ttyS0`, `ttyS1`), base_baud 921600, console a **115200 8N1** | Osservato: `Serial: BCM63XX driver`, `ttyS0 at MMIO 0xfffe8600` |
| Boot ROM sicuro | Verifica crittografica (RSA/SHA) via checkpoint a 4 caratteri (`BTRM`...`PASS`) prima di avviare CFE | Osservato + analisi statica firmware, vedi `UART-BOOT-LOG-IT.md` |
| Processo litografico / package | Non reperibile da fonte pubblica affidabile | — omesso, non un'ipotesi da datasheet secondario |

### 1.2 Datasheet — NAND Micron MT29F2G08ABA

Il driver kernel stampa l'identificativo del chip per intero, quindi qui
tutto è **verificato direttamente** sull'unità (non serve un datasheet
esterno per i parametri di geometria — li ha già confermati Linux stesso
durante il probe):

```
[    0.821933] brcmnand_read_id: CS0: dev_id=2cda9095
[    0.845419] busWidth=1, pageSize=2048B, page_shift=11, page_mask=000007ff
[    0.852402] BrcmNAND mfg 2c da MICRON MT29F2G08ABA 256MB on CS0
[    0.898628] page_shift=11, bbt_erase_shift=17, chip_shift=28, phys_erase_shift=17
[    0.913768] ECC layout=brcmnand_oob_bch4_2k
[    0.928824] brcmnand_scan, eccsize=512, writesize=2048, eccsteps=4, ecclevel=4, eccbytes=7
```

| Parametro | Valore | Fonte |
|---|---|---|
| Manufacturer ID / Device ID | `0x2C` (Micron) / `0xDA` | Osservato: `mfg 2c da`, `dev_id=2cda9095` |
| Tipo | SLC NAND, 2 Gbit (256 MB) | Osservato: `MICRON MT29F2G08ABA 256MB` |
| Bus width | 8 bit (`busWidth=1`) | Osservato |
| Pagina | 2048 byte dati + 64 byte spare (`oobsize=64`) | Osservato: `pageSize=2048B`, `mtd->oobsize=64` |
| Blocco | 128 KB = 64 pagine (`erase_shift=17` → 2¹⁷ byte) | Osservato: `Block size=00020000, erase shift=17` |
| ECC richiesta dal chip | minimo 4 bit corretti ogni 512 byte | Osservato indirettamente: il driver usa esattamente `eccsize=512`, `ecclevel=4` (BCH-4), coerente con la soglia minima tipica delle famiglie SLC Micron di questa generazione |
| Endurance tipica dichiarata per la famiglia | ≥ 100.000 cicli P/E (classe SLC) | Pubblico (datasheet generico famiglia Micron SLC, non misurato su questa unità) |
| Tensione operativa tipica per la famiglia | 3,3 V (range 2,7–3,6 V) | Pubblico, non misurato — coerente con l'adattatore UART usato in questo progetto (PL2303 a 3,3 V, vedi `UART-BOOT-LOG-IT.md`) |
| Tempi tipici pubblicati per famiglia (program/erase) | program ~200 µs tip. / 700 µs max; erase ~1,5 ms tip. / 3 ms max | Pubblico, valori indicativi della classe di prodotto — non misurati su questa unità |

## 2. Tabella delle partizioni MTD

Stampata dal driver `technicolor-nand-tl` a ogni boot (`parse_btab: num_banks (5)`):

| Range (byte) | Nome | Dimensione | Note |
|---|---|---|---|
| `0x000000080000`–`0x0000000a0000` | `eripv2` | 128 KB | Vedi §4 — probabile chiavi OSCK/OSIK/EIK (formato `.rbi`) |
| `0x0000000a0000`–`0x0000000e0000` | `rawstorage` | 256 KB | Scopo non identificato — nome generico, non ancora investigato |
| `0x0000000e0000`–`0x000005a00000` | `rootfs_data` | ~89 MB | **Overlay scrivibile persistente**, vedi §3 |
| `0x000005a00000`–`0x00000aa00000` | `bank_1` | 80 MB (`0x5000000`) | Immagine firmware completa (kernel+squashfs) |
| `0x00000aa00000`–`0x00000fa00000` | `bank_2` | 80 MB (`0x5000000`) | Immagine firmware completa, gemella di bank_1 |
| `0x000005c00000`–`0x000008860000` | `rootfs` | ~44 MB (dinamica) | Sotto-partizione **dinamica**: punta alla porzione squashfs dentro qualunque bank sia attivo — non è fissa, si sposta con `/proc/banktable/active` |

`0x5000000` (80MB) combacia esattamente con la dimensione del payload
raw decifrato da un `.rbi` (vedi `RBI-FORMAT-IT.md` §2.3) — conferma che
un `.rbi` VBNT-K contiene sempre e solo il contenuto di **un intero bank**,
non un sottoinsieme.

### 2.1 Confronto: `/proc/mtd` su un'unità diversa, già rootata, firmware AGTEF_2.2.1

Dati raccolti in una sessione separata (2026-08-27), **su un'unità fisica
diversa** da quella di questo documento (MAC/seriale non pubblicati),
firmware attivo **AGTEF_2.2.1** (OpenWrt Chaos Calmer 15.05.1, kernel
4.1.38) — quindi non direttamente comparabile alla 2.4.5 discussa nel resto
del repo, ma utile come secondo punto dati per lo stesso modello di scheda:

```
mtd0: 10000000 00020000 "brcmnand.0"   (chip intero, 256MB)
mtd1: 04df0000 00020000 "rootfs"       (81.723.392 byte, squashfs, ro)
mtd2: 05920000 00020000 "rootfs_data"  (93.323.264 byte ≈ 89MB)
mtd3: 05000000 00020000 "bank_1"       (83.886.080 byte = 80MB)
mtd4: 05000000 00020000 "bank_2"       (83.886.080 byte = 80MB)
mtd5: 00020000 00020000 "eripv2"       (131.072 byte = 128KB)
mtd6: 00040000 00020000 "rawstorage"   (262.144 byte = 256KB)
```

`eripv2`, `rawstorage`, `rootfs_data`, `bank_1`, `bank_2` combaciano
**esattamente** in dimensione con la tabella sopra. La differenza è
`rootfs`: qui appare come **nodo MTD a sé stante** (`mtd1`, ~81.7MB, quasi
quanto un intero bank), non come sotto-partizione dinamica da ~44MB dentro
il bank attivo. Non è chiaro se sia una differenza dovuta alla versione
firmware/kernel (generazione della tabella partizioni diversa in
`technicolor-nand-tl` fra 2.2.1 e 2.4.5) o alla revisione hardware — **non
verificato**, segnalato qui solo come dato di confronto per chi lavora su
altre unità/versioni. Mount live osservato su questa stessa unità: `mtd1`
("rootfs") montato **ro** su `/rom`; `mtd2` ("rootfs_data") montato **rw**
su `/overlay`, secondo il classico schema squashfs+overlayfs di §3.

## 3. Sistema dual-bank e persistenza di `/etc`

- `bank_1`/`bank_2`: due copie complete e indipendenti di kernel+squashfs.
  `/proc/banktable/booted` e `/proc/banktable/active` (letti/scritti da
  root via SSH, vedi `GUIDA-ROOT-IT.md`) indicano quale bank è in esecuzione
  e quale verrà usato al prossimo boot — permettono un classico schema A/B
  (aggiorna il bank inattivo, poi fai lo switch, con rollback facile se il
  nuovo bank non boota).
- Il rootfs vero e proprio è **sola lettura** (squashfs, log di boot:
  `VFS: Mounted root (squashfs filesystem) readonly on device 31:1`).
- Subito dopo, il kernel monta `rootfs_data` (JFFS2) e fa
  `switching to overlay` / `mounting overlayfs fs`: **`/etc` (e altri path
  scrivibili) sono in realtà un overlayfs** — squashfs come layer inferiore
  read-only, `rootfs_data` come layer superiore scrivibile.
- **Punto critico per chi fa patch/rooting**: `rootfs_data` è **una singola
  partizione condivisa, separata da bank_1/bank_2**, non contenuta
  dentro l'immagine da 80MB di nessuno dei due bank. Riscrivere un bank
  (via `mtd write` da root, o via recovery BOOTP/TFTP) **non tocca
  `rootfs_data`**. Qualunque file scritto in overlay da un boot precedente
  (es. un tentativo di rooting fatto su una sessione diversa, settimane
  prima) **sopravvive indefinitamente** a reflash successivi e **oscura**
  le versioni presenti nel nuovo squashfs per lo stesso path, per via della
  normale semantica di overlayfs (layer superiore vince).

  Conseguenza pratica verificata (2026-08-23): un flash riuscito e
  verificato (hash SHA-256 confermato) di un `221` patchato con nuovi
  `/etc/passwd` + `/etc/shadow` + `/etc/config/dropbear` (per abilitare SSH
  root) non è bastato a sbloccare il login SSH — ipotesi principale, non
  ancora confermata, è che versioni precedenti di questi stessi file
  scritte in `rootfs_data` da un tentativo precedente su questo router
  restino attive. Vedi `RBI-FORMAT-IT.md` §5.3 per i dettagli del test.
  **Per un vero test pulito** servirebbe azzerare `rootfs_data` (factory
  reset via 7 secondi sul tasto reset a router acceso — procedura diversa
  dalla recovery BOOTP/TFTP; **un primo tentativo, 2026-08-23, non ha
  chiarito nulla**: lo stesso reset era già stato provato in passato su
  questo router per un problema diverso senza risolverlo) oppure, da root,
  cancellare/reinizializzare esplicitamente la partizione.

## 4. `eripv2` — probabilmente le chiavi di cifratura del firmware

Il nome (`erip` = **E**ncrypted **R**oot **I**nfo **P**artition? non
confermato) e soprattutto il parametro nella command line del kernel
osservato in boot (`platform.r2secr=0x1ffdf000`) corrispondono esattamente
al driver kernel **`r2secr`** usato dal tool community
[`pedro-n-rocha/secr`](https://github.com/pedro-n-rocha/secr) per estrarre
`ECKey`/`OSCK`/`OSIK`/`EIK` da un dispositivo rootato (vedi `rip2.h`,
`rip2_crypto.h`, `ripdrv.h` nel sorgente di quel tool). Ipotesi di lavoro,
non ancora verificata direttamente su questo hardware: questa piccola
partizione (128KB) contiene il materiale crittografico per-board usato
dal bootloader per la cifratura AES dei `.rbi` (vedi `RBI-FORMAT-IT.md`
§2.1) — spiegherebbe perché OSCK è "per modello scheda" (§ dedicata in
quel file) piuttosto che generata al volo.

### 4.1 Formato "THENC" (backup configurazione) — meccanismo confermato da codice sorgente

Aggiornamento 2026-08-27: l'ipotesi sul backup "THENC" (vedi
`root/import_config.py`) è ora **confermata leggendo direttamente il
sorgente Lua** (`/usr/lib/lua/transformer/shared/ConfigCommon.lua`) su
**un'unità diversa** da quella di questo documento, firmware attivo
**AGTEF_2.2.1** (non 2.4.5 — versione più vecchia, quindi la conferma è sul
meccanismo, non garantita byte-per-byte identica su 2.4.5, anche se il
modulo `transformer` è condiviso fra le versioni e non risulta cambiato
nei diff fin qui documentati in `VERSION-CHANGELOG-IT.md`):

- Header in chiaro del file: `PREAMBLE=THENC`, `BACKUPVERSION=1.00`,
  `BOARDMNEMONIC`, `PRODUCTNAME`, `SERIALNUMBER`, `MAC`, `BUILDVERSION`,
  `CIPHERKEY=GW`, `SIGNATUREKEY=GW` — `GW` è un **alias**, non la chiave.
- Alias `"GW"` → chiave letta da `/proc/rip/0108` (variabile `rip_random_B`
  nel sorgente): chiave AES = **primi 32 byte**, chiave HMAC = **primi 64
  byte** dello stesso blob.
- Alias alternativo `"GW_KEYD"` (non usato di default, solo se
  `system.config.export_commonkey`/`import_commonkey` è impostato
  esplicitamente) → chiave da `/proc/rip/012b` (`rip_random_D`): AES = byte
  1–32, HMAC = byte 33–96.
- Schema: `cipher_scheme = "AES-256-CBC"`, `signature_scheme = "HMAC-SHA1"`.
- Verificato sull'unità 2.2.1: nessun override UCI attivo (default `"GW"`
  confermato in uso), `export_plaintext`/`export_unsigned` = 0 (cifratura+
  firma attive normalmente).

**Non transferibile fra unità**: il materiale a `/proc/rip/0108` è per-scheda
(stesso sotto-sistema `rip`/`ripdrv` di §4, verosimilmente per-unità come
OSCK/OSIK), quindi conoscere l'algoritmo non permette di decifrare il
`config.bin` di un'unità diversa senza leggerne la propria chiave da root —
per questo qui non viene pubblicato alcun byte della chiave osservata, solo
il meccanismo.

## 5. Aperture / da verificare

- `rawstorage` (256KB): scopo sconosciuto, nome troppo generico per
  ipotizzare — da investigare se si trova un modo per leggerla da root.
- Non verificato se la recovery BOOTP/TFTP scriva sempre su un bank fisso
  (es. sempre quello "booted" corrente) o se possa essere indirizzata
  all'altro bank — nei test del 2026-08-23 ha sempre scritto e fatto
  boot da Bank 1, ma il router era già su Bank 1 prima del test, quindi
  non distingue le due ipotesi.
  **Segnalazione di terza mano, non confermata indipendentemente** (da una
  sessione parallela diversa, riportata solo per memoria di progetto, non
  verificata di persona): un tentativo di flash BOOTP/TFTP di una 1.0.3
  sarebbe stato scritto/accettato dal CFE, ma al riavvio il router avrebbe
  bootato **l'altro** bank (invariato). Se confermato, indicherebbe che
  "banco scritto da BOOTP" e "banco attivato al boot" sono governati da
  meccanismi CFE indipendenti — coerente con l'ipotesi di questo punto, ma
  da verificare con un test dedicato (es. partire da uno stato con
  `booted` ≠ `active` noto, come osservato nell'unità 2.2.1 di §2.1: lì
  `booted=bank_2` ma `active=bank_1` in condizioni normali) prima di
  fidarsene per un piano di downgrade.
- Relazione esatta fra `rootfs` (la sotto-partizione dinamica ~44MB) e il
  contenuto squashfs dentro il bank attivo non ricostruita byte-per-byte
  — l'offset dello squashfs dentro l'immagine da 80MB varia per versione
  (vedi `RBI-FORMAT-IT.md` §3.2 per gli offset osservati su 221/245).
- **Discrepanza kernel non ancora chiarita**: il log di boot del test del
  2026-08-23 (firmware `AGTEF_2.2.1_CLOSED.rbi` da `F:\Modem`) mostra
  `Linux version 3.4.11-rt19 ... Mar 9 2017` — kernel della generazione
  1.0.3→2.0.1_003 secondo `RBI-FORMAT-IT.md` §3.4, che invece attribuisce a
  2.2.0/2.2.1 il kernel 4.1.38. Non è un errore della pipeline di build (il
  kernel viene riusato verbatim dall'header/payload originale, non toccato
  dalla patch) — o il file sorgente in `F:\Modem` non è il vero 2.2.1, o
  l'attribuzione kernel→versione in §3.4 va rivista. Non ancora indagato.

  **Dato utile per chiarirla (2026-08-27)**: su **un'unità diversa**, live e
  funzionante, con `BUILDVERSION`/`friendly_sw_version_activebank`
  confermato via UCI = `AGTEF_2.2.1`, `uname -a` restituisce
  `Linux version 4.1.38 (repowrt-builder@...) ... Fri Apr 24 18:36:14 UTC
  2020` — cioè **conferma il kernel 4.1.38 per 2.2.1**, coerente con
  l'attribuzione di `RBI-FORMAT-IT.md` §3.4 e NON con quanto osservato nel
  boot log del 2026-08-23. Rafforza l'ipotesi che il file
  `AGTEF_2.2.1_CLOSED.rbi` usato in quel test non fosse davvero un 2.2.1
  genuino (piuttosto che una revisione della mappa kernel→versione) — non
  è una prova definitiva (unità fisica diversa, non lo stesso file `.rbi`
  verificato byte-a-byte), ma è un indizio concreto in quella direzione.
