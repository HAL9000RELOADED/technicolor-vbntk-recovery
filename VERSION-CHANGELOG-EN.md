# AGTEF (VBNT-K / DGA0130TCH) sequential changelog

What changes, version by version, across the 14 unique `.rbi` images found in the folder — in version-number order (not necessarily real release order, see the `1.1.3` outlier below). Methodology and format details are in [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md); this doc focuses on the file-level delta between each consecutive pair.

**On "busybox noise":** in almost every transition, dozens of files under `bin/` (`ash`, `busybox`, `cat`, `grep`, `ls`, ...) show up as "modified". Nearly all of them are symlinks to the same BusyBox binary: whenever BusyBox gets rebuilt (even with no functional change), every link shows different content. These counts are included in the totals below but **not listed individually** — attention goes to files with an explicit, meaningful name.

**Methodological note:** the transitions involving `2.4.1` and `2.4.5` were recomputed from a clean re-extraction, straight from the original `.rbi` files — a first local extraction of these two versions was contaminated by an earlier rooting attempt (`patch_241.sh`/`patch_245.sh` edit `/etc/passwd`, `/etc/shadow`, `/etc/config/dropbear` **in-place** in the folder used as the source). See [`RBI-FORMAT-EN.md` §3.7](RBI-FORMAT-EN.md#37-245-closed-vs-patched) for details.

---

## 1.0.3 → 1.0.4

**118 removed, 340 added, 1826 modified.** A minor update but with a fair amount of internal churn (especially in `usr/`, 244 files added). No kernel change (`3.4.11`) and no SSH/console config change (both disabled in both versions — see RBI-FORMAT §3.2/3.3). `etc/config/dropbear` moves from `1.0.3`'s single-instance form to the `lan`+`wan` scheme that stays standard through `2.0.1_003`.

## 1.0.4 → 1.1.2

**112 removed, 371 added, 1582 modified.** `mosquitto` (MQTT broker) appears — the first version in the line to ship it. Dropbear structure unchanged (`lan`+`wan`, both disabled).

## 1.1.2 → 1.1.3 — ⚠️ side branch, not sequential

**691 removed, 206 added, 1989 modified.** Numbers that stand out against the rest of the line: nearly 700 files disappear (including the entire `etc/boards/`, and `mosquitto`), and the dropbear structure regresses to `1.0.3`'s single-instance form — with root SSH **enabled** and the serial console active with no login (see RBI-FORMAT §3.2/3.3). Decisive proof this isn't a sequential release: the next transition (`1.1.3 → 1.2.0_001`) shows **the exact numbers reversed** (206 removed, 691 added) — meaning `1.2.0_001` picks up right where `1.1.2` left off, as if `1.1.3` never existed in that line. Everything points to `AGTEF_1.1.3_CLOSED.rbi` being a lab/debug image, not a public TIM release.

## 1.1.3 → 1.2.0_001

**206 removed, 691 added, 1991 modified** — the exact mirror of the previous transition (see above). `1.2.0_001` is effectively the natural continuation of `1.1.2`.

## 1.2.0_001 → 2.0.0

**0 removed, 8 added, 781 modified.** A contained update, mostly recompilation (781 "modified" is largely busybox noise plus a few dozen real binaries/libs). Nothing removed.

## 2.0.0 → 2.0.0_002

**2 removed, 0 added, 16 modified.** The smallest, cleanest transition in the first part of the line — no busybox noise. Files touched: `etc/banner`, `etc/config/version`, `etc/config/web`, `etc/config/wireless`, `etc/sysctl-tch.conf`, `etc/uci-defaults/tch_5000_versioncusto`, `usr/share/transformer/commitapply/uci_web_users.ca`, BBF mappings (`DeviceInfo.map`, `WiFi.Radio.map`), `rpc/env.var.map`, web templates (`090_cwmpconf.lp`, `gateway.lp`, `main-min.js`, `cwmpconf-modal.lp`, `ethernet-modal.lp`), and the `it-it/webui-parental.mo` translation. A targeted config/UI revision, not a system-wide update.

## 2.0.0_002 → 2.0.1_003

**0 removed, 3 added, 759 modified.** Similar to `1.2.0_001 → 2.0.0`: mostly recompilation, nothing removed.

## 2.0.1_003 → 2.2.0 — kernel generation jump

**214 removed, 614 added, 2222 modified.** **Kernel `3.4.11` → `4.1.38`** — the first real generation transition in the line. `lxc` (container support) appears. Supported boards go from 2 (`VBNT-K`, `VBNT-S`) to 5 (+ `VANT-W`, `VBNT-F`, `VBNT-H`).

## 2.2.0 → 2.2.1

**6 removed, 45 added, 924 modified.** A minor update on the same kernel (`4.1.38`), same 5 boards. `AllowLocalForwarding` appears as an option in the dropbear sections (all set to `'0'`).

## 2.2.1 → 2.3.2 — the largest transition in the line

**528 removed, 1633 added, 3005 modified.** **Kernel `4.1.38` → `4.1.52`** and **consolidation from 5 to 18 boards** (`VANT-W`, `VBNT-6/7/9/H/J/K/O/S/V/Y`, `VCNT-A/C/E/H/I/X/Z`) into a single image — hence most of the 1223 files added under `usr/` alone (per-board modules/opkg packages) and the 159 under `www/`. The serial console entry switches from pointing at `/bin/login` to `/bin/restricted_shell` (still disabled by default). Dropbear's `RootPasswordAuth` switches from string (`'on'`) to numeric (`'0'`), a sign of tightened security defaults.

## 2.3.2 → 2.4.1

**15 removed, 104 added, 1270 modified.** Same kernel (`4.1.52`), same 18 boards — an incremental update on the same architectural base, not another generation jump.

## 2.4.1 → 2.4.5

**0 removed, 4 added, 23 modified.** A small, clean delta with no busybox noise (only `bin/ps` among binaries). New files: two certificates (`etc/ssl/certs/4ec17c6c.0`, `etc/ssl/certs/TimGroupPrivateRootCA.b64.cer` — TIM adding its own private CA), `lib/mount_root/00_overlay_threshold_check`, and `usr/sbin/mon_reinit.sh`. Modified: `etc/banner`, `etc/config/cwmpd`, `etc/config/version`, `etc/init.d/wireless` + `etc/rc.d/S13wireless`, four `etc/uci-defaults/tch_*` entries (WAN network, removals, versioning, "LTE 2 Box" profile), `usr/bin/bulkdata`, WiFi/MultiAP/host mappings (`transformer/shared/wifi.lua`, `web/content_helper.lua`, several BBF/device2/rpc `.map` files), and `www/docroot/modals/system-info-modal.lp`. A targeted update around WiFi/MultiAP management, CWMP, and certificates — it does not touch security config (dropbear/passwd/shadow stay exactly as in `2.4.1`, both with SSH disabled).

## 2.4.5 → 2.4.5_PATCHED — the local rooting patch

**0 removed, 0 added, 3 modified.** The only transition in this list that isn't a TIM release, but the patch produced in this repository (`patch_245.sh`). It changes only:

- `etc/passwd`: root's shell from `/bin/restricted_shell` to `/bin/ash` (a full shell)
- `etc/shadow`: from a locked root account (no password) to a known password (sha512crypt hash)
- `etc/config/dropbear` (`lan` section): root SSH enabled (`enable`, `RootLogin`, `RootPasswordAuth`, `AllowLocalForwarding` all flipped from `'0'` to `'1'`) — `public_lan`/`wan` remain disabled

Full details and signature-mechanism verification in [`RBI-FORMAT-EN.md` §3.7](RBI-FORMAT-EN.md#37-245-closed-vs-patched).
