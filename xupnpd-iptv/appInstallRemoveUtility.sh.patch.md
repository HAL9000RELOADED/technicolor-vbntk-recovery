# modgui App Store install-flag bug — fix

File: `/usr/share/transformer/scripts/appInstallRemoveUtility.sh` (part of the
Ansuel modgui firmware mod, not stock TCH/AGTEF).

## Bug

`app_xupnp()`'s `install()` function sets the UCI "installed" flag
unconditionally, with no check on whether `opkg install` actually succeeded:

```sh
app_xupnp() {
  install() {
    opkg update
    opkg install xupnpd
    uci set modgui.app.xupnp_app="1"
    uci commit modgui
  }
  ...
```

If `opkg install xupnpd` fails (e.g. the configured feed is unreachable/dead —
see the main write-up), the UCI flag is still set to `1`, so the modgui web UI
keeps showing "XUPnP installed" forever even though nothing was actually
installed. The "Remove" button then fails too, since there's nothing to
remove. Matches a report on Ansuel's tracker:
[Ansuel/tch-nginx-gui#940](https://github.com/Ansuel/tch-nginx-gui/issues/940).

## Fix

Reset the stale flag to the real state, then patch the function to only set
the flag on success:

```sh
uci set modgui.app.xupnp_app='0'
uci commit modgui
```

```sh
app_xupnp() {
  install() {
    opkg update
    if opkg install xupnpd; then
      uci set modgui.app.xupnp_app="1"
    else
      uci set modgui.app.xupnp_app="0"
      logger -t modgui "xupnpd install failed: opkg could not find/install the package"
    fi
    uci commit modgui
  }
  ...
```

Back up the original file before editing
(`cp appInstallRemoveUtility.sh appInstallRemoveUtility.sh.bak`).
