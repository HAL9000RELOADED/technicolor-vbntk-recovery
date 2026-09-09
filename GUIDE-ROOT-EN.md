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

**Conclusion**: three different endpoints, same negative outcome — fairly strong evidence that the ISP patched this class of command-injection vulnerability in version 2.4.5 (the original rooting notes were written against the much older 1.0.3).

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

Scanning the admin panel's pages (no firmware-upgrade link/button is exposed anywhere in this ISP-branded skin — likely deliberately removed), the "Gateway" tile's "Configuration" tab was found to still expose native **Export/Import Configuration**:

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

See the update below though: root+GUI on 2.4.5 were reached anyway, via a
different, indirect path from the direct injection above.

## Update 2026-09-09: root reached indirectly (root 1.0.3 → bank planning → upgrade to 2.4.5 with root preserved)

In a different session, the direct rooting attempt described above was
sidestepped entirely by changing approach: **root the vulnerable firmware
first (1.0.3), then carry the root through the upgrade to 2.4.5**, instead
of trying to exploit 2.4.5 directly (patched, per above).

Starting conditions: router on AGTEF_1.0.3, SSH closed, web UI rendered
proper HTML/CSRF (no raw-Lua issue hit in this attempt).

### Steps

1. **Headless AutoFlashGUI injection** (same `libautoflashgui.mainScript`,
   `Ping` method, the `DGA4130 TIM AGTEF_1.0.3`-specific command from
   AutoFlashGUI's `defaults.ini`) → root SSH successfully enabled,
   confirmed `uid=0`. This vulnerability class is still open on 1.0.3
   (consistent with what's already documented elsewhere in this repo).
2. **Bank planning**: real state read from `/proc/banktable/*` —
   `booted=bank_2` (freshly rooted 1.0.3), `active=bank_1`, bank_1
   **completely empty** (`0xFF` across all 64 bytes checked). Applied the
   "flash directly into the empty bank" variant instead of
   swap-then-erase (see
   [`dga4130-root` README](https://github.com/HAL9000RELOADED/dga4130-root#bank-planning-quando-saltare-lo-swap-then-erase-variante-più-sicura)):
   no overlay swap, rooted `bank_2` stays untouched as a fallback for the
   whole procedure.
3. Uploaded `AGTEF_2.4.5_CLOSED.rbi` (32,876,123 bytes) over an SSH exec
   channel (`cat > /tmp/new.rbi`, not SFTP — this firmware's dropbear
   doesn't expose the sftp subsystem), MD5 verified identical to the
   local file.
4. On-device unseal (`bli_parser`/`bli_unseal | dd bs=4 skip=1 seek=1`) →
   `/tmp/new.bin` exactly 83,886,080 bytes = one bank's size
   (`mtd3`/`mtd4`), confirming container integrity.
5. Staged the same root-persistence `rc.local` block (see
   `Root-DGA4130.ps1`) into `/overlay/bank_1/etc/rc.local`, MD5 verified.
6. `mtd write /tmp/new.bin bank_1` + `echo bank_1 > /proc/banktable/active`
   + reboot.
7. Successful boot into `bank_1`: `rc.local` ran and self-deleted as
   expected, root confirmed (`uid=0`).
8. Uploaded + installed the Ansuel GUI (`GUI.tar.bz2`, MD5 verified) via
   `bzcat | tar -C / -xvf - && /etc/init.d/rootdevice force`. **Practical
   note**: both the unseal (step 4) and `rootdevice force` (this step) are
   long-running (tens of seconds, the latter ~70s) and survive the SSH
   channel that launched them being closed — if the SSH client times out,
   the command keeps running on the modem regardless; check completion via
   `ps` before treating it as failed.

### GUI install confirmation

```
$ uci show modgui
modgui.gui.gui_version='9.5.38-ba81e28c'
modgui.gui.gui_hash='<uploaded GUI.tar.bz2's md5>'
modgui.var.version_spoof_mode='enabled'
modgui.var.isp_autodetect='1'
modgui.var.isp='TIM'
```
Same "signature" (`modgui` UCI, `rootdevice`/`modgui_scripts` by Christian
Marangi) already documented for the "martin router king" unit in
`MEMORY-ARCHITECTURE-EN.md`.

### Finding: the "AGTEF_2.4.5" label doesn't match the firmware's own internal version string

The community-labeled file `AGTEF_2.4.5_CLOSED.rbi` (sha256
`8fe8eb38531ac3f1cdc58671c5598885204a037d3db530a5230f476398b6a1f8`), once
booted, reports `/etc/config/version`:
```
option version '19.4.1051-3401200-20241119103149-cf49b74e8c88c918fead0a0f9ad052f3283f4ee7'
option marketing_name 'Damson'
option marketing_version '19.4'
```
with `/etc/openwrt_release`: `DISTRIB_REVISION='r14144-e2ae576c18'`,
`DISTRIB_TARGET='brcm6xxx-tch/VBNTJ_502L07p1'`, kernel `4.1.52`. The
"AGTEF X.Y.Z" label used by the community/hack-technicolor to catalog
files **does not match** TIM's own internal version string (same
phenomenon already known for 1.0.3, which internally reports as
`16.3.7636`) — useful to know for anyone trying to correlate a downloaded
`.rbi` file with what the panel/SSH reports after flashing it.

### Hardening against operator reclaim via ACS/CWMP: NOT present by default

Verified on this unit (rooted, on 2.4.5/19.4.1051, with VDSL disconnected
per the procedure): the TR-069 client (`cwmpd` + its `cwmpevents` Lua
helper) is **active and enabled at boot** (`/etc/rc.d/S70cwmpd`) — rooting
and installing the GUI **does not touch it**. `uci show cwmpd` exposes two
operational ACS profiles:

```
cwmpd.cwmpd_config.acs_url='https://regman-tl.interbusiness.it:10700/acs/'
cwmpd.cwmpd_config.acs_user='0018F6-Thomson-AGBasAdv'
cwmpd.cwmpd_config.periodicinform_enable='0'
cwmpd.operationalACS1.acs_url='https://regman-tl.interbusiness.it:10700/acs/'
cwmpd.operationalACS1.acs_user='0018F6-Thomson-AGBasAdv'
cwmpd.operationalACS1.connectionrequest_username='0018F6-Technicolor-CR-AG3play'
cwmpd.operationalACS2.acs_url='https://mobile.acs.tim.it:11201/cwmpWeb/WGCPEMgt'
cwmpd.operationalACS2.acs_user='fwacpedefaultusr'
cwmpd.operationalACS2.connectionrequest_username='fwacpecrdefaultusr'
cwmpd.operationalACS2.periodicinform_enable='1'
cwmpd.operationalACS2.periodicinform_interval='3600'
```
(`acs_pass`/`connectionrequest_password` fields are present in the same
output but deliberately omitted here — retrievable with the same
`uci show cwmpd` command on a rooted unit, since they're stored in plain
text in the device's own UCI config.)

`operationalACS2` (`mobile.acs.tim.it`) has `periodicinform_enable='1'`
with a **3600s** interval — this is TIM's "live" profile: once VDSL is
reconnected, the modem will attempt a CWMP Inform to that host every hour,
on its own initiative (CPE-initiated), regardless of any LAN-side
firewall rule. Port 7547 (the ConnectionRequest listener, for *inbound*
requests from the ACS) was found **not listening** at check time — so the
operator could not force a connection at that exact moment — but this
does not block the periodic **outbound** Inform, inside which the ACS can
still issue standard CWMP RPCs (`Download`/firmware upgrade,
`SetParameterValues`, `FactoryReset`, `Reboot`) within the session the CPE
itself opened.

A firewall rule `Deny_CWMP_Conn_Reqs_from_LAN` was also found, but it
protects against spoofed ConnectionRequests **from the LAN side** — not
hardening against the operator.

**Conclusion: the device is NOT hardened against the operator reclaiming
it.** As long as VDSL stays disconnected (already a standing precondition
of this whole procedure, see the main guide) this is moot. The moment WAN
comes back up, TIM's ACS has a working standard CWMP channel and could, at
their policy's discretion, force a firmware update that silently reverts
root. **Mitigation not yet applied on this unit**:
`/etc/init.d/cwmpd disable; killall cwmpd cwmpevents` stops the client
(at the cost of losing official ISP remote diagnostics/support) — it needs
to be made persistent the same way root is (same `rc.local`/overlay
mechanism), otherwise it comes back on the next clean boot or after any
Download RPC received before disabling it. Alternatively, anyone who wants
to keep VDSL connected can firewall-block the CPE's own outbound traffic
to the ACS hosts listed above.

## Also see

[`GUIDE-EN.md`](GUIDE-EN.md) — the firmware recovery guide that precedes this rooting attempt.

[`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) — analysis of the `.rbi` format used by these firmware images (header, AES encryption, "signature" block) and a comparison across the available versions.

[`dga4130-root` repo](https://github.com/HAL9000RELOADED/dga4130-root) — the `Root-DGA4130.ps1` script and the bank-planning variant used in the update above.
