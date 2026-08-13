"""Paywall enforcement tests.

The claim being tested is narrow and important: paid content is returned only
to a session that a signed Whop webhook has tied to an active membership.
Everything else -- an ordinary visitor, a crafted request, a forged webhook,
an expired or cancelled membership -- gets the free reading.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Point the store at a scratch database before anything imports it.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["ASTRO_DB_PATH"] = _tmp.name
os.environ["WHOP_WEBHOOK_SECRET"] = "test-webhook-secret"

from astrology import entitlements  # noqa: E402

SECRET = "test-webhook-secret"

BIRTH = {
    "name": "Sam",
    "date": "1997-03-12",
    "time": "14:25",
    "timeKnown": True,
    "place": "New York City, New York, United States",
    "latitude": 40.7143,
    "longitude": -74.006,
    "timezone": "America/New_York",
}


@pytest.fixture(autouse=True)
def clean_store():
    entitlements.init()
    entitlements.reset_for_tests()
    yield
    entitlements.reset_for_tests()


@pytest.fixture
def client():
    from app import app

    app.config["TESTING"] = True
    return app.test_client()


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send_webhook(client, payload: dict, secret: str = SECRET, header="X-Whop-Signature"):
    raw = json.dumps(payload).encode()
    return client.post(
        "/api/whop/webhook",
        data=raw,
        headers={"Content-Type": "application/json", header: sign(raw, secret)},
    )


def session_of(client) -> str:
    """Establish a session and return its token."""
    client.get("/")
    for cookie in client.cookie_jar if hasattr(client, "cookie_jar") else []:
        if cookie.name == entitlements.COOKIE_NAME:
            return cookie.value
    # Werkzeug >= 2.3 exposes cookies on the client itself.
    return client.get_cookie(entitlements.COOKIE_NAME).value


def reading_tier(client) -> str:
    """The tier this client actually gets back -- the only thing that matters."""
    return client.post("/api/reading", json=BIRTH).get_json()["tier"]


def membership_payload(session_id: str, **overrides) -> dict:
    data = {
        "id": "mem_TEST1",
        "status": "active",
        "user_id": "user_TEST",
        "plan_id": "plan_WEEKLY",
        "metadata": {"sid": session_id},
    }
    data.update(overrides)
    return {"event": "membership.went_valid", "data": data}


# --------------------------------------------------------------------------
# The headline requirement
# --------------------------------------------------------------------------

def test_unauthenticated_request_gets_the_free_reading(client):
    """A plain visitor asking for a reading gets the free tier."""
    response = client.post("/api/reading", json=BIRTH)
    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "free"
    assert body["entitlement"]["entitled"] is False


def test_client_cannot_ask_for_paid_content(client):
    """The old hole: passing tier='paid' must do nothing at all.

    This is the exact request that used to return the full reading.
    """
    response = client.post("/api/reading", json={**BIRTH, "tier": "paid"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "free", "client-supplied tier must be ignored"
    assert len(body["content"]["strengths"]) == 2  # the free shape


def test_verified_membership_returns_the_full_reading(client):
    """The whole point: webhook first, then paid content."""
    sid = session_of(client)

    before = client.post("/api/reading", json=BIRTH).get_json()
    assert before["tier"] == "free"

    assert send_webhook(client, membership_payload(sid)).status_code == 200

    after = client.post("/api/reading", json=BIRTH).get_json()
    assert after["tier"] == "paid"
    assert after["entitlement"]["entitled"] is True
    assert len(after["content"]["strengths"]) > len(before["content"]["strengths"])
    assert len(after["content"]["timing"]) > len(before["content"]["timing"])


def test_membership_only_unlocks_its_own_session(client):
    """One person's purchase must not unlock a different browser."""
    from app import app

    buyer = app.test_client()
    buyer_sid = session_of(buyer)
    send_webhook(buyer, membership_payload(buyer_sid))
    assert buyer.post("/api/reading", json=BIRTH).get_json()["tier"] == "paid"

    stranger = app.test_client()
    session_of(stranger)
    assert stranger.post("/api/reading", json=BIRTH).get_json()["tier"] == "free"


def test_guessed_session_token_grants_nothing(client):
    """A forged cookie matches no row, so it is simply unknown."""
    from app import app

    attacker = app.test_client()
    attacker.set_cookie(entitlements.COOKIE_NAME, "not-a-real-session-token")
    assert attacker.post("/api/reading", json=BIRTH).get_json()["tier"] == "free"


# --------------------------------------------------------------------------
# Webhook authenticity
# --------------------------------------------------------------------------

