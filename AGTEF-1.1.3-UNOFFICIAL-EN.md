# AGTEF 1.1.3 — UNOFFICIAL build (root pre-enabled) derived from 1.0.3

> ⚠️ **Disclaimer — read this first.** This firmware image **is not a genuine Technicolor stock release.** It is a **community-modified build**, derived from stock `1.0.3`, with root/shell access **deliberately pre-enabled**. It is documented here only for completeness and provenance tracking: it is **not** part of the official AGTEF version lineage covered in [`VERSION-CHANGELOG-EN.md`](VERSION-CHANGELOG-EN.md) and [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md), and must not be confused with it or slotted into an official changelog.

Byte-level analysis of the `1.1.3` image compared with the stock `1.0.3` it derives from. As in the rest of the repo, images are referred to only by version number (`1.0.3`, `1.1.3`), never by local file path.

## 1. Kernel — byte-for-byte identical to 1.0.3

The fully decompressed kernel body of `1.1.3` has the **same sha256** as stock `1.0.3`. Same banner:

`Linux version 3.4.11-rt19 (repowrt-builder@9c0b3ba154ab) (gcc version 4.6.4 (OpenWrt/Linaro GCC 4.6-2013.05 r49389) ) #1 SMP PREEMPT Thu Mar 9 02:50:43 UTC 2017`

Same outer-header/mini-header layout documented in [`FIRMWARE-INTERNALS-EN.md`](FIRMWARE-INTERNALS-EN.md) §2.3 (26-byte header → 12-byte mini-header with `load_addr = 0xc0008000` → LZMA_ALONE stream, props `0x6d`, 4 MiB dictionary, single-wrapped like every pre-2.4 version).

This proves `1.1.3` involved **zero kernel engineering**: the "1.1.3" version label **does not correspond to any real kernel rebuild**, only a rootfs patch on top of `1.0.3`.

## 2. Rootfs — nearly identical to 1.0.3

Both rootfs images extract to **exactly 3708 files**. A full recursive diff (`diff -rq`, native ext4 on WSL, both squashfs images extracted from their respective decrypted raw images) finds only **two functionally meaningful changes**, plus a handful of build-artifact noise (a few special-file-vs-directory placeholder mismatches for `etc/cups/certs`, `etc/mtab`, `var` — packaging/build-tool noise, not meaningful).

### 2.1 `etc/config/dropbear` — SSH root access enabled

| Entry | Stock 1.0.3 | 1.1.3 |
|---|---|---|
| `option enable` | `'0'` | `'1'` |
| `option RootPasswordAuth` | `'off'` | `'on'` |
| `option RootLogin` | *(absent)* | `'1'` *(line added)* |

### 2.2 `etc/inittab` — serial console with direct shell

The serial console changes from a commented-out `/bin/login` prompt (disabled) to an active, uncommented direct shell:

- Stock 1.0.3: `#::askconsole:/bin/login` *(disabled)*
- 1.1.3: `::askconsole:/bin/ash` *(enabled)*

Note it points straight to `/bin/ash`, **bypassing any login/authentication prompt entirely** on the serial console — a more direct access vector than the SSH change.

### 2.3 `etc/passwd` and `etc/shadow` — identical to stock

`etc/passwd` and `etc/shadow` are **byte-for-byte identical** to stock `1.0.3`: the patch does **not** set a custom root password.

## 3. Context — stock 1.0.3 already ships root passwordless

This is not a `1.1.3`-specific issue, but it is what makes the patch so minimal. Stock `1.0.3` itself ships root in its own `/etc/shadow` with an **empty password-hash field**:

`root::0:0:99999:7:::`  *(the second colon-separated field, the password hash, is empty)*

and its `/etc/passwd` root entry already uses `/bin/ash` as the shell (not a restricted shell). This is why the `1.1.3` patch is so minimal: it does not need to crack or set a password — enabling dropbear (whose `RootPasswordAuth=on`, combined with an empty shadow hash, may accept a blank/any password depending on dropbear's own handling) and/or pointing the console straight to `/bin/ash` are each already sufficient to reach a root shell, because there is no real password to defeat in the first place.

Stated factually and neutrally: this is a documented characteristic of a years-old, no-longer-current firmware baseline, **not** an actionable exploit against current hardware.

## 4. Conclusion / framing

`1.1.3` is best understood as a community "root-enable" reference build for the DGA4130/VBNT-K, conceptually identical in purpose to the later `2.2.1_PATCHED`/`2.4.5_PATCHED` images already documented in this repo ([`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) §3.7) — just applied to a much older base (`1.0.3`, kernel 3.4.11) and using a slightly different, more direct technique (console autologin **in addition to** SSH, rather than SSH alone). It also requires **even less** modification than the later patches, because `1.0.3`'s stock shadow already ships passwordless.

## 5. Open questions / limits

- **Exact provenance not traced**: `1.1.3` is confirmed non-stock by structure (kernel identical to 1.0.3 + root-enable rootfs patch), but its precise origin (author/community thread) is not established in this document.
- **Dropbear auth behaviour with an empty hash**: whether `RootPasswordAuth=on` + empty shadow hash accepts a blank or any password depends on dropbear's internal handling on that build and was **not** verified live here — the unambiguous access path is the `/bin/ash` console of §2.2 regardless.
