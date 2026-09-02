# Step-by-step guide: custom WireGuard build + brick recovery (Technicolor VBNT-K)

## Starting conditions

- **Router:** Technicolor VBNT-K (identifies itself via CFE as Technicolor DGA4130), Broadcom BCM63138 SoC, Linux kernel 4.1.52, OpenWrt-derived firmware with ISP branding ("AGTEF"), dual-bank signed firmware architecture. The device was originally provided on loan by the ISP (to a previous holder, not this guide's author) and is now fully owned by its current holder.
- **Original goal:** stock ISP firmware ships no VPN kernel modules. Goal: cross-compile and install `kmod-wireguard` + `kmod-tun` matching the router's exact kernel, to enable a native WireGuard tunnel (client to a VPN provider and/or "road warrior" remote-access server), without replacing the ISP firmware.
- **Known constraints:** the ISP no longer pushes firmware updates to this specific modem. No serial/UART access available going in — network only (root SSH previously obtained through a separate rooting procedure) and the router's USB port for storage.

---

## Part A — Build environment (WSL2 + Docker + OpenWrt 18.06 buildroot)

1. **WSL2 + Debian**: `wsl --update`, install/verify a Debian distro, `wsl --set-version Debian 2`. Requires virtualization enabled on the Windows host.
2. **Docker inside WSL2 Debian**: `tch-build` container based on `ubuntu:18.04` — this old base is required for Python2 + period-correct toolchain ABI compatibility.
3. **Toolchain**: `toolchain-arm_cortex-a9+neon_gcc-4.8-linaro_glibc_eabi.tar` (source: mega.nz link in the `Ansuel/GUI_ipk` GitHub repo README). Extracted to `~/build/toolchain/`. Binary prefix: `arm-openwrt-linux-` (not `-gnueabi-`).
4. **Buildroot**: `openwrt_18.x_tch_buildroot_based_custom.tar.xz` (same source). A full OpenWrt 18.06-branch buildroot with `target/linux/brcm63xx-tch/` containing VBNTK/VANTW/VANTF/VBNTO/VBNTS subtargets — ours is **VBNTK**.
5. **Kernel source**: the buildroot's hash-verified download for `linux-4.1.52.tar.xz` is broken (no matching hash entry). Downloaded manually from `cdn.kernel.org` and placed in `dl/`.
6. **mklibs**: the `sources.lede-project.org` mirror is dead. Fetched `mklibs_0.1.35.tar.gz` from the Debian snapshot archive (SHA256-verified).
7. **Missing tools**: `help2man` and `makeinfo` under `tools/missing-macros/src/bin/` are absent from the buildroot archive — recovered from the `openwrt-18.06` branch of the official `openwrt/openwrt` repo, made executable.
8. **mkhash**: missing wrapper — compiled directly from `scripts/mkhash.c` with `gcc -O2`.
9. **Broken patch symlinks**: every patch under `target/linux/brcm63xx-tch/patches-4.1/*.patch` in the VBNTK subtarget was a broken absolute symlink (pointing to a path that only existed on the original packager's machine). The critical Broadcom SDK patch (~24.7MB) was recovered from a real copy under the **VANTW** subtarget (same SDK version, compatible). The patch reports an overall failure due to ~57 unrelated hunks (other vendor/dts files, from the kernel version gap), but the actually-needed Broadcom content applies cleanly — verified via grep/find, then confirmed to the buildroot using the "stamp file" trick.
10. **A second broken patch**: one isolated hunk (Kconfig.bcm-related) extracted and applied manually with `patch -p1 --fuzz=5`, fixing a missing-file error in the Kconfig chain.
11. **`bcmdrivers` symlink** (critical, late-discovered fix): create a link from the build tree to the real Broadcom vendor driver source inside the buildroot's `extern/` extraction. Does not persist across `make clean`/`dirclean` — must be recreated, or hooked via a `Kernel/Prepare` step in the target Makefile. Without it, `make modules` fails.
12. **WireGuard source**: `git.zx2c4.com` unreachable from the build container — used the OpenWrt CDN mirror instead (`sources.cdn.openwrt.org`), SHA256-verified against `PKG_HASH`.
13. **Toolchain wiring**: `CONFIG_EXTERNAL_TOOLCHAIN=y` with the toolchain path/prefix set accordingly.
14. **Kernel Kconfig** (`target/linux/brcm63xx-tch/config-default`): 60+ manual `(NEW)` prompt iterations, later collapsed into a single `make olddefconfig` pass (huge shortcut). Critical fix: **`CONFIG_PREEMPT=y`** (see vermagic bug below), plus consistent RCU symbols (`CONFIG_PREEMPT_RCU=y`, `CONFIG_PREEMPT_COUNT=y`, etc. — enabling full preemption changes the RCU implementation, and the generic kernel default would otherwise force a conflicting `CONFIG_TINY_RCU=y`). Other non-default board-specific values (read from the VBNTK's own kernel-3.4 config): `CONFIG_ROOT_FLASHFS="ro noinitrd"`, `CONFIG_BCM_CPU_ARCH_NAME="arma9"`, `CONFIG_BCM_TCH_BL=y`.
15. **Build steps** (`target/linux/compile`, `package/kernel/linux/compile`, `package/network/services/wireguard/compile`, each with `V=s -j1` and `FORCE_UNSAFE_CONFIGURE=1`), launched in the background inside the container via `docker exec -d ... > step.log 2>&1` (a plain `nohup &` through `wsl.exe` does not reliably background in this setup — track progress via log line-count growth over time, not `pgrep`, since the container's PID 1 doesn't reap zombie processes).

### The vermagic mismatch bug (why `CONFIG_PREEMPT` matters)

First build: every stage completed successfully, packages installed on the router via `opkg`, but `insmod` failed with:

```
wireguard: version magic '4.1.52 SMP mod_unload ARMv7 ' should be '4.1.52 SMP preempt mod_unload ARMv7 '
```

The router's actual firmware kernel has full preemption enabled; our config-default didn't (Linux's modpost only appends "preempt" to the vermagic string for full `CONFIG_PREEMPT`, not `PREEMPT_VOLUNTARY`/`PREEMPT_NONE`). Fixed as above, rebuilt, verified with `strings wireguard.ko | grep vermagic` → now matching the router exactly.

---

## Part B — The incident: the router goes down

With the corrected (vermagic-matching) build ready, running `opkg install kmod-tun` on the router caused the SSH connection to drop at the exact moment the package was installed. Host-side diagnostics: the Ethernet port went to **no-carrier**, no route to the router's LAN IP at all, no recovery even after several minutes of waiting (no watchdog reboot observed in that window).

**Suspected cause:** the BCM63138 has a hardware packet-flow accelerator (Broadcom's "pktrunner"/runner architecture) almost certainly active in the stock firmware, even though not visible/enabled in our custom kernel config. Loading a new/foreign netdev-registering module (`tun.ko`, built entirely outside Broadcom's own SDK toolchain, though vermagic-compatible) likely crashed or wedged the hardware forwarding datapath hard enough to take the entire LAN port down at the link layer — not just software networking.

**Lesson:** loading custom-built kernel modules that register new netdevs (tun/tap, VPN interfaces) on Broadcom BCM63xx/PON boards with an active hardware flow accelerator is high risk — the accelerator may not gracefully handle netdevs it doesn't know about.

---

## Part C — Diagnosis in the recovery session

1. **Initial reported symptom**: no signs of life at all after a power cycle and a reset-button press — potentially a hardware fault.
2. **First checks**: power supply verified good (multimeter / alternate adapter); the case was warm (sign of power actually reaching the board); reset held down *during* power-on (not on an already-running router).
3. **Key observation**: connecting a PC directly to the router's LAN port via Ethernet, the PC's network interface received an APIPA address (`169.254.x.x`) — meaning the router wasn't answering any DHCP request, but the physical link came up intermittently for ~40 seconds before the router rebooted itself, in a continuous cycle. A repeated ping to the expected LAN IP confirmed the intermittency:

   ```
   Pinging 192.168.1.1 with 32 bytes of data:
   Reply from 192.168.1.1: bytes=32 time=18ms TTL=64
   Request timed out.
   Request timed out.
   Reply from 192.168.1.1: bytes=32 time=281ms TTL=64

   Ping statistics for 192.168.1.1:
       Packets: Sent = 4, Received = 2,
       Lost = 2 (50% loss)
   ```

4. **Wireshark capture** on the direct PC↔router link: `BOOTP`/`Boot Request` packets sent **by the router itself** (not requested by the PC), repeating roughly once per second, carrying the board model string (`VBNT-K`) in the "Boot file name" field and a vendor-specific blob (DHCP option 43) with serial/board info. Packet decode in Wireshark:

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
5. **Cross-referenced with hack-technicolor documentation**: this pattern matches exactly the CFE bootloader's built-in **BOOTP/TFTP recovery mode** — when firmware fails to load 3 times in a row from BOTH banks, the bootloader enters this mode and broadcasts, waiting for a DHCP+TFTP server to hand it a valid firmware image.

---

## Part D — The recovery attempt

### Materials already on hand

From earlier rooting work on the same device, the following were already available locally: several official ISP firmware versions (`AGTEF_x.y.z_CLOSED.rbi`), the community tool `autoflashgui` (previously used for DDNS-exploit-based rooting on an **already-booted** router — not applicable to a bootloader stuck in recovery), PuTTY/WinSCP, and personal rooting notes.

> Note: the `autoflashgui` rooting procedure requires a router that is **powered on and reachable** (admin/admin web access) — it does not apply to this scenario, where the router is stuck in the bootloader before any OS loads.

### Attempt 1 — Tftpd64 with its built-in DHCP server

1. Downloaded **Tftpd64** (portable edition, from the official `PJO2/tftpd64` GitHub release) — no installation, extraction only.
2. Configured `tftpd32.ini`: only TFTP Server + DHCP Server services enabled, TFTP base directory pointed at the firmware folder, DHCP pool `10.0.0.100`–`10.0.0.119`, subnet `255.255.255.0`, gateway `10.0.0.99`, boot filename set to the target firmware file.
3. **Problem found**: the PC's own network card (sitting in APIPA) grabbed a lease from our freshly-started DHCP server, changing its own address and breaking Tftpd64's socket binding to the previously-configured IP. Tftpd64 log (`tftpd64.log`):

   ```
   Rcvd DHCP Discover Msg for IP 0.0.0.0, Mac D8:BB:C1:xx:xx:xx
   DHCP: proposed address 10.0.0.100
   Rcvd DHCP Rqst Msg for IP 0.0.0.0, Mac D8:BB:C1:xx:xx:xx
   Previously allocated address 10.0.0.100 acked
   Message received on an unbound interface (IP 10.0.0.100)
   Message received on an unbound interface (IP 10.0.0.100)
   Message received on an unbound interface (IP 10.0.0.100)
   [... repeats every ~1s ...]
   ```

4. **Fix**: set a **static IP** on the PC's Ethernet adapter (`10.0.0.99/24` — requires administrator privileges, not available in the automated session: applied manually by the user), and explicitly re-bound Tftpd64 to that stable address.
5. The router correctly obtained a BOOTP lease (`10.0.0.101`), confirmed in the log and persisted in Tftpd64's ini — but it never progressed to an actual TFTP request, endlessly repeating the BOOTP cycle every ~30 seconds:

   ```
   Rcvd BootP Msg for IP 0.0.0.0, Mac 10:13:31:xx:xx:xx
   DHCP: proposed address 10.0.0.101
   [... repeats every ~30s, no TFTP request ever arrives ...]
   ```

### The real cause: a bug in Tftpd64's own source code

Live-capturing the network traffic (using Python/`scapy`, since Wireshark itself wasn't installed on this machine but the **Npcap** driver was) revealed that the server's BOOTP reply had its **`siaddr`** field ("next server", i.e. the TFTP server address to fetch from) always set to `0.0.0.0` — even though the boot filename was correct. Without this field, the CFE bootloader has no idea who to ask for the file over TFTP:

```
CLIENT->SRV src=0.0.0.0 dst=255.255.255.255 yiaddr=0.0.0.0 siaddr=0.0.0.0 file=b'VBNT-K\x00...'
SRV->CLIENT src=10.0.0.99 dst=255.255.255.255 yiaddr=10.0.0.101 siaddr=0.0.0.0 file=b'AGTEF_2.4.5_CLOSED.rbi'
                                                                        ^^^^^^^^^^^^ should be 10.0.0.99, not 0.0.0.0
```

Reviewing Tftpd64's public source (`PJO2/tftpd64` on GitHub, `src/_services/bootpd.c`): `siaddr` is only auto-filled through a custom DHCP option (option 66) that turns out to be **never actually read from the ini file** anywhere in the codebase (defined in headers but never wired to the ini-reading logic — the code's own comments confirm an unfinished attempt: *"TODO: add optional siaaddr"*, *"Failed: couldn't add box"*). The automatic fallback (nearest-interface lookup) is guarded by a check for the wrong sentinel value (`INADDR_NONE` instead of zero), so it never actually triggers in practice — actual excerpt from `bootpd.c` (the bug is the last `if`):

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
if (pDhcpPkt->siaddr.S_un.S_addr == INADDR_NONE) {   // <-- bug: compares against INADDR_NONE (0xFFFFFFFF)
    if (sSettings.uServices & TFTPD32_TFTP_SERVER)   //     instead of 0 (unset) -> never actually triggers
        pDhcpPkt->siaddr = *pNearest;
    pDhcpPkt->siaddr = *pNearest;
}
```

### The fix: a custom BOOTP responder

1. Left **Tftpd64 running in TFTP-only mode** (disabled its DHCP server, which wasn't solving the `siaddr` problem anyway).
2. Wrote a small Python script (`scripts/bootp_responder.py`, included in this repository) using **scapy** to:
   - sniff for broadcast `BOOTREQUEST` packets from the router's MAC address,
   - build and send a correct `BOOTREPLY`, with `siaddr` explicitly set to the TFTP server's address, `yiaddr` set to the offered IP, and the target firmware filename.
3. **A bug in the script itself, first try**: the first version used `scapy.send()` (layer 3, scapy's own routing-table-based interface selection) — on a Windows machine with many virtual interfaces (Hyper-V, VPN, etc.) the reply got routed out the wrong interface and never physically reached the router:

   ```
   [03:20:45] Got BOOTREQUEST xid=0x316674ea from 10:13:31:xx:xx:xx, sending reply...
   WARNING: MAC address to reach destination not found. Using broadcast.
     -> reply sent: yiaddr=10.0.0.101 siaddr=10.0.0.99 file=b'AGTEF_2.4.5_CLOSED.rbi'
   ```

   (the script believed it had sent the reply, but the router kept retransmitting every second — a sign it never actually arrived). **Fix**: switched to `scapy.sendp()` (layer 2, respects the explicitly specified network interface).
4. With that fix, the router finally sent a real TFTP read request (`RRQ`) to the correct server, and Tftpd64 served the firmware file — **32.9 MB transferred in 18 seconds, zero blocks retransmitted**:

   ```
   Connection received from 10.0.0.101 on port 4594
   Read request for file <AGTEF_2.4.5_CLOSED.rbi>. Mode octet
   Using local port 56033
   <AGTEF_2.4.5_CLOSED.rbi>: sent 64212 blks, 32876123 bytes in 18 s. 0 blk resent
   ```

5. The router flashed the firmware and rebooted, coming back up normally on its standard LAN IP, with its own DHCP server working again (verified with a stable, 0%-loss ping, and the PC's network card picking up a normal DHCP address from the router itself).

---

## Also see

[`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) — analysis of this firmware's `.rbi` format (header, AES encryption, "signature" block) and a comparison across the available versions.

## Tools & references used

- [hack-technicolor documentation — Recovery](https://hack-technicolor.readthedocs.io/en/stable/Recovery/)
- [PJO2/tftpd64 GitHub repository](https://github.com/PJO2/tftpd64) (source of the `siaddr` bug found and worked around here)
- [hack-technicolor/hack-technicolor issue #235 — DGA4130 (VBNT-K) support thread](https://github.com/hack-technicolor/hack-technicolor/issues/235)
- Ansuel's toolchain/buildroot links, referenced from the `Ansuel/GUI_ipk` GitHub repo README
- ilpuntotecnico.com forum threads on rooting Technicolor gateways
- Wireshark, Npcap, Python 3 + scapy, Tftpd64

## Legal note

No proprietary ISP firmware image is redistributed in this repository — obtain the correct signed firmware for your own device/ISP variant separately (your operator's support site, your own prior backup, or the community resources linked above).