def test_unsigned_webhook_is_rejected(client):
    sid = session_of(client)
    response = client.post(
        "/api/whop/webhook",
        data=json.dumps(membership_payload(sid)).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "free"


def test_wrongly_signed_webhook_is_rejected(client):
    """Anyone can POST this endpoint; only a correct HMAC counts."""
    sid = session_of(client)
    response = send_webhook(client, membership_payload(sid), secret="attacker-guess")
    assert response.status_code == 401
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "free"


def test_tampered_body_invalidates_the_signature(client):
    """Signature covers the body, so swapping the session id breaks it."""
    sid = session_of(client)
    raw = json.dumps(membership_payload(sid)).encode()
    signature = sign(raw)

    tampered = json.dumps(membership_payload("someone-elses-session")).encode()
    response = client.post(
        "/api/whop/webhook",
        data=tampered,
        headers={"Content-Type": "application/json", "X-Whop-Signature": signature},
    )
    assert response.status_code == 401


def test_webhook_fails_closed_without_a_secret(monkeypatch, client):
    """No configured secret must mean no webhook is trusted at all."""
    monkeypatch.delenv("WHOP_WEBHOOK_SECRET", raising=False)
    sid = session_of(client)
    raw = json.dumps(membership_payload(sid)).encode()
    response = client.post(
        "/api/whop/webhook",
        data=raw,
        headers={"Content-Type": "application/json", "X-Whop-Signature": sign(raw)},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "header", ["X-Whop-Signature", "Whop-Signature", "X-Hub-Signature-256"]
)
def test_signature_accepted_from_any_documented_header(client, header):
    sid = session_of(client)
    assert send_webhook(client, membership_payload(sid), header=header).status_code == 200
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "paid"


def test_signature_accepted_with_sha256_prefix(client):
    sid = session_of(client)
    raw = json.dumps(membership_payload(sid)).encode()
    response = client.post(
        "/api/whop/webhook",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Whop-Signature": f"sha256={sign(raw)}",
        },
    )
    assert response.status_code == 200


# --------------------------------------------------------------------------
# Membership lifecycle
# --------------------------------------------------------------------------

def test_trialing_membership_is_entitled(client):
    """The default plan is a 3-day trial, so `trialing` must count.

    Gating on `active` alone would lock out exactly the users the highlighted
    plan exists to attract.
    """
    sid = session_of(client)
    send_webhook(client, membership_payload(sid, status="trialing"))
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "paid"


def test_canceling_membership_keeps_access_until_the_period_ends(client):
    """Cancelled but paid through: they bought the time, they keep it."""
    sid = session_of(client)
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).isoformat()
    send_webhook(client, membership_payload(sid, status="canceling", expires_at=future))
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "paid"


@pytest.mark.parametrize("status", ["expired", "canceled", "past_due", "paused"])
def test_dead_statuses_are_not_entitled(client, status):
    sid = session_of(client)
    send_webhook(client, membership_payload(sid, status=status))
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "free"


def test_expired_period_revokes_access_even_without_a_webhook(client):
    """A missed revocation webhook must not leave access on forever."""
    sid = session_of(client)
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
    send_webhook(client, membership_payload(sid, status="active", expires_at=past))
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "free"


def test_cancellation_webhook_revokes_access(client):
    sid = session_of(client)
    send_webhook(client, membership_payload(sid))
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "paid"

    # Revocations identify the membership but need not echo our metadata.
    send_webhook(client, {
        "event": "membership.went_invalid",
        "data": {"id": "mem_TEST1", "status": "expired"},
    })
    assert client.post("/api/reading", json=BIRTH).get_json()["tier"] == "free"


def test_webhook_for_unknown_membership_is_recorded_not_dropped(client):
    """A membership we have never seen is still written down.

    Whop retries non-2xx and retrying cannot fix an unmatchable event, so this
    stays a 200. What changed is that the event is no longer discarded: an
    unrecorded cancellation used to vanish, leaving the row absent if a later
    event referred to it.
    """
    response = send_webhook(client, {
        "event": "membership.went_invalid",
        "data": {"id": "mem_NEVER_SEEN", "status": "expired"},
    })
    assert response.status_code == 200
    assert response.get_json()["applied"] is True

    stored = entitlements.membership("mem_NEVER_SEEN")
    assert stored is not None
    assert stored["status"] == "expired"
    # Recorded, but it entitles nobody.
    assert entitlements.sessions_for_membership("mem_NEVER_SEEN") == []


def test_repeated_webhooks_are_idempotent(client):
    sid = session_of(client)
    for _ in range(3):
        assert send_webhook(client, membership_payload(sid)).status_code == 200
    assert len(entitlements.grants_for_session(sid)) == 1


