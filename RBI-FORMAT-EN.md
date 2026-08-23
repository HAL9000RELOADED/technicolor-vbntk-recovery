# AGTEF `.rbi` format: header, encryption and "signature" — what changes between versions

Analysis of the `.rbi` firmware container used by the Technicolor VBNT-K (TIM, `AGTEF_x.y.z_CLOSED.rbi`), of its internal encryption/"signature" mechanism, and a real comparison between versions `1.0.3` and `2.4.5` (original vs patched).

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

### 2.3 Layer 0xB4/0xB0

`0xB4`: `magic(1) + "MUTE"(4) + flag(1) + counter(4) + zlib_data`. `0xB0`: `magic(1) + "MUTE"(4) + flag(1) + plaintext_payload` — the final flash image, 80 MB (`0x5000000`) across all files tested.

## 3. Real comparison across all available firmware versions

Analysis extended to all **13 unique images** found in the folder (deduplicated by MD5 — `*_copy.rbi` files are byte-for-byte duplicates, excluded): `1.0.3`, `1.0.4`, `1.1.2`, `1.2.0_001`, `2.0.0`, `2.0.0_002`, `2.0.1_003`, `2.2.0`, `2.2.1`, `2.3.2`, `2.4.1`, `2.4.5`, `2.4.5_PATCHED`. Rootfs extracted natively in WSL (ext4, case-sensitive) — extracting on a case-insensitive Windows/DrvFs filesystem silently drops files that differ only by case, so always re-check on a case-sensitive filesystem before drawing conclusions from a `diff -rq`.

### 3.1 Signature check — universal across all 13

The byte-for-byte check described in §2.2 (`0xB8` hash == `SHA-256` of the following `0xB4` chunk) was repeated across all 13 images, patch included: **positive match on every single one**, no exceptions. This definitively confirms the mechanism was never a private-key signature in any observed version of the AGTEF line.

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
