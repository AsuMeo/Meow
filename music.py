import os
import re
import json
import time
import hashlib
import requests
from urllib.parse import quote, unquote, urlparse
from flask import Blueprint, request, jsonify, Response, render_template_string, session

VK_DOMAIN = "vk.com"
VK_AUDIO_URL = f"https://{VK_DOMAIN}/al_audio.php"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def vk_audio_decipher(url_str, vk_id=0):
    if not url_str or not isinstance(url_str, str):
        return ""
    if "index.m3u8" in url_str or ".mp3" in url_str:
        return url_str.strip()
    clean_url = url_str.replace("?extra=", "").replace("#", "")
    return clean_url.strip()

class VKSessionManager:
    def __init__(self):
        self._sessions = {}

    def get_client_session(self, client_key: str) -> dict:
        if client_key not in self._sessions:
            sess = requests.Session()
            sess.headers.update({
                'User-Agent': DEFAULT_USER_AGENT,
                'Accept': '*/*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': f'https://{VK_DOMAIN}/',
                'X-Requested-With': 'XMLHttpRequest',
            })
            self._sessions[client_key] = {
                'http': sess,
                'csrf_hash': None,
                'last_auth': 0,
                'vk_id': None,
                'logged_in': False
            }
        return self._sessions[client_key]

    def set_auth_cookies(self, client_key: str, remixsid=None, remixsid6=None, remixnsid=None, vk_id=None):
        data = self.get_client_session(client_key)
        sess = data['http']
        if remixsid:
            sess.cookies.set('remixsid', remixsid, domain='.vk.com', path='/')
        if remixsid6:
            sess.cookies.set('remixsid6', remixsid6, domain='.vk.com', path='/')
        if remixnsid:
            sess.cookies.set('remixnsid', remixnsid, domain='.vk.com', path='/')
        if vk_id:
            sess.cookies.set('remixusid', str(vk_id), domain='.vk.com', path='/')
            data['vk_id'] = str(vk_id)

        data['logged_in'] = True
        data['last_auth'] = time.time()
        self.extract_csrf(client_key)
        return self.check_valid(client_key)

    def extract_csrf(self, client_key: str):
        data = self.get_client_session(client_key)
        sess = data['http']
        try:
            resp = sess.get(f'https://{VK_DOMAIN}/', timeout=10)
            m = re.search(r'"vk\.csrf"\s*:\s*"([a-f0-9]+)"', resp.text)
            if m:
                data['csrf_hash'] = m.group(1)
                return True
            m2 = re.search(r'"hash":"([a-f0-9]{32,})"', resp.text)
            if m2:
                data['csrf_hash'] = m2.group(1)
                return True
        except Exception:
            pass
        return False

    def check_valid(self, client_key: str) -> bool:
        data = self.get_client_session(client_key)
        if not data['logged_in']:
            return False
        if time.time() - data['last_auth'] > 3600:
            try:
                resp = data['http'].get(f'https://{VK_DOMAIN}/feed.php', timeout=8, allow_redirects=False)
                if resp.status_code == 200:
                    data['last_auth'] = time.time()
                    return True
                else:
                    data['logged_in'] = False
                    return False
            except Exception:
                return False
        return True

session_manager = VKSessionManager()

def get_client_id():
    if 'client_key' not in session:
        session['client_key'] = hashlib.md5(f"{time.time()}_{os.urandom(8)}".encode()).hexdigest()
    return session['client_key']

def parse_vk_json(text):
    text = text.strip()
    if text.startswith('<!--'):
        text = text[4:]
    if text.endswith('-->'):
        text = text[:-3]
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 1:
            return data[1]
        return data
    except Exception:
        return None

def fetch_vk_audio_section(client_key, act='section', **params):
    c_data = session_manager.get_client_session(client_key)
    sess = c_data['http']
    payload = {
        'act': act,
        'al': '1',
        'hash': c_data.get('csrf_hash') or '',
    }
    payload.update(params)
    resp = sess.post(VK_AUDIO_URL, data=payload, timeout=12)
    return parse_vk_json(resp.text)

