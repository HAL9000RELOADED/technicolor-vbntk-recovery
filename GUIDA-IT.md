# Guida passo-passo: build WireGuard custom + recovery brick (Technicolor VBNT-K / TIM)

## Condizioni di partenza

- **Router:** Technicolor VBNT-K (identificato via CFE come Technicolor DGA4130), SoC Broadcom BCM63138, kernel Linux 4.1.52, firmware derivato OpenWrt con branding TIM ("AGTEF"), architettura a doppio bank firmware con verifica firma. Il dispositivo era originariamente fornito in comodato da TIM (non all'autore di questa guida) ed è ora di proprietà piena dell'attuale possessore.
- **Obiettivo iniziale:** il firmware TIM stock non include moduli VPN. Obiettivo: compilare e installare `kmod-wireguard` + `kmod-tun` per lo stesso identico kernel del router, per abilitare un tunnel WireGuard nativo (client verso un provider VPN e/o server per accesso remoto "road warrior"), senza sostituire il firmware ISP.
- **Vincoli noti:** TIM non aggiorna più da tempo il firmware di questo specifico modem. Nessun accesso seriale/UART disponibile in partenza — solo rete (SSH root ottenuto in precedenza tramite procedura di rooting separata) e porta USB del router per storage.

---

## Parte A — Ambiente di build (WSL2 + Docker + buildroot OpenWrt 18.06)

1. **WSL2 + Debian**: `wsl --update`, installazione/verifica distro Debian, `wsl --set-version Debian 2`. Richiede virtualizzazione abilitata sull'host Windows.
2. **Docker dentro WSL2 Debian**: container `tch-build` basato su `ubuntu:18.04` — versione datata necessaria per compatibilità ABI con Python2 e la toolchain dell'epoca.
3. **Toolchain**: `toolchain-arm_cortex-a9+neon_gcc-4.8-linaro_glibc_eabi.tar` (fonte: link mega.nz nel README del repo GitHub `Ansuel/GUI_ipk`). Estratto in `~/build/toolchain/`. Prefisso binari: `arm-openwrt-linux-` (non `-gnueabi-`).
4. **Buildroot**: `openwrt_18.x_tch_buildroot_based_custom.tar.xz` (stessa fonte). È un buildroot OpenWrt 18.06 completo con `target/linux/brcm63xx-tch/` e sottotarget VBNTK/VANTW/VANTF/VBNTO/VBNTS — il nostro è **VBNTK**.
5. **Kernel source**: l'hash del buildroot per `linux-4.1.52.tar.xz` è rotto (nessuna voce `LINUX_KERNEL_HASH-4.1.52`). Scaricato manualmente da `cdn.kernel.org` e posizionato in `dl/`.
6. **mklibs**: mirror `sources.lede-project.org` morto. Recuperato `mklibs_0.1.35.tar.gz` dall'archivio snapshot Debian (con verifica SHA256).
7. **Tool mancanti**: `help2man` e `makeinfo` sotto `tools/missing-macros/src/bin/` assenti dall'archivio del buildroot — recuperati dal branch `openwrt-18.06` del repo ufficiale `openwrt/openwrt`, resi eseguibili.
8. **mkhash**: wrapper mancante — compilato direttamente da `scripts/mkhash.c` con `gcc -O2`.
9. **Symlink di patch rotti**: tutte le patch sotto `target/linux/brcm63xx-tch/patches-4.1/*.patch` del sottotarget VBNTK erano symlink assoluti rotti (puntavano a un percorso esistente solo sulla macchina originale del packager). La patch critica (SDK Broadcom, ~24.7MB) è stata recuperata da una copia reale presente nel sottotarget **VANTW** (stessa versione SDK, compatibile). La patch riporta "fallita" a livello globale per ~57 hunk relativi ad altri vendor/dts non pertinenti (dovuti al salto di versione kernel), ma il contenuto Broadcom realmente necessario si applica correttamente — verificato con grep/find, poi confermato al buildroot con la tecnica dello "stamp file".
10. **Seconda patch rotta**: un hunk isolato (relativo a `Kconfig.bcm`) estratto ed applicato manualmente con `patch -p1 --fuzz=5`, per risolvere un errore di file mancante nella catena Kconfig.
11. **Symlink `bcmdrivers`** (fix critico, scoperto tardi): creare il link
    `build_dir/target-arm-openwrt-linux_glibc/bcmdrivers` → sorgente driver vendor Broadcom reale dentro l'estrazione `extern/`. Non persiste tra un `make clean`/`dirclean` e l'altro — va ricreato, o agganciato a un hook `Kernel/Prepare` nel Makefile del target. Senza questo, `make modules` fallisce.
12. **Sorgente WireGuard**: `git.zx2c4.com` irraggiungibile dal container di build — usato il mirror CDN OpenWrt (`sources.cdn.openwrt.org`), verificato SHA256 contro `PKG_HASH`.
13. **Config toolchain nel buildroot**: `CONFIG_EXTERNAL_TOOLCHAIN=y`, percorso e prefisso toolchain impostati di conseguenza.
14. **Kconfig del kernel** (`target/linux/brcm63xx-tch/config-default`): oltre 60 iterazioni manuali di prompt `(NEW)`, poi collassate con un singolo passaggio `make olddefconfig` (scorciatoia enorme). Fix critico: **`CONFIG_PREEMPT=y`** (vedi bug vermagic sotto), più simboli RCU di conseguenza coerenti (`CONFIG_PREEMPT_RCU=y`, `CONFIG_PREEMPT_COUNT=y`, ecc. — abilitare `PREEMPT` cambia l'implementazione RCU e il default del kernel forzerebbe `CONFIG_TINY_RCU=y` in conflitto). Altri valori non di default impostati sui propri valori di board (letti dalla config kernel 3.4 originale del VBNTK): `CONFIG_ROOT_FLASHFS="ro noinitrd"`, `CONFIG_BCM_CPU_ARCH_NAME="arma9"`, `CONFIG_BCM_TCH_BL=y`.
15. **Script di compilazione** (`target/linux/compile`, `package/kernel/linux/compile`, `package/network/services/wireguard/compile`, tutti con `V=s -j1` e `FORCE_UNSAFE_CONFIGURE=1`), lanciati in background dentro il container con `docker exec -d ... > step.log 2>&1` (il pattern `nohup & ` tramite `wsl.exe` non si affidabilizza in questo setup — verificare l'avanzamento contando le righe del log nel tempo, non con `pgrep`, perché il PID 1 del container non fa reap degli zombie).

### Bug vermagic (perché `CONFIG_PREEMPT` è fondamentale)

Prima build: tutte le fasi completate con successo, pacchetti installati sul router via `opkg`, ma `insmod` falliva con:

```
wireguard: version magic '4.1.52 SMP mod_unload ARMv7 ' should be '4.1.52 SMP preempt mod_unload ARMv7 '
```

Il firmware del router ha la preemption completa del kernel abilitata; la nostra config-default no (il modpost di Linux aggiunge "preempt" al vermagic solo con `CONFIG_PREEMPT` pieno, non con `PREEMPT_VOLUNTARY`/`PREEMPT_NONE`). Corretto come sopra, ricompilato, verificato con `strings wireguard.ko | grep vermagic` → risultato combaciante col router.

---

## Parte B — L'incidente: il router si blocca

Con la build corretta (vermagic combaciante) pronta, durante l'installazione via `opkg install kmod-tun` sul router, la connessione SSH è caduta nello stesso istante in cui il pacchetto veniva installato. Diagnostica lato host: la porta Ethernet è passata a **no-carrier**, nessuna rotta verso l'IP LAN del router, nessun ripristino nemmeno dopo diversi minuti di attesa (nessun riavvio da watchdog osservato in quella finestra).

**Causa sospetta:** il BCM63138 ha un acceleratore hardware del flusso pacchetti (architettura "pktrunner"/runner di Broadcom) quasi certamente attivo nel firmware stock, anche se non visibile/abilitato nella nostra config kernel personalizzata. Il caricamento di un modulo netdev nuovo/esterno (`tun.ko`, compilato completamente fuori dal toolchain Broadcom SDK, sebbene compatibile a livello di vermagic) ha probabilmente mandato in crash o bloccato il datapath di forwarding hardware, abbattendo l'intera porta LAN a livello fisico — non solo la rete software.

**Lezione:** caricare moduli kernel custom che registrano nuovi netdev (tun/tap, interfacce VPN) su schede Broadcom BCM63xx/PON con acceleratore hardware attivo è ad alto rischio — l'acceleratore potrebbe non gestire correttamente netdev che non conosce.

---

## Parte C — Diagnosi nella sessione di recovery

1. **Sintomo iniziale riportato**: nessun segno di vita dopo spegni/accendi e pressione del tasto reset — potenzialmente un guasto hardware.
2. **Checklist prime verifiche**: alimentatore verificato buono con un multimetro/alimentatore alternativo; il case si scaldava (segno di corrente in ingresso); reset tenuto premuto durante l'accensione (non a router già acceso).
3. **Osservazione chiave**: collegando un PC via cavo Ethernet direttamente alla LAN del router, l'interfaccia di rete del PC riceveva un indirizzo APIPA (`169.254.x.x`) — segno che il router non rispondeva a nessuna richiesta DHCP, ma il link fisico a tratti si alzava per ~40 secondi prima che il router si riavviasse da solo, in un ciclo continuo. Un ping ripetuto verso l'IP LAN atteso confermava questa intermittenza:

   ```
   Esecuzione di Ping 192.168.1.1 con 32 byte di dati:
   Risposta da 192.168.1.1: byte=32 durata=18ms TTL=64
   Richiesta scaduta.
   Richiesta scaduta.
   Risposta da 192.168.1.1: byte=32 durata=281ms TTL=64

   Statistiche Ping per 192.168.1.1:
       Pacchetti: Trasmessi = 4, Ricevuti = 2,
       Persi = 2 (50% persi)
   ```

4. **Cattura Wireshark** sul collegamento diretto PC↔router: pacchetti `BOOTP`/`Boot Request` inviati **dal router stesso** (non richiesti dal PC), ripetuti ogni ~1 secondo, contenenti nel campo "Boot file name" la stringa del modello (`VBNT-K`) e un blob vendor-specific (opzione DHCP 43) con seriale/informazioni di board. Decodifica del pacchetto in Wireshark:

   ```
   Ethernet II, Src: TechnicolorD_xx:xx:xx, Dst: Broadcast (ff:ff:ff:ff:ff:ff)
   Internet Protocol, Src: 0.0.0.0, Dst: 255.255.255.255
   User Datagram Protocol, Src Port: 68, Dst Port: 67
   Dynamic Host Configuration Protocol
       Message type: Boot Request (1)
       Client IP address: 0.0.0.0
       Your (client) IP address: 0.0.0.0
       Client MAC address: TechnicolorD_xx:xx:xx
       Boot file name: VBNT-K\0...
       Magic cookie: DHCP
       Option: (43) Vendor-Specific Information
           Length: 55
   ```
5. **Riscontro con la documentazione hack-technicolor**: questo pattern corrisponde esattamente alla **modalità di recovery BOOTP/TFTP** del bootloader CFE — quando il firmware fallisce il caricamento 3 volte su ENTRAMBI i bank, il bootloader entra in questa modalità e trasmette in broadcast aspettando un server DHCP+TFTP che gli fornisca un'immagine firmware valida.

---

## Parte D — Tentativo di recovery

### Materiali già disponibili

Da un lavoro precedente di rooting dello stesso dispositivo, erano già disponibili localmente: più versioni del firmware ufficiale TIM (`AGTEF_x.y.z_CLOSED.rbi`), lo strumento community `autoflashgui` (usato in passato per il rooting via exploit DDNS su router **già avviato** — non applicabile a un bootloader fermo in recovery), PuTTY/WinSCP, e note personali sulla procedura di rooting.

> Nota: la procedura di rooting via `autoflashgui` richiede un router **acceso e raggiungibile** (accesso web admin/admin) — non si applica a questo scenario, dove il router è fermo nel bootloader prima che qualsiasi sistema operativo carichi.

### Tentativo 1 — Tftpd64 con DHCP integrato

1. Scaricato **Tftpd64** (edizione portable, dalla release ufficiale GitHub `PJO2/tftpd64`) — nessuna installazione, solo estrazione.
2. Configurato `tftpd32.ini`: solo servizi TFTP Server + DHCP Server abilitati, cartella base TFTP puntata alla cartella coi firmware, pool DHCP `10.0.0.100`–`10.0.0.119`, subnet `255.255.255.0`, gateway `10.0.0.99`, boot filename impostato sul file firmware desiderato.
3. **Problema riscontrato**: la scheda di rete del PC stesso (in APIPA) ha intercettato e ottenuto un lease dal nostro stesso server DHCP appena avviato, cambiando il proprio indirizzo e disallineando il binding di Tftpd64 sull'IP configurato in precedenza. Log di Tftpd64 (`tftpd64.log`):

   ```
   Rcvd DHCP Discover Msg for IP 0.0.0.0, Mac D8:BB:C1:xx:xx:xx
   DHCP: proposed address 10.0.0.100
   Rcvd DHCP Rqst Msg for IP 0.0.0.0, Mac D8:BB:C1:xx:xx:xx
   Previously allocated address 10.0.0.100 acked
   Message received on an unbound interface (IP 10.0.0.100)
   Message received on an unbound interface (IP 10.0.0.100)
   Message received on an unbound interface (IP 10.0.0.100)
   [... ripetuto ogni ~1s ...]
   ```

4. **Fix**: impostato un **IP statico** sulla scheda Ethernet del PC (`10.0.0.99/24` — richiede privilegi di amministratore, non disponibili nella sessione automatizzata: eseguito manualmente dall'utente), e ribinding esplicito di Tftpd64 su quell'indirizzo stabile.
5. Il router ha correttamente ottenuto un lease BOOTP (`10.0.0.101`), confermato nel log e persistito nell'ini di Tftpd64 — ma non progrediva mai a una richiesta TFTP effettiva, ripetendo il ciclo BOOTP ogni ~30 secondi indefinitamente:

   ```
   Rcvd BootP Msg for IP 0.0.0.0, Mac 10:13:31:xx:xx:xx
   DHCP: proposed address 10.0.0.101
   [... si ripete ogni ~30s, nessuna richiesta TFTP mai arrivata ...]
   ```

### La causa reale: un bug nel codice sorgente di Tftpd64

Analizzando live il traffico di rete (cattura con Python/`scapy`, dato che Wireshark non era disponibile su questa macchina ma il driver **Npcap** sì) è emerso che la risposta BOOTP inviata dal server aveva il campo **`siaddr`** ("next server", cioè l'indirizzo del server TFTP da cui scaricare) sempre a `0.0.0.0` — nonostante il nome del file fosse corretto. Senza questo campo, il bootloader CFE non sa a chi richiedere il file via TFTP:

```
CLIENT->SRV src=0.0.0.0 dst=255.255.255.255 yiaddr=0.0.0.0 siaddr=0.0.0.0 file=b'VBNT-K\x00...'
SRV->CLIENT src=10.0.0.99 dst=255.255.255.255 yiaddr=10.0.0.101 siaddr=0.0.0.0 file=b'AGTEF_2.4.5_CLOSED.rbi'
                                                                        ^^^^^^^^^^^^ dovrebbe essere 10.0.0.99, non 0.0.0.0
```

Analizzando il codice sorgente pubblico di Tftpd64 (`PJO2/tftpd64` su GitHub, file `src/_services/bootpd.c`): il campo `siaddr` viene riempito automaticamente solo tramite un'opzione DHCP personalizzata (opzione 66) che **non risulta mai effettivamente letta dal file ini** in nessun punto del codice (funzionalità definita nei header ma mai cablata all'interfaccia/lettura ini — commenti nel codice stesso confermano un tentativo incompiuto: *"TODO: add optional siaaddr"*, *"Failed: couldn't add box"*). Il fallback automatico (ricerca dell'interfaccia di rete più vicina) è protetto da un controllo che verifica il valore sentinella sbagliato (`INADDR_NONE` invece di zero), quindi non scatta mai nella pratica — estratto reale da `bootpd.c` (il bug è nell'ultimo `if`):

```c
pNearest = FindNearestServerAddress(&pDhcpPkt->yiaddr, &in_Aux, TRUE);
if (!pNearest)
    pNearest = &(receivingAddress->sin_addr);

// HACK -- If we are the bootp server, we are also the tftpserver
for (int i = 0; i < 10; i++) {
    if (sParamDHCP.t[i].nAddOption == 66) {
        pDhcpPkt->siaddr.S_un.S_addr = inet_addr(sParamDHCP.t[i].szAddOption);
    }
}
if (pDhcpPkt->siaddr.S_un.S_addr == INADDR_NONE) {   // <-- bug: confronta con INADDR_NONE (0xFFFFFFFF)
    if (sSettings.uServices & TFTPD32_TFTP_SERVER)   //     invece di 0 (non impostato) -> non scatta mai
        pDhcpPkt->siaddr = *pNearest;
    pDhcpPkt->siaddr = *pNearest;
}
```

### Soluzione: responder BOOTP personalizzato

1. Lasciato **Tftpd64 attivo in sola modalità TFTP** (disabilitato il suo server DHCP, che comunque non risolveva il problema del `siaddr`).
2. Scritto un piccolo script Python (`scripts/bootp_responder.py`, incluso in questo repository) che usa **scapy** per:
   - ascoltare le richieste `BOOTREQUEST` broadcast provenienti dal MAC del router,
   - costruire e inviare una risposta `BOOTREPLY` corretta, con `siaddr` impostato esplicitamente all'indirizzo del server TFTP, `yiaddr` con l'IP da assegnare, e il nome del file firmware.
3. **Primo bug nello script stesso**: la prima versione usava `scapy.send()` (livello 3, instradamento automatico tramite tabella di routing di scapy) — su una macchina Windows con molte interfacce virtuali (Hyper-V, VPN, ecc.) la risposta veniva instradata sull'interfaccia sbagliata e non arrivava mai fisicamente al router:

   ```
   [03:20:45] Got BOOTREQUEST xid=0x316674ea from 10:13:31:xx:xx:xx, sending reply...
   WARNING: MAC address to reach destination not found. Using broadcast.
     -> reply sent: yiaddr=10.0.0.101 siaddr=10.0.0.99 file=b'AGTEF_2.4.5_CLOSED.rbi'
   ```

   (la risposta veniva "inviata" secondo lo script, ma il router continuava a ritrasmettere ogni secondo — segno che non arrivava mai davvero). **Fix**: sostituito con `scapy.sendp()` (livello 2, rispetta esplicitamente l'interfaccia di rete specificata).
4. Con questa correzione, il router ha finalmente inviato una vera richiesta TFTP (`RRQ`) al server corretto, e Tftpd64 ha servito il file firmware — **32.9 MB trasferiti in 18 secondi, zero blocchi ritrasmessi**:

   ```
   Connection received from 10.0.0.101 on port 4594
   Read request for file <AGTEF_2.4.5_CLOSED.rbi>. Mode octet
   Using local port 56033
   <AGTEF_2.4.5_CLOSED.rbi>: sent 64212 blks, 32876123 bytes in 18 s. 0 blk resent
   ```

5. Il router ha scritto il firmware in flash e si è riavviato, tornando operativo normalmente sul suo IP LAN standard, con il proprio server DHCP di nuovo funzionante (verificato con un ping stabile, 0% pacchetti persi, e con la scheda di rete del PC che otteneva un normale indirizzo DHCP dal router stesso).

---

## Strumenti e riferimenti usati

- [Documentazione hack-technicolor — Recovery](https://hack-technicolor.readthedocs.io/en/stable/Recovery/)
- [Repository GitHub PJO2/tftpd64](https://github.com/PJO2/tftpd64) (fonte del bug `siaddr` scoperto e aggirato)
- [Issue #235 hack-technicolor — supporto DGA4130/VBNT-K](https://github.com/hack-technicolor/hack-technicolor/issues/235)
- Link toolchain/buildroot di Ansuel, referenziati dal README del repo GitHub `Ansuel/GUI_ipk`
- Thread del forum ilpuntotecnico.com sul rooting dei Technicolor TIM
- Wireshark, Npcap, Python 3 + scapy, Tftpd64

## Nota legale

Nessuna immagine firmware proprietaria dell'ISP viene ridistribuita in questo repository — procurati il firmware firmato corretto per il tuo specifico dispositivo/variante separatamente (sito di supporto dell'operatore, un tuo backup precedente, o le risorse community linkate sopra).
