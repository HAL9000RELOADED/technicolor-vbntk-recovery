# Technicolor VBNT-K (DGA4130) — WireGuard build + BOOTP/TFTP brick recovery

**IT** — Documentazione completa di due fasi collegate su un gateway Technicolor VBNT-K con branding dell'operatore (Technicolor DGA4130, SoC Broadcom BCM63138): (1) compilazione cross toolchain di un kernel module WireGuard/tun custom per abilitare una VPN nativa su un firmware ISP che non la supporta, e (2) il recovery completo del modem dopo che l'installazione del modulo ha mandato in crash il datapath di rete, portando il bootloader CFE in modalità di recovery BOOTP/TFTP permanente. Include la diagnosi via Wireshark, un bug reale scoperto nel codice sorgente di Tftpd64, e lo script Python (scapy) scritto per aggirarlo.

**EN** — Full write-up of two connected phases on an ISP-branded Technicolor VBNT-K gateway (Technicolor DGA4130, Broadcom BCM63138 SoC): (1) cross-toolchain build of a custom WireGuard/tun kernel module to enable a native VPN on an ISP firmware that doesn't support one, and (2) the full recovery of the device after installing that module crashed the network datapath hard enough to push the CFE bootloader into a permanent BOOTP/TFTP recovery loop. Includes the Wireshark-based diagnosis, a real bug found in Tftpd64's own source code, and the Python (scapy) script written to work around it.

## Guide / Guida

- [`GUIDA-IT.md`](GUIDA-IT.md) — guida passo-passo completa in italiano (build + recovery firmware)
- [`GUIDE-EN.md`](GUIDE-EN.md) — full step-by-step guide in English (build + firmware recovery)
- [`GUIDA-ROOT-IT.md`](GUIDA-ROOT-IT.md) — seguito: tentativo di rooting (fallito, patchato) + ripristino configurazione (riuscito)
- [`GUIDE-ROOT-EN.md`](GUIDE-ROOT-EN.md) — follow-on: rooting attempt (failed, patched) + configuration restore (succeeded)
- [`RBI-FORMAT-IT.md`](RBI-FORMAT-IT.md) — analisi del formato `.rbi` (header, cifratura AES, blocco "firma") + confronto tra tutte le 14 versioni disponibili
- [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) — `.rbi` container format analysis (header, AES encryption, "signature" block) + comparison across all 14 available versions
- [`VERSION-CHANGELOG-IT.md`](VERSION-CHANGELOG-IT.md) — changelog sequenziale versione-per-versione (1.0.3 → 2.4.5_PATCHED), incluso il contenuto esatto della patch di rooting
- [`VERSION-CHANGELOG-EN.md`](VERSION-CHANGELOG-EN.md) — sequential version-by-version changelog (1.0.3 → 2.4.5_PATCHED), including the exact content of the rooting patch
- [`MEMORY-ARCHITECTURE-IT.md`](MEMORY-ARCHITECTURE-IT.md) — layout NAND, partizioni MTD, sistema dual-bank, datasheet SoC/NAND
- [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) — NAND layout, MTD partitions, dual-bank system, SoC/NAND datasheet
- [`FIRMWARE-INTERNALS-IT.md`](FIRMWARE-INTERNALS-IT.md) — interni dell'immagine flash: layout kernel/squashfs per versione, header del blob kernel decodificato, generazione di `etc/config/network`, nuovi servizi 2.4.5
- [`FIRMWARE-INTERNALS-EN.md`](FIRMWARE-INTERNALS-EN.md) — flash-image internals: per-version kernel/squashfs layout, decoded kernel-blob header, `etc/config/network` generation, new 2.4.5 services
- [`NETWORK-SECURITY-IT.md`](NETWORK-SECURITY-IT.md) — audit live (sola lettura) di servizi di rete e firewall di un'unità reale: superficie WAN, CWMP/TR-069, gate anti-OTA del firmware community, UPnP, sezioni UCI `wifi_doctor_agent`/`mosquitto`/dropbear
- [`NETWORK-SECURITY-EN.md`](NETWORK-SECURITY-EN.md) — live (read-only) audit of a real unit's network services and firewall: WAN surface, CWMP/TR-069, community-firmware anti-OTA gate, UPnP, `wifi_doctor_agent`/`mosquitto`/dropbear UCI sections
- [`AGTEF-1.1.3-NON-UFFICIALE-IT.md`](AGTEF-1.1.3-NON-UFFICIALE-IT.md) — confronto con la build **non ufficiale** 1.1.3 (root pre-abilitato), derivata da 1.0.3 — non è una release ufficiale
- [`AGTEF-1.1.3-UNOFFICIAL-EN.md`](AGTEF-1.1.3-UNOFFICIAL-EN.md) — comparison with the **unofficial** 1.1.3 build (root pre-enabled), derived from 1.0.3 — not an official release
- [`UART-BOOT-LOG-IT.md`](UART-BOOT-LOG-IT.md) — trascrizione commentata di un boot seriale reale (Boot ROM, CFE, kernel Linux, recovery BOOTP/TFTP) con spiegazione dei checkpoint a 4 caratteri
- [`UART-BOOT-LOG-EN.md`](UART-BOOT-LOG-EN.md) — annotated transcript of a real serial boot (Boot ROM, CFE, Linux kernel, BOOTP/TFTP recovery) with the 4-character checkpoints explained

