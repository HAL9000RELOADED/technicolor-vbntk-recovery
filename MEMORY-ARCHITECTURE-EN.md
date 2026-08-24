# Memory architecture of the Technicolor VBNT-K (DGA4130)

NAND layout, dual-bank system, and partitions relevant to anyone doing
recovery, downgrades, or firmware patching. Derived from a real serial boot
log (Linux kernel, `technicolor-nand-tl` driver) captured on physical
hardware — not from official documentation. Full log captured 2026-08-23.

## 1. Hardware

- SoC: Broadcom **BCM63138B0**
- RAM: **512MB**
- Flash: **256MB NAND**, **Micron MT29F2G08ABA** chip (`mfg 2c da`, `dev_id=2cda9095`), 128K block size, 2048 writesize, BCH4 ECC (2K)
- Bootloader: CFE, typical "Boot Loader Version" `16.11.1013-...`, board mnemonic `VBNT-K`

### 1.1 Datasheet — Broadcom BCM63138B0 SoC

Broadcom does not publish a downloadable official datasheet for this class
of gateway SoC (NDA-only material for licensees). The data below is split
into two groups: values **directly observed** on this unit's serial boot
log (full log in `UART-BOOT-LOG-EN.md`), and values **publicly known** for
the BCM63138 family from secondary sources (OpenWrt/linux-brcm63xx open
source drivers, hack-technicolor documentation, Broadcom marketing
collateral) — the latter explicitly flagged, since they cannot be
independently verified on this specific hardware.

| Parameter | Value | Source |
|---|---|---|
| CPU | Dual-core ARM Cortex-A9 (ARMv7, rev 1), SMP | Observed: `CPU: ARMv7 Processor [414fc091]`, `Brought up 2 CPUs` |
| L2 cache | PL310 (L2C-310), 16-way, 512 KB | Observed: `L2C-310 cache controller enabled, 16 ways, 512 kB` |
| Interrupt controller | Cortex-A9 MPCORE GIC | Observed: `Cortex A9 MPCORE GIC init` |
| Estimated speed | ~1319 BogoMIPS/core (`lpj=659968`) — **not an exact clock measurement**, only an order of magnitude | Observed (kernel calibration) |
| Publicly advertised max clock for the family | up to ~1 GHz per core | Public, not verified on this unit |
| Memory controller | DDR3/DDR3L, up to DDR3-1600 | Observed: `DDR3-1600 CL11 512MB`, `NVRAM memcfg 0x427` |
| NAND controller | `BrcmNand`, version **7.0** | Observed: `Brcm NAND controller version = 7.0` |
| Packet accelerator | "Runner"/BPM/Packet Flow Cache (hardware L2-L4 offload) | Observed: driver names `Broadcom Runner Blog Driver`, `Broadcom Packet Flow Cache` |
| PCIe | 2 PCIe cores, 1 lane each (Rev 3.01) | Observed: `bcm963xx-pcie: found core [0]`/`[1]` |
| UART | 2x BCM63XX UART (`ttyS0`, `ttyS1`), base_baud 921600, console at **115200 8N1** | Observed: `Serial: BCM63XX driver`, `ttyS0 at MMIO 0xfffe8600` |
| Secure boot ROM | Cryptographic verification (RSA/SHA) via 4-character checkpoints (`BTRM`...`PASS`) before starting CFE | Observed + firmware static analysis, see `UART-BOOT-LOG-EN.md` |
| Process node / package | Not found from a reliable public source | — omitted, not a guess from a secondary datasheet |

### 1.2 Datasheet — Micron MT29F2G08ABA NAND

The kernel driver prints the chip's identity in full, so everything here is
**directly verified** on the unit (no external datasheet needed for the
geometry parameters — Linux itself already confirmed them during probe):

```
[    0.821933] brcmnand_read_id: CS0: dev_id=2cda9095
[    0.845419] busWidth=1, pageSize=2048B, page_shift=11, page_mask=000007ff
[    0.852402] BrcmNAND mfg 2c da MICRON MT29F2G08ABA 256MB on CS0
[    0.898628] page_shift=11, bbt_erase_shift=17, chip_shift=28, phys_erase_shift=17
[    0.913768] ECC layout=brcmnand_oob_bch4_2k
[    0.928824] brcmnand_scan, eccsize=512, writesize=2048, eccsteps=4, ecclevel=4, eccbytes=7
```

