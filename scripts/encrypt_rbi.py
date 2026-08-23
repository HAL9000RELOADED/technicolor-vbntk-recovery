import struct
import sys
import zlib
import hashlib
import os
from Crypto.Cipher import AES

OSCK = bytes.fromhex("FFD56A4E3A21401BF1798B3CD8AD54D238BA80039623BBA08B6D50B8EC73F7B4")
MUTE = b"MUTE"


def pad_pkcs5(data, block=16):
    pad = block - (len(data) % block)
    if pad == 0:
        pad = block
    return data + bytes([pad]) * pad


def build(template_rbi_path, new_payload_path, out_path):
    with open(template_rbi_path, "rb") as f:
        template = f.read()
    with open(new_payload_path, "rb") as f:
        payload = f.read()

    payload_offset = struct.unpack(">I", template[0x28:0x2C])[0]
    fixed_header = bytearray(template[:payload_offset])

    # --- ricalcola il campo "ridondante" a 0x2C (4 byte dopo payload_offset),
    # mantenendo lo stesso delta rispetto al payload_size del template originale ---
    orig_redundant = struct.unpack(">I", template[0x2C:0x30])[0]
    # payload_size del template (per confronto/derivazione delta)
    tpos = payload_offset + 1 + 5
    orig_payload_size = struct.unpack(">I", template[tpos:tpos + 4])[0]
    redundant_delta = orig_redundant - orig_payload_size

    print(f"payload_offset={hex(payload_offset)}  orig_redundant={orig_redundant}  "
          f"orig_payload_size={orig_payload_size}  delta={redundant_delta}")

    # === B0: chunk piu' interno, e' il payload grezzo ===
    b0_chunk = bytes([0xB0]) + MUTE + bytes([0x00]) + payload

    # === B4: comprime b0_chunk con zlib ===
    compressed = zlib.compress(b0_chunk, level=9)
    b4_counter = len(compressed)  # nessun sotto-campo fisso tra counter e dati zlib -> corretto cosi'
    b4_chunk = bytes([0xB4]) + MUTE + bytes([0x00]) + struct.pack(">I", b4_counter) + compressed
    # NB: decrypt_rbi.py salta esattamente 9 byte dopo il magic 0xB4 (MUTE(4)+flag(1)+counter(4))
    # poi decomprime TUTTO il resto del buffer -> deve combaciare esattamente

    # === B8: blocco di firma, hash SHA-256 di tutto cio' che segue (b4_chunk) ===
    sig_hash = hashlib.sha256(b4_chunk).digest()
    # regola verificata sugli originali: counter = tutto cio' che segue il counter stesso,
    # cioe' hash(32) + b4_chunk -- NON solo len(b4_chunk)
    sig_counter = len(sig_hash) + len(b4_chunk)
    b8_block = bytes([0xB8]) + MUTE + bytes([0x00]) + struct.pack(">I", sig_counter) + sig_hash

    inner_plaintext = b8_block + b4_chunk

    # === B7: cifra tutto con AES-256-CBC, chiave key2 generata a caso, key2 cifrata con OSCK ===
    key2 = os.urandom(32)
    iv2 = os.urandom(16)
    padded_inner = pad_pkcs5(inner_plaintext)
    cipher2 = AES.new(key2, AES.MODE_CBC, iv2)
    ciphertext = cipher2.encrypt(padded_inner)

    iv1 = os.urandom(16)
    key2_padded = pad_pkcs5(key2)  # 32 -> 48 byte
    cipher1 = AES.new(OSCK, AES.MODE_CBC, iv1)
    enc48 = cipher1.encrypt(key2_padded)

    # regola verificata sugli originali: counter = tutto cio' che segue il counter stesso,
    # cioe' iv1(16)+enc48(48)+iv2(16)+ciphertext -- NON solo len(ciphertext)
    b7_counter = len(iv1) + len(enc48) + len(iv2) + len(ciphertext)
    b7_container = (
        bytes([0xB7])
        + MUTE + bytes([0x00])
        + struct.pack(">I", b7_counter)
        + iv1
        + enc48
        + iv2
        + ciphertext
    )

    # aggiorna il campo ridondante nell'header fisso con lo stesso delta osservato nel template
    new_redundant = b7_counter + redundant_delta
    fixed_header[0x2C - payload_offset + payload_offset if False else 0x2C:0x30] = struct.pack(">I", new_redundant & 0xFFFFFFFF)

    out = bytes(fixed_header) + b7_container
    with open(out_path, "wb") as f:
        f.write(out)

    print(f"Scritto {out_path}: {len(out)} byte")
    print(f"  payload originale: {len(payload)} byte")
    print(f"  b0_chunk: {len(b0_chunk)} byte")
    print(f"  compressed (b4 body): {len(compressed)} byte")
    print(f"  b4_chunk totale: {len(b4_chunk)} byte")
    print(f"  ciphertext: {len(ciphertext)} byte")
    print(f"  key2: {key2.hex()}")
    print(f"  iv1: {iv1.hex()}  iv2: {iv2.hex()}")
    return out_path


if __name__ == "__main__":
    template = sys.argv[1]
    new_payload = sys.argv[2]
    out = sys.argv[3]
    build(template, new_payload, out)
