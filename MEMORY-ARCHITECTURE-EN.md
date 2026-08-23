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
  flash of a patched `221` with new `/etc/passwd` + `/etc/shadow` +
  `/etc/config/dropbear` (to enable root SSH) was not enough to unlock SSH
  login — leading hypothesis, not yet confirmed, is that earlier versions
  of these same files written to `rootfs_data` by a prior attempt on this
  router are still in effect. See `RBI-FORMAT-EN.md` §5.3 for the test
  details. **A genuinely clean test** would require clearing
  `rootfs_data` (factory reset via 7 seconds on the reset button while
  the router is already powered on — a different procedure from BOOTP/TFTP
  recovery, not yet verified on this hardware) or, as root, explicitly
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
