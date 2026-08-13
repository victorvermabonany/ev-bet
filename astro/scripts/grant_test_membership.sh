#!/usr/bin/env bash
#
# Flip one session to paid on a running server, by sending the same signed
# webhook Whop would send after a real purchase.
#
# This is how you see the paywall open on a live deployment without spending
# money. It is not a backdoor: it needs WHOP_WEBHOOK_SECRET, which is the same
# secret that authenticates Whop itself. Anyone who has that can already grant
# access, and anyone who does not gets a 401 exactly like a forged event.
#
# Usage:
#   sh scripts/grant_test_membership.sh <base-url> <session-id> [revoke]
#
# The session id is the `transit_sid` cookie in your browser:
#   DevTools -> Application -> Cookies -> your site -> transit_sid -> Value
# (It is httpOnly, so devtools is the only place to read it -- by design.)
#
# Environment:
#   WHOP_WEBHOOK_SECRET   required, must match the server's
#
# Examples:
#   WHOP_WEBHOOK_SECRET=... sh scripts/grant_test_membership.sh \
#       https://northstar-astro.onrender.com AbC123...
#   WHOP_WEBHOOK_SECRET=... sh scripts/grant_test_membership.sh \
#       https://northstar-astro.onrender.com AbC123... revoke
#
set -eu

BASE=${1:-}
SID=${2:-}
MODE=${3:-grant}
SECRET=${WHOP_WEBHOOK_SECRET:-}

if [ -z "$BASE" ] || [ -z "$SID" ]; then
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
  exit 64
fi

if [ -z "$SECRET" ]; then
  echo "WHOP_WEBHOOK_SECRET is not set. It must match the server's, or the" >&2
  echo "webhook will be rejected with 401 (which is the point)." >&2
  exit 64
fi

BASE=${BASE%/}

if [ "$MODE" = "revoke" ]; then
  ACTION=membership.went_invalid
  STATUS=expired
else
  ACTION=membership.went_valid
  STATUS=active
fi

BODY=$(python3 -c '
import json, sys, time
action, status, sid = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    "action": action,
    "data": {
        "id": "mem_manual_test",
        "status": status,
        "user_id": "user_manual_test",
        "plan_id": "plan_manual_test",
        # Thirty days out, so the independent expiry check does not immediately
        # revoke what we just granted.
        "renewal_period_end": int(time.time()) + 30 * 24 * 3600,
        "metadata": {"sid": sid},
    },
}))' "$ACTION" "$STATUS" "$SID")

SIG=$(printf '%s' "$BODY" | python3 -c '
import hmac, hashlib, sys
print(hmac.new(sys.argv[1].encode(), sys.stdin.buffer.read(), hashlib.sha256).hexdigest())' "$SECRET")

echo "-> $ACTION for session ${SID%"${SID#????????}"}... at $BASE"

RESPONSE=$(curl -sS -w '\n%{http_code}' -X POST "$BASE/api/whop/webhook" \
  -H 'Content-Type: application/json' \
  -H "X-Whop-Signature: sha256=$SIG" \
  -d "$BODY")

CODE=$(printf '%s' "$RESPONSE" | tail -1)
PAYLOAD=$(printf '%s' "$RESPONSE" | sed '$d')

echo "<- HTTP $CODE $PAYLOAD"

case "$CODE" in
  200)
    if [ "$MODE" = "revoke" ]; then
      echo "Revoked. Reload the page; the locked sections should return."
    else
      echo "Granted. Reload the page in that same browser and the reading unlocks."
    fi
    ;;
  401)
    echo "Rejected: the signature did not verify. WHOP_WEBHOOK_SECRET here does" >&2
    echo "not match the one set on the server." >&2
    exit 1
    ;;
  *)
    echo "Unexpected response. Is $BASE running this app?" >&2
    exit 1
    ;;
esac
