# XUPnP / xupnpd — UPnP/DLNA IPTV relay for clients without multicast support (e.g. Fire TV Stick)

Done on an already-rooted DGA4130/VBNT-K unit (modgui/Ansuel), with the goal
of having an IPTV decoder/relay reachable by a UPnP/DLNA client behind the
modem (typically a Fire TV Stick, which has no native support for the IPTV
multicast many ISPs use to distribute channels).

## 1. The "installed" flag bug in modgui's App Store

The modgui panel (`http://<router>:4044/ui/` once installed) offers XUPnP as
an installable app in its built-in "App Store". If the install is triggered
and the download fails, **the UCI flag stays stuck at "installed" anyway** —
a real bug, not specific to this unit: see
[Ansuel/tch-nginx-gui#940](https://github.com/Ansuel/tch-nginx-gui/issues/940)
for an identical report on another DGA4130.

Root cause: `app_xupnp()` in
`/usr/share/transformer/scripts/appInstallRemoveUtility.sh` runs
`opkg install xupnpd` and sets `modgui.app.xupnp_app="1"` **without checking
the command's exit status**. Fix and instructions:
[`xupnpd-iptv/appInstallRemoveUtility.sh.patch.md`](xupnpd-iptv/appInstallRemoveUtility.sh.patch.md).

## 2. The `xupnpd` package can no longer be obtained from any known opkg feed

Unlike most other modgui apps, `xupnpd` **is not part of Ansuel's generic
`GUI_ipk` feed** (checked the `base/`, `packages/`, `routing/`, `telephony/`,
`target/packages/` folders on the `kernel-4.1` branch, which otherwise
matches this router family's kernel 4.1.52). The community repos that used
to serve it (`repository.ilpuntotecnico(eadsl).com/.../roleo/public/agtef/...`)
are both offline. Even the project's own site (`xupnpd.org`) has expired and
is now squatted by an unrelated third party — **don't trust links found
there**.

The only remaining path is compiling xupnpd from the official source:
[clark15b/xupnpd](https://github.com/clark15b/xupnpd) (C++ core + embedded
Lua 5.3, no releases published, source only).

## 3. Cross-compiling for this router's exact ABI

The target ABI is **not** the obvious one: despite having a VFP-capable
Cortex-A9 CPU, this OpenWrt/TCH build uses **soft-float**, not hard-float.
Confirmed by pulling `/bin/busybox` off the router and inspecting it with
`readelf -A` / `readelf -h`:

```
ELF 32-bit LSB executable, ARM, EABI5 version 1 (SYSV) ...
Flags: 0x5000200, Version5 EABI, soft-float ABI
```

dynamic userland, but on **glibc 2.27** (old, 2018).

Toolchain issues hit, in order:

1. **Bootlin no longer ships a standalone soft-float `armv7-eabi` toolchain**
   — only `armv7-eabihf` (hard-float), which would crash on any floating
   point operation on this router (different calling convention). Used
   Debian's `gcc-arm-linux-gnueabi` / `g++-arm-linux-gnueabi` /
   `libc6-dev-armel-cross` instead (armel = soft-float, the right ABI).
2. Debian's cross-toolchain ships **glibc 2.41** for the target — too new to
   dynamically link against the router's 2.27 safely (real risk of
   `GLIBC_2.3x not found` at runtime). **Fix: static linking**
   (`-static -marm -march=armv7-a -mfloat-abi=soft`), which removes the
   runtime glibc dependency entirely — see
   [`xupnpd-iptv/Makefile.armel-tim`](xupnpd-iptv/Makefile.armel-tim). Known
   side effect: `dlopen`/`gethostbyname` remain fragile in a static glibc
   binary (link-time warnings), so hostname-based DNS resolution inside the
   binary may not be reliable — not an issue for IP/multicast relay, which
   is the primary use case.
3. xupnpd's `rules.mk` expects the Lua directory (`lua-5.3.5/`) to contain
   Lua's `.c` sources directly, not a full tarball extraction with its own
   `src/` subdir. Needs flattening one level:
   `mv lua-5.3.5/src/* lua-5.3.5/ && rmdir lua-5.3.5/src` before building,
   otherwise `make -C lua-5.3.5 a` fails with "No rule to make target 'a'".

## 4. Deploying to the router

Copied the whole runtime tree — not just the binary and the app's `.lua`
files, but also `www/`, `ui/`, `plugins/`, `profiles/`, `config/` from the
built repo — to **`/opt/xupnpd`, on USB storage** (not the internal overlay,
which on these routers typically only has a few dozen MB free).

Watch out: `xupnpd.lua` must start with `cfg={}` and end with
`dofile('xupnpd_main.lua')` — that line is what actually starts the server.
A first attempt with a hand-trimmed config missing both lines crash-looped
under procd
(`xupnpd.lua:2: attempt to index a nil value (global 'cfg')`). Always start
from the upstream template and only change what's needed — see
[`xupnpd-iptv/xupnpd.lua.example`](xupnpd-iptv/xupnpd.lua.example) for the
lines that actually need changing (LAN interface, IPTV multicast interface,
HTTP port).

procd service: [`xupnpd-iptv/xupnpd.init`](xupnpd-iptv/xupnpd.init)
(`/etc/init.d/xupnpd`, starts automatically on boot).

To keep modgui's App Store consistent with reality:

```sh
ln -sfn /opt/xupnpd /usr/share/xupnpd   # 04_config.sh detects the app from this dir
uci set modgui.app.xupnp_app=1
uci commit modgui
```

## 5. Verification

```sh
curl -s -D - -o /dev/null http://<router-ip>:4044/
# HTTP/1.1 301 Moved Permanently
# Server: eXtensible UPnP agent
# Location: ui/
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://<router-ip>:4044/ui/
# HTTP 200
```

Note: the service binds to the LAN bridge's IP (`br-lan`), not
`127.0.0.1` — a local `curl` on the router itself needs to target the LAN
IP, not loopback.

## 6. From an empty player to the operator's real channel catalog (Broadpeak nanoCDN)

A freshly installed xupnpd is a UPnP/DLNA player with no content: it needs a
channel catalog. On this operator that catalog is not a static playlist: it
is generated live by the same Broadpeak nanoCDN stack
(`nanocdn-core`/`nanocdn-rr`, see
[`NETWORK-SECURITY-EN.md`](NETWORK-SECURITY-EN.md) §7) the router already
runs for the operator's own official decoder.

### 6.1 The live catalog format

`nanocdn-core` receives, on the same multicast control channel documented in
§7 (`239.200.0.0:5004`, on the dedicated IPTV VLAN), a plain-text list,
refreshed periodically, with lines shaped like this:

```
<origin-cdn-host>/<channel-path>;mi=<multicast-ip>&mp=<port>&sri=<stream-name>&...&rto=<timeout>
```

`origin-cdn-host` is a hostname on the operator's own internal CDN (a domain
like `*.cb.<operator-cdn>.it`, or a third-party domain for content delivered
under partnership with an external provider), `mi`/`mp` are the matching
multicast stream's address/port, `sri` a session identifier. These
parameters have a short validity window: a stale catalog produces entries
that genuinely reach the operator's CDN but answer 404, because that
specific session no longer exists.