| Parameter | Value | Source |
|---|---|---|
| Manufacturer ID / Device ID | `0x2C` (Micron) / `0xDA` | Observed: `mfg 2c da`, `dev_id=2cda9095` |
| Type | SLC NAND, 2 Gbit (256 MB) | Observed: `MICRON MT29F2G08ABA 256MB` |
| Bus width | 8-bit (`busWidth=1`) | Observed |
| Page | 2048-byte data + 64-byte spare (`oobsize=64`) | Observed: `pageSize=2048B`, `mtd->oobsize=64` |
| Block | 128 KB = 64 pages (`erase_shift=17` → 2¹⁷ bytes) | Observed: `Block size=00020000, erase shift=17` |
| ECC required by the chip | minimum 4-bit correction per 512 bytes | Indirectly observed: the driver uses exactly `eccsize=512`, `ecclevel=4` (BCH-4), consistent with the typical minimum threshold for Micron SLC families of this generation |
| Typical endurance published for the family | ≥ 100,000 P/E cycles (SLC class) | Public (generic Micron SLC family datasheet, not measured on this unit) |
| Typical operating voltage for the family | 3.3V (2.7–3.6V range) | Public, not measured — consistent with the UART adapter used in this project (PL2303 at 3.3V, see `UART-BOOT-LOG-EN.md`) |
| Typical published family timings (program/erase) | program ~200µs typ. / 700µs max; erase ~1.5ms typ. / 3ms max | Public, indicative values for the product class — not measured on this unit |

## 2. MTD partition table

Printed by the `technicolor-nand-tl` driver on every boot (`parse_btab: num_banks (5)`):

| Range (bytes) | Name | Size | Notes |
|---|---|---|---|
| `0x000000080000`–`0x0000000a0000` | `eripv2` | 128 KB | See §4 — likely the OSCK/OSIK/EIK keys (`.rbi` format) |
| `0x0000000a0000`–`0x0000000e0000` | `rawstorage` | 256 KB | Purpose not identified — generic name, not investigated yet |
| `0x0000000e0000`–`0x000005a00000` | `rootfs_data` | ~89 MB | **Persistent writable overlay**, see §3 |
| `0x000005a00000`–`0x00000aa00000` | `bank_1` | 80 MB (`0x5000000`) | Complete firmware image (kernel+squashfs) |
| `0x00000aa00000`–`0x00000fa00000` | `bank_2` | 80 MB (`0x5000000`) | Complete firmware image, twin of bank_1 |
| `0x000005c00000`–`0x000008860000` | `rootfs` | ~44 MB (dynamic) | **Dynamic** sub-partition: points into the squashfs portion of whichever bank is active — moves with `/proc/banktable/active` |

`0x5000000` (80MB) matches exactly the size of a raw payload decrypted from
a `.rbi` (see `RBI-FORMAT-EN.md` §2.3) — confirming a VBNT-K `.rbi` always
carries the content of **one entire bank**, never a subset.

## 3. Dual-bank system and `/etc` persistence

- `bank_1`/`bank_2`: two complete, independent copies of kernel+squashfs.
  `/proc/banktable/booted` and `/proc/banktable/active` (readable/writable
  as root over SSH, see `GUIDE-ROOT-EN.md`) indicate which bank is currently
  running and which will be used on next boot — a classic A/B scheme
  (update the inactive bank, then switch, with an easy rollback if the new
  bank fails to boot).
- The actual rootfs is **read-only** (squashfs; boot log:
  `VFS: Mounted root (squashfs filesystem) readonly on device 31:1`).
- Right after, the kernel mounts `rootfs_data` (JFFS2) and does
  `switching to overlay` / `mounting overlayfs fs`: **`/etc` (and other
  writable paths) are actually an overlayfs** — squashfs as the read-only
  lower layer, `rootfs_data` as the writable upper layer.
