# radyo10.com - Balıkesir Radyo 10

**Since 24 November 2026 radyo10.com permanently (301) forwards to https://radyoon.net/** (see `site/_redirects`).
The old site below is kept untouched for a rollback: delete `site/_redirects` and it is live again
about a minute later. A frozen copy is also on the `2026-11-24-before-redirect` branch.

The radyo10.com website as a static site, served by Cloudflare Pages. Any change saved
to the files in `site/` goes live automatically about a minute later.

## How to edit a page
1. Open the `site` folder above. The home page is `site/index.html`; the other pages
   keep the old addresses, e.g. radyo10.com/index.php/hakkimizda/ is
   `site/index.php/hakkimizda/index.html`.
2. Click the pencil icon (Edit this file), change the text, and click **Commit changes**.
3. Wait about a minute and refresh the website.

The radio player's station address lives in `site/audioigniter-playlist-29.json`
(the `"audio"` value). In November 2026 the old address
(http://sunucu2.radyosfer.com:9362/stream) was no longer answering, so put the
station's current stream address there to make the player play again.
