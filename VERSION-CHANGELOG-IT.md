# Changelog sequenziale AGTEF (VBNT-K / DGA0130TCH)

Cosa cambia, versione dopo versione, tra le 14 immagini `.rbi` uniche trovate in cartella — in ordine di numero di versione (non necessariamente ordine di rilascio reale, vedi l'anomalia `1.1.3` più sotto). Metodologia e dettagli sul formato in [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md); qui il focus è sul delta file-per-file tra ogni coppia consecutiva.

**Nota sul rumore "busybox":** in quasi ogni transizione, decine di file sotto `bin/` (`ash`, `busybox`, `cat`, `grep`, `ls`, ...) risultano "modificati". Sono quasi tutti symlink allo stesso binario BusyBox: quando BusyBox viene ricompilato (anche senza cambiare funzionalità), ogni link mostra contenuto diverso. Questi conteggi sono inclusi nei totali qui sotto ma **non vengono elencati singolarmente** — l'attenzione va ai file con nome esplicito.

**Nota metodologica:** le transizioni che coinvolgono `2.4.1` e `2.4.5` sono state ricalcolate da una ri-estrazione pulita, diretta dai file `.rbi` originali — una prima estrazione locale di queste due versioni era contaminata da un precedente tentativo di rooting (`patch_241.sh`/`patch_245.sh` modificano `/etc/passwd`, `/etc/shadow`, `/etc/config/dropbear` **in-place** nella cartella usata come sorgente). Vedi [`RBI-FORMAT-IT.md` §3.7](RBI-FORMAT-IT.md#37-245-closed-vs-patched) per i dettagli.

---

## 1.0.3 → 1.0.4

**118 rimossi, 340 aggiunti, 1826 modificati.** Aggiornamento minore ma con parecchio ricambio interno (soprattutto in `usr/`, 244 file aggiunti). Nessun cambio di kernel (`3.4.11`) né di config SSH/console (entrambe disabilitate in entrambe le versioni — vedi RBI-FORMAT §3.2/3.3). La struttura di `etc/config/dropbear` passa dalla forma a istanza singola di `1.0.3` allo schema `lan`+`wan` che resterà lo standard fino a `2.0.1_003`.

## 1.0.4 → 1.1.2

**112 rimossi, 371 aggiunti, 1582 modificati.** Compare `mosquitto` (broker MQTT) — prima versione della linea ad averlo. Struttura dropbear invariata (`lan`+`wan`, entrambe disabilitate).

## 1.1.2 → 1.1.3 — ⚠️ ramo laterale, non sequenziale

**691 rimossi, 206 aggiunti, 1989 modificati.** Numeri anomali rispetto al resto della linea: quasi 700 file spariscono (incluso l'intero `etc/boards/`, `mosquitto`) e la struttura dropbear regredisce alla forma a istanza singola di `1.0.3` — con SSH root **abilitato** e console seriale attiva senza login (vedi RBI-FORMAT §3.2/3.3). Prova decisiva che non è una release sequenziale: la transizione successiva (`1.1.3 → 1.2.0_001`) mostra **esattamente i numeri invertiti** (206 rimossi, 691 aggiunti) — cioè `1.2.0_001` riprende da dove si trovava `1.1.2`, ignorando `1.1.3` come se non fosse mai esistita in quella linea. Tutto indica che `AGTEF_1.1.3_CLOSED.rbi` è un'immagine di laboratorio/debug, non una release pubblica TIM.

## 1.1.3 → 1.2.0_001

**206 rimossi, 691 aggiunti, 1991 modificati** — il mirror esatto della transizione precedente (vedi sopra). Di fatto `1.2.0_001` è la naturale prosecuzione di `1.1.2`.

## 1.2.0_001 → 2.0.0

**0 rimossi, 8 aggiunti, 781 modificati.** Aggiornamento contenuto, quasi tutto ricompilazione (781 "modificati" sono in larga parte rumore busybox + poche decine di binari/lib reali). Nessun file rimosso.

## 2.0.0 → 2.0.0_002

**2 rimossi, 0 aggiunti, 16 modificati.** La transizione più piccola e pulita della prima parte della linea — nessun rumore busybox. File toccati: `etc/banner`, `etc/config/version`, `etc/config/web`, `etc/config/wireless`, `etc/sysctl-tch.conf`, `etc/uci-defaults/tch_5000_versioncusto`, `usr/share/transformer/commitapply/uci_web_users.ca`, mapping BBF (`DeviceInfo.map`, `WiFi.Radio.map`), `rpc/env.var.map`, template web (`090_cwmpconf.lp`, `gateway.lp`, `main-min.js`, `cwmpconf-modal.lp`, `ethernet-modal.lp`) e la traduzione `it-it/webui-parental.mo`. Una revisione mirata lato configurazione/UI, non un aggiornamento di sistema.

## 2.0.0_002 → 2.0.1_003

**0 rimossi, 3 aggiunti, 759 modificati.** Simile a `1.2.0_001 → 2.0.0`: quasi tutto ricompilazione, nessuna rimozione.

## 2.0.1_003 → 2.2.0 — salto di generazione kernel

**214 rimossi, 614 aggiunti, 2222 modificati.** **Kernel `3.4.11` → `4.1.38`** — la prima vera transizione di generazione della linea. Compare `lxc` (supporto container). Le board supportate salgono da 2 (`VBNT-K`, `VBNT-S`) a 5 (+ `VANT-W`, `VBNT-F`, `VBNT-H`).

## 2.2.0 → 2.2.1

**6 rimossi, 45 aggiunti, 924 modificati.** Aggiornamento minore sullo stesso kernel (`4.1.38`), stesse 5 board. Compare `AllowLocalForwarding` come opzione nelle sezioni dropbear (tutte impostate a `'0'`).

## 2.2.1 → 2.3.2 — la transizione più grande della linea

**528 rimossi, 1633 aggiunti, 3005 modificati.** **Kernel `4.1.38` → `4.1.52`** e **consolidamento da 5 a 18 board** (`VANT-W`, `VBNT-6/7/9/H/J/K/O/S/V/Y`, `VCNT-A/C/E/H/I/X/Z`) in un'unica immagine — da qui il grosso dei 1223 file aggiunti solo in `usr/` (moduli/pacchetti opkg per-board) e i 159 in `www/`. La console seriale passa da puntare a `/bin/login` a puntare a `/bin/restricted_shell` (resta comunque disabilitata di fabbrica). `RootPasswordAuth` in dropbear passa da stringa (`'on'`) a numerico (`'0'`), segno di un irrigidimento della configurazione di sicurezza.

## 2.3.2 → 2.4.1

**15 rimossi, 104 aggiunti, 1270 modificati.** Stesso kernel (`4.1.52`), stesse 18 board — un aggiornamento incrementale sulla stessa base architetturale, non un altro salto di generazione.

## 2.4.1 → 2.4.5

**0 rimossi, 4 aggiunti, 23 modificati.** Delta piccolo e pulito, nessun rumore busybox (solo `bin/ps` tra i binari). File nuovi: due certificati (`etc/ssl/certs/4ec17c6c.0`, `etc/ssl/certs/TimGroupPrivateRootCA.b64.cer` — TIM aggiunge la propria CA privata), `lib/mount_root/00_overlay_threshold_check` e `usr/sbin/mon_reinit.sh`. Modificati: `etc/banner`, `etc/config/cwmpd`, `etc/config/version`, `etc/init.d/wireless` + `etc/rc.d/S13wireless`, quattro `etc/uci-defaults/tch_*` (rete WAN, rimozioni, versioning, profilo "LTE 2 Box"), `usr/bin/bulkdata`, mapping WiFi/MultiAP/host (`transformer/shared/wifi.lua`, `web/content_helper.lua`, vari `.map` BBF/device2/rpc) e `www/docroot/modals/system-info-modal.lp`. Un aggiornamento mirato su gestione WiFi/MultiAP, CWMP e certificati — non tocca la configurazione di sicurezza (dropbear/passwd/shadow restano quelli di `2.4.1`, entrambi con SSH disabilitato).

## 2.4.5 → 2.4.5_PATCHED — la patch di rooting locale

**0 rimossi, 0 aggiunti, 3 modificati.** L'unica transizione della lista che non è una release TIM, ma la patch prodotta in questo repository (`patch_245.sh`). Cambia solo:

- `etc/passwd`: shell di root da `/bin/restricted_shell` a `/bin/ash` (shell piena)
- `etc/shadow`: da account root bloccato (nessuna password) a una password nota (hash sha512crypt)
- `etc/config/dropbear` (sezione `lan`): SSH root abilitato (`enable`, `RootLogin`, `RootPasswordAuth`, `AllowLocalForwarding` tutti da `'0'` a `'1'`) — `public_lan`/`wan` restano disabilitate

Dettagli completi e verifica del meccanismo di firma in [`RBI-FORMAT-IT.md` §3.7](RBI-FORMAT-IT.md#37-245-closed-vs-patched).
