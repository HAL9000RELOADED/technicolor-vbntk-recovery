# AGTEF `.rbi` format: header, encryption and "signature" — what changes between versions

Analysis of the `.rbi` firmware container used by the Technicolor VBNT-K (`AGTEF_x.y.z_CLOSED.rbi`), of its internal encryption/"signature" mechanism, and a real comparison between versions `1.0.3` and `2.4.5` (original vs patched).

## 1. Static header

The first `0x30` bytes are a fixed-field header:

```
0x00  4   magic            "BLI2"
0x04  2   fim
0x06  2   fia
0x08  12  prodid
0x14  12  varid
0x20  4   version          (per-byte: major.minor.patch.build)
0x24  4   unknown
0x28  4   data_offset      (absolute offset of the first payload chunk)
0x2C  4   data_size        ("redundant" declared payload size)
```

Across all files analyzed (`1.0.3`, `2.4.5` CLOSED and PATCHED): `magic="BLI2"`, `data_offset=0x171`, board `VBNT-K` / product `Technicolor DGA0130TCH`.

A fixed `0x104`-byte blob immediately follows the static header, commented as "Signature? Hash?" in the reference tool — **verified that it is NOT**: it is byte-identical between `2.4.5` CLOSED and `2.4.5` PATCHED (despite their payloads and file sizes being completely different). It does not depend on content — it's static material (likely a certificate/key tied to a build generation, not a payload hash).

Dynamic TLV fields (`id`, `len`, `value`) follow up to `data_offset`: `timestamp`, `boardname`, `prodname`, `varname`, `tagpparserversion`, `flashaddress`.

## 2. Chunk chain (starting at `data_offset`)

At `data_offset` a sequence of nested chunks begins, each introduced by a magic byte preceded by the ASCII tag `MUTE`:

```
0xB7  encrypted container (AES-256-CBC)   — outer layer, always present
  └─ 0xB8  "signature" block               — hash of the next chunk
       └─ 0xB4  zlib-compressed chunk
            └─ 0xB0  plaintext payload      — final flash image (80 MB)
```

Confirmed identical across all 3 files analyzed: `['0xb7', '0xb8', '0xb4', '0xb0']`.

### 2.1 Layer 0xB7 — AES encryption

```
magic(1) + "MUTE"(4) + flag(1) + counter(4) + iv1(16) + enc_key2(48) + iv2(16) + ciphertext
```

- `enc_key2` is a random AES-256 key (`key2`), encrypted with AES-256-CBC using `iv1` and a **fixed, shared** key (hardcoded in the tool, identical across every version/file):

  ```
  OSCK = FFD56A4E3A21401BF1798B3CD8AD54D238BA80039623BBA08B6D50B8EC73F7B4
  ```

- The actual payload (`0xB8`+`0xB4`+`0xB0`) is encrypted with `key2` (CBC, `iv2`), PKCS5 padding.

**This layer is obfuscation, not authentication**: the `OSCK` key is static and shared across all versions — anyone who knows it (as this same tool does) can encrypt/decrypt any arbitrary payload into a valid `0xB7` container.

### 2.2 Layer 0xB8 — the "signature" block

```
magic(1) + "MUTE"(4) + flag(1) + counter(4) + hash(32)
```

**Empirically verified byte-for-byte that `hash = SHA-256(the following 0xB4 chunk)`.** This is not an RSA/ECDSA signature tied to a private key — it's a plain self-consistency digest, recomputed by whatever tool packs the file (see `encrypt_rbi.py`, `build()` function):

```python
sig_hash = hashlib.sha256(b4_chunk).digest()
b8_block = bytes([0xB8]) + MUTE + bytes([0x00]) + struct.pack(">I", len(b4_chunk)) + sig_hash
```

Verification across the 3 files (declared header hash vs. hash recomputed on the decrypted payload):

| File | match |
|---|---|
| `AGTEF_1.0.3_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_PATCHED.rbi` | ✅ |

