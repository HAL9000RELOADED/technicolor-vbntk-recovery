# Cosa succede quando si collega la UART

Trascrizione commentata di una cattura seriale reale (`115200 8N1`) sul
Technicolor VBNT-K (DGA4130), dal power-on fino al kernel Linux avviato,
più il ciclo completo di recovery BOOTP/TFTP innescato da seriale. Ogni
blocco di codice sotto è **testo reale copiato dalla cattura**, non
ricostruito — solo ripulito dai codici di controllo ANSI del terminale e,
dove indicato, troncato nei tratti puramente ripetitivi (es. le righe di
progresso "kB received"). Log completo raccolto durante le sessioni UART
del 2026-08-19/21, cross-referenziato con l'analisi statica del formato
firmware in [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md).

Per il layout hardware (SoC, NAND, partizioni MTD) vedi
[`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md); questa pagina è
il complemento "cosa si vede sul terminale seriale", non un'analisi
dell'hardware.

## Collegamento fisico

- Adattatore USB-seriale **Prolific PL2303**, livelli **3,3V** (il SoC non
  tollera 5V sui pin UART) — TX/RX/GND ai pin dell'header UART sulla
  scheda, nessun controllo di flusso.
- Parametri porta: **115200 baud, 8 bit dati, nessuna parità, 1 bit di
  stop (8N1)**.
- La porta COM assegnata da Windows non è fissa (dipende da quando/come
  l'adattatore viene ricollegato) — va verificata a ogni sessione.
- **Attenzione**: la console seriale resta viva anche a Linux già avviato.
  Un vero BREAK seriale (`send_break()`) o una sequenza `Magic SysRq` non
  intenzionale possono terminare tutti i processi utente in corsa,
  facendo sembrare "bloccato" un router che in realtà ha fatto boot
  correttamente. Il capitolo "Modalità recovery" più sotto mostra invece
  come *innescare* la modalità di recovery deliberatamente, con normali
  caratteri ASCII, non un BREAK.

## Fase 1 — Boot ROM sicuro (BTRM)

La primissima cosa che compare sul terminale al power-on/reset, prima di
qualunque banner leggibile, è una sequenza di sigle di 4 caratteri stampate
dal **Boot ROM** di Broadcom — incorporato nel silicio del BCM63138B0, non
modificabile da firmware. Verifica la catena di fiducia (firma crittografica
dell'immagine in NAND) prima di cedere il controllo al bootloader vero.
Trascrizione **esatta e integrale** di un blocco osservato:

```
----
BTRM
V1.6
PMCS
AFEL
PWRZ
MEML
PMCD
MEMP
CODE
ZBSS
MAIN
CACH
OTP?
OTPP
ROTB
SCBT
NAND
IMG?
IMGL
HDR?
HDRP
MCV?
KEY?
KEYA
MID?
MIDP
MCVA
SBI?
SBIA
PASS
----
```

Il blocco compare **due volte di seguito** in ogni cattura (il Boot ROM
gira la sequenza due volte prima di passare a CFE — comportamento
osservato in modo consistente, non un artefatto della cattura). Se questo
blocco non arriva a `PASS` (es. si ferma su `SBI?` senza mai stampare
`SBIA`), l'immagine in NAND ha fallito la verifica di firma del Boot
ROM — un controllo più profondo e più rigido della validazione "BLI" che
CFE fa sui file ricevuti via TFTP (vedi [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md)):
il Boot ROM verifica la firma dell'immagine già scritta in NAND, CFE
verifica solo la struttura del contenitore `.rbi` ricevuto in rete, prima
ancora di scriverlo.

## Fase 2 — CFE, alias "Technicolor Gateway"

Subito dopo `PASS` compare il banner del bootloader vero e proprio — nel
firmware ISP/Technicolor si presenta come "Technicolor Gateway", ma è
un CFE (Common Firmware Environment) Broadcom con branding personalizzato.
Prima si ripresenta la sequenza di checkpoint (stavolta il "Blocco 2",
diverso dal primo — vedi la tabella completa più sotto), poi la
calibrazione della RAM DDR3, poi il banner con le informazioni della
scheda:

```
HELO
4.1603-1.0.38-116.174
CPU0
PMCM
PMCS
AFEL
PWRZ
MEML
APMT
PMCD
L1CD
MMUI
CODE
ZBBS
MAIN
DRAM
NVRAM memcfg 0x427
MCB chksum 0xf67f5b05
DDR3-1600 CL11 512MB

MemsysInit lpe2_custom 0p10 20140709
DDR3
80711258 80003000 00000070 016028BC
MCB rev=0x00020201 Ref ID=0x028BC Sub Bld=0x016
```

Dopo `DRAM` seguono decine di righe di calibrazione timing DDR (blocchi
`Shmoo WL`, `Shmoo RD DQ`, `Shmoo WR DQ`, misure `ROSC` — la RAM viene
"allenata" a ogni boot freddo, non è un errore né richiede intervento),
omesse qui perché puramente diagnostiche e non informative sul
comportamento del sistema. Alla fine della calibrazione compare il banner
vero e proprio della scheda:

```
Technicolor Gateway
(c) 2016, All rights reserved

Gateway initialization sequence started
Status wait timeout: nandsts=0x70000000 mask=0x40000000, count=0
Boot Loader Version : 16.11.1013-0000000-20160314084347-870409210027d7bcfa4d54666160c0bb5322e291
Boot Loader OID     : unofficialbuildOID0000
CPU                 : BCM63138B0
RAM                 : 512MB
Flash               : 250MB NAND
Board Mnemonic      : VBNT-K
Market ID           : FFFC
*** Press b to enter BOOT-P ***                    Booting             : Bank 1
SW Version          : 18.3.k.0451-3161014-20191025182009-3f83315f6d40733756f2a3ef5b192653d99f3c87
Starting the Linux kernel

Enabling watchdog
Code Address: 0x00008000, Entry Address: 0x00008000
Decompression OK!
Entry at 0x00008000
Closing network.
Starting program at 0x00008000
```

La riga `*** Press b to enter BOOT-P ***` è la finestra — pochi decimi di
secondo — in cui inviare `'b'` sulla seriale forza la modalità di recovery
di rete invece del boot normale (vedi "Modalità recovery" più sotto). Se
non si interviene, il boot prosegue con `Starting the Linux kernel`.

## Fase 3 — kernel Linux (boot normale)

Da qui in poi il log è un normale dmesg del kernel Linux ARM, in chiaro.
Estratto reale, dall'ingresso in kernel space fino al montaggio del
filesystem principale:

```
[    0.000000] Booting Linux on physical CPU 0x0
[    0.000000] Linux version 4.1.38 (repowrt-builder@ff55a63a23d5) (gcc version 5.3.0 (OpenWrt GCC 5.3.0 unknown) ) #1 SMP PREEMPT Wed Oct 16 15:21:10 UTC 2019
[    0.000000] CPU: ARMv7 Processor [414fc091] revision 1 (ARMv7), cr=10c5387d
[    0.000000] Machine: BCM963138
[    0.000000] Kernel command line: console=ttyS0,115200 irqaffinity=0 debug root=/dev/mtdblock1 rootfstype=squashfs coherent_pool=1M tbbt_addr=0xfaa0000 btab=0xb800c btab_bootid=1 bl_version=16.11.1013-0000000-20160314084347-870409210027d7bcfa4d54666160c0bb5322e291 board=VBNT-K platform.prozone_addr=0x1ffe0000 bl_oid=unofficialbuildOID0000
[    0.421895] Calibrating delay loop... 1319.93 BogoMIPS (lpj=659968)
[    0.548116] Brought up 2 CPUs
[    0.550566] SMP: Total of 2 processors activated (2650.11 BogoMIPS).
[    0.763461] squashfs: version 4.0 (2009/01/31) Phillip Lougher
[    0.768914] jffs2: version 2.2 (NAND) (SUMMARY) (ZLIB) (LZMA) (RTIME) (CMODE_PRIORITY) (c) 2001-2006 Red Hat, Inc.
[    0.790191] Broadcom NAND controller (BrcmNand Controller)
[    0.821933] brcmnand_read_id: CS0: dev_id=2cda9095
[    0.845419] busWidth=1, pageSize=2048B, page_shift=11, page_mask=000007ff
[    0.852402] BrcmNAND mfg 2c da MICRON MT29F2G08ABA 256MB on CS0
[    0.928824] brcmnand_scan, eccsize=512, writesize=2048, eccsteps=4, ecclevel=4, eccbytes=7
[    0.968515] parse_btab: num_banks (5)
[    0.972269] Creating 1 MTD partitions on "technicolor-nand-tl":
[    0.978206] 0x000005c10000-0x00000aa00000 : "rootfs"
[    0.983302] mtd: partition "rootfs" doesn't start on an erase block boundary -- force read-only
[    0.992911] Creating 5 MTD partitions on "technicolor-nand-tl":
[    0.998415] 0x0000000e0000-0x000005a00000 : "rootfs_data"
[    1.004491] 0x000005a00000-0x00000aa00000 : "bank_1"
[    1.009603] 0x00000aa00000-0x00000fa00000 : "bank_2"
[    1.014805] 0x000000080000-0x0000000a0000 : "eripv2"
[    1.019898] 0x0000000a0000-0x0000000e0000 : "rawstorage"
[    2.960247] VFS: Mounted root (squashfs filesystem) readonly on device 31:1.
[    4.585921] init: Console is alive
[    7.344701] init: - preinit -
[    9.106625] jffs2: jffs2_scan_inode_node(): CRC failed on node at 0x04d75fc4: Read 0xffffffff, calculated 0xbfb5396f
switching to overlay
mounting overlay fs
[   10.442882] eRIPv2 secrets passed correctly to Linux
[   10.485265] Set board (VBNT-K)
```

Note reali su questo estratto (non ipotesi — comportamento osservato):

- La partizione `rootfs_data` (l'overlay JFFS2 scrivibile) viene montata
  con un **errore CRC su un nodo** (`jffs2_scan_inode_node(): CRC
  failed`), ma il boot prosegue comunque — JFFS2 scarta il nodo corrotto e
  ricostruisce lo stato dai nodi validi rimanenti. Non blocca il boot, ma
  è un segnale diretto di un filesystem overlay che ha visto scritture
  interrotte in passato (coerente con la storia di bootloop discussa in
  [`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) §3).