# --------------------------------------------------------------------------
# The paid-only question endpoint
# --------------------------------------------------------------------------

def test_question_endpoint_requires_a_membership(client):
    response = client.post("/api/question", json={**BIRTH, "question": "Should I quit?"})
    assert response.status_code == 402


def test_question_endpoint_opens_with_a_membership(client):
    sid = session_of(client)
    send_webhook(client, membership_payload(sid))
    response = client.post("/api/question", json={**BIRTH, "question": "Should I quit?"})
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"


# --------------------------------------------------------------------------
# Session and endpoint plumbing
# --------------------------------------------------------------------------

def test_session_cookie_is_httponly_and_samesite(client):
    response = client.get("/")
    cookie = next(
        h for h in response.headers.getlist("Set-Cookie")
        if h.startswith(entitlements.COOKIE_NAME)
    )
    assert "HttpOnly" in cookie          # not readable from JavaScript
    assert "SameSite=Lax" in cookie      # survives the return from checkout


def test_session_is_stable_across_requests(client):
    first = session_of(client)
    client.post("/api/reading", json=BIRTH)
    assert client.get_cookie(entitlements.COOKIE_NAME).value == first


def test_entitlement_endpoint_reports_state(client):
    sid = session_of(client)
    assert client.get("/api/entitlement").get_json()["entitled"] is False
    send_webhook(client, membership_payload(sid, status="trialing"))
    after = client.get("/api/entitlement").get_json()
    assert after["entitled"] is True
    assert after["status"] == "trialing"


def test_checkout_endpoint_rejects_unknown_plans(client):
    assert client.post("/api/checkout", json={"plan": "lifetime"}).status_code == 400


def test_session_tokens_are_unguessable():
    tokens = {entitlements.new_session_id() for _ in range(500)}
    assert len(tokens) == 500
    assert all(len(t) >= 40 for t in tokens)


def test_parse_event_finds_metadata_in_nested_payloads():
    """Whop's shape varies by event; the parser has to cope."""
    parsed = entitlements.parse_event({
        "event": "membership.went_valid",
        "data": {"membership": {"id": "mem_X", "metadata": {"sid": "abc"}, "status": "active"}},
    })
    assert parsed["session_id"] == "abc"
    assert parsed["status"] == "active"


# ---------------------------------------------------------------------------
# Finding 01: purchases that do not begin at our own checkout
# ---------------------------------------------------------------------------


def test_purchase_without_session_metadata_is_kept_and_claimable(client):
    """The audit's worst case: paid via a Whop link, no metadata, nothing lost.

    This previously returned applied: False and wrote nothing at all, so the
    customer paid, saw no change, and left no record to support them with.
    """
    response = send_webhook(client, {
        "event": "membership.went_valid",
        "data": {
            "id": "mem_via_whop_link",
            "status": "active",
            "user_id": "user_real",
            "email": "Buyer@Example.com",
            "plan_id": "plan_weekly",
        },
    })
    assert response.status_code == 200
    assert response.get_json()["applied"] is True

    stored = entitlements.membership("mem_via_whop_link")
    assert stored["status"] == "active"
    # The email is captured, so a paying customer is reachable.
    assert stored["email"] == "buyer@example.com"

    # It belongs to nobody yet, and grants nobody access.
    assert entitlements.sessions_for_membership("mem_via_whop_link") == []
    assert [m["membership_id"] for m in entitlements.unclaimed_memberships()] == [
        "mem_via_whop_link"
    ]
    assert reading_tier(client) == "free"

    # The buyer claims it with the id from their Whop receipt.
    claimed = client.post("/api/claim", json={"membershipId": "mem_via_whop_link"})
    assert claimed.status_code == 200
    assert claimed.get_json()["entitlement"]["entitled"] is True
    assert reading_tier(client) == "paid"
    assert entitlements.unclaimed_memberships() == []


def test_claiming_needs_the_real_membership_id(client):
    send_webhook(client, {
        "event": "membership.went_valid",
        "data": {"id": "mem_secret_id", "status": "active"},
    })
    for guess in ("", "mem_", "mem_wrong", "MEM_SECRET_ID "):
        response = client.post("/api/claim", json={"membershipId": guess})
        assert response.status_code == 404, guess
    assert reading_tier(client) == "free"


def test_expired_membership_cannot_be_claimed(client):
    send_webhook(client, {
        "event": "membership.went_valid",
        "data": {
            "id": "mem_lapsed",
            "status": "active",
            "renewal_period_end": int(dt.datetime.now(dt.timezone.utc).timestamp()) - 60,
        },
    })
    response = client.post("/api/claim", json={"membershipId": "mem_lapsed"})
    assert response.status_code == 404
    assert reading_tier(client) == "free"


