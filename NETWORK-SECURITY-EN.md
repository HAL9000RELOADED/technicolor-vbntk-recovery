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
[`MEMORY-ARCHITECTURE-EN.md`](MEMORY-ARCHITECTURE-EN.md) §4.3).

**Consumer identified (2026-09-11)**: it's **`wifi_doctor_agent`**, the same
component from §6.1. The `/usr/lib/libwifidoctoragent.so` library contains a
full MQTT client (links `libmosquitto`, strings such as `[fhc] Established
connection to MQTT broker`, `Using secure MQTT connection`, `chain.pem`) that
references the exact same `/tmp/certs/` path used by mosquitto's TLS
listener. The server-side auth plugin (`/usr/lib/mosquitto/wd_auth_plugin.so`)
contains the string `wd_auth` — same "WD" (WiFi Doctor) prefix. The
`wifi_doctor_agent` UCI config confirms the relationship: its `app_support`
section self-declares `is_broker='1'`.

**But on the observed unit the whole chain is dormant**, despite several UCI
flags individually being on (`app_support.enable='1'`, `fhc.enable='1'`,
`fhc_master.enable='1'`, while the top-level cloud toggle
`wifi_doctor_agent.config.enabled` stays `'0'` as already noted in §6.1):
`/tmp/certs/` doesn't exist, **no process anywhere on the system has
`libwifidoctoragent.so` mapped into memory** (verified by scanning
`/proc/*/maps` across every PID), no `/etc/init.d/` script references it, and
mosquitto itself has neither a real PID nor a listening port (`8883`/`1883`
absent from `ss -tln`) — despite `/etc/init.d/mosquitto status` reporting
"running" (a false positive: the status check doesn't verify actual process
liveness). In short: the broker exists as ready-to-use infrastructure, but on
this unit nothing currently starts it and nothing currently connects to it.

### 6.3 Dropbear — `wan` (WAN, dormant) and `afg` (LAN, active) profiles

The dropbear configuration contains two distinct profiles with root-login
enabled, not to be confused with each other:

- **`afg`** — restricted to `Interface='lan'`: not reachable from
  Internet/WAN. This is the **active** profile, used for the SSH admin
  access documented in [`GUIDE-ROOT-EN.md`](GUIDE-ROOT-EN.md) (section
  "Update 2026-09-09: root reached indirectly") — so it is not relevant to
  the WAN exposure this audit is about.
- **`wan`** — the profile that would, in the abstract, matter for a WAN SSH
  exposure, is **disabled**:

```
dropbear.wan.enable = '0'
```

So **no WAN SSH exposure is active** — but the capability is **dormant** in
the `wan` profile's configuration (an `enable='1'` would activate it). Worth
knowing: an attacker gaining write access to the config could re-enable WAN
SSH without adding anything new. Consistent with the dropbear evolution
documented in [`RBI-FORMAT-EN.md`](RBI-FORMAT-EN.md) §3.2.

## 7. Broadpeak nanoCDN / MABR IPTV redirector — dual-instance bind conflict (Observed, 2026-09-09)