- Le due tabelle di partizioni MTD stampate (una da 1 partizione, una da 5)
  sono **normali**: il driver `technicolor-nand-tl` fa un primo passaggio
  con solo `rootfs` (bootstrap), poi ripubblica la tabella completa a 5
  partizioni una volta letto il `btab` (boot table) reale dalla NAND.
- `eRIPv2 secrets passed correctly to Linux` conferma che la partizione
  `eripv2` (128KB, vedi `MEMORY-ARCHITECTURE-IT.md` §4) viene letta ed
  esposta al kernel come materiale crittografico, non solo teorizzato da
  analisi statica.

Da qui il boot prosegue con l'inizializzazione dello switch Ethernet, del
WiFi Quantenna (loggato con prefisso `[Quantenna]`), di `hostapd`, e dei
servizi userspace fino al prompt di login — non riportato qui perché non
specifico del percorso UART/bootloader.

## Fase 4 — modalità recovery BOOTP/TFTP (alternativa alla Fase 3)

Se durante la finestra `*** Press b to enter BOOT-P ***` (Fase 2) si
inviano sulla seriale caratteri ASCII `'b'` — testo semplice, **non** un
BREAK — CFE abbandona il boot normale ed entra in modalità di recovery via
rete. Trascrizione reale di un ciclo completo, dal trigger fino al reset
finale (le righe di avanzamento `kB received/tested/programmed`, migliaia
di ripetizioni identiche a intervalli di 128KB, sono troncate con `[...]`
— il contenuto realmente stampato dal dispositivo, non riassunto a mano):

