"""Restore a configuration backup through the STOCK web UI's own Import
Configuration feature -- no root/exploit needed, works on stock/patched
firmware. Reverse-engineered from the "Configuration" tab under the
Gateway tile's "System Information" modal (not linked from anywhere else
in this TIM-branded UI, and with no manual firmware-upgrade option
alongside it -- see the guide).

Usage: edit CONFIG_FILE below, then run from this directory (needs
AutoFlashGUI's libautoflashgui.py etc. on PYTHONPATH, see
afg_inject_common.py in this folder for the exact dependency setup).
"""
from afg_inject_common import afg, HOST, USERNAME, PASSWORD
from robobrowser import RoboBrowser

CONFIG_FILE = r"PATH_TO_YOUR\config-backup.bin"

br = RoboBrowser(history=True, parser="html.parser")
afg.srp6authenticate(br, HOST, USERNAME, PASSWORD)

# The CSRF token must come from the main dashboard page ("/"), not from the
# sub-fetched modal page -- fetching it from system-config-modal.lp itself
# returns no token and the POST below then fails with a plain 403.
br.open('http://' + HOST + '/')
token = br.find(lambda tag: tag.has_attr('name') and tag['name'] == 'CSRFtoken')['content']

files = {'configfile': ('config-backup.bin', open(CONFIG_FILE, 'rb'), 'application/octet-stream')}
r = br.session.post(
    'http://' + HOST + '/modals/system-config-modal.lp?action=import_config',
    data={'CSRFtoken': token},
    files=files,
)
print("STATUS:", r.status_code)
print("BODY:", r.text[:2000])
# Expected on success: {"success":"true"} followed by the gateway rebooting
# on its own (~1 minute) to apply the imported configuration.
