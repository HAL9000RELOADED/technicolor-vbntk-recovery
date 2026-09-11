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

### 4.2 Conferma pratica end-to-end su due backup reali dello stesso device (2026-09-09)

Aggiornamento 2026-09-09: il meccanismo THENC descritto in §4.1 è ora
**verificato funzionante end-to-end su un file reale** — non più solo dedotto
dal sorgente Lua. Sono stati confrontati **due backup `config.bin` reali dello
stesso device** (stesso `SERIALNUMBER`, stesso `MAC` `10:13:31:xx:xx:xx`,
stesso `BUILDVERSION=AGTEF_2.4.5`) presi a distanza di ~8 mesi, decifrati
usando la **vera chiave hardware del device** letta da `/proc/rip/0108`:

- Entrambi i file: **HMAC-SHA1 valido** in fase di decifratura, cioè l'intera
  catena `header ASCII → IV (16 byte) → AES-256-CBC → HMAC-SHA1`, con chiave
  derivata da `/proc/rip/0108` (AES = primi 32 byte, HMAC = primi 64 byte),
  è confermata corretta su dati veri. È la **prima conferma pratica** che il
  meccanismo descritto a parole in §4.1 funziona davvero su un `config.bin`
  genuino, non solo in teoria.
- Header identico fra i due (stesso device): cambiano solo **IV** e **firma
  HMAC** (attesi: dipendono dal contenuto e dall'IV casuale per-backup) e la
  dimensione del payload cifrato.
- Tool usato: `thenc_tool.py` (sottocomandi `parse`/`decrypt`/`diff`,
  quest'ultimo con `--key-file` per il confronto in chiaro) — disponibile come
  utility riusabile per ripetere l'operazione.

**Riepilogo categorizzato di cosa cambia nel tempo** (NON un diff
riga-per-riga, NESSUN valore reale riportato — solo il *tipo* di impostazioni,
utile per sapere cosa aspettarsi nel contenuto decifrato di un device in uso):

- **Hostname del device**: cambia dal default di fabbrica a un nome scelto
  dall'utente.
- **Sezione `[modgui]` (provisioning/modding)**: **presente o assente** a
  seconda che il root/patch della GUI sia attivo o meno. Nel backup di un
  device rootato compare l'intera sezione (flag di spoofing versione,
  disabilitazione update CWMP, hash/credenziali della GUI moddata, elenco
  app abilitate); nel backup "normale" non esiste. È l'indicatore più netto
  della presenza del modding.
- **Versione firmware della "banca passiva" dichiarata**
  (`env.var.friendly_sw_version_passivebank`): cambia da una versione reale a
  un valore fittizio molto alto (schema `x.99.99.99`). Interessante perché
  sembra usato come **anti-downgrade-detection**: dichiarando una passiva già
  "più recente", si scoraggia il provider/CWMP dal riportare il device a una
  versione precedente presente nell'altro bank.
- **Credenziali DDNS**: passano da **placeholder di default**
  (`your_username` / `your_password` / `yourhost.example.com` / servizio
  generico) a un servizio/hostname/credenziali reali configurati dall'utente.
- **Profilo VoIP/SIP** (`mmpbxrvsipnet.sip_profile_0` e `sip_net`): passa da
  **placeholder `line0`** (user/uri/password tutti = `line0`, profilo
  disabilitato) a numero telefonico e credenziali reali, con il profilo
  abilitato e i proxy/realm SIP del provider popolati.
- **Livello e regole firewall**: cambia il livello dichiarato
  (`firewall.fwconfig.level`, es. da `normal` a `lax`), l'input della zona WAN
  (es. da `DROP` a `REJECT`), e compaiono/spariscono regole e port-forward
  definiti dall'utente (redirect verso host LAN interni).
- **Ruoli utente web** (`web.usr_*`): cambiano gli utenti definiti e i loro
  ruoli (`admin` / `engineer` / `guest`), i verifier/salt SRP e il set di
  regole/pagine accessibili nella UI — coerente con l'attivazione di una GUI
  con privilegi diversi.
- **Server NTP** (`system.ntp.server`): passa da **server interni dell'ISP**
  (host `*.interbusiness.it` / `inrim.it`) a **pool pubblici**
  (`pool.ntp.org`, `it.pool.ntp.org`).
- **Chiave WiFi**: cambiata dall'utente (valore **non riportato qui**).
- Vari altri toggle di servizio (UPnP/NAT-PMP, printer/file sharing, DLNA,
  samba, watchdog, ecc.) cambiano di stato ma senza contenuto sensibile.

**Finding tecnico — campi derivabili dal seriale vs campi solo-ACS**: nel
contenuto decifrato si distinguono due classi di dati "utente":

- Campi **ricostruibili localmente dal seriale del device**: p.es.
  `network.wan.username` segue il pattern deterministico
  `<SERIALNUMBER>-101331@<realm>` (dove `101331` deriva dalle prime cifre del
  MAC/OUI del device). Questi non richiedono conoscenza esterna: dato il
  seriale (che è nell'header THENC in chiaro) e il realm del provider, si
  rigenerano.
- Campi che arrivano **solo da un push TR-069/ACS del provider**: il profilo
  SIP completo (numero telefonico, `display_name`, `password`/hash SIP, proxy
  e realm effettivi) **non è derivabile da alcuna formula locale** — viene
  scritto dal provider via provisioning ACS dopo la prima registrazione. Per
  questo un backup preso *prima* del provisioning contiene solo i placeholder
  `line0`, mentre uno preso *dopo* contiene il profilo reale. La distinzione
  è utile: spiega perché alcuni segreti nel backup si possono predire dal
  seriale e altri (quelli VoIP) no, sono opachi e dipendono dall'ACS.

**Come trovare il proxy SIP e il DNS corretto per la fonia (metodo, non un valore fisso)**:
le credenziali SIP (utente/password o hash) non sono derivabili da nessuna
formula, per lo stesso motivo del punto sopra — vanno lette dal proprio
`config.bin` decifrato (campo `mmpbxrvsipnet.sip_profile_0`) o via UCI live
su un'unità rootata (`uci show mmpbxrvsipnet`).

Il proxy SIP in uscita per la fonia TIM ha un hostname del tipo
`d<NN>s<N>.co.imsw.telecomitalia.it`: il prefisso regionale/di centrale — e
quindi anche quale DNS risolve correttamente — **varia su base
territoriale**. Non esiste un DNS "giusto" universale da scrivere qui: il
proprio hostname proxy va preso dal proprio config.bin, non copiato da un
esempio.

Metodo per risolvere l'IP realmente attivo (serve il record SRV, non solo
l'hostname):
1. `nslookup` da CMD → `set type=SRV`
2. query `_sip._udp.<il-tuo-outbound-proxy>` (es.
   `_sip._udp.d11s7.co.imsw.telecomitalia.it`)
3. la risposta dà due o più hostname con "priority": prendi quello con
   priority più bassa
4. `set type=A`, risolvi quell'hostname specifico → è l'IP da usare

Il DNS da interrogare per questi passaggi conviene sia quello assegnato dal
proprio ISP via DHCP sulla WAN (visibile su un'unità rootata in
`/etc/resolv.conf.auto`), non un resolver pubblico generico — un DNS
regionale dell'ISP (host `dns-alice-<N>.interbusiness.it`, il numero cambia
per centrale) ha dato risposte corrette in un caso osservato; non
verificato se un DNS pubblico dia lo stesso risultato.

### 4.3 Catalogo `/proc/rip/*` — 35 infoblock dati leggibili estratti e verificati (2026-09-09)

Aggiornamento 2026-09-09: l'ipotesi di §4 (che `eripv2` contenga il materiale
crittografico per-board) è ora concretizzata dall'enumerazione completa
dell'interfaccia runtime `/proc/rip/*` — la **vista live** del sotto-sistema
`rip`/`ripdrv` che espone il contenuto della partizione `eripv2` (§2/§4).
Estratti in sola lettura (`cat | base64` via SSH) dall'unità rootata di §4.2,
con **hash SHA-256 verificato identico locale/remoto su tutti e 35** gli
infoblock dati (nessun troncamento in trasferimento).

