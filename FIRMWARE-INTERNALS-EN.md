# AGTEF firmware internals: kernel/squashfs layout, kernel-blob header, `network` generation, new services

Byte-level analysis of the contents of the 80 MiB flash image (the plaintext `0xB0` payload described in [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) §2.3), which [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) describes as the contents of **one whole bank**. This file complements the others: where `MEMORY-ARCHITECTURE` describes the NAND partitions and `RBI-FORMAT` the `.rbi` container, here we look **inside** the decrypted image — where the kernel ends and the squashfs begins, how the proprietary kernel-blob header is laid out, where `etc/config/network` comes from on recent builds, and what the services that appeared in 2.4.5 actually do.

Sections 1, 3 and 4 come from a direct comparison of two decrypted raw images: **the 2.2.1 stock build** (`AGTEF_2.2.1_CLOSED.rbi`, hereafter "221") and **the 2.4.5 CLOSED build** (`AGTEF_2.4.5_CLOSED.rbi`, hereafter "245"). Section 2 (kernel-blob header/decompression) instead covers all five official builds available, `1.0.3` → `2.4.5`. The offsets quoted are relative to the start of the 83,886,080-byte raw payload (80 MiB, `0x5000000`), not to the `.rbi` file.

## 1. Kernel/squashfs layout and growth of the reserved partition

The 80 MiB image starts with a proprietary kernel blob (§2) and, further in, contains the squashfs root filesystem. The split point is **not fixed across versions**:

| Build | squashfs start (`hsqs`) | Real kernel-payload end (non-padding) | Kernel payload size |
|---|---|---|---|
| 221 stock | `0x210000` (2,162,688) | `0x1ff96a` (2,095,466) | 2,095,440 bytes (header excluded) |
| 245 CLOSED | `0x600000` (6,291,456) | `0x221d57` (2,235,735) | 2,235,709 bytes (header excluded) |

The little-endian squashfs magic is `hsqs` (i.e. `0x73717368`, "sqsh" byte-swapped) and marks the start of the root filesystem inside the bank. Between the two builds the space **reserved** for the kernel goes from ~2.06 MiB (`0x210000`) to 6 MiB (`0x600000`), nearly tripling; but the **real** kernel payload grows only from 2,095,466 to 2,235,735 bytes, i.e. **about +6.7%**. So this is not a kernel that got much bigger, but a **flash-layout change**: the kernel window before the squashfs was widened (and aligned to a 6 MiB boundary), leaving a large padding margin up to the `hsqs`.

