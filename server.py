"""
VNL Live - 数据代理后端
抓取 volleyballworld.com 数据，提供给前端

启动: python server.py
端口: 8888
"""

import json
import re
import csv
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import schedule_mapping
import live_schedule
import mimetypes
from urllib.parse import urlparse, parse_qs

mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')

BASE_URL = "https://en.volleyballworld.com"
LIVE_API = "https://en-live.volleyballworld.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

CACHE = {}
CACHE_TTL = {
    'match': 10, 'players': 30, 'team_stats': 30,
    'boxscore': 30, 'playbyplay': 30, 'roster': 300,
}

# Country code → Chinese name
CODE_TO_CN = {
    'CHN': '中国', 'TUR': '土耳其', 'BUL': '保加利亚', 'ITA': '意大利',
    'SRB': '塞尔维亚', 'JPN': '日本', 'ARG': '阿根廷', 'GER': '德国',
    'UKR': '乌克兰', 'BRA': '巴西', 'CUB': '古巴', 'USA': '美国',
    'POL': '波兰', 'BEL': '比利时', 'FRA': '法国', 'IRI': '伊朗',
    'SLO': '斯洛文尼亚', 'CAN': '加拿大',
}
CN_TO_CODE = {v: k for k, v in CODE_TO_CN.items()}

# CSV 根目录
CSV_DIR = os.path.dirname(os.path.abspath(__file__))


def fetch_url(url, timeout=10):
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://en.volleyballworld.com/",
    })
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "text/html")


def cache_get(key):
    entry = CACHE.get(key)
    if entry:
        ts, data = entry
        if (datetime.now() - ts).total_seconds() < CACHE_TTL.get(key.split(':')[0], 10):
            return data
    return None


def cache_set(key, data):
    CACHE[key] = (datetime.now(), data)


