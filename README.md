# Technicolor VBNT-K (DGA4130) — WireGuard build + BOOTP/TFTP brick recovery

**IT** — Documentazione completa di due fasi collegate su un gateway TIM Technicolor VBNT-K (Technicolor DGA4130, SoC Broadcom BCM63138): (1) compilazione cross toolchain di un kernel module WireGuard/tun custom per abilitare una VPN nativa su un firmware ISP che non la supporta, e (2) il recovery completo del modem dopo che l'installazione del modulo ha mandato in crash il datapath di rete, portando il bootloader CFE in modalità di recovery BOOTP/TFTP permanente. Include la diagnosi via Wireshark, un bug reale scoperto nel codice sorgente di Tftpd64, e lo script Python (scapy) scritto per aggirarlo.

**EN** — Full write-up of two connected phases on a TIM-branded Technicolor VBNT-K gateway (Technicolor DGA4130, Broadcom BCM63138 SoC): (1) cross-toolchain build of a custom WireGuard/tun kernel module to enable a native VPN on an ISP firmware that doesn't support one, and (2) the full recovery of the device after installing that module crashed the network datapath hard enough to push the CFE bootloader into a permanent BOOTP/TFTP recovery loop. Includes the Wireshark-based diagnosis, a real bug found in Tftpd64's own source code, and the Python (scapy) script written to work around it.

## Guide / Guida

- [`GUIDA-IT.md`](GUIDA-IT.md) — guida passo-passo completa in italiano
- [`GUIDE-EN.md`](GUIDE-EN.md) — full step-by-step guide in English

## Contents / Contenuto

- `scripts/bootp_responder.py` — minimal scapy-based BOOTP responder that correctly fills the `siaddr` (next-server) field Tftpd64 leaves blank
- `scripts/tftpd32.ini.example` — working Tftpd64 configuration used for the TFTP-only recovery server

## Hardware / Software involved

| | |
|---|---|
| Router | TIM-provided Technicolor VBNT-K (Technicolor DGA4130), Broadcom BCM63138, kernel 4.1.52, OpenWrt-derived TIM firmware ("AGTEF") |
| Build toolchain | WSL2 + Debian, Docker (`ubuntu:18.04` base), OpenWrt 18.06-based buildroot for `brcm63xx-tch` / VBNT-K |
| Recovery tools | [Wireshark](https://www.wireshark.org/), [Tftpd64](https://github.com/PJO2/tftpd64) (portable), Python 3 + [scapy](https://scapy.net/) |

## Key references used

- [hack-technicolor documentation — Recovery](https://hack-technicolor.readthedocs.io/en/stable/Recovery/)
- [hack-technicolor — Resources](https://hack-technicolor.readthedocs.io/en/latest/Resources/)
- [PJO2/tftpd64 — GitHub repository](https://github.com/PJO2/tftpd64) (source of the `siaddr` bug found & worked around here)
- [hack-technicolor/hack-technicolor issue #235 — DGA4130 (VBNT-K) support thread](https://github.com/hack-technicolor/hack-technicolor/issues/235)
- Ansuel's `GUI_ipk` toolchain/buildroot mega.nz links, referenced from the [`Ansuel/GUI_ipk`](https://github.com/Ansuel) GitHub README
- [ilpuntotecnico.com forum — TIM Technicolor rooting threads](https://www.ilpuntotecnico.com/forum/index.php/topic,78162.0.html) ([part 2](https://www.ilpuntotecnico.com/forum/index.php/topic,81461.0.html))

## Disclaimer

This documents recovery of the author's own hardware for interoperability/personal-use purposes. No proprietary ISP firmware images are redistributed here — obtain the correct signed firmware for your own device/ISP variant separately (support site, your own prior backup, or the community resources linked above).