A small script that watches that file and turns it into an M3U playlist (one
`#EXTINF` line plus the origin URL, verbatim) covers the simple case — just
reference it in the `playlist={}` table of this repo's
[`xupnpd.lua.example`](xupnpd-iptv/xupnpd.lua.example). The tricky part is
that it needs to be **regenerated continuously**, not read once at boot.

### 6.2 Why those URLs don't work out of the box

The catalog's hostnames belong to the operator's CDN, publicly reachable
over the Internet. On the operator's own official decoder, those same
hostnames are resolved locally to the router's own IP via a dedicated DNS
entry (`dnsmasq`), instead of going out to the Internet: the router itself
then serves them through nanoCDN's "Request Router" module (`nanocdn-rr`),
which behaves like an HTTP proxy keyed on the request's `Host:` header — if
it matches a known CDN hostname, it answers from the local multicast buffer,
otherwise it forwards the request to the real CDN.

To use xupnpd the same way (since it also runs on the router), the same
local DNS entry needs to be replicated for the catalog's hostnames, plus a
NAT rule that steers HTTP requests to the real port `nanocdn-rr` listens on
(see the update in [`NETWORK-SECURITY-EN.md`](NETWORK-SECURITY-EN.md) §7 on
the real port, different from the one in the config file) — covering both
traffic coming from the LAN and traffic the router itself generates, since
xupnpd issues the HTTP request server-side, locally.

### 6.3 Version pitfall: newer config than the binary

Trying to restart `nanocdn-rr` with the current shared config file
(`--conf`) can plausibly cause a total bind failure (see the update in §7 of
[`NETWORK-SECURITY-EN.md`](NETWORK-SECURITY-EN.md)): the config gets updated
remotely by the operator (ACS/CWMP channel, already documented in this
repo), while the binary installed on the firmware stays at whatever version
the router was rooted with — a mismatch that shows up as unrecognized
`rr-*` options in the logs. In that case the only way observed to bring it
back to a working state is starting it **without** `--conf` (on its
compiled-in defaults): the file's advanced settings are lost, but the basic
HTTP relay — the part xupnpd actually needs — comes back up.

## Next steps (not covered here)

- Set up a UPnP/DLNA client on the device that will play the channels (e.g.
  BubbleUPnP or VLC on a Fire TV Stick).