def test_cancelled_membership_cannot_be_claimed(client):
    send_webhook(client, {
        "event": "membership.went_valid",
        "data": {"id": "mem_gone", "status": "active"},
    })
    send_webhook(client, {
        "event": "membership.went_invalid",
        "data": {"id": "mem_gone", "status": "expired"},
    })
    response = client.post("/api/claim", json={"membershipId": "mem_gone"})
    assert response.status_code == 404
    assert reading_tier(client) == "free"


def test_claim_does_not_transfer_access_away_from_the_buyer(client):
    """Claiming adds a link; it does not move one."""
    send_webhook(client, {
        "event": "membership.went_valid",
        "data": {"id": "mem_shared", "status": "active"},
    })
    client.post("/api/claim", json={"membershipId": "mem_shared"})
    assert reading_tier(client) == "paid"

    from app import app as flask_app

    second = flask_app.test_client()
    second.get("/")
    second.post("/api/claim", json={"membershipId": "mem_shared"})

    # Both now hold it -- a licence key that is shared is shared, which is why
    # the id must come from the receipt rather than anything guessable.
    assert reading_tier(client) == "paid"
    assert len(entitlements.sessions_for_membership("mem_shared")) == 2


def test_cancellation_after_a_claim_revokes_access(client):
    send_webhook(client, {
        "event": "membership.went_valid",
        "data": {"id": "mem_claim_then_cancel", "status": "active"},
    })
    client.post("/api/claim", json={"membershipId": "mem_claim_then_cancel"})
    assert reading_tier(client) == "paid"

    send_webhook(client, {
        "event": "membership.went_invalid",
        "data": {"id": "mem_claim_then_cancel", "status": "expired"},
    })
    assert reading_tier(client) == "free"


def test_legacy_grants_table_is_migrated(tmp_path, monkeypatch):
    """An existing deployment must not lose live subscribers to the split."""
    import importlib
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE grants (
            session_id TEXT NOT NULL, membership_id TEXT NOT NULL,
            whop_user_id TEXT, plan_id TEXT, status TEXT NOT NULL,
            valid_until TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, membership_id));
        INSERT INTO grants VALUES
            ('sid_existing', 'mem_existing', 'user_1', 'plan_weekly',
             'active', NULL, '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    original_path = os.environ["ASTRO_DB_PATH"]
    try:
        monkeypatch.setenv("ASTRO_DB_PATH", str(db))
        module = importlib.reload(entitlements)
        module.init()

        assert module.entitlement("sid_existing")["entitled"] is True
        assert module.membership("mem_existing")["plan_id"] == "plan_weekly"
    finally:
        # Reload leaves the module bound to the scratch database, and every
        # other test in the file shares this module object.
        os.environ["ASTRO_DB_PATH"] = original_path
        importlib.reload(entitlements)
        entitlements.init()


# --- storage durability -------------------------------------------------
#
# The grants table decides who has paid. On Render's free plan it lands on the
# container filesystem, which is rebuilt on every deploy and every spin-down
# after 15 minutes idle -- so paying customers silently lose access, and the
# service reports itself healthy the whole time.


def test_durability_is_off_unless_declared(monkeypatch):
    monkeypatch.delenv("ASTRO_STORAGE_DURABLE", raising=False)
    assert entitlements.storage_is_durable() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_durability_accepts_the_usual_affirmatives(monkeypatch, value):
    monkeypatch.setenv("ASTRO_STORAGE_DURABLE", value)
    assert entitlements.storage_is_durable() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "maybe"])
def test_durability_is_not_granted_by_a_vague_value(monkeypatch, value):
    monkeypatch.setenv("ASTRO_STORAGE_DURABLE", value)
    assert entitlements.storage_is_durable() is False


def test_a_writable_ephemeral_path_does_not_imply_durability(monkeypatch, tmp_path):
    """The failure this exists to catch.

    _resolve_db_path only warns when the path is UNWRITABLE. On Render the
    process runs as root, so /var/data is created happily and nothing is
    logged -- a writable directory is not evidence of a mounted disk.
    """
    target = tmp_path / "var" / "data" / "entitlements.db"
    monkeypatch.setattr(entitlements, "DB_PATH", str(target))
    monkeypatch.delenv("ASTRO_STORAGE_DURABLE", raising=False)

    assert entitlements._resolve_db_path() == str(target)   # succeeds silently
    assert os.path.isdir(target.parent)                      # it even made the dir
    assert entitlements.storage_is_durable() is False        # and still not durable


def test_health_reports_durability(client):
    body = client.get("/health").get_json()
    assert "entitlementsDurable" in body
