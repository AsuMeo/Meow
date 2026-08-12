"""
music.py — VK Music Web Scraper
Работает через cookie-сессию vk.com (как неофициальные клиенты)
Авторизация: remixsid/remixsid6 из браузера или логин/пароль через vk_api
"""

import os
import re
import json
import time
import random
import hashlib
import threading
import requests
from urllib.parse import quote, unquote, parse_qs
from flask import Blueprint, request, jsonify, Response, render_template_string

# ─── CONFIG ───
VK_DOMAIN = "vk.com"
VK_AUDIO_URL = f"https://{VK_DOMAIN}/al_audio.php"
VK_LOGIN_URL = f"https://{VK_DOMAIN}/login"

# Thread-local session
_session_local = threading.local()

def get_session():
    if not hasattr(_session_local, 'session'):
        _session_local.session = requests.Session()
        _session_local.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': f'https://{VK_DOMAIN}/',
            'X-Requested-With': 'XMLHttpRequest',
        })
    return _session_local.session

# ─── AUTH STATE ───
_auth_state = {
    'vk_id': None,
    'remixsid': None,
    'remixsid6': None,
    'logged_in': False,
    'csrf_hash': None,
    'last_auth': 0,
}

# ─── VK API FALLBACK (для получения токена через логин/пароль) ───
def _try_vk_api_auth(login, password):
    """Пробуем авторизоваться через vk_api библиотеку, если она установлена"""
    try:
        import vk_api
        vk_session = vk_api.VkApi(login=login, password=password)
        vk_session.auth()
        # Копируем cookies из vk_api сессии
        sess = get_session()
        for cookie in vk_session.http.cookies:
            sess.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        _auth_state['remixsid'] = vk_session.http.cookies.get('remixsid', domain='.vk.com')
        _auth_state['remixsid6'] = vk_session.http.cookies.get('remixsid6', domain='.vk.com')
        _auth_state['logged_in'] = True
        _auth_state['last_auth'] = time.time()
        # Получаем vk_id
        user_info = vk_session.method('users.get', {'fields': 'id'})[0]
        _auth_state['vk_id'] = user_info['id']
        _extract_csrf()
        return True
    except Exception as e:
        print(f"[VK Music] vk_api auth failed: {e}")
        return False

def _extract_csrf():
    """Извлекаем CSRF-hash из главной страницы VK"""
    try:
        sess = get_session()
        resp = sess.get(f'https://{VK_DOMAIN}/', timeout=10)
        # Ищем vk.csrf или hash в скриптах
        m = re.search(r'"vk\.csrf"\s*:\s*"([a-f0-9]+)"', resp.text)
        if m:
            _auth_state['csrf_hash'] = m.group(1)
            return True
        # Fallback: ищем в других местах
        m2 = re.search(r'"hash":"([a-f0-9]{32,})"', resp.text)
        if m2:
            _auth_state['csrf_hash'] = m2.group(1)
            return True
    except Exception as e:
        print(f"[VK Music] CSRF extract error: {e}")
    return False

def _check_session_valid():
    """Проверяем, жива ли сессия"""
    if not _auth_state['logged_in']:
        return False
    if time.time() - _auth_state['last_auth'] > 3600:  # 1 час
        return False
    try:
        sess = get_session()
        resp = sess.get(f'https://{VK_DOMAIN}/feed.php', timeout=10, allow_redirects=False)
        if resp.status_code == 200:
            _auth_state['last_auth'] = time.time()
            return True
    except:
        pass
    return False

# ─── PUBLIC AUTH METHODS ───
def auth_with_cookies(remixsid=None, remixsid6=None, vk_id=None):
    """Авторизация через готовые cookies из браузера"""
    sess = get_session()
    if remixsid:
        sess.cookies.set('remixsid', remixsid, domain='.vk.com', path='/')
        _auth_state['remixsid'] = remixsid
    if remixsid6:
        sess.cookies.set('remixsid6', remixsid6, domain='.vk.com', path='/')
        _auth_state['remixsid6'] = remixsid6
    if vk_id:
        sess.cookies.set('remixusid', str(vk_id), domain='.vk.com', path='/')
        _auth_state['vk_id'] = vk_id

    _auth_state['logged_in'] = True
    _auth_state['last_auth'] = time.time()
    _extract_csrf()
    return _check_session_valid()

def auth_with_login_password(login, password):
    """Авторизация через логин/пароль (через vk_api fallback)"""
    return _try_vk_api_auth(login, password)

