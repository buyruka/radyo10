#!/usr/bin/env python3
"""Turn a wget mirror of a WordPress site (./crawl) into a static site (./site)
that works on Cloudflare Pages, both on its *.pages.dev test address and on the
real domain.

Environment:
  HOSTS          comma list of host names, primary first (www.example.com,example.com)
  ORIGIN         base URL used to fetch anything missing (https://www.example.com)
  KEEP_FEEDS     comma list of feed paths to keep (/feed/,/feed/podcast/)
  SEARCH_SITE    if set, WordPress search boxes are pointed at Google site search
  SKIP_FETCH     regex of paths never to download (default: \\.mp3$)
  REDIRECTS      text written to site/_redirects
  HEADERS        text written to site/_headers
"""
import os, re, sys, shutil, pathlib, urllib.parse, urllib.request, time

CRAWL = pathlib.Path('crawl')
OUT = pathlib.Path('site')
HOSTS = [h.strip() for h in os.environ['HOSTS'].split(',') if h.strip()]
ORIGIN = os.environ['ORIGIN'].rstrip('/')
KEEP_FEEDS = {f.strip() for f in os.environ.get('KEEP_FEEDS', '/feed/').split(',') if f.strip()}
SEARCH_SITE = os.environ.get('SEARCH_SITE', '').strip()
SKIP_FETCH = re.compile(os.environ.get('SKIP_FETCH', r'\.mp3$'), re.I)
UA = os.environ.get('UA', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/130.0 Safari/537.36 site-owner-archive')
ASSET_EXT = re.compile(r'\.(jpe?g|png|gif|webp|svg|ico|bmp|css|js|woff2?|ttf|eot|otf|pdf|mp4|webm|m4a|ogg|json|xml|txt)$', re.I)
CHALLENGE_MARKERS = ('Please wait while your request is being verified', 'One moment, please...')
TEXT_EXT = ('.html', '.htm', '.css', '.js', '.json')


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 1. merge hosts
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir()
for host in reversed(HOSTS):          # primary host copied last, so it wins
    src = CRAWL / host
    if not src.exists():
        continue
    for p in src.rglob('*'):
        if p.is_file():
            dest = OUT / p.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
log('merged hosts:', [h for h in HOSTS if (CRAWL / h).exists()])

# ------------------------------------------- 2. strip ?ver=... from file names
renamed = dropped = 0
for p in sorted(OUT.rglob('*'), key=lambda x: -len(str(x))):
    if p.is_file() and '?' in p.name:
        base = p.with_name(p.name.split('?')[0])
        if base.exists():
            p.unlink(); dropped += 1
        else:
            p.rename(base); renamed += 1
log(f'query-string files: renamed {renamed}, dropped duplicates {dropped}')

# ------------------------------------------------ 3. drop per-post/category feeds
removed_feeds = 0
for d in sorted([d for d in OUT.rglob('feed') if d.is_dir()], key=lambda x: -len(str(x))):
    url = '/' + d.relative_to(OUT).as_posix() + '/'
    if url in KEEP_FEEDS or any(k.startswith(url) for k in KEEP_FEEDS):
        continue
    shutil.rmtree(d); removed_feeds += 1
log(f'removed {removed_feeds} per-post/category feed folders; kept {sorted(KEEP_FEEDS)}')

# ------------------------------------------- 4. make links root-relative
bases = [s + h for h in HOSTS for s in ('https://', 'http://')]
PROTECT = re.compile(r'<link\b[^>]*\brel=["\'](?:canonical|shortlink|alternate)["\'][^>]*>'
                     r'|<meta\b[^>]*(?:property|name)=["\'](?:og:url|twitter:url)["\'][^>]*>', re.I)
FORM = re.compile(r'(<form\b[^>]*>)(.*?)(</form>)', re.S | re.I)


def fix_search(m):
    start, body, end = m.groups()
    if not re.search(r'\bname=["\']s["\']', body):
        return m.group(0)
    if re.search(r'\baction=', start, re.I):
        start = re.sub(r'\baction=["\'][^"\']*["\']', 'action="https://www.google.com/search"', start, flags=re.I)
    else:
        start = start[:-1] + ' action="https://www.google.com/search">'
    body = re.sub(r'\bname=["\']s["\']', 'name="q"', body)
    body += f'<input type="hidden" name="as_sitesearch" value="{SEARCH_SITE}">'
    return start + body + end


def rewrite(text, is_html):
    kept = []
    if is_html:
        text = PROTECT.sub(lambda m: (kept.append(m.group(0)), f'\x00{len(kept)-1}\x00')[1], text)
    for b in bases:
        text = text.replace(b + '/', '/')
        text = text.replace(b.replace('/', '\\/') + '\\/', '\\/')
        text = re.sub(r'(["\'])' + re.escape(b) + r'(["\'])', r'\1/\2', text)
    if is_html:
        text = re.sub('\x00(\\d+)\x00', lambda m: kept[int(m.group(1))], text)
        if SEARCH_SITE:
            text = FORM.sub(fix_search, text)
    return text


changed = 0
for p in OUT.rglob('*'):
    if p.is_file() and (p.suffix.lower() in TEXT_EXT or p.name == 'index.html'):
        # feeds are saved as feed/index.html but are XML: keep their absolute links
        raw = p.read_bytes()
        if raw.lstrip()[:5] == b'<?xml':
            continue
        txt = raw.decode('utf-8', errors='surrogateescape')
        new = rewrite(txt, p.suffix.lower() in ('.html', '.htm'))
        if new != txt:
            p.write_bytes(new.encode('utf-8', errors='surrogateescape')); changed += 1
log(f'rewrote links in {changed} files')

# ------------------------------------- 5. fetch referenced assets that are missing
ATTR = re.compile(r'''(?:src|href|data-src|data-lazy-src|data-bg|data-full|data-large-file|data-orig-file|poster)\s*=\s*["']([^"']+)["']''', re.I)
SRCSET = re.compile(r'''(?:srcset|data-srcset|data-lazy-srcset)\s*=\s*["']([^"']+)["']''', re.I)
CSSURL = re.compile(r'''url\(\s*['"]?([^'")]+?)['"]?\s*\)''', re.I)


def local_path(urlpath):
    path = urllib.parse.unquote(urlpath.split('#')[0].split('?')[0])
    if not path.startswith('/'):
        return None
    if path.endswith('/'):
        path += 'index.html'
    return OUT / path.lstrip('/')


def refs_in(p):
    txt = p.read_text('utf-8', errors='ignore')
    found = set(ATTR.findall(txt)) | set(CSSURL.findall(txt))
    for s in SRCSET.findall(txt):
        for part in s.split(','):
            bits = part.strip().split()
            if bits:
                found.add(bits[0])
    page_url = '/' + p.relative_to(OUT).as_posix()
    out = set()
    for u in found:
        u = u.strip()
        if not u or u.startswith(('data:', 'mailto:', 'javascript:', '#', '//')):
            continue
        if u.startswith(('http://', 'https://')):
            pu = urllib.parse.urlparse(u)
            if pu.netloc not in HOSTS:
                continue
            u = pu.path
        else:
            u = urllib.parse.urljoin(page_url, u)
        out.add(u.split('#')[0].split('?')[0])
    return out


fetched, failed, failed_urls = 0, [], set()
for round_no in (1, 2):
    wanted = set()
    for p in OUT.rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.html', '.htm', '.css'):
            for u in refs_in(p):
                if ASSET_EXT.search(u) and not SKIP_FETCH.search(u) and u not in failed_urls:
                    lp = local_path(u)
                    if lp is not None and not lp.exists():
                        wanted.add(u)
    log(f'round {round_no}: {len(wanted)} referenced assets missing')
    for u in sorted(wanted):
        lp = local_path(u)
        try:
            req = urllib.request.Request(ORIGIN + urllib.parse.quote(urllib.parse.unquote(u)), headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(data)
            if lp.suffix.lower() == '.css':
                lp.write_text(rewrite(lp.read_text('utf-8', errors='surrogateescape'), False), 'utf-8', errors='surrogateescape')
            fetched += 1
            time.sleep(0.2)
        except Exception as e:  # missing on the server too (404) etc.
            failed.append(f'{u} ({e})'); failed_urls.add(u)
log(f'fetched {fetched} missing assets; {len(failed)} could not be fetched')
for f in failed[:60]:
    log('  missing:', f)

# --------------------------------------------- 6. bot-challenge page detection
bad = []
for p in OUT.rglob('*.html'):
    t = p.read_text('utf-8', errors='ignore')
    if any(c in t for c in CHALLENGE_MARKERS):
        bad.append(p.relative_to(OUT).as_posix())
if bad:
    log(f'ERROR: {len(bad)} pages are bot-challenge pages, not real content, e.g. {bad[:10]}')
    sys.exit(2)

# ----------------------------------------------------- 7. Pages config files
if os.environ.get('REDIRECTS'):
    (OUT / '_redirects').write_text(os.environ['REDIRECTS'].strip() + '\n', 'utf-8')
if os.environ.get('HEADERS'):
    (OUT / '_headers').write_text(os.environ['HEADERS'].strip() + '\n', 'utf-8')

# ------------------- 8. set aside files over Cloudflare's 25 MiB per-file limit
too_big = []
for p in [p for p in OUT.rglob('*') if p.is_file() and p.stat().st_size > 25 * 1024 * 1024]:
    rel = p.relative_to(OUT).as_posix()
    too_big.append((rel, p.stat().st_size))
    dest = pathlib.Path('oversize') / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), dest)

# --------------------------------------------------------------- 9. report
files = [p for p in OUT.rglob('*') if p.is_file()]
total = sum(p.stat().st_size for p in files)
html_pages = sum(1 for p in files if p.suffix.lower() == '.html')
report = [
    f'# Archive build report',
    f'- files: {len(files)} (Cloudflare Pages free limit: 20,000)',
    f'- HTML pages: {html_pages}',
    f'- total size: {total/1024/1024:.1f} MB',
    f'- files over 25 MiB set aside in oversize/ (not deployed): {len(too_big)} {too_big[:10]}',
    f'- missing assets that the old server could not supply: {len(failed)}',
]
pathlib.Path('crawl-report.md').write_text('\n'.join(report) + '\n\n' + '\n'.join(f'  - {f}' for f in failed[:200]) + '\n', 'utf-8')
log('\n'.join(report))
if len(files) > 20000:
    log('WARNING: more than 20,000 files - Cloudflare Pages free plan will refuse this deployment')
