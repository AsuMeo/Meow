import os
import re
import json
import time
import hashlib
import requests
from urllib.parse import quote, unquote, urlparse, parse_qs
from flask import Blueprint, request, jsonify, Response, render_template_string, session, redirect

VK_DOMAIN = "vk.com"
VK_AUDIO_URL = f"https://{VK_DOMAIN}/al_audio.php"
VK_CLIENT_ID = os.environ.get("VK_CLIENT_ID", "6121396")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def vk_audio_decipher(url_str):
    if not url_str or not isinstance(url_str, str):
        return ""
    if "index.m3u8" in url_str or ".mp3" in url_str:
        return url_str.strip()
    return url_str.replace("?extra=", "").replace("#", "").strip()

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
                'access_token': None,
                'logged_in': False
            }
        return self._sessions[client_key]

    def set_token_auth(self, client_key: str, access_token: str, vk_id=None):
        data = self.get_client_session(client_key)
        data['access_token'] = access_token
        data['vk_id'] = str(vk_id) if vk_id else None
        data['logged_in'] = True
        data['last_auth'] = time.time()
        
        sess = data['http']
        try:
            resp = sess.get(f"https://api.vk.com/method/users.get?access_token={access_token}&v=5.131")
            res_json = resp.json()
            if "response" in res_json and len(res_json["response"]) > 0:
                data['vk_id'] = str(res_json["response"][0]["id"])
                data['user_name'] = f"{res_json['response'][0].get('first_name', '')} {res_json['response'][0].get('last_name', '')}"
                return True
        except Exception:
            pass
        
        return True

    def check_valid(self, client_key: str) -> bool:
        data = self.get_client_session(client_key)
        return bool(data.get('logged_in'))

session_manager = VKSessionManager()

def get_client_id():
    if 'client_key' not in session:
        session['client_key'] = hashlib.md5(f"{time.time()}_{os.urandom(8)}".encode()).hexdigest()
    return session['client_key']

def fetch_vk_api(client_key, method, params):
    c_data = session_manager.get_client_session(client_key)
    token = c_data.get('access_token')
    if not token:
        return None
    
    default_params = {
        'access_token': token,
        'v': '5.131'
    }
    default_params.update(params)
    
    try:
        resp = requests.get(f"https://api.vk.com/method/{method}", params=default_params, timeout=10)
        return resp.json()
    except Exception:
        return None

music_bp = Blueprint('music', __name__, url_prefix='/music')

@music_bp.route('/')
def music_index():
    return render_template_string(MUSIC_HTML)

@music_bp.route('/auth/vk_id')
def auth_vk_id_redirect():
    redirect_uri = request.host_url.rstrip('/') + '/music/auth/callback'
    vk_oauth_url = (
        f"https://oauth.vk.com/authorize?"
        f"client_id={VK_CLIENT_ID}&"
        f"display=page&"
        f"redirect_uri={quote(redirect_uri)}&"
        f"scope=audio,offline&"
        f"response_type=token&"
        f"v=5.131"
    )
    return redirect(vk_oauth_url)

@music_bp.route('/auth/callback')
def auth_callback():
    return render_template_string(OAUTH_CALLBACK_HTML)

@music_bp.route('/api/auth/token', methods=['POST'])
def api_auth_token():
    data = request.json or {}
    token = data.get('access_token')
    user_id = data.get('user_id')

    if not token:
        return jsonify({'error': 'Токен не передан'}), 400

    client_key = get_client_id()
    valid = session_manager.set_token_auth(client_key, token, user_id)
    c_data = session_manager.get_client_session(client_key)
    
    return jsonify({
        'success': valid,
        'status': {
            'logged_in': valid,
            'vk_id': c_data.get('vk_id'),
            'user_name': c_data.get('user_name', 'Пользователь VK')
        }
    })

@music_bp.route('/api/status')
def api_status():
    client_key = get_client_id()
    c_data = session_manager.get_client_session(client_key)
    valid = session_manager.check_valid(client_key)
    return jsonify({
        'logged_in': valid,
        'vk_id': c_data.get('vk_id'),
        'user_name': c_data.get('user_name', '')
    })

@music_bp.route('/api/search')
def api_search():
    client_key = get_client_id()
    query = request.args.get('q', '').strip()
    count = request.args.get('count', 40, type=int)

    if not query:
        return jsonify({'error': 'Запрос не указан'}), 400

    res = fetch_vk_api(client_key, 'audio.search', {'q': query, 'count': count})
    if not res or 'response' not in res:
        return jsonify({'error': 'Ошибка поиска через VK ID'}), 500

    items = res['response'].get('items', [])
    tracks = []
    for t in items:
        tracks.append({
            'id': f"{t.get('owner_id')}_{t.get('id')}",
            'title': t.get('title', 'Без названия'),
            'artist': t.get('artist', 'Неизвестен'),
            'duration': t.get('duration', 0),
            'duration_formatted': f"{t.get('duration', 0) // 60}:{t.get('duration', 0) % 60:02d}",
            'url': t.get('url', ''),
            'cover': t.get('album', {}).get('thumb', {}).get('photo_300', '') if t.get('album') else ''
        })

    return jsonify({'tracks': tracks, 'query': query})