def get_auth_status():
    return {
        'logged_in': _check_session_valid(),
        'vk_id': _auth_state['vk_id'],
        'last_auth': _auth_state['last_auth'],
    }

# ─── AUDIO SCRAPING ───
def _build_audio_payload(act, **extra):
    """Строим payload для VK audio AJAX"""
    payload = {
        'act': act,
        'al': '1',
        'hash': _auth_state.get('csrf_hash') or '',
    }
    payload.update(extra)
    return payload

def _parse_audio_response(text):
    """Парсим ответ VK audio (формат: <!-- {...} -->)"""
    # VK отвечает в формате: <!-- {...} -->
    text = text.strip()
    if text.startswith('<!--'):
        text = text[4:]
    if text.endswith('-->'):
        text = text[:-3]
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 1:
            return data[1]  # payload обычно во втором элементе
        return data
    except:
        return None

def search_audio(query, count=30):
    """Поиск аудио в VK"""
    if not _check_session_valid():
        return {'error': 'Not authenticated. Provide cookies or login/password.'}

    sess = get_session()
    payload = _build_audio_payload('section', section='search', q=query)

    try:
        resp = sess.post(VK_AUDIO_URL, data=payload, timeout=15)
        data = _parse_audio_response(resp.text)
        if not data:
            return {'error': 'Failed to parse response'}

        # Извлекаем список треков
        tracks = []
        # VK возвращает HTML + данные, парсим из JSON-структуры
        if isinstance(data, list) and len(data) >= 2:
            html_part = data[0] if isinstance(data[0], str) else ''
            json_part = data[1] if len(data) > 1 and isinstance(data[1], list) else []

            # json_part[0] обычно содержит список треков
            if json_part and isinstance(json_part, list):
                track_list = json_part[0] if isinstance(json_part[0], list) else json_part
                for track_data in track_list[:count]:
                    if not isinstance(track_data, list) or len(track_data) < 16:
                        continue
                    # Формат трека VK audio:
                    # [id, owner_id, url, title, artist, duration, ...]
                    track_id = f"{track_data[1]}_{track_data[0]}"
                    title = track_data[3] if len(track_data) > 3 else 'Unknown'
                    artist = track_data[4] if len(track_data) > 4 else 'Unknown'
                    duration = track_data[5] if len(track_data) > 5 else 0

                    tracks.append({
                        'id': track_id,
                        'title': title,
                        'artist': artist,
                        'duration': int(duration) if duration else 0,
                        'duration_formatted': f"{int(duration)//60}:{int(duration)%60:02d}" if duration else '0:00',
                    })

        return {'tracks': tracks, 'query': query}
    except Exception as e:
        return {'error': str(e)}

def get_audio_url(track_id):
    """Получаем прямую HLS-ссылку на аудио"""
    if not _check_session_valid():
        return {'error': 'Not authenticated'}

    sess = get_session()
    parts = track_id.split('_')
    if len(parts) != 2:
        return {'error': 'Invalid track ID format. Expected: owner_id_track_id'}

    owner_id, audio_id = parts
    payload = _build_audio_payload('reload_audio', 
        ids=f"[{audio_id},{owner_id}]"
    )

    try:
        resp = sess.post(VK_AUDIO_URL, data=payload, timeout=15)
        data = _parse_audio_response(resp.text)

        if data and isinstance(data, list) and len(data) > 0:
            track_data = data[0]
            if isinstance(track_data, list) and len(track_data) > 2:
                # URL обычно в третьем элементе
                audio_url = track_data[2] if len(track_data) > 2 else None
                if audio_url and audio_url.startswith('http'):
                    return {
                        'track_id': track_id,
                        'url': audio_url,
                        'expires_in': 3600,  # URL протухает примерно через час
                    }

        return {'error': 'Could not extract audio URL', 'raw': str(data)[:500]}
    except Exception as e:
        return {'error': str(e)}