def load_roster(code, gender=None):
    """从 CSV 加载某个国家的球员名单。gender='men'/'women'/None(全部)"""
    cn_name = CODE_TO_CN.get(code.upper())
    if not cn_name:
        return []
    players = []
    all_files = [
        ('VNL2026_男排名单_合并.csv', 'men'),
        ('VNL2026_全部女排名单_合并.csv', 'women'),
    ]
    for fname, fgender in all_files:
        if gender and fgender != gender:
            continue
        fp = os.path.join(CSV_DIR, fname)
        if not os.path.exists(fp):
            continue
        with open(fp, 'r', encoding='utf-8-sig') as f:
            for row in csv.reader(f):
                if len(row) < 7:
                    continue
                if row[0] == cn_name:
                    players.append(row)
    players.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 999)
    return players


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def _send(self, code, body, ct="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", f"{ct}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip("/")
        try:
            # /api/schedule — 赛程列表
            if path == "/api/schedule":
                return self.handle_schedule()

            # /api/schedule/<matchId> — 单场比赛元数据
            if m := re.match(r"^/api/schedule/(\d+)$", path):
                return self.handle_schedule_by_id(int(m.group(1)))

            # /api/roster/<code> — 国家代码球员名单
            if m := re.match(r"^/api/roster/([A-Za-z]{3})", path):
                return self.handle_roster(m.group(1).upper())

            # /api/match/<id> — 比赛实时数据
            if m := re.match(r"^/api/match/(\d+)$", path):
                return self.handle_match(int(m.group(1)))

            # /api/players/<id> — 球员统计数据 HTML
            if m := re.match(r"^/api/players/(\d+)$", path):
                return self.handle_players(int(m.group(1)))

            # /api/team-stats/<id>
            if m := re.match(r"^/api/team-stats/(\d+)$", path):
                return self.handle_team_stats(int(m.group(1)))

            # try static file serving
            self._serve_static()
        except Exception as e:
            print(f"Error: {e}")
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))

    def _serve_static(self):
        path = self.path.lstrip("/")
        if not path:
            path = "index.html"
        fp = os.path.normpath(os.path.join(CSV_DIR, path))
        if not fp.startswith(CSV_DIR):
            return self._send(403, json.dumps({"error": "Forbidden"}, ensure_ascii=False))
        if not os.path.isfile(fp):
            return self._send(404, json.dumps({"error": "Not found"}, ensure_ascii=False))
        ct = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        with open(fp, "rb") as f:
            self._send(200, f.read(), ct)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    # ==================== Schedule ====================

    def handle_schedule(self):
        cached = cache_get("schedule")
        if cached:
            return self._send(200, cached)
        sch = live_schedule.get_schedule() or schedule_mapping.SCHEDULE
        data = json.dumps(sch, ensure_ascii=False)
        cache_set("schedule", data)
        self._send(200, data)

    def handle_schedule_by_id(self, match_id):
        sch = live_schedule.get_schedule() or schedule_mapping.SCHEDULE
        for m in sch:
            if m['vwMatchId'] == match_id:
                return self._send(200, json.dumps(m, ensure_ascii=False))
        self._send(404, json.dumps({"error": "Match not found"}, ensure_ascii=False))

    # ==================== Roster ====================

    def handle_roster(self, code):
        # parse ?gender= query param
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        gender = qs.get('gender', [None])[0]
        if gender not in ('men', 'women', None):
            gender = None
        cache_key = f"roster:{code}:{gender}"
        cached = cache_get(cache_key)
        if cached:
            return self._send(200, cached)
        print(f"  [roster] loading {code} gender={gender} → cn={CODE_TO_CN.get(code)} csv_dir={CSV_DIR}")
        players = load_roster(code, gender)
        print(f"  [roster] {code}: {len(players)} players")
        data = json.dumps(players, ensure_ascii=False)
        cache_set(cache_key, data)
        self._send(200, data)

    # ==================== Match Data ====================

    def handle_match(self, match_id):
        cache_key = f"match:{match_id}"
        cached = cache_get(cache_key)
        if cached is not None:
            return self._send(200, cached)
        try:
            url = f"{LIVE_API}/api/v1/live/matches/{match_id}"
            body, _ = fetch_url(url, timeout=8)
            data = body.decode()
            cache_set(cache_key, data)
            self._send(200, body, "application/json")
        except (HTTPError, URLError, OSError, TimeoutError) as e:
            print(f"  Match {match_id} API failed: {e}")
            data = json.dumps({"error": True, "message": "比赛数据暂时不可用"}, ensure_ascii=False)
            self._send(200, data)  # 返回 200 让前端正常处理

    def handle_players(self, match_id):
        cache_key = f"players:{match_id}"
        cached = cache_get(cache_key)
        if cached is not None:
            return self._send(200, cached, "text/html")
        try:
            url = f"{BASE_URL}/volleyball/competitions/volleyball-nations-league/schedule/{match_id}/_libraries/live/_volley-match-statistics-by-player"
            body, _ = fetch_url(url, timeout=8)
            data = body.decode(errors='ignore')
            cache_set(cache_key, data)
            self._send(200, data, "text/html")
        except (HTTPError, URLError, OSError, TimeoutError) as e:
            print(f"  Players {match_id} failed: {e}")
            self._send(200, "", "text/html")

    def handle_team_stats(self, match_id):
        cache_key = f"team_stats:{match_id}"
        cached = cache_get(cache_key)
        if cached is not None:
            return self._send(200, cached, "text/html")
        try:
            url = f"{BASE_URL}/volleyball/competitions/volleyball-nations-league/schedule/{match_id}/_libraries/live/_volley-match-statistics-by-team"
            body, _ = fetch_url(url, timeout=8)
            data = body.decode(errors='ignore')
            cache_set(cache_key, data)
            self._send(200, data, "text/html")
        except (HTTPError, URLError, OSError, TimeoutError) as e:
            print(f"  TeamStats {match_id} failed: {e}")
            self._send(200, "", "text/html")


def main():
    live_schedule.start()  # auto-scrape VBTV, hourly refresh
    port = int(os.environ.get("PORT", 8888))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"VNL Live backend: http://localhost:{port}")
    print(f"  Schedule: /api/schedule")
    print(f"  Roster: /api/roster/CHN")
    print(f"  Match: /api/match/26621")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
