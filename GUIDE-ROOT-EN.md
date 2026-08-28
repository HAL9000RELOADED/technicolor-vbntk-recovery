# Root guide: rooting attempt on AGTEF_2.4.5 (failed) + config restore (succeeded)

Direct follow-on from [`GUIDE-EN.md`](GUIDE-EN.md): after the firmware recovery, an attempt was made to regain the root access lost in the reflash (needed to install the community "Ansuel" GUI), then to restore a configuration backup. Scripts in [`root/`](root/).

## Starting conditions

- Router just recovered with `AGTEF_2.4.5_CLOSED.rbi` (see the main guide), so on "stock" clean firmware — no root modification survives a full bank reflash.
- Admin web panel reachable at `192.168.1.1`, credentials `admin`/`admin`.
- Prior (self-authored) rooting notes for this same device, written against **AGTEF_1.0.3**, much older than the current 2.4.5.

## Tool: AutoFlashGUI

[AutoFlashGUI](https://github.com/mswhirl/autoflashgui) (by Mark Smith / Whirlpool, GPLv3, part of the [hack-technicolor](https://hack-technicolor.readthedocs.io) ecosystem) automates rooting Technicolor gateways via **command injection** in one of the admin panel's DDNS fields: the router runs an internal ping/DDNS-update action without properly sanitizing the input, allowing arbitrary shell commands to be smuggled in as part of the "domain"/"IP address" value in the request.

Rather than driving the Windows GUI (not easily scriptable), the underlying Python library (`libautoflashgui.py`) was called directly from a script.

### Dependencies: three Python 3 compatibility bugs to work around

1. **`robobrowser`** (the library's HTTP dependency) has been abandoned since 2016 and is incompatible with modern Werkzeug (`cannot import name 'cached_property' from 'werkzeug'`). Fix: a dedicated virtualenv with `werkzeug<1.0` pinned, then `pip install --no-deps robobrowser` so it doesn't pull in a recent Werkzeug.
2. **`mysrp.py`** (the bundled local SRP-6 auth implementation) mixes `str` and `bytes` in one spot (`username + six.b(':') + password`), causing an immediate `TypeError` on the very first login attempt under Python 3. Fix (without touching the vendored file): pass username/password as **bytes** (`b"admin"`, not `"admin"`) from the calling script — this propagates correctly through the whole chain.
3. Bonus: `libautoflashgui.py`'s own except-handler calls `traceback.print_exc()` without importing `traceback` — if authentication fails for any other reason, this masks the real error behind a second `NameError`. Fix: inject a `traceback` attribute into the module before calling it (see `root/afg_inject_common.py`).

See `root/afg_inject_common.py` for the full setup.

## Rooting attempt: three variants, all failed

AutoFlashGUI supports several injection "methods" (different panel endpoints). Three were tried, in sequence, each completing SRP-6 authentication successfully (credentials confirmed correct) but **none of them resulted in SSH becoming reachable**:

| Script | Method/endpoint | Outcome |
|---|---|---|
| `root/afg_inject_advancedddns.py` | `AdvancedDDNS` → `/modals/wanservices-modal.lp` (`ddns_domain` field) | Commands sent with no transport error, port 22 stayed closed |
| `root/afg_inject_ping.py` | `Ping` → `/modals/diagnostics-ping-modal.lp` (`ipAddress` field), DGA4130/1.0.3-specific command | Same outcome |
| `root/afg_inject_basicddns.py` | `BasicDDNS` → `/dyndns.lp` (`ddns_domain` field) | Same outcome |

**Conclusion**: three different endpoints, same negative outcome — fairly strong evidence that TIM patched this class of command-injection vulnerability in version 2.4.5 (the original rooting notes were written against the much older 1.0.3).

### Idea considered and dropped: forcing BOOTP/TFTP mode for a downgrade

Before giving up on direct rooting, downgrading to an older, presumably still-vulnerable firmware (2.2.1) was considered, reusing the same CFE-level BOOTP/TFTP mechanism documented in the main guide (which had already worked for the recovery), triggered by holding the reset button for 8 seconds as per the original rooting notes.

**Result**: on a **healthy** router, holding reset for 8 seconds does not trigger BOOTP recovery mode — that mode only fires *automatically* after a genuine boot failure on both firmware banks (verified: after the reset, firmware stayed unchanged at `AGTEF_2.4.5` and the router came back up normally within ~1 minute). Deliberately forcing it would require recreating a genuine boot failure — exactly the risk that caused the original incident — so the idea was dropped as not safely practicable without a second deliberate attempt at corrupting the banks.

**Update 2026-08-27 — the "2.2.1 presumably still vulnerable" premise is confirmed**: on **a different physical unit** (not the one this guide is about, which stays on 2.4.5 here) found already running firmware **AGTEF_2.2.1**, root via the classic "Ansuel GUI"/AutoFlashGUI chain is indeed present and working — confirmed by reading `/etc/init.d/rootdevice` and `/etc/modgui_scripts/*.sh` (Christian Marangi, GUI version `9.6.69-3bd8c3f6`) and the live dropbear config, which shows a dedicated `dropbear.afg` stanza (LAN-only) enabled. Opkg feeds used for packages (LuCI etc.), for future reference:
```
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/base
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/packages
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/luci
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/routing
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/telephony
https://raw.githubusercontent.com/Ansuel/GUI_ipk/kernel-4.1/target/packages
```
This does **not** solve the practical problem described above (how to force
the downgrade/BOOTP on a healthy router without recreating the original
incident) — it's only independent confirmation that, once a safe way to
reach 2.2.1 is found, the vulnerability surface AutoFlashGUI exploits is
still present on that version. See also `MEMORY-ARCHITECTURE-EN.md`
§2.1/§4.1/§5 for other data collected on the same unit (partition map,
config-backup encryption mechanism, a — third-hand, unconfirmed — lead on
bank targeting via BOOTP).

## Success: config restore via the stock UI (no root needed)

Scanning the admin panel's pages (no firmware-upgrade link/button is exposed anywhere in this TIM-branded skin — likely deliberately removed), the "Gateway" tile's "Configuration" tab was found to still expose native **Export/Import Configuration**:

```
POST /modals/system-config-modal.lp?action=import_config
Content-Type: multipart/form-data
file field: configfile (must have a .bin extension)
```

The CSRF token must come from the main dashboard page (`/`), not from the modal page itself (fetching it from there returns `403 Forbidden`). Working script: `root/import_config.py`. Success response:

```
{ "success":"true" }
```

followed by the router rebooting on its own (~1 minute) to apply the imported configuration — verified with a stable ping (4/4, 1-4ms) once it came back.

## Outcome summary

| Goal | Outcome |
|---|---|
| Root / SSH on AGTEF_2.4.5 | ❌ Failed (3 injection methods tried, all blocked) |
| Forced downgrade to 2.2.1 via reset | ❌ Dropped (doesn't trigger recovery mode on healthy firmware) |
| Configuration restore | ✅ Succeeded, via a stock endpoint not documented publicly elsewhere |
| Ansuel GUI installation | ⏸ Not done (requires root, not obtained) |

## Also see

[`GUIDE-EN.md`](GUIDE-EN.md) — the firmware recovery guide that precedes this rooting attempt.

[`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) — analysis of the `.rbi` format used by these firmware images (header, AES encryption, "signature" block) and a comparison across the available versions.