```
*** Press b to enter BOOT-P ***                    Entering BOOT-P mode (reason: BUTTON_PUSH )
BOOTP Reply received
Local IP:        192.168.1.50
BOOTP Server IP: 192.168.1.2
TFTP Server IP:  192.168.1.2
Filename:        VBNT-K
TFTP started
*** 0 kB received ****** 50 kB received ****** 100 kB received ****** [...] ****** 28138 kB received ***
TFTP finished
Testing started
*** 128 kB tested ****** 256 kB tested ****** [...] ****** 81920 kB tested ***
Testing finished
Flashing started
*** 128 kB programmed ****** 256 kB programmed ****** [...] ****** 81920 kB programmed ***
Flashing finished
Resetting the gateway
----
BTRM
V1.6
[...]
PASS
----
HELO
4.1603-1.0.38-116.174
[...]
```

Note reali su questo ciclo:

- Il campo `reason: BUTTON_PUSH` nel log **non riflette letteralmente**
  cosa ha innescato la modalità in questa cattura (è arrivata da seriale,
  non da tasto fisico) — CFE etichetta così qualunque ingresso manuale in
  BOOT-P, tasto fisico o `'b'` da seriale che sia; non è un bug, solo una
  stringa di log generica riusata per più trigger.
- Il file richiesto via TFTP è `VBNT-K` — il nome file nella richiesta
  BOOTP coincide col **Board Mnemonic** visto nel banner CFE (Fase 2), non
  un nome scelto dal server TFTP: è CFE a determinarlo, il server deve
  solo servire un file con quel nome esatto (vedi
  [`GUIDA-IT.md`](GUIDA-IT.md) Parte D per il traffico di rete lato PC).
  La ricezione osservata qui (28.138 KB, ≈ 28MB) è più piccola degli
  ~80MB di un bank pieno — questo router accetta anche immagini `.rbi`
  parziali/di test più piccole di un bank intero durante il recovery via
  seriale, il che conferma che il limite dei tre stadi (`Testing` →
  `Flashing`) opera sul payload ricevuto, non su una dimensione fissa
  attesa.
