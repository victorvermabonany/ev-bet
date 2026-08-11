#!/bin/sh
# Creates the Transit product and its two pricing plans on Whop.
#
#   $7.99 / week with a 3-day free trial  -> the default, highlighted option
#   $89 / year                            -> shown, not emphasised
#
# Run once, from anywhere:
#
#   whop login                    # or: export WHOP_API_KEY=whop_xxx
#   sh astro/scripts/setup_whop.sh
#
# It prints the two plan IDs as environment variables to hand to the app. The
# script is safe to re-run: pass an existing product with PRODUCT_ID=prod_xxx
# and it will attach plans to that instead of creating a second product.
set -eu

command -v whop >/dev/null 2>&1 || {
	echo "error: whop CLI not found. Install it with:" >&2
	echo "  curl -fsSL https://whop.com/install.sh | sh" >&2
	exit 1
}

# An API key in the environment counts as logged in; the CLI picks it up.
if [ -z "${WHOP_API_KEY:-}" ]; then
	whop auth status >/dev/null 2>&1 || {
		echo "error: not authenticated. Run 'whop login', or set WHOP_API_KEY." >&2
		exit 1
	}
fi

id_of() { sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p' | head -n1; }

if [ -n "${PRODUCT_ID:-}" ]; then
	product_id="$PRODUCT_ID"
	echo "Using existing product $product_id"
else
	echo "Creating product…"
	product_id="$(
		whop products create \
			--title "Transit — full career reading" \
			--headline "Your chart, decoded. Timing you can act on." \
			--description "The complete transit calendar for the next 18 months, your Saturn return window, deeper friction analysis, and the ability to ask about a specific career decision." \
			--visibility visible \
			--custom_cta subscribe \
			--format json | id_of
	)"
	[ -n "$product_id" ] || { echo "error: product creation returned no id" >&2; exit 1; }
	echo "  product: $product_id"
fi

# --- default / highlighted: $7.99 per week, 3-day free trial -----------------
echo "Creating weekly plan (\$7.99/wk, 3-day trial)…"
weekly_id="$(
	whop plans create \
		--product_id "$product_id" \
		--title "Weekly" \
		--description "Full readings and ongoing timing. 3 days free, then \$7.99 per week. Cancel anytime." \
		--plan_type renewal \
		--renewal_price 7.99 \
		--billing_period 7 \
		--trial_period_days 3 \
		--currency USD \
		--visibility visible \
		--unlimited_stock \
		--metadata '{"tier":"paid","cadence":"weekly","highlighted":"true"}' \
		--format json | id_of
)"
[ -n "$weekly_id" ] || { echo "error: weekly plan creation returned no id" >&2; exit 1; }
echo "  weekly:  $weekly_id"

# --- secondary: $89 per year, no trial ---------------------------------------
echo "Creating annual plan (\$89/yr)…"
annual_id="$(
	whop plans create \
		--product_id "$product_id" \
		--title "Annual" \
		--description "The same full access, billed once a year at \$89." \
		--plan_type renewal \
		--renewal_price 89 \
		--billing_period 365 \
		--currency USD \
		--visibility visible \
		--unlimited_stock \
		--metadata '{"tier":"paid","cadence":"annual","highlighted":"false"}' \
		--format json | id_of
)"
[ -n "$annual_id" ] || { echo "error: annual plan creation returned no id" >&2; exit 1; }
echo "  annual:  $annual_id"

cat <<EOF

Done. Give these to the app (add them to your environment or Render service):

  export WHOP_PRODUCT_ID=$product_id
  export WHOP_WEEKLY_PLAN_ID=$weekly_id
  export WHOP_ANNUAL_PLAN_ID=$annual_id

Then restart it. The paywall reads them from /api/config and mounts the Whop
checkout overlay against those plan IDs. Without them the app still runs and
the paywall falls back to its demo unlock.
EOF
