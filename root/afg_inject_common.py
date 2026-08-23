"""Shared setup for the afg_inject_*.py scripts in this folder.

Requires AutoFlashGUI's library modules on PYTHONPATH:
https://github.com/mswhirl/autoflashgui (libautoflashgui.py, mysrp.py, liblang.py)

Also requires (in a virtualenv -- the upstream `robobrowser` dependency is
abandoned since ~2016 and incompatible with modern Werkzeug):
    pip install "werkzeug<1.0" beautifulsoup4 requests six
    pip install --no-deps robobrowser

`mysrp.py` (bundled with AutoFlashGUI) has a Python 2/3 str-vs-bytes bug in
gen_x() that crashes on the first login attempt with older Python -- pass
the admin username/password as bytes (b"admin", not "admin") to work around
it without patching the vendored file. `libautoflashgui.py`'s exception
handler also calls traceback.print_exc() without importing `traceback`
itself, which masks the real error on any login failure; this shim
monkeypatches that in.
"""
import sys
import traceback as _traceback

AUTOFLASHGUI_DIR = r"PATH_TO\autoflashgui-master"  # <- point this at your own checkout
sys.path.insert(0, AUTOFLASHGUI_DIR)

import libautoflashgui as afg  # noqa: E402

afg.traceback = _traceback
afg.init_language(sys.argv, sys.path, "en")

HOST = "192.168.1.1"
USERNAME = b"admin"
PASSWORD = b"admin"
