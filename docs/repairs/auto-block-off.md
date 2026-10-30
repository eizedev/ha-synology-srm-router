# Repair: the auto block is off

**Shown when** SRM's auto block is switched off on a router.

The auto block stops an address after a number of failed logins within a few minutes. Without it,
nothing stops anyone from trying one password after another, from your network or, if SRM is
reachable from the internet, from anywhere.

**What to do**

Switch the auto block on in SRM, with a number of attempts and minutes that fits you. Home Assistant counts towards it too: with a wrong password it can block itself, see
[the device blocks Home Assistant](blocked.md).

The repair disappears at the next slow update (every 5 minutes by default) after the auto block is
on.
