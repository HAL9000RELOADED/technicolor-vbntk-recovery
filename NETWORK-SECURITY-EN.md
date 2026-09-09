# Network services audit and firewall posture — live VBNT-K (2026-09-09)

A snapshot of the **network surface** and service configuration of a real
Technicolor VBNT-K, read read-only over SSH root from a rooted physical unit
(community firmware of the AGTEF 2.4.5 family, kernel 4.1.52 — the **same
unit** as [`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.2 and
[`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) §6).

This file is distinct from the rest of the repo (which analyzes firmware
**format/layout and static reverse engineering**): here we document the
**live security posture** of an in-service unit — which ports are exposed, how
they are authenticated, which services are active and which dormant. All
derived from `uci show`, firewall tables and service state on the unit;
**nothing was modified**.

> **Scope and limits.** This is a point-in-time snapshot of **one** unit, with
> its configuration (partly modified by the community firmware, see §3). It is
> not an assessment of the factory TIM stock, nor does it automatically apply
> to other variants/versions. Sensitive data (internal LAN IPs, WAN public IP,
> SSIDs/passwords, PPPoE/SIP/DDNS credentials, key/certificate bytes) is **not
> reproduced**; the operator's ACS hostnames are public endpoints and are
> reported (consistent with the convention already used in the repo for
> telephony/ACS).

## 1. Firewall — solid default deny/reject on WAN (Observed)

The default policy toward the WAN is **closed**: management services are all
explicitly blocked from outside.

| Service | Port | WAN exposure |
|---|---|---|
| SSH (dropbear) | 22 | blocked |
| Web UI | 80 / 443 (+ accessory ports) | blocked |
| SMB / CIFS | 445 / 139 | blocked |
| CUPS (printing) | 631 | blocked |

None of these is reachable from the WAN in the observed configuration. The
one relevant exception is the operator's remote-management channel
(CWMP/TR-069), covered in §2.

## 2. CWMP / TR-069 — the only real WAN surface (Observed)

Port **7170/tcp** (TR-069 Connection Request) is **open to the entire WAN**:

```
connectionrequest_allowedips = '0.0.0.0/0,::/0'
```

It is not open access, though: it is protected by **HTTP Digest
Authentication** (`connectionrequest_auth = '2'`) with **throttling**
(observed limit: ~200 attempts / 60 s). The real attack surface is therefore a
**brute-force against the digest**, not an authentication bypass — the
endpoint requires valid credentials before doing anything.

The outbound channel to the ACS is instead **TLS-enforced with full
certificate verification**:

```
enforce_https = 1
ssl_verifypeer = 1        (certificates in /etc/ssl/acs-cert/)
```

**Two ACS profiles** are configured:

| Profile | Endpoint | Use | Polling |
|---|---|---|---|
| Primary | `regman-tl.interbusiness.it:10700` | TIM business | no periodic polling, push only |
| Secondary | `mobile.acs.tim.it:11201` | TIM mobile / LTE | active polling |

## 3. Community-firmware anti-automatic-OTA gate (Observed)

A notable discovery specific to **this** community build: a custom flag
intercepts the ACS's push upgrade requests and does **not** perform the update
automatically.

```
modgui.var.disable_cwmp_update = '1'
```