This resolves the note left open in [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §5, which observed that "the squashfs offset inside the 80MB image varies by version," citing `RBI-FORMAT-EN.md §3.2` as the source. That reference was imprecise: §3.2 of `RBI-FORMAT-EN.md` covers the evolution of the dropbear/SSH configuration, not the squashfs offsets. The real values (never published until now) are the ones in the table above.

### 1.1 Correction — the two builds do NOT share the same OpenWrt base

A mistaken claim that 221 and 245 share the same base OpenWrt string must be corrected (an initial hypothesis from this same analysis pass, later corrected by direct verification). Verified directly by reading `etc/openwrt_release` from each squashfs:

| Field | 221 stock | 245 CLOSED |
|---|---|---|
| `DISTRIB_RELEASE` | `'Chaos Calmer'` | `'SNAPSHOT'` |
| `DISTRIB_REVISION` | `'unknown'` | `'r14144-e2ae576c18'` |
| `DISTRIB_TARGET` | `'brcm63xx-tch/VANTW'` | `'brcm6xxx-tch/VBNTJ_502L07p1'` |
| `DISTRIB_DESCRIPTION` | `'OpenWrt Chaos Calmer 15.05.1'` | (not `Chaos Calmer`) |
| `DISTRIB_ARCH` | — | `'arm_cortex-a9'` |

These are two distinct OpenWrt bases: 221 is still on Chaos Calmer 15.05.1, 245 on a recompiled SNAPSHOT with a completely different target and revision. This **confirms at the offset/partition level** what is already documented in [`VERSION-CHANGELOG-DIFFS-IT.md`](VERSION-CHANGELOG-DIFFS-IT.md) (Italian only) about the OpenWrt-base rebuild that happened between 2.2.1 and 2.3.2 — it does not contradict it: the growth of the kernel window and the change of `openwrt_release` are two faces of the same platform rebase.

## 2. Kernel-blob header (decoded) and decompression — solved

> **Update.** An earlier version of this document did not spot a **12-byte mini-header** sitting between the 26-byte outer header and the compressed stream, and therefore concluded that kernel-body decompression was a dead end. That claim was wrong and is **superseded**: a later analysis, extended to every available official version (`1.0.3`, `2.2.0`, `2.2.1`, `2.4.1`, `2.4.5`), found the real layout and recovered the `Linux version` banner of each. The format detail is in §2.3.

Both builds begin the kernel blob with a fixed proprietary header of **0x1a (26) bytes**, followed by the mini-header and the compressed stream (§2.3). Field-by-field decode of the outer header (offsets relative to the start of the blob):

| Offset | Bytes | 221 | 245 | Meaning |
|---|---|---|---|---|
| `0x00`–`0x03` | 4 | `ff ff ff ff` | `ff ff ff ff` | Fixed sentinel, identical in both |
| `0x04`–`0x0b` | 8 | `00 …00` | `00 …00` | Eight zero bytes, fixed |
| `0x0c`–`0x0f` | 4 | `01 bb 00 00` | `02 34 00 00` | Version-dependent BE 2-byte value + `00 00` padding — **purpose not identified** |
| `0x10` | 1 | `b6` | `b6` | Constant in both |
| `0x11`–`0x15` | 5 | `4c 49 4e 55 0a` | `4c 49 4e 55 0a` | ASCII `LINU` + `0x0a` (line-feed) — **not** `LINUX` |
| `0x16`–`0x19` | 4 | `00 1f f9 50` | `00 22 1d 3d` | **Payload length, BE32 — solved (§2.1)** |

### 2.1 Length field (0x16–0x19) — solved

Reading the 4 bytes at `0x16` as a big-endian integer:

- 221 → `0x001ff950` = 2,095,440
- 245 → `0x00221d3d` = 2,235,709

Adding the header size (`0x1a` = 26 bytes):

- 221 → `0x1ff950 + 0x1a = 0x1ff96a`
- 245 → `0x221d3d + 0x1a = 0x221d57`

Both match **byte-for-byte** the real kernel-payload end offsets found independently (§1). The field is confirmed: **length of the compressed payload that follows the header**.

### 2.2 Fields still not identified

- `0x0c`–`0x0f`: the BE 2-byte value changes with the version. With the data now available across 5 official versions, in chronological order the values are **408, 441, 443, 560, 564** (1.0.3, 2.2.0, 2.2.1, 2.4.1, 2.4.5): strictly **non-decreasing**. But `2.4.1` and `2.4.5` have an **identical** kernel body (same sha256, §2.3) yet **different** values (560 vs 564): this proves the field is **not** a hash or a length derived from the kernel content. Most likely a vendor-internal build/revision counter. Checksum, XOR of payload bytes, and payload block-size divisor hypotheses were all tried and discarded. Exact purpose still **not identified**.
- `0x11`–`0x15`: the tag `LINU\n` is identical in both builds, but the fifth byte is a line-feed `0x0a`, not `X` (`0x58`). The reason for the truncation/line-feed termination is **not identified** semantically (likely a fixed tag emitted by the Broadcom build tool, not an interpreted field).

### 2.3 Body decompression — solved (LZMA_ALONE + mini-header)

The missing piece that had sunk the earlier attempts is a **12-byte mini sub-header** sitting between the 26-byte outer header and the actual compressed stream. The `FORMAT_RAW` bruteforce failed **immediately** precisely because it assumed the stream started right after byte `0x1a`: there is still structure there, and the stream is a standard **LZMA_ALONE** container (not raw LZMA). Layer by layer, identical across all 5 official versions tested:

1. **26-byte outer header** (`0x00`–`0x19`): the one decoded in §2/§2.1, unchanged.
2. **12-byte mini sub-header** (file offset `0x1a`, body offset 0): three little-endian 32-bit words — `<load_addr> <load_addr repeated> <inner_length>`. `inner_length` = kernel body size **minus 12**, exact across all 5 versions. `load_addr` = `0xc0008000` for `1.0.3`/`2.2.0`/`2.2.1`, and `0xc0018000` for `2.4.1`/`2.4.5` (a different ARM load address for the newer two).
3. **LZMA_ALONE stream** (file offset `0x26`, body offset 12): classic `.lzma` "LZMA_ALONE" header — 1 properties byte, 4-byte little-endian dictionary size, 8-byte little-endian uncompressed size — followed by a plain LZMA1 stream. Decodable directly with the Python standard library:

   ```python
   import lzma
   kernel = lzma.decompress(body[12:], format=lzma.FORMAT_ALONE)
   ```

   Properties byte = `0x6d` (lc=1, lp=2, pb=2), dictionary = 4 MiB — identical on every version tested. This is exactly what defeated the "raw LZMA1 bruteforce": the standard LZMA_ALONE container, with its own embedded properties/size header, was never tried, because the earlier pass assumed the stream started right after the 26-byte header — the 12-byte mini-header in between was the missing piece.

From here behaviour diverges across versions:

- **`1.0.3`, `2.2.0`, `2.2.1`**: this single LZMA_ALONE decompression yields the complete flat kernel image **directly**, with a plaintext `Linux version ...` banner readable inside it.
- **`2.4.1` and `2.4.5`**: the first decompression instead yields a self-extracting **ARM Linux `zImage` stub** (confirmed by the canonical `head.S` signature: 8× NOP instructions, then a branch, then the magic word `0x016f2818`, at relative offset `0x24` in the decompressed output — the standard, well-known ARM zImage decompressor-stub signature). That stub contains a **second**, nested LZMA_ALONE stream, at relative offset `0x41c4` (properties byte `0x6d`, dictionary 1 MiB, uncompressed-size field set to the "unknown length" sentinel `0xFFFFFFFFFFFFFFFF`, i.e. "decompress until the stream itself ends"). Decompressing that nested stream recovers the true flat kernel and its banner. So `2.4.1`/`2.4.5` are **double-LZMA**: outer CFE-level container → self-extracting zImage → real kernel; the older four versions are single-wrapped.

**Recovered `Linux version` banners** (exact strings, verified byte-for-byte against the decompressed kernel files):

- **`1.0.3`** (kernel `3.4.11-rt19`):
  `Linux version 3.4.11-rt19 (repowrt-builder@9c0b3ba154ab) (gcc version 4.6.4 (OpenWrt/Linaro GCC 4.6-2013.05 r49389) ) #1 SMP PREEMPT Thu Mar 9 02:50:43 UTC 2017`
- **`2.2.0`** (kernel `4.1.38`):
  `Linux version 4.1.38 (repowrt-builder@ff55a63a23d5) (gcc version 5.3.0 (OpenWrt GCC 5.3.0 unknown) ) #1 SMP PREEMPT Wed Oct 16 15:21:10 UTC 2019`
- **`2.2.1`** (kernel `4.1.38`):
  `Linux version 4.1.38 (repowrt-builder@2d2f3d55d158) (gcc version 5.3.0 (OpenWrt GCC 5.3.0 unknown) ) #1 SMP PREEMPT Fri Apr 24 18:36:14 UTC 2020`
- **`2.4.1`** and **`2.4.5`** (kernel `4.1.52`, **byte-for-byte identical kernel body between the two, sha256-confirmed** — 2.4.5 shipped no kernel change over 2.4.1, only rootfs/package changes, consistent with what is already documented elsewhere in this repo about 2.4.1→2.4.5 being a small, targeted update):
  `Linux version 4.1.52 (repowrt-builder@defb8768b1b8) (gcc version 5.5.0 (OpenWrt GCC 5.5.0 r14144-e2ae576c18) ) #0 SMP PREEMPT Fri Oct 28 16:57:49 2022`

**Cross-validation.** For each of the 5 versions, the recovered banner's kernel-version number matches `/lib/modules/<version>/` in that version's own extracted rootfs exactly — independent confirmation this is a real decompression, not an artifact.

#### Comparative table (official lineage only)

| Version | Squashfs @ | Kernel-payload end | Kernel size | Header `0x0c`–`0x0f` | `load_addr` | Kernel | Banner (build hash) |
|---|---|---|---|---|---|---|---|
| 1.0.3 | `0x200000` | `0x1b3d9c` | 1,785,218 bytes | `0x0198` (408) | `0xc0008000` | 3.4.11-rt19 | `9c0b3ba154ab` |
| 2.2.0 | `0x210000` | `0x1ff156` | 2,093,372 bytes | `0x01b9` (441) | `0xc0008000` | 4.1.38 | `ff55a63a23d5` |
| 2.2.1 | `0x210000` | `0x1ff96a` | 2,095,440 bytes | `0x01bb` (443) | `0xc0008000` | 4.1.38 | `2d2f3d55d158` |
| 2.4.1 | `0x600000` | `0x221d57` | 2,235,709 bytes | `0x0230` (560) | `0xc0018000` | 4.1.52 | `defb8768b1b8` |
| 2.4.5 | `0x600000` | `0x221d57` | 2,235,709 bytes | `0x0234` (564) | `0xc0018000` | 4.1.52 | `defb8768b1b8` (identical to 2.4.1) |

> The **unofficial** community build `1.1.3` shares this exact layout and has a kernel identical to `1.0.3`, but it does **not** belong to the official lineage and is not included here: see [`AGTEF-1.1.3-UNOFFICIAL-EN.md`](AGTEF-1.1.3-UNOFFICIAL-EN.md).

Indirect confirmation from the boot log in [`UART-BOOT-LOG-EN.md`](UART-BOOT-LOG-EN.md) (lines 151–154): CFE prints `Decompression OK!` shortly before the actual jump (`Starting program at 0x00008000`) — consistent with **CFE itself** decompressing the outer LZMA_ALONE stream and jumping to the image (or, for `2.4.x`, to the zImage stub that then self-extracts).

**Conclusion.** The kernel-blob format is now fully understood and reproducible with the Python standard library alone: 26-byte header → 12-byte mini-header → LZMA_ALONE (→ for `2.4.x`, zImage → nested LZMA_ALONE). Of the header, only the exact purpose of fields `0x0c`–`0x0f` (§2.2) and the reason for the `LINU\n` tag remain unknown.

## 3. Where `etc/config/network` comes from in 2.4.5

In 245 the file `etc/config/network` is **not present** in the squashfs, while in 221 it is. This is neither a regression nor a lost config: the file is **synthesized at first real boot**. Reconstruction of the mechanism, with the evidence.

- **221**: `etc/config/network` is baked into the squashfs, but contains only the minimum (`config interface 'loopback'` + `option ula_prefix 'auto'` in `globals`) — **not** a complete board-specific network config.
- `/bin/config_generate` (10,111 bytes, present identically in both builds) contains the function `generate_static_network()`, whose embedded UCI commands (`set network.loopback=...`, `set network.globals=...`) reproduce **verbatim** the contents of the 221 file. The script's first line is:

  ```sh
  [ -s /etc/config/network -a -s /etc/config/system ] && exit 0
  ```

  i.e. it is a **no-op if the files already exist** (this is how, in 221 where the file is present, `config_generate` leaves it alone).
- `/etc/board.d/02_network` (present in 245) is a Technicolor board-detection script: it calls `ucidef_set_interface_lan` / `ucidef_add_switch` based on the detected SoC. The `brcm,bcm963138` branch corresponds to the DGA4130. It is invoked via `board_config_update` / `board_config_flush`, defined in `/lib/functions/uci-defaults.sh`.
- `/etc/init.d/boot`, function `boot()`, runs in order:

  1. `config_generate`
  2. `uci_apply_defaults` — iterates over `/etc/uci-defaults/*`, sources each script and, on success, **self-deletes** it with `rm -f`
  3. `sync`

- In 245 the following are present in the squashfs listing (precisely because they self-delete after the first run, so they no longer appear on an already-booted device): the Technicolor scripts `etc/uci-defaults/tch_0015-network-globals`, `tch_0020-network-lan`, `tch_0030-network-wan`. These complete `network` with the real LAN/WAN/wireless interfaces (e.g. `wlnet_b_24`, `wlnet_b_5`) at first boot.

**Conclusion.** In 245 the `network` file is **deliberately absent** from the squashfs because it is synthesized at first boot by the chain `config_generate` → `board.d/02_network` → `tch_00NN-network-*` scripts (which self-delete, which is why they are not seen again after the first boot). In 221 the baked-in file was only the **minimal skeleton** produced by `config_generate`, without the board.d/uci-defaults customization layer seen above. The generation mechanism exists **identically** in both builds (same `config_generate`, same `init.d/boot`) — only the **packaging choice** differs: include the minimal skeleton (221) versus omit it entirely and generate everything at first boot (245).

## 4. New services in 2.4.5 — what they actually do

Services that appeared in 245, analyzed at the init-script and binary/strings level (not by name alone):

| Service | Init / gating | Binary | Function |
|---|---|---|---|
| `multiap_agent` | rc.d **S99**; ebtables BROUTE rule on destination MAC `01:80:C2:00:00:13` (IEEE 1905.1 multicast) | `/usr/bin/multiap_agent` (149 KB) — strings `CMDU_TYPE_TOPOLOGY_*`, `lib1905_*` | Wi-Fi Alliance **Multi-AP (EasyMesh)** agent over IEEE 1905.1 — mesh topology discovery/registration node |
| `multiap_controller` | rc.d **S95**; same 1905.1 infrastructure | `/usr/bin/multiap_controller` (117 KB) | Multi-AP (EasyMesh) controller — orchestrator of the agents |
| `nanocdn` | rc.d **S99**; gated on `uci get system.mabr.enabled`; starts `nanocdn-core` and `nanocdn-rr` via procd; reads `/etc/broadpeak/nanocdn.conf`; dedicated `nanocdn` user | `nanocdn-core`/`nanocdn-rr` binaries **not found** in the extracted listing (only the Lua helper `/usr/bin/nanocdnMinMax.lua`, `/root/nanocdn.ipk`, staging `/root/temp_nanoCDN/`) | **Broadpeak nanoCDN** — multicast-ABR CPE agent (multicast→unicast conversion) for IPTV/OTT. `mABR` = Multicast ABR. Identified from path/vendor, **not** at the binary-strings level |
| `wlaffinity` | **No rc.d symlink** — not started automatically at boot; pure POSIX script (27,318 bytes) | n/a — uses `/proc/irq/$irq/smp_affinity`, `taskset -p`, `nvram kget/kset` | **CPU-pinning** utility for WiFi IRQs and threads (D11 MAC, M2M) per radio — manual/on-demand use (script header: "configures interrupt & thread affinity regarding to WLAN") |
| `dnsfilter` | rc.d **S80/K10**; `iptables`/`ip6tables` mangle rules redirecting UDP/TCP port 53 to **NFQUEUE**; gated on config `parental` with `mode="dns"` | `/usr/sbin/dnsfilterd` (38,532 bytes) — strings `nfq_bind_pf`, `nfq_create_queue`, `libnetfilter_queue.so.1` | **DNS parental-control** filter based on NFQUEUE (blocking by category/domain) |
| `datausaged` / `datausage_notifier` | rc.d **S55** (ubus service `datausage`) / **S50** (ubus service `datausage_notifier`); gated on dedicated UCI configs; notifier with Lua handlers `/usr/lib/lua/datausage_notifier/{email,sms,intercept}.lua` | `/usr/bin/datausaged` (14,575 bytes), `/usr/bin/datausage_notifier` (4,911 bytes) | Pair of **data-usage monitoring** daemons + threshold notification (email/SMS), tied to `/etc/hotplug.d/ntp/35-datausaged` and the web UI (`/www/cards/011_datausage.lp`) |

The shared 1905.1 infrastructure of `multiap_agent`/`multiap_controller` (same multicast MAC `01:80:C2:00:00:13`, same `lib1905_*`) and the simultaneous appearance of `nanocdn` are consistent with the platform rebase toward a newer SNAPSHOT (§1.1): these are EasyMesh + IPTV features that the Chaos Calmer base of 221 did not have.

## 5. Open questions / limits

- **Header fields `0x0c`–`0x0f` and the `LINU\n` tag** (§2.2): decoded as bytes but not identified semantically. Across 5 official versions the `0x0c`–`0x0f` values are non-decreasing (408, 441, 443, 560, 564) but provably **not** derived from the kernel content (2.4.1 and 2.4.5 have an identical kernel yet different values) — likely a vendor-internal build counter, not confirmed.
- **`nanocdn-core` / `nanocdn-rr` binaries not found** in the extracted filesystem (§4): identification as Broadpeak nanoCDN is based on path, vendor dir (`/etc/broadpeak/`), dedicated user, and Lua helper — **not** on strings extracted from the binaries themselves, which are absent from the listing.
