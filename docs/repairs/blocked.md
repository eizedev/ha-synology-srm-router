# Repair: the device blocks Home Assistant

**Shown when** SRM's auto block refuses logins from Home Assistant's address after failed
attempts. The device is not read while the block lasts.

**What to do**

1. In SRM, open the auto block settings and remove Home Assistant's address from the blocked
   list, or wait until the block expires.
2. Check that the password Home Assistant uses is still right; a wrong one is what usually causes
   the block. If it changed, Home Assistant asks you to sign in again.

Home Assistant tries to log in again every 15 minutes; each attempt counts towards the block, so a
wrong password keeps the block alive. The repair disappears after the next successful update.
