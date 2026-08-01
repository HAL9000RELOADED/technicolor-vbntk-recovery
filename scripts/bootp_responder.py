#!/usr/bin/env python3
"""Minimal BOOTP responder for Technicolor CFE recovery mode.

Works around a bug in Tftpd64 (https://github.com/PJO2/tftpd64) where the
BOOTREPLY's `siaddr` ("next server" / TFTP server address) field is never
actually populated from configuration, leaving it as 0.0.0.0 and preventing
the CFE bootloader from ever progressing to the actual TFTP GET.

Requires: Python 3, scapy (`pip install scapy`), Npcap (Windows) or an
equivalent packet-capture driver, and enough privilege to send raw L2 frames.

Edit the constants below for your own setup before running. Run this
alongside a TFTP-only server (e.g. Tftpd64 with its DHCP service disabled)
that actually serves BOOTFILE from its base directory.
"""
import time
from scapy.all import sniff, sendp, Ether, IP, UDP, BOOTP, DHCP, get_if_hwaddr

IFACE = "Ethernet"                     # network interface facing the router
MY_IP = "10.0.0.99"                    # this host's IP == the TFTP server IP
CLIENT_MAC = "10:13:31:66:74:ea"       # router's MAC, as seen in BOOTREQUEST
OFFERED_IP = "10.0.0.101"              # IP to hand to the router
BOOTFILE = b"AGTEF_2.4.5_CLOSED.rbi"   # firmware filename, must exist on the TFTP server

my_mac = get_if_hwaddr(IFACE)
print(f"Responder starting. My MAC={my_mac} IFACE={IFACE} MY_IP={MY_IP}")


def handle(pkt):
    if not pkt.haslayer(BOOTP):
        return
    b = pkt[BOOTP]
    chaddr = b.chaddr[:6].hex(":") if isinstance(b.chaddr, bytes) else None
    if chaddr is None or chaddr.lower() != CLIENT_MAC.lower():
        return
    if b.op != 1:  # only reply to BOOTREQUEST
        return
    print(f"[{time.strftime('%H:%M:%S')}] Got BOOTREQUEST xid={b.xid:#x} from {chaddr}, sending reply...")

    file_field = BOOTFILE + b"\x00" * (128 - len(BOOTFILE))

    reply = (
        Ether(src=my_mac, dst="ff:ff:ff:ff:ff:ff") /
        IP(src=MY_IP, dst="255.255.255.255") /
        UDP(sport=67, dport=68) /
        BOOTP(
            op=2, htype=1, hlen=6, hops=0,
            xid=b.xid, secs=0, flags=b.flags,
            ciaddr="0.0.0.0", yiaddr=OFFERED_IP, siaddr=MY_IP, giaddr="0.0.0.0",
            chaddr=b.chaddr, sname=b"\x00" * 64, file=file_field,
        ) /
        DHCP(options=[
            ("message-type", "offer"),
            ("subnet_mask", "255.255.255.0"),
            ("router", MY_IP),
            ("server_id", MY_IP),
            ("lease_time", 3600),
            ("tftp_server_name", MY_IP),
            ("end"),
        ])
    )
    try:
        # NOTE: use sendp() (layer 2), not send() (layer 3) -- send() routes
        # via scapy's own routing table and will silently pick the wrong
        # interface on a multi-NIC host, so the reply never reaches the router.
        sendp(reply, iface=IFACE, verbose=False)
        print(f"  -> reply sent: yiaddr={OFFERED_IP} siaddr={MY_IP} file={BOOTFILE!r}")
    except Exception as e:
        print("  -> SEND FAILED:", e)


print("Sniffing for BOOTREQUEST from", CLIENT_MAC, "... (running 240s)")
sniff(iface=IFACE, filter="udp and port 67", prn=handle, timeout=240, store=False)
print("Responder done.")
