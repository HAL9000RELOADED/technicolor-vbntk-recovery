# What happens when you connect the UART

Annotated transcript of a real serial capture (`115200 8N1`) on the
Technicolor VBNT-K (DGA4130), from power-on through a booted Linux kernel,
plus a full BOOTP/TFTP recovery cycle triggered over the serial line. Every
code block below is **real text copied from the capture**, not
reconstructed — only cleaned of ANSI terminal control codes and, where
noted, truncated on purely repetitive stretches (e.g. the "kB received"
progress lines). Full log captured during the UART sessions of
2026-08-19/21, cross-referenced against the firmware container static
analysis in [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md).

For the hardware layout (SoC, NAND, MTD partitions) see
[`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md); this page is the
"what you actually see on the serial terminal" companion, not a hardware
analysis.

## Physical connection

- **Prolific PL2303** USB-serial adapter, **3.3V** logic levels (the SoC
  does not tolerate 5V on the UART pins) — TX/RX/GND to the pins on the
  board's UART header, no flow control.
- Port parameters: **115200 baud, 8 data bits, no parity, 1 stop bit
  (8N1)**.
- The COM port Windows assigns is not fixed (depends on when/how the
  adapter gets reconnected) — check it every session.
- **Warning**: the serial console stays live even once Linux has already
  booted. An actual serial BREAK (`send_break()`) or an unintended `Magic
  SysRq` sequence can kill every running userspace process, making a
  router that booted fine look "hung". The recovery-mode section below
  shows how to *deliberately* trigger recovery mode instead, using plain
  ASCII characters, not a BREAK.

## Stage 1 — Secure Boot ROM (BTRM)

The very first thing to appear on the terminal at power-on/reset, before
any readable banner, is a sequence of 4-character tags printed by
Broadcom's **Boot ROM** — burned into the BCM63138B0 silicon, not
modifiable by firmware. It verifies the chain of trust (cryptographic
signature of the image in NAND) before handing control to the actual
bootloader. **Exact, full transcript** of one observed block:

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

The block appears **twice in a row** in every capture (the Boot ROM runs
the sequence twice before handing off to CFE — a consistently observed
behavior, not a capture artifact). If this block never reaches `PASS`
(e.g. it stalls on `SBI?` without ever printing `SBIA`), the image in NAND
failed the Boot ROM's signature check — a deeper and stricter check than
the "BLI" validation CFE performs on files received over TFTP (see
[`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md)): the Boot ROM verifies the
signature of the image already written to NAND, CFE only checks the
`.rbi` container's structure as it comes in over the network, before ever
writing it.

## Stage 2 — CFE, a.k.a. "Technicolor Gateway"

Right after `PASS` comes the banner of the actual bootloader — in
TIM/Technicolor firmware it presents itself as "Technicolor Gateway", but
it's a Broadcom CFE (Common Firmware Environment) with custom branding.
First the checkpoint sequence runs again (this time "Block 2", different
from the first one — see the full table below), then DDR3 RAM
calibration, then the banner with the board's information:

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

After `DRAM` come dozens of DDR timing calibration lines (`Shmoo WL`,
`Shmoo RD DQ`, `Shmoo WR DQ` blocks, `ROSC` measurements — RAM gets
"trained" on every cold boot, this is neither an error nor something
requiring intervention), omitted here as purely diagnostic and not
informative about system behavior. At the end of calibration the actual
board banner appears:

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

The `*** Press b to enter BOOT-P ***` line is the window — a few tenths
of a second — during which sending `'b'` on the serial line forces network
recovery mode instead of the normal boot (see "Recovery mode" below). If
nothing is sent, the boot continues with `Starting the Linux kernel`.

## Stage 3 — Linux kernel (normal boot)

From here on the log is a plain ARM Linux kernel dmesg, in the clear. Real
excerpt, from kernel entry through mounting the main filesystem:

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

Real notes on this excerpt (not guesses — observed behavior):

