"""Paid-access enforcement.

The first piece of persistent state the app has. Everything else is computed
per request and thrown away; a purchase has to outlive the process, so this is
the one thing that touches a disk.

Identity model: the browser holds an opaque session token in an httpOnly
cookie. That token is passed into Whop checkout as metadata, and Whop's webhook
hands it back once payment (or a trial) starts, which is what links an anonymous
visitor to a real membership. We never see or store a password, and we never ask
for an email -- Whop already authenticated the buyer, so duplicating that would
mean two sources of truth for who somebody is.

The session token is a bearer credential: possession of it grants access. It is
256 bits of `secrets` randomness, so guessing one is not a practical attack, and
it is only ever accepted after a database lookup -- a forged token matches no
row and is simply unknown.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading

log = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "ASTRO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "transit.db"),
)

COOKIE_NAME = "transit_sid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 400  # ~13 months

# Statuses that entitle someone to paid content.
#
#   trialing  -- the 3-day free trial on the default plan. Omitting this would
#                lock out exactly the users the highlighted plan is designed to
#                attract, which is the kind of bug that only shows up in
#                production on a real card.
#   canceling -- cancelled but paid through the end of the current period. They
#                bought the time; they keep it until it runs out.
#
# past_due is deliberately excluded: a failed payment should lose access rather
# than quietly keep it while Whop retries.
ENTITLED_STATUSES = frozenset({"active", "trialing", "canceling"})

_lock = threading.Lock()
_connection: sqlite3.Connection | None = None

# Two tables, not one.
#
# The original single `grants` table keyed access on (session_id, membership_id)
# and so could not represent a purchase that had no session yet. That is not an
# edge case: it is every purchase that does not begin at our own /api/checkout
# -- a Whop product page, the marketplace, an affiliate link, a checkout URL
# forwarded to a friend. Those arrived with no metadata and were dropped
# entirely, meaning the customer paid and got nothing, and we kept no record
# that it had happened.
#
# So: `memberships` records what Whop told us, always, whether or not we can yet
# say whose browser it belongs to. `session_links` is the separate, later
# question of which visitor may use it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS memberships (
    membership_id TEXT PRIMARY KEY,
    whop_user_id  TEXT,
    email         TEXT,
    plan_id       TEXT,
    status        TEXT NOT NULL,
    valid_until   TEXT,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memberships_by_user ON memberships (whop_user_id);
CREATE INDEX IF NOT EXISTS memberships_by_email ON memberships (email);

CREATE TABLE IF NOT EXISTS session_links (
    session_id    TEXT NOT NULL,
    membership_id TEXT NOT NULL,
    linked_at     TEXT NOT NULL,
    PRIMARY KEY (session_id, membership_id)
);
CREATE INDEX IF NOT EXISTS links_by_session ON session_links (session_id);
CREATE INDEX IF NOT EXISTS links_by_membership ON session_links (membership_id);
"""

# The pre-split table. Carried forward on first connect so an existing
# deployment does not lose live subscribers to a schema change.
LEGACY_SCHEMA_MIGRATION = """
INSERT OR IGNORE INTO memberships
    (membership_id, whop_user_id, email, plan_id, status, valid_until, updated_at)
SELECT membership_id, whop_user_id, NULL, plan_id, status, valid_until, updated_at
FROM grants;

INSERT OR IGNORE INTO session_links (session_id, membership_id, linked_at)
SELECT session_id, membership_id, updated_at FROM grants;
"""


def _resolve_db_path() -> str:
    """Where the grants file can actually be written.

    ASTRO_DB_PATH normally points at a mounted disk. If that directory does not
    exist or is not writable -- the common case being a Render blueprint whose
    disk is commented out on the free plan -- fall back to a path beside the app
    rather than refusing to boot. Losing persistence degrades the service;
    failing to start takes it down entirely, and the fallback is no less durable
    than the ephemeral filesystem the mount point would have been.
    """
    directory = os.path.dirname(os.path.abspath(DB_PATH))
    try:
        os.makedirs(directory, exist_ok=True)
        if os.access(directory, os.W_OK):
            return DB_PATH
        raise OSError(f"{directory} is not writable")
    except OSError as exc:
        fallback = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "transit.db"
        )
        log.warning(
            "ASTRO_DB_PATH=%s unusable (%s); falling back to %s. Entitlements "
            "will not survive a restart -- mount a persistent disk before "
            "taking real payments.",
            DB_PATH, exc, fallback,
        )
        return fallback


