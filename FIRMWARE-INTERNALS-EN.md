# AGTEF firmware internals: kernel/squashfs layout, kernel-blob header, `network` generation, new services

Byte-level analysis of the contents of the 80 MiB flash image (the plaintext `0xB0` payload described in [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) §2.3), which [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) describes as the contents of **one whole bank**. This file complements the others: where `MEMORY-ARCHITECTURE` describes the NAND partitions and `RBI-FORMAT` the `.rbi` container, here we look **inside** the decrypted image — where the kernel ends and the squashfs begins, how the proprietary kernel-blob header is laid out, where `etc/config/network` comes from on recent builds, and what the services that appeared in 2.4.5 actually do.

All values come from a direct comparison of two decrypted raw images: **the 2.2.1 stock build** (`AGTEF_2.2.1_CLOSED.rbi`, hereafter "221") and **the 2.4.5 CLOSED build** (`AGTEF_2.4.5_CLOSED.rbi`, hereafter "245"). The offsets quoted are relative to the start of the 83,886,080-byte raw payload (80 MiB, `0x5000000`), not to the `.rbi` file.

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

## 2. Kernel-blob header (decoded) and decompression attempt

Both builds begin the kernel blob with a fixed proprietary header of **0x1a (26) bytes**, followed by the compressed body. Field-by-field decode (offsets relative to the start of the blob):

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

- `0x0c`–`0x0f`: the BE 2-byte value (443 for 221, 564 for 245) changes with the version. Checksum, XOR of payload bytes, and payload block-size divisor hypotheses were all tried and discarded: none holds. Purpose **not identified**.
- `0x11`–`0x15`: the tag `LINU\n` is identical in both builds, but the fifth byte is a line-feed `0x0a`, not `X` (`0x58`). The reason for the truncation/line-feed termination is **not identified** semantically (likely a fixed tag emitted by the Broadcom build tool, not an interpreted field).

### 2.3 Body decompression — documented dead end

The body (bytes from `0x1a` to the end of the real payload, both builds) was attacked with every compression format plausible for a Broadcom bcm63xx kernel. **None works.** Documented here with the evidence, to avoid repeating the work:

- **gzip** (`1f 8b`): no match in the first `0x2000`/`0x4000` bytes.
- **zlib/deflate** (header `78 xx` with a valid RFC1950 checksum): a single accidental match (245, `body+0x24`, `78 01`) that yields no valid output on decompression — false positive.
- **legacy LZMA "alone"** (props byte `0x5d`): no match in the first `0x400` bytes.
- **raw LZMA** (`FORMAT_RAW`), full bruteforce of `lc ∈ 0–3`, `lp ∈ 0–2`, `pb ∈ 0–2`, `dict_size ∈ {1,2,4,8,16 MiB}`, start offset `∈ {0,1,2,4,8,13}`: every combination fails **immediately** with corrupt data, in both builds.
- No **uImage** (`27 05 19 56`), **ELF** (`7f 45 4c 46`), or **ARM zImage stub** (`18 28 6f 01`) magic present in the body.
- Body **entropy** ~7.95–8.0 bits/byte from start to end of the real payload — consistent with compressed or encrypted data, and in particular the **absence of a low-entropy decompressor stub** before the stream (which you would expect in a self-extracting `zImage`).

Indirect confirmation from the boot log in [`UART-BOOT-LOG-EN.md`](UART-BOOT-LOG-EN.md) (lines 151–154): CFE prints `Decompression OK!` shortly before the actual jump (`Starting program at 0x00008000`). This confirms that (a) the kernel blob is genuinely compressed, and (b) it is **CFE itself** that decompresses it internally before the jump.

**Conclusion.** The header is decoded almost completely: only the purpose of fields `0x0c`–`0x0f` and the exact reason for the `LINU\n` tag remain unknown. The compressed body resists every standard method tried. The most likely hypothesis is that the Broadcom CFE uses a **proprietary/non-standard LZMA variant**, with the parameters (props, dictionary, any pre-processing) hardcoded in the bootloader rather than in the blob header — which would explain both the immediate failure of the `FORMAT_RAW` bruteforce and the absence of an in-band stub. Useful next step, **not attempted here**: disassemble the CFE decompression routine, or obtain a Broadcom bcm963xx GPL source drop with its modified `lzma.c` and compare the parameters.

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

- **Kernel-body compression algorithm not recovered** (§2.3): all standard formats fail; recovering it would require disassembling the CFE decompression routine or a Broadcom bcm963xx GPL source drop with its `lzma.c`.
- **Header fields `0x0c`–`0x0f` and the `LINU\n` tag** (§2.2): decoded as bytes but not identified semantically.
- **`nanocdn-core` / `nanocdn-rr` binaries not found** in the extracted filesystem (§4): identification as Broadpeak nanoCDN is based on path, vendor dir (`/etc/broadpeak/`), dedicated user, and Lua helper — **not** on strings extracted from the binaries themselves, which are absent from the listing.
