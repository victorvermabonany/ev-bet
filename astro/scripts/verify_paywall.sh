#!/usr/bin/env bash
# End-to-end proof that the paywall is enforced server-side.
set -u
BASE=${1:-http://127.0.0.1:5001}
SECRET=${WHOP_WEBHOOK_SECRET:-live-secret-abc}
JAR=$(mktemp)
BIRTH='"name":"Proof","date":"1990-04-17","time":"09:25","timeKnown":true,"place":"London, United Kingdom","latitude":51.5085,"longitude":-0.1257,"timezone":"Europe/London"'

pass=0; fail=0
check() { # label expected actual
  if [ "$2" = "$3" ]; then echo "  PASS  $1 (= $3)"; pass=$((pass+1));
  else echo "  FAIL  $1 (expected $2, got $3)"; fail=$((fail+1)); fi
}

sign() { python3 -c 'import hmac,hashlib,sys;print(hmac.new(sys.argv[1].encode(),sys.stdin.buffer.read(),hashlib.sha256).hexdigest())' "$1"; }

echo "== 1. Unauthenticated request that explicitly asks for tier: paid =="
R1=$(curl -s -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH,\"tier\":\"paid\"}")
T1=$(echo "$R1" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')
W1=$(echo "$R1" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["content"]["timing"]))')
E1=$(echo "$R1" | python3 -c 'import json,sys;print(json.load(sys.stdin)["entitlement"]["entitled"])')
check "tier returned"            "free"  "$T1"
check "transit windows withheld" "1"     "$W1"
check "entitled flag"            "False" "$E1"

echo
echo "== 2. Paid-only question endpoint, unauthenticated =="
Q=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/question" -H 'Content-Type: application/json' -d "{$BIRTH,\"question\":\"Should I take the offer?\"}")
check "HTTP status" "402" "$Q"

echo
echo "== 3. Establish a browser session (httpOnly cookie from GET /) =="
curl -s -c "$JAR" "$BASE/" > /dev/null
SID=$(awk '/transit_sid/ {print $7}' "$JAR")
HTTPONLY=$(grep -c '^#HttpOnly_' "$JAR")
check "cookie is httpOnly" "1" "$HTTPONLY"
echo "  session id: ${SID:0:12}..."

echo
echo "== 4. Same session, still unpaid =="
T4=$(curl -s -b "$JAR" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH,\"tier\":\"paid\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')
check "tier returned" "free" "$T4"

echo
echo "== 5. Webhook with a BAD signature carrying that session id =="
BODY=$(python3 -c 'import json,sys;print(json.dumps({"action":"membership.went_valid","data":{"id":"mem_forged","status":"active","plan_id":"plan_weekly","metadata":{"sid":sys.argv[1]}}}))' "$SID")
S5=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/whop/webhook" -H 'Content-Type: application/json' -H "X-Whop-Signature: $(printf '%s' "$BODY" | sign wrong-secret)" -d "$BODY")
check "HTTP status" "401" "$S5"
T5=$(curl -s -b "$JAR" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')
check "forged webhook granted nothing" "free" "$T5"

echo
echo "== 6. Webhook with a VALID signature =="
BODY=$(python3 -c 'import json,sys;print(json.dumps({"action":"membership.went_valid","data":{"id":"mem_real_001","status":"active","plan_id":"plan_weekly","user_id":"user_abc","renewal_period_end":4102444800,"metadata":{"sid":sys.argv[1]}}}))' "$SID")
S6=$(curl -s -X POST "$BASE/api/whop/webhook" -H 'Content-Type: application/json' -H "X-Whop-Signature: sha256=$(printf '%s' "$BODY" | sign "$SECRET")" -d "$BODY" -w '\n%{http_code}')
CODE6=$(echo "$S6" | tail -1); APPLIED=$(echo "$S6" | head -1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["applied"])')
check "HTTP status" "200"  "$CODE6"
check "applied"     "True" "$APPLIED"

echo
echo "== 7. Same session now returns the FULL reading =="
R7=$(curl -s -b "$JAR" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH}")
T7=$(echo "$R7" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')
W7=$(echo "$R7" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["content"]["timing"]))')
check "tier returned"        "paid" "$T7"
check "more timing than free"   "yes"  "$([ "$W7" -gt "$W1" ] && echo yes || echo no)"
Q7=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$BASE/api/question" -H 'Content-Type: application/json' -d "{$BIRTH,\"question\":\"Should I take the offer?\"}")
check "question endpoint opens" "200" "$Q7"

echo
echo "== 7b. The cut is in the facts, not just the prose =="
FACTS=$(cd /home/user/ev-bet/astro && /home/user/ev-bet/.venv/bin/python -c '
from astrology.chart import BirthData, build_chart
from astrology import career, places, reading
import datetime as dt
b = BirthData(name="Proof", date=dt.date(1990,4,17), time=dt.time(9,25), time_known=True,
              place_label="London", latitude=51.5085, longitude=-0.1257, timezone="Europe/London")
m = places.resolve_moment(b.date, b.time, b.timezone)
c = build_chart(b, m); p = career.build_profile(c); t = career.timing_summary(c)
f = reading.build_facts(c, p, t, "free"); q = reading.build_facts(c, p, t, "paid")
print(len(f["transitWindows"]), len(q["transitWindows"]), len(t["windows"]))')
check "facts given to free tier" "1" "$(echo $FACTS | cut -d" " -f1)"
check "facts given to paid tier" "8" "$(echo $FACTS | cut -d" " -f2)"
echo "  (of $(echo $FACTS | cut -d' ' -f3) windows computed; paid is capped at 8)"

echo
echo "== 8. A DIFFERENT session does not inherit that membership =="
JAR2=$(mktemp); curl -s -c "$JAR2" "$BASE/" > /dev/null
T8=$(curl -s -b "$JAR2" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH,\"tier\":\"paid\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')
check "tier returned" "free" "$T8"
T8B=$(curl -s -b "transit_sid=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')
check "guessed session token" "free" "$T8B"

echo
echo "== 9. Cancellation revokes access =="
BODY=$(python3 -c 'import json,sys;print(json.dumps({"action":"membership.went_invalid","data":{"id":"mem_real_001","status":"expired","metadata":{"sid":sys.argv[1]}}}))' "$SID")
curl -s -o /dev/null -X POST "$BASE/api/whop/webhook" -H 'Content-Type: application/json' -H "X-Whop-Signature: $(printf '%s' "$BODY" | sign "$SECRET")" -d "$BODY"
T9=$(curl -s -b "$JAR" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')
check "tier returned" "free" "$T9"

echo
echo "== 10. Launch blockers =="

echo "-- 01: a purchase made outside our checkout is kept, not dropped"
BODY=$(python3 -c 'import json,time;print(json.dumps({"action":"membership.went_valid","data":{"id":"mem_no_metadata","status":"active","user_id":"user_paid","email":"Buyer@Example.com","plan_id":"plan_weekly","renewal_period_end":int(time.time())+2592000}}))')
R=$(curl -s -X POST "$BASE/api/whop/webhook" -H 'Content-Type: application/json' -H "X-Whop-Signature: sha256=$(printf '%s' "$BODY" | sign "$SECRET")" -d "$BODY")
check "webhook applied"  "True" "$(echo "$R" | python3 -c 'import json,sys;print(json.load(sys.stdin)["applied"])')"

JAR3=$(mktemp); curl -s -c "$JAR3" "$BASE/" > /dev/null
check "grants nobody access yet" "free" "$(curl -s -b "$JAR3" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')"
check "wrong id is refused"      "404"  "$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR3" -X POST "$BASE/api/claim" -H 'Content-Type: application/json' -d '{"membershipId":"mem_guess"}')"
check "buyer claims it"          "200"  "$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR3" -X POST "$BASE/api/claim" -H 'Content-Type: application/json' -d '{"membershipId":"mem_no_metadata"}')"
check "and now sees paid"        "paid" "$(curl -s -b "$JAR3" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$BIRTH}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tier"])')"

echo "-- 02: a repeat reading is served from cache, not regenerated"
JAR4=$(mktemp); curl -s -c "$JAR4" "$BASE/" > /dev/null
B2='"name":"CacheProof","date":"1993-07-22","time":"11:11","timeKnown":true,"place":"Oslo","latitude":59.9127,"longitude":10.7461,"timezone":"Europe/Oslo"'
check "first call generates"  "False" "$(curl -s -b "$JAR4" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$B2}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["cached"])')"
check "second is cached"      "True"  "$(curl -s -b "$JAR4" -X POST "$BASE/api/reading" -H 'Content-Type: application/json' -d "{$B2}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["cached"])')"

echo "-- 02: cross-origin requests are not invited in"
check "no ACAO header" "" "$(curl -s -D- -o /dev/null -X POST "$BASE/api/reading" -H 'Origin: https://evil.example' -H 'Content-Type: application/json' -d "{$BIRTH}" | grep -i '^access-control-allow-origin' | tr -d '\r')"

echo "-- 03: the session cookie is Secure behind a TLS-terminating proxy"
COOKIE=$(curl -s -D- -o /dev/null "$BASE/" -H 'X-Forwarded-Proto: https' | grep -i '^set-cookie' | tr -d '\r')
check "Secure flag present"   "yes" "$(echo "$COOKIE" | grep -qi 'Secure'   && echo yes || echo no)"
check "HttpOnly flag present" "yes" "$(echo "$COOKIE" | grep -qi 'HttpOnly' && echo yes || echo no)"

echo
echo "-------------------------------------------"
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