## Contents / Contenuto

- `scripts/bootp_responder.py` — minimal scapy-based BOOTP responder that correctly fills the `siaddr` (next-server) field Tftpd64 leaves blank
- `scripts/tftpd32.ini.example` — working Tftpd64 configuration used for the TFTP-only recovery server
- `root/afg_inject_*.py` — three AutoFlashGUI-based command-injection rooting attempts (all failed on AGTEF_2.4.5 -- see the root guide)
- `root/import_config.py` — working script for the stock UI's undocumented configuration import endpoint (no root needed)

## Hardware / Software involved

| | |
|---|---|
| Router | TIM - Technicolor VBNT-K (Technicolor DGA4130), Broadcom BCM63138, kernel 4.1.52, OpenWrt-derived ISP firmware ("AGTEF") |
| Build toolchain | WSL2 + Debian, Docker (`ubuntu:18.04` base), OpenWrt 18.06-based buildroot for `brcm63xx-tch` / VBNT-K |
| Recovery tools | [Wireshark](https://www.wireshark.org/), [Tftpd64](https://github.com/PJO2/tftpd64) (portable), Python 3 + [scapy](https://scapy.net/) |
| Rooting attempt tools | [AutoFlashGUI](https://github.com/mswhirl/autoflashgui), `robobrowser` + `werkzeug<1.0` (isolated virtualenv) |

## Key references used

- [hack-technicolor documentation — Recovery](https://hack-technicolor.readthedocs.io/en/stable/Recovery/)
- [hack-technicolor — Resources](https://hack-technicolor.readthedocs.io/en/latest/Resources/)
- [PJO2/tftpd64 — GitHub repository](https://github.com/PJO2/tftpd64) (source of the `siaddr` bug found & worked around here)
- [hack-technicolor/hack-technicolor issue #235 — DGA4130 (VBNT-K) support thread](https://github.com/hack-technicolor/hack-technicolor/issues/235)
- Ansuel's `GUI_ipk` toolchain/buildroot mega.nz links, referenced from the [`Ansuel/GUI_ipk`](https://github.com/Ansuel) GitHub README
- [mswhirl/autoflashgui — GitHub repository](https://github.com/mswhirl/autoflashgui) (rooting-attempt tool)
- [ilpuntotecnico.com forum — Technicolor rooting threads](https://www.ilpuntotecnico.com/forum/index.php/topic,78162.0.html) ([part 2](https://www.ilpuntotecnico.com/forum/index.php/topic,81461.0.html))

## Disclaimer

This documents recovery of the author's own hardware for interoperability/personal-use purposes. No proprietary ISP firmware images are redistributed here — obtain the correct signed firmware for your own device/ISP variant separately (support site, your own prior backup, or the community resources linked above).
