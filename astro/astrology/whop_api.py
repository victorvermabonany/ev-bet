"""Minimal Whop API client.

Only one call is needed: create a checkout configuration that carries our
session token as metadata. Whop copies that metadata onto the resulting payment
and membership, and hands it back on the webhook -- which is the entire link
between an anonymous browser and a real purchase.

The embedded checkout has no metadata attribute of its own (the only data-*
hooks it reads are plan-id, session, overlay and style-*), so a server-created
checkout configuration is the only way to attach anything. That is why this
module exists rather than the browser talking to Whop directly.

The request shape below was captured from the official CLI by pointing it at a
local listener with WHOP_API_BASE_URL, rather than guessed:

    POST {base}/checkout_configurations
    Authorization: Bearer <api key>
    {"metadata": {...}, "plan_id": "plan_..."}
    -> {"id": "ckcfg_..."}

Uses urllib so the app gains no new dependency for one endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

BASE_URL = os.environ.get("WHOP_API_BASE_URL", "https://api.whop.com/api/v1").rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("WHOP_API_TIMEOUT", "12"))


class WhopError(RuntimeError):
    """A Whop API call failed."""


def api_key() -> str:
    return os.environ.get("WHOP_API_KEY", "")


def configured() -> bool:
    return bool(api_key())


def _post(path: str, body: dict) -> dict:
    if not configured():
        raise WhopError("WHOP_API_KEY is not set")

    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise WhopError(f"{path} returned {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise WhopError(f"{path} unreachable: {exc.reason}") from None
    except ValueError:
        raise WhopError(f"{path} returned invalid JSON") from None


def create_checkout_configuration(plan_id: str, metadata: dict) -> str:
    """Create a checkout configuration and return its id.

    The id goes to the browser as `data-whop-checkout-session`, which is how the
    metadata rides along into the purchase.
    """
    payload = _post(
        "/checkout_configurations", {"plan_id": plan_id, "metadata": metadata}
    )
    checkout_id = payload.get("id") or (payload.get("data") or {}).get("id")
    if not checkout_id:
        raise WhopError(f"no id in checkout configuration response: {payload!r}")
    return checkout_id


__all__ = ["BASE_URL", "WhopError", "api_key", "configured", "create_checkout_configuration"]