**Che cosa conta il numero 35.** Il **35** si riferisce esclusivamente ai
**blocchi dati leggibili** effettivamente estratti via SSH e verificati con
SHA-256 (locale=remoto su tutti) — sono i 35 codici elencati nella prima
tabella qui sotto. Elencati **separatamente**, per sola completezza
documentale, ci sono anche i **5 nodi di controllo**
(`clean`/`encrypt`/`lock`/`new`/`signed`, mai letti né toccati in questa
sessione) e la voce `0116` (**verificata assente** su questa unità): questi
**non fanno parte del conteggio dei 35** e sono raccolti nella seconda tabella,
così il totale resta inequivocabile.

**Nessun byte di alcuna chiave, hash o certificato è riportato qui** (vincolo
di scrub del repo). I blocchi già documentati altrove sono solo **referenziati,
non duplicati**: `0108` (chiave "GW", cifratura `config.bin`) e `012b`
(`rip_random_D`) → §4.1; `0120` (chiave pubblica RSA-2048 "OSIK") →
[`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §6.

**Tabella A — i 35 blocchi dati leggibili** (estratti e verificati SHA-256
locale=remoto; è questo l'insieme a cui si riferisce il conteggio "35"):

| Codice | Dim. reale | Permessi | Significato |
|---|---|---|---|
| `0002` | 2 B | `r--r--r--` | Flag hardware SFP (bit sul nibble alto) |
| `0004` | 8 B | `r--r--r--` | PBA / numero di produzione |
| `0010` | 2 B | `r--r--r--` | `sw_flag` |
| `0012` | 9 B | `r--r--r--` | Numero di serie |
| `0022` | 6 B | `r--r--r--` | Data di fabbrica (YYMMDD) |
| `0028` | 2 B | `r--r--r--` | `fia` (form factor id) — già noto, usato in `platform_check_bliheader` (sotto-funzione di `platform_check_image_imp`, vedi [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §6.4) |
| `0032` | 6 B | `r--r--r--` | MAC Ethernet |
| `0038` | 4 B | `r--r--r--` | `company_id` |
| `003c` | 2 B | `r--r--r--` | `factory_id` |
| `0040` | 6 B | `r--r--r--` | Mnemonico board (`VBNT-K`) — già noto, usato nel check header BLI |
| `0048` `0049` `004a` `004b` | 1 B ciascuno | `r--r--r--` | Non identificati |
| `004c` | 6 B | `r--r--r--` | MAC USB |
| `0083` | 288 B dichiarati (contenuto reale minore, vedi nota) | `r--------` | Modem Access Code |
| `0088` | 288 B dichiarati | `r--------` | Non identificato, stessa dimensione di `0083` |
| `008d` | 6 B | `r--r--r--` | MAC WiFi |
| `0107` | 320 B dichiarati | `r--------` | "rndA" — Generic Access Key legacy |
| `0108` | 352 B dichiarati | `r--------` | Chiave "GW" — **già documentata in dettaglio in §4.1** (cifratura `config.bin`) |
| `0115` | 4 B | `r--r--r--` | Chip ID Broadcom raw |
| `0119` | 256 B | `rw-r--r--` | Non identificato, pattern binario non testuale |
| `011a.cert` | 7088 B | `r--------` | Certificato TLS client MQTT |
| `011c` | 4 B | `r--r--r--` | Non identificato |
| `0120` | 512 B dichiarati | `r--------` | **Chiave pubblica RSA-2048, alias "OSIK" = Operator Software Image Key** — verifica firma firmware, vedi [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §6 |
| `0124` | 368 B dichiarati | `r--------` | "GAK" — Generic Access Key (10 chiavi × 8 B) |
| `0127` | 512 B dichiarati | `r--------` | Non identificato, stessa dimensione di `0120` — **ipotesi non confermata**: seconda chiave RSA-2048 |
| `0128` | 320 B dichiarati | `r--------` | Non identificato, stessa dimensione di `0107` |
| `012a` | 2336 B dichiarati | `r--------` | Famiglia chiavi cifratura `config.bin` (con `0108`/`012b`) |
| `012b` | 2336 B dichiarati | `r--------` | "rip_random_D" — **già documentata in §4.1** |
| `012c` `012d` `012e` | 416 / 496 / 672 B dichiarati | `r--------` | Non identificati |
| `8001` | 1 B | `rw-r--r--` | `product_id` (valore osservato: `0` = non provisionato) |
| `8003` | 1 B | `rw-r--r--` | `variant_id` (valore osservato: `0`) |

I codici elencati sopra sono esattamente 35 (`0048 0049 004a 004b` e
`012c 012d 012e`, raggruppati in un'unica riga per compattezza, valgono per il
conteggio come voci distinte).

**Tabella B — voci elencate a parte, NON incluse nei 35** (nodi di controllo
mai letti/toccati + slot verificato assente; qui solo per completezza
documentale):

| Codice | Dim. reale | Permessi | Significato |
|---|---|---|---|
| `0116` | **non esiste** su questa unità | — | Slot DSA legacy mai provisionato — vedi [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) §6.3 (fallback firma DSA/SHA-1 inerte) |
| `clean` `encrypt` `lock` `new` `signed` | 0 B | `rw-r--r--` | Nodi di controllo (non dati) — **mai letti/toccati** in questa sessione |

**Nota tecnica — dimensione dichiarata vs reale.** Per i blocchi protetti
(`r--------`), la dimensione **reale** del contenuto (`wc -c`, confermata
dall'hash SHA-256 identico locale/remoto) è spesso **inferiore** alla
dimensione dichiarata da `ls -la`/`stat()`. È un quirk noto degli pseudo-file
`/proc` custom: `st_size` riflette il buffer interno del driver, non la
lunghezza reale del dato generato. **Non è un errore di estrazione** — dove la
tabella dice "dichiarati" si intende il valore di `stat()`, non il numero di
byte effettivi.

Questo catalogo sostituisce la caratterizzazione vaga di `eripv2` come blob da
128 KB "non investigato" (§2/§4) con la mappa concreta del suo contenuto
esposto a runtime. Restano non identificati diversi blocchi (elencati sopra),
segnalati come tali e non come ipotesi.

**Aperto / da riconciliare — `VBNT-K` vs `VBNTJ`.** L'infoblock `0040` letto
qui riporta il mnemonico board `"VBNT-K"`, mentre altrove nel repo
(`FIRMWARE-INTERNALS-IT.md`, `GUIDA-ROOT-IT.md`) l'unità 2.4.5 ha
`DISTRIB_TARGET='brcm6xxx-tch/VBNTJ_502L07p1'`. Non è necessariamente una
contraddizione — potrebbero essere due cose distinte (stringa target di build
OpenWrt vs mnemonico board reale in RIP) — ma la discrepanza non è mai stata
riconciliata nel repo ed è segnalata qui come aperta.

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
- ~~Relazione esatta fra `rootfs` (la sotto-partizione dinamica ~44MB) e il
  contenuto squashfs dentro il bank attivo non ricostruita byte-per-byte —
  l'offset dello squashfs dentro l'immagine da 80MB varia per versione~~ —
  **risolto**: vedi [`FIRMWARE-INTERNALS-IT.md`](FIRMWARE-INTERNALS-IT.md) §1
  per gli offset reali osservati su 221/245 e la spiegazione (cambio di
  layout della flash, non crescita del kernel). Il riferimento originario a
  `RBI-FORMAT-IT.md` §3.2 era impreciso — quella sezione tratta l'evoluzione
  della configurazione dropbear/SSH, non gli offset dello squashfs.
- **Discrepanza kernel non ancora chiarita**: il log di boot del test del
  2026-08-23 (firmware `AGTEF_2.2.1_CLOSED.rbi` dalla cartella locale dei firmware) mostra
  `Linux version 3.4.11-rt19 ... Mar 9 2017` — kernel della generazione
  1.0.3→2.0.1_003 secondo `RBI-FORMAT-IT.md` §3.4, che invece attribuisce a
  2.2.0/2.2.1 il kernel 4.1.38. Non è un errore della pipeline di build (il
  kernel viene riusato verbatim dall'header/payload originale, non toccato
  dalla patch) — o il file sorgente nella cartella locale dei firmware non è il vero 2.2.1, o
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
