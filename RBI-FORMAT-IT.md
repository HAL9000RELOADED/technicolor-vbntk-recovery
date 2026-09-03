# Formato `.rbi` AGTEF: header, cifratura e "firma" — cosa cambia tra le versioni

Analisi del contenitore firmware `.rbi` usato dal Technicolor VBNT-K (`AGTEF_x.y.z_CLOSED.rbi`), del meccanismo di cifratura/"firma" interno, e confronto reale tra le versioni `1.0.3` e `2.4.5` (originale vs patchata).

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

## 5. Costruzione (encrypt) di un .rbi valido — verificato su hardware reale

Le sezioni precedenti analizzano il formato in lettura. Qui il percorso inverso:
costruire da zero un `.rbi` valido a partire da un'immagine raw (kernel+squashfs,
80MB) patchata, usando solo l'OSCK pubblica (§2.1) — **senza alcuna chiave
privata Technicolor**. Confermato funzionante sia in round-trip locale
(decrypt→encrypt→decrypt) sia in un **flash reale** via recovery BOOTP/TFTP su
un VBNT-K fisico (vedi §5.3).

### 5.1 Algoritmo di costruzione

Riassemblaggio dall'interno verso l'esterno (inverso esatto di §2):

```
b0  = 0xB0 + "MUTE" + flag(0x00) + payload_raw
b4  = 0xB4 + "MUTE" + flag(0x00) + len(b0)_be32 + zlib.compress(b0)
b8  = 0xB8 + "MUTE" + flag(0x00) + len(b4)_be32 + SHA256(b4)
combined = b8 + b4     # concatenazione PIATTA, non annidamento — b8 e' solo
                        # header+hash, il chunk b4 vero segue subito dopo nello
                        # stream decifrato (§2.2 lo chiarisce, ma e' facile
                        # implementarlo per errore come "cifra solo b8")
key2, iv1, iv2 = random(32), random(16), random(16)
enc_key2  = AES256-CBC(OSCK, iv1).encrypt(pkcs7_pad(key2))      # sempre 48 byte
ciphertext = AES256-CBC(key2, iv2).encrypt(pkcs7_pad(combined))
b7 = 0xB7 + "MUTE" + flag(0x00) + len(ciphertext)_be32 + iv1 + enc_key2 + iv2 + ciphertext

rbi_file = header_originale[0:data_offset] + b7   # header riusato verbatim
                                                    # da un .rbi originale dello
                                                    # stesso modello, tranne il
                                                    # campo data_size (0x2C)
                                                    # aggiornato a len(b7)
```

Implementazione di riferimento (Python, pycryptodome): `encrypt_rbi.py`, non
ancora pubblicato in questo repo — non esitate ad aprire una issue se serve
il sorgente completo.

### 5.2 Invariante non documentata: byte 0x2F / 0x178+offset_header

Verificato sui 12 `.rbi` esaminati in questa fase (le 8 versioni principali
1.0.3→2.4.5 più i 3 backup intermedi della catena hdrfix/b7fix/b8fix di
`AGTEF_2.4.5_PATCHED.rbi` più una copia duplicata di `VBNT-K.rbi` — un
sottoinsieme dei 14 file unici del confronto in §3): il campo `data_size`
(0x2C, 4 byte) e il campo `counter` del chunk 0xB7 (i primi 4 byte subito
dopo `flag`, a offset `data_offset + 6`) hanno una relazione fissa fra i
rispettivi ultimi byte:

```
byte_finale(data_size) == byte_finale(counter_0xB7) | 0x0A
```