- **Critical point for anyone patching/rooting**: `rootfs_data` is **a
  single shared partition, separate from bank_1/bank_2**, not contained
  inside either bank's 80MB image. Rewriting a bank (via `mtd write` as
  root, or via BOOTP/TFTP recovery) **does not touch `rootfs_data`**.
  Any file written to the overlay by an earlier boot (e.g. a rooting
  attempt done in a different session, weeks earlier) **survives
  indefinitely** across later reflashes and **shadows** the versions
  present in the new squashfs for the same path, due to ordinary overlayfs
  semantics (upper layer wins).

  Verified practical consequence (2026-08-23): a confirmed-successful
  (SHA-256 hash matched) flash of a patched `221` with new `/etc/passwd` +
  `/etc/shadow` + `/etc/config/dropbear` (to enable root SSH) was not
  enough to unlock SSH login — leading hypothesis, not yet confirmed, is
  that earlier versions of these same files written to `rootfs_data` by a
  prior attempt on this router are still in effect. See
  `RBI-FORMAT-EN.md` §5.3 for the test details. **A genuinely clean test**
  would require clearing `rootfs_data` (factory reset via 7 seconds on the
  reset button while the router is already powered on — a different
  procedure from BOOTP/TFTP recovery; **a first attempt, 2026-08-23, was
  inconclusive**: this same reset had already been tried before on this
  router for a different problem without fixing it) or, as root, explicitly
  wiping/reinitializing the partition.

## 4. `eripv2` — likely the firmware encryption keys

The name (`erip` = **E**ncrypted **R**oot **I**nfo **P**artition? not
confirmed) and especially the kernel command-line parameter observed at
boot (`platform.r2secr=0x1ffdf000`) match exactly the **`r2secr`** kernel
driver used by the community tool
[`pedro-n-rocha/secr`](https://github.com/pedro-n-rocha/secr) to extract
`ECKey`/`OSCK`/`OSIK`/`EIK` from a rooted device (see `rip2.h`,
`rip2_crypto.h`, `ripdrv.h` in that tool's source). Working hypothesis, not
yet directly verified on this hardware: this small (128KB) partition holds
the per-board cryptographic material used by the bootloader for `.rbi` AES
encryption (see `RBI-FORMAT-EN.md` §2.1) — this would explain why OSCK is
"per board model" (see the dedicated note in that file) rather than
generated on the fly.

Related note: the "THENC" configuration backup format (see
`root/import_config.py`) uses a separate AES-256/HMAC-SHA1 key, read at
runtime from `/proc/rip/0108` — the same `rip`/`ripdrv` sub-system, but
likely distinct key material from what's used for `.rbi` files.

## 5. Open questions / to verify

- `rawstorage` (256KB): unknown purpose, name too generic to guess from —
  worth investigating if a way to read it as root is found.
- Not verified whether BOOTP/TFTP recovery always writes to a fixed bank
  (e.g. always the currently "booted" one) or can be targeted at the other
  bank — in the 2026-08-23 tests it always wrote to and booted from Bank 1,
  but the router was already on Bank 1 before the test, so this doesn't
  distinguish between the two hypotheses.
- The exact relationship between `rootfs` (the ~44MB dynamic
  sub-partition) and the squashfs content inside the active bank hasn't
  been reconstructed byte-for-byte — the squashfs offset inside the 80MB
  image varies by version (see `RBI-FORMAT-EN.md` §3.2 for the offsets
  observed on 221/245).
- **Unexplained kernel discrepancy**: the 2026-08-23 test's boot log
  (firmware `AGTEF_2.2.1_CLOSED.rbi` from `F:\Modem`) shows
  `Linux version 3.4.11-rt19 ... Mar 9 2017` — a kernel from the
  1.0.3→2.0.1_003 generation per `RBI-FORMAT-EN.md` §3.4, which instead
  attributes kernel 4.1.38 to 2.2.0/2.2.1. This isn't a build-pipeline
  error (the kernel is reused verbatim from the original header/payload,
  untouched by the patch) — either the source file in `F:\Modem` isn't
  genuinely 2.2.1, or the kernel→version mapping in §3.4 needs revisiting.
  Not yet investigated.
