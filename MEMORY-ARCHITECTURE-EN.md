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

### 2.1 Comparison: `/proc/mtd` on a different, already-rooted unit, firmware AGTEF_2.2.1

Data collected in a separate session (2026-08-27), **on a physical unit
different** from the one this document is based on (MAC/serial not
published), running firmware **AGTEF_2.2.1** (OpenWrt Chaos Calmer 15.05.1,
kernel 4.1.38) — so not directly comparable to the 2.4.5 discussed
elsewhere in this repo, but useful as a second data point for the same
board model:

```
mtd0: 10000000 00020000 "brcmnand.0"   (whole chip, 256MB)
mtd1: 04df0000 00020000 "rootfs"       (81,723,392 bytes, squashfs, ro)
mtd2: 05920000 00020000 "rootfs_data"  (93,323,264 bytes ≈ 89MB)
mtd3: 05000000 00020000 "bank_1"       (83,886,080 bytes = 80MB)
mtd4: 05000000 00020000 "bank_2"       (83,886,080 bytes = 80MB)
mtd5: 00020000 00020000 "eripv2"       (131,072 bytes = 128KB)
mtd6: 00040000 00020000 "rawstorage"   (262,144 bytes = 256KB)
```

`eripv2`, `rawstorage`, `rootfs_data`, `bank_1`, `bank_2` match the table
above **exactly** in size. The difference is `rootfs`: here it appears as
a **standalone MTD node** (`mtd1`, ~81.7MB, almost as large as a full
bank), not as the ~44MB dynamic sub-partition inside the active bank
described above. Unclear whether this is a firmware/kernel-version
difference (different partition-table generation in
`technicolor-nand-tl` between 2.2.1 and 2.4.5) or a hardware revision —
**not verified**, noted here only as a comparison point for anyone working
on other units/versions. Live mount observed on this same unit: `mtd1`
("rootfs") mounted **ro** on `/rom`; `mtd2` ("rootfs_data") mounted **rw**
on `/overlay`, matching the classic squashfs+overlayfs scheme from §3.

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

### 4.1 "THENC" format (configuration backup) — mechanism confirmed from source code

Update 2026-08-27: the hypothesis about the "THENC" backup (see
`root/import_config.py`) is now **confirmed by directly reading the Lua
source** (`/usr/lib/lua/transformer/shared/ConfigCommon.lua`) on **a
different unit** than the one this document is based on, running firmware
**AGTEF_2.2.1** (not 2.4.5 — an older version, so the confirmation is on the
mechanism, not guaranteed byte-identical on 2.4.5, though the `transformer`
module is shared across versions and doesn't appear changed in the diffs
documented so far in `VERSION-CHANGELOG-EN.md`):

- Plaintext file header: `PREAMBLE=THENC`, `BACKUPVERSION=1.00`,
  `BOARDMNEMONIC`, `PRODUCTNAME`, `SERIALNUMBER`, `MAC`, `BUILDVERSION`,
  `CIPHERKEY=GW`, `SIGNATUREKEY=GW` — `GW` is an **alias**, not the key
  itself.
- Alias `"GW"` → key read from `/proc/rip/0108` (`rip_random_B` in the
  source): AES key = **first 32 bytes**, HMAC key = **first 64 bytes** of
  the same blob.
- Alternate alias `"GW_KEYD"` (not used by default, only if
  `system.config.export_commonkey`/`import_commonkey` is explicitly set)
  → key from `/proc/rip/012b` (`rip_random_D`): AES = bytes 1–32, HMAC =
  bytes 33–96.
- Scheme: `cipher_scheme = "AES-256-CBC"`, `signature_scheme = "HMAC-SHA1"`.
- Verified on the 2.2.1 unit: no active UCI override (default `"GW"`
  confirmed in use), `export_plaintext`/`export_unsigned` = 0 (encryption+
  signing active as normal).

**Not transferable between units**: the material at `/proc/rip/0108` is
per-board (same `rip`/`ripdrv` sub-system as §4, plausibly per-unit like
OSCK/OSIK), so knowing the algorithm does not let you decrypt a different
unit's `config.bin` without reading that unit's own key as root — for this
reason, no byte of the observed key is published here, only the mechanism.

### 4.2 End-to-end practical confirmation on two real backups of the same device (2026-09-09)

Update 2026-09-09: the THENC mechanism described in §4.1 is now **verified
working end-to-end on a real file** — no longer just inferred from the Lua
source. Two **real `config.bin` backups of the same device** were compared
(same `SERIALNUMBER`, same `MAC` `10:13:31:xx:xx:xx`, same
`BUILDVERSION=AGTEF_2.4.5`) taken ~8 months apart, decrypted using the
device's **real hardware key** read from `/proc/rip/0108`:

- Both files: **valid HMAC-SHA1** on decryption, i.e. the whole chain
  `ASCII header → IV (16 bytes) → AES-256-CBC → HMAC-SHA1`, with the key
  derived from `/proc/rip/0108` (AES = first 32 bytes, HMAC = first 64 bytes),
  is confirmed correct on real data. This is the **first practical
  confirmation** that the mechanism described in prose in §4.1 actually works
  on a genuine `config.bin`, not just in theory.
- Identical header between the two (same device): only the **IV** and the
  **HMAC signature** change (expected: they depend on the content and on the
  per-backup random IV), plus the encrypted payload size.
- Tool used: `thenc_tool.py` (subcommands `parse`/`decrypt`/`diff`, the last
  with `--key-file` for the plaintext comparison) — available as a reusable
  utility to repeat the operation.