@music_bp.route('/api/my_music')
def api_my_music():
    client_key = get_client_id()
    count = request.args.get('count', 60, type=int)

    res = fetch_vk_api(client_key, 'audio.get', {'count': count})
    if not res or 'response' not in res:
        return jsonify({'error': 'Не удалось получить аудиозаписи'}), 500

    items = res['response'].get('items', [])
    tracks = []
    for t in items:
        tracks.append({
            'id': f"{t.get('owner_id')}_{t.get('id')}",
            'title': t.get('title', 'Без названия'),
            'artist': t.get('artist', 'Неизвестен'),
            'duration': t.get('duration', 0),
            'duration_formatted': f"{t.get('duration', 0) // 60}:{t.get('duration', 0) % 60:02d}",
            'url': t.get('url', ''),
            'cover': t.get('album', {}).get('thumb', {}).get('photo_300', '') if t.get('album') else ''
        })

    return jsonify({'tracks': tracks})

@music_bp.route('/api/recommendations')
def api_recommendations():
    client_key = get_client_id()
    count = request.args.get('count', 40, type=int)

    res = fetch_vk_api(client_key, 'audio.getRecommendations', {'count': count})
    if not res or 'response' not in res:
        return jsonify({'error': 'Не удалось получить рекомендации'}), 500

    items = res['response'].get('items', [])
    tracks = []
    for t in items:
        tracks.append({
            'id': f"{t.get('owner_id')}_{t.get('id')}",
            'title': t.get('title', 'Без названия'),
            'artist': t.get('artist', 'Неизвестен'),
            'duration': t.get('duration', 0),
            'duration_formatted': f"{t.get('duration', 0) // 60}:{t.get('duration', 0) % 60:02d}",
            'url': t.get('url', ''),
            'cover': t.get('album', {}).get('thumb', {}).get('photo_300', '') if t.get('album') else ''
        })

    return jsonify({'tracks': tracks})

@music_bp.route('/proxy')
def proxy_audio():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Отсутствует URL'}), 400

    try:
        req_headers = {k: v for k, v in request.headers if k.lower() in ['range', 'user-agent', 'accept']}
        resp = requests.get(url, headers=req_headers, stream=True, timeout=15)

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

OAUTH_CALLBACK_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Авторизация VK ID...</title></head>
<body style="background:#08080a;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;">
<div style="text-align:center;">
    <h2>Авторизация через VK ID...</h2>
    <p>Пожалуйста, подождите</p>
</div>
<script>
const hash = window.location.hash.substring(1);
const params = new URLSearchParams(hash);
const accessToken = params.get('access_token');
const userId = params.get('user_id');

