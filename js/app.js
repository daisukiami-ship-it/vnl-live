/**
 * VNL Live - 鎺掔悆鐩存挱涓績
 * 鏁版嵁閫氳繃鏈湴 Python 鍚庣浠ｇ悊鎶撳彇 volleyballworld.com
 * 璧涚▼鏁版嵁鏉ヨ嚜 VBTV 鈫?VW 瀹屾暣鏄犲皠
 */

// 部署时自动用当前域名，本地开发用 127.0.0.1:8888
const API = window.location.hostname === 'localhost' ? 'http://127.0.0.1:8888/api' : '/api';
const FLAG_BASE = 'https://images.volleyballworld.com/image/upload/f_png/t_flag/assets/flags';

const CONFIG = {
  refreshInterval: 30000,
};

const APP = {
  state: {
    schedule: [],       // 璧涚▼鍒楄〃
    currentMatch: null, // 褰撳墠閫変腑鐨勬瘮璧?    matchData: null,    // 姣旇禌瀹炴椂鏁版嵁 (API)
    playersA: [],       // Team A 鐞冨憳缁熻 (API)
    playersB: [],       // Team B 鐞冨憳缁熻 (API)
    rosterA: [],        // Team A 鐞冨憳鍚嶅崟 (CSV)
    rosterB: [],        // Team B 鐞冨憳鍚嶅崟 (CSV)
  },

  /* ========== 鍒濆鍖?========== */
  async init() {
    this.initPlayer();
    this.bindEvents();
    await this.loadSchedule();
    this.startPolling();
  },

  /* ---- HLS 鎾斁鍣?---- */
  initPlayer() {
    this._hlsInstance = null;
    this._video = document.getElementById('video-player');
    this._placeholder = document.getElementById('player-placeholder');
  },

  switchHlsSource(m3u8Url) {
    const video = this._video;
    const placeholder = this._placeholder;

    // 娓呯悊鏃у疄渚?    if (this._hlsInstance) {
      this._hlsInstance.destroy();
      this._hlsInstance = null;
    }
    video.pause();
    video.removeAttribute('src');

    if (!m3u8Url) {
      placeholder.classList.remove('hidden');
      placeholder.querySelector('p').textContent = '鏃犵洿鎾簮';
      return;
    }

    if (Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        backBufferLength: 90,
      });
      hls.loadSource(m3u8Url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        placeholder.classList.add('hidden');
        video.play().catch(() => {});
      });
      hls.on(Hls.Events.ERROR, (event, data) => {
        if (data.fatal) {
          console.error('HLS error:', data.type, data.details);
          placeholder.classList.remove('hidden');
          placeholder.querySelector('p').textContent = '鐩存挱婧愭殏涓嶅彲鐢?;
        }
      });
      this._hlsInstance = hls;
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = m3u8Url;
      video.addEventListener('loadedmetadata', () => placeholder.classList.add('hidden'), { once: true });
    }
  },

  /* ---- 浜嬩欢缁戝畾 ---- */
  bindEvents() {
    document.getElementById('btn-refresh').addEventListener('click', () => this.refreshAll());
    document.getElementById('btn-fullscreen').addEventListener('click', () => {
      const el = document.getElementById('area-live');
      document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen();
    });
    document.querySelectorAll('.nav-menu a').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        document.querySelector('.nav-menu a.active')?.classList.remove('active');
        a.classList.add('active');
      });
    });
  },

  /* ========== 璧涚▼鍔犺浇 ========== */
  async loadSchedule() {
    try {
      const res = await fetch(`${API}/schedule`);
      this.state.schedule = await res.json();
      this.renderSchedule();
      // 榛樿閫変腑绗竴鍦?      if (this.state.schedule.length > 0) {
        this.selectMatch(this.state.schedule[0]);
      }
    } catch (e) {
      console.error('Schedule load failed:', e);
      document.getElementById('schedule-list').innerHTML =
        '<div class="loading-hint">璧涚▼鍔犺浇澶辫触</div>';
    }
  },

  renderSchedule() {
    const container = document.getElementById('schedule-list');
    const list = this.state.schedule;
    if (!list.length) {
      container.innerHTML = '<div class="loading-hint">鏆傛棤姣旇禌</div>';
      return;
    }

    // 鎸夋棩鏈熷垎缁?    const groups = {};
    list.forEach(m => {
      const d = m.date || m.localTime?.slice(0, 10) || '寰呭畾';
      if (!groups[d]) groups[d] = [];
      groups[d].push(m);
    });

    const flagUrl = (code) => `${FLAG_BASE}/flag_${code.toLowerCase()}`;
    const timeStr = (m) => {
      if (m.localTime) return m.localTime.slice(11, 16); // "23:00"
      return '--:--';
    };
    const stateLabel = (m) => {
      switch (m.eventState) {
        case 'LIVE': return '<span class="sch-state live">鐩存挱涓?/span>';
        case 'PRE_LIVE': return `<span class="sch-state upcoming">${timeStr(m)}</span>`;
        case 'FINISHED': return '<span class="sch-state finished">宸茬粨鏉?/span>';
        default: return `<span class="sch-state upcoming">${timeStr(m)}</span>`;
      }
    };

    container.innerHTML = Object.entries(groups).map(([date, matches]) => `
      <div class="sch-group">
        <div class="sch-date">${date}</div>
        ${matches.map(m => `
          <div class="sch-item" data-match-id="${m.vwMatchId}"
               onclick="APP.selectMatchById(${m.vwMatchId})">
            <div class="sch-teams">
              <span class="sch-team-left">
                <img class="sch-flag" src="${flagUrl(m.codeA)}" onerror="this.style.display='none'">
                <span class="sch-team-name">${m.codeA}</span>
              </span>
              <span class="sch-vs">vs</span>
              <span class="sch-team-right">
                <span class="sch-team-name">${m.codeB}</span>
                <img class="sch-flag" src="${flagUrl(m.codeB)}" onerror="this.style.display='none'">
              </span>
            </div>
            <div class="sch-meta">${stateLabel(m)}</div>
          </div>
        `).join('')}
      </div>
    `).join('');
  },

  /* ========== 閫変腑姣旇禌 ========== */
  selectMatchById(matchId) {
    const m = this.state.schedule.find(s => s.vwMatchId === matchId);
    if (m) this.selectMatch(m);
  },

  selectMatch(match) {
    this.state.currentMatch = match;
    this.state.matchId = match.vwMatchId;

    // 鏇存柊楂樹寒
    document.querySelectorAll('.sch-item').forEach(el => el.classList.remove('active'));
    const el = document.querySelector(`.sch-item[data-match-id="${match.vwMatchId}"]`);
    if (el) el.classList.add('active');

    // 鏇存柊椤堕儴鏍囬
    document.getElementById('nav-match-title').textContent =
      `${match.codeA} vs ${match.codeB}`;

    // 鏇存柊鍥芥棗
    const flagUrl = (code) => `${FLAG_BASE}/flag_${code.toLowerCase()}`;
    document.getElementById('flag-a').src = flagUrl(match.codeA);
    document.getElementById('flag-b').src = flagUrl(match.codeB);
    document.getElementById('team-a-name').textContent = match.teamA;
    document.getElementById('team-b-name').textContent = match.teamB;

    // 鏇存柊瑙嗛婧?    this.switchHlsSource(match.m3u8 || null);

    // 鍔犺浇涓ら槦鐞冨憳鍚嶅崟
    this.loadRosters(match.codeA, match.codeB);

    // 鍔犺浇姣旇禌鏁版嵁鍜岀悆鍛樼粺璁?    this.loadMatchData();
    this.loadPlayerStats();

    // 鏇存柊鐞冨憳缁熻鏍囩
    document.querySelectorAll('#player-stats-tabs .tab-btn')[0]?.setAttribute('data-team', 'a');
    document.querySelectorAll('#player-stats-tabs .tab-btn')[0].textContent = match.codeA;
    document.querySelectorAll('#player-stats-tabs .tab-btn')[1]?.setAttribute('data-team', 'b');
    document.querySelectorAll('#player-stats-tabs .tab-btn')[1].textContent = match.codeB;
    document.querySelectorAll('#player-stats-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('#player-stats-tabs .tab-btn[data-team="a"]')?.classList.add('active');
    this.currentStatTeam = 'a';
  },

  updateScoreBar() { /* 姣斿垎鏍忓凡绉婚櫎 */ },

  /* ========== 鐞冨憳鍚嶅崟 (CSV) ========== */
  async loadRosters(codeA, codeB) {
    const gender = this.state.currentMatch?.gender ? `?gender=${this.state.currentMatch.gender}` : '';
    const [resA, resB] = await Promise.all([
      fetch(`${API}/roster/${codeA}${gender}`),
      fetch(`${API}/roster/${codeB}${gender}`),
    ]);
    const rosterA = await resA.json();
    const rosterB = await resB.json();
    this.state.rosterA = rosterA;
    this.state.rosterB = rosterB;
    this.renderRoster('roster-table-a', rosterA);
    this.renderRoster('roster-table-b', rosterB);
  },

  renderRoster(tableId, players) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    if (!players || !players.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary)">鏆傛棤鏁版嵁</td></tr>';
      return;
    }
    tbody.innerHTML = players.map(p => `
      <tr>
        <td>${p[1]}</td>
        <td>${p[2]}</td>
        <td class="pos">${p[3]}</td>
        <td class="r">${p[4]}</td>
        <td class="r">${p[5]}</td>
        <td class="club">${p[6]}</td>
      </tr>
    `).join('');
  },

  /* ========== 姣旇禌瀹炴椂鏁版嵁 ========== */
  async loadMatchData() {
    try {
      const res = await fetch(`${API}/match/${this.state.matchId}`);
      const data = await res.json();
      if (data.error) {
        this.updateScoreBar();
        return;
      }
      this.state.matchData = data;
      this.renderMatchBar(data);
    } catch (e) {
      console.error('Match data:', e);
      this.updateScoreBar();
    }
  },

  renderMatchBar(data) { /* 姣斿垎鏍忓凡绉婚櫎 */ },

  /* ========== 鐞冨憳缁熻 (API) ========== */
  async loadPlayerStats() {
    try {
      const res = await fetch(`${API}/players/${this.state.matchId}`);
      const html = await res.text();
      if (!html.trim()) {
        this.state.playersA = [];
        this.state.playersB = [];
        this.renderPlayerStatsDetail();
        return;
      }
      this.parsePlayerStats(html);
    } catch (e) {
      console.error('Player stats:', e);
      this.state.playersA = [];
      this.state.playersB = [];
      this.renderPlayerStatsDetail();
    }
  },

  parsePlayerStats(html) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');

    const parseTable = (table) => {
      if (!table) return [];
      const rows = table.querySelectorAll('tbody tr.vbw-o-table__row--scoring');
      const players = [];
      rows.forEach(row => {
        const shirt = row.querySelector('.shirtnumber')?.textContent.trim();
        const nameEl = row.querySelector('.playername');
        const name = nameEl?.textContent.trim();
        const pos = row.querySelector('.position')?.textContent.trim();
        if (!shirt || !name) return;
        const pt = (sel) => row.querySelector(sel)?.textContent.trim() || '-';
        players.push({
          shirt, name, pos: pos || '',
          totalAbs: pt('.total-abs'),
          attacks: pt('.attacks'),
          blocks: pt('.blocks'),
          serves: pt('.serves'),
          errors: pt('.errors'),
          efficiency: pt('.efficiency-percentage'),
        });
      });
      return players;
    };

    const tableA = doc.querySelector('table[data-stattype="scoring"]:not(.hidden)');
    const tableB = doc.querySelector('table[data-stattype="scoring"][data-team="teamb"]');
    this.state.playersA = parseTable(tableA);
    this.state.playersB = parseTable(tableB);

    // 鐢?CSV 鍚嶅崟涓殑涓枃鍚嶆浛鎹?API 鑻辨枃鍚?    const buildNameMap = (roster) => {
      const map = {};
      roster.forEach(r => { map[r[1]] = r[2]; });
      return map;
    };
    if (this.state.rosterA.length) {
      const map = buildNameMap(this.state.rosterA);
      this.state.playersA.forEach(p => {
        if (map[p.shirt]) p.name = map[p.shirt];
      });
    }
    if (this.state.rosterB.length) {
      const map = buildNameMap(this.state.rosterB);
      this.state.playersB.forEach(p => {
        if (map[p.shirt]) p.name = map[p.shirt];
      });
    }

    // 宸︿晶鍚嶅崟鍙樉绀哄疄闄呭嚭鍦烘湁缁熻鐨勭悆鍛?    this.filterRostersByStats();

    this.renderPlayerStatsDetail();
    if (!this._tabsBound) {
      this.bindPlayerStatTabs();
      this._tabsBound = true;
    }
  },

  /* 鎸夌悆鍛樼粺璁′腑鐨勮儗鍙疯繃婊ゅ乏渚у悕鍗?*/
  filterRostersByStats() {
    const aShirts = new Set(this.state.playersA.map(p => p.shirt));
    const bShirts = new Set(this.state.playersB.map(p => p.shirt));
    if (aShirts.size > 0) {
      const filtered = this.state.rosterA.filter(p => aShirts.has(p[1]));
      this.renderRoster('roster-table-a', filtered);
    }
    if (bShirts.size > 0) {
      const filtered = this.state.rosterB.filter(p => bShirts.has(p[1]));
      this.renderRoster('roster-table-b', filtered);
    }
  },

  /* ---- 涓爮锛歁atch Statistics by Player ---- */
  currentStatTeam: 'a',

  bindPlayerStatTabs() {
    document.querySelectorAll('#player-stats-tabs .tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#player-stats-tabs .tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.currentStatTeam = btn.dataset.team;
        this.renderPlayerStatsDetail();
      });
    });
  },

  renderPlayerStatsDetail() {
    const players = this.currentStatTeam === 'a' ? this.state.playersA : this.state.playersB;
    const container = document.getElementById('player-stats-content');
    if (!players || players.length === 0) {
      container.innerHTML = '<div class="loading-hint">鏆傛棤鏁版嵁锛堟瘮璧涙湭寮€濮嬫垨鏁版嵁涓嶅彲鐢級</div>';
      return;
    }

    const fmt = (v) => {
      if (v === '-' || v === '' || v == null) return '<span class="num-zero">-</span>';
      const n = parseInt(v);
      if (isNaN(n)) return v;
      return n === 0 ? `<span class="num-zero">0</span>` : `<span class="num-highlight">${n}</span>`;
    };

    container.innerHTML = `
      <table class="ps-table">
        <thead><tr>
          <th>#</th><th class="col-player">Player</th><th>Pos</th>
          <th>Total</th><th>Attack</th><th>Block</th><th>Serve</th><th>Error</th><th>Eff%</th>
        </tr></thead>
        <tbody>${players.map(p => `
          <tr>
            <td class="col-no">${p.shirt}</td>
            <td class="col-player">${p.name}</td>
            <td class="col-pos">${p.pos}</td>
            <td>${fmt(p.totalAbs)}</td><td>${fmt(p.attacks)}</td>
            <td>${fmt(p.blocks)}</td><td>${fmt(p.serves)}</td>
            <td>${fmt(p.errors)}</td>
            <td>${p.efficiency !== '-' && p.efficiency ? p.efficiency : '<span class="num-zero">-</span>'}</td>
          </tr>
        `).join('')}</tbody>
      </table>`;
  },

  /* ========== 瀹氭椂鍒锋柊 ========== */
  startPolling() {
    setInterval(() => this.refreshAll(), CONFIG.refreshInterval);
  },

  async refreshAll() {
    const match = this.state.currentMatch;
    if (!match) return;
    await Promise.all([
      this.loadMatchData(),
      this.loadPlayerStats(),
    ]);
  },
};

document.addEventListener('DOMContentLoaded', () => APP.init());

