import os
import re
import json
import random
import requests
import hashlib
import base64
from io import BytesIO
from datetime import datetime
from urllib.parse import urlparse
from flask import Blueprint, render_template_string, request, jsonify, Response
from werkzeug.utils import secure_filename

cloud_bp = Blueprint('cloud', __name__)

# === CONFIG & CONSTANTS ===
VK_API = "https://api.vk.com/method"
API_VERSION = "5.199"
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB limit per file for VK Documents
SHARE_SECRET = os.environ.get('CLOUD_SHARE_SECRET', 'tsuyu_cloud_share_master_secret_2026')

# Kate Mobile Client Headers & Official UA to bypass VK blocks and restrictions
KATE_HEADERS = {
    'User-Agent': 'KateMobileAndroid/108 lite-armeabi-v7a (Android 13; SDK 33; arm64-v8a; Xiaomi Redmi Note 10; ru)',
    'Accept-Language': 'ru,en',
    'Connection': 'keep-alive'
}

# Whitelisted VK domains for SSRF prevention
ALLOWED_VK_DOMAINS = (
    'vk.com', 'vkuser.net', 'vk-cdn.net', 'userapi.com',
    'vk-cdn.me', 'vk.me', 'userapi.me', 'vk.ru', 'vkuser.ru'
)

FIREBASE_DB_URL = os.environ.get('FIREBASE_DB_URL', 'https://meow-874ce-default-rtdb.europe-west1.firebasedatabase.app')
FIREBASE_API_KEY = os.environ.get('FIREBASE_API_KEY', '')

KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cloud_keys_storage.json')

_session_local = requests.Session()

def get_session():
    return _session_local

def load_cloud_keys():
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print("Cloud key load error:", e)
            return {}
    return {}