def _connect() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(_resolve_db_path(), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.executescript(SCHEMA)
        _migrate_legacy_grants(_connection)
        _connection.commit()
    return _connection


def _migrate_legacy_grants(conn: sqlite3.Connection) -> None:
    """Carry a pre-split `grants` table into the two-table schema."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='grants'"
    ).fetchone()
    if not exists:
        return
    conn.executescript(LEGACY_SCHEMA_MIGRATION)
    moved = conn.execute("SELECT count(*) FROM grants").fetchone()[0]
    conn.execute("ALTER TABLE grants RENAME TO grants_migrated")
    log.info("migrated %d row(s) from the legacy grants table", moved)


def init() -> None:
    with _lock:
        _connect()


def reset_for_tests() -> None:
    """Drop all state. Only used by the test suite."""
    global _connection
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM memberships")
        conn.execute("DELETE FROM session_links")
        conn.commit()


def new_session_id() -> str:
    """A fresh opaque session token."""
    return secrets.token_urlsafe(32)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_time(value) -> dt.datetime | None:
    """Whop may send an ISO timestamp or a unix epoch; accept either."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return dt.datetime.fromtimestamp(int(text), dt.timezone.utc)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def record_membership(
    membership_id: str,
    status: str,
    session_id: str | None = None,
    whop_user_id: str | None = None,
    email: str | None = None,
    plan_id: str | None = None,
    valid_until=None,
) -> None:
    """Upsert what a webhook told us about a membership.

    ``session_id`` is optional on purpose. A purchase is recorded whether or not
    we yet know which browser it belongs to; binding it to a session is a
    separate step that can happen now, later, or by hand.
    """
    if not membership_id:
        raise ValueError("membership_id is required")

    expiry = _parse_time(valid_until)
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO memberships
                (membership_id, whop_user_id, email, plan_id, status,
                 valid_until, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(membership_id) DO UPDATE SET
                whop_user_id = COALESCE(excluded.whop_user_id, memberships.whop_user_id),
                email        = COALESCE(excluded.email, memberships.email),
                plan_id      = COALESCE(excluded.plan_id, memberships.plan_id),
                status       = excluded.status,
                valid_until  = excluded.valid_until,
                updated_at   = excluded.updated_at
            """,
            (
                membership_id,
                whop_user_id,
                (email or "").strip().lower() or None,
                plan_id,
                (status or "").lower(),
                expiry.isoformat() if expiry else None,
                _now().isoformat(),
            ),
        )
        if session_id:
            conn.execute(
                "INSERT OR IGNORE INTO session_links "
                "(session_id, membership_id, linked_at) VALUES (?, ?, ?)",
                (session_id, membership_id, _now().isoformat()),
            )
        conn.commit()


def link_session(session_id: str, membership_id: str) -> bool:
    """Bind a membership to a browser session. True if this created the link."""
    if not session_id or not membership_id:
        raise ValueError("session_id and membership_id are required")
    with _lock:
        conn = _connect()
        cursor = conn.execute(
            "INSERT OR IGNORE INTO session_links "
            "(session_id, membership_id, linked_at) VALUES (?, ?, ?)",
            (session_id, membership_id, _now().isoformat()),
        )
        conn.commit()
        return cursor.rowcount > 0


def membership(membership_id: str) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM memberships WHERE membership_id = ?", (membership_id,)
        ).fetchone()
    return dict(row) if row else None


def sessions_for_membership(membership_id: str) -> list[str]:
    with _lock:
        rows = _connect().execute(
            "SELECT session_id FROM session_links WHERE membership_id = ?",
            (membership_id,),
        ).fetchall()
    return [r["session_id"] for r in rows]


def unclaimed_memberships() -> list[dict]:
    """Live memberships nobody has claimed -- purchases owed an owner.

    This is the operator's view of finding 01: anyone in this list paid and
    cannot currently see what they bought.
    """
    with _lock:
        rows = _connect().execute(
            """
            SELECT m.* FROM memberships m
            LEFT JOIN session_links l ON l.membership_id = m.membership_id
            WHERE l.session_id IS NULL
            ORDER BY m.updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows if r["status"] in ENTITLED_STATUSES]


def update_membership_status(membership_id: str, status: str, valid_until=None) -> int:
    """Apply a lifecycle change to a membership we already know about."""
    expiry = _parse_time(valid_until)
    with _lock:
        conn = _connect()
        cursor = conn.execute(
            """
            UPDATE memberships
               SET status = ?,
                   valid_until = COALESCE(?, valid_until),
                   updated_at = ?
             WHERE membership_id = ?
            """,
            (
                (status or "").lower(),
                expiry.isoformat() if expiry else None,
                _now().isoformat(),
                membership_id,
            ),
        )
        conn.commit()
        return cursor.rowcount