def parse_track_list(raw_data, limit=50):
    tracks = []
    if not raw_data or not isinstance(raw_data, list):
        return tracks

    target_list = []
    for item in raw_data:
        if isinstance(item, list) and len(item) > 0:
            if isinstance(item[0], list):
                target_list = item[0]
                break
            elif len(item) >= 10:
                target_list = raw_data
                break

    for t in target_list:
        if not isinstance(t, list) or len(t) < 8:
            continue
        try:
            track_id = f"{t[1]}_{t[0]}"
            url = vk_audio_decipher(t[2] if len(t) > 2 and isinstance(t[2], str) else "")
            title = str(t[3]) if len(t) > 3 else "Неизвестный трек"
            artist = str(t[4]) if len(t) > 4 else "Неизвестный исполнитель"
            duration = int(t[5]) if len(t) > 5 and str(t[5]).isdigit() else 0

            cover = ""
            if len(t) > 14 and isinstance(t[14], str) and t[14].startswith("http"):
                cover = t[14]
            elif len(t) > 8 and isinstance(t[8], str) and t[8].startswith("http"):
                cover = t[8]

            tracks.append({
                'id': track_id,
                'title': title,
                'artist': artist,
                'duration': duration,
                'duration_formatted': f"{duration // 60}:{duration % 60:02d}",
                'url': url,
                'cover': cover
            })
            if len(tracks) >= limit:
                break
        except Exception:
            continue

    return tracks

music_bp = Blueprint('music', __name__, url_prefix='/music')

@music_bp.route('/')
def music_index():
    return render_template_string(MUSIC_HTML)

@music_bp.route('/api/auth/cookies', methods=['POST'])
def api_auth_cookies():
    data = request.json or {}
    remixsid = data.get('remixsid')
    remixsid6 = data.get('remixsid6')
    remixnsid = data.get('remixnsid')
    vk_id = data.get('vk_id')

    if not remixsid and not remixsid6 and not remixnsid:
        return jsonify({'error': 'Укажите хотя бы один cookie'}), 400

    client_key = get_client_id()
    valid = session_manager.set_auth_cookies(client_key, remixsid, remixsid6, remixnsid, vk_id)
    return jsonify({
        'success': valid,
        'status': {
            'logged_in': valid,
            'vk_id': session_manager.get_client_session(client_key).get('vk_id')
        }
    })

@music_bp.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    data = request.json or {}
    login = data.get('login')
    password = data.get('password')

    if not login or not password:
        return jsonify({'error': 'Логин и пароль обязательны'}), 400

    client_key = get_client_id()
    try:
        import vk_api
        vk_sess = vk_api.VkApi(login=login, password=password)
        vk_sess.auth()
        c_data = session_manager.get_client_session(client_key)
        sess = c_data['http']
        for c in vk_sess.http.cookies:
            sess.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
        c_data['logged_in'] = True
        c_data['last_auth'] = time.time()
        user_info = vk_sess.method('users.get', {'fields': 'id'})[0]
        c_data['vk_id'] = user_info['id']
        session_manager.extract_csrf(client_key)
        return jsonify({'success': True, 'status': {'logged_in': True, 'vk_id': user_info['id']}})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@music_bp.route('/api/status')
def api_status():
    client_key = get_client_id()
    c_data = session_manager.get_client_session(client_key)
    valid = session_manager.check_valid(client_key)
    return jsonify({
        'logged_in': valid,
        'vk_id': c_data.get('vk_id'),
        'last_auth': c_data.get('last_auth')
    })

@music_bp.route('/api/search')
def api_search():
    client_key = get_client_id()
    query = request.args.get('q', '').strip()
    count = request.args.get('count', 40, type=int)

    if not query:
        return jsonify({'error': 'Параметр "q" обязателен'}), 400

    try:
        raw = fetch_vk_audio_section(client_key, act='section', section='search', q=query)
        tracks = parse_track_list(raw, limit=count)
        return jsonify({'tracks': tracks, 'query': query})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@music_bp.route('/api/my_music')
