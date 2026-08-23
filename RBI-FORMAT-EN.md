# AGTEF `.rbi` format: header, encryption and "signature" — what changes between versions

Analysis of the `.rbi` firmware container used by the Technicolor VBNT-K (TIM, `AGTEF_x.y.z_CLOSED.rbi`), of its internal encryption/"signature" mechanism, and a real comparison between versions `1.0.3`, `1.1.3` and `2.4.5` (original vs patched).

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

Across all files analyzed (`1.0.3`, `1.1.3`, `2.4.5` CLOSED and PATCHED): `magic="BLI2"`, `data_offset=0x171`, board `VBNT-K` / product `Technicolor DGA0130TCH`.

A fixed `0x104`-byte blob immediately follows the static header, commented as "Signature? Hash?" in the reference tool — **verified that it is NOT**: it is byte-identical between `1.0.3` and `1.1.3`, and byte-identical between `2.4.5` CLOSED and `2.4.5` PATCHED (despite their payloads and file sizes being completely different). It does not depend on content — it's static material (likely a certificate/key tied to a build generation, not a payload hash).

Dynamic TLV fields (`id`, `len`, `value`) follow up to `data_offset`: `timestamp`, `boardname`, `prodname`, `varname`, `tagpparserversion`, `flashaddress`.

## 2. Chunk chain (starting at `data_offset`)

At `data_offset` a sequence of nested chunks begins, each introduced by a magic byte preceded by the ASCII tag `MUTE`:

```
0xB7  encrypted container (AES-256-CBC)   — outer layer, always present
  └─ 0xB8  "signature" block               — hash of the next chunk
       └─ 0xB4  zlib-compressed chunk
            └─ 0xB0  plaintext payload      — final flash image (80 MB)
```

Confirmed identical across all 4 files analyzed: `['0xb7', '0xb8', '0xb4', '0xb0']`.

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

Verification across the 4 files (declared header hash vs. hash recomputed on the decrypted payload):

| File | match |
|---|---|
| `AGTEF_1.0.3_CLOSED.rbi` | ✅ |
| `AGTEF_1.1.3_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_PATCHED.rbi` | ✅ |

**Conclusion:** this format has no cryptographic signature tied to a Technicolor private key that would prevent building a "valid"-looking `.rbi` with an arbitrary payload — the only internal consistency check (the `0xB8` hash) is correctly recomputed by anyone using the same packing toolchain, as demonstrated by the patched build (`2.4.5_PATCHED`) passing this check exactly like the original does. Whether the router's CFE bootloader actually enforces this field (or anything else, e.g. header fields) during boot/recovery is a separate question about the bootloader itself, not about the file format.

### 2.3 Layer 0xB4/0xB0

`0xB4`: `magic(1) + "MUTE"(4) + flag(1) + counter(4) + zlib_data`. `0xB0`: `magic(1) + "MUTE"(4) + flag(1) + plaintext_payload` — the final flash image, 80 MB (`0x5000000`) across all files tested.

## 3. Real comparison between firmware versions

### 1.0.3 vs 1.1.3

Rootfs extracted natively (caveat: extracting on a case-insensitive Windows/DrvFs filesystem silently drops files that differ only by case — always re-check on a case-sensitive filesystem before drawing conclusions from a `diff -rq`).

Real differences (not extraction artifacts):

- **`etc/config/dropbear`**: `1.0.3` ships with SSH disabled by default (`enable '0'`, `RootPasswordAuth off`); `1.1.3` ships it **enabled** (`enable '1'`, `RootPasswordAuth on`, `RootLogin '1'`).
- **`etc/inittab`**: `1.0.3` has the serial console commented out (`#::askconsole:/bin/login`); `1.1.3` has it **active with no login** (`::askconsole:/bin/ash` — direct shell over UART, no authentication).
- Kernel modules (`3.4.11`, `3.4.11-rt19`) are identical in both versions.
- A few placeholder files (`etc/fstab`, `etc/mtab`, `etc/resolv.conf`, `etc/TZ`, `etc/snmp/snmpd.conf`) exist only in `1.1.3` — likely OpenWrt build/overlay markers, not necessarily meaningful firmware payload.

### 2.4.5 CLOSED vs PATCHED

Identical container structure (`0xB7→0xB8→0xB4→0xB0`), identical static `0x104`-byte blob, different `0xB8` hash but **internally consistent** with its own payload in both cases (see table above) — the patched rebuild is structurally indistinguishable from an "original" file with respect to this verification mechanism.