def get_my_audio(count=50):
    """Получаем аудио из "Моей музыки""""
    if not _check_session_valid():
        return {'error': 'Not authenticated'}

    sess = get_session()
    payload = _build_audio_payload('section', section='all')

    try:
        resp = sess.post(VK_AUDIO_URL, data=payload, timeout=15)
        data = _parse_audio_response(resp.text)

        tracks = []
        if data and isinstance(data, list) and len(data) >= 2:
            json_part = data[1] if len(data) > 1 else []
            if json_part and isinstance(json_part, list):
                track_list = json_part[0] if isinstance(json_part[0], list) else json_part
                for track_data in track_list[:count]:
                    if not isinstance(track_data, list) or len(track_data) < 16:
                        continue
                    track_id = f"{track_data[1]}_{track_data[0]}"
                    title = track_data[3] if len(track_data) > 3 else 'Unknown'
                    artist = track_data[4] if len(track_data) > 4 else 'Unknown'
                    duration = track_data[5] if len(track_data) > 5 else 0

                    tracks.append({
                        'id': track_id,
                        'title': title,
                        'artist': artist,
                        'duration': int(duration) if duration else 0,
                        'duration_formatted': f"{int(duration)//60}:{int(duration)%60:02d}" if duration else '0:00',
                    })

        return {'tracks': tracks}
    except Exception as e:
        return {'error': str(e)}