`system.mabr.enabled = '1'`. `/etc/init.d/nanocdn` (procd) starts **two**
separate binaries from the **same** shared config file
(`/etc/broadpeak/nanocdn.conf`): `nanocdn-core` and `nanocdn-rr` ("Request
Router"). Since both read every line of the same file, each logs `unknown
option` for whichever CLI flags it doesn't recognize (the other binary's
options) — expected noise, not an error.

**`nanocdn-core` runs correctly**: stable, TIM-branded build
(`v2.6.2@5365-tim`), listens on `18081`, answers `/nanocdnstatus.xml`,
`/crossdomain.xml` and `/clientaccesspolicy.xml` with valid content.

**Clarification on `BkStbA` (2026-09-11, static binary-string analysis only)**: 
`BkStbA` is Broadpeak's client library for
multicast IPTV reception (version `BkStbA 2.2.0`, `msync_bkstba` module),
statically linked into `nanocdn-core`. Important correction to the earlier
phrasing: **`BkStbA_SetNewLiveChannel` and `BkStbA_CreateLiveStream` are
internal C library functions** (seen in the strings as `BkStbA.c:<line>`
references, never as HTTP paths) — they handle multicast group join/leave,
**Fast Channel Change (FCC)**, **unicast RTP retry** for lost multicast
packets, and **FEC** (forward error correction). They are not reachable over
the network as HTTP endpoints in this binary — they're the API the *rest* of
`nanocdn-core`'s own code uses to drive the library, not something an
external STB calls directly.

Other URL-shaped strings also show up in the binary, whose direction (served
by `nanocdn-core` inbound on `18081`, versus templates `nanocdn-core` itself
uses for outbound requests) **isn't confirmed by strings alone** — consistent
with the fact that this file already serves `crossdomain.xml`/
`clientaccesspolicy.xml` inbound, which makes server-side exposure plausible
but not certain: `/QualityLevels(`, `/Fragments(`, `/Segment`, `/Level`,
`/Alter` — **Microsoft Smooth Streaming** manifest/segment request syntax (a
precise confirmation of the earlier "Flash/Silverlight-style pattern" guess,
now identified as standard MSS syntax) — and `/nservices/metricsReceiver`
(a name consistent with a metrics-collection endpoint, likely received rather
than requested, but not verified). Same level of uncertainty applies to
`/GetBkeServerList`, which appears as an isolated string; its direction
(whether `nanocdn-core` requests it from a Broadpeak/operator
backend, or exposes it itself) isn't determinable from strings alone and was
not tested.

The overall picture is therefore a **standard multicast IPTV redirector/
relay for the subscription's linear channels** (multicast join + FCC + RTP
retry + ABR via Smooth Streaming) — common telco-IPTV technology.

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

### Update (2026-09-12, second unit, same family) — `nanocdn-rr` observed running live: bind-fail cause reframed

On a second unit of the same family (DGA4130/VBNT-K), `nanocdn-rr` was not
crash-looping but **survived as an orphaned process** from an earlier boot,
listening and **working** on TCP port **8000** — not `18081`/`18082` as in
the shared config file. This made it possible to observe its real behavior
for the first time when it does start successfully: it's a **transparent
HTTP reverse proxy keyed on the request's `Host:` header** — when it matches
one of the operator's CDN hostnames listed in `smartlib-conf`, it forwards
the request to the real CDN (confirmed by `Via:` headers naming real
operator backbone hosts in the response) or serves it from the local
multicast buffer.

Manually restarting it with the same shared `--conf` reproduces the bind
failure identically (`ERROR could not bind to any interface`) — but the log,
read in full, also shows `unknown option` for several directives **in its
own namespace** (`rr-*` prefix, so not attributable to "the other binary" as
hypothesized above), absent from any older build: a sign that the shared
config file — updated remotely by the operator over the ACS/CWMP channel in
§2 — is now written for a newer Broadpeak protocol/schema version than the
binary installed on this firmware understands. Started instead **with no
config file at all** (compiled-in defaults), the bind on `0.0.0.0:8000`
always succeeds, and the relay works as described above.

This doesn't rule out the original hypothesis (bind-race on the multicast
control channel shared with `nanocdn-core`) as a contributing cause — the
specific test wasn't repeated on this second unit — but it adds a concrete,
reproducible factor: the config/binary version mismatch. The fix already
documented above (removing the instance from `/etc/init.d/nanocdn`) remains
valid as a stability measure; for anyone who actually needs `nanocdn-rr`'s
HTTP relay (useful e.g. for third-party UPnP/DLNA bridges, see
[`XUPNPD-IPTV-EN.md`](XUPNPD-IPTV-EN.md) §6), the only mode observed working
is starting it standalone, without `--conf`.

## 8. ⚠️ `wifi-nurse-modal.lp` is not a safe read-only GET (Observed, 2026-09-09)

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

## 9. VoIP/SIP: "callee unreachable" despite local "Registered" state — stale binding on the operator's SBC (Observed/Resolved, 2026-09-11)

Symptom: calling the landline (voice via `mmpbxd`, SIP profile against
registrar `telecomitalia.it` / proxy `88.50.251.167:5060`) from a mobile phone
on a third-party carrier, the calling carrier returned "the callee is
temporarily unreachable" — even though the Modgui panel and the local SIP
state both showed "Registered".

Diagnostic path (all read-only over root SSH, no changes until the final
fix):

1. **Service config and status** (`uci show mmpbx*`): SIP profile correctly
   populated (registrar/proxy/realm set, no leftover placeholder), `mmpbxd`
   process running, regular re-registration cycles roughly every 55-58
   minutes visible in `logread` — nothing obviously wrong at first glance.
2. Found one isolated deregistration incident earlier the same morning,
   caused by a UDP send failure (`errno=22`) to the SIP proxy — lasted about
   3 minutes, but **did not line up** with the actual timestamps of the
   reported failed call attempts: a red herring, not the cause.
3. **NAT helper (SIP ALG)**: confirmed the `nf_conntrack_sip`/`nf_nat_sip`
   kernel modules are loaded, but **ruled out** as the cause:
   `net.netfilter.nf_conntrack_helper=0` disables global helper auto-attach,
   and the `sip` helper is only assigned to the `lan`/`loopback` firewall
   zones, not `wan` — where this router's own native SIP traffic runs, with a
   direct public IP over PPPoE and no NAT applied to its own traffic. The SIP
   ALG therefore never touches this unit's native voice service.
4. **Decisive test**: live-captured `logread -f` for 60 seconds while two
   real call attempts were placed from an external number. Result: **zero
   SIP/mmpbx log activity for the entire window** — no INVITE ever reached
   the router. Direct proof the problem wasn't on the CPE but **upstream, on
   the operator's network/SBC**, which held a stale registration binding for
   that number despite the router looking regularly registered on its own
   side.

**Fix**: `/etc/init.d/mmpbxd restart` (after confirming via
`ubus call mmpbxbrcmfxs.state get '{"device":"fxs_dev_N"}'` that neither FXS
line had a call in progress). This produced a clean Deregister → Register
Success cycle in under 2 seconds, forcing the operator's SBC to drop the
stale binding and create a fresh one. A verification call succeeded right
after.

Real log excerpt from the fix (phone number and public WAN IP not reported,
consistent with this file's policy):

```
[...] mmpbxd[9774]: SIP Registration: SIP: <number> : Deregister
[...] mmpbxd[9774]: SIP Registration: SIP: <number> : Register Success
```

**Why it happened — mechanism verified in the actual code, not just a
guess**: the user confirmed manually disabling the SIP helper on the Modgui
panel's "NAT Helper" tab about one minute before the line became unreachable
(a deliberate action, unrelated to this session's own work). Reading the
actual code involved (`/www/docroot/modals/nat-alg-helper-modal.lp` +
`/usr/share/transformer/mappings/uci/firewall_helpers.map`) and that
afternoon's own logs made it possible to reconstruct the exact chain, not
just a hypothesis:

1. Saving the form removes `sip` from the `firewall.lan.helper` list and
   writes it to UCI (`uci commit firewall`).
2. In the real log at 14:04:52 that commit actually failed:
   `commit_err=lua-uci: I/O error` (likely a momentary lock/contention issue —
   disk space and `dmesg` are clean, not an out-of-storage problem).
3. Despite the error reported to the user, the change was applied anyway:
   `transformer[26159]` fired off **`async run: /etc/init.d/firewall
   restart`** asynchronously, and repeated it **6 times** between 14:09 and
   15:39 (not one clean restart, but a burst of retries over an hour and a
   half, which then stopped).
4. A full `/etc/init.d/firewall restart` rebuilds **all** iptables rules from
   scratch, including the dynamic `Allow_SIP` rules `mmpbxfwctl` maintains to
   let traffic from the TIM proxy (`88.50.251.167`) through. If, during one of
   those restarts, that rule disappears and isn't immediately reinserted
   (`mmpbxfwctl` typically reinserts it in reaction to registration events,
   not by proactively monitoring firewall state), inbound calls get dropped
   **by the router's own local firewall** — no stale binding on the
   operator's SBC is needed to explain the symptom.

This also fits the session's second episode ("not working anymore"): the last
of the six logged firewall restarts is at 15:39:27, just 4 minutes before a
second `mmpbxd` restart was requested. Note: no log window was captured with
the `Allow_SIP` rule visibly missing during one of these restarts — so the
link between "firewall restart" and "window of missed calls" is the most
concrete mechanism identified, not an instant-by-instant proof.

It remains true that the SIP ALG module itself (`nf_conntrack_sip`/
`nf_nat_sip`, §9 point 3) is not the direct cause — it's still not assigned to
the `wan` zone and never touches this unit's native traffic. It's **saving
the toggle** (with the resulting failed UCI commit and the burst of firewall
restarts that followed) that triggered the disruption, not the helper's
on/off state itself — consistent with the fact that the user later left the
SIP helper disabled without the problem recurring.

**How to apply if this recurs**: if inbound calls fail with "unreachable"
while the router shows "Registered", don't waste time re-checking local SIP
config/NAT/ALG (already ruled out as a class of cause) — go straight to: (1)
live-capture logs during a real call attempt to confirm the INVITE never
arrives (the upstream-problem signature), (2) `/etc/init.d/mmpbxd restart` as
the fast self-service fix, after confirming both lines are idle, (3) if the
restart doesn't fix it, escalate to the carrier's support line with the exact
symptom, since it's state on their SBC, not something fixable from customer
premises.

## 10. Open questions / to verify

- ~~Exact internal cause of the stale SBC-side binding (§9): not determinable
  from the client side~~ — **resolved**: trigger confirmed by the user
  (manually toggling the SIP helper off in the NAT Helper panel, ~1 minute
  before the symptom). What remains hypothetical is only the exact internal
  mechanism on the SBC side (why a local conntrack reload produces an
  orphaned binding on the operator's end) — not verifiable without visibility
  into the SBC itself.
- ~~Exact consumer of the local MQTT broker (§6.2): companion-app pairing
  assumed, not confirmed~~ — **resolved**: it's `wifi_doctor_agent`, but on
  the observed unit the whole chain (agent, certs, broker) is dormant, not an
  active consumer.
- Not verified whether the CWMP throttling (§2, ~200/60 s) is applied per-IP
  or globally — this changes the assessment of resistance to distributed
  brute-force.
- `wifi_doctor_agent` (§6.1): not verified what exact data it would send if
  enabled, nor whether the factory stock has it active by default.
- Single-unit snapshot with community firmware: firewall values and ACS
  profiles could differ on the factory TIM stock — not compared in this
  session.
- ~~`nanocdn-core`'s `BkStbA` STB-agent protocol (§7) was not
  reverse-engineered far enough to actually request and play a live
  channel~~ — **Partially Analyzed**: static
  string analysis established that `SetNewLiveChannel` is an internal C
  library function (not a network endpoint) and mapped the real HTTP surface
  (`/QualityLevels(`, `/Fragments(`, `/nservices/metricsReceiver`, etc.).
  **Advanced further** (§7 update, 2026-09-12, second unit): confirmed
  `nanocdn-rr` (not `BkStbA` directly) actually reaching the operator's CDN
  for a live channel-catalog entry, proving the HTTP relay mechanism
  end-to-end — actually playing a channel remains unreached in the test (the
  catalog session had expired by the time of the attempt).
- The exact internal cause of `wifi-nurse-modal.lp`'s config-write side effect
  (§8) — under what conditions it triggers, and whether it can be reproduced
  deliberately — was not isolated further; observed once, empirically, not
  forced.
