# Changelog dettagliato AGTEF (diff reali) — companion di VERSION-CHANGELOG-IT.md

Questo file è un complemento a [`VERSION-CHANGELOG-IT.md`](VERSION-CHANGELOG-IT.md): dove quel changelog riassume in prosa cosa cambia tra una versione e l'altra, qui c'è il **contenuto reale dei diff** dei file di configurazione principali (`dropbear`, `firewall`, `system`, `network`, `inittab`, `openwrt_release`, `nginx.conf`, ecc.), riga per riga, non solo conteggi o nomi di file.

Aggiunge anche due versioni non presenti nell'altro changelog: **`2.0.1`** (distinta da `2.0.1_003`, tra `2.0.1_003` e `2.2.0`) e **`2.4.4`** (tra `2.4.1` e `2.4.5`).

Generato analizzando il rootfs reale estratto da ciascun `.rbi` (decrittato con la chiave OSCK board VBNT-K, squashfs scompattato). Ogni sezione confronta una versione con quella immediatamente precedente nella sequenza cronologica osservata. Le transizioni che coinvolgono `2.4.1` e `2.4.5` usano ri-estrazioni pulite dai `.rbi` originali (non le cartelle di lavoro usate per il rooting SSH in questa stessa sessione), per lo stesso motivo documentato in [`RBI-FORMAT-IT.md` §3.7](RBI-FORMAT-IT.md#37-245-closed-vs-patched).

## 1.0.3 -> 1.0.4

**Kernel**: `3.4.11` -> `3.4.11, 3.4.11-rt19`

**openwrt_release cambiato:**
```diff
--- 
+++ 
@@ -1,6 +1,6 @@
 DISTRIB_ID='OpenWrt'
 DISTRIB_RELEASE='Chaos Calmer'
-DISTRIB_REVISION='r49389'
+DISTRIB_REVISION='r48709'
 DISTRIB_CODENAME='chaos_calmer'
 DISTRIB_TARGET='brcm63xx-tch/VBNTK'
 DISTRIB_DESCRIPTION='OpenWrt Chaos Calmer 15.05.1'
```

**Servizi aggiunti** (`/etc/init.d/`): cgevent, dlnad, fseventd, gre-hotspotd, mud, mvfs, pinholehelper, prozone, redirecthelper, select_vbntk_brcm_country_map, sfpmon, softswitch

**Servizi rimossi** (`/etc/init.d/`): minidlna, minidlna-procd, mmdbd

**File totali**: 4052 -> 4285 (707 aggiunti, 474 rimossi, confronto contenuto su 3578 comuni)

Aggiunti per area: lib(366), usr(251), etc(80), www(10)

Rimossi per area: lib(351), usr(64), etc(33), www(25), sbin(1)

**Modifiche di configurazione (diff reale):**

`etc/config/dropbear`:
```diff
--- 
+++ 
@@ -1,6 +1,17 @@
-config dropbear
-option enable '0'
+#NG-88913
+
+config dropbear 'lan'
+	option enable '0'
+	option IdleTimeout	'600'	
 	option PasswordAuth 'on'
-	option RootPasswordAuth 'off'
-	option Port         '22'
-#	option BannerFile   '/etc/banner'
+	option Port '22'
+	option Interface 'lan'
+
+config dropbear 'wan'
+	option enable '0'
+	option Interface 'wan'
+	option PasswordAuth 'on'
+	option RootPasswordAuth 'on'
+	option Port '22'
+	option IdleTimeout '600'
+
```

`etc/config/firewall`:
```diff
--- 
+++ 
@@ -1,2 +1,2 @@
-#NG-57986; NG-85491
+#NG-57986; NG-85491; NG-90907
 
@@ -58,3 +58,11 @@
 
-
+#NG-90907 Firewall is Stateless for IPv4
+config rule 'Drop_non_TCP_SYN'
+	option name		'Drop_non_TCP_SYN'
+	option src		'wan'
+	option dest		'*'
+	option proto	'tcp'
+	option target	'DROP'
+	option extra	'! --tcp-flags ALL SYN'
+	
 config rule 'drop_lan_2_z_wlnetb24'
@@ -342,2 +350,11 @@
 
+#NG-92911 enable/disable ssh/dropbear for wan
+config rule 'SSH_wan'
+	option name 'SSH_wan'
+	option src 'wan'
+	option proto 'tcp'
+	option dest_port '22'
+	option target 'DROP'
+	option family 'ipv4'
+	
 # include a file with users custom iptables rules
@@ -395,2 +412,7 @@
 
+config rulesgroup 'pinholerules'
+	option enabled		 '1'
+	option name		 'FW rules for opening pinholes'
+	option type		 'pinholerule'
+
 config redirectsgroup 'userredirects'
```

`etc/config/system`:
```diff
--- 
+++ 
@@ -6,3 +6,5 @@
 	option network_timezone 0
-
+#NG-102268 Enlarge the default log buffer size
+	option log_buffer_size '4096'
+	
 config timeserver ntp
@@ -27 +29,2 @@
 	option path 'logread'
+
```

`etc/inittab`:
```diff
--- 
+++ 
@@ -2,2 +2,2 @@
 ::shutdown:/etc/init.d/rcS K shutdown
-#::askconsole:/bin/login
+#::askconsolelate:/bin/login
```

`etc/openwrt_release`:
```diff
--- 
+++ 
@@ -2,3 +2,3 @@
 DISTRIB_RELEASE='Chaos Calmer'
-DISTRIB_REVISION='r49389'
+DISTRIB_REVISION='r48709'
 DISTRIB_CODENAME='chaos_calmer'
```

`etc/nginx/nginx.conf`:
```diff
--- 
+++ 
@@ -81,3 +81,7 @@
               local mgr = require("web.sessioncontrol").getmgr()
-              mgr:checkrequest()
+	      if ngx.req.get_uri_args().auto_update == "true" then
+                 mgr:checkrequest(true)
+              else
+                 mgr:checkrequest()
+              end
               mgr:handleAuth()
@@ -122,14 +126,41 @@
               for k, v in pairs(getargs) do
-                 local assistant = assistance.getAssistant(k)
-                 local enable, mode, pwdcfg, pwd = string.match(string.untaint(v), "(.*)_(.*)_(.*)_(.*)")
-                 if pwdcfg == "random" then
-                    pwd=nil
-                 elseif pwdcfg == "keep" then
-                    pwd=false
-                 end
-                 if enable == "on" then
-                   assistant:enable(true, mode=="permanent", pwd)
-                 elseif enable == "off" then
-                   assistant:enable(false, mode=="permanent", pwd)
-                 end
+                local assistant = assistance.getAssistant(k)
+                local enable, mode, pwdcfg, pwd = string.match(string.untaint(v), "(.*)_(.*)_(.*)_(.*)")
+                if pwdcfg == "random" then
+                  pwd=nil
+                elseif pwdcfg == "keep" then
+                  pwd=false
+                elseif pwdcfg == "srpuci" then
+                  local dm = require("datamodel")
+                  local srp_pair, user_map = {}, {}
+                  local cfg=dm.get("uci.web.user.")
+                  if cfg then
+                    for _, entry in ipairs(cfg) do
+                      local ra_name = string.match(string.untaint(entry.path),"%.@([^.]*)%.")
+                      if ra_name then
+                        if entry.param == "name" then
+                          user_map[entry.value] = ra_name
+                        end
+                        if (entry.param == "srp_salt" or entry.param == "srp_verifier") and entry.value ~= "" then
+                          srp_pair[ra_name] = srp_pair[ra_name] or {}
+                          srp_pair[ra_name][string.match(entry.param, "srp_(.*)")] = string.untaint(entry.value)
+                        end
+                      end
+                    end
+                  end
+
+                  local result = dm.get("uci.web.assistance.@" .. k .. ".user")
+                  if result then
+                    local user = result[1].value
+                    pwd = srp_pair[user_map[user]]
+                  end
+                  if pwd and (not pwd["salt"] or not pwd["verifier"]) then
+                    pwd = nil
+                  end
+                end
+                if enable == "on" then
+                  assistant:enable(true, mode=="permanent", pwd)
+                elseif enable == "off" then
+                  assistant:enable(false, mode=="permanent", pwd)
+                end
               end
```

`etc/config/wireless`:
```diff
--- 
+++ 
@@ -14,3 +14,3 @@
         option ht_security_restriction '1'
-        option sgi '0'
+        option sgi '1'
         option cdd '0'
@@ -37,4 +37,4 @@
         option acs_channel_monitor_period '5'
-        option tx_power_adjust '0'
-        option tx_power_overrule_reg '0'
+        option tx_power_adjust '+2'
+        option tx_power_overrule_reg '1'
 
@@ -56,3 +56,3 @@
         option security_mode 'wpa2-psk'
-        option supported_security_modes 'none wep wpa2-psk wpa-wpa2-psk wpa2 wpa-wpa2'
+        option supported_security_modes 'none wep wpa2-psk wpa-wpa2-psk'
         option pmf 'disabled'
```

## 1.0.4 -> 1.1.2

**openwrt_release cambiato:**
```diff
--- 
+++ 
@@ -1,6 +1,6 @@
 DISTRIB_ID='OpenWrt'
 DISTRIB_RELEASE='Chaos Calmer'
-DISTRIB_REVISION='r48709'
+DISTRIB_REVISION='r46610'
 DISTRIB_CODENAME='chaos_calmer'
 DISTRIB_TARGET='brcm63xx-tch/VBNTK'
 DISTRIB_DESCRIPTION='OpenWrt Chaos Calmer 15.05.1'
```

**Servizi aggiunti** (`/etc/init.d/`): bcm-usb-support, datausaged, dosprotect, ewifi, fhcd, install-ipks, iperf, lcmd, mosquitto, rtfd, weburl, wfa-testsuite-daemon, wifi-conductor

**Servizi rimossi** (`/etc/init.d/`): cwmpdboot, dhcprelay, select_vbntk_brcm_country_map

**File totali**: 4285 -> 4553 (373 aggiunti, 105 rimossi, confronto contenuto su 4180 comuni)

Aggiunti per area: usr(255), etc(89), lib(15), www(9), sbin(3), bin(1), opt(1)

Rimossi per area: usr(65), etc(31), lib(9)

**Modifiche di configurazione (diff reale):**

`etc/config/dropbear`:
```diff
--- 
+++ 
@@ -6,12 +6,11 @@
 	option PasswordAuth 'on'
-	option Port '22'
-	option Interface 'lan'
+	option Port         '22'
+	option Interface 'lan'		
+#	option BannerFile   '/etc/banner'
 
 config dropbear 'wan'
-	option enable '0'
-	option Interface 'wan'
-	option PasswordAuth 'on'
-	option RootPasswordAuth 'on'
-	option Port '22'
-	option IdleTimeout '600'
-
+    option enable           '0'
+	option IdleTimeout		'600'	
+    option PasswordAuth     'on'
+    option Port             '22'
+    option Interface        'wan'
```

`etc/config/firewall`:
```diff
--- 
+++ 
@@ -11,3 +11,3 @@
 
-config zone
+config zone 'lan'
 	option name		 lan
@@ -21,3 +21,3 @@
 
-config zone
+config zone 'wan'
 	option name		 wan
@@ -35,3 +35,3 @@
 
-config forwarding
+config forwarding 'lan_wan'
 	option src		 lan
@@ -216,2 +216,23 @@
 	
+config zone 'public_lan'
+        option name              public_lan
+        list network             'public_lan'
+        option input             ACCEPT
+        option output            ACCEPT
+        option forward           ACCEPT
+        option wan               0
+        option log               1
+        option log_limit         5/minute
+
+config forwarding 'public_lan_wan'
+        option src               'public_lan'
+        option dest              'wan'
+        option name              'subnet_out'
+        option enabled           '1'
+
+config forwarding 'wan_public_lan'
+        option src               'wan'
+        option dest              'public_lan'
+        option name              'subnet_in'
+        option enabled           '1'
 # We need to accept udp packets on port 68,
@@ -350,2 +371,11 @@
 
+config rule 'rule13'
+	option name 'Allow-Ping6'
+	option src 'wan'
+	option proto 'icmp'
+	list icmp_type 'echo-request'
+	option family 'ipv6'
+	option target 'ACCEPT'
+	option enabled '0'
+
 #NG-92911 enable/disable ssh/dropbear for wan
@@ -359,2 +389,12 @@
 	
+# Reject LAN access to TCP services on CPE WAN address(es)
+config rule
+	option name		 'Restrict-TCP-LAN-Input'
+	option src		 'lan'
+	option dest_ip		 '!lan'
+	option proto		 'tcp'
+	option family		 'ipv4'
+	option extra		 '-m mark --mark 0/0x9000000' # exclude intercepted traffic
+	option target		 'REJECT'
+
 # include a file with users custom iptables rules
@@ -538,52 +578,52 @@
 
-config helper 'helper1'
-	option helper		 ftp
-	option dest_port	 21
-	option proto		 tcp
-
-config helper 'helper2'
-	option helper		 tftp
-	option dest_port	 69
-	option proto		 udp
-
-config helper 'helper3'
-	option helper		 snmp
-	option family		 ipv4
-	option dest_port	 161
-	option proto		 udp
-
-config helper 'helper4'
-	option helper		 pptp
-	option family		 ipv4
-	option dest_port	 1723
-	option proto		 tcp
-
-config helper 'helper5'
+config helper 'ftphelper'
+	option helper		 'ftp'
+	option dest_port	 '21'
+	option proto		 'tcp'
+
+config helper 'tftphelper'
+	option helper		 'tftp'
+	option dest_port	 '69'
+	option proto		 'udp'
+
+config helper 'snmphelper'
+	option helper		 'snmp'
+	option family		 'ipv4'
+	option dest_port	 '161'
+	option proto		 'udp'
+
+config helper 'pptphelper'
+	option helper		 'pptp'
+	option family		 'ipv4'
+	option dest_port	 '1723'
+	option proto		 'tcp'
+
+config helper 'siphelper'
 	option enable        0
-	option helper		 sip
-	option dest_port	 5060
-	option proto		 udp
-
-config helper 'helper6'
... (49 righe diff omesse)
```

`etc/config/system`:
```diff
--- 
+++ 
@@ -21,2 +21,6 @@
 	option import_unsigned	0
+	option import_restricted 1
+	option enable_usb3_support '0'
+	option enable_usb2_support '1'
+	option enable_usb1_support '1'
 
@@ -24,4 +28,5 @@
 	option reboot	'1'
-	option action	'compress'
+	option action	'upload'
 	option path	'/root'
+	option url	'https://internal-core.tgwfd.org:5443/'
 
@@ -30 +35,6 @@
 
+#Backup and restore support between different releases
+config importversion
+	option version_match 'AGTEF_%d%.%d.%d[_%d]*'
+	option importer '/etc/import/import_ti.lua'
+	
```

`etc/openwrt_release`:
```diff
--- 
+++ 
@@ -2,3 +2,3 @@
 DISTRIB_RELEASE='Chaos Calmer'
-DISTRIB_REVISION='r48709'
+DISTRIB_REVISION='r46610'
 DISTRIB_CODENAME='chaos_calmer'
```

`etc/nginx/nginx.conf`:
```diff
--- 
+++ 
@@ -77,2 +77,3 @@
 
+        # check the get args with auto_update param is true.
         location ^~ / {
```

`etc/config/wireless`:
```diff
--- 
+++ 
@@ -47,2 +47,3 @@
         option reliable_multicast '0'
+		option uapsd '0'
 
@@ -67,3 +68,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode disabled
+        option acl_mode 'unlock'
         option acl_registration_time '60'
@@ -74,2 +75,3 @@
 		option display_connected_devices '1'
+        option bandsteer_id 'off'
 
@@ -99,2 +101,3 @@
         option txbf '1'
+		option acs_allowed_channels '36 40 44 48 52 56 60 64 100 104 108 112'
 
@@ -107,3 +110,4 @@
         option reliable_multicast '1'
-
+		option uapsd '0'
+		
 config wifi-ap 'ap1'
@@ -125,3 +129,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode disabled
+        option acl_mode 'unlock'
         option acl_registration_time '60'
@@ -133 +137,16 @@
 		option display_connected_devices '1'
+		option bandsteer_id 'off'
+config wifi-radius-server 'ap1_auth0'
+        option state '0'
+        option ip '0.0.0.0'
+        option port '1812'
+        option secret 'SET_BY_SCRIPT'
+        option priority '3'
+
+config wifi-bandsteer 'bs0'
+        option policy_mode '5'
+        option monitor_window '5'
+        option sta_comeback_to '5'
+        option debug_flags '3'
+        option rssi_5g_threshold '-80'
+        option rssi_threshold '-60'
```

`etc/config/dhcp`:
```diff
--- 
+++ 
@@ -1,2 +1,2 @@
-config dnsmasq
+config dnsmasq 'dnsmasq'
 	option domainneeded	 1
@@ -45,3 +45,2 @@
 	option ra_hoplimit	 64
-	option ra_max_mtu	 1500
 	option force		 '1'
@@ -89 +88,3 @@
 	option ignore		 '1'
+
+config relay 'relay'
```

## 1.1.2 -> 1.2.0_001

**File totali**: 4553 -> 4553 (0 aggiunti, 0 rimossi, confronto contenuto su 4553 comuni)

**Modifiche di configurazione (diff reale):**

`etc/config/firewall`:
```diff
--- 
+++ 
@@ -273,3 +273,3 @@
 	option proto		 icmp
-	list   icmp_type	 echo-request
+	#list   icmp_type	 echo-request
 	list   icmp_type	 echo-reply
```

`etc/config/network`:
```diff
--- 
+++ 
@@ -7,3 +7,7 @@
 
+#custo start TCOMITAGW-2157
+
 config globals globals
-	option ula_prefix none
+	option ula_prefix auto
+	
+#custo end TCOMITAGW-2157
```

## 1.2.0_001 -> 2.0.0

**File totali**: 4553 -> 4561 (8 aggiunti, 0 rimossi, confronto contenuto su 4553 comuni)

Aggiunti per area: usr(5), www(2), etc(1)

**Modifiche di configurazione (diff reale):**

`etc/config/network`:
```diff
--- 
+++ 
@@ -10,3 +10,3 @@
 config globals globals
-	option ula_prefix auto
+	option ula_prefix none
 	
```

`etc/config/wireless`:
```diff
--- 
+++ 
@@ -68,3 +68,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode 'unlock'
+        option acl_mode 'disabled'
         option acl_registration_time '60'
@@ -129,3 +129,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode 'unlock'
+        option acl_mode 'disabled'
         option acl_registration_time '60'
```

## 2.0.0 -> 2.0.0_002

**File totali**: 4561 -> 4559 (0 aggiunti, 2 rimossi, confronto contenuto su 4559 comuni)

Rimossi per area: usr(2)

**Modifiche di configurazione (diff reale):**

`etc/config/wireless`:
```diff
--- 
+++ 
@@ -68,3 +68,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode 'disabled'
+        option acl_mode 'unlock'
         option acl_registration_time '60'
@@ -129,3 +129,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode 'disabled'
+        option acl_mode 'unlock'
         option acl_registration_time '60'
```

## 2.0.0_002 -> 2.0.1_003

**File totali**: 4559 -> 4562 (3 aggiunti, 0 rimossi, confronto contenuto su 4559 comuni)

Aggiunti per area: usr(2), www(1)

**Modifiche di configurazione (diff reale):**

`etc/config/firewall`:
```diff
--- 
+++ 
@@ -73,2 +73,9 @@
 	option target	'DROP'
+
+config rule
+	option src 'lan'
+	option name 'Deny_CWMP_Conn_Reqs_from_LAN'
+	option proto 'tcp'
+	option dest_port '7170'
+	option target 'DROP'
 
```

`etc/config/wireless`:
```diff
--- 
+++ 
@@ -68,3 +68,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode 'unlock'
+        option acl_mode 'disabled'
         option acl_registration_time '60'
@@ -129,3 +129,3 @@
         option wps_ap_pin 'SET_BY_SCRIPT'
-        option acl_mode 'unlock'
+        option acl_mode 'disabled'
         option acl_registration_time '60'
```

## 2.0.1_003 -> 2.0.1

**File totali**: 4562 -> 4562 (0 aggiunti, 0 rimossi, confronto contenuto su 4562 comuni)

## 2.0.1 -> 2.2.0

(salt&ato, rootfs non disponibile)

## 2.2.0 -> 2.2.1

(salt&ato, rootfs non disponibile)

## 2.2.1 -> 2.3.2

**Kernel**: `4.1.38` -> `4.1.52`

**openwrt_release cambiato:**
```diff
--- 
+++ 
@@ -1,7 +1,7 @@
 DISTRIB_ID='OpenWrt'
-DISTRIB_RELEASE='Chaos Calmer'
-DISTRIB_REVISION='unknown'
-DISTRIB_CODENAME='chaos_calmer'
-DISTRIB_TARGET='brcm63xx-tch/VANTW'
-DISTRIB_DESCRIPTION='OpenWrt Chaos Calmer 15.05.1'
+DISTRIB_RELEASE='SNAPSHOT'
+DISTRIB_REVISION='r13941-6c08aeb78c'
+DISTRIB_TARGET='brcm6xxx-tch/VBNTJ_502L07p1'
+DISTRIB_ARCH='arm_cortex-a9'
+DISTRIB_DESCRIPTION='OpenWrt SNAPSHOT r13941-6c08aeb78c'
 DISTRIB_TAINTS='no-all glibc busybox'
```

**Servizi aggiunti** (`/etc/init.d/`): datausage_notifier, datausaged, gpio_switch, license_init.sh, multiap_agent, multiap_controller, nanocdn, sensors, urandom_seed, urngd, vopi_intfs, wireless, wlaffinity, wol

**Servizi rimossi** (`/etc/init.d/`): bcm_spdsvc, conntrackd, sfp-hisr-pppoe-graceful-restart, snmpd, sysctl-tch, wifi-conductor

**File totali**: 5807 -> 11953 (6900 aggiunti, 754 rimossi, confronto contenuto su 5053 comuni)

Aggiunti per area: chroot(4823), usr(1251), lib(315), etc(296), www(174), srv(27), sbin(5), bin(4), root(3), data(1), opt(1)

Rimossi per area: usr(374), lib(269), etc(79), srv(16), www(11), sbin(4), bin(1)

**Modifiche di configurazione (diff reale):**

`etc/config/dropbear`:
```diff
--- 
+++ 
@@ -4,3 +4,4 @@
 	option PasswordAuth 'on'
-	option RootPasswordAuth 'on'
+	option RootLogin '0'
+	option RootPasswordAuth '0'
 	option Port '22'
@@ -13,3 +14,3 @@
 	option PasswordAuth 'on'
-	option RootPasswordAuth 'on'
+	option RootPasswordAuth '0'
 	option Port '22'
@@ -23,3 +24,3 @@
 	option PasswordAuth 'on'
-	option RootPasswordAuth 'on'
+	option RootPasswordAuth '0'
 	option Port '22'
@@ -28,2 +29 @@
 	option AllowLocalForwarding '0'
-
```

`etc/config/firewall`:
```diff
--- 
+++ 
@@ -7,2 +7,11 @@
 	option drop_invalid '1'
+	option auto_helper '0'
+
+config zone 'loopback'
+	option name		 loopback
+	list   network		 'loopback'
+	option input		 ACCEPT
+	option output		 ACCEPT
+	option forward		 ACCEPT
+	list helper 'sip'
 
@@ -16,2 +25,9 @@
 	option wan '0'
+	list helper 'ftp'
+	list helper 'tftp'
+	list helper 'snmp'
+	list helper 'pptp'
+	list helper 'irc'
+	list helper 'amanda'
+	list helper 'rtsp'
 
@@ -29,2 +45,3 @@
 	option wan '1'
+	list helper 'ftp'
 
@@ -73,2 +90,16 @@
 
+config zone 'iptv'
+	option name 'iptv'
+	option input 'DROP'
+	option output 'ACCEPT'
+	option forward 'DROP'
+	option masq '1'
+	option mtu_fix '1'
+	option wan '1'
+	list network 'iptv'
+
+config forwarding 'lan_iptv'
+	option src 'lan'
+	option dest 'iptv'
+
 config rule 'Drop_non_TCP_SYN'
@@ -113,3 +144,3 @@
 	option src 'z_wlnetb24'
-	option proto 'igmp'
+	option proto 'icmp'
 	option target 'ACCEPT'
@@ -191,3 +222,3 @@
 	option src 'z_wlnetb5'
-	option proto 'igmp'
+	option proto 'icmp'
 	option target 'ACCEPT'
@@ -660,53 +691,2 @@
 
-config helper 'ftphelper'
-	option helper 'ftp'
-	option dest_port '21'
-	option proto 'tcp'
-
-config helper 'tftphelper'
-	option helper 'tftp'
-	option dest_port '69'
-	option proto 'udp'
-
-config helper 'snmphelper'
-	option helper 'snmp'
-	option family 'ipv4'
-	option dest_port '161'
-	option proto 'udp'
-
-config helper 'pptphelper'
-	option helper 'pptp'
-	option family 'ipv4'
-	option dest_port '1723'
-	option proto 'tcp'
-
-config helper 'siphelper'
-	option enable '0'
-	option helper 'sip'
-	option dest_port '5060'
-	option proto 'tcpudp'
-
-config helper 'siploopback'
-	option helper 'sip'
-	option dest_port '5060'
-	option proto 'tcpudp'
-	option intf 'loopback'
-
-config helper 'irchelper'
-	option helper 'irc'
-	option family 'ipv4'
-	option dest_port '6667'
-	option proto 'tcp'
-
-config helper 'amandahelper'
-	option helper 'amanda'
-	option dest_port '10080'
-	option proto 'udp'
-
-config helper 'rtsphelper'
-	option helper 'rtsp'
-	option dest_port '554'
-	option family 'ipv4'
-	option proto 'tcp'
-
 config include 'dhcpsnooper'
@@ -731,2 +711 @@
 	option reload '1'
-
```

`etc/config/system`:
```diff
--- 
+++ 
@@ -23,2 +23,3 @@
 	option reboot	'1'
+	list reboot_exceptions 'dnsmasq'
 	option action	'compress'
@@ -34 +35,14 @@
 	option rotate '0'
+
+config wifi-bandsteer 'bs0'
+	option last_state '1'
+	option bandsteer_last_state '1'
+
+config agent acotel
+	option enabled '1'
+
+config wifi-wps 'ap0'
+        option last_state '1'
+
+config wifi-wps 'ap1'
+        option last_state '1'
```

`etc/config/network`:
```diff
--- 
+++ 
@@ -1,9 +0,0 @@
-
-config interface loopback
-	option ifname	lo
-	option proto	static
-	option ipaddr	127.0.0.1
-	option netmask	255.0.0.0
-
-config globals globals
-	option ula_prefix auto
```

`etc/inittab`:
```diff
--- 
+++ 
@@ -2,2 +2,2 @@
 ::shutdown:/etc/init.d/rcS K shutdown
-#::askconsolelate:/bin/login
+#::askconsole:/bin/restricted_shell
```

`etc/openwrt_release`:
```diff
--- 
+++ 
@@ -1,7 +1,7 @@
 DISTRIB_ID='OpenWrt'
-DISTRIB_RELEASE='Chaos Calmer'
-DISTRIB_REVISION='unknown'
-DISTRIB_CODENAME='chaos_calmer'
-DISTRIB_TARGET='brcm63xx-tch/VANTW'
-DISTRIB_DESCRIPTION='OpenWrt Chaos Calmer 15.05.1'
+DISTRIB_RELEASE='SNAPSHOT'
+DISTRIB_REVISION='r13941-6c08aeb78c'
+DISTRIB_TARGET='brcm6xxx-tch/VBNTJ_502L07p1'
+DISTRIB_ARCH='arm_cortex-a9'
+DISTRIB_DESCRIPTION='OpenWrt SNAPSHOT r13941-6c08aeb78c'
 DISTRIB_TAINTS='no-all glibc busybox'
```

`etc/device_info`:
```diff
--- 
+++ 
@@ -1,2 +1,3 @@
 DEVICE_MANUFACTURER='OpenWrt'
+DEVICE_MANUFACTURER_URL='https://openwrt.org/'
 DEVICE_PRODUCT='Generic'
```

`etc/nginx/nginx.conf`:
```diff
--- 
+++ 
@@ -35,3 +35,4 @@
         sessioncontrol.setManagerForPort("default", "80")
-        sessioncontrol.setManagerForPort("assistance", "443")
+        sessioncontrol.setManagerForPort("default", "443")
+        sessioncontrol.setManagerForPort("assistance", "9443")
     ';
@@ -42,2 +43,4 @@
         listen       443 ssl;
+        listen       9443 ssl;
+
         # ipv6
@@ -45,2 +48,3 @@
         listen       [::]:443 ssl;
+        listen       [::]:9443 ssl;
 
@@ -110,4 +114,6 @@
             content_by_lua '
-				local role = require("webservice.accesscontrol_token").authenticate()
-				require("webservice.api").process(role)
+              local json = require("dkjson")
+              local ngx = ngx
+              ngx.header.content_type = "application/json"
+              ngx.print(json.encode({ error = { errorcode = "403", errormessage = "This is insecure way of accessing web API. Kindly upgrade to secure mechanism" }}, {indent = true}))
             ';
```

`etc/config/wireless`:
```diff
--- 
+++ 
@@ -20,3 +20,3 @@
 	option frame_bursting '0'
-	option interference_mode 'auto'
+	option interference_mode 'auto_w_noise'
 	option interference_channel_list '1 2 3 4 5 6 7 8 9 10 11 12 13'
@@ -26,2 +26,3 @@
 	option acs_chanim_tracing '0'
+	option acs_allowed_channels '1 6 11'
 	option acs_traffic_tracing '0'
@@ -38,3 +39,2 @@
 	option tx_power_overrule_reg '0'
-	option acs_allowed_channels '1 6 11'
 	option acs_rescan_period '86400'
@@ -43,2 +43,3 @@
 	option ldpc '1'
+    option rx_amsdu_in_ampdu '0'
 
@@ -49,5 +50,6 @@
 	option network 'lan'
-	option reliable_multicast '0'
-	option uapsd '0'
-	option ssid 'SET_BY_SCRIPT'
+	option reliable_multicast '1'
+	option uapsd '0'
+	option ssid 'SET_BY_SCRIPT'
+        option qos_prio_override '1'
 
@@ -103,3 +105,4 @@
 	option acs_allowed_channels '36 40 44 48 52 56 60 64 100 104 108 112'
-        option mumimo '0'
+	option mumimo '0'
+	option amsdu '0'
 
@@ -110,2 +113,3 @@
 	option network 'lan'
+        option ifname 'eth5'
 	option reliable_multicast '1'
@@ -113,2 +117,3 @@
 	option ssid 'SET_BY_SCRIPT'
+        option qos_prio_override '1'
 
@@ -153,2 +158,3 @@
 	option ssid 'SET_BY_SCRIPT'
+        option qos_prio_override '1'
 
@@ -198,2 +204,3 @@
 	option ssid 'SET_BY_SCRIPT'
+        option qos_prio_override '1'
 
@@ -225,8 +232,9 @@
 config wifi-bandsteer 'bs0'
-        option policy_mode '5'
-        option monitor_window '5'
-        option sta_comeback_to '5'
-        option debug_flags '0'
-        option rssi_5g_threshold '-80'
-        option rssi_threshold '-60'
-        option no_powersave_steer '0'
+        option state '1'
+	option policy_mode '5'
+	option monitor_window '5'
+	option sta_comeback_to '5'
+	option debug_flags '0'
+	option rssi_5g_threshold '-80'
+	option rssi_threshold '-60'
+	option no_powersave_steer '0'
```

## 2.3.2 -> 2.4.1

**openwrt_release cambiato:**
```diff
--- 
+++ 
@@ -1,7 +1,7 @@
 DISTRIB_ID='OpenWrt'
 DISTRIB_RELEASE='SNAPSHOT'
-DISTRIB_REVISION='r13941-6c08aeb78c'
+DISTRIB_REVISION='r14144-e2ae576c18'
 DISTRIB_TARGET='brcm6xxx-tch/VBNTJ_502L07p1'
 DISTRIB_ARCH='arm_cortex-a9'
-DISTRIB_DESCRIPTION='OpenWrt SNAPSHOT r13941-6c08aeb78c'
+DISTRIB_DESCRIPTION='OpenWrt SNAPSHOT r14144-e2ae576c18'
 DISTRIB_TAINTS='no-all glibc busybox'
```

**Servizi aggiunti** (`/etc/init.d/`): dnsfilter, memorystats

**File totali**: 11953 -> 7361 (243 aggiunti, 4835 rimossi, confronto contenuto su 7118 comuni)

Aggiunti per area: root(144), usr(43), etc(41), lib(9), srv(6)

Rimossi per area: chroot(4823), usr(6), lib(3), etc(1), sbin(1), srv(1)

**Modifiche di configurazione (diff reale):**

`etc/config/firewall`:
```diff
--- 
+++ 
@@ -32,2 +32,3 @@
 	list helper 'rtsp'
+	list helper 'ipsec'
 
@@ -711 +712,9 @@
 	option reload '1'
+
+config rule
+	option name 'Reject closed TCP connections'
+	option src 'lan'
+	option dest 'wan'
+	option proto 'tcp'
+	option extra '--tcp-flags SYN,RST,FIN NONE'
+	option target 'REJECT'
```

`etc/config/system`:
```diff
--- 
+++ 
@@ -23,3 +23,2 @@
 	option reboot	'1'
-	list reboot_exceptions 'dnsmasq'
 	option action	'compress'
@@ -37,3 +36,3 @@
 config wifi-bandsteer 'bs0'
-	option last_state '1'
+	option last_state '0'
 	option bandsteer_last_state '1'
@@ -41,3 +40,3 @@
 config agent acotel
-	option enabled '1'
+	option enabled '0'
 
```

`etc/openwrt_release`:
```diff
--- 
+++ 
@@ -2,6 +2,6 @@
 DISTRIB_RELEASE='SNAPSHOT'
-DISTRIB_REVISION='r13941-6c08aeb78c'
+DISTRIB_REVISION='r14144-e2ae576c18'
 DISTRIB_TARGET='brcm6xxx-tch/VBNTJ_502L07p1'
 DISTRIB_ARCH='arm_cortex-a9'
-DISTRIB_DESCRIPTION='OpenWrt SNAPSHOT r13941-6c08aeb78c'
+DISTRIB_DESCRIPTION='OpenWrt SNAPSHOT r14144-e2ae576c18'
 DISTRIB_TAINTS='no-all glibc busybox'
```

`etc/config/wireless`:
```diff
--- 
+++ 
@@ -70,3 +70,3 @@
 	option wsc_state 'configured'
-	option wps_ap_setup_locked '1'
+	option wps_ap_setup_locked '3'
 	option acl_mode 'disabled'
@@ -104,4 +104,5 @@
 	option txbf '1'
-	option acs_allowed_channels '36 40 44 48 52 56 60 64 100 104 108 112'
-	option mumimo '0'
+	option acs_allowed_channels '36 40 44 48 52 56 60 64 100 104 108'
+	option allowed_channels '36 40 44 48 52 56 60 64 100 104 108'
+        option mumimo '0'
 	option amsdu '0'
```

`etc/config/dhcp`:
```diff
--- 
+++ 
@@ -1,3 +1,2 @@
-
-config dnsmasq 'dnsmasq'
+config dnsmasq 'dnsmasq_lan'
 	option domainneeded '1'
@@ -14,2 +13,3 @@
 	option readethers '1'
+	list interface 'lan'
 	option leasefile '/tmp/dhcp.leases'
@@ -19,4 +19,27 @@
 	list hostname 'dsldevice'
+	list hostname 'localdevice.abrstream.tech'
 	option allservers '1'
 	option addmac '0'
+
+config dnsmasq 'dnsmasq_guest'
+	option domainneeded '1'
+	option boguspriv '1'
+	option filterwin2k '0'
+	option localise_queries '1'
+	option rebind_protection '1'
+	option rebind_localhost '1'
+	option local '/broadband/'
+	option domain 'broadband'
+	option expandhosts '1'
+	option nonegcache '0'
+	option authoritative '1'
+	option readethers '1'
+	option leasefile '/tmp/dhcp_guest.leases'
+	option resolvfile '/tmp/resolv.conf.auto'
+	option nonwildcard '1'
+	list interface 'wlnet_b_24'
+	list interface 'wlnet_b_5'
+	list notinterface 'loopback'
+	option strictorder '1'
+	option dhcpscript '/lib/dnsmasq/dhcp-event.sh'
 
@@ -27,2 +50,3 @@
 config dhcp 'lan'
+	option instance 'dnsmasq_lan'
 	option interface 'lan'
@@ -39,4 +63,6 @@
 	option force '1'
+	option ra_useleasetime '1'
 
 config dhcp 'wlnet_b_24'
+	option instance 'dnsmasq_guest'
 	option interface 'wlnet_b_24'
@@ -54,4 +80,6 @@
 	option limit '125'
+	option ra_useleasetime '1'
 
 config dhcp 'wlnet_b_5'
+	option instance 'dnsmasq_guest'
 	option interface 'wlnet_b_5'
@@ -69,2 +97,3 @@
 	option limit '125'
+	option ra_useleasetime '1'
 
@@ -91 +120,10 @@
 	option policy 'if1_mwan'
+
+config dhcp 'voip'
+	option interface 'voip'
+	option ignore '1'
+
+config dhcp 'voip6'
+	option interface 'voip'
+	option ignore '1'
+
```

## 2.4.1 -> 2.4.4

**File totali**: 7361 -> 7362 (1 aggiunti, 0 rimossi, confronto contenuto su 7361 comuni)

Aggiunti per area: lib(1)

**Nuovo file `lib/mount_root/00_overlay_threshold_check`** — script che controlla lo spazio usato dall'overlay e, se supera il 90%, cancella l'intera partizione `rootfs_data` e riavvia:

```sh
#!/bin/sh
# This script is to delete the content from the /etc/bulkdata/ of both the bank_1 & bank_2
MAX_USE_PERCENTAGE=90
get_use_percentage=$(df -h | awk '$NF == "/overlay" {print $(NF-1)}' | tr -d '%')

mtd_erase() {
    sync
    for mtd in "$@" ; do
        if grep -q $mtd /proc/mtd ; then
            mtd erase $mtd
        fi
    done
}

kill_writing_processes() {
    local sig=${1:-15}
    local OVERLAY_MOUNT=''
    [ -d /overlayfs ] && OVERLAY_MOUNT='/overlayfs'
    [ -d /overlay ]   && OVERLAY_MOUNT='/overlay'
    lsof $OVERLAY_MOUNT | awk '/ REG / { print $2} ' | uniq | while read p ; do
        if [ -d "/proc/$p" ] ; then
            kill -$sig $p
        fi
    done
}

erase_jffs2_partition() {
    local mount_point="$1"
    mount -type overlayfs -o ro,remount /
    umount -r "${mount_point}"
    kill_writing_processes 9
    mtd_erase 'rootfs_data'
}

if [ "$get_use_percentage" -gt "$MAX_USE_PERCENTAGE" ]; then
  erase_jffs2_partition /overlay
  sync
  reboot -f
fi
```

Modificati (oltre alla riga di versione in `etc/banner`/`etc/config/version`, build `3401135`→`3401180`, 2024-04-10→2024-09-26): `usr/bin/bulkdata` (ricompilato, 1 byte di differenza) e `etc/uci-defaults/tch_5000_versioncusto` (tabella mapping versione, aggiunte le voci per `2.4.3`/`2.4.4`).

## 2.4.4 -> 2.4.5

**File totali**: 7362 -> 7365 (3 aggiunti, 0 rimossi, confronto contenuto su 7362 comuni)

Aggiunti per area: etc(2), usr(1)

**Modifiche di configurazione (diff reale):**

`etc/config/cwmpd`:
```diff
-        option connectionrequest_throttle_number '100'
+        option connectionrequest_throttle_number '200'
```

`etc/init.d/wireless` e `etc/rc.d/S13wireless` (identiche, aggiungono una workaround marcata `NG-223325`):
```diff
+    #WAR for NG-223325
+    if [ "$(cat /proc/device-tree/model 2>/dev/null)" == "Broadcom BCM963138" ]; then
+        local OLD_PID=$(ps | grep mon_reinit.sh | grep -v grep | cut -d ' ' -f2)
+        if [ $OLD_PID ]; then
+             echo "Warning: mon_reinit.sh script is already running. Kill old script PID: $OLD_PID" > /dev/console
+             kill -9 $OLD_PID
+        fi
+        echo "Start mon_reinit.sh monitor script" > /dev/console
+        mon_reinit.sh &
+    fi
```
(collegata al nuovo binario `usr/sbin/mon_reinit.sh` introdotto in questa stessa versione — vedi §3.7 / VERSION-CHANGELOG-IT.md)

`etc/uci-defaults/tch_0030-network-wan`:
```diff
-        uci add_list qos.@reclassify[2].srcif='loopback'
-        uci set qos.waneth4=device
-        uci set qos.waneth4.pcp='5'
-        uci set qos.waneth4.force_pcp='0'
-        uci set qos.pcp_6=label
-        uci set qos.pcp_6.pcp='6'
-        uci add qos reclassify >/dev/null 2>/dev/null
-        uci set qos.@reclassify[-1].target='pcp_6'
-        uci set qos.@reclassify[-1].ports='7170,10500,10700'
-        uci set qos.@reclassify[-1].proto='tcp'
-        uci add_list qos.@reclassify[-1].srcif='loopback'
-        uci add_list qos.@reclassify[-1].dstif='wan'
+uci add network ppp_placeholder
+uci set network.@ppp_placeholder[0].uciname='pppoe-wan'
-uci commit qos
```

`etc/uci-defaults/tch_0090-remove`:
```diff
+file=/etc/ssl/certs/4ec17c6c.0
+if [ -f $file ] ; then
+    mkdir -p /etc/ssl/acs-cert/
+    cp $file /etc/ssl/acs-cert/
+fi
```

`etc/uci-defaults/tch_5001_LTE_2_Box`:
```diff
-uci set cwmpd.operationalACS2.acs_url="https://fwa.cdp.tim.it/cwmpWeb/CPEMgt"
+uci set cwmpd.operationalACS2.acs_url="https://mobile.acs.tim.it:11201/cwmpWeb/WGCPEMgt"
```

Più il consueto bump di versione/build (`etc/banner`, `etc/config/version`: `3401180`→`3401200`, 2024-09-26→2024-11-19; `etc/uci-defaults/tch_5000_versioncusto` aggiorna la tabella mapping per `2.4.5`) e i mapping WiFi/MultiAP/host già noti dal changelog prosa.
