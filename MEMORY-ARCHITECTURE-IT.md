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
  verificato di un `221` patchato con nuovi `/etc/passwd` + `/etc/shadow`
  + `/etc/config/dropbear` (per abilitare SSH root) non è bastato a
  sbloccare il login SSH — ipotesi principale, non ancora confermata, è che
  versioni precedenti di questi stessi file scritte in `rootfs_data` da un
  tentativo precedente su questo router restino attive. Vedi
  `RBI-FORMAT-IT.md` §5.3 per i dettagli del test. **Per un vero test
  pulito** servirebbe azzerare `rootfs_data` (factory reset via 7 secondi
  sul tasto reset a router acceso — procedura diversa dalla recovery
  BOOTP/TFTP, non ancora verificata su questo hardware) oppure, da root,
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

## 5. Aperture / da verificare

- `rawstorage` (256KB): scopo sconosciuto, nome troppo generico per
  ipotizzare — da investigare se si trova un modo per leggerla da root.
- Non verificato se la recovery BOOTP/TFTP scriva sempre su un bank fisso
  (es. sempre quello "booted" corrente) o se possa essere indirizzata
  all'altro bank — nei test del 2026-08-23 ha sempre scritto e fatto
  boot da Bank 1, ma il router era già su Bank 1 prima del test, quindi
  non distingue le due ipotesi.
- Relazione esatta fra `rootfs` (la sotto-partizione dinamica ~44MB) e il
  contenuto squashfs dentro il bank attivo non ricostruita byte-per-byte
  — l'offset dello squashfs dentro l'immagine da 80MB varia per versione
  (vedi `RBI-FORMAT-IT.md` §3.2 per gli offset osservati su 221/245).