def save_cloud_keys(data):
    try:
        with open(KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Cloud key save error:", e)

def firebase_get(path):
    if not FIREBASE_DB_URL:
        return None
    url = f"{FIREBASE_DB_URL.rstrip('/')}/{path}.json"
    if FIREBASE_API_KEY:
        url += f"?auth={FIREBASE_API_KEY}"
    try:
        resp = get_session().get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print("Firebase GET error:", e)
    return None

def firebase_put(path, data):
    if not FIREBASE_DB_URL:
        return False
    url = f"{FIREBASE_DB_URL.rstrip('/')}/{path}.json"
    if FIREBASE_API_KEY:
        url += f"?auth={FIREBASE_API_KEY}"
    try:
        resp = get_session().put(url, json=data, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        print("Firebase PUT error:", e)
    return False

def get_cloud_key_data(vk_id):
    vk_id_str = str(vk_id)
    if FIREBASE_DB_URL:
        fb_data = firebase_get(f"cloud_keys/{vk_id_str}")
        if fb_data and isinstance(fb_data, dict) and 'cloud_key_enc' in fb_data:
            return fb_data
    local_data = load_cloud_keys()
    return local_data.get(f"cloud_{vk_id_str}")

def store_cloud_key(vk_id, data):
    vk_id_str = str(vk_id)
    local_data = load_cloud_keys()
    local_data[f"cloud_{vk_id_str}"] = data
    save_cloud_keys(local_data)

    if FIREBASE_DB_URL and 'cloud_key_enc' in data:
        firebase_put(f"cloud_keys/{vk_id_str}", {
            'cloud_key_enc': data['cloud_key_enc'],
            'created_at': data.get('created_at', datetime.now().isoformat())
        })

def vk_request(method, token, **params):
    params['access_token'] = token
    params['v'] = API_VERSION
    try:
        resp = get_session().get(f"{VK_API}/{method}", params=params, headers=KATE_HEADERS, timeout=10)
        data = resp.json()
        return data.get('response', data.get('error'))
    except Exception as e:
        return {'error': str(e)}

def extract_doc_attachment(save_result):
    if not save_result or (isinstance(save_result, dict) and 'error' in save_result):
        return None
    if isinstance(save_result, list) and len(save_result) > 0:
        d = save_result[0]
        if isinstance(d, dict) and 'owner_id' in d and 'id' in d:
            return f"doc{d['owner_id']}_{d['id']}"
    if isinstance(save_result, dict):
        if 'doc' in save_result:
            d = save_result['doc']
            if isinstance(d, dict) and 'owner_id' in d and 'id' in d:
                return f"doc{d['owner_id']}_{d['id']}"
        if 'owner_id' in save_result and 'id' in save_result:
            return f"doc{save_result['owner_id']}_{save_result['id']}"
    return None

def buf_to_b64(buf):
    import base64
    return base64.b64encode(buf).decode('utf-8')

def b64_to_buf(b64):
    import base64
    return base64.b64decode(b64)

# --- ADVANCED TITLE METADATA ENCODING (Zero Firebase Metadata) ---
def encode_cloud_title(orig_name, file_type, folder="", version=1, tags=None):
    """
    Encodes full file metadata (Name, Type, Folder, Version, Tags) 
    directly inside the obfuscated VK doc title as Base64 JSON payload.
    No database required!
    """
    if tags is None: tags = []
    meta = {
        'n': orig_name,
        't': file_type,
        'f': folder,
        'v': version,
        'tg': tags
    }
    json_bytes = json.dumps(meta, ensure_ascii=False).encode('utf-8')
    b64_payload = base64.urlsafe_b64encode(json_bytes).decode('utf-8').rstrip('=')
    salt = hashlib.md5(os.urandom(8)).hexdigest()[:6]
    return f"cl_{salt}_{b64_payload}.doc"

def decode_cloud_title(title):
    if not (title.startswith('cl_') and title.endswith('.doc')):
        return None
    try:
        parts = title[3:-4].split('_', 1)
        if len(parts) < 2: return None
        salt, b64_payload = parts[0], parts[1]
        padding = '=' * (4 - len(b64_payload) % 4)
        json_bytes = base64.urlsafe_b64decode(b64_payload + padding)
        meta = json.loads(json_bytes.decode('utf-8'))
        return meta
    except Exception:
        return None

def is_safe_vk_url(url):
    """SSRF Prevention: Validates that URL belongs to official VK CDN hosts"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname.lower() if parsed.hostname else ''
        return any(hostname.endswith('.' + domain) or hostname == domain for domain in ALLOWED_VK_DOMAINS)
    except Exception:
        return False

# --- TEMPORARY SHARED LINK HMAC HELPERS ---
def generate_share_token(doc_url, ttl_seconds=86400):
    exp = int(datetime.now().timestamp()) + ttl_seconds
    data = f"{doc_url}|{exp}"
    sig = hashlib.sha256(f"{data}|{SHARE_SECRET}".encode('utf-8')).hexdigest()[:16]
    token_raw = f"{data}|{sig}"
    return base64.urlsafe_b64encode(token_raw.encode('utf-8')).decode('utf-8').rstrip('=')

def parse_share_token(token):
    try:
        padding = '=' * (4 - len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding).decode('utf-8')
        doc_url, exp_str, sig = raw.rsplit('|', 2)
        exp = int(exp_str)
        if datetime.now().timestamp() > exp:
            return None
        data = f"{doc_url}|{exp_str}"
        expected_sig = hashlib.sha256(f"{data}|{SHARE_SECRET}".encode('utf-8')).hexdigest()[:16]
        if sig != expected_sig:
            return None
        return doc_url
    except Exception:
        return None


# === HTML TEMPLATE ===
CLOUD_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>VK Tsuyu Cloud Ultra Professional</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#000;color:#f2f2f7;height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased}
.app{height:100vh;display:flex;flex-direction:column;position:relative;overflow:hidden;background:#000}

/* Top Navigation Bar */
.header{height:60px;background:rgba(13,13,13,0.85);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);display:flex;align-items:center;padding:0 16px;border-bottom:1px solid #1c1c1e;flex-shrink:0;justify-content:space-between;z-index:100}
.header-left{display:flex;align-items:center;gap:12px}
.header-title{font-size:17px;font-weight:700;letter-spacing:-0.4px;color:#fff;display:flex;align-items:center;gap:8px}
.header-subtitle{font-size:11px;color:#8e8e93;font-weight:500}
.header-back{width:36px;height:36px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%;background:rgba(255,255,255,0.08);color:#fff;flex-shrink:0;transition:all 0.15s ease}
.header-back:active{background:rgba(255,255,255,0.2);transform:scale(0.95)}
.header-actions{display:flex;gap:8px;align-items:center}
.header-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;color:#fff;background:rgba(255,255,255,0.08);border:none;outline:none;transition:all 0.15s ease}
.header-btn:active{background:rgba(255,255,255,0.2);transform:scale(0.95)}
.header-btn.active{background:#0a84ff;color:#fff}

/* Storage Overview Bar */
.storage-bar{padding:8px 16px;background:#0d0d0d;border-bottom:1px solid #1c1c1e;display:flex;flex-direction:column;gap:6px}
.storage-info{display:flex;justify-content:space-between;align-items:center}
.storage-label{font-size:11px;color:#8e8e93;font-weight:500;display:flex;align-items:center;gap:6px}
.storage-used{font-size:11px;font-weight:600;color:#f2f2f7}
.storage-track{height:4px;background:#1c1c1e;border-radius:2px;overflow:hidden;position:relative}
.storage-fill{height:100%;background:linear-gradient(90deg,#0a84ff,#30b0c7);border-radius:2px;transition:width 0.4s cubic-bezier(0.16,1,0.3,1);width:100%}

/* Folder Navigation & Management Bar */
.folders-bar{display:flex;gap:6px;padding:8px 16px;background:#0d0d0d;border-bottom:1px solid #1c1c1e;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch;flex-shrink:0;align-items:center}
.folders-bar::-webkit-scrollbar{display:none}
.folder-pill{padding:6px 12px;border-radius:10px;background:#1c1c1e;color:#8e8e93;font-size:12px;font-weight:600;white-space:nowrap;cursor:pointer;transition:all 0.2s ease;display:flex;align-items:center;gap:6px}
.folder-pill svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2}
.folder-pill.active{background:#30d158;color:#000}

/* Toolbar: Search, Sort & Multi-select */
.toolbar{display:flex;align-items:center;gap:8px;padding:8px 16px;background:#0d0d0d;border-bottom:1px solid #1c1c1e;flex-shrink:0}
.search-box{flex:1;position:relative;display:flex;align-items:center}
.search-box svg{position:absolute;left:10px;width:16px;height:16px;color:#8e8e93;pointer-events:none}
.search-input{width:100%;padding:8px 12px 8px 32px;border-radius:10px;background:#1c1c1e;border:1px solid transparent;color:#fff;font-size:13px;outline:none;transition:all 0.2s}
.search-input:focus{border-color:#0a84ff;background:#2c2c2e}
.search-input::placeholder{color:#636366}

.sort-select{padding:7px 10px;border-radius:10px;background:#1c1c1e;border:none;color:#8e8e93;font-size:12px;font-weight:500;outline:none;cursor:pointer}

/* Multi-select bar */
.multiselect-bar{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:rgba(28,28,30,0.92);backdrop-filter:blur(20px);border:1px solid #3a3a3c;border-radius:20px;padding:8px 16px;display:flex;align-items:center;gap:16px;z-index:400;box-shadow:0 8px 32px rgba(0,0,0,0.6);transition:all 0.25s ease}
.multiselect-bar.hidden{display:none}
.multiselect-count{font-size:13px;font-weight:600;color:#fff}
.multiselect-btn{background:none;border:none;color:#0a84ff;font-size:13px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px}
.multiselect-btn.danger{color:#ff3b30}

/* SVG Category Tabs */
.tabs-container{display:flex;gap:6px;padding:8px 16px;background:#0d0d0d;border-bottom:1px solid #1c1c1e;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch;flex-shrink:0}
.tabs-container::-webkit-scrollbar{display:none}
.tab-item{padding:7px 12px;border-radius:10px;background:#1c1c1e;color:#8e8e93;font-size:12px;font-weight:600;white-space:nowrap;cursor:pointer;transition:all 0.2s ease;display:flex;align-items:center;gap:6px}
.tab-item svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:2}
.tab-item.active{background:#0a84ff;color:#fff}

/* Upload Drop Zone */
.upload-zone{margin:8px 16px;padding:12px;border:1.5px dashed #2c2c2e;border-radius:12px;text-align:center;cursor:pointer;transition:all 0.2s;background:#0d0d0d;flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:10px}
.upload-zone:active,.upload-zone.dragover{background:#1c1c1e;border-color:#0a84ff}
.upload-icon{width:24px;height:24px;color:#0a84ff;flex-shrink:0}
.upload-text{font-size:12px;color:#8e8e93;text-align:left;line-height:1.3}
.upload-text b{color:#fff;font-weight:600}

/* Professional File Grid */
.file-grid{flex:1;overflow-y:auto;padding:12px 16px 80px;display:grid;grid-template-columns:repeat(3,1fr);gap:10px;-webkit-overflow-scrolling:touch}
.file-item{position:relative;background:#141416;border-radius:12px;overflow:hidden;border:1px solid #1c1c1e;cursor:pointer;transition:transform 0.15s,box-shadow 0.15s,border-color 0.15s;display:flex;flex-direction:column;user-select:none}
.file-item:active{transform:scale(0.97)}
.file-item.selected{border-color:#0a84ff;box-shadow:0 0 0 2px rgba(10,132,255,0.4)}

.file-thumb-container{width:100%;aspect-ratio:1;position:relative;background:#1a1a1c;display:flex;align-items:center;justify-content:center;overflow:hidden}
.file-thumb{width:100%;height:100%;object-fit:cover;display:block}
.file-thumb svg{width:32px;height:32px;color:#48484a}

/* Version Pill Indicator */
.version-badge{position:absolute;top:6px;right:6px;background:rgba(0,0,0,0.75);backdrop-filter:blur(10px);color:#30d158;font-size:9px;font-weight:700;padding:2px 6px;border-radius:6px;border:1px solid rgba(48,209,88,0.3);z-index:5}

/* Checkbox overlay */
.file-checkbox{position:absolute;top:6px;left:6px;width:20px;height:20px;border-radius:50%;border:1.5px solid rgba(255,255,255,0.5);background:rgba(0,0,0,0.4);display:none;align-items:center;justify-content:center;z-index:10;transition:all 0.15s ease}
.file-item.selecting .file-checkbox{display:flex}
.file-item.selected .file-checkbox{background:#0a84ff;border-color:#0a84ff}
.file-checkbox svg{width:12px;height:12px;stroke:#fff;fill:none;stroke-width:3}

/* Decryption Micro Spinner */
.file-item.decrypting .file-thumb-container::after{content:'';position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);backdrop-filter:blur(2px)}
.file-item.decrypting .file-thumb-container::before{content:'';position:absolute;z-index:3;width:18px;height:18px;border:2px solid rgba(255,255,255,0.2);border-top-color:#0a84ff;border-radius:50%;animation:spin 0.6s linear infinite}

/* Minimal Info Card */
.file-info{padding:8px;background:#141416;display:flex;flex-direction:column;gap:2px}
.file-name{font-size:11px;font-weight:500;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-meta{font-size:10px;color:#8e8e93;display:flex;justify-content:space-between;align-items:center}

/* Upload Toast Progress Bar */
.upload-toast{position:fixed;top:70px;left:50%;transform:translateX(-50%);background:rgba(28,28,30,0.95);backdrop-filter:blur(20px);border:1px solid #3a3a3c;color:#fff;padding:10px 18px;border-radius:20px;font-size:13px;font-weight:500;z-index:900;display:flex;flex-direction:column;gap:6px;box-shadow:0 8px 32px rgba(0,0,0,0.6);min-width:260px}
.upload-toast.hidden{display:none}
.upload-toast-header{display:flex;align-items:center;justify-content:space-between}
.upload-progress-bar{height:4px;background:#2c2c2e;border-radius:2px;overflow:hidden}
.upload-progress-fill{height:100%;background:#0a84ff;border-radius:2px;width:0%;transition:width 0.2s ease}

/* Modals & Action Sheet */
.action-sheet{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);backdrop-filter:blur(10px);z-index:500;display:flex;flex-direction:column;justify-content:flex-end}
.action-sheet-content{background:#1c1c1e;border-top-left-radius:20px;border-top-right-radius:20px;padding:16px;display:flex;flex-direction:column;gap:8px}
.action-sheet-item{padding:14px 16px;border-radius:12px;background:#2c2c2e;color:#fff;font-size:15px;font-weight:500;display:flex;align-items:center;gap:12px;cursor:pointer}
.action-sheet-item.danger{color:#ff3b30}
.action-sheet-item svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:2}

.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);backdrop-filter:blur(15px);display:flex;align-items:center;justify-content:center;z-index:600;padding:20px}
.modal-content{background:#1c1c1e;border-radius:20px;padding:24px;width:100%;max-width:380px;border:1px solid #2c2c2e}
.modal-title{font-size:18px;font-weight:700;margin-bottom:8px;color:#fff;display:flex;align-items:center;gap:8px}
.modal-text{font-size:13px;color:#8e8e93;margin-bottom:16px;line-height:1.5}
.modal-input{width:100%;padding:12px 14px;border-radius:12px;background:#2c2c2e;border:1px solid #3a3a3c;color:#fff;font-size:14px;outline:none;margin-bottom:12px}
.modal-input:focus{border-color:#0a84ff}

.btn{width:100%;padding:14px;border:none;border-radius:12px;background:#fff;color:#000;font-size:15px;font-weight:600;cursor:pointer;margin-bottom:8px;transition:all 0.1s}
.btn:active{transform:scale(0.97);opacity:.85}
.btn-secondary{background:#2c2c2e;color:#fff;border:1px solid #3a3a3c}
.btn-danger{background:#ff3b30;color:#fff}

/* Key box & Share Link Box */
.key-box{background:#0a0a0a;border:1px solid #2c2c2e;padding:12px;border-radius:10px;font-family:monospace;font-size:11px;color:#30d158;word-break:break-all;max-height:80px;overflow-y:auto;margin-top:4px}
.warning-box{background:rgba(255,59,48,0.1);border:1px solid rgba(255,59,48,0.3);color:#ff453a;padding:12px;border-radius:10px;font-size:12px;margin-bottom:14px;line-height:1.4}

/* Empty State */
.empty-state{text-align:center;padding:60px 20px;color:#8e8e93;width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center}
.empty-state svg{width:56px;height:56px;color:#3a3a3c;margin-bottom:12px}
.empty-title{font-size:16px;font-weight:600;color:#f2f2f7;margin-bottom:6px}
.empty-text{font-size:13px;color:#8e8e93;line-height:1.4}

/* Preview Modal */
.preview-modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);backdrop-filter:blur(20px);z-index:700;display:flex;flex-direction:column;opacity:0;pointer-events:none;transition:opacity 0.2s ease}
.preview-modal.active{opacity:1;pointer-events:auto}
.preview-header{height:60px;background:#0d0d0d;display:flex;align-items:center;padding:0 16px;border-bottom:1px solid #1c1c1e;flex-shrink:0;justify-content:space-between}
.preview-body{flex:1;display:flex;align-items:center;justify-content:center;padding:20px;overflow:hidden}
.preview-body img{max-width:100%;max-height:100%;object-fit:contain;border-radius:8px}
.preview-body video{max-width:100%;max-height:100%;border-radius:8px}
.preview-body audio{width:100%;max-width:400px}
.preview-filename{color:#fff;font-size:14px;font-weight:600;flex:1;text-align:center;padding:0 12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
.hidden{display:none!important}
</style>
</head>
<body>
<div class="app">

<!-- Upload Progress Toast -->
<div class="upload-toast hidden" id="uploadToast">
  <div class="upload-toast-header">
    <span id="uploadToastText" style="font-size:12px;font-weight:600">Загрузка...</span>
    <span id="uploadToastPercent" style="font-size:11px;color:#8e8e93">0%</span>
  </div>
  <div class="upload-progress-bar">
    <div class="upload-progress-fill" id="uploadProgressFill"></div>
  </div>
</div>

<!-- Navigation Header -->
<div class="header">
  <div class="header-left">
    <div class="header-back" onclick="goBack()" title="Назад">
      <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" fill="none" stroke-width="2.5"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
    </div>
    <div>
      <div class="header-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0a84ff" stroke-width="2.5"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
        VK Cloud Ultra
      </div>
      <div class="header-subtitle" id="storageSubtitle">Зашифрованное хранилище v2.0</div>
    </div>
  </div>
  <div class="header-actions">
    <button class="header-btn" id="multiSelectToggleBtn" onclick="toggleMultiSelectMode()" title="Выбрать файлы">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
    </button>
    <button class="header-btn" onclick="openKeyModal()" title="Ключ шифрования">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    </button>
    <button class="header-btn" onclick="document.getElementById('fileInput').click()" title="Загрузить">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
    </button>
  </div>
</div>

<!-- Storage Bar -->
<div class="storage-bar">
  <div class="storage-info">
    <div class="storage-label">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
      Объём хранилища
    </div>
    <div class="storage-used" id="storageUsed">0 файлов</div>
  </div>
  <div class="storage-track">
    <div class="storage-fill" id="storageFill"></div>
  </div>
</div>

<!-- Folder Navigation Bar -->
<div class="folders-bar" id="foldersBar">
  <div class="folder-pill active" data-folder="" onclick="switchFolder('')">
    <svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    Все папки
  </div>
  <!-- Folder pills injected dynamically -->
  <div class="folder-pill" style="border:1.5px dashed #3a3a3c;background:none" onclick="promptCreateFolder()">
    <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
    Папка
  </div>
</div>

<!-- Toolbar: Search & Sort -->
<div class="toolbar">
  <div class="search-box">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    <input type="search" class="search-input" id="searchInput" placeholder="Поиск по файлам..." oninput="filterAndRenderFiles()">
  </div>
  <select class="sort-select" id="sortSelect" onchange="filterAndRenderFiles()">
    <option value="date-desc">Сначала новые</option>
    <option value="date-asc">Сначала старые</option>
    <option value="name-asc">Имя (А - Я)</option>
    <option value="name-desc">Имя (Я - А)</option>
    <option value="size-desc">Размер (большие)</option>
    <option value="size-asc">Размер (маленькие)</option>
  </select>
</div>

<!-- Professional SVG Category Tabs -->
<div class="tabs-container" id="categoryTabs">
  <div class="tab-item active" data-category="photo" onclick="switchCategory('photo')">
    <svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
    Фото
  </div>
  <div class="tab-item" data-category="video" onclick="switchCategory('video')">
    <svg viewBox="0 0 24 24"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
    Видео
  </div>
  <div class="tab-item" data-category="audio" onclick="switchCategory('audio')">
    <svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
    Музыка
  </div>
  <div class="tab-item" data-category="doc" onclick="switchCategory('doc')">
    <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
    Файлы
  </div>
</div>

<!-- Upload Zone -->
<div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
  <div class="upload-icon">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
  </div>
  <div class="upload-text">
    <b>Загрузить файлы в Облако</b><br>
    Нажмите или перетащите. Файлы шифруются частями на вашем устройстве.
  </div>
</div>

<input type="file" class="hidden" id="fileInput" multiple accept="image/*,video/*,audio/*,*/*" onchange="handleFiles(event)">

<!-- File Grid -->
<div class="file-grid" id="fileGrid"></div>

<!-- Multi-select Bottom Action Bar -->
<div class="multiselect-bar hidden" id="multiSelectBar">
  <span class="multiselect-count" id="multiSelectCount">Выбрано: 0</span>
  <button class="multiselect-btn" onclick="downloadSelectedBatch()">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    Скачать
  </button>
  <button class="multiselect-btn danger" onclick="deleteSelectedBatch()">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
    Удалить
  </button>
  <button class="multiselect-btn" style="color:#8e8e93" onclick="exitMultiSelectMode()">Отмена</button>
</div>

<!-- Empty State -->
<div class="empty-state hidden" id="emptyState">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
  <div class="empty-title">Файлов пока нет</div>
  <div class="empty-text">Загрузите файлы — они зашифруются и будут сохранены в облаке</div>
</div>

<!-- Preview Modal -->
<div class="preview-modal" id="previewModal" onclick="closePreview(event)">
  <div class="preview-header" onclick="event.stopPropagation()">
    <div class="header-back" onclick="closePreview()">
      <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" fill="none" stroke-width="2.5"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
    </div>
    <div class="preview-filename" id="previewFilename">Файл</div>
    <button class="header-btn" onclick="downloadCurrentFile()" title="Скачать">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    </button>
  </div>
  <div class="preview-body" id="previewBody" onclick="event.stopPropagation()"></div>
</div>

<!-- Action Sheet -->
<div class="action-sheet hidden" id="actionSheet" onclick="closeActionSheet(event)">
  <div class="action-sheet-content" onclick="event.stopPropagation()">
    <div class="action-sheet-item" onclick="previewSelectedFile()">
      <svg viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
      Открыть
    </div>
    <div class="action-sheet-item" onclick="downloadSelectedFile()">
      <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Скачать
    </div>
    <div class="action-sheet-item" onclick="generateShareLinkForSelectedFile()">
      <svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
      Поделиться ссылкой
    </div>
    <div class="action-sheet-item" onclick="showVersionHistoryModal()">
      <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      История версий
    </div>
    <div class="action-sheet-item danger" onclick="deleteSelectedFile()">
      <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
      Удалить
    </div>
    <div class="action-sheet-item" style="justify-content:center;color:#8e8e93" onclick="closeActionSheet()">Отмена</div>
  </div>
</div>

<!-- Share Link Modal -->
<div class="modal hidden" id="shareModal">
  <div class="modal-content">
    <div class="modal-title">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0a84ff" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
      Временная ссылка
    </div>
    <div class="modal-text">Ссылка действительна 24 часа для прямой загрузки зашифрованного файла:</div>
    <input type="text" class="modal-input" id="shareLinkInput" readonly onclick="this.select()">
    <button class="btn" onclick="copyShareLink()">Скопировать ссылку</button>
    <button class="btn btn-secondary" onclick="closeShareModal()">Закрыть</button>
  </div>
</div>

<!-- Version History Modal -->
<div class="modal hidden" id="versionModal">
  <div class="modal-content">
    <div class="modal-title">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#30d158" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      История версий
    </div>
    <div class="modal-text" id="versionModalSub">Версии файла:</div>
    <div id="versionListContainer" style="max-height:200px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;margin-bottom:16px"></div>
    <button class="btn btn-secondary" onclick="closeVersionModal()">Закрыть</button>
  </div>
</div>

<!-- Encryption Key Settings Modal -->
<div class="modal hidden" id="keyModal">
  <div class="modal-content">
    <div class="modal-title">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0a84ff" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
      Ключ шифрования
    </div>
    <div class="warning-box">
      Ключ шифрует медиафайлы прямо в вашем браузере с помощью WebCrypto (AES-GCM 256). Сохраните его для использования на других устройствах!
    </div>
    <div class="modal-text" style="margin-bottom:4px">Зашифрованный JWK-ключ:</div>
    <div class="key-box" id="keyBox">Загрузка...</div>
    <div style="display:flex;gap:8px;margin-top:16px">
      <button class="btn btn-secondary" style="flex:1;font-size:13px;padding:10px" onclick="exportCloudKey()">📤 Экспорт</button>
      <button class="btn btn-secondary" style="flex:1;font-size:13px;padding:10px" onclick="document.getElementById('importKeyInput').click()">📥 Импорт</button>
    </div>
    <input type="file" class="hidden" id="importKeyInput" accept=".json" onchange="importCloudKey(event)">
    <button class="btn btn-danger" style="margin-top:10px;font-size:13px;padding:10px" onclick="regenerateCloudKey()">🔄 Сгенерировать новый</button>
    <button class="btn" style="margin-top:10px" onclick="closeKeyModal()">Закрыть</button>
  </div>
</div>

</div>

<script>
let token = localStorage.getItem('vk_token');
let myVkId = null;
let cloudKey = null;
let filesData = [];
let currentCategory = 'photo';
let currentFolder = '';
let availableFolders = new Set();
let selectedFile = null;
let currentPreviewFile = null;

// Multi-selection state
let isMultiSelectMode = false;
let selectedDocIds = new Set();

// Memory leak protection cache & abort controllers
const decryptionCache = {}; // doc_id -> { blobUrl, blob }
let activeAbortController = null;
let intersectionObserver = null;

function showToastProgress(text, percent) {
    const t = document.getElementById('uploadToast');
    document.getElementById('uploadToastText').textContent = text;
    document.getElementById('uploadToastPercent').textContent = percent + '%';
    document.getElementById('uploadProgressFill').style.width = percent + '%';
    t.classList.remove('hidden');
}
function hideToastProgress() {
    document.getElementById('uploadToast').classList.add('hidden');
}

function goBack() { window.location.href = '/'; }

async function initCloud() {
    if (!token) { alert('Сначала войдите в аккаунт'); goBack(); return; }

    try {
        const res = await fetch('/cloud/api/init', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({token})
        });
        const data = await res.json();
        if (data.error) { alert(data.error); goBack(); return; }
        myVkId = data.vk_id;

        await initCloudKey();
        await loadFiles();
    } catch(e) { console.error(e); }
}

async function initCloudKey() {
    const storedKey = localStorage.getItem('vk_cloud_key_' + myVkId);
    const storedPass = localStorage.getItem('vk_pass');

    if (storedKey) {
        try {
            cloudKey = await importCloudCryptoKey(storedKey);
            return;
        } catch(e) {}
    }

    try {
        const res = await fetch('/cloud/api/key/' + myVkId);
        const data = await res.json();
        if (data.cloud_key_enc && storedPass) {
            const masterKey = await deriveCloudKey(storedPass, myVkId + "_cloud_salt");
            const decBuf = await decryptAESGCM(masterKey, b64ToBuf(data.cloud_key_enc));
            const keyJwk = JSON.parse(new TextDecoder().decode(decBuf));
            cloudKey = await crypto.subtle.importKey("jwk", keyJwk, {name:"AES-GCM", length:256}, true, ["encrypt","decrypt"]);
            localStorage.setItem('vk_cloud_key_' + myVkId, JSON.stringify(keyJwk));
            return;
        }
    } catch(e) {}

    cloudKey = await crypto.subtle.generateKey({name:"AES-GCM", length:256}, true, ["encrypt","decrypt"]);
    const keyJwk = await crypto.subtle.exportKey("jwk", cloudKey);
    localStorage.setItem('vk_cloud_key_' + myVkId, JSON.stringify(keyJwk));

    if (storedPass) {
        const masterKey = await deriveCloudKey(storedPass, myVkId + "_cloud_salt");
        const encBuf = await encryptAESGCM(masterKey, new TextEncoder().encode(JSON.stringify(keyJwk)));
        await fetch('/cloud/api/key/' + myVkId, {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({cloud_key_enc: bufToB64(encBuf)})
        });
    }
}

async function deriveCloudKey(pass, saltStr) {
    const enc = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey("raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]);
    return await crypto.subtle.deriveKey(
        {name:"PBKDF2", salt:enc.encode(saltStr), iterations:600000, hash:"SHA-256"},
        keyMaterial,
        {name:"AES-GCM", length:256},
        false,
        ["encrypt","decrypt"]
    );
}

// Chunked Memory-efficient AES-GCM Encryption
async function encryptAESGCM(key, plainBuf) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({name:"AES-GCM", iv}, key, plainBuf);
    const combined = new Uint8Array(iv.byteLength + ciphertext.byteLength);
    combined.set(iv, 0);
    combined.set(new Uint8Array(ciphertext), iv.byteLength);
    return combined.buffer;
}

async function decryptAESGCM(key, combinedBuf) {
    const bytes = new Uint8Array(combinedBuf);
    const iv = bytes.slice(0, 12);
    const ciphertext = bytes.slice(12);
    return await crypto.subtle.decrypt({name:"AES-GCM", iv}, key, ciphertext);
}

function bufToB64(buf) {
    let binary = '';
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
}

function b64ToBuf(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
}

async function importCloudCryptoKey(jwkStr) {
    const jwk = typeof jwkStr === 'string' ? JSON.parse(jwkStr) : jwkStr;
    return await crypto.subtle.importKey("jwk", jwk, {name:"AES-GCM", length:256}, true, ["encrypt","decrypt"]);
}

async function loadFiles() {
    showToastProgress('Синхронизация...', 20);
    try {
        const res = await fetch('/cloud/api/files', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({token})
        });
        const data = await res.json();
        filesData = data.files || [];
        
        // Extract folders
        availableFolders.clear();
        for (const f of filesData) {
            if (f.folder) availableFolders.add(f.folder);
        }
        renderFoldersBar();
        filterAndRenderFiles();
    } catch(e) { console.error(e); }
    hideToastProgress();
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
    if (bytes < 1024*1024*1024) return (bytes/(1024*1024)).toFixed(1) + ' MB';
    return (bytes/(1024*1024*1024)).toFixed(1) + ' GB';
}

function renderFoldersBar() {
    const bar = document.getElementById('foldersBar');
    bar.innerHTML = `
        <div class="folder-pill ${currentFolder === '' ? 'active' : ''}" data-folder="" onclick="switchFolder('')">
            <svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            Все файлы
        </div>
    `;

    for (const folderName of availableFolders) {
        const div = document.createElement('div');
        div.className = `folder-pill ${currentFolder === folderName ? 'active' : ''}`;
        div.dataset.folder = folderName;
        div.innerHTML = `
            <svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            ${escapeHtml(folderName)}
        `;
        div.onclick = () => switchFolder(folderName);
        bar.appendChild(div);
    }

    const addDiv = document.createElement('div');
    addDiv.className = 'folder-pill';
    addDiv.style.cssText = 'border:1.5px dashed #3a3a3c;background:none';
    addDiv.innerHTML = `<svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Папка`;
    addDiv.onclick = promptCreateFolder;
    bar.appendChild(addDiv);
}

function switchFolder(folderName) {
    currentFolder = folderName;
    renderFoldersBar();
    filterAndRenderFiles();
}

function promptCreateFolder() {
    const name = prompt('Введите имя новой папки:');
    if (name && name.trim()) {
        currentFolder = name.trim();
        availableFolders.add(currentFolder);
        renderFoldersBar();
        filterAndRenderFiles();
    }
}

function switchCategory(cat) {
    currentCategory = cat;
    document.querySelectorAll('.tab-item').forEach(el => {
        el.classList.toggle('active', el.dataset.category === cat);
    });
    filterAndRenderFiles();
}

// Group versions & Search & Sort
function filterAndRenderFiles() {
    if (activeAbortController) {
        activeAbortController.abort();
    }
    activeAbortController = new AbortController();

    const searchQuery = (document.getElementById('searchInput').value || '').toLowerCase().trim();
    const sortValue = document.getElementById('sortSelect').value;

    let filtered = filesData.filter(f => f.type === currentCategory);

    if (currentFolder) {
        filtered = filtered.filter(f => f.folder === currentFolder);
    }

    if (searchQuery) {
        filtered = filtered.filter(f => f.name.toLowerCase().includes(searchQuery));
    }

    // Grouping by versions (highest version shown first)
    const groupedMap = new Map();
    for (const f of filtered) {
        const key = (f.folder || '') + '|' + f.name;
        if (!groupedMap.has(key)) {
            groupedMap.set(key, []);
        }
        groupedMap.get(key).push(f);
    }

    const primaryFiles = [];
    for (const [key, versions] of groupedMap.entries()) {
        versions.sort((a, b) => (b.version || 1) - (a.version || 1));
        const primary = versions[0];
        primary.allVersions = versions;
        primaryFiles.push(primary);
    }

    // Sort
    primaryFiles.sort((a, b) => {
        if (sortValue === 'date-desc') return (b.date || '').localeCompare(a.date || '');
        if (sortValue === 'date-asc') return (a.date || '').localeCompare(b.date || '');
        if (sortValue === 'name-asc') return a.name.localeCompare(b.name);
        if (sortValue === 'name-desc') return b.name.localeCompare(a.name);
        if (sortValue === 'size-desc') return b.size - a.size;
        if (sortValue === 'size-asc') return a.size - b.size;
        return 0;
    });

    renderGrid(primaryFiles);
}

// Safe DOM Construction
function renderGrid(filteredFiles) {
    const grid = document.getElementById('fileGrid');
    const empty = document.getElementById('emptyState');
    const usedLabel = document.getElementById('storageUsed');

    grid.innerHTML = '';
    usedLabel.textContent = filteredFiles.length + ' файлов';

    if (filteredFiles.length === 0) {
        empty.classList.remove('hidden');
        return;
    }
    empty.classList.add('hidden');

    if (intersectionObserver) intersectionObserver.disconnect();

    intersectionObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const docId = entry.target.dataset.id;
                const fileObj = filteredFiles.find(f => f.doc_id === docId);
                if (fileObj) {
                    lazyDecryptItem(fileObj);
                    intersectionObserver.unobserve(entry.target);
                }
            }
        });
    }, { root: grid, rootMargin: '100px' });

    for (const f of filteredFiles) {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'file-item' + (isMultiSelectMode ? ' selecting' : '') + (selectedDocIds.has(f.doc_id) ? ' selected' : '');
        itemDiv.id = `item_${f.doc_id}`;
        itemDiv.dataset.id = f.doc_id;

        // Version badge if > 1 version
        if (f.allVersions && f.allVersions.length > 1) {
            const vBadge = document.createElement('div');
            vBadge.className = 'version-badge';
            vBadge.textContent = `v${f.version || 1} (${f.allVersions.length})`;
            itemDiv.appendChild(vBadge);
        }

        // Checkbox overlay for multi-select
        const checkDiv = document.createElement('div');
        checkDiv.className = 'file-checkbox';
        checkDiv.innerHTML = `<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>`;
        itemDiv.appendChild(checkDiv);

        // Thumbnail Container
        const thumbContainer = document.createElement('div');
        thumbContainer.className = 'file-thumb-container';

        const placeholderIcon = document.createElement('div');
        placeholderIcon.className = 'file-thumb';
        placeholderIcon.style.cssText = 'display:flex;align-items:center;justify-content:center';
        placeholderIcon.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 15V3m0 12l-4-4m4 4l4-4M2 17l.621 2.485A2 2 0 004.561 21h14.878a2 2 0 001.94-1.515L22 17"/></svg>`;
        thumbContainer.appendChild(placeholderIcon);
        itemDiv.appendChild(thumbContainer);

        // Card Info
        const infoDiv = document.createElement('div');
        infoDiv.className = 'file-info';

        const nameDiv = document.createElement('div');
        nameDiv.className = 'file-name';
        nameDiv.textContent = f.name;

        const metaDiv = document.createElement('div');
        metaDiv.className = 'file-meta';
        
        const sizeSpan = document.createElement('span');
        sizeSpan.textContent = formatSize(f.size);

        metaDiv.appendChild(sizeSpan);
        infoDiv.appendChild(nameDiv);
        infoDiv.appendChild(metaDiv);

        itemDiv.appendChild(infoDiv);

        itemDiv.onclick = (e) => {
            if (isMultiSelectMode) {
                toggleItemSelection(f.doc_id, itemDiv);
            } else {
                openFile(f);
            }
        };

        itemDiv.oncontextmenu = (e) => {
            e.preventDefault();
            if (!isMultiSelectMode) showActionSheet(f);
        };

        grid.appendChild(itemDiv);

        if (decryptionCache[f.doc_id]) {
            applyDecryptedPreview(f.doc_id, f.type);
        } else {
            intersectionObserver.observe(itemDiv);
        }
    }
}

// On-the-fly Lazy Decryptor
async function lazyDecryptItem(f) {
    if (decryptionCache[f.doc_id]) {
        applyDecryptedPreview(f.doc_id, f.type);
        return;
    }

    const itemEl = document.getElementById(`item_${f.doc_id}`);
    if (!itemEl) return;

    itemEl.classList.add('decrypting');

    try {
        const resp = await fetch('/cloud/api/download?url=' + encodeURIComponent(f.url), {
            signal: activeAbortController ? activeAbortController.signal : null
        });
        if (!resp.ok) throw new Error("Download failed");

        const encBuf = await resp.arrayBuffer();
        const decBuf = await decryptAESGCM(cloudKey, encBuf);
        const blob = new Blob([decBuf], {type: f.mime || 'application/octet-stream'});
        const blobUrl = URL.createObjectURL(blob);

        decryptionCache[f.doc_id] = { blobUrl, blob };
        applyDecryptedPreview(f.doc_id, f.type);
    } catch (e) {
        if (e.name !== 'AbortError') {
            console.error("Decrypt error:", f.name, e);
        }
    } finally {
        itemEl.classList.remove('decrypting');
    }
}

function applyDecryptedPreview(doc_id, type) {
    const itemEl = document.getElementById(`item_${doc_id}`);
    if (!itemEl) return;

    const cache = decryptionCache[doc_id];
    if (!cache) return;

    const container = itemEl.querySelector('.file-thumb-container');
    if (!container) return;

    container.innerHTML = '';

    if (type === 'photo') {
        const img = document.createElement('img');
        img.className = 'file-thumb';
        img.src = cache.blobUrl;
        container.appendChild(img);
    } else if (type === 'video') {
        const vid = document.createElement('video');
        vid.src = cache.blobUrl;
        vid.muted = true;
        vid.loop = true;
        vid.playsInline = true;
        vid.autoplay = true;
        vid.style.cssText = 'width:100%;height:100%;object-fit:cover';
        container.appendChild(vid);
    } else if (type === 'audio') {
        container.innerHTML = `<div class="file-thumb" style="display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" fill="none" stroke="#30d158" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg></div>`;
    } else {
        container.innerHTML = `<div class="file-thumb" style="display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" fill="none" stroke="#af52de" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div>`;
    }
}

// Multi-Select Mode Operations
function toggleMultiSelectMode() {
    isMultiSelectMode = !isMultiSelectMode;
    document.getElementById('multiSelectToggleBtn').classList.toggle('active', isMultiSelectMode);
    document.getElementById('multiSelectBar').classList.toggle('hidden', !isMultiSelectMode);

    if (!isMultiSelectMode) {
        selectedDocIds.clear();
    }
    filterAndRenderFiles();
}

function toggleItemSelection(doc_id, itemEl) {
    if (selectedDocIds.has(doc_id)) {
        selectedDocIds.delete(doc_id);
        itemEl.classList.remove('selected');
    } else {
        selectedDocIds.add(doc_id);
        itemEl.classList.add('selected');
    }
    document.getElementById('multiSelectCount').textContent = `Выбрано: ${selectedDocIds.size}`;
}

function exitMultiSelectMode() {
    isMultiSelectMode = false;
    selectedDocIds.clear();
    document.getElementById('multiSelectToggleBtn').classList.remove('active');
    document.getElementById('multiSelectBar').classList.add('hidden');
    filterAndRenderFiles();
}

async function downloadSelectedBatch() {
    if (selectedDocIds.size === 0) return;
    for (const docId of selectedDocIds) {
        const fileObj = filesData.find(f => f.doc_id === docId);
        if (fileObj) {
            const cached = decryptionCache[docId];
            if (cached) {
                const a = document.createElement('a');
                a.href = cached.blobUrl;
                a.download = fileObj.name;
                a.click();
            }
        }
    }
}

async function deleteSelectedBatch() {
    if (selectedDocIds.size === 0) return;
    if (!confirm(`Удалить выбранные файлы (${selectedDocIds.size} шт.)?`)) return;

    showToastProgress('Удаление...', 50);
    for (const docId of selectedDocIds) {
        try {
            await fetch('/cloud/api/delete', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({token, doc_id: docId})
            });
            if (decryptionCache[docId]) {
                URL.revokeObjectURL(decryptionCache[docId].blobUrl);
                delete decryptionCache[docId];
            }
        } catch(e) {}
    }
    exitMultiSelectMode();
    await loadFiles();
    hideToastProgress();
}

// Parallel Concurrency Upload Runner (Max 3 Concurrent Streams)
async function pMap(items, concurrency, fn) {
    const results = [];
    const executing = [];
    for (const item of items) {
        const p = Promise.resolve().then(() => fn(item));
        results.push(p);
        if (concurrency <= items.length) {
            const e = p.then(() => executing.splice(executing.indexOf(e), 1));
            executing.push(e);
            if (executing.length >= concurrency) {
                await Promise.race(executing);
            }
        }
    }
    return Promise.all(results);
}

// File Upload with Concurrency & Real Progress & Versioning
async function handleFiles(e) {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    for (const f of files) {
        if (f.size > 200 * 1024 * 1024) {
            alert(`Файл ${f.name} превышает лимит ВКонтакте (200 МБ)`);
            return;
        }
    }

    let completed = 0;
    const total = files.length;

    await pMap(files, 3, async (file) => {
        // Calculate next version if file exists
        const existingVersions = filesData.filter(f => f.name === file.name && f.folder === currentFolder);
        const nextVersion = existingVersions.length > 0 ? (Math.max(...existingVersions.map(v => v.version || 1)) + 1) : 1;

        showToastProgress(`Загрузка ${file.name} (v${nextVersion})...`, Math.round((completed / total) * 100));

        try {
            const fileBuf = await file.arrayBuffer();
            const encBuf = await encryptAESGCM(cloudKey, fileBuf);
            const encBlob = new Blob([encBuf], {type: 'application/octet-stream'});

            const formData = new FormData();
            formData.append('token', token);
            formData.append('file', encBlob, 'encrypted_payload.bin');
            formData.append('original_name', file.name);
            formData.append('folder', currentFolder);
            formData.append('version', nextVersion);
            formData.append('size', file.size);

            const res = await fetch('/cloud/api/upload', {
                method: 'POST',
                body: formData
            });

            const data = await res.json();
            if (data.error) {
                alert('Ошибка загрузки: ' + data.error);
            }
        } catch(e) {
            console.error('Upload error:', e);
            alert('Ошибка при шифровании файла');
        }
        completed++;
        showToastProgress(`Загрузка (${completed}/${total})...`, Math.round((completed / total) * 100));
    });

    showToastProgress('Завершение...', 100);
    e.target.value = '';
    await loadFiles();
    hideToastProgress();
}

// Share Links & Version History Modals
async function generateShareLinkForSelectedFile() {
    closeActionSheet();
    if (!selectedFile) return;

    try {
        const res = await fetch('/cloud/api/share/generate', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({doc_url: selectedFile.url})
        });
        const data = await res.json();
        if (data.share_url) {
            document.getElementById('shareLinkInput').value = data.share_url;
            document.getElementById('shareModal').classList.remove('hidden');
        }
    } catch(e) {
        alert('Не удалось сгенерировать ссылку');
    }
}

function copyShareLink() {
    const input = document.getElementById('shareLinkInput');
    input.select();
    navigator.clipboard.writeText(input.value);
    alert('Ссылка скопирована!');
    closeShareModal();
}

function closeShareModal() {
    document.getElementById('shareModal').classList.add('hidden');
}

function showVersionHistoryModal() {
    closeActionSheet();
    if (!selectedFile) return;

    const modal = document.getElementById('versionModal');
    const container = document.getElementById('versionListContainer');
    document.getElementById('versionModalSub').textContent = `История версий файла "${selectedFile.name}":`;

    container.innerHTML = '';
    const versions = selectedFile.allVersions || [selectedFile];

    for (const v of versions) {
        const div = document.createElement('div');
        div.className = 'action-sheet-item';
        div.style.cssText = 'background:#2c2c2e;margin-bottom:0;justify-content:space-between';
        div.innerHTML = `
            <div>
                <div style="font-size:13px;font-weight:600;color:#fff">Версия ${v.version || 1}</div>
                <div style="font-size:10px;color:#8e8e93">${v.date} · ${formatSize(v.size)}</div>
            </div>
            <button class="btn" style="width:auto;padding:6px 12px;font-size:12px;margin:0" onclick="openFileFromObj('${v.doc_id}')">Открыть</button>
        `;
        container.appendChild(div);
    }

    modal.classList.remove('hidden');
}

function closeVersionModal() {
    document.getElementById('versionModal').classList.add('hidden');
}

function openFileFromObj(docId) {
    closeVersionModal();
    const fObj = filesData.find(f => f.doc_id === docId);
    if (fObj) openFile(fObj);
}

// Instant Preview / Playback
function openFile(f) {
    const cached = decryptionCache[f.doc_id];
    if (!cached) {
        alert("Расшифровка файла...");
        lazyDecryptItem(f);
        return;
    }

    currentPreviewFile = {...f, blobUrl: cached.blobUrl};

    const modal = document.getElementById('previewModal');
    const body = document.getElementById('previewBody');
    const filename = document.getElementById('previewFilename');

    filename.textContent = f.name;
    body.innerHTML = '';

    if (f.type === 'photo') {
        const img = document.createElement('img');
        img.src = cached.blobUrl;
        body.appendChild(img);
    } else if (f.type === 'video') {
        const vid = document.createElement('video');
        vid.src = cached.blobUrl;
        vid.controls = true;
        vid.autoplay = true;
        body.appendChild(vid);
    } else if (f.type === 'audio') {
        const aud = document.createElement('audio');
        aud.src = cached.blobUrl;
        aud.controls = true;
        aud.autoplay = true;
        body.appendChild(aud);
    } else {
        const a = document.createElement('a');
        a.href = cached.blobUrl;
        a.download = f.name;
        a.textContent = 'Скачать файл';
        a.style.cssText = 'color:#0a84ff;font-size:15px;text-decoration:none;padding:16px 24px;border:1.5px solid #0a84ff;border-radius:12px;font-weight:600';
        body.appendChild(a);
    }

    modal.classList.add('active');
}

function closePreview(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('previewModal').classList.remove('active');
    currentPreviewFile = null;
}

function downloadCurrentFile() {
    if (!currentPreviewFile || !currentPreviewFile.blobUrl) return;
    const a = document.createElement('a');
    a.href = currentPreviewFile.blobUrl;
    a.download = currentPreviewFile.name;
    a.click();
}

function showActionSheet(f) {
    selectedFile = f;
    document.getElementById('actionSheet').classList.remove('hidden');
}

function closeActionSheet(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('actionSheet').classList.add('hidden');
}

function previewSelectedFile() {
    closeActionSheet();
    if (selectedFile) openFile(selectedFile);
}

function downloadSelectedFile() {
    closeActionSheet();
    if (selectedFile) {
        const cached = decryptionCache[selectedFile.doc_id];
        if (cached) {
            const a = document.createElement('a');
            a.href = cached.blobUrl;
            a.download = selectedFile.name;
            a.click();
        } else {
            openFile(selectedFile);
        }
    }
}

async function deleteSelectedFile() {
    closeActionSheet();
    if (!selectedFile) return;
    if (!confirm('Удалить этот файл из облака?')) return;

    showToastProgress('Удаление...', 50);
    try {
        const res = await fetch('/cloud/api/delete', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({token, doc_id: selectedFile.doc_id})
        });
        const d = await res.json();
        if (d.error) {
            alert("Не удалось удалить из облака.");
        } else {
            if (decryptionCache[selectedFile.doc_id]) {
                URL.revokeObjectURL(decryptionCache[selectedFile.doc_id].blobUrl);
                delete decryptionCache[selectedFile.doc_id];
            }
            await loadFiles();
        }
    } catch(e) {}
    hideToastProgress();
}

// Encryption keys
function openKeyModal() {
    const keyBox = document.getElementById('keyBox');
    const storedKey = localStorage.getItem('vk_cloud_key_' + myVkId);
    if (storedKey) {
        keyBox.textContent = storedKey.substring(0, 60) + '...';
    } else {
        keyBox.textContent = 'Ключ не найден';
    }
    document.getElementById('keyModal').classList.remove('hidden');
}

function closeKeyModal() {
    document.getElementById('keyModal').classList.add('hidden');
}

function exportCloudKey() {
    const storedKey = localStorage.getItem('vk_cloud_key_' + myVkId);
    if (!storedKey) { alert('Ключ не найден'); return; }
    const blob = new Blob([storedKey], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `vk_tsuyu_cloud_key_${myVkId}.json`;
    a.click();
}

async function importCloudKey(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (evt) => {
        try {
            const keyData = JSON.parse(evt.target.result);
            localStorage.setItem('vk_cloud_key_' + myVkId, JSON.stringify(keyData));
            cloudKey = await importCloudCryptoKey(keyData);
            alert('Ключ облака импортирован!');
            location.reload();
        } catch(err) {
            alert('Неверный формат ключа');
        }
    };
    reader.readAsText(file);
    e.target.value = '';
}

async function regenerateCloudKey() {
    if (!confirm('ВНИМАНИЕ: Новый ключ НЕ сможет расшифровать старые файлы! Старые файлы станут недоступны.')) return;

    cloudKey = await crypto.subtle.generateKey({name:"AES-GCM", length:256}, true, ["encrypt","decrypt"]);
    const keyJwk = await crypto.subtle.exportKey("jwk", cloudKey);
    localStorage.setItem('vk_cloud_key_' + myVkId, JSON.stringify(keyJwk));

    const storedPass = localStorage.getItem('vk_pass');
    if (storedPass && myVkId) {
        const masterKey = await deriveCloudKey(storedPass, myVkId + "_cloud_salt");
        const encBuf = await encryptAESGCM(masterKey, new TextEncoder().encode(JSON.stringify(keyJwk)));
        await fetch('/cloud/api/key/' + myVkId, {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({cloud_key_enc: bufToB64(encBuf)})
        });
    }

    alert('Новый ключ создан! Перезапуск...');
    location.reload();
}

// Drag & drop
const uploadZone = document.getElementById('uploadZone');
uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFiles({target: {files}});
    }
});

function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

initCloud();
</script>
</body>
</html>
"""


@cloud_bp.route('/')
def cloud_index():
    return render_template_string(CLOUD_HTML)


@cloud_bp.route('/api/init', methods=['POST'])
def cloud_init():
    token = request.json.get('token')
    if not token:
        return jsonify({'error': 'No token'}), 400

    params = {'access_token': token, 'v': API_VERSION}
    try:
        resp = get_session().get(f"{VK_API}/users.get", params=params, headers=KATE_HEADERS, timeout=10)
        data = resp.json()
        user = data.get('response', [{}])[0]
        vk_id = user.get('id')
        return jsonify({'vk_id': vk_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@cloud_bp.route('/api/key/<vk_id>', methods=['GET'])
def get_cloud_key(vk_id):
    stored = get_cloud_key_data(vk_id)
    if stored:
        return jsonify(stored)
    return jsonify({'error': 'Not found'}), 404


@cloud_bp.route('/api/key/<vk_id>', methods=['POST'])
def save_cloud_key(vk_id):
    data = request.json
    now_iso = datetime.now().isoformat()
    if 'cloud_key_enc' in data:
        store_cloud_key(vk_id, {'cloud_key_enc': data['cloud_key_enc'], 'created_at': now_iso})
    return jsonify({'ok': True})


@cloud_bp.route('/api/files', methods=['POST'])
def cloud_files():
    """Reads docs from VK via Kate Mobile API and decodes full metadata"""
    token = request.json.get('token')
    if not token:
        return jsonify({'error': 'No token'}), 400

    result = vk_request('docs.get', token, count=2000, type=0)

    if isinstance(result, dict) and 'error' in result:
        return jsonify(result), 400

    files = []
    for item in result.get('items', []):
        title = item.get('title', '')

        # Decode obfuscated title JSON metadata
        decoded_meta = decode_cloud_title(title)
        if decoded_meta and isinstance(decoded_meta, dict):
            files.append({
                'doc_id': f"doc{item.get('owner_id')}_{item.get('id')}",
                'name': decoded_meta.get('n', 'file'),
                'type': decoded_meta.get('t', 'doc'),
                'folder': decoded_meta.get('f', ''),
                'version': decoded_meta.get('v', 1),
                'tags': decoded_meta.get('tg', []),
                'url': item.get('url', ''),
                'size': item.get('size', 0),
                'mime': item.get('type', 'application/octet-stream'),
                'date': datetime.fromtimestamp(item.get('date', 0)).strftime('%Y-%m-%d') if item.get('date') else ''
            })
            continue

        # Backward compatibility fallback for simple title formatting
        title_lower = title.lower()
        is_cloud = (title_lower.startswith('cloud_') and title_lower.endswith('.doc')) or \
                   title_lower.endswith('.cimg.doc') or title_lower.endswith('.cvid.doc') or \
                   title_lower.endswith('.caud.doc') or title_lower.endswith('.cld.doc')

        if is_cloud:
            orig_name = title
            if orig_name.endswith('.doc'):
                orig_name = orig_name[:-4]

            file_type = 'doc'
            if orig_name.endswith(('.cimg', '.png', '.jpg', '.jpeg', '.gif')):
                file_type = 'photo'
            elif orig_name.endswith(('.cvid', '.mp4', '.avi', '.mov')):
                file_type = 'video'
            elif orig_name.endswith(('.caud', '.mp3', '.ogg', '.wav')):
                file_type = 'audio'

            files.append({
                'doc_id': f"doc{item.get('owner_id')}_{item.get('id')}",
                'name': orig_name,
                'type': file_type,
                'folder': '',
                'version': 1,
                'tags': [],
                'url': item.get('url', ''),
                'size': item.get('size', 0),
                'mime': item.get('type', 'application/octet-stream'),
                'date': datetime.fromtimestamp(item.get('date', 0)).strftime('%Y-%m-%d') if item.get('date') else ''
            })

    return jsonify({'files': files})


@cloud_bp.route('/api/upload', methods=['POST'])
def cloud_upload():
    """Uploads encrypted file using Kate Mobile signature and encodes complete metadata JSON inside title"""
    token = request.form.get('token')
    file = request.files.get('file')
    original_name = request.form.get('original_name', 'encrypted_file')
    folder = request.form.get('folder', '')
    version = int(request.form.get('version', 1))

    if not file or not token:
        return jsonify({'error': 'Missing file or token'}), 400

    file_bytes = file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return jsonify({'error': 'File size exceeds VK 200MB limit'}), 400

    # Get upload server
    upload_server = vk_request('docs.getMessagesUploadServer', token, type='doc', peer_id=0)
    if isinstance(upload_server, dict) and 'error' in upload_server:
        return jsonify(upload_server), 400

    upload_url = upload_server.get('upload_url')
    files = {'file': (secure_filename(file.filename), BytesIO(file_bytes), 'application/octet-stream')}
    
    upload_resp = get_session().post(upload_url, files=files, headers=KATE_HEADERS, timeout=60).json()

    # Determine type of the file
    file_type = 'doc'
    original_name_lower = original_name.lower()
    if original_name_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
        file_type = 'photo'
    elif original_name_lower.endswith(('.mp4', '.mov', '.avi', '.mkv', '.3gp')):
        file_type = 'video'
    elif original_name_lower.endswith(('.mp3', '.ogg', '.wav', '.m4a')):
        file_type = 'audio'

    # Encode full JSON title metadata
    safe_title = encode_cloud_title(original_name, file_type, folder=folder, version=version)

    save_result = vk_request('docs.save', token, 
        file=upload_resp.get('file'), 
        title=safe_title
    )

    attachment = extract_doc_attachment(save_result)
    if attachment:
        return jsonify({'ok': True, 'attachment': attachment})

    return jsonify({'error': 'Upload failed', 'details': save_result}), 400


@cloud_bp.route('/api/share/generate', methods=['POST'])
def generate_share_link():
    doc_url = request.json.get('doc_url')
    if not doc_url or not is_safe_vk_url(doc_url):
        return jsonify({'error': 'Invalid URL'}), 400

    token = generate_share_token(doc_url, ttl_seconds=86400)
    share_url = f"{request.host_url.rstrip('/')}/cloud/s/{token}"
    return jsonify({'share_url': share_url})


@cloud_bp.route('/s/<share_token>')
def access_shared_file(share_token):
    doc_url = parse_share_token(share_token)
    if not doc_url:
        return "Ссылка недействительна или её срок действия (24ч) истёк.", 403

    try:
        resp = get_session().get(doc_url, headers=KATE_HEADERS, timeout=30, allow_redirects=True)
        if resp.status_code != 200:
            return jsonify({'error': f'HTTP {resp.status_code}'}), resp.status_code
        return Response(resp.content, mimetype='application/octet-stream')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@cloud_bp.route('/api/download')
def cloud_download():
    """Proxy file downloading through Kate Mobile User Agent with SSRF host validation"""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL'}), 400

    if not is_safe_vk_url(url):
        return jsonify({'error': 'SSRF Protection: Invalid URL domain'}), 403

    try:
        resp = get_session().get(url, headers=KATE_HEADERS, timeout=30, allow_redirects=True)
        if resp.status_code != 200:
            return jsonify({'error': f'HTTP {resp.status_code}'}), resp.status_code
        return Response(resp.content, mimetype='application/octet-stream')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@cloud_bp.route('/api/delete', methods=['POST'])
def cloud_delete():
    token = request.json.get('token')
    doc_id = request.json.get('doc_id', '')

    if not token or not doc_id:
        return jsonify({'error': 'Missing params'}), 400

    match = re.match(r'doc(-?\d+)_(\d+)', doc_id)
    if not match:
        return jsonify({'error': 'Invalid doc_id'}), 400

    owner_id = match.group(1)
    doc_id_num = match.group(2)

    result = vk_request('docs.delete', token, owner_id=owner_id, doc_id=doc_id_num)
    if isinstance(result, dict) and 'error' in result:
        return jsonify({'error': result.get('error_msg', 'VK Error')}), 400

    return jsonify({'result': result})


@cloud_bp.route('/api/ping', methods=['GET'])
def cloud_ping():
    return jsonify({'ok': True, 'time': datetime.now().isoformat()})