def entitlement(session_id: str) -> dict:
    """Whether this session may see paid content, and why.

    Returns a dict rather than a bool so the endpoints and the UI can explain
    themselves -- "your trial ended" is a very different message from "we have
    never seen you before".
    """
    blank = {"entitled": False, "status": None, "planId": None, "validUntil": None}
    if not session_id:
        return blank

    with _lock:
        rows = _connect().execute(
            """
            SELECT m.* FROM session_links l
            JOIN memberships m ON m.membership_id = l.membership_id
            WHERE l.session_id = ?
            ORDER BY m.updated_at DESC
            """,
            (session_id,),
        ).fetchall()

    now = _now()
    best = None
    for row in rows:
        if row["status"] not in ENTITLED_STATUSES:
            continue
        # A stored status can go stale if a webhook is missed, so the period end
        # is enforced independently: past it, access lapses whether or not Whop
        # managed to tell us.
        expiry = _parse_time(row["valid_until"])
        if expiry and expiry <= now:
            continue
        best = row
        break

    if best is None:
        latest = rows[0] if rows else None
        return {
            **blank,
            "status": latest["status"] if latest else None,
        }

    return {
        "entitled": True,
        "status": best["status"],
        "planId": best["plan_id"],
        "validUntil": best["valid_until"],
    }