Es. su un file autentico: `data_size` finisce in `...4A`, il counter del
chunk 0xB7 finisce in `...40` → `0x40 | 0x0A = 0x4A` ✓. Una costruzione
"pulita" che calcola i due campi indipendentemente (come la formula in §5.1,
senza questo fix) **non** soddisfa l'invariante — verificato che il file
risultante viene comunque accettato e decifrato correttamente dal tool di
lettura (l'invariante non è controllata lì), ma non è chiaro se sia
controllata altrove (bootloader?), quindi lo script di riferimento la
applica comunque per sicurezza, forzando `data_size`:

```python
full[0x2F] = full[offset_counter_0xB7_ultimo_byte] | 0x0A
```

Origine sospetta: non un vero campo di sicurezza, più probabilmente un
artefatto di come il tool originale Technicolor deriva entrambi i campi da
un unico valore interno con una trasformazione di maschera — non
approfondito oltre.

### 5.3 Verifica su hardware reale (2026-08-23)

Costruito un `.rbi` con questo schema a partire da `AGTEF_2.2.1_CLOSED.rbi`
("221") patchato con gli stessi 3 file di §3.7 (dropbear/passwd/shadow),
servito via recovery BOOTP/TFTP (procedura in `GUIDA-IT.md`) a un VBNT-K
fisico. Risultato:

- Router entrato in BOOT-P mode via trigger seriale automatico su
  `Market ID`.
- **Trasferimento TFTP completato con successo per due volte di seguito**
  (log: `TFTP started` → `TFTP finished`, nessun errore CFE), il router ha
  scritto e riavviato da Bank 1 entrambe le volte senza errori.
- Boot Linux completo e pulito con l'immagine appena scritta: nessun kernel
  panic, WiFi (Quantenna) operativo, nessun loop di riavvio. Verificato con
  hash SHA-256 che il file effettivamente trasferito combacia byte-per-byte
  con il `.rbi` costruito localmente.

Questo è, ad oggi, la **prima conferma su hardware reale** (non solo via
round-trip del tool di lettura) che il CFE di questo bootloader accetta un
`.rbi` costruito interamente da zero con la sola OSCK pubblica, senza alcuna
firma privata Technicolor — coerente con la conclusione di §2.2 ("non è
autenticazione, è offuscamento").

**Nota per chi ripete il test — timeout CFE -21**: nei primi tentativi (due
sessioni diverse, file diversi) il trasferimento falliva sempre con
`Loading failed.: CFE error -21` dopo un tempo costante (~8.5s,
indipendente dalla dimensione del file). Verificato nel sorgente Broadcom
originale (`cfe_error.h`, repo `Noltari/cfe_bcm63xx`): **-21 =
`CFE_ERR_TIMEOUT`**, non un rifiuto di validazione. Causa reale: **Windows
Firewall blocca di default il traffico UDP in ingresso sulla porta 69** per
processi senza una regola esplicita (il traffico BOOTP passa comunque perché
cattura/invia a livello driver via scapy/Npcap, bypassando il firewall — il
TFTP invece usa un socket UDP standard, bloccato). Fix:

```powershell
New-NetFirewallRule -DisplayName "TFTP recovery" -Direction Inbound -Protocol UDP -LocalPort 69 -Action Allow -Profile Private
```

**Problema aperto, non ancora risolto**: dopo il flash riuscito (confermato
dal log seriale e dall'hash), il login SSH `root`/`root` sulla nuova
immagine **continua a fallire** ("Permission denied (password)"), nonostante
l'hash in `/etc/shadow` sia verificato correttamente in locale prima del
flash. Contestualmente, la webUI mostra un sintomo distinto ma forse
correlato — vedi **[`WEBUI-LUA-ISSUE-IT.md`](WEBUI-LUA-ISSUE-IT.md)** per
l'analisi completa (motore Lua attivo ma template renderizzati come testo
grezzo invece che eseguiti). Ipotesi principale sulla parte SSH, non ancora
verificata: questi sistemi montano lo squashfs in sola lettura con un
**overlay scrivibile persistente** (altra partizione, non toccata dal flash
BOOTP/TFTP, che copre solo kernel+rootfs — vedi
[`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md)) per `/etc` — se una
versione precedente dei file (da un tentativo di rooting precedente su
questo stesso router) è già stata scritta nell'overlay, questa oscura le
modifiche fatte nello squashfs indipendentemente da cosa contenga l'immagine
appena flashata. Da verificare con un vero factory-reset (7 secondi sul
tasto reset **a router già acceso**, procedura diversa dal
power-on-con-reset-premuto usato per la recovery BOOTP) per svuotare
l'overlay — **primo tentativo (2026-08-23) inconcludente**: lo stesso
identico hard-reset era già stato provato in passato su questo router per un
problema diverso (§10.1 della documentazione di recovery locale, non ancora
pubblicata qui) senza risolverlo, quindi non è garantito che svuoti davvero
`rootfs_data` su questo hardware.