if (accessToken) {
    fetch('/music/api/auth/token', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ access_token: accessToken, user_id: userId })
    }).then(res => res.json()).then(data => {
        if(data.success) {
            window.location.href = '/music/';
        } else {
            alert('Ошибка авторизации VK ID');
            window.location.href = '/music/';
        }
    }).catch(() => {
        window.location.href = '/music/';
    });
} else {
    window.location.href = '/music/';
}
</script>
</body>
</html>
"""

MUSIC_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>VK Music Engine - VK ID Instant Login</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', Roboto, Helvetica, Arial, sans-serif; background: #08080a; color: #fff; height: 100vh; overflow: hidden; }
.app { height: 100vh; display: flex; flex-direction: column; background: radial-gradient(circle at top right, #1a102f, #08080a 60%); }
.header { height: 60px; background: rgba(18, 18, 22, 0.8); backdrop-filter: blur(20px); display: flex; align-items: center; padding: 0 20px; border-bottom: 1px solid rgba(255,255,255,0.08); flex-shrink:0; justify-content: space-between; }
.header-brand { display: flex; align-items: center; gap: 12px; }
.header-logo { width: 36px; height: 36px; background: #007aff; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; box-shadow: 0 4px 12px rgba(0,122,255,0.3); }
.header-title { font-size: 17px; font-weight: 700; }
.header-subtitle { font-size: 11px; color: #8e8e93; }

.vk-id-banner { padding: 20px; text-align: center; background: rgba(0, 122, 255, 0.1); border-bottom: 1px solid rgba(0, 122, 255, 0.2); }
.vk-id-btn { display: inline-flex; align-items: center; justify-content: center; gap: 10px; width: 100%; max-width: 320px; padding: 14px 20px; background: #007aff; color: #fff; text-decoration: none; font-weight: 700; font-size: 15px; border-radius: 14px; box-shadow: 0 6px 20px rgba(0, 122, 255, 0.4); transition: transform 0.15s; }
.vk-id-btn:active { transform: scale(0.97); }

.search-bar { padding: 12px 16px; display: flex; gap: 10px; background: rgba(0,0,0,0.2); }
.search-input { flex: 1; padding: 12px 16px; border: 1px solid rgba(255,255,255,0.1); border-radius: 14px; background: rgba(255,255,255,0.06); color: #fff; font-size: 14px; outline: none; }
.search-btn { width: 46px; height: 46px; border-radius: 14px; background: #007aff; color: #fff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; }

.tabs { display: flex; gap: 8px; padding: 10px 16px; overflow-x: auto; }
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
.track-duration { font-size: 12px; color: #666; }
.dl-btn { background: none; border: none; color: #8e8e93; cursor: pointer; padding: 6px; font-size: 16px; }

.player-bar { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(20, 20, 26, 0.95); backdrop-filter: blur(25px); border-top: 1px solid rgba(255,255,255,0.1); padding: 12px 20px 20px 20px; z-index: 1000; transform: translateY(100%); transition: transform 0.3s cubic-bezier(0.1, 0.9, 0.2, 1); }
.player-bar.active { transform: translateY(0); }
.progress-container { width: 100%; height: 4px; background: rgba(255,255,255,0.15); border-radius: 2px; cursor: pointer; margin-bottom: 12px; }
.progress-bar { height: 100%; background: #007aff; border-radius: 2px; width: 0%; }
.player-content { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.player-left { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
.player-cover { width: 48px; height: 48px; border-radius: 10px; background: #222; background-size: cover; background-position: center; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 22px; }
.player-details { flex: 1; min-width: 0; }
.player-title { font-size: 14px; font-weight: 700; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.player-artist { font-size: 12px; color: #8e8e93; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.player-controls { display: flex; align-items: center; gap: 14px; }
.p-btn { background: none; border: none; color: #fff; cursor: pointer; font-size: 20px; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.p-btn.play { width: 44px; height: 44px; background: #007aff; font-size: 20px; }

.empty-state { text-align: center; padding: 60px 20px; color: #666; font-size: 14px; }
.loader { border: 2px solid rgba(255,255,255,0.1); border-top: 2px solid #007aff; border-radius: 50%; width: 24px; height: 24px; animation: spin 0.7s linear infinite; display: inline-block; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="app">

<div class="header">
    <div class="header-brand">
        <div class="header-logo">VK</div>
        <div>
            <div class="header-title">VK Music</div>
            <div class="header-subtitle" id="statusSub">Проверка авторизации...</div>
        </div>
    </div>
</div>

<div class="vk-id-banner" id="loginBanner">
    <a href="/music/auth/vk_id" class="vk-id-btn">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M15.07 2H8.93C3.33 2 2 3.33 2 8.93v6.14C2 20.67 3.33 22 8.93 22h6.14c5.6 0 6.93-1.33 6.93-6.93V8.93C22 3.33 20.67 2 15.07 2zm3.12 14.19h-1.39c-.58 0-.76-.46-1.8-1.5-.91-.88-1.31-.99-1.54-.99-.32 0-.41.09-.41.54v1.37c0 .37-.12.58-1.1.58-1.62 0-3.41-.98-4.67-2.8-1.9-2.67-2.42-4.69-2.42-5.1 0-.23.09-.44.53-.44h1.39c.39 0 .54.18.69.6.76 2.2 2.03 4.13 2.56 4.13.2 0 .29-.09.29-.6v-2.3c-.06-1.04-.61-1.13-.61-1.5 0-.18.15-.36.39-.36h2.18c.33 0 .45.18.45.57v3.09c0 .33.15.45.24.45.2 0 .37-.12.74-.49 1.14-1.28 1.95-3.26 1.95-3.26.1-.22.28-.36.67-.36h1.39c.42 0 .52.22.42.52-.17.78-1.83 3.16-1.83 3.16-.15.24-.21.36 0 .63.15.21.67.66 1.01 1.06.63.73 1.11 1.34 1.24 1.76.13.42-.08.64-.5.64z"/></svg>
        Войти через VK ID в 1 клик
    </a>
</div>

<div class="search-bar">
    <input type="text" class="search-input" id="searchInput" placeholder="Поиск музыки VK..." onkeypress="if(event.key==='Enter')searchTracks()">
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
            document.getElementById('loginBanner').style.display = 'none';
            document.getElementById('statusSub').textContent = data.user_name || 'Авторизован';
            loadMyMusic();
        } else {
            document.getElementById('statusSub').textContent = 'Нажмите синюю кнопку для входа';
            document.getElementById('trackList').innerHTML = '<div class="empty-state">Нажмите "Войти через VK ID" выше для моментальной авторизации без паролей и куки</div>';
        }
    } catch(e) {
        document.getElementById('statusSub').textContent = 'Ошибка';
    }
});

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
        list.innerHTML = '<div class="empty-state">Музыка не найдена</div>';
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

    const streamUrl = track.url;
    if(!streamUrl) {
        alert('Ссылка на файл недоступна');
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
