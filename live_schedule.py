"""
live_schedule.py
动态 VBTV 赛程抓取 → volleyballworld.com 比赛 ID 映射
server.py 通过 get_schedule() 获取赛程，每小时自动刷新
"""

import urllib.request
import ssl
import re
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
# 系统本地时区
LOCAL_TZ = datetime.now().astimezone().tzinfo
JW_SITE_ID = "fM9jRrkn"
M3U8_BASE = f"https://livecdn.euw1-0008.jwplive.com/live/sites/{JW_SITE_ID}/media"

# VBTV competition group pages
VBTV_URLS = [
    "https://tv.volleyballworld.com/competition-groups/XDclOMyU",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# English team name → country code
TEAM_TO_CODE = {
    'china': 'CHN', 'turkey': 'TUR', 'türkiye': 'TUR', 'turkiye': 'TUR',
    'bulgaria': 'BUL', 'italy': 'ITA', 'serbia': 'SRB', 'japan': 'JPN',
    'argentina': 'ARG', 'germany': 'GER', 'ukraine': 'UKR', 'brazil': 'BRA',
    'cuba': 'CUB', 'usa': 'USA', 'united states': 'USA',
    'poland': 'POL', 'belgium': 'BEL', 'france': 'FRA', 'iran': 'IRI',
    'slovenia': 'SLO', 'canada': 'CAN', 'netherlands': 'NED',
    'dominican republic': 'DOM', 'thailand': 'THA', 'korea': 'KOR',
    'south korea': 'KOR', 'czech republic': 'CZE', 'czechia': 'CZE',
    'portugal': 'POR', 'egypt': 'EGY', 'australia': 'AUS',
}

MONTH_MAP = {
    'january': '01', 'february': '02', 'march': '03', 'april': '04',
    'may': '05', 'june': '06', 'july': '07', 'august': '08',
    'september': '09', 'october': '10', 'november': '11', 'december': '12',
}

_lock = threading.Lock()
_live_schedule = []
_vw_id_cache = {}
_cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vw_match_cache.json')


def _create_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _load_vw_cache():
    """Load vwMatchId cache from disk, seed with static schedule_mapping"""
    global _vw_id_cache
    _vw_id_cache = {}
    if os.path.exists(_cache_file):
        try:
            with open(_cache_file, 'r', encoding='utf-8') as f:
                _vw_id_cache = json.load(f)
        except Exception:
            pass

    # Seed with known mappings from static schedule_mapping.py
    try:
        import schedule_mapping
        added = 0
        for m in schedule_mapping.SCHEDULE:
            if not m.get('vwMatchId') or not m.get('teamA') or not m.get('teamB'):
                continue
            g = m.get('gender', 'men')
            # Both orderings
            for a, b in [(m['teamA'], m['teamB']), (m['teamB'], m['teamA'])]:
                key = f"{a.lower()}_{b.lower()}_{g}"
                if key not in _vw_id_cache:
                    _vw_id_cache[key] = m['vwMatchId']
                    added += 1
        if added:
            print(f"[schedule] Seeded {added} vwMatchId entries from static mapping")
    except ImportError:
        pass


def _save_vw_cache():
    try:
        with open(_cache_file, 'w', encoding='utf-8') as f:
            json.dump(_vw_id_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[schedule] Failed to save cache: {e}")


def scrape_vbtv():
    """Scrape all VBTV competition group pages, return raw match list"""
    all_matches = []
    ssl_ctx = _create_ssl_ctx()

    for url in VBTV_URLS:
        print(f"[schedule] Fetching {url} ...")
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[schedule] VBTV fetch failed: {e}")
            continue

        # Extract __remixContext
        try:
            start = html.index('window.__remixContext = ') + len('window.__remixContext = ')
            end = html.index('window.__remixRouteModules', start)
        except ValueError:
            print("[schedule] __remixContext not found in page")
            continue

        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(html[start:end])
        except json.JSONDecodeError as e:
            print(f"[schedule] JSON decode failed: {e}")
            continue

        # Navigate to feed entries
        loader = data.get('state', {}).get('loaderData', {})
        route_keys = [k for k in loader if k != 'root']
        if not route_keys:
            print("[schedule] No route keys in loaderData")
            continue

        feeds = loader[route_keys[0]].get('serverLoadedFeeds', [])
        for feed_entry in feeds:
            feed = feed_entry.get('feed', {})
            for entry in feed.get('entry', []):
                etype = entry.get('type', {}).get('value', '')
                if etype not in ('liveEvent-future', 'liveEvent-live', 'liveEvent-replay'):
                    continue

                media_id = entry.get('id', '')
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                extensions = entry.get('extensions', {})

                # Teams: "China v Türkiye | Week 2 | Men's VNL 2026"
                teams_part = title.split('|')[0].strip() if '|' in title else title
                team_names = [t.strip() for t in teams_part.split(' v ')]

                # Date: "Wednesday, 24 June 2026"
                dm = re.search(r'(\w+day),\s*(\d+)\s+(\w+)\s+(\d{4})', summary)
                match_date = ''
                if dm:
                    match_date = f"{dm.group(4)}-{MONTH_MAP.get(dm.group(3).lower(), '00')}-{dm.group(2).zfill(2)}"

                # Local time from ScheduledEnd
                local_time = ''
                scheduled_end = extensions.get('VCH.ScheduledEnd', '')
                if scheduled_end:
                    try:
                        dt = datetime.fromisoformat(scheduled_end.replace('Z', '+00:00'))
                        local_time = dt.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M')
                    except Exception:
                        pass

                gender = 'men' if "Men's" in title or "Men" in title.split('|')[-1] else 'women'

                # Thumbnail
                thumb = ''
                for mg in entry.get('media_group', []):
                    if mg.get('type') == 'image':
                        for mi in mg.get('media_item', []):
                            if mi.get('key') in ('1280', '640', '320'):
                                thumb = mi.get('src', '')
                if not thumb:
                    thumb = f"https://cdn.jwplayer.com/v2/media/{media_id}/poster.jpg?width=640"

                all_matches.append({
                    'mediaId': media_id,
                    'teamA': team_names[0] if len(team_names) > 0 else '',
                    'teamB': team_names[1] if len(team_names) > 1 else '',
                    'date': match_date,
                    'localTime': local_time,
                    'gender': gender,
                    'm3u8': f"{M3U8_BASE}/{media_id}/live.isml/.m3u8",
                    'thumbnail': thumb,
                    'eventState': extensions.get('VCH.EventState', ''),
                })

    print(f"[schedule] VBTV returned {len(all_matches)} matches")
    return all_matches


def build_schedule():
    """Scrape VBTV + resolve vwMatchIds → full schedule list"""
    _load_vw_cache()

    vbtv_matches = scrape_vbtv()
    if not vbtv_matches:
        print("[schedule] VBTV empty, using static fallback")
        try:
            import schedule_mapping
            return schedule_mapping.SCHEDULE
        except ImportError:
            return []

    schedule = []
    for m in vbtv_matches:
        ta = m['teamA'].lower()
        tb = m['teamB'].lower()
        g = m['gender']

        # Look up vwMatchId from cache (both orderings, normalize Türkiye/Turkey)
        vw_id = None
        for ka, kb in [(ta, tb), (tb, ta)]:
            # direct
            vw_id = _vw_id_cache.get(f"{ka}_{kb}_{g}", 0)
            if vw_id: break
            # normalize
            na = ka.replace('türkiye', 'turkey').replace('turkiye', 'turkey')
            nb = kb.replace('türkiye', 'turkey').replace('turkiye', 'turkey')
            vw_id = _vw_id_cache.get(f"{na}_{nb}_{g}", 0)
            if vw_id: break
        if not vw_id:
            vw_id = 0

        code_a = TEAM_TO_CODE.get(ta, '')
        code_b = TEAM_TO_CODE.get(tb, '')

        schedule.append({
            "vwMatchId": vw_id or 0,
            "mediaId": m['mediaId'],
            "teamA": m['teamA'],
            "teamB": m['teamB'],
            "codeA": code_a,
            "codeB": code_b,
            "date": m['date'],
            "utcTime": "",
            "localTime": m['localTime'],
            "eventState": m['eventState'],
            "m3u8": m['m3u8'],
            "thumbnail": m['thumbnail'],
            "gender": m['gender'],
            "week": "auto",
        })

    return schedule


def get_schedule():
    """Thread-safe schedule access"""
    with _lock:
        return list(_live_schedule)


def _refresh_loop():
    global _live_schedule
    while True:
        time.sleep(3600)
        try:
            new_sch = build_schedule()
            with _lock:
                _live_schedule = new_sch
            print(f"[schedule] Refreshed: {len(new_sch)} matches")
        except Exception as e:
            print(f"[schedule] Refresh error: {e}")


def start():
    """Init schedule + launch background refresh thread"""
    global _live_schedule
    try:
        _live_schedule = build_schedule()
        print(f"[schedule] Ready: {len(_live_schedule)} matches")
    except Exception as e:
        print(f"[schedule] Init error: {e}, falling back to static")
        try:
            import schedule_mapping
            _live_schedule = schedule_mapping.SCHEDULE
        except ImportError:
            _live_schedule = []

    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
