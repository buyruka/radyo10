#!/usr/bin/env bash
# Mirror a (WordPress) site into ./crawl with wget, politely.
# Required env: START_URLS (space separated), DOMAINS (comma separated)
# Optional env: REJECT_REGEX, WAIT, NO_PARENT=1, UA
set -uo pipefail

UA="${UA:-Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 site-owner-archive}"
REJECT_REGEX="${REJECT_REGEX:-/wp-login\.php|/wp-admin/|/xmlrpc\.php|/wp-json/|/wp-cron\.php|[?&](replytocom|share|s|p|page_id|attachment_id|preview|amp|doing_wp_cron)=|/trackback/?$|\.mp3$}"

mkdir -p crawl
set -x
wget --mirror --page-requisites --adjust-extension \
  --span-hosts --domains="$DOMAINS" \
  -e robots=off --wait="${WAIT:-0.3}" --random-wait \
  --tries=3 --timeout=60 --no-verbose \
  --user-agent="$UA" \
  --reject-regex="$REJECT_REGEX" \
  ${NO_PARENT:+--no-parent} \
  --directory-prefix=crawl \
  $START_URLS 2> crawl.log
code=$?
set +x
echo "wget finished with exit code $code (8 just means some links returned errors such as 404)"
echo "Files fetched: $(grep -c ' URL:' crawl.log || true)"
echo "Errors logged: $(grep -ciE 'ERROR [0-9]{3}' crawl.log || true)"
grep -E 'ERROR [0-9]{3}' crawl.log | head -40 || true
exit 0