def grants_for_session(session_id: str) -> list[dict]:
    with _lock:
        rows = _connect().execute(
            """
            SELECT m.*, l.session_id FROM session_links l
            JOIN memberships m ON m.membership_id = l.membership_id
            WHERE l.session_id = ?
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Webhook verification
# ---------------------------------------------------------------------------

SIGNATURE_HEADERS = (
    "X-Whop-Signature",
    "Whop-Signature",
    "X-Signature",
    "X-Hub-Signature-256",
)


def webhook_secret() -> str:
    return os.environ.get("WHOP_WEBHOOK_SECRET", "")


def verify_webhook(raw_body: bytes, headers) -> tuple[bool, str]:
    """Verify a webhook's HMAC signature.

    Fails closed. With no secret configured the endpoint rejects everything:
    an unauthenticated webhook that grants paid access is a worse hole than the
    client-side flag this replaces, because it is silent and permanent.
    """
    secret = webhook_secret()
    if not secret:
        return False, "WHOP_WEBHOOK_SECRET is not set"

    provided = ""
    for name in SIGNATURE_HEADERS:
        if headers.get(name):
            provided = headers.get(name)
            break
    if not provided:
        return False, "no signature header"

    # Signatures are sent variously as the bare hex digest, `sha256=<hex>`, or
    # a comma-separated list of `k=v` pairs. Take the last hex-looking value.
    candidates = []
    for part in str(provided).split(","):
        piece = part.strip()
        if "=" in piece:
            piece = piece.split("=", 1)[1].strip()
        if piece:
            candidates.append(piece)

    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    for candidate in candidates:
        if hmac.compare_digest(candidate.lower(), expected):
            return True, "ok"
    return False, "signature mismatch"


# ---------------------------------------------------------------------------
# Webhook payload parsing
# ---------------------------------------------------------------------------

# Events that create or confirm access, and those that revoke it. Whop's exact
# event names are configured when the webhook is created; these cover the
# documented membership lifecycle and are matched loosely so a near-miss in
# naming does not silently drop a payment.
GRANTING_EVENTS = ("valid", "succeeded", "created", "started", "active")
REVOKING_EVENTS = ("invalid", "cancel", "expire", "fail", "past_due", "refund", "delete")


def _dig(payload: dict, *names):
    """Find the first present key among ``names``, searching nested dicts."""
    stack = [payload]
    while stack:
        current = stack.pop(0)
        if not isinstance(current, dict):
            continue
        for name in names:
            value = current.get(name)
            if value not in (None, "", {}):
                return value
        stack.extend(v for v in current.values() if isinstance(v, dict))
    return None


def parse_event(payload: dict) -> dict:
    """Pull the fields we care about out of a webhook body.

    Deliberately defensive about shape. The exact payload differs by event and
    API version, and a membership that fails to record because a key moved is a
    customer who paid and did not get access.
    """
    event = str(
        payload.get("event") or payload.get("type") or payload.get("action") or ""
    ).lower()

    data = payload.get("data")
    body = data if isinstance(data, dict) else payload

    membership_id = _dig(body, "membership_id", "id") if "membership" in event else None
    if not membership_id:
        membership_id = _dig(body, "membership_id") or _dig(body, "id")

    metadata = _dig(body, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "event": event,
        "membership_id": membership_id,
        "session_id": metadata.get("sid") or metadata.get("session_id"),
        "whop_user_id": _dig(body, "user_id", "whop_user_id"),
        # Captured so a paying customer is reachable. Without it, a purchase we
        # cannot bind to a session is also a customer we cannot contact.
        "email": _dig(body, "email", "user_email", "customer_email"),
        "plan_id": _dig(body, "plan_id"),
        "status": (_dig(body, "status") or "").lower(),
        "valid_until": _dig(
            body, "renewal_period_end", "expires_at", "valid_until", "current_period_end"
        ),
    }


def apply_event(payload: dict) -> dict:
    """Record a webhook. Returns a summary for logging and tests.

    The rule is that a verified purchase is *always* written down, even when we
    cannot yet say whose it is. Previously an event with no session metadata and
    no matching row was discarded, which meant a customer could pay and leave no
    trace at all -- nothing to reconcile, nothing to support them with.
    """
    parsed = parse_event(payload)
    event = parsed["event"]
    membership_id = parsed["membership_id"]

    if not membership_id:
        return {"applied": False, "reason": "no membership id in payload", **parsed}

    revoking = any(token in event for token in REVOKING_EVENTS)
    granting = any(token in event for token in GRANTING_EVENTS)

    status = parsed["status"]
    if not status:
        status = "expired" if revoking else "active"

    if revoking or not granting:
        changed = update_membership_status(membership_id, status, parsed["valid_until"])
        if changed:
            return {"applied": True, "action": "updated", "rows": changed, **parsed}
        # A revocation for something we never recorded. Write it down anyway so
        # the state is right if a later event refers to it.
        record_membership(
            membership_id=membership_id,
            status=status,
            whop_user_id=parsed["whop_user_id"],
            email=parsed["email"],
            plan_id=parsed["plan_id"],
            valid_until=parsed["valid_until"],
        )
        return {"applied": True, "action": "recorded-inactive", **parsed}

    record_membership(
        membership_id=membership_id,
        status=status,
        session_id=parsed["session_id"],
        whop_user_id=parsed["whop_user_id"],
        email=parsed["email"],
        plan_id=parsed["plan_id"],
        valid_until=parsed["valid_until"],
    )

    if parsed["session_id"]:
        return {"applied": True, "action": "granted", **parsed}

    # Bought somewhere other than our own checkout, so there is no session to
    # attach it to yet. The purchase is safe; it now needs claiming. Logged at
    # warning level because somebody has paid and cannot yet see what they
    # bought -- that should be visible in the logs, not silent.
    log.warning(
        "unclaimed membership %s (whop_user=%s email=%s): paid, but no session "
        "metadata to bind it to. Awaiting /api/claim.",
        membership_id, parsed["whop_user_id"], parsed["email"],
    )
    return {"applied": True, "action": "recorded-unclaimed", **parsed}


def claim(session_id: str, membership_id: str) -> dict:
    """Bind a paid-for membership to the browser session asking for it.

    The membership id is the shared secret. Whop shows it to the buyer on their
    receipt and in their account, it is high-entropy and unguessable, and it is
    only ever accepted for a membership that is currently live -- so this is a
    licence-key claim, not a lookup by anything a stranger could enumerate.

    Deliberately *not* claim-by-email: an email address is not a secret, and
    letting one bind a subscription would hand over paid access to anyone who
    could guess a customer's address. Whop OAuth is the better long-term
    answer; this closes the hole in the meantime.
    """
    if not session_id:
        return {"claimed": False, "reason": "no session"}

    membership_id = (membership_id or "").strip()
    if not membership_id:
        return {"claimed": False, "reason": "no membership id"}

    record = membership(membership_id)
    if record is None:
        return {"claimed": False, "reason": "not found"}

    if record["status"] not in ENTITLED_STATUSES:
        return {"claimed": False, "reason": "not active"}

    expiry = _parse_time(record["valid_until"])
    if expiry and expiry <= _now():
        return {"claimed": False, "reason": "expired"}

    created = link_session(session_id, membership_id)
    log.info(
        "membership %s claimed by a session (new link: %s)", membership_id, created
    )
    return {"claimed": True, "membershipId": membership_id, "new": created}


__all__ = [
    "COOKIE_NAME", "COOKIE_MAX_AGE", "ENTITLED_STATUSES", "DB_PATH",
    "init", "reset_for_tests", "new_session_id", "record_membership",
    "update_membership_status", "entitlement", "grants_for_session",
    "verify_webhook", "webhook_secret", "parse_event", "apply_event",
    "claim", "link_session", "membership", "sessions_for_membership",
    "unclaimed_memberships",
]