def api_my_music():
    client_key = get_client_id()
    count = request.args.get('count', 60, type=int)
    try:
        raw = fetch_vk_audio_section(client_key, act='section', section='all')
        tracks = parse_track_list(raw, limit=count)
        return jsonify({'tracks': tracks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@music_bp.route('/api/recommendations')
def api_recommendations():
    client_key = get_client_id()
    count = request.args.get('count', 40, type=int)
    try:
        raw = fetch_vk_audio_section(client_key, act='section', section='recoms')
        tracks = parse_track_list(raw, limit=count)
        return jsonify({'tracks': tracks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@music_bp.route('/api/get_url')
def api_get_url():
    client_key = get_client_id()
    track_id = request.args.get('id', '').strip()
    if not track_id or '_' not in track_id:
        return jsonify({'error': 'Некорректный ID трека'}), 400

    owner_id, audio_id = track_id.split('_', 1)
    try:
        raw = fetch_vk_audio_section(client_key, act='reload_audio', ids=f"[{audio_id},{owner_id}]")
        if raw and isinstance(raw, list) and len(raw) > 0:
            track_data = raw[0]
            if isinstance(track_data, list) and len(track_data) > 2:
                url = vk_audio_decipher(track_data[2])
                if url:
                    return jsonify({'track_id': track_id, 'url': url})
        return jsonify({'error': 'Не удалось извлечь URL'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@music_bp.route('/proxy')
def proxy_audio():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Отсутствует URL'}), 400

    try:
        client_key = get_client_id()
        c_data = session_manager.get_client_session(client_key)
        sess = c_data['http']

        req_headers = {k: v for k, v in request.headers if k.lower() in ['range', 'user-agent', 'accept']}
        resp = sess.get(url, headers=req_headers, stream=True, timeout=15)

        def generate():
            for chunk in resp.iter_content(chunk_size=32768):
                if chunk:
                    yield chunk

        headers = {
            'Content-Type': resp.headers.get('Content-Type', 'audio/mpeg'),
            'Accept-Ranges': resp.headers.get('Accept-Ranges', 'bytes'),
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'public, max-age=3600'
        }
        if 'Content-Range' in resp.headers:
            headers['Content-Range'] = resp.headers['Content-Range']
        if 'Content-Length' in resp.headers:
            headers['Content-Length'] = resp.headers['Content-Length']

        return Response(generate(), status=resp.status_code, headers=headers)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

MUSIC_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>VK Music Engine</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', Roboto, Helvetica, Arial, sans-serif; background: #08080a; color: #fff; height: 100vh; overflow: hidden; }
.app { height: 100vh; display: flex; flex-direction: column; background: radial-gradient(circle at top right, #1a102f, #08080a 60%); }
.header { height: 60px; background: rgba(18, 18, 22, 0.8); backdrop-filter: blur(20px); display: flex; align-items: center; padding: 0 20px; border-bottom: 1px solid rgba(255,255,255,0.08); flex-shrink:0; justify-content: space-between; }
.header-brand { display: flex; align-items: center; gap: 12px; }
.header-logo { width: 34px; height: 34px; background: linear-gradient(135deg, #007aff, #5856d6); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; box-shadow: 0 4px 12px rgba(0,122,255,0.3); }
.header-title { font-size: 17px; font-weight: 700; letter-spacing: -0.3px; }
.header-subtitle { font-size: 11px; color: #8e8e93; }
.auth-panel { padding: 18px; background: rgba(22, 22, 28, 0.95); border-bottom: 1px solid rgba(255,255,255,0.08); }
.auth-title { font-size: 13px; color: #8e8e93; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 12px; }
.input-field { width: 100%; padding: 12px 14px; border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; background: rgba(0,0,0,0.4); color: #fff; font-size: 14px; margin-bottom: 10px; outline: none; transition: all 0.2s; }
.input-field:focus { border-color: #007aff; background: rgba(0,0,0,0.6); }
.btn { width: 100%; padding: 12px; border: none; border-radius: 12px; background: #007aff; color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; transition: transform 0.1s, background 0.2s; }
.btn:active { transform: scale(0.98); opacity: 0.9; }
.btn-secondary { background: rgba(255,255,255,0.1); color: #fff; margin-top: 6px; }
.search-bar { padding: 12px 16px; display: flex; gap: 10px; background: rgba(0,0,0,0.2); }
.search-input { flex: 1; padding: 12px 16px; border: 1px solid rgba(255,255,255,0.1); border-radius: 14px; background: rgba(255,255,255,0.06); color: #fff; font-size: 14px; outline: none; }
.search-btn { width: 46px; height: 46px; border-radius: 14px; background: linear-gradient(135deg, #007aff, #0051a8); color: #fff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.tabs { display: flex; gap: 8px; padding: 10px 16px; overflow-x: auto; scrollbar-width: none; }
.tab { padding: 8px 16px; border-radius: 20px; background: rgba(255,255,255,0.06); color: #8e8e93; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; transition: all 0.2s; border: 1px solid transparent; }
.tab.active { background: rgba(255,255,255,0.18); color: #fff; border-color: rgba(255,255,255,0.2); }
.track-list { flex: 1; overflow-y: auto; padding: 8px 16px 120px 16px; }
.track-item { display: flex; align-items: center; padding: 10px 12px; border-radius: 14px; cursor: pointer; margin-bottom: 6px; background: rgba(255,255,255,0.02); transition: background 0.15s; gap: 12px; border: 1px solid rgba(255,255,255,0.03); }
.track-item:hover, .track-item:active { background: rgba(255,255,255,0.08); }
.track-item.playing { background: rgba(0, 122, 255, 0.15); border-color: rgba(0, 122, 255, 0.4); }
.track-cover { width: 46px; height: 46px; border-radius: 10px; background: rgba(255,255,255,0.1); display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; background-size: cover; background-position: center; }
.track-info { flex: 1; min-width: 0; }
.track-title { font-size: 14px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.track-artist { font-size: 12px; color: #8e8e93; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.track-meta { display: flex; align-items: center; gap: 8px; }
.track-duration { font-size: 12px; color: #666; font-variant-numeric: tabular-nums; }
.dl-btn { background: none; border: none; color: #8e8e93; cursor: pointer; padding: 6px; font-size: 16px; }
.dl-btn:hover { color: #fff; }
.player-bar { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(20, 20, 26, 0.95); backdrop-filter: blur(25px); border-top: 1px solid rgba(255,255,255,0.1); padding: 12px 20px 20px 20px; z-index: 1000; transform: translateY(100%); transition: transform 0.3s cubic-bezier(0.1, 0.9, 0.2, 1); box-shadow: 0 -10px 30px rgba(0,0,0,0.5); }
.player-bar.active { transform: translateY(0); }
.progress-container { width: 100%; height: 4px; background: rgba(255,255,255,0.15); border-radius: 2px; cursor: pointer; margin-bottom: 12px; position: relative; }
.progress-bar { height: 100%; background: linear-gradient(90deg, #007aff, #5856d6); border-radius: 2px; width: 0%; position: relative; }
.player-content { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.player-left { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
.player-cover { width: 48px; height: 48px; border-radius: 10px; background: #222; background-size: cover; background-position: center; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 22px; }
.player-details { flex: 1; min-width: 0; }
.player-title { font-size: 14px; font-weight: 700; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.player-artist { font-size: 12px; color: #8e8e93; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.player-controls { display: flex; align-items: center; gap: 14px; }
.p-btn { background: none; border: none; color: #fff; cursor: pointer; font-size: 20px; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; transition: background 0.2s; }
.p-btn:active { background: rgba(255,255,255,0.15); }
.p-btn.play { width: 44px; height: 44px; background: #007aff; font-size: 20px; box-shadow: 0 4px 14px rgba(0,122,255,0.4); }
.empty-state { text-align: center; padding: 60px 20px; color: #666; font-size: 14px; }
.loader { border: 2px solid rgba(255,255,255,0.1); border-top: 2px solid #007aff; border-radius: 50%; width: 24px; height: 24px; animation: spin 0.7s linear infinite; display: inline-block; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="app">

<div class="header">
    <div class="header-brand">
        <div class="header-logo">🎵</div>
        <div>
            <div class="header-title">VK Music Engine</div>
            <div class="header-subtitle" id="statusSub">Проверка авторизации...</div>
        </div>
    </div>
</div>

<div class="auth-panel" id="authPanel">
    <div class="auth-title">🔑 Авторизация в VK</div>
    <input type="text" class="input-field" id="remixsidInput" placeholder="remixsid cookie из браузера">
    <input type="text" class="input-field" id="remixsid6Input" placeholder="remixsid6 cookie (опционально)">
    <input type="text" class="input-field" id="vkIdInput" placeholder="Ваш VK ID">
    <button class="btn" onclick="authWithCookies()">Войти по Cookie</button>
    <div style="text-align:center; margin: 10px 0; font-size: 11px; color: #666;">— ИЛИ —</div>
    <input type="text" class="input-field" id="loginInput" placeholder="Телефон или Email">
    <input type="password" class="input-field" id="passwordInput" placeholder="Пароль VK">
    <button class="btn btn-secondary" onclick="authWithLogin()">Войти с логином и паролем</button>
</div>

<div class="search-bar">
    <input type="text" class="search-input" id="searchInput" placeholder="Поиск исполнителя или трека..." onkeypress="if(event.key==='Enter')searchTracks()">
    <button class="search-btn" onclick="searchTracks()">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    </button>
</div>

<div class="tabs">
    <div class="tab active" onclick="switchTab('my')" id="tabMy">🎵 Моя Музыка</div>
    <div class="tab" onclick="switchTab('recoms')" id="tabRecoms">✨ Рекомендации</div>
    <div class="tab" onclick="switchTab('search')" id="tabSearch">🔍 Поиск</div>
</div>

<div class="track-list" id="trackList">
    <div class="empty-state"><span class="loader"></span></div>
</div>

<div class="player-bar" id="playerBar">
    <div class="progress-container" onclick="seekTrack(event)">
        <div class="progress-bar" id="progressBar"></div>
    </div>
    <div class="player-content">
        <div class="player-left">
            <div class="player-cover" id="playerCover">🎵</div>
            <div class="player-details">
                <div class="player-title" id="playerTitle">Трек не выбран</div>
                <div class="player-artist" id="playerArtist">...</div>
            </div>
        </div>
        <div class="player-controls">
            <button class="p-btn" onclick="prevTrack()">⏮</button>
            <button class="p-btn play" id="playBtn" onclick="togglePlay()">▶</button>
            <button class="p-btn" onclick="nextTrack()">⏭</button>
        </div>
    </div>
</div>

</div>

<script>
let currentTracks = [];
let currentIndex = -1;
let hlsPlayer = null;
let audioEl = new Audio();
let isPlaying = false;

window.addEventListener('DOMContentLoaded', async () => {
    try {
        const res = await fetch('/music/api/status');
        const data = await res.json();
        if (data.logged_in) {
            document.getElementById('authPanel').style.display = 'none';
            document.getElementById('statusSub').textContent = 'Авторизован';
            loadMyMusic();
        } else {
            document.getElementById('statusSub').textContent = 'Требуется вход';
            document.getElementById('trackList').innerHTML = '<div class="empty-state">Авторизуйтесь выше для доступа к трекам</div>';
        }
    } catch(e) {
        document.getElementById('statusSub').textContent = 'Ошибка подключения';
    }
});

async function authWithCookies() {
    const remixsid = document.getElementById('remixsidInput').value.trim();
    const remixsid6 = document.getElementById('remixsid6Input').value.trim();
    const vk_id = document.getElementById('vkIdInput').value.trim();

    if(!remixsid) { alert('Укажите remixsid!'); return; }

    const res = await fetch('/music/api/auth/cookies', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ remixsid, remixsid6, vk_id })
    });
    const data = await res.json();
    if(data.success) {
        document.getElementById('authPanel').style.display = 'none';
        document.getElementById('statusSub').textContent = 'Авторизован';
        loadMyMusic();
    } else {
        alert('Ошибка авторизации по cookie');
    }
}

async function authWithLogin() {
    const login = document.getElementById('loginInput').value.trim();
    const password = document.getElementById('passwordInput').value.trim();

    if(!login || !password) { alert('Заполните логин и пароль'); return; }

    const res = await fetch('/music/api/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ login, password })
    });
    const data = await res.json();
    if(data.success) {
        document.getElementById('authPanel').style.display = 'none';
        document.getElementById('statusSub').textContent = 'Авторизован';
        loadMyMusic();
    } else {
        alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
    }
}

async function loadMyMusic() {
    showLoader();
    const res = await fetch('/music/api/my_music?count=60');
    const data = await res.json();
    currentTracks = data.tracks || [];
    renderTracks();
}

async function loadRecommendations() {
    showLoader();
    const res = await fetch('/music/api/recommendations?count=50');
    const data = await res.json();
    currentTracks = data.tracks || [];
    renderTracks();
}

async function searchTracks() {
    const q = document.getElementById('searchInput').value.trim();
    if(!q) return;
    showLoader();
    switchTab('search');
    const res = await fetch(`/music/api/search?q=${encodeURIComponent(q)}&count=50`);
    const data = await res.json();
    currentTracks = data.tracks || [];
    renderTracks();
}

function renderTracks() {
    const list = document.getElementById('trackList');
    if(!currentTracks || currentTracks.length === 0) {
        list.innerHTML = '<div class="empty-state">Нет аудиозаписей</div>';
        return;
    }

    list.innerHTML = currentTracks.map((t, idx) => `
        <div class="track-item ${idx === currentIndex ? 'playing' : ''}" onclick="playTrack(${idx})">
            <div class="track-cover" style="${t.cover ? `background-image:url('${t.cover}')` : ''}">
                ${!t.cover ? '🎵' : ''}
            </div>
            <div class="track-info">
                <div class="track-title">${escapeHtml(t.title)}</div>
                <div class="track-artist">${escapeHtml(t.artist)}</div>
            </div>
            <div class="track-meta">
                <span class="track-duration">${t.duration_formatted}</span>
                <button class="dl-btn" title="Скачать" onclick="downloadTrack(event, ${idx})">⬇</button>
            </div>
        </div>
    `).join('');
}

async function playTrack(idx) {
    if(idx < 0 || idx >= currentTracks.length) return;
    currentIndex = idx;
    const track = currentTracks[idx];

    document.getElementById('playerTitle').textContent = track.title;
    document.getElementById('playerArtist').textContent = track.artist;
    const coverEl = document.getElementById('playerCover');
    if(track.cover) {
        coverEl.style.backgroundImage = `url('${track.cover}')`;
        coverEl.textContent = '';
    } else {
        coverEl.style.backgroundImage = 'none';
        coverEl.textContent = '🎵';
    }
    document.getElementById('playerBar').classList.add('active');

    let streamUrl = track.url;
    if(!streamUrl) {
        const res = await fetch(`/music/api/get_url?id=${encodeURIComponent(track.id)}`);
        const data = await res.json();
        streamUrl = data.url;
    }

    if(!streamUrl) {
        alert('Не удалось воспроизвести данный трек');
        return;
    }

    const proxyUrl = `/music/proxy?url=${encodeURIComponent(streamUrl)}`;

    if(hlsPlayer) {
        hlsPlayer.destroy();
        hlsPlayer = null;
    }

    if(streamUrl.includes('.m3u8') && Hls.isSupported()) {
        hlsPlayer = new Hls();
        hlsPlayer.loadSource(proxyUrl);
        hlsPlayer.attachMedia(audioEl);
        hlsPlayer.on(Hls.Events.MANIFEST_PARSED, () => {
            audioEl.play();
            isPlaying = true;
            updatePlayBtn();
        });
    } else {
        audioEl.src = proxyUrl;
        audioEl.play();
        isPlaying = true;
        updatePlayBtn();
    }

    renderTracks();
}

audioEl.ontimeupdate = () => {
    if(audioEl.duration) {
        const pct = (audioEl.currentTime / audioEl.duration) * 100;
        document.getElementById('progressBar').style.width = pct + '%';
    }
};

audioEl.onended = () => {
    nextTrack();
};

function togglePlay() {
    if(!audioEl.src && !hlsPlayer) return;
    if(isPlaying) {
        audioEl.pause();
        isPlaying = false;
    } else {
        audioEl.play();
        isPlaying = true;
    }
    updatePlayBtn();
}

function updatePlayBtn() {
    document.getElementById('playBtn').textContent = isPlaying ? '⏸' : '▶';
}

function prevTrack() {
    if(currentIndex > 0) playTrack(currentIndex - 1);
}

function nextTrack() {
    if(currentIndex < currentTracks.length - 1) playTrack(currentIndex + 1);
}

function seekTrack(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    if(audioEl.duration) {
        audioEl.currentTime = pos * audioEl.duration;
    }
}

function downloadTrack(e, idx) {
    e.stopPropagation();
    const t = currentTracks[idx];
    if(!t || !t.url) return;
    const a = document.createElement('a');
    a.href = `/music/proxy?url=${encodeURIComponent(t.url)}`;
    a.download = `${t.artist} - ${t.title}.mp3`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    if(tab === 'my') {
        document.getElementById('tabMy').classList.add('active');
        loadMyMusic();
    } else if(tab === 'recoms') {
        document.getElementById('tabRecoms').classList.add('active');
        loadRecommendations();
    } else {
        document.getElementById('tabSearch').classList.add('active');
    }
}

function showLoader() {
    document.getElementById('trackList').innerHTML = '<div class="empty-state"><span class="loader"></span></div>';
}

function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
</script>
</body>
</html>
"""