**Conclusion:** this format has no cryptographic signature tied to a Technicolor private key that would prevent building a "valid"-looking `.rbi` with an arbitrary payload — the only internal consistency check (the `0xB8` hash) is correctly recomputed by anyone using the same packing toolchain, as demonstrated by the patched build (`2.4.5_PATCHED`) passing this check exactly like the original does. Whether the router's CFE bootloader actually enforces this field (or anything else, e.g. header fields) during boot/recovery is a separate question about the bootloader itself, not about the file format.

> **Update 2026-09-09 — do not conflate two distinct mechanisms.** The `0xB8` hash described here is a self-consistency digest *internal to the file*. There is, however, on the **device** (Linux/userspace side), a completely separate signature check, and that one **is** public-key RSA-2048/PSS — confirmed at the machine-code level by disassembling the unit's real binaries. It operates on the BLI header+payload, not on the `0xB8` chunk. See the new [§6](#6-device-side-signature-verification--confirmed-at-the-machine-code-level-2026-09-09).

### 2.3 Layer 0xB4/0xB0

`0xB4`: `magic(1) + "MUTE"(4) + flag(1) + counter(4) + zlib_data`. `0xB0`: `magic(1) + "MUTE"(4) + flag(1) + plaintext_payload` — the final flash image, 80 MB (`0x5000000`) across all files tested.

## 3. Real comparison across all available firmware versions

Analysis extended to all **13 unique images** found in the folder (deduplicated by MD5 — `*_copy.rbi` files are byte-for-byte duplicates, excluded): `1.0.3`, `1.0.4`, `1.1.2`, `1.2.0_001`, `2.0.0`, `2.0.0_002`, `2.0.1_003`, `2.2.0`, `2.2.1`, `2.3.2`, `2.4.1`, `2.4.5`, `2.4.5_PATCHED`. Rootfs extracted natively in WSL (ext4, case-sensitive) — extracting on a case-insensitive Windows/DrvFs filesystem silently drops files that differ only by case, so always re-check on a case-sensitive filesystem before drawing conclusions from a `diff -rq`.

### 3.1 Signature check — universal across all 13

The byte-for-byte check described in §2.2 (`0xB8` hash == `SHA-256` of the following `0xB4` chunk) was repeated across all 13 images, patch included: **positive match on every single one**, no exceptions. This definitively confirms **this** mechanism (the file-internal hash) was never a private-key signature in any observed version of the AGTEF line.