# ─── HLS PROXY (обход CORS) ───
def proxy_hls_segment(url):
    """Проксируем HLS-сегмент, чтобы обойти CORS в браузере"""
    try:
        sess = get_session()
        resp = sess.get(url, timeout=15, stream=True)
        return Response(
            resp.iter_content(chunk_size=8192),
            content_type=resp.headers.get('Content-Type', 'application/octet-stream'),
            status=resp.status_code
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── FLASK BLUEPRINT ───
music_bp = Blueprint('music', __name__, url_prefix='/music')

@music_bp.route('/')
def music_index():
    """Главная страница музыкального плеера"""
    return render_template_string(MUSIC_HTML)

@music_bp.route('/api/auth/cookies', methods=['POST'])
def api_auth_cookies():
    """Авторизация через cookies из браузера"""
    data = request.json or {}
    remixsid = data.get('remixsid')
    remixsid6 = data.get('remixsid6')
    vk_id = data.get('vk_id')

    if not remixsid and not remixsid6:
        return jsonify({'error': 'No cookies provided. Need remixsid or remixsid6'}), 400

    success = auth_with_cookies(remixsid, remixsid6, vk_id)
    return jsonify({'success': success, 'status': get_auth_status()})

@music_bp.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """Авторизация через логин/пароль"""
    data = request.json or {}
    login = data.get('login')
    password = data.get('password')

    if not login or not password:
        return jsonify({'error': 'Login and password required'}), 400

    success = auth_with_login_password(login, password)
    return jsonify({'success': success, 'status': get_auth_status()})

@music_bp.route('/api/status')
def api_status():
    """Статус авторизации"""
    return jsonify(get_auth_status())

@music_bp.route('/api/search')
def api_search():
    """Поиск аудио"""
    query = request.args.get('q', '').strip()
    count = request.args.get('count', 30, type=int)

    if not query:
        return jsonify({'error': 'Query parameter "q" is required'}), 400

    result = search_audio(query, count)
    return jsonify(result)

@music_bp.route('/api/get_url')
def api_get_url():
    """Получить URL трека"""
    track_id = request.args.get('id', '').strip()
    if not track_id:
        return jsonify({'error': 'Track ID required'}), 400

    result = get_audio_url(track_id)
    return jsonify(result)

@music_bp.route('/api/my_music')
def api_my_music():
    """Моя музыка"""
    count = request.args.get('count', 50, type=int)
    result = get_my_audio(count)
    return jsonify(result)

@music_bp.route('/proxy')
def proxy_audio():
    """Прокси для аудио-потока (обход CORS)"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL required'}), 400
    return proxy_hls_segment(url)

# ─── HTML INTERFACE ───
MUSIC_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>VK Tsuyu Music</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#000;color:#fff;height:100vh;overflow:hidden}
.app{height:100vh;display:flex;flex-direction:column}

/* Header */
.header{height:56px;background:#0d0d0d;display:flex;align-items:center;padding:0 16px;border-bottom:1px solid #1c1c1c;flex-shrink:0}
.header-back{width:40px;height:40px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%;background:rgba(255,255,255,0.08);color:#fff;margin-right:12px;flex-shrink:0}
.header-back:active{background:rgba(255,255,255,0.2)}
.header-title{font-size:18px;font-weight:700;flex:1}
.header-subtitle{font-size:12px;color:#8e8e93}

/* Auth Panel */
.auth-panel{padding:16px;background:#141416;border-bottom:1px solid #1c1c1c}
.auth-panel h3{font-size:14px;color:#8e8e93;margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px}
.input-field{width:100%;padding:12px 14px;border:none;border-radius:12px;background:#1c1c1e;color:#fff;font-size:14px;margin-bottom:10px;outline:none;border:1px solid #2c2c2c}
.input-field:focus{border-color:#555}
.input-field::placeholder{color:#666}
.btn{width:100%;padding:12px;border:none;border-radius:12px;background:#fff;color:#000;font-size:15px;font-weight:600;cursor:pointer;margin-bottom:8px}
.btn:active{opacity:.85;transform:scale(0.98)}
.btn-secondary{background:transparent;color:#fff;border:1px solid #333}
.btn-success{background:#34c759;color:#000}
.status-badge{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:20px;font-size:12px;font-weight:600;margin-top:8px}
.status-badge.online{background:rgba(52,199,89,0.15);color:#34c759}
.status-badge.offline{background:rgba(255,59,48,0.15);color:#ff3b30}

/* Search */
.search-bar{padding:12px 16px;background:#0d0d0d;border-bottom:1px solid #1c1c1c;display:flex;gap:8px}
.search-input{flex:1;padding:10px 14px;border:none;border-radius:12px;background:#1c1c1e;color:#fff;font-size:14px;outline:none;border:1px solid #2c2c2c}
.search-input:focus{border-color:#0a84ff}
.search-btn{width:44px;height:44px;border-radius:12px;background:#0a84ff;color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center}
.search-btn:active{opacity:.8}

/* Tabs */
.tabs{display:flex;gap:4px;padding:8px 16px;overflow-x:auto;background:#0d0d0d;border-bottom:1px solid #1c1c1c}
.tab{white-space:nowrap;padding:6px 14px;border-radius:16px;background:#1c1c1e;color:#8e8e93;font-size:13px;font-weight:500;cursor:pointer;border:1px solid transparent}
.tab.active{background:#2c2c2e;color:#fff;border-color:#3a3a3c}

/* Track List */
.track-list{flex:1;overflow-y:auto;padding:8px 0}
.track-item{display:flex;align-items:center;padding:10px 16px;cursor:pointer;border-bottom:1px solid #111;gap:12px}
.track-item:active{background:#111}
.track-item.playing{background:rgba(10,132,255,0.1)}
.track-num{width:32px;text-align:center;color:#666;font-size:13px;font-weight:600;flex-shrink:0}
.track-info{flex:1;min-width:0}
.track-title{font-size:14px;font-weight:600;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track-artist{font-size:12px;color:#8e8e93;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track-duration{font-size:12px;color:#666;flex-shrink:0}
.track-play-btn{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.1);display:flex;align-items:center;justify-content:center;color:#fff;flex-shrink:0}
.track-play-btn:active{background:rgba(255,255,255,0.2)}

/* Player Bar */
.player-bar{position:fixed;bottom:0;left:0;width:100%;background:#141416;border-top:1px solid #1c1c1c;padding:10px 16px;display:flex;align-items:center;gap:12px;z-index:100;transform:translateY(100%);transition:transform 0.25s cubic-bezier(0.1,0.9,0.2,1)}
.player-bar.active{transform:translateY(0)}
.player-cover{width:44px;height:44px;border-radius:8px;background:#222;display:flex;align-items:center;justify-content:center;color:#666;font-size:18px}
.player-info{flex:1;min-width:0}
.player-title{font-size:13px;font-weight:600;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.player-artist{font-size:11px;color:#8e8e93;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.player-controls{display:flex;align-items:center;gap:12px}
.player-btn{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#fff;background:rgba(255,255,255,0.08)}
.player-btn:active{background:rgba(255,255,255,0.15)}
.player-btn.play{background:#0a84ff;color:#fff}
.player-progress{position:absolute;top:0;left:0;height:2px;background:#0a84ff;width:0%;transition:width 0.1s linear}

/* Loading */
.loader{border:2px solid #333;border-top:2px solid #fff;border-radius:50%;width:16px;height:16px;animation:spin 0.6s linear infinite;display:inline-block}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
.empty-state{text-align:center;padding:60px 20px;color:#666;font-size:14px}
.hidden{display:none!important}
</style>
</head>
<body>
<div class="app">

<div class="header">
<a href="/" class="header-back" title="Назад в VK Tsuyu">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
</a>
<div>
<div class="header-title">VK Music</div>
<div class="header-subtitle" id="authStatusText">Не авторизован</div>
</div>
</div>

<!-- Auth Panel -->
<div class="auth-panel" id="authPanel">
<h3>🔐 Авторизация VK</h3>
<div id="cookieAuth">
<input type="text" class="input-field" id="remixsidInput" placeholder="remixsid из браузера (F12 → Application → Cookies)">
<input type="text" class="input-field" id="remixsid6Input" placeholder="remixsid6 (опционально)">
<input type="text" class="input-field" id="vkIdInput" placeholder="Ваш VK ID (число)">
<button class="btn" onclick="authWithCookies()">Войти через Cookies</button>
</div>
<div style="text-align:center;margin:10px 0;color:#666;font-size:12px">— или —</div>
<div id="loginAuth">
<input type="text" class="input-field" id="loginInput" placeholder="Телефон / Email / Логин">
<input type="password" class="input-field" id="passwordInput" placeholder="Пароль VK">
<button class="btn btn-secondary" onclick="authWithLogin()">Войти через Логин/Пароль</button>
</div>
<div id="authStatus" class="status-badge offline" style="display:none">
<span>●</span> <span id="authStatusLabel">Оффлайн</span>
</div>
</div>

<!-- Search -->
<div class="search-bar">
<input type="text" class="search-input" id="searchInput" placeholder="Поиск треков, исполнителей..." onkeypress="if(event.key==='Enter')searchTracks()">
<button class="search-btn" onclick="searchTracks()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
</button>
</div>

<!-- Tabs -->
<div class="tabs">
<div class="tab active" onclick="switchTab('search')" id="tabSearch">🔍 Поиск</div>
<div class="tab" onclick="switchTab('my')" id="tabMy">🎵 Моя музыка</div>
</div>

<!-- Track List -->
<div class="track-list" id="trackList">
<div class="empty-state">
<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#444" stroke-width="1.5" style="display:block;margin:0 auto 12px"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
Войдите в VK и начните поиск музыки
</div>
</div>

<!-- Player Bar -->
<div class="player-bar" id="playerBar">
<div class="player-progress" id="playerProgress"></div>
<div class="player-cover">🎵</div>
<div class="player-info">
<div class="player-title" id="playerTitle">...</div>
<div class="player-artist" id="playerArtist">...</div>
</div>
<div class="player-controls">
<button class="player-btn" onclick="prevTrack()">⏮</button>
<button class="player-btn play" id="playPauseBtn" onclick="togglePlay()">▶</button>
<button class="player-btn" onclick="nextTrack()">⏭</button>
</div>
</div>

</div>

<script>
let currentTracks = [];
let currentTrackIndex = -1;
let audioPlayer = null;
let isPlaying = false;

// Check auth status on load
(async () => {
    try {
        const res = await fetch('/music/api/status');
        const data = await res.json();
        updateAuthUI(data.logged_in);
    } catch(e) {}
})();

function updateAuthUI(loggedIn) {
    const panel = document.getElementById('authPanel');
    const status = document.getElementById('authStatus');
    const statusLabel = document.getElementById('authStatusLabel');
    const statusText = document.getElementById('authStatusText');

    if (loggedIn) {
        panel.style.display = 'none';
        statusText.textContent = 'Авторизован';
        status.className = 'status-badge online';
        status.style.display = 'inline-flex';
        loadMyMusic();
    } else {
        statusText.textContent = 'Не авторизован';
        status.className = 'status-badge offline';
    }
}

async function authWithCookies() {
    const remixsid = document.getElementById('remixsidInput').value.trim();
    const remixsid6 = document.getElementById('remixsid6Input').value.trim();
    const vkId = document.getElementById('vkIdInput').value.trim();

    if (!remixsid) { alert('Введите remixsid'); return; }

    showLoading();
    try {
        const res = await fetch('/music/api/auth/cookies', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({remixsid, remixsid6, vk_id: vkId})
        });
        const data = await res.json();
        if (data.success) {
            updateAuthUI(true);
        } else {
            alert('Ошибка авторизации. Проверьте cookies.');
        }
    } catch(e) {
        alert('Ошибка сети');
    }
    hideLoading();
}

async function authWithLogin() {
    const login = document.getElementById('loginInput').value.trim();
    const password = document.getElementById('passwordInput').value.trim();

    if (!login || !password) { alert('Введите логин и пароль'); return; }

    showLoading();
    try {
        const res = await fetch('/music/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({login, password})
        });
        const data = await res.json();
        if (data.success) {
            updateAuthUI(true);
        } else {
            alert('Ошибка авторизации: ' + (data.status?.error || 'Неверный логин/пароль'));
        }
    } catch(e) {
        alert('Ошибка сети. Убедитесь, что установлена библиотека vk_api: pip install vk_api');
    }
    hideLoading();
}

async function searchTracks() {
    const query = document.getElementById('searchInput').value.trim();
    if (!query) return;

    showLoading();
    try {
        const res = await fetch(`/music/api/search?q=${encodeURIComponent(query)}&count=30`);
        const data = await res.json();
        if (data.error) {
            showError(data.error);
            return;
        }
        currentTracks = data.tracks || [];
        renderTracks(currentTracks);
        switchTab('search');
    } catch(e) {
        showError('Ошибка поиска');
    }
    hideLoading();
}

async function loadMyMusic() {
    showLoading();
    try {
        const res = await fetch('/music/api/my_music?count=50');
        const data = await res.json();
        if (data.error) {
            showError(data.error);
            return;
        }
        currentTracks = data.tracks || [];
        renderTracks(currentTracks);
    } catch(e) {
        showError('Ошибка загрузки');
    }
    hideLoading();
}

function renderTracks(tracks) {
    const list = document.getElementById('trackList');
    if (!tracks || tracks.length === 0) {
        list.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
        return;
    }

    list.innerHTML = tracks.map((t, i) => `
        <div class="track-item ${i === currentTrackIndex ? 'playing' : ''}" onclick="playTrack(${i})">
            <div class="track-num">${i + 1}</div>
            <div class="track-info">
                <div class="track-title">${escapeHtml(t.title)}</div>
                <div class="track-artist">${escapeHtml(t.artist)}</div>
            </div>
            <div class="track-duration">${t.duration_formatted || '0:00'}</div>
            <div class="track-play-btn">${i === currentTrackIndex && isPlaying ? '⏸' : '▶'}</div>
        </div>
    `).join('');
}

async function playTrack(index) {
    if (index < 0 || index >= currentTracks.length) return;
    currentTrackIndex = index;
    const track = currentTracks[index];

    // Update UI
    document.getElementById('playerTitle').textContent = track.title;
    document.getElementById('playerArtist').textContent = track.artist;
    document.getElementById('playerBar').classList.add('active');

    // Get audio URL
    showLoading();
    try {
        const res = await fetch(`/music/api/get_url?id=${encodeURIComponent(track.id)}`);
        const data = await res.json();
        if (data.error || !data.url) {
            alert('Не удалось получить ссылку на трек');
            hideLoading();
            return;
        }

        // Play through proxy (bypass CORS)
        const proxyUrl = `/music/proxy?url=${encodeURIComponent(data.url)}`;

        if (audioPlayer) {
            audioPlayer.pause();
            audioPlayer.src = '';
        }
        audioPlayer = new Audio(proxyUrl);
        audioPlayer.play();
        isPlaying = true;
        updatePlayButton();

        audioPlayer.ontimeupdate = () => {
            if (audioPlayer.duration) {
                const pct = (audioPlayer.currentTime / audioPlayer.duration) * 100;
                document.getElementById('playerProgress').style.width = pct + '%';
            }
        };

        audioPlayer.onended = () => {
            isPlaying = false;
            updatePlayButton();
            nextTrack();
        };

        renderTracks(currentTracks); // Update play icons
    } catch(e) {
        alert('Ошибка воспроизведения');
    }
    hideLoading();
}

function togglePlay() {
    if (!audioPlayer) return;
    if (isPlaying) {
        audioPlayer.pause();
        isPlaying = false;
    } else {
        audioPlayer.play();
        isPlaying = true;
    }
    updatePlayButton();
    renderTracks(currentTracks);
}

function updatePlayButton() {
    document.getElementById('playPauseBtn').textContent = isPlaying ? '⏸' : '▶';
}

function prevTrack() {
    if (currentTrackIndex > 0) playTrack(currentTrackIndex - 1);
}

function nextTrack() {
    if (currentTrackIndex < currentTracks.length - 1) playTrack(currentTrackIndex + 1);
}

function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab' + (tab === 'search' ? 'Search' : 'My')).classList.add('active');
    if (tab === 'my') loadMyMusic();
}

function escapeHtml(t) {
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
}

function showLoading() {
    document.getElementById('trackList').innerHTML = '<div class="empty-state"><span class="loader"></span> Загрузка...</div>';
}
function hideLoading() {}
function showError(msg) {
    document.getElementById('trackList').innerHTML = `<div class="empty-state">❌ ${escapeHtml(msg)}</div>`;
}
</script>
</body>
</html>
"""