- The `rootfs_data` partition (the writable JFFS2 overlay) mounts with a
  **CRC error on one node** (`jffs2_scan_inode_node(): CRC failed`), but
  the boot continues regardless — JFFS2 discards the corrupted node and
  rebuilds state from the remaining valid ones. It doesn't block boot, but
  it's a direct signal of an overlay filesystem that saw interrupted
  writes in the past (consistent with the bootloop history discussed in
  [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §3).
- The two printed MTD partition tables (one with 1 partition, one with 5)
  are **normal**: the `technicolor-nand-tl` driver does a first pass with
  just `rootfs` (bootstrap), then republishes the full 5-partition table
  once it has read the real `btab` (boot table) from NAND.
- `eRIPv2 secrets passed correctly to Linux` confirms that the `eripv2`
  partition (128KB, see `MEMORY-ARCHITECTURE-EN.md` §4) is actually read
  and exposed to the kernel as cryptographic material, not just a static
  analysis theory.

From here the boot continues with Ethernet switch initialization,
Quantenna WiFi (logged with a `[Quantenna]` prefix), `hostapd`, and
userspace services down to the login prompt — not reproduced here as it
isn't specific to the UART/bootloader path.

## Stage 4 — BOOTP/TFTP recovery mode (alternative to Stage 3)

If, during the `*** Press b to enter BOOT-P ***` window (Stage 2), ASCII
`'b'` characters are sent on the serial line — plain text, **not** a
BREAK — CFE abandons the normal boot and enters network recovery mode.
Real transcript of a full cycle, from the trigger to the final reset (the
`kB received/tested/programmed` progress lines, thousands of identical
repetitions at 128KB intervals, are truncated with `[...]` — actual device
output, not hand-summarized):

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

Real notes on this cycle:

- The `reason: BUTTON_PUSH` field in the log does **not literally**
  reflect what triggered recovery mode in this capture (it came from the
  serial line, not a physical button) — CFE labels any manual entry into
  BOOT-P this way, whether from a physical button or `'b'` over serial;
  not a bug, just a generic log string reused across triggers.
- The file requested over TFTP is `VBNT-K` — the filename in the BOOTP
  request matches the **Board Mnemonic** seen in the CFE banner
  (Stage 2), not a name chosen by the TFTP server: CFE determines it, the
  server only has to serve a file with that exact name (see
  [`GUIDE-EN.md`](GUIDE-EN.md) Part D for the PC-side network traffic).
  The reception observed here (28,138 KB, ≈28MB) is smaller than the
  ~80MB of a full bank — this router also accepts smaller partial/test
  `.rbi` images during serial-triggered recovery, confirming that the
  three-stage gate (`Testing` → `Flashing`) operates on the payload
  actually received, not on a fixed expected size.
- Three distinct, sequential phases after reception: **Testing**
  (validates the received payload before touching flash — presumably the
  structural "BLI" validation of the `.rbi` container, see
  [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md)), then **Flashing** (physical
  write to NAND, only once `Testing` has passed), then an automatic
  **reset**. A rejection for an invalid container (`File is not a valid
  BLI`, observed in other sessions — see `RBI-FORMAT-EN.md`) blocks the
  flow **before** `Testing started`, i.e. before touching NAND: a failed
  attempt due to a malformed file cannot corrupt the existing bank.
- After `Resetting the gateway` the Boot ROM sequence restarts identically
  from Stage 1 — a full software reset, not a simple re-jump into the
  bootloader.

## Full table of the 4-character checkpoints

These tags are low-level diagnostic checkpoints printed by the Boot ROM
(Block 1, before `HELO`) and by CFE during hardware initialization for the
CPU (Block 2, after `HELO`). They are not an error when you see them —
this is normal diagnostics baked into the silicon/bootloader, absent from
any public official Broadcom documentation. Tags with **clear,
unambiguous semantics** (names that directly mirror a known step of the
secure-boot chain) are explained individually; the rest are grouped
because their exact meaning cannot be verified from a public source.

| Checkpoint | Block | Meaning |
|---|---|---|
| `BTRM` | 1 | Boot ROM — start of the verification sequence |
| `V1.6` | 1 | Boot ROM version |
| `OTP?` → `OTPP` | 1 | Reading OTP (one-time-programmable) fuses → passed |
| `ROTB` | 1 | Root of Trust — base chain-of-trust check |
| `NAND` | 1 | NAND flash controller init |
| `IMG?` → `IMGL` | 1 | Searching for the boot image → image found/loaded |
| `HDR?` → `HDRP` | 1 | Reading the image header → header valid |
| `KEY?` → `KEYA` | 1 | Verifying the signing key → key accepted |
| `MID?` → `MIDP` | 1 | Market/Manufacturer ID check → passed |
| `SBI?` → `SBIA` | 1 | Verifying the Secure Boot Image signature → authenticated |
| `PASS` | 1 | Verification completed successfully — hands control to CFE |
| `HELO` | between 1 and 2 | CFE introduces itself with its version — end of Boot ROM, start of CFE |
| `CPU0` | 2 | Initialization referring to CPU 0 |
| `DRAM` | 2 | Start of DDR3 RAM calibration/training (the `Shmoo`/`ROSC` lines that follow) |

Tags **shared between the two blocks** (`PMCS`, `AFEL`, `PWRZ`, `MEML`,
`PMCD`, `CODE`, `MAIN`) and variants observed in only one block (`ZBSS` in
Block 1 / `ZBBS` in Block 2, `CACH` in Block 1 / `L1CD` in Block 2): this
is not a transcription error — the two bootloaders (Boot ROM and CFE)
call low-level subroutines with the same name for analogous tasks (power
management setup, section zeroing, cache) in two different contexts. The
exact meaning of these tags, plus `SCBT`, `MCV?`/`MCVA`, `APMT`, `PMCM`,
`MMUI`, **is not publicly documented by Broadcom** — any expansion (e.g.
"Power Management Controller" for `PMC*`) is a plausible guess from the
tag itself, not a confirmation from an official source, and is therefore
not offered here as certain.

## See also

- [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) — NAND layout,
  MTD partitions, dual-bank system, SoC/NAND datasheet.
- [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) — the `.rbi` container format
  (header, AES encryption, signature block, the "BLI" validation cited in
  Stage 4).
- [`GUIDE-EN.md`](GUIDE-EN.md) Parts D/E — PC-side BOOTP/TFTP network
  traffic (Wireshark, the bug found in Tftpd64) and the physical UART
  connection.

## Legal note

No proprietary ISP firmware image is redistributed in this repository —
the logs reproduced here are text transcripts of bootloader/kernel
diagnostic output; they do not contain and are not derived from any
firmware binary.
