#!/usr/bin/env python3
"""Keep the AudioIgniter radio player working on a static site: its track list comes
from a WordPress URL (/?audioigniter_playlist_id=N), so save that list as a plain JSON
file and point the player at it."""
import re, json, pathlib, urllib.request
OUT = pathlib.Path('site')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 site-owner-archive'
PAT = re.compile(r'data-tracks-url="[^"]*\?audioigniter_playlist_id=(\d+)"')
ids = set()
for p in OUT.rglob('*.html'):
    ids |= set(PAT.findall(p.read_text('utf-8', errors='ignore')))
for i in sorted(ids):
    req = urllib.request.Request(f'https://radyo10.com/?audioigniter_playlist_id={i}', headers={'User-Agent': UA})
    raw = urllib.request.urlopen(req, timeout=60).read().decode('utf-8')
    tracks = json.loads(raw)
    txt = raw.replace('https:\\/\\/radyo10.com\\/', '\\/').replace('https://radyo10.com/', '/')
    (OUT / f'audioigniter-playlist-{i}.json').write_text(txt, 'utf-8')
    print(f'playlist {i}:', [(t.get('title'), t.get('audio')) for t in tracks])
for p in OUT.rglob('*.html'):
    t = p.read_text('utf-8', errors='surrogateescape')
    n = PAT.sub(r'data-tracks-url="/audioigniter-playlist-\1.json"', t)
    if n != t:
        p.write_text(n, 'utf-8', errors='surrogateescape')
print('playlists saved:', sorted(ids))
