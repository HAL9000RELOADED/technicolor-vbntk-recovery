# Formato `.rbi` AGTEF: header, cifratura e "firma" — cosa cambia tra le versioni

Analisi del contenitore firmware `.rbi` usato dal Technicolor VBNT-K (TIM, `AGTEF_x.y.z_CLOSED.rbi`), del meccanismo di cifratura/"firma" interno, e confronto reale tra le versioni `1.0.3`, `1.1.3` e `2.4.5` (originale vs patchata).

## 1. Header statico

I primi `0x30` byte sono un header a campi fissi:

```
0x00  4   magic            "BLI2"
0x04  2   fim
0x06  2   fia
0x08  12  prodid
0x14  12  varid
0x20  4   version          (byte-per-byte: major.minor.patch.build)
0x24  4   unknown
0x28  4   data_offset      (offset assoluto del primo chunk payload)
0x2C  4   data_size        (dimensione dichiarata del blocco payload, "ridondante")
```

Su tutti i file analizzati (`1.0.3`, `1.1.3`, `2.4.5` CLOSED e PATCHED): `magic="BLI2"`, `data_offset=0x171`, board `VBNT-K` / prodotto `Technicolor DGA0130TCH`.

Segue un blob fisso di `0x104` byte (subito dopo l'header statico) che nel tool di riferimento è commentato come "Signature? Hash?" — **verificato che NON lo è**: è identico byte-per-byte tra `1.0.3` e `1.1.3` (stesso valore) e identico tra `2.4.5` CLOSED e `2.4.5` PATCHED (nonostante payload e dimensione del file siano completamente diversi). Non dipende dal contenuto — è materiale statico (probabilmente un certificato/chiave legato alla generazione di build, non un hash del payload).

Dopo questo blob seguono campi dinamici in formato TLV (`id`, `len`, `value`) fino a `data_offset`: `timestamp`, `boardname`, `prodname`, `varname`, `tagpparserversion`, `flashaddress`.

## 2. Catena dei chunk (a partire da `data_offset`)

A `data_offset` inizia una sequenza di chunk annidati, ciascuno introdotto da un byte magic preceduto dal tag ASCII `MUTE`:

```
0xB7  container cifrato (AES-256-CBC)   — livello esterno, sempre presente
  └─ 0xB8  blocco "firma"                — hash del chunk successivo
       └─ 0xB4  chunk compresso (zlib)
            └─ 0xB0  payload in chiaro   — immagine flash finale (80 MB)
```

Confermato identico su tutti e 4 i file analizzati: `['0xb7', '0xb8', '0xb4', '0xb0']`.

### 2.1 Livello 0xB7 — cifratura AES

```
magic(1) + "MUTE"(4) + flag(1) + counter(4) + iv1(16) + enc_key2(48) + iv2(16) + ciphertext
```

- `enc_key2` = una chiave AES-256 casuale (`key2`), cifrata con AES-256-CBC usando `iv1` e una chiave **fissa e condivisa** (hardcoded nel tool, uguale su ogni versione/file):

  ```
  OSCK = FFD56A4E3A21401BF1798B3CD8AD54D238BA80039623BBA08B6D50B8EC73F7B4
  ```

- Il vero payload (`0xB8`+`0xB4`+`0xB0`) è cifrato con `key2` (CBC, `iv2`), padding PKCS5.

**Questo livello è offuscamento, non autenticazione**: la chiave `OSCK` è statica e condivisa tra tutte le versioni — chiunque la conosca (come questo stesso tool) può cifrare/decifrare qualsiasi payload arbitrario in un contenitore `0xB7` valido.

### 2.2 Livello 0xB8 — il blocco "firma"

```
magic(1) + "MUTE"(4) + flag(1) + counter(4) + hash(32)
```

**Verificato empiricamente (byte a byte) che `hash = SHA-256(chunk 0xB4 che segue)`.** Non è una firma RSA/ECDSA con chiave privata: è un semplice digest di autoconsistenza, ricalcolato dal tool che impacchetta il file (vedi `encrypt_rbi.py`, funzione `build()`):

```python
sig_hash = hashlib.sha256(b4_chunk).digest()
b8_block = bytes([0xB8]) + MUTE + bytes([0x00]) + struct.pack(">I", len(b4_chunk)) + sig_hash
```

Verifica sui 4 file (hash dichiarato nell'header vs hash ricalcolato sul payload decifrato):

| File | match |
|---|---|
| `AGTEF_1.0.3_CLOSED.rbi` | ✅ |
| `AGTEF_1.1.3_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_PATCHED.rbi` | ✅ |

**Conclusione:** non esiste, in questo formato, una firma crittografica legata a una chiave privata Technicolor che impedisca di costruire un file `.rbi` "valido" con un payload arbitrario — il solo controllo di consistenza interno (l'hash `0xB8`) viene ricalcolato correttamente da chiunque usi lo stesso toolchain di impacchettamento, come dimostra il fatto che la versione patchata (`2.4.5_PATCHED`) supera questo controllo esattamente come l'originale. Se la CFE del router verifica effettivamente questo campo (o altro, es. campi header) durante il boot/recovery resta una domanda separata, legata al bootloader stesso e non al formato file.

### 2.3 Livello 0xB4/0xB0

`0xB4`: `magic(1) + "MUTE"(4) + flag(1) + counter(4) + dati_zlib`. `0xB0`: `magic(1) + "MUTE"(4) + flag(1) + payload_in_chiaro` — l'immagine flash finale, 80 MB (`0x5000000`) su tutti i file testati.

## 3. Confronto reale tra le versioni firmware

### 1.0.3 vs 1.1.3

Rootfs riestratti nativamente (attenzione: un'estrazione su filesystem Windows/DrvFs case-insensitive perde silenziosamente file che differiscono solo per maiuscole/minuscole — ricontrollare sempre su un filesystem case-sensitive prima di trarre conclusioni da un `diff -rq`).

Differenze reali (non artefatti di estrazione):

- **`etc/config/dropbear`**: `1.0.3` ha SSH disabilitato di fabbrica (`enable '0'`, `RootPasswordAuth off`); `1.1.3` lo ha **abilitato** (`enable '1'`, `RootPasswordAuth on`, `RootLogin '1'`).
- **`etc/inittab`**: `1.0.3` ha la console seriale commentata (`#::askconsole:/bin/login`); `1.1.3` la ha **attiva senza login** (`::askconsole:/bin/ash` — shell diretta su UART, nessuna autenticazione).
- Moduli kernel (`3.4.11`, `3.4.11-rt19`) identici in entrambe le versioni.
- Alcuni file placeholder (`etc/fstab`, `etc/mtab`, `etc/resolv.conf`, `etc/TZ`, `etc/snmp/snmpd.conf`) presenti solo in `1.1.3` — probabili marker di build/overlay OpenWrt, non necessariamente payload firmware significativo.

### 2.4.5 CLOSED vs PATCHED

Stessa identica struttura di contenitore (`0xB7→0xB8→0xB4→0xB0`), stesso blob statico da `0x104` byte, hash `0xB8` diverso ma **internamente coerente** con il rispettivo payload in entrambi i casi (vedi tabella sopra) — la ricostruzione patchata è strutturalmente indistinguibile da un file "originale" per quanto riguarda questo meccanismo di verifica.