To be sharply distinguished from the **device-side** signature check, which is a genuine RSA-2048/PSS (public key read from `/proc/rip/0120`, alias "OSIK") applied to the BLI header+payload, not to the `0xB8` chunk: see [§6](#6-device-side-signature-verification--confirmed-at-the-machine-code-level-2026-09-09) for the machine-code-level analysis.

### 3.2 SSH (dropbear) — evolution over time

| Version | Config structure | `enable` (lan) | `RootPasswordAuth` | `RootLogin` |
|---|---|---|---|---|
| 1.0.3 | single instance | `0` | `off` | — |
| 1.0.4 → 2.0.1_003 | `lan` + `wan` | `0` / `0` | `on` (but disabled) | — |
| 2.2.0 / 2.2.1 | `lan` + `public_lan` + `wan` | `0` / `0` / `0` | `on` | `0` (public_lan/wan) |
| 2.3.2 / 2.4.1 / 2.4.5 | `lan` + `public_lan` + `wan` | `0` / `0` / `0` | `0` (numeric, tightened) | `0` |

Key points:

- **From `2.3.2` through `2.4.5`, stock ships SSH fully disabled** on all three interfaces, with root's shell set to `/bin/restricted_shell` (not a full shell) — consistent with the hardening trend that started at `2.3.2`. Methodological caveat: a first extraction of `2.4.1`/`2.4.5` from this local repository turned out to be contaminated by an earlier rooting attempt (`patch_241.sh`/`patch_245.sh`, run **in-place** on the very folder used as the "stock" reference) — the correct values above come from a clean re-extraction, straight from the original `.rbi` files, not from reused working folders. See §3.7 for what the patch actually changes.

### 3.3 Serial console (`etc/inittab`, `askconsole` line)

| Version | `askconsole` line |
|---|---|
| 1.0.3 | `#::askconsole:/bin/login` (disabled) |
| 1.0.4 → 2.0.1_003 | `#::askconsolelate:/bin/login` (disabled, entry renamed) |
| 2.3.2 → 2.4.5_PATCHED | `#::askconsole:/bin/restricted_shell` (disabled, but now points at a restricted shell instead of `/bin/login`) |

### 3.4 Kernel and supported boards

| Version | Kernel | Boards in `etc/boards/` |
|---|---|---|
| 1.0.3 → 2.0.1_003 | `3.4.11` (+ `3.4.11-rt19`) | 2 (`VBNT-K`, `VBNT-S`) — missing in 1.0.3 |
| 2.2.0 / 2.2.1 | `4.1.38` | 5 (+ `VANT-W`, `VBNT-F`, `VBNT-H`) |
| 2.3.2 → 2.4.5_PATCHED | `4.1.52` | **18** (`VANT-W`, `VBNT-6/7/9/H/J/K/O/S/V/Y`, `VCNT-A/C/E/H/I/X/Z`) |

Two clear jumps: the kernel generation change `3.4.11 → 4.1.38` at `2.2.0`, and the large multi-board consolidation (from 5 to 18 Technicolor variants covered by a single image) starting at `2.3.2`.

### 3.5 Features over time

| Version | mosquitto (MQTT) | lxc (containers) | wireguard | openvpn |
|---|---|---|---|---|
| 1.0.3 / 1.0.4 | ❌ | ❌ | ❌ | ❌ |
| 1.1.2 → 2.0.1_003 | ✅ | ❌ | ❌ | ❌ |
| 2.2.0 → 2.4.5_PATCHED | ✅ | ✅ | ❌ | ❌ |

**WireGuard is never present in any stock release**, across all 13 versions analyzed — consistent with why this repository had to cross-compile a custom WireGuard kernel module (see [`GUIDE-EN.md`](GUIDE-EN.md)) instead of enabling one already shipped.

### 3.6 Total file count (complexity proxy)

`1.0.3`=4255, `1.0.4`=4494, `1.1.2`=4781, `1.2.0_001`=4781, `2.0.0`=4789, `2.0.0_002`=4787, `2.0.1_003`=4790, `2.2.0`=6114, `2.2.1`=6178, `2.3.2`=**13112**, `2.4.1`=8011, `2.4.5`=8015, `2.4.5_PATCHED`=8015.

The peak at `2.3.2` (almost double `2.4.1`) coincides with the 18-board consolidation — likely per-board assets not yet merged, later reorganized/pruned in `2.4.x`.

### 3.7 2.4.5 CLOSED vs PATCHED

Identical container structure (`0xB7→0xB8→0xB4→0xB0`), identical static `0x104`-byte blob, different `0xB8` hash but **internally consistent** with its own payload in both cases (see §3.1) — the patched rebuild is structurally indistinguishable from an "original" file with respect to this verification mechanism.

At the rootfs level, comparing a clean re-extraction of `2.4.5` (straight from the original `.rbi`) against `2.4.5_PATCHED`, **exactly 3 files change** — nothing else:

| File | Stock 2.4.5 | Patched |
|---|---|---|
| `etc/passwd` (root line) | `root:x:0:0:root:/root:/bin/restricted_shell` | `root:x:0:0:root:/root:/bin/ash` |
| `etc/shadow` (root line) | `root:*:0:0:99999:7:::` (no password, locked account) | `root:$6$<salt>$<hash>:0:0:99999:7:::` (a known password set, sha512crypt hash) |
| `etc/config/dropbear` (`lan` section) | `enable '0'`, `RootLogin '0'`, `RootPasswordAuth '0'`, `AllowLocalForwarding '0'` | `enable '1'`, `RootLogin '1'`, `RootPasswordAuth '1'`, `AllowLocalForwarding '1'` |

The `public_lan` and `wan` dropbear sections are left untouched (still disabled). The patch is therefore narrow and minimal: it swaps root's shell for a full one, sets a known root password, and enables root-login SSH on the LAN interface only — nothing else in the filesystem is touched.

**Important methodological note:** an earlier pass at this analysis, based on working folders reused from a prior rooting attempt in this same local repository, wrongly showed "0 differences" between `2.4.5` and `2.4.5_PATCHED` — because the folder used as the "stock" reference had already been patched **in-place** by the rooting script itself (`patch_245.sh`), which edits `/etc/passwd`, `/etc/shadow` and `/etc/config/dropbear` directly in the source folder before a separate script (`rebuild_245.sh`) repacks it into a new `.rbi`. Lesson: whenever a folder may have been used as the source for a rebuild/patch, always re-extract it fresh from the original `.rbi` before using it as a "stock" baseline — don't trust recycled working folders.

## 4. Sequential per-version changelog

See [`VERSION-CHANGELOG-EN.md`](VERSION-CHANGELOG-EN.md) for a version-by-version (not just aggregate) breakdown of what changed between each consecutive release.

## 5. Building (encrypting) a valid .rbi — verified on real hardware

The previous sections analyze the format from the reading side. Here is the
reverse path: building a valid `.rbi` from scratch out of a patched raw image
(kernel+squashfs, 80MB), using only the public OSCK (§2.1) — **with no
Technicolor private key at all**. Confirmed working both in a local round-trip
(decrypt→encrypt→decrypt) and in a **real flash** via BOOTP/TFTP recovery on
physical VBNT-K hardware (see §5.3).

### 5.1 Build algorithm

Reassembly from the inside out (exact inverse of §2):

```
b0  = 0xB0 + "MUTE" + flag(0x00) + payload_raw
b4  = 0xB4 + "MUTE" + flag(0x00) + len(b0)_be32 + zlib.compress(b0)
b8  = 0xB8 + "MUTE" + flag(0x00) + len(b4)_be32 + SHA256(b4)
combined = b8 + b4     # FLAT concatenation, not nesting — b8 is only a
                        # header+hash; the real b4 chunk follows right after
                        # it in the decrypted stream (§2.2 explains this, but
                        # it's an easy mistake to encrypt only b8)
key2, iv1, iv2 = random(32), random(16), random(16)
enc_key2  = AES256-CBC(OSCK, iv1).encrypt(pkcs7_pad(key2))      # always 48 bytes
ciphertext = AES256-CBC(key2, iv2).encrypt(pkcs7_pad(combined))
b7 = 0xB7 + "MUTE" + flag(0x00) + len(ciphertext)_be32 + iv1 + enc_key2 + iv2 + ciphertext

rbi_file = original_header[0:data_offset] + b7   # header reused verbatim from
                                                   # an original .rbi for the
                                                   # same board, except the
                                                   # data_size field (0x2C)
                                                   # updated to len(b7)
```

Reference implementation (Python, pycryptodome): `encrypt_rbi.py`, not yet
published in this repo — feel free to open an issue if the full source is
needed.

### 5.2 Undocumented invariant: byte 0x2F / 0x178+header_offset

Verified across the 12 `.rbi` files examined in this pass (the 8 primary
1.0.3→2.4.5 versions plus the 3 intermediate hdrfix/b7fix/b8fix backups of
`AGTEF_2.4.5_PATCHED.rbi` plus one duplicate `VBNT-K.rbi` copy — a subset of
the 14 unique files compared in §3): the `data_size` field (0x2C, 4 bytes)
and the `counter` field of the 0xB7 chunk (the first 4 bytes right after
`flag`, at offset `data_offset + 6`) have a fixed relationship between their
respective last bytes:

```
last_byte(data_size) == last_byte(counter_0xB7) | 0x0A
```

E.g. on an authentic file: `data_size` ends in `...4A`, the 0xB7 chunk's
counter ends in `...40` → `0x40 | 0x0A = 0x4A` ✓. A "clean" build that
computes both fields independently (as in the §5.1 formula, without this fix)
does **not** satisfy the invariant — verified that the resulting file is
still accepted and correctly decrypted by the reading tool (the invariant
isn't checked there), but it's unclear whether it's checked elsewhere (the
bootloader?), so the reference script applies it anyway for safety, forcing
`data_size`:

```python
full[0x2F] = full[offset_of_0xB7_counter_last_byte] | 0x0A
```

Suspected origin: probably not a real security field, more likely an
artifact of how the original Technicolor tool derives both fields from a
single internal value via a masking transform — not investigated further.
Historical note: an earlier session had already discovered this relationship
empirically by hand-repairing an encrypted file with a hex editor (hence the
`.bak_pre_hdrfix`/`.bak_pre_b7fix`/`.bak_pre_b8fix` backup names seen around
the project), before the general mechanism described here was understood.

### 5.3 Real-hardware verification (2026-08-23)

Built a `.rbi` with this scheme starting from `AGTEF_2.2.1_CLOSED.rbi`
("221") patched with the same 3 files from §3.7 (dropbear/passwd/shadow),
served via BOOTP/TFTP recovery (procedure in `GUIDE-EN.md`) to a physical
VBNT-K. Result:

- Router entered BOOT-P mode via the automatic serial trigger on
  `Market ID`.
- **TFTP transfer completed successfully twice in a row** (log:
  `TFTP started` → `TFTP finished`, no CFE error), the router wrote and
  rebooted from Bank 1 both times with no errors.
- Clean, complete Linux boot with the freshly-written image: no kernel
  panic, WiFi (Quantenna) operational, no reboot loop. Confirmed via
  SHA-256 hash that the file actually transferred matches byte-for-byte the
  locally-built `.rbi`.

This is, as of now, the **first real-hardware confirmation** (not just a
round-trip through the reading tool) that this bootloader's CFE accepts a
`.rbi` built entirely from scratch with only the public OSCK, with no
Technicolor private signature — consistent with §2.2's conclusion
("obfuscation, not authentication").

**Note for anyone repeating the test — CFE timeout -21**: in the first
attempts (two different sessions, different files) the transfer always
failed with `Loading failed.: CFE error -21` after a constant time (~8.5s,
independent of file size). Verified against the original Broadcom source
(`cfe_error.h`, `Noltari/cfe_bcm63xx` repo): **-21 = `CFE_ERR_TIMEOUT`**, not
a validation rejection. Real cause: **Windows Firewall blocks inbound UDP
traffic on port 69 by default** for processes without an explicit rule (the
BOOTP traffic still gets through because it's captured/sent at the driver
level via scapy/Npcap, bypassing the firewall — TFTP instead uses a standard
UDP socket, which gets blocked). Fix:

```powershell
New-NetFirewallRule -DisplayName "TFTP recovery" -Direction Inbound -Protocol UDP -LocalPort 69 -Action Allow -Profile Private
```

**Open problem, not yet resolved**: after a confirmed-successful flash (per
the serial log and hash match), SSH login with `root`/`root` on the new
image **still fails** ("Permission denied (password)"), even though the
`/etc/shadow` hash was verified correct locally before flashing. At the same
time, the web UI shows a distinct but possibly related symptom: the Lua
engine is alive, but page templates get rendered as raw unexecuted text
instead of being run (observed repeatedly across the project; the term
"raw-Lua issue" also appears in [`GUIDE-ROOT-EN.md`](GUIDE-ROOT-EN.md), there
only to note it did *not* occur in that specific attempt) — **no dedicated
write-up exists yet for this symptom**, it remains an open problem without
its own document. Leading hypothesis on the SSH side, not yet
confirmed: these systems mount the squashfs read-only with a **persistent
writable overlay** (a separate partition, untouched by the BOOTP/TFTP flash,
which only covers kernel+rootfs — see
[`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md)) for `/etc` — if an
earlier version of these files (from a previous rooting attempt on this same
router) was already written into the overlay, it shadows whatever changes
are made in the squashfs, regardless of what the freshly-flashed image
contains. To be verified with a genuine factory reset (7 seconds on the
reset button **while the router is already powered on and booted**, a
different procedure from the power-on-with-reset-held used for BOOTP
recovery) to clear the overlay — **first attempt (2026-08-23) inconclusive**:
this exact same hard reset had already been tried before on this router for
a different problem (§10.1 of the local, not-yet-published recovery
documentation) without fixing it, so it's not guaranteed to actually clear
`rootfs_data` on this hardware.

## 6. Device-side signature verification — confirmed at the machine-code level (2026-09-09)

§2.2/§3.1 are about the `0xB8` self-consistency hash **inside the** `.rbi`
**file**: a plain SHA-256, recomputable by anyone, which is not
authentication. The question §2.2 left open remained — does the **device**
have a genuine public-key verification of the firmware? This session answers
it by disassembling the real binaries extracted read-only from a rooted
physical unit (root over SSH, community firmware of the AGTEF 2.4.5 family,
kernel 4.1.52; the same unit as
[`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.2).

**Answer: yes, it exists — and it is standard OpenSSL RSA-2048/PSS, not
tampered with.** It is a mechanism independent of the container format: it
operates on the BLI header+payload, not on the `0xB8` chunk. Until now in the
repo this was presumably known only from black-box behavior (SIGTEST); here it
is confirmed by reading the machine code directly.

### 6.1 Binaries and algorithm (Observed — ARM disassembly)

Binaries analyzed (dynamic ARM ELF, **non-stripped**, `blitools` v1.0
package), extracted read-only from the unit's filesystem:

| Binary | Size | Role |
|---|---|---|
| `signature_checker` | 13612 B | verification orchestrator |
| `bli_unseal_rsa_helper` | 9516 B | RSA operations (OpenSSL) |
| `bli_parser` | 5420 B | BLI header field parsing |

> **Naming note — `bli_unseal_rsa` vs `bli_unseal_rsa_helper`.** These are two
> real, distinct entities, not a naming inconsistency: `bli_unseal_rsa_helper`
> (in the table) is the **actual ELF binary** — the one actually disassembled
> here. It is invoked by a small **128-byte shell wrapper script** named
> `bli_unseal_rsa`, which just runs
> `dd bs=1 count=5 &>/dev/null; exec bli_unseal_rsa_helper | bli_unseal`.
> So: `bli_unseal_rsa` = wrapper script → `bli_unseal_rsa_helper` = real
> binary.

Exact algorithm reconstructed from the disassembly:

1. `SHA-256` over the content (header + payload).
2. `RSA_public_decrypt(..., padding = RSA_NO_PADDING)` over the 256-byte
   signature (RSA-2048).
3. `RSA_verify_PKCS1_PSS(hash = SHA256, salt = auto)`.

These are all standard OpenSSL calls, with no modification to the crypto code.
**No bypass present in the binary**: no imported `getenv`, no suspicious
`debug`/`skip`/backdoor strings. If the verification material is missing the
binary does `exit(1)` (fail-closed, see §6.3), it does not silently proceed.

### 6.2 "OSIK" resolved — Operator Software Image Key (Observed)

The verification public key is read from `/proc/rip/0120` (or from a file
passed with `-k`): 512 bytes, permissions `-r--------` (see the full catalog
in [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.3).

`MEMORY-ARCHITECTURE-EN.md` §4 already cited `OSIK` as one of the names seen
in the external tool
[`pedro-n-rocha/secr`](https://github.com/pedro-n-rocha/secr), but **without
the acronym's expansion**. This session provides it, as the **first direct
confirmation**: the real script `/usr/sbin/rip-create-efu.sh` present in the
firmware filesystem contains the alias line binding the RSA key of
`/proc/rip/0120` to the name **OSIK = "Operator Software Image Key"**. No byte
of the key is reproduced here (repo scrub constraint).

### 6.3 DSA/SHA-1 fallback — present in code, inert on this hardware (Observed)

The disassembly shows a fallback path: if `/proc/rip/0120` cannot be opened,
`signature_checker` tries `/proc/rip/0116` and, if present, verifies with
**DSA + SHA-1** (a weaker scheme) instead of RSA-PSS/SHA-256. If **neither**
block exists, it does `exit(1)` — fail-closed, no verification bypassed.

**Empirically verified on the real unit**: `/proc/rip/0116` **does not exist**
on this device (only `0120` exists, see
[`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.3). So the weaker
DSA/SHA-1 branch is **present in the code but inert** on normal production
hardware: the `0116` slot was never provisioned. Worth flagging because, on a
hypothetical unit where `0120` were unreadable but `0116` populated,
verification would fall back to a significantly weaker algorithm — not the
case here, but an assumption not to be taken for granted on other
boards/variants.

### 6.4 Same mechanism reused in the userspace update path (NEW fact)

A discovery not yet documented in any repo file: **the exact same
`signature_checker`/`bli_unseal_rsa_helper`/`bli_parser` is also invoked from
the userspace update path**, not only in the bootloader context. The chain is:

```
sysupgrade-safe → /sbin/sysupgrade --safe
               → platform_check_image_imp()  (in /lib/upgrade/platform.sh)
               → signature_checker            (streaming, while writing the inactive bank)
```

Beyond the RSA signature, `platform_check_image_imp` runs — through its
internal sub-function `platform_check_bliheader` — a **separate check of the
BLI header fields** (`fia` / `fim` / `boardname` / `prodid` / `varid`)
against the device's corresponding infoblocks: `/proc/rip/0028`,
`/proc/rip/0040`, `/proc/rip/8001`, `/proc/rip/8003` (see
[`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.3 for the meaning
of these codes) — i.e. an image for the wrong board/variant is rejected
regardless of the signature.

There is a bypass flag, `--nosig` / `IGNORE_SIGNATURE=1`, in the wrapper
script, **explicitly labelled by the developers "for development only"**.
Important: it skips **only** the `signature_checker` call, **not** the other
checks (header fields, size). It is therefore not a "flash anything": it
disables the cryptographic verification alone, leaving the hardware-
compatibility checks in place.

### 6.5 Third layer (`validate_firmware_image` / `ucert`) — present but empty (Observed)

`/usr/libexec/validate_firmware_image` references the standard OpenWrt
`fwtool` / `ucert` mechanism ("usign" signatures). On this device, however,
`/usr/bin/ucert` **does not exist** and `/etc/opkg/keys/` **does not exist**:
this layer is effectively an empty shell, never actually active. Real firmware
verification on this unit therefore goes through the RSA/PSS mechanism of
§6.1, not through `ucert`.

### 6.6 Open questions / relationship with §5.3

- **Tension with §5.3, not yet resolved.** In §5.3 a `.rbi` built from scratch
  with only the public OSCK (no private RSA signature) was **flashed
  successfully via BOOTP/TFTP recovery** and booted cleanly. The RSA-2048/PSS
  verification described here lives in the **userspace/Linux** binaries
  (`signature_checker`) and is called by the `sysupgrade` path, which is a
  **different** route from the CFE-driven BOOTP/TFTP recovery. The reading
  most consistent with both data points is that the **two bank-writing paths
  are governed by distinct checks**: `sysupgrade` (Linux) enforces the RSA
  signature of §6.1, while the CFE-level recovery flash evidently does **not**
  (or applies only weaker checks), consistent with §5.3's empirical
  conclusion. Not verified: the CFE code itself was not disassembled in this
  session — the analysis here concerns the Linux binaries. It thus remains
  possible, but unproven, that a verification exists in the CFE too that §5.3
  satisfied by another route (e.g. the header reused verbatim from a genuine
  image).
- Not verified whether `signature_checker` is also invoked at bank
  boot/activation time (beyond write via `sysupgrade`).
- `/proc/rip/0127` has the same declared size as `/proc/rip/0120` (512 B):
  unconfirmed hypothesis that it is a **second RSA-2048 key** (see
  [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.3) — it is not
  referenced by `signature_checker` in the observed paths.
