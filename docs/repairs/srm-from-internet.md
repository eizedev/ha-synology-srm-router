# Repair: the router can be managed from the internet

**Shown when** SRM allows access to its web interface from the internet on a router. Access points
are not checked: an access point's WAN port is your own network, and it is reachable from the
internet only through your router.

Anyone on the internet who finds the router can try to sign in, and a flaw in SRM would be open
to all of them, not only to your own network.

**What to do**

1. If you do not need SRM while away, switch off the setting in SRM that allows access to SRM from
   the internet.
2. If you do need it, prefer a VPN to your network (SRM can run a VPN server), and keep two-factor
   authentication on for the accounts people sign in with, and the auto block on.

The repair disappears at the next slow update (every 5 minutes by default) after the setting is
off. If you keep the access on purpose, ignore the repair in Home Assistant.
