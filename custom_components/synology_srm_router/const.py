"""Constants for the Synology SRM Router integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "synology_srm_router"
LOGGER = logging.getLogger(__package__)

CONF_USE_HTTPS: Final = "use_https"
CONF_FINGERPRINT: Final = "fingerprint"
CONF_VERIFY_CERTIFICATE: Final = "verify_certificate"
CONF_TRACKED: Final = "tracked"
CONF_TRACK_ALL: Final = "track_all"
CONF_FAST_INTERVAL: Final = "fast_interval"
CONF_SLOW_INTERVAL: Final = "slow_interval"
CONF_IS_ROUTER: Final = "is_router"
CONF_CONSIDER_HOME: Final = "consider_home"
CONF_SHOW_ALL: Final = "show_all"
# An access point next to a router keeps its own trackers (by default the router keeps all).
CONF_OWN_TRACKERS: Final = "own_trackers"
CONF_FIREWALL_HITS: Final = "firewall_hits"

DEFAULT_HTTPS_PORT: Final = 8001
DEFAULT_HTTP_PORT: Final = 8000
DEFAULT_USERNAME: Final = "admin"
# Clients, Wi-Fi, load and WAN change quickly; firmware, uptime and DHCP rarely.
DEFAULT_FAST_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_SLOW_INTERVAL: Final = timedelta(minutes=5)
MIN_FAST_INTERVAL: Final = 10
MIN_SLOW_INTERVAL: Final = 60
# A client counts as away only after it was missing this long. SRM marks idle wired clients offline
# for a minute now and then; the value matches Home Assistant's default for router trackers.
DEFAULT_CONSIDER_HOME: Final = timedelta(minutes=3)
# Clients seen online this recently are offered for tracking even while they are away.
RECENTLY_SEEN: Final = timedelta(days=30)
# Every update must finish well before the next one, even when the router answers slowly.
UPDATE_TIMEOUT: Final = 25
# One read may take this long; several run per update, so it stays well below UPDATE_TIMEOUT.
REQUEST_TIMEOUT: Final = 10
# After SRM's auto block, try to log in again this often (each attempt counts towards the block).
BLOCKED_RETRY: Final = timedelta(minutes=15)
# A tracker keeps its last trusted location this long while the device it was on cannot be read.
LOCATION_GRACE: Final = timedelta(minutes=10)

DOCS_URL: Final = "https://ha-synology-srm-router.eize.dev/"

# SRM keeps one session per account and session name: a second login under the same name ends the
# first (measured). Each Home Assistant installation, and its setup dialog, logs in under its own.
SESSION_NAME: Final = "HomeAssistant"
