import os
import re
import json
import random
import requests
import hashlib
import base64
from io import BytesIO
from datetime import datetime
from flask import Blueprint, render_template_string, request, jsonify, Response, session
from werkzeug.utils import secure_filename

cloud_bp = Blueprint('cloud', __name__)

# === CONFIG ===
VK_API = "https://api.vk.com/method"
API_VERSION = "5.199"

# Kate Mobile Client Headers & Official UA to bypass VK blocks and restrictions
KATE_HEADERS = {
    'User-Agent': 'KateMobileAndroid/108 lite-armeabi-v7a (Android 13; SDK 33; arm64-v8a; Xiaomi Redmi Note 10; ru)',
    'Accept-Language': 'ru,en',
    'Connection': 'keep-alive'
}

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

def get_cloud_key(vk_id):
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

# --- CLOUD TITLE OBFUSCATION HELPERS ---
def encode_cloud_title(orig_name, file_type):
    # Map types to short markers: photo -> p, video -> v, audio -> a, doc -> d
    type_map = {'photo': 'p', 'video': 'v', 'audio': 'a', 'doc': 'd'}
    t_char = type_map.get(file_type, 'd')
    b64_name = base64.urlsafe_b64encode(orig_name.encode('utf-8')).decode('utf-8').rstrip('=')
    return f"cl_{t_char}_{b64_name}.doc"

def decode_cloud_title(title):
    if not (title.startswith('cl_') and title.endswith('.doc')):
        return None
    try:
        parts = title[3:-4].split('_', 1)
        if len(parts) != 2:
            return None
        t_char, b64_name = parts
        type_map = {'p': 'photo', 'v': 'video', 'a': 'audio', 'd': 'doc'}
        file_type = type_map.get(t_char, 'doc')
        # Add padding back
        padding = '=' * (4 - len(b64_name) % 4)
        orig_name = base64.urlsafe_b64decode(b64_name + padding).decode('utf-8')
        return orig_name, file_type
    except Exception:
        return None


# === HTML TEMPLATE ===
CLOUD_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>☁️ VK Tsuyu Cloud</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#000;color:#fff;height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased}
.app{height:100vh;display:flex;flex-direction:column;position:relative;overflow:hidden}