**Categorized summary of what changes over time** (NOT a line-by-line diff, NO
real values reproduced — only the *type* of settings, useful to know what to
expect in the decrypted content of a device in use):

- **Device hostname**: changes from the factory default to a user-chosen name.
- **`[modgui]` section (provisioning/modding)**: **present or absent**
  depending on whether the GUI root/patch is active. On a rooted device's
  backup the whole section appears (version-spoofing flags, CWMP-update
  disable, modded-GUI hash/credentials, list of enabled apps); on a "stock"
  backup it does not exist. It is the clearest indicator that modding is
  present.
- **Declared "passive bank" firmware version**
  (`env.var.friendly_sw_version_passivebank`): changes from a real version to
  a very high fake value (pattern `x.99.99.99`). Interesting because it seems
  used as **anti-downgrade-detection**: by declaring the passive bank as
  already "newer", the provider/CWMP is discouraged from rolling the device
  back to an earlier version present in the other bank.
- **DDNS credentials**: move from **default placeholders**
  (`your_username` / `your_password` / `yourhost.example.com` / generic
  service) to a real user-configured service/hostname/credentials.
- **VoIP/SIP profile** (`mmpbxrvsipnet.sip_profile_0` and `sip_net`): moves
  from **`line0` placeholders** (user/uri/password all = `line0`, profile
  disabled) to a real phone number and credentials, with the profile enabled
  and the provider's SIP proxies/realm populated.
- **Firewall level and rules**: the declared level changes
  (`firewall.fwconfig.level`, e.g. from `normal` to `lax`), the WAN zone input
  policy changes (e.g. from `DROP` to `REJECT`), and user-defined rules and
  port-forwards appear/disappear (redirects toward internal LAN hosts).
- **Web user roles** (`web.usr_*`): the defined users and their roles change
  (`admin` / `engineer` / `guest`), along with the SRP verifiers/salts and the
  set of accessible UI rules/pages — consistent with enabling a GUI with
  different privileges.
- **NTP servers** (`system.ntp.server`): move from **ISP-internal servers**
  (hosts `*.interbusiness.it` / `inrim.it`) to **public pools**
  (`pool.ntp.org`, `it.pool.ntp.org`).
- **WiFi key**: changed by the user (value **not reproduced here**).
- Various other service toggles (UPnP/NAT-PMP, printer/file sharing, DLNA,
  samba, watchdog, etc.) change state but carry no sensitive content.

**Technical finding — serial-derivable fields vs ACS-only fields**: in the
decrypted content two classes of "user" data can be distinguished:

- Fields **reconstructable locally from the device serial**: e.g.
  `network.wan.username` follows the deterministic pattern
  `<SERIALNUMBER>-101331@<realm>` (where `101331` derives from the leading
  digits of the device MAC/OUI). These require no external knowledge: given
  the serial (which is in the plaintext THENC header) and the provider realm,
  they can be regenerated.
- Fields that arrive **only via a TR-069/ACS push from the provider**: the
  full SIP profile (phone number, `display_name`, SIP `password`/hash, actual
  proxies and realm) **is not derivable by any local formula** — it is written
  by the provider through ACS provisioning after the first registration. This
  is why a backup taken *before* provisioning contains only the `line0`
  placeholders, while one taken *after* contains the real profile. The
  distinction is useful: it explains why some secrets in the backup can be
  predicted from the serial and others (the VoIP ones) cannot — they are
  opaque and depend on the ACS.

## 5. Open questions / to verify

- `rawstorage` (256KB): unknown purpose, name too generic to guess from —
  worth investigating if a way to read it as root is found.
- Not verified whether BOOTP/TFTP recovery always writes to a fixed bank
  (e.g. always the currently "booted" one) or can be targeted at the other
  bank — in the 2026-08-23 tests it always wrote to and booted from Bank 1,
  but the router was already on Bank 1 before the test, so this doesn't
  distinguish between the two hypotheses.
  **Third-hand, independently-unconfirmed report** (from a different
  parallel session, relayed only as project memory, not personally
  verified): a BOOTP/TFTP flash attempt of a 1.0.3 image was reportedly
  accepted/written by the CFE, but on reboot the router came back up on
  **the other** bank (unchanged). If confirmed, this would mean "bank
  written by BOOTP" and "bank activated on boot" are governed by
  independent CFE mechanisms — consistent with this bullet's hypothesis,
  but needs a dedicated test (e.g. starting from a known `booted` ≠
  `active` state, as observed on the 2.2.1 unit in §2.1: there
  `booted=bank_2` but `active=bank_1` under normal conditions) before
  relying on it for a downgrade plan.
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

  **Data point toward resolving this (2026-08-27)**: on **a different
  unit**, live and running, with `BUILDVERSION`/
  `friendly_sw_version_activebank` confirmed via UCI = `AGTEF_2.2.1`,
  `uname -a` reports `Linux version 4.1.38 (repowrt-builder@...) ... Fri
  Apr 24 18:36:14 UTC 2020` — i.e. **confirms kernel 4.1.38 for 2.2.1**,
  matching `RBI-FORMAT-EN.md` §3.4's attribution and NOT what the
  2026-08-23 boot log showed. This strengthens the hypothesis that the
  `AGTEF_2.2.1_CLOSED.rbi` file used in that test wasn't genuinely a real
  2.2.1 (rather than the kernel→version map needing revision) — not
  conclusive proof (different physical unit, not the same `.rbi` file
  verified byte-for-byte), but a concrete data point in that direction.
