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

## 7. Open questions / to verify

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