/* Header */
.header{height:56px;background:#0d0d0d;display:flex;align-items:center;padding:0 12px;border-bottom:1px solid #1c1c1c;flex-shrink:0;justify-content:space-between}
.header-title{font-size:18px;font-weight:900;letter-spacing:0.8px;color:#fff}
.header-subtitle{font-size:11px;color:#8e8e93}
.header-back{width:40px;height:40px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%;background:rgba(255,255,255,0.1);color:#fff;flex-shrink:0}
.header-back svg{width:22px;height:22px;stroke:#fff;stroke-width:2.5px;fill:none}
.header-back:active{background:rgba(255,255,255,0.25)}
.header-actions{display:flex;gap:8px;align-items:center}
.header-btn{width:38px;height:38px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;color:#fff;background:rgba(255,255,255,0.08);border:none;outline:none}
.header-btn:active{background:rgba(255,255,255,0.2)}

/* Storage bar */
.storage-bar{padding:12px 16px;background:#0d0d0d;border-bottom:1px solid #1c1c1c}
.storage-info{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.storage-label{font-size:13px;color:#8e8e93}
.storage-used{font-size:13px;font-weight:600;color:#fff}
.storage-track{height:6px;background:#1c1c1e;border-radius:3px;overflow:hidden}
.storage-fill{height:100%;background:#0a84ff;border-radius:3px;transition:width 0.3s ease;width:0%}

/* Horizontal Category Tabs */
.tabs-container{display:flex;gap:8px;padding:10px 16px;background:#0d0d0d;border-bottom:1px solid #1c1c1c;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch;flex-shrink:0}
.tabs-container::-webkit-scrollbar{display:none}
.tab-item{padding:8px 16px;border-radius:20px;background:#1c1c1e;color:#8e8e93;font-size:13px;font-weight:600;white-space:nowrap;cursor:pointer;transition:all 0.2s ease}
.tab-item.active{background:#0a84ff;color:#fff}

/* Upload zone */
.upload-zone{margin:12px 16px;padding:20px;border:2px dashed #2c2c2e;border-radius:16px;text-align:center;cursor:pointer;transition:all 0.2s;background:#0d0d0d;flex-shrink:0}
.upload-zone:active{background:#1c1c1e;border-color:#0a84ff}
.upload-zone.dragover{background:#1c1c1e;border-color:#0a84ff}
.upload-icon{width:40px;height:40px;margin:0 auto 8px;color:#8e8e93}
.upload-text{font-size:13px;color:#8e8e93;line-height:1.4}
.upload-text b{color:#fff}

/* File grid */
.file-grid{flex:1;overflow-y:auto;padding:12px 16px 20px;display:grid;grid-template-columns:repeat(3,1fr);gap:10px;-webkit-overflow-scrolling:touch}
.file-item{position:relative;background:#141416;border-radius:14px;overflow:hidden;border:1px solid #1c1c1c;cursor:pointer;transition:transform 0.15s,opacity 0.15s;display:flex;flex-direction:column}
.file-item:active{transform:scale(0.95);opacity:0.8}
.file-thumb-container{width:100%;aspect-ratio:1;position:relative;background:#1c1c1e;display:flex;align-items:center;justify-content:center;overflow:hidden}
.file-thumb{width:100%;height:100%;object-fit:cover;display:block}

/* Micro decryption loading state inside item */
.file-item.decrypting .file-thumb-container::after{content:'';position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center}
.file-item.decrypting .file-thumb-container::before{content:'';position:absolute;z-index:2;width:20px;height:20px;border:2px solid #333;border-top-color:#0a84ff;border-radius:50%;animation:spin 0.6s linear infinite}

.file-thumb svg{width:32px;height:32px;color:#8e8e93}
.file-info{padding:8px 10px;background:#141416}
.file-name{font-size:11px;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px}
.file-meta{font-size:10px;color:#666;display:flex;justify-content:space-between}
.file-size{color:#8e8e93}

/* Badges */
.file-badge{position:absolute;top:6px;right:6px;background:rgba(0,0,0,0.75);color:#fff;font-size:9px;font-weight:700;padding:2px 6px;border-radius:6px;text-transform:uppercase;letter-spacing:0.5px;z-index:5}
.file-badge.photo{background:rgba(10,132,255,0.85)}
.file-badge.video{background:rgba(255,59,48,0.85)}
.file-badge.audio{background:rgba(52,199,89,0.85)}
.file-badge.doc{background:rgba(175,82,222,0.85)}

/* Upload progress toast */
.upload-toast{position:fixed;top:60px;left:50%;transform:translateX(-50%);background:rgba(28,28,30,0.95);border:1px solid #3a3a3c;color:#fff;padding:8px 16px;border-radius:20px;font-size:13px;font-weight:500;z-index:900;display:flex;align-items:center;gap:10px;box-shadow:0 4px 16px rgba(0,0,0,0.5)}
.upload-toast.hidden{display:none}
.loader{border:2px solid #333;border-top:2px solid #fff;border-radius:50%;width:14px;height:14px;animation:spin 0.6s linear infinite;display:inline-block;vertical-align:middle;margin-right:6px}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}

/* Action sheet */
.action-sheet{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:500;display:flex;flex-direction:column;justify-content:flex-end}
.action-sheet-content{background:#1c1c1e;border-top-left-radius:20px;border-top-right-radius:20px;padding:16px;display:flex;flex-direction:column;gap:8px}
.action-sheet-item{padding:14px 16px;border-radius:12px;background:#2c2c2e;color:#fff;font-size:15px;font-weight:500;display:flex;align-items:center;gap:12px;cursor:pointer}
.action-sheet-item.danger{color:#ff3b30}
.action-sheet-item svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:2}

/* Modal */
.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.85);display:flex;align-items:center;justify-content:center;z-index:600;padding:20px}
.modal-content{background:#161616;border-radius:20px;padding:24px;width:100%;max-width:380px;border:1px solid #282828}
.modal-title{font-size:18px;font-weight:600;margin-bottom:10px;color:#fff}
.modal-text{font-size:13px;color:#aaa;margin-bottom:20px;line-height:1.5}
.btn{width:100%;padding:14px;border:none;border-radius:14px;background:#fff;color:#000;font-size:16px;font-weight:600;cursor:pointer;margin-bottom:8px;transition:all 0.1s}
.btn:active{transform:scale(0.97);opacity:.85}
.btn-secondary{background:transparent;color:#fff;border:1px solid #333}
.btn-danger{background:#ff3b30;color:#fff}

/* Empty state */
.empty-state{text-align:center;padding:60px 20px;color:#666;width:100%}
.empty-state svg{width:64px;height:64px;color:#333;margin-bottom:16px;display:block;margin-left:auto;margin-right:auto}
.empty-title{font-size:16px;font-weight:600;color:#8e8e93;margin-bottom:8px}
.empty-text{font-size:13px;color:#666;line-height:1.5}

/* Preview modal */
.preview-modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:700;display:flex;flex-direction:column;opacity:0;pointer-events:none;transition:opacity 0.2s ease}
.preview-modal.active{opacity:1;pointer-events:auto}
.preview-header{height:56px;background:#0d0d0d;display:flex;align-items:center;padding:0 12px;border-bottom:1px solid #1c1c1c;flex-shrink:0;justify-content:space-between}
.preview-body{flex:1;display:flex;align-items:center;justify-content:center;padding:20px;overflow:hidden}
.preview-body img{max-width:100%;max-height:100%;object-fit:contain;border-radius:8px}
.preview-body video{max-width:100%;max-height:100%;border-radius:8px}
.preview-body audio{width:100%;max-width:400px}
.preview-filename{color:#fff;font-size:14px;font-weight:600;flex:1;text-align:center;padding:0 12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Key box */
.key-box{background:#0a0a0a;border:1px solid #222;padding:10px;border-radius:10px;font-family:monospace;font-size:11px;color:#34c759;word-break:break-all;max-height:80px;overflow-y:auto;margin-top:4px}
.warning-box{background:rgba(255,59,48,0.1);border:1px solid rgba(255,59,48,0.3);color:#ff3b30;padding:10px;border-radius:10px;font-size:12px;margin-bottom:14px;line-height:1.4}

.hidden{display:none!important}
</style>
</head>
<body>
<div class="app">

<!-- Upload Toast -->
<div class="upload-toast hidden" id="uploadToast">
<span class="loader"></span>
<span id="uploadToastText">Загрузка...</span>
</div>

<!-- Header -->
<div class="header">
<div style="display:flex;align-items:center;gap:10px">
<div class="header-back" onclick="goBack()">
<svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
</div>
<div>
<div class="header-title">☁️ VK Tsuyu Cloud</div>
<div class="header-subtitle" id="storageSubtitle">Бесконечное облачное хранилище</div>
</div>
</div>
<div class="header-actions">
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
<div class="storage-label">Использовано</div>
<div class="storage-used" id="storageUsed">0 файлов</div>
</div>
<div class="storage-track">
<div class="storage-fill" id="storageFill" style="width:100%"></div>
</div>
</div>

<!-- Navigation tabs for Categories -->
<div class="tabs-container" id="categoryTabs">
<div class="tab-item active" data-category="photo" onclick="switchCategory('photo')">📸 Фото</div>
<div class="tab-item" data-category="video" onclick="switchCategory('video')">🎬 Видео</div>
<div class="tab-item" data-category="audio" onclick="switchCategory('audio')">🎵 Музыка</div>
<div class="tab-item" data-category="doc" onclick="switchCategory('doc')">📁 Файлы</div>
</div>

<!-- Upload Zone -->
<div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
<div class="upload-icon">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
</div>
<div class="upload-text">
<b>Нажмите или перетащите файлы</b><br>
Все загружаемые файлы автоматически шифруются
</div>
</div>

<input type="file" class="hidden" id="fileInput" multiple accept="image/*,video/*,audio/*,*/*" onchange="handleFiles(event)">

<!-- File Grid -->
<div class="file-grid" id="fileGrid"></div>

<!-- Empty State -->
<div class="empty-state hidden" id="emptyState">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
<div class="empty-title">В этой категории пусто</div>
<div class="empty-text">Загрузите файлы, и они появятся здесь</div>
</div>

<!-- Preview Modal -->
<div class="preview-modal" id="previewModal" onclick="closePreview(event)">
<div class="preview-header" onclick="event.stopPropagation()">
<div class="header-back" onclick="closePreview()">
<svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
</div>
<div class="preview-filename" id="previewFilename">Файл</div>
<button class="header-btn" onclick="downloadCurrentFile()" title="Скачать">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
</button>
</div>
<div class="preview-body" id="previewBody" onclick="event.stopPropagation()"></div>
</div>

<!-- Action Sheet (Context actions) -->
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
<div class="action-sheet-item danger" onclick="deleteSelectedFile()">
<svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
Удалить
</div>
<div class="action-sheet-item" style="justify-content:center;color:#888" onclick="closeActionSheet()">Отмена</div>
</div>
</div>

<!-- Key Modal -->
<div class="modal hidden" id="keyModal">
<div class="modal-content">
<div class="modal-title">🔐 Ключ облака</div>
<div class="warning-box">
Этот ключ шифрования используется для безопасной расшифровки ваших медиафайлов прямо в браузере.
</div>
<div class="modal-text" style="margin-bottom:4px">Ваш зашифрованный ключ:</div>
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
let selectedFile = null;
let currentPreviewFile = null;

// Decryption cache storage
const decryptionCache = {}; // doc_id -> { blobUrl, blob }
let decryptingQueue = [];
let isDecrypting = false;

function showToast(text) {
    const t = document.getElementById('uploadToast');
    document.getElementById('uploadToastText').textContent = text;
    t.classList.remove('hidden');
}
function hideToast() { document.getElementById('uploadToast').classList.add('hidden'); }

function goBack() { window.location.href = '/'; }

async function initCloud() {
    if (!token) { alert('Сначала войдите в систему'); goBack(); return; }

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
    showToast('Синхронизация с облаком...');
    try {
        const res = await fetch('/cloud/api/files', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({token})
        });
        const data = await res.json();
        filesData = data.files || [];
        renderFiles();
    } catch(e) { console.error(e); }
    hideToast();
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
    if (bytes < 1024*1024*1024) return (bytes/(1024*1024)).toFixed(1) + ' MB';
    return (bytes/(1024*1024*1024)).toFixed(1) + ' GB';
}

function switchCategory(cat) {
    currentCategory = cat;
    document.querySelectorAll('.tab-item').forEach(el => {
        el.classList.toggle('active', el.dataset.category === cat);
    });
    renderFiles();
}

// RENDER FILES AND TRIGGER AUTO DECRYPTION
function renderFiles() {
    const grid = document.getElementById('fileGrid');
    const empty = document.getElementById('emptyState');
    const usedLabel = document.getElementById('storageUsed');

    grid.innerHTML = '';

    // Filter current category
    const filtered = filesData.filter(f => f.type === currentCategory);

    usedLabel.textContent = filtered.length + ' файлов';

    if (filtered.length === 0) {
        empty.classList.remove('hidden');
        return;
    }

    empty.classList.add('hidden');

    // Reset decryption queue
    decryptingQueue = [];

    for (const f of filtered) {
        const div = document.createElement('div');
        div.className = 'file-item';
        div.id = `item_${f.doc_id}`;
        div.dataset.id = f.doc_id;

        // Visual placeholder structure
        div.innerHTML = `
            <div class="file-thumb-container">
                <div class="file-thumb">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M12 15V3m0 12l-4-4m4 4l4-4M2 17l.621 2.485A2 2 0 004.561 21h14.878a2 2 0 001.94-1.515L22 17"/>
                    </svg>
                </div>
            </div>
            <div class="file-badge ${f.type}">${f.type}</div>
            <div class="file-info">
                <div class="file-name">${escapeHtml(f.name)}</div>
                <div class="file-meta">
                    <span class="file-size">${formatSize(f.size)}</span>
                </div>
            </div>
        `;

        // Interaction handlers
        div.onclick = () => openFile(f);
        div.oncontextmenu = (e) => { e.preventDefault(); showActionSheet(f); };

        grid.appendChild(div);

        // Check if item decryption is cached, otherwise add to background decryption queue
        if (decryptionCache[f.doc_id]) {
            applyDecryptedPreview(f.doc_id, f.type);
        } else {
            decryptingQueue.push({
                doc_id: f.doc_id,
                url: f.url,
                mime: f.mime,
                type: f.type,
                name: f.name
            });
        }
    }

    // Process immediate auto-decryption on-the-fly!
    if (decryptingQueue.length > 0) {
        startBackgroundDecryption();
    }
}

// Background Decryptor Loop
async function startBackgroundDecryption() {
    if (isDecrypting) return;
    isDecrypting = true;

    while (decryptingQueue.length > 0) {
        const task = decryptingQueue.shift();
        const itemEl = document.getElementById(`item_${task.doc_id}`);
        if (!itemEl) continue; // Category might have switched

        itemEl.classList.add('decrypting');

        try {
            const resp = await fetch('/cloud/api/download?url=' + encodeURIComponent(task.url));
            if (!resp.ok) throw new Error("Load failed");
            const encBuf = await resp.arrayBuffer();
            const decBuf = await decryptAESGCM(cloudKey, encBuf);
            const blob = new Blob([decBuf], {type: task.mime || 'application/octet-stream'});
            const blobUrl = URL.createObjectURL(blob);

            decryptionCache[task.doc_id] = { blobUrl, blob };
            applyDecryptedPreview(task.doc_id, task.type);
        } catch (e) {
            console.error("Auto decrypt error for:", task.name, e);
        } finally {
            itemEl.classList.remove('decrypting');
        }
    }
    isDecrypting = false;
}

function applyDecryptedPreview(doc_id, type) {
    const itemEl = document.getElementById(`item_${doc_id}`);
    if (!itemEl) return;

    const cache = decryptionCache[doc_id];
    if (!cache) return;

    const container = itemEl.querySelector('.file-thumb-container');
    if (!container) return;

    if (type === 'photo') {
        container.innerHTML = `<img class="file-thumb" src="${cache.blobUrl}">`;
    } else if (type === 'video') {
        container.innerHTML = `
            <div class="file-thumb video" style="position:relative;width:100%;height:100%">
                <video src="${cache.blobUrl}" muted loop playsinline autoplay style="width:100%;height:100%;object-fit:cover"></video>
            </div>
        `;
    } else if (type === 'audio') {
        container.innerHTML = `
            <div class="file-thumb audio">
                <svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="file-thumb doc">
                <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
        `;
    }
}

function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

async function handleFiles(e) {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    for (const file of files) {
        await uploadFile(file);
    }
    e.target.value = '';
    await loadFiles();
}

async function uploadFile(file) {
    showToast('Шифрование ' + file.name + '...');

    try {
        const fileBuf = await file.arrayBuffer();
        const encBuf = await encryptAESGCM(cloudKey, fileBuf);
        const encBlob = new Blob([encBuf], {type: 'application/octet-stream'});

        showToast('Загрузка в ВК...');

        const formData = new FormData();
        formData.append('token', token);
        formData.append('file', encBlob, 'encrypted_payload.bin');
        formData.append('original_name', file.name);
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
        alert('Ошибка при шифровании или загрузке файла');
    }
}

// Click to Open (Instant playback/view using auto-decrypted cache)
function openFile(f) {
    const cached = decryptionCache[f.doc_id];
    if (!cached) {
        alert("Подождите, файл еще расшифровывается...");
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
        a.style.cssText = 'color:#0a84ff;font-size:16px;text-decoration:none;padding:20px;border:2px solid #0a84ff;border-radius:14px';
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
    if (!confirm('Удалить файл из облака?')) return;

    showToast('Удаление...');
    try {
        const res = await fetch('/cloud/api/delete', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({token, doc_id: selectedFile.doc_id})
        });
        const d = await res.json();
        if (d.error) {
            alert("Не удалось удалить из облака. Возможно, VK заблокировал удаление для этого токена.");
        } else {
            await loadFiles();
        }
    } catch(e) {}
    hideToast();
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
        for (const file of files) uploadFile(file);
        setTimeout(loadFiles, 2000);
    }
});

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


def get_cloud_key_data(vk_id):
    vk_id_str = str(vk_id)
    if FIREBASE_DB_URL:
        fb_data = firebase_get(f"cloud_keys/{vk_id_str}")
        if fb_data and isinstance(fb_data, dict) and 'cloud_key_enc' in fb_data:
            return fb_data
    local_data = load_cloud_keys()
    return local_data.get(f"cloud_{vk_id_str}")


@cloud_bp.route('/api/key/<vk_id>', methods=['POST'])
def save_cloud_key(vk_id):
    data = request.json
    now_iso = datetime.now().isoformat()
    if 'cloud_key_enc' in data:
        store_cloud_key(vk_id, {'cloud_key_enc': data['cloud_key_enc'], 'created_at': now_iso})
    return jsonify({'ok': True})


@cloud_bp.route('/api/files', methods=['POST'])
def cloud_files():
    """Reads docs from VK via Kate Mobile API and decodes obfuscated names"""
    token = request.json.get('token')
    if not token:
        return jsonify({'error': 'No token'}), 400

    result = vk_request('docs.get', token, count=2000, type=0)

    if isinstance(result, dict) and 'error' in result:
        return jsonify(result), 400

    files = []
    for item in result.get('items', []):
        title = item.get('title', '')

        # Attempt to decode obfuscated cloud title metadata
        decoded_meta = decode_cloud_title(title)
        if decoded_meta:
            orig_name, file_type = decoded_meta
            files.append({
                'doc_id': f"doc{item.get('owner_id')}_{item.get('id')}",
                'name': orig_name,
                'url': item.get('url', ''),
                'size': item.get('size', 0),
                'mime': item.get('type', 'application/octet-stream'),
                'date': datetime.fromtimestamp(item.get('date', 0)).strftime('%d.%m.%Y') if item.get('date') else '',
                'type': file_type
            })
            continue

        # Backward compatibility fallback
        title_lower = title.lower()
        is_cloud = (title_lower.startswith('cloud_') and title_lower.endswith('.doc')) or \
                   title_lower.endswith('.cimg.doc') or title_lower.endswith('.cvid.doc') or \
                   title_lower.endswith('.caud.doc') or title_lower.endswith('.cld.doc')

        if is_cloud:
            orig_name = title
            if orig_name.endswith('.doc'):
                orig_name = orig_name[:-4]  # Correct Python slice! (Replaces JS error)

            # Guess visual category
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
                'url': item.get('url', ''),
                'size': item.get('size', 0),
                'mime': item.get('type', 'application/octet-stream'),
                'date': datetime.fromtimestamp(item.get('date', 0)).strftime('%d.%m.%Y') if item.get('date') else '',
                'type': file_type
            })

    return jsonify({'files': files})


@cloud_bp.route('/api/upload', methods=['POST'])
def cloud_upload():
    """Uploads encrypted file using Kate Mobile signature and returns formatted target"""
    token = request.form.get('token')
    file = request.files.get('file')
    original_name = request.form.get('original_name', 'encrypted_file')

    if not file or not token:
        return jsonify({'error': 'Missing file or token'}), 400

    # Get upload server
    upload_server = vk_request('docs.getMessagesUploadServer', token, type='doc', peer_id=0)
    if isinstance(upload_server, dict) and 'error' in upload_server:
        return jsonify(upload_server), 400

    upload_url = upload_server.get('upload_url')
    file_bytes = file.read()
    files = {'file': (secure_filename(file.filename), BytesIO(file_bytes), 'application/octet-stream')}
    
    upload_resp = get_session().post(upload_url, files=files, headers=KATE_HEADERS, timeout=60).json()

    # Determine type of the file for category routing
    file_type = 'doc'
    original_name_lower = original_name.lower()
    if original_name_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
        file_type = 'photo'
    elif original_name_lower.endswith(('.mp4', '.mov', '.avi', '.mkv', '.3gp')):
        file_type = 'video'
    elif original_name_lower.endswith(('.mp3', '.ogg', '.wav', '.m4a')):
        file_type = 'audio'

    # Secure title with obfuscated payload format to bypass blocks
    safe_title = encode_cloud_title(original_name, file_type)

    save_result = vk_request('docs.save', token, 
        file=upload_resp.get('file'), 
        title=safe_title
    )

    attachment = extract_doc_attachment(save_result)
    if attachment:
        return jsonify({'ok': True, 'attachment': attachment})

    return jsonify({'error': 'Upload failed', 'details': save_result}), 400


@cloud_bp.route('/api/download')
def cloud_download():
    """Proxy file downloading through Kate Mobile User Agent to dodge restriction policies"""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL'}), 400
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
