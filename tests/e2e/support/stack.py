"""Where the stack under test is. compose.test.yaml sets these in the e2e container; the
defaults are the dev stack on this machine (scripts/fixture_to_test.sh), reached through the
control panel's proxy."""

from __future__ import annotations

import os

CONTROL_PANEL_URL = os.environ.get("CONTROL_PANEL_URL", "http://127.0.0.1:18091")
CONTROL_API_URL = os.environ.get("CONTROL_API_URL", f"{CONTROL_PANEL_URL}/_control/api")
DISCORD_SIM_URL = os.environ.get("DISCORD_SIM_URL", CONTROL_PANEL_URL)
WEB_URL = os.environ.get("WEB_URL", "http://127.0.0.1:18000")
# The chrome service's Playwright server. Unset, pytest-playwright starts a local Chromium.
PW_WS_ENDPOINT = os.environ.get("PW_WS_ENDPOINT")