With this flag set, an OTA push from the operator does **not** produce a
silent flash: the upgrade requires manual approval from the Modgui panel. This
changes the "the operator reflashes me remotely and I lose root" risk
assessment: on this unit that path is defused at the firmware level. (This
connects to the device-side signature verification in
[`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) §6: the `sysupgrade` path would in any
case still be subject to the signature/header checks described there.)

## 4. UPnP active (Observed)

The **`miniupnpd-igdv2`** daemon is active and, at audit time, had dynamic
forwards toward internal LAN hosts (specific IPs **not reproduced** —
generalized as "internal LAN hosts"). No additional control observed beyond
the standard IGDv2 ones. Worth keeping in mind as a LAN-side surface: a
compromised internal app/host can open forwards automatically.

## 5. Previously-known services — confirmed off/disabled (Observed)

Services already mentioned in prior sessions, re-checked here and confirmed
**disabled**: `iperf`, `urlfilterd`, `dnsfilterd`, `gre-hotspotd`. None of
them is listening.

**No log or telemetry to external servers** was detected in this session
(beyond the legitimate ACS channel of §2 and the local MQTT broker of §6,
which is local).

## 6. UCI sections never documented before in the repo (Observed)

### 6.1 `wifi_doctor_agent`

A third-party cloud agent for WiFi diagnostics, with OAuth2 toward
`device-auth-ap.wifi-doctor.org`. **Currently `enabled = '0'`** — present in
the firmware but disabled. Flagged because it is a cloud-side telemetry
channel that, if enabled, would send diagnostic data to a third party: worth
watching on units where it turns out active.

### 6.2 `mosquitto`

A **local** MQTT broker with mutual-cert TLS on `:8883` (the corresponding
client certificate is the `/proc/rip/011a.cert` infoblock, see
[`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.3). Most likely
used for companion-app pairing. **Hypothesis**, the broker's exact consumer
not verified.

### 6.3 Dropbear — `wan`/`afg` profiles with dormant capability

The dropbear configuration contains `wan` and `afg` profiles with root-login
enabled **in the config**, but the `wan` profile is **disabled**:

```
dropbear.wan.enable = '0'
```

So **no WAN SSH exposure is active** — but the capability is **dormant** in
the configuration (an `enable='1'` would activate it). Worth knowing: an
attacker gaining write access to the config could re-enable WAN SSH without
adding anything new. Consistent with the dropbear evolution documented in
[`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) §3.2.

## 8. Broadpeak nanoCDN / MABR IPTV redirector — dual-instance bind conflict (Observed, 2026-09-09)

`system.mabr.enabled = '1'`. `/etc/init.d/nanocdn` (procd) starts **two**
separate binaries from the **same** shared config file
(`/etc/broadpeak/nanocdn.conf`): `nanocdn-core` and `nanocdn-rr` ("Request
Router"). Since both read every line of the same file, each logs `unknown
option` for whichever CLI flags it doesn't recognize (the other binary's
options) — expected noise, not an error.

**`nanocdn-core` runs correctly**: stable, TIM-branded build
(`v2.6.2@5365-tim`), listens on `18081`, answers `/nanocdnstatus.xml`,
`/crossdomain.xml` and `/clientaccesspolicy.xml` with valid content. Its
proprietary STB-agent API (`BkStbA`, strings include `SetNewLiveChannel` and
`/GetBkeServerList`) is reachable but its call sequence for requesting a live
channel was not reverse-engineered in this session (undocumented,
Flash/Silverlight-era "QualityLevels()/Fragments()" and HLS/DASH manifest
patterns are present in the binary, consistent with Microsoft Smooth
Streaming + HLS/DASH output support).

**`nanocdn-rr` crash-loops continuously** (`ERROR could not bind to any
interface`, respawned by `procd` every ~5s, `respawn 3600 5 0`). Ruled out as
causes, each independently verified on the live unit:
- **Not** the operator's anti-root kill-switch: `env.var.unlockedstatus = '0'`
  (this rooting method does not flip that flag, so the firmware's own
  `nanocdn stop`-on-unlock logic, present elsewhere in this build's
  uci-defaults, never fires).
- **Not** missing TLS trust material: `/etc/broadpeak/certs/` has a full,
  intact CA bundle.
- **Not** CDN backend unreachability: the operator's CDN host referenced in
  `smartlib-conf` is reachable and answers HTTPS.
- **Not** a TCP port collision on the value in `rr-nano-addr`: changing it
  (`18081` → `18082`) and restarting the service had **zero effect** on the
  error — this rules out `rr-nano-addr` being `nanocdn-rr`'s own listen
  address; it is more likely the address `nanocdn-rr` uses to reach
  `nanocdn-core` as an upstream, not something it binds itself.

**Best-supported remaining hypothesis**: both binaries try to open their own
"control channel multicast receiver" (binary string: `Control channel
multicast receiver started on multicast '%s:%s'`) on the identical
`controlchannel-multicast=239.200.0.0:5004` value, on the same interface
(`br-lan`). `nanocdn-core` starts first (script order) and wins the bind;
`nanocdn-rr`'s later attempt fails, and the binary reports a generic
"any interface" message instead of a specific "address in use" — plausible if
the multicast receive socket isn't opened with `SO_REUSEADDR`/`SO_REUSEPORT`.
This fits Broadpeak's own documented role split (`nanocdn-rr` is the
load-balancing "Request Router" **across multiple** `nanocdn-core` instances,
a real CDN-scale-out pattern) — on a single-box home CPE with exactly one
`nanocdn-core`, the two are structurally redundant and appear not to have been
tested/designed to coexist on the same host/interface.

**Fix applied on this unit**: the `nanocdn-rr` instance block was removed
from `/etc/init.d/nanocdn` (`procd_open_instance nanocdn-rr` ... 
`procd_close_instance`), `nanocdn-core`'s block left untouched (backup of the
original script kept alongside it). Confirmed after restart: `nanocdn-core`
still stable and listening on `18081`, no more respawn-loop, no functional
regression observed (the core IPTV-redirector role — the actually useful
one — does not depend on `nanocdn-rr` being present).

## 9. ⚠️ `wifi-nurse-modal.lp` is not a safe read-only GET (Observed, 2026-09-09)

A plain `GET /modals/wifi-nurse-modal.lp` was observed, on this same class of
unit, to trigger **server-side write logic** rather than just returning a
status page: when issued while WAN/ACS connectivity is unavailable (e.g.
during root/recovery work with WAN intentionally disconnected, or any other
condition where the branding data it expects isn't reachable), it overwrote
**live** `wireless` UCI config — SSID **and** `wpa_psk_key`/`wep_key`/
`wps_ap_pin` on all four `wifi-iface` sections — with the firmware's stock
factory placeholder string `SET_BY_SCRIPT` (confirmed hardcoded in
`/etc/config/wireless` in multiple firmware dumps studied for this repo,
meant to be overwritten by first-activation branding). This dropped every
associated WiFi client (they saw the SSID literally renamed) until corrected.

**Practical implication for anyone scanning/enumerating this web UI's `.lp`
endpoints** (see also the pacing guidance already established for this
class of embedded Lua/nginx webserver): treat `wifi-nurse-modal.lp` — and
by extension any other endpoint whose name implies an active "fix/nurse/
diagnose" action rather than a passive status display — as a **write**
operation, not a safe read. `cwmpconf-modal.lp` (CWMP/ACS config) carries the
same category of risk and should be excluded from routine scans for the same
reason.

## 10. Open questions / to verify

- Exact consumer of the local MQTT broker (§6.2): companion-app pairing
  assumed, not confirmed.
- Not verified whether the CWMP throttling (§2, ~200/60 s) is applied per-IP
  or globally — this changes the assessment of resistance to distributed
  brute-force.
- `wifi_doctor_agent` (§6.1): not verified what exact data it would send if
  enabled, nor whether the factory stock has it active by default.
- Single-unit snapshot with community firmware: firewall values and ACS
  profiles could differ on the factory TIM stock — not compared in this
  session.
- `nanocdn-core`'s `BkStbA` STB-agent protocol (§8) was not reverse-engineered
  far enough to actually request and play a live channel — the exact
  `SetNewLiveChannel`/`GetBkeServerList` call format remains unknown.
- The exact internal cause of `wifi-nurse-modal.lp`'s config-write side effect
  (§9) — under what conditions it triggers, and whether it can be reproduced
  deliberately — was not isolated further; observed once, empirically, not
  forced.