- Tre fasi distinte e sequenziali dopo la ricezione: **Testing** (verifica
  del payload ricevuto, prima di toccare la flash — presumibilmente la
  validazione strutturale "BLI" del contenitore `.rbi`, vedi
  [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md)), poi **Flashing** (scrittura
  fisica in NAND, solo dopo che `Testing` è passato), poi **reset**
  automatico. Un rifiuto per contenitore non valido (`File is not a valid
  BLI`, osservato in sessioni diverse — vedi `RBI-FORMAT-IT.md`) blocca il
  flusso **prima** di `Testing started`, quindi prima di toccare la NAND:
  un tentativo fallito per formato non corretto non rischia di corrompere
  il bank esistente.
- Dopo `Resetting the gateway` la sequenza Boot ROM riparte identica dalla
  Fase 1 — un reset software pieno, non un semplice re-jump nel
  bootloader.

## Tabella completa dei checkpoint a 4 caratteri

Le sigle sono checkpoint diagnostici di basso livello stampati dal Boot
ROM (Blocco 1, prima di `HELO`) e da CFE durante l'inizializzazione
hardware per la CPU (Blocco 2, dopo `HELO`). Non sono un errore quando si
vedono — sono la normale diagnostica incorporata nel silicio/bootloader,
assente da qualunque documentazione ufficiale Broadcom pubblica. Le
sigle con **semantica chiara e non ambigua** (nomi che rispecchiano
direttamente un passo noto della catena di secure boot) sono spiegate
singolarmente; le altre sono raggruppate perché il loro significato esatto
non è verificabile da fonte pubblica.

| Checkpoint | Blocco | Significato |
|---|---|---|
| `BTRM` | 1 | Boot ROM — inizio della sequenza di verifica |
| `V1.6` | 1 | Versione del Boot ROM |
| `OTP?` → `OTPP` | 1 | Lettura fusibili OTP (one-time-programmable) → superata |
| `ROTB` | 1 | Root of Trust — verifica base della catena di fiducia |
| `NAND` | 1 | Init controller NAND flash |
| `IMG?` → `IMGL` | 1 | Ricerca immagine di boot → immagine trovata/caricata |
| `HDR?` → `HDRP` | 1 | Lettura header immagine → header valido |
| `KEY?` → `KEYA` | 1 | Verifica chiave di firma → chiave accettata |
| `MID?` → `MIDP` | 1 | Controllo Market/Manufacturer ID → superato |
| `SBI?` → `SBIA` | 1 | Verifica firma della Secure Boot Image → autenticata |
| `PASS` | 1 | Verifica completata con successo — passa il controllo a CFE |
| `HELO` | tra 1 e 2 | CFE si presenta con la propria versione — fine del Boot ROM, inizio di CFE |
| `CPU0` | 2 | Inizializzazione riferita alla CPU 0 |
| `DRAM` | 2 | Inizio calibrazione/training della RAM DDR3 (righe `Shmoo`/`ROSC` che seguono) |

Sigle **condivise fra i due blocchi** (`PMCS`, `AFEL`, `PWRZ`, `MEML`,
`PMCD`, `CODE`, `MAIN`) e varianti osservate solo in un blocco (`ZBSS` nel
Blocco 1 / `ZBBS` nel Blocco 2, `CACH` nel Blocco 1 / `L1CD` nel Blocco 2):
non è un errore di trascrizione — i due bootloader (Boot ROM e CFE)
richiamano sotto-routine di basso livello con lo stesso nome per compiti
analoghi (setup power management, azzeramento sezioni, cache) in due
contesti diversi. Il significato esatto di queste sigle, più `SCBT`,
`MCV?`/`MCVA`, `APMT`, `PMCM`, `MMUI`, **non è documentato pubblicamente da
Broadcom** — qualunque espansione (es. "Power Management Controller" per
`PMC*`) è un'ipotesi plausibile dalla sigla stessa, non una conferma da
fonte ufficiale, e per questo non viene proposta qui come certa.

## Vedi anche

- [`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) — layout NAND,
  partizioni MTD, sistema dual-bank, datasheet SoC/NAND.
- [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) — formato del contenitore `.rbi`
  (header, cifratura AES, blocco firma, validazione "BLI" citata in Fase
  4).
- [`GUIDA-IT.md`](GUIDA-IT.md) Parte D/E — traffico di rete BOOTP/TFTP
  lato PC (Wireshark, bug scoperto in Tftpd64) e collegamento fisico UART.

## Nota legale

Nessuna immagine firmware proprietaria dell'ISP viene ridistribuita in
questo repository — i log qui riportati sono trascrizioni testuali di
output diagnostico del bootloader/kernel, non contengono e non derivano
da alcun binario firmware.
