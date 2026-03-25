#!/usr/bin/env python3
"""
token_refresh.py — Auto-refresh Phygitals auth token from Chrome

Reads `privy:token` directly from Chrome's localStorage using AppleScript.
Requires: phygitals.com open in a Chrome tab, Chrome running on macOS.

Usage:
  python3 token_refresh.py              # prints token + updates config.py
  python3 token_refresh.py --check      # just show time remaining
"""

import subprocess
import json
import time
import sys
import re
from datetime import datetime, timezone

CONFIG_PATH = "config.py"

# ─── EXTRACT TOKEN FROM CHROME ────────────────────────────────────────────────

def get_token_from_chrome() -> str | None:
    """
    Uses AppleScript to read privy:token from localStorage of the
    phygitals.com tab in Chrome. No remote debugging port needed.
    """
    script = '''
    tell application "Google Chrome"
        set tabFound to false
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "phygitals.com" then
                    set result to execute t javascript "JSON.parse(localStorage.getItem('privy:token') || 'null')"
                    if result is not missing value then
                        return result
                    end if
                end if
            end repeat
        end repeat
        return ""
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        token = result.stdout.strip()
        if token and token.startswith("eyJ"):
            return "Bearer " + token
        return None
    except Exception as e:
        print(f"  AppleScript error: {e}")
        return None


def decode_token_expiry(token: str) -> dict:
    """Decode JWT payload to check expiry without a library."""
    try:
        raw = token.replace("Bearer ", "")
        parts = raw.split(".")
        # Add padding for base64
        payload_b64 = parts[1] + "=="
        import base64
        payload = json.loads(base64.b64decode(payload_b64))
        exp = payload.get("exp", 0)
        iat = payload.get("iat", 0)
        now = time.time()
        minutes_left = (exp - now) / 60
        return {
            "valid": minutes_left > 0,
            "minutes_left": round(minutes_left, 1),
            "issued": datetime.fromtimestamp(iat, tz=timezone.utc).strftime("%H:%M UTC"),
            "expires": datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%H:%M UTC"),
        }
    except Exception:
        return {"valid": False, "minutes_left": 0}


def update_config(new_token: str):
    """Write the new token into config.py."""
    try:
        with open(CONFIG_PATH, "r") as f:
            content = f.read()

        updated = re.sub(
            r'AUTH_TOKEN\s*=\s*"Bearer [^"]*"',
            f'AUTH_TOKEN = "{new_token}"',
            content
        )

        if updated == content:
            # Try single quotes
            updated = re.sub(
                r"AUTH_TOKEN\s*=\s*'Bearer [^']*'",
                f"AUTH_TOKEN = '{new_token}'",
                content
            )

        with open(CONFIG_PATH, "w") as f:
            f.write(updated)
        return True
    except Exception as e:
        print(f"  Failed to update config.py: {e}")
        return False


# ─── MAIN ────────────────────────────────────────────────────────────────────

def refresh(verbose=True) -> str | None:
    if verbose:
        print("🔑 Fetching token from Chrome...")

    token = get_token_from_chrome()

    if not token:
        print("  ✗ Could not read token — is phygitals.com open in Chrome?")
        return None

    info = decode_token_expiry(token)

    if not info["valid"]:
        print("  ✗ Token found but expired. Log back into phygitals.com.")
        return None

    if verbose:
        print(f"  ✓ Token valid — {info['minutes_left']} min remaining (expires {info['expires']})")

    # Update config.py
    if update_config(token):
        if verbose:
            print(f"  ✓ config.py updated")

    return token


def check():
    """Just report token status without writing."""
    token = get_token_from_chrome()
    if not token:
        print("❌ No token found — is phygitals.com open in Chrome?")
        return
    info = decode_token_expiry(token)
    if info["valid"]:
        print(f"✅ Token valid — {info['minutes_left']} min left (expires {info['expires']})")
    else:
        print(f"❌ Token expired. Please reload phygitals.com and log in.")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        refresh()
