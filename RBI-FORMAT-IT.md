# Formato `.rbi` AGTEF: header, cifratura e "firma" — cosa cambia tra le versioni

Analisi del contenitore firmware `.rbi` usato dal Technicolor VBNT-K (TIM, `AGTEF_x.y.z_CLOSED.rbi`), del meccanismo di cifratura/"firma" interno, e confronto reale tra le versioni `1.0.3` e `2.4.5` (originale vs patchata).

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

Su tutti i file analizzati (`1.0.3`, `2.4.5` CLOSED e PATCHED): `magic="BLI2"`, `data_offset=0x171`, board `VBNT-K` / prodotto `Technicolor DGA0130TCH`.

Segue un blob fisso di `0x104` byte (subito dopo l'header statico) che nel tool di riferimento è commentato come "Signature? Hash?" — **verificato che NON lo è**: è identico byte-per-byte tra `2.4.5` CLOSED e `2.4.5` PATCHED (nonostante payload e dimensione del file siano completamente diversi). Non dipende dal contenuto — è materiale statico (probabilmente un certificato/chiave legato alla generazione di build, non un hash del payload).

Dopo questo blob seguono campi dinamici in formato TLV (`id`, `len`, `value`) fino a `data_offset`: `timestamp`, `boardname`, `prodname`, `varname`, `tagpparserversion`, `flashaddress`.

## 2. Catena dei chunk (a partire da `data_offset`)

A `data_offset` inizia una sequenza di chunk annidati, ciascuno introdotto da un byte magic preceduto dal tag ASCII `MUTE`:

```
0xB7  container cifrato (AES-256-CBC)   — livello esterno, sempre presente
  └─ 0xB8  blocco "firma"                — hash del chunk successivo
       └─ 0xB4  chunk compresso (zlib)
            └─ 0xB0  payload in chiaro   — immagine flash finale (80 MB)
```

Confermato identico su tutti e 3 i file analizzati: `['0xb7', '0xb8', '0xb4', '0xb0']`.

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

Verifica sui 3 file (hash dichiarato nell'header vs hash ricalcolato sul payload decifrato):

| File | match |
|---|---|
| `AGTEF_1.0.3_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_CLOSED.rbi` | ✅ |
| `AGTEF_2.4.5_PATCHED.rbi` | ✅ |

**Conclusione:** non esiste, in questo formato, una firma crittografica legata a una chiave privata Technicolor che impedisca di costruire un file `.rbi` "valido" con un payload arbitrario — il solo controllo di consistenza interno (l'hash `0xB8`) viene ricalcolato correttamente da chiunque usi lo stesso toolchain di impacchettamento, come dimostra il fatto che la versione patchata (`2.4.5_PATCHED`) supera questo controllo esattamente come l'originale. Se la CFE del router verifica effettivamente questo campo (o altro, es. campi header) durante il boot/recovery resta una domanda separata, legata al bootloader stesso e non al formato file.

### 2.3 Livello 0xB4/0xB0

`0xB4`: `magic(1) + "MUTE"(4) + flag(1) + counter(4) + dati_zlib`. `0xB0`: `magic(1) + "MUTE"(4) + flag(1) + payload_in_chiaro` — l'immagine flash finale, 80 MB (`0x5000000`) su tutti i file testati.

## 3. Confronto reale tra tutte le versioni firmware disponibili

Analisi estesa a tutte le **13 immagini uniche** trovate in cartella (dedup per hash MD5 — i file `*_copy.rbi` sono duplicati byte-per-byte, esclusi): `1.0.3`, `1.0.4`, `1.1.2`, `1.2.0_001`, `2.0.0`, `2.0.0_002`, `2.0.1_003`, `2.2.0`, `2.2.1`, `2.3.2`, `2.4.1`, `2.4.5`, `2.4.5_PATCHED`. Rootfs riestratti nativamente in WSL (ext4, case-sensitive) — un'estrazione su filesystem Windows/DrvFs perde silenziosamente file che differiscono solo per maiuscole/minuscole, quindi ricontrollare sempre su un filesystem case-sensitive prima di trarre conclusioni da un `diff -rq`.

### 3.1 Verifica firma — universale su tutte e 13

Il controllo byte-per-byte descritto al §2.2 (`hash 0xB8 == SHA-256(chunk 0xB4)`) è stato ripetuto su tutte e 13 le immagini, patch inclusa: **match positivo su tutte**, nessuna eccezione. Conferma definitiva che il meccanismo non è mai stato una firma a chiave privata in nessuna versione della linea AGTEF osservata.

### 3.2 SSH (dropbear) — evoluzione nel tempo

| Versione | Struttura config | `enable` (lan) | `RootPasswordAuth` | `RootLogin` |
|---|---|---|---|---|
| 1.0.3 | istanza singola | `0` | `off` | — |
| 1.0.4 → 2.0.1_003 | `lan` + `wan` | `0` / `0` | `on` (ma disabilitato) | — |
| 2.2.0 / 2.2.1 | `lan` + `public_lan` + `wan` | `0` / `0` / `0` | `on` | `0` (public_lan/wan) |
| 2.3.2 / 2.4.1 / 2.4.5 | `lan` + `public_lan` + `wan` | `0` / `0` / `0` | `0` (numerico, irrigidito) | `0` |

Punti chiave:

- **Da `2.3.2` a `2.4.5`, lo stock ha SSH completamente disabilitato** su tutte e tre le interfacce e shell di root impostata su `/bin/restricted_shell` (non una shell piena) — coerente con l'irrigidimento iniziato in `2.3.2`. Attenzione metodologica: una prima estrazione di `2.4.1`/`2.4.5` da questo repository locale è risultata contaminata da un tentativo di rooting precedente (`patch_241.sh`/`patch_245.sh`, eseguiti **in-place** sulla stessa cartella usata come "stock" di riferimento) — i valori corretti qui sopra vengono da una ri-estrazione pulita, diretta dai file `.rbi` originali, non dalle cartelle di lavoro riutilizzate. Vedi §3.7 per il contenuto reale della patch.

### 3.3 Console seriale (`etc/inittab`, riga `askconsole`)

| Versione | Riga `askconsole` |
|---|---|
| 1.0.3 | `#::askconsole:/bin/login` (disabilitata) |
| 1.0.4 → 2.0.1_003 | `#::askconsolelate:/bin/login` (disabilitata, nome voce cambiato) |
| 2.3.2 → 2.4.5_PATCHED | `#::askconsole:/bin/restricted_shell` (disabilitata, ma ora punta a una shell ristretta invece di `/bin/login`) |

### 3.4 Kernel e board supportate

| Versione | Kernel | Board in `etc/boards/` |
|---|---|---|
| 1.0.3 → 2.0.1_003 | `3.4.11` (+ `3.4.11-rt19`) | 2 (`VBNT-K`, `VBNT-S`) — assente in 1.0.3 |
| 2.2.0 / 2.2.1 | `4.1.38` | 5 (+ `VANT-W`, `VBNT-F`, `VBNT-H`) |
| 2.3.2 → 2.4.5_PATCHED | `4.1.52` | **18** (`VANT-W`, `VBNT-6/7/9/H/J/K/O/S/V/Y`, `VCNT-A/C/E/H/I/X/Z`) |

Due salti netti: il passaggio di generazione kernel `3.4.11 → 4.1.38` a `2.2.0`, e la grande consolidazione multi-board (da 5 a 18 varianti Technicolor coperte da un'unica immagine) a partire da `2.3.2`.

### 3.5 Feature nel tempo

| Versione | mosquitto (MQTT) | lxc (container) | wireguard | openvpn |
|---|---|---|---|---|
| 1.0.3 / 1.0.4 | ❌ | ❌ | ❌ | ❌ |
| 1.1.2 → 2.0.1_003 | ✅ | ❌ | ❌ | ❌ |
| 2.2.0 → 2.4.5_PATCHED | ✅ | ✅ | ❌ | ❌ |

**WireGuard non è mai presente in nessuna release stock**, su nessuna delle 13 versioni analizzate — coerente con il motivo per cui in questo repository è stato necessario compilare un modulo kernel WireGuard custom (vedi [`GUIDA-IT.md`](GUIDA-IT.md)) invece di attivarne uno già incluso.

### 3.6 Conteggio file totali (proxy di complessità)

`1.0.3`=4255, `1.0.4`=4494, `1.1.2`=4781, `1.2.0_001`=4781, `2.0.0`=4789, `2.0.0_002`=4787, `2.0.1_003`=4790, `2.2.0`=6114, `2.2.1`=6178, `2.3.2`=**13112**, `2.4.1`=8011, `2.4.5`=8015, `2.4.5_PATCHED`=8015.

Il picco a `2.3.2` (quasi il doppio di `2.4.1`) coincide con la consolidazione a 18 board — probabilmente asset per-board non ancora accorpati, poi riorganizzati/potati in `2.4.x`.

### 3.7 2.4.5 CLOSED vs PATCHED

Stessa identica struttura di contenitore (`0xB7→0xB8→0xB4→0xB0`), stesso blob statico da `0x104` byte, hash `0xB8` diverso ma **internamente coerente** con il rispettivo payload in entrambi i casi (vedi §3.1) — la ricostruzione patchata è strutturalmente indistinguibile da un file "originale" per quanto riguarda questo meccanismo di verifica.

A livello di rootfs, confrontando una ri-estrazione pulita di `2.4.5` (diretta dal `.rbi` originale) con `2.4.5_PATCHED`, **cambiano esattamente 3 file** — nessun altro:

| File | Stock 2.4.5 | Patchata |
|---|---|---|
| `etc/passwd` (riga root) | `root:x:0:0:root:/root:/bin/restricted_shell` | `root:x:0:0:root:/root:/bin/ash` |
| `etc/shadow` (riga root) | `root:*:0:0:99999:7:::` (nessuna password, account bloccato) | `root:$6$<salt>$<hash>:0:0:99999:7:::` (password nota impostata, hash sha512crypt) |
| `etc/config/dropbear` (sezione `lan`) | `enable '0'`, `RootLogin '0'`, `RootPasswordAuth '0'`, `AllowLocalForwarding '0'` | `enable '1'`, `RootLogin '1'`, `RootPasswordAuth '1'`, `AllowLocalForwarding '1'` |

Le sezioni `public_lan` e `wan` di dropbear restano invariate (disabilitate). La patch è quindi mirata e minimale: sostituisce la shell di root con una piena, imposta una password di root nota, e abilita SSH root-login sulla sola interfaccia LAN — nient'altro nel filesystem viene toccato.

**Nota metodologica importante:** una prima versione di questa analisi, basata su cartelle di lavoro riutilizzate da un tentativo di rooting precedente in questo stesso repository locale, aveva erroneamente mostrato "0 differenze" tra `2.4.5` e `2.4.5_PATCHED` — perché la cartella usata come riferimento "stock" era in realtà già stata patchata **in-place** dallo script di rooting stesso (`patch_245.sh`), che modifica direttamente `/etc/passwd`, `/etc/shadow` e `/etc/config/dropbear` nella cartella sorgente prima che uno script separato (`rebuild_245.sh`) la ricomprima in un nuovo `.rbi`. Morale: quando una cartella estratta può essere stata usata come sorgente di un rebuild/patch, va sempre ri-estratta da zero dal file `.rbi` originale prima di usarla come termine di paragone "stock" — non fidarsi di cartelle di lavoro riciclate.

## 4. Changelog sequenziale per versione

Vedi [`VERSION-CHANGELOG-IT.md`](VERSION-CHANGELOG-IT.md) per il dettaglio versione-per-versione (non solo aggregato) di cosa cambia tra ogni release consecutiva.
