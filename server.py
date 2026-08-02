import os
import re
import json
import base64
import hashlib
import requests
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, Response

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', os.urandom(32).hex())

VK_API = "https://api.vk.com/method"
API_VERSION = "5.199"

FIREBASE_DB_URL = os.environ.get('FIREBASE_DB_URL', '')
FIREBASE_API_KEY = os.environ.get('FIREBASE_API_KEY', '')


def firebase_get(path):
    """GET data from Firebase Realtime Database"""
    if not FIREBASE_DB_URL:
        return None
    url = f"{FIREBASE_DB_URL}/{path}.json"
    try:
        resp = requests.get(url, timeout=10)
        return resp.json()
    except Exception:
        return None


def firebase_put(path, data):
    """PUT data to Firebase Realtime Database"""
    if not FIREBASE_DB_URL:
        return False
    url = f"{FIREBASE_DB_URL}/{path}.json"
    try:
        resp = requests.put(url, json=data, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def vk_request(method, token, **params):
    """Proxy request to VK API"""
    params['access_token'] = token
    params['v'] = API_VERSION
    try:
        resp = requests.get(f"{VK_API}/{method}", params=params, timeout=30)
        data = resp.json()
        return data.get('response', data.get('error'))
    except Exception as e:
        return {'error': str(e)}


HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>VK Client - Instant E2EE</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#000;color:#fff;height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased}
.app{height:100vh;display:flex;flex-direction:column;position:relative}

/* Login */
.login-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;z-index:100;animation:fadeIn .2s ease}
.login-screen h1{font-size:26px;margin-bottom:6px;font-weight:700;color:#fff}
.login-screen p{color:#888;margin-bottom:24px;font-size:13px;text-align:center;max-width:320px}
.badge-e2e{background:#1a1a1a;color:#fff;border:1px solid #333;padding:5px 12px;border-radius:14px;font-size:12px;font-weight:600;margin-bottom:20px;display:inline-flex;align-items:center;gap:6px}
.token-input,.pass-input{width:100%;max-width:360px;padding:14px 16px;border:none;border-radius:14px;background:#161616;color:#fff;font-size:15px;margin-bottom:12px;outline:none;border:1px solid #2c2c2c;transition:border-color .2s}
.token-input:focus,.pass-input:focus{border-color:#555}
.token-input::placeholder,.pass-input::placeholder{color:#666}
.btn{width:100%;max-width:360px;padding:14px;border:none;border-radius:14px;background:#fff;color:#000;font-size:16px;font-weight:600;cursor:pointer;margin-bottom:8px;transition:transform .1s ease, opacity .1s ease}
.btn:active{transform:scale(.98);opacity:.9}
.btn-secondary{background:transparent;color:#fff;border:1px solid #333}
.btn-danger{background:#e53935;color:#fff}
.btn-green{background:#fff;color:#000}

/* Header */
.header{height:52px;background:#0d0d0d;display:flex;align-items:center;padding:0 12px;border-bottom:1px solid #1c1c1c;flex-shrink:0;z-index:5}
.header-back{width:36px;height:36px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%;margin-right:4px}
.header-back:active{background:#222}
.header-avatar{width:34px;height:34px;border-radius:50%;object-fit:cover;margin-right:10px;background:#222}
.header-info{flex:1;min-width:0}
.header-title{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.header-subtitle{font-size:12px;color:#888;display:flex;align-items:center;gap:4px}
.header-actions{display:flex;gap:4px}
.header-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;color:#777;transition:color .2s}
.header-btn.active{color:#fff}

/* Dialogs */
.dialogs-screen{flex:1;display:flex;flex-direction:column;overflow:hidden}
.dialogs-list{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.dialog{display:flex;align-items:center;padding:12px 14px;cursor:pointer;border-bottom:1px solid #111;transition:background .15s}
.dialog:active{background:#111}
.dialog-avatar{width:50px;height:50px;border-radius:50%;object-fit:cover;margin-right:12px;flex-shrink:0;background:#222}
.dialog-info{flex:1;min-width:0}
.dialog-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px}
.dialog-name{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;margin-right:8px}
.dialog-time{font-size:11px;color:#666;flex-shrink:0}
.dialog-bottom{display:flex;align-items:center;gap:6px}
.dialog-preview{font-size:13px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.dialog-unread{min-width:18px;height:18px;border-radius:50%;background:#fff;color:#000;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;padding:0 5px;flex-shrink:0}

/* Chat Screen */
.chat-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;z-index:10;transform:translateX(100%);transition:transform .22s cubic-bezier(0.2, 0.9, 0.1, 1)}
.chat-screen.active{transform:translateX(0)}
.messages{flex:1;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:6px;-webkit-overflow-scrolling:touch}

/* Message Item & Swiping */
.msg-wrapper{position:relative;width:100%;display:flex;flex-direction:column;user-select:none;-webkit-user-select:none}
.msg-reply-indicator{position:absolute;left:-36px;top:50%;transform:translateY(-50%);width:26px;height:26px;border-radius:50%;background:#333;display:flex;align-items:center;justify-content:center;color:#fff;opacity:0;transition:opacity .15s}
.msg{max-width:82%;padding:8px 12px;border-radius:16px;font-size:14px;line-height:1.4;word-wrap:break-word;position:relative;background:#1c1c1e;color:#fff;transition:transform .08s linear}
.msg-in{align-self:flex-start;background:#1c1c1e;border-bottom-left-radius:4px}
.msg-out{align-self:flex-end;background:#2c2c2e;border-bottom-right-radius:4px}

/* Standard Colors - NO GREEN TINT */
.msg-author{font-size:11px;color:#aaa;font-weight:600;margin-bottom:3px}
.msg-text{color:#fff;word-break:break-word}
.msg-time{font-size:10px;color:#888;margin-top:4px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:3px}

/* Replying snippet inside message */
.msg-reply-quote{background:rgba(255,255,255,.08);border-left:3px solid #fff;padding:4px 8px;border-radius:4px;margin-bottom:6px;font-size:12px;cursor:pointer}
.msg-reply-author{font-weight:600;color:#aaa;margin-bottom:1px}
.msg-reply-text{color:#ddd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Photos & Attachments */
.msg-photo{max-width:100%;border-radius:12px;margin-top:6px;display:block;max-height:280px;object-fit:cover;cursor:pointer;background:#111}
.msg-file{background:rgba(255,255,255,.05);padding:10px;border-radius:10px;margin-top:6px;display:flex;align-items:center;gap:10px}
.msg-file-icon{font-size:20px}
.msg-file-info{flex:1;min-width:0}
.msg-file-name{font-size:13px;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.msg-file-size{font-size:11px;color:#888}

/* TG Style Video Note (.mec) - "Кружочек" */
.video-note-container{position:relative;width:190px;height:190px;border-radius:50%;overflow:hidden;margin-top:4px;background:#000;box-shadow:0 4px 12px rgba(0,0,0,.5);border:2px solid rgba(255,255,255,.15);cursor:pointer}
.video-note-player{width:100%;height:100%;object-fit:cover;border-radius:50%;display:block}
.video-note-overlay{position:absolute;top:0;left:0;width:100%;height:100%;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.3);transition:opacity .2s}
.video-note-overlay.playing{opacity:0}
.video-note-overlay.playing:hover{opacity:1}
.video-note-btn{width:44px;height:44px;border-radius:50%;background:rgba(0,0,0,.6);color:#fff;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px)}

/* TG Style Voice Message (.meg) - "Голосовое" */
.voice-message-container{display:flex;align-items:center;gap:10px;padding:6px 2px;min-width:210px}
.voice-play-btn{width:36px;height:36px;border-radius:50%;background:#fff;color:#000;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:transform .1s}
.voice-play-btn:active{transform:scale(.92)}
.voice-waveform-wrap{flex:1;display:flex;flex-direction:column;gap:3px}
.voice-waveform{display:flex;align-items:center;gap:2px;height:24px;cursor:pointer;width:100%}
.voice-bar{flex:1;background:rgba(255,255,255,.3);border-radius:2px;transition:height .15s ease, background .15s ease}
.voice-bar.played{background:#fff}
.voice-meta{display:flex;justify-content:space-between;font-size:11px;color:#aaa}

/* Reply Preview Bar */
.reply-banner{background:#111;border-top:1px solid #1c1c1c;padding:6px 12px;display:flex;align-items:center;justify-content:space-between;animation:slideUp .18s ease}
.reply-banner-info{border-left:2px solid #fff;padding-left:8px;min-width:0;flex:1}
.reply-banner-title{font-size:12px;font-weight:600;color:#fff}
.reply-banner-text{font-size:12px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.reply-banner-close{width:28px;height:28px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#888}

/* Edit Banner */
.edit-banner{background:#111;border-top:1px solid #1c1c1c;padding:6px 12px;display:flex;align-items:center;justify-content:space-between;animation:slideUp .18s ease}
.edit-banner-title{font-size:12px;font-weight:600;color:#fff;display:flex;align-items:center;gap:4px}

/* Input Area */
.input-area{min-height:54px;background:#0d0d0d;border-top:1px solid #1a1a1a;display:flex;align-items:flex-end;padding:8px;gap:6px;position:relative}
.input-btn{width:38px;height:38px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;flex-shrink:0;color:#aaa;transition:background .15s, color .15s}
.input-btn:active{background:#222;color:#fff}
.message-input{flex:1;padding:10px 14px;border:none;border-radius:20px;background:#1c1c1e;color:#fff;font-size:14px;outline:none;resize:none;max-height:100px;font-family:inherit;line-height:1.4;border:1px solid #2a2a2c}
.send-btn{width:38px;height:38px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;border:none;color:#000;transition:transform .15s ease, background .15s}
.send-btn:active{transform:scale(.92)}
.send-btn:disabled{background:#222;color:#555}

/* Recording Overlays */
.recording-bar{position:absolute;top:0;left:0;width:100%;height:100%;background:#0d0d0d;display:flex;align-items:center;padding:0 12px;gap:12px;z-index:20;animation:fadeIn .15s ease}
.recording-dot{width:12px;height:12px;border-radius:50%;background:#e53935;animation:pulseRed 1s infinite}
.recording-timer{font-size:15px;font-weight:600;color:#fff;flex:1}
.recording-cancel{color:#e53935;cursor:pointer;font-size:14px;font-weight:500;padding:8px}

/* Video Note Recorder Modal */
.video-note-modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.92);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:300;animation:fadeIn .18s ease}
.vnote-preview-wrap{position:relative;width:260px;height:260px;border-radius:50%;overflow:hidden;border:3px solid #fff;box-shadow:0 0 30px rgba(255,255,255,.2);margin-bottom:30px;background:#111}
.vnote-preview-video{width:100%;height:100%;object-fit:cover;transform:scaleX(-1)}
.vnote-controls{display:flex;align-items:center;gap:24px}
.vnote-btn{width:56px;height:56px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:transform .15s}
.vnote-btn:active{transform:scale(.9)}
.vnote-btn-cancel{background:#222;color:#fff}
.vnote-btn-rec{background:#e53935;color:#fff}
.vnote-btn-send{background:#fff;color:#000}
.vnote-timer{font-size:18px;font-weight:700;color:#fff;margin-bottom:20px;letter-spacing:1px}

/* Bottom nav */
.bottom-nav{height:50px;background:#0d0d0d;border-top:1px solid #1a1a1a;display:flex;justify-content:space-around;align-items:center;flex-shrink:0}
.nav-item{flex:1;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;cursor:pointer;color:#666}
.nav-item.active{color:#fff}
.nav-item span{font-size:10px}

/* Modals & Context Action Sheets */
.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.85);display:flex;align-items:center;justify-content:center;z-index:250;padding:20px;animation:fadeIn .15s ease}
.modal-content{background:#161616;border-radius:20px;padding:22px;width:100%;max-width:360px;border:1px solid #282828}
.modal-title{font-size:18px;font-weight:600;margin-bottom:10px;color:#fff}
.modal-text{font-size:13px;color:#aaa;margin-bottom:16px;line-height:1.5}

.context-sheet{position:fixed;bottom:0;left:0;width:100%;background:#161616;border-top-left-radius:20px;border-top-right-radius:20px;padding:16px;z-index:220;border-top:1px solid #282828;animation:slideUp .2s ease}
.context-option{padding:14px 16px;display:flex;align-items:center;gap:12px;font-size:15px;color:#fff;cursor:pointer;border-radius:12px;transition:background .15s}
.context-option:active{background:#222}
.context-option.danger{color:#e53935}

/* Checkbox design */
.checkbox-row{display:flex;align-items:center;gap:10px;margin-bottom:20px;cursor:pointer;user-select:none}
.checkbox-box{width:20px;height:20px;border-radius:6px;border:2px solid #555;display:flex;align-items:center;justify-content:center;transition:all .15s}
.checkbox-row.active .checkbox-box{background:#fff;border-color:#fff;color:#000}

.file-input{display:none}
.hidden{display:none!important}
.loader{border:2px solid #333;border-top:2px solid #fff;border-radius:50%;width:16px;height:16px;animation:spin .8s linear infinite;display:inline-block;vertical-align:middle;margin-right:6px}

@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes slideUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
@keyframes pulseRed{0%{transform:scale(1);opacity:1}50%{transform:scale(1.3);opacity:.5}100%{transform:scale(1);opacity:1}}
</style>
</head>
<body>
<div class="app">

<!-- Login Screen -->
<div class="login-screen" id="loginScreen">
<h1>VK Client E2EE</h1>
<div class="badge-e2e">
<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
100% Client-Side Encryption
</div>
<p>Шифрование происходит локально на телефоне. Сервер не имеет доступа к вашим данным.</p>
<button class="btn btn-secondary" onclick="getToken()">1. Получить токен VK</button>
<input type="text" class="token-input" id="tokenUrl" placeholder="Вставьте ссылку с токеном...">
<input type="password" class="pass-input" id="password" placeholder="Пароль шифрования...">
<button class="btn" onclick="login()">Войти</button>
</div>

<!-- Setup Encryption Modal -->
<div class="modal hidden" id="setupModal">
<div class="modal-content">
<div class="modal-title">Генерация RSA/AES ключей</div>
<div class="modal-text" id="setupText">Генерируем ключи в вашем браузере... Приватный ключ шифруется локально на вашем устройстве.</div>
<button class="btn btn-green" id="setupBtn" onclick="setupEncryption()">Создать ключи на телефоне</button>
</div>
</div>

<!-- Dialogs Screen -->
<div class="dialogs-screen hidden" id="dialogsScreen">
<div class="header">
<img class="header-avatar" id="headerAvatar" src="" alt="">
<div class="header-info">
<div class="header-title" id="headerTitle">VK</div>
<div class="header-subtitle">
<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
Локальная защита
</div>
</div>
<div class="header-actions">
<div class="header-btn active" id="encryptBtn" onclick="toggleEncrypt()" title="Шифрование">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
</div>
</div>
</div>

<div class="dialogs-list" id="dialogsList"></div>

<div class="bottom-nav">
<div class="nav-item active" onclick="showDialogs()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
<span>Чаты</span>
</div>
<div class="nav-item" onclick="logout()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
<span>Выход</span>
</div>
</div>
</div>

<!-- Chat Screen -->
<div class="chat-screen" id="chatScreen">
<div class="header">
<div class="header-back" onclick="backToDialogs()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
</div>
<img class="header-avatar" id="chatAvatar" src="" alt="">
<div class="header-info">
<div class="header-title" id="chatTitle"></div>
<div class="header-subtitle" id="chatEncryptStatus">E2EE Ready</div>
</div>
</div>

<div class="messages" id="messages"></div>

<!-- Reply Banner -->
<div class="reply-banner hidden" id="replyBanner">
<div class="reply-banner-info">
<div class="reply-banner-title" id="replyAuthor">Ответ</div>
<div class="reply-banner-text" id="replySnippet">Сообщение</div>
</div>
<div class="reply-banner-close" onclick="cancelReply()">✕</div>
</div>

<!-- Edit Banner -->
<div class="edit-banner hidden" id="editBanner">
<div class="edit-banner-title">
<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
Редактирование
</div>
<div class="reply-banner-close" onclick="cancelEdit()">✕</div>
</div>

<!-- Input Area -->
<div class="input-area">
<div class="input-btn" onclick="document.getElementById('fileInput').click()" title="Прикрепить файл">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
</div>
<input type="file" class="file-input" id="fileInput" accept="image/*,video/*,*/*" onchange="handleFile(event)">

<textarea class="message-input" id="msgInput" placeholder="Сообщение..." rows="1" oninput="toggleInputIcons()"></textarea>

<!-- Video Note Toggle Icon -->
<div class="input-btn" id="videoNoteBtn" onclick="openVideoNoteRecorder()" title="Записать кружочек">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><polygon points="10 8 16 12 10 16 10 8"/></svg>
</div>

<!-- Voice Record Toggle Icon -->
<div class="input-btn" id="voiceBtn" onclick="startVoiceRecording()" title="Записать голосовое">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
</div>

<button class="send-btn hidden" id="sendBtn" onclick="sendMessage()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>

<!-- Voice Recording Bar -->
<div class="recording-bar hidden" id="voiceRecordingBar">
<div class="recording-dot"></div>
<div class="recording-timer" id="voiceTimer">0:00</div>
<div class="recording-cancel" onclick="cancelVoiceRecording()">Отмена</div>
<button class="send-btn" onclick="stopAndSendVoice()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>
</div>

</div>
</div>

<!-- Video Note Recorder Modal (TG Style "Кружочек") -->
<div class="video-note-modal hidden" id="videoNoteModal">
<div class="vnote-timer" id="vnoteTimer">0:00</div>
<div class="vnote-preview-wrap">
<video class="vnote-preview-video" id="vnoteVideo" autoplay playsinline muted></video>
</div>
<div class="vnote-controls">
<button class="vnote-btn vnote-btn-cancel" onclick="closeVideoNoteRecorder()">✕</button>
<button class="vnote-btn vnote-btn-rec" id="vnoteRecBtn" onclick="toggleVideoNoteRecord()">
<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="8"/></svg>
</button>
<button class="vnote-btn vnote-btn-send hidden" id="vnoteSendBtn" onclick="sendVideoNote()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>
</div>
</div>

<!-- Context Menu -->
<div class="modal hidden" id="contextModal" onclick="closeContextMenu()">
<div class="context-sheet" onclick="event.stopPropagation()">
<div class="context-option" onclick="replySelectedMessage()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>
Ответить
</div>
<div class="context-option hidden" id="contextEditOpt" onclick="editSelectedMessage()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
Редактировать
</div>
<div class="context-option danger" onclick="openDeleteModal()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
Удалить
</div>
</div>
</div>

<!-- Delete Message Modal -->
<div class="modal hidden" id="deleteModal">
<div class="modal-content">
<div class="modal-title">Удалить сообщение?</div>
<div class="modal-text">Выберите вариант удаления:</div>
<div class="checkbox-row active" id="deleteForBothRow" onclick="toggleDeleteCheckbox()">
<div class="checkbox-box" id="deleteCheckbox">✓</div>
<span style="font-size:14px">Удалить у обоих (до 24ч)</span>
</div>
<div style="display:flex;gap:10px">
<button class="btn btn-secondary" onclick="closeDeleteModal()">Отмена</button>
<button class="btn btn-danger" onclick="confirmDeleteMessage()">Удалить</button>
</div>
</div>
</div>

</div>

<script>
/* =========================================================================
   PURE CLIENT-SIDE E2EE ENGINE USING WEB CRYPTO API (subtle.crypto)
   ========================================================================= */

const ENCRYPT_PREFIX = "ENC2:";
let token = localStorage.getItem('vk_token');
let password = localStorage.getItem('vk_pass');
let currentPeer = null;
let currentUser = null;
let dialogsData = [];
let pollInterval = null;
let encryptionEnabled = true;
let myVkId = null;

let localKeyPair = null;
let peerKeysCache = {};
let decryptedCache = {};

let lastRenderedPeer = null;
let lastMessagesHash = "";

// Action State
let selectedMsg = null;
let replyingMsg = null;
let editingMsg = null;
let deleteForBoth = true;

// Media Recording State
let voiceRecorder = null;
let voiceChunks = [];
let voiceTimerInterval = null;
let voiceSeconds = 0;

let vnoteStream = null;
let vnoteRecorder = null;
let vnoteChunks = [];
let vnoteTimerInterval = null;
let vnoteSeconds = 0;

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

async function deriveMasterKey(pass, saltStr) {
    const enc = new TextEncoder();
    const keyMaterial = await window.crypto.subtle.importKey(
        "raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]
    );
    return await window.crypto.subtle.deriveKey(
        { name: "PBKDF2", salt: enc.encode(saltStr), iterations: 100000, hash: "SHA-256" },
        keyMaterial, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]
    );
}

async function encryptAESGCM(key, plainBuf) {
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, plainBuf);
    const combined = new Uint8Array(iv.byteLength + ciphertext.byteLength);
    combined.set(iv, 0);
    combined.set(new Uint8Array(ciphertext), iv.byteLength);
    return combined.buffer;
}

async function decryptAESGCM(key, combinedBuf) {
    const bytes = new Uint8Array(combinedBuf);
    const iv = bytes.slice(0, 12);
    const ciphertext = bytes.slice(12);
    return await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
}

async function initClientCrypto() {
    if (!myVkId || !password || !token) return false;
    const masterKey = await deriveMasterKey(password, myVkId + "_vk_e2ee_salt");
    const res = await fetch(`/api/keys/${myVkId}`);
    const stored = await res.json();
    
    if (stored && stored.public_key && stored.private_key_enc) {
        try {
            const privEncBuf = b64ToBuf(stored.private_key_enc);
            const privDecBuf = await decryptAESGCM(masterKey, privEncBuf);
            const privJwk = JSON.parse(new TextDecoder().decode(privDecBuf));
            const pubJwk = JSON.parse(stored.public_key);

            const publicKey = await window.crypto.subtle.importKey("jwk", pubJwk, { name: "RSA-OAEP", hash: "SHA-256" }, true, ["encrypt"]);
            const privateKey = await window.crypto.subtle.importKey("jwk", privJwk, { name: "RSA-OAEP", hash: "SHA-256" }, true, ["decrypt"]);
            localKeyPair = { publicKey, privateKey, pubJwkStr: stored.public_key };
            return true;
        } catch(e) {
            alert("Неверный пароль шифрования!");
            return false;
        }
    } else {
        const keyPair = await window.crypto.subtle.generateKey(
            { name: "RSA-OAEP", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
            true, ["encrypt", "decrypt"]
        );
        const pubJwk = await window.crypto.subtle.exportKey("jwk", keyPair.publicKey);
        const privJwk = await window.crypto.subtle.exportKey("jwk", keyPair.privateKey);
        const pubJwkStr = JSON.stringify(pubJwk);

        const privEncBuf = await encryptAESGCM(masterKey, new TextEncoder().encode(JSON.stringify(privJwk)));
        const privEncB64 = bufToB64(privEncBuf);

        await fetch(`/api/keys/${myVkId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ public_key: pubJwkStr, private_key_enc: privEncB64 })
        });

        localKeyPair = { publicKey: keyPair.publicKey, privateKey: keyPair.privateKey, pubJwkStr };
        return true;
    }
}

async function getPeerPubKey(peerId) {
    if (peerKeysCache[peerId]) return peerKeysCache[peerId];
    if (String(peerId) === String(myVkId)) {
        if (localKeyPair) {
            peerKeysCache[peerId] = localKeyPair.publicKey;
            return localKeyPair.publicKey;
        }
    }
    const res = await fetch(`/api/keys/${peerId}`);
    const stored = await res.json();
    if (stored && stored.public_key) {
        const pubJwk = JSON.parse(stored.public_key);
        const key = await window.crypto.subtle.importKey("jwk", pubJwk, { name: "RSA-OAEP", hash: "SHA-256" }, true, ["encrypt"]);
        peerKeysCache[peerId] = key;
        return key;
    }
    return null;
}

async function clientEncryptData(peerKey, plainBuf) {
    const sessionKey = await window.crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]);
    const encPayload = await encryptAESGCM(sessionKey, plainBuf);
    const rawSession = await window.crypto.subtle.exportKey("raw", sessionKey);

    const encKeyPeer = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, peerKey, rawSession);
    const encKeySelf = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, localKeyPair.publicKey, rawSession);

    return {
        k1: bufToB64(encKeyPeer),
        k2: bufToB64(encKeySelf),
        payload: bufToB64(encPayload)
    };
}

async function clientDecryptData(encObj) {
    if (!localKeyPair) return null;
    let rawSession = null;
    try {
        rawSession = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, localKeyPair.privateKey, b64ToBuf(encObj.k1));
    } catch(e) {
        try {
            rawSession = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, localKeyPair.privateKey, b64ToBuf(encObj.k2));
        } catch(e2) {
            return null;
        }
    }

    const sessionKey = await window.crypto.subtle.importKey("raw", rawSession, { name: "AES-GCM" }, false, ["decrypt"]);
    return await decryptAESGCM(sessionKey, b64ToBuf(encObj.payload));
}

/* =========================================================================
   APP & UI LOGIC
   ========================================================================= */

const AUTH_URL = 'https://oauth.vk.com/authorize?client_id=2685278&scope=messages,audio,photos,video,docs,notes,pages,status,wall,groups,email,stats,notifications,offline&redirect_uri=https://oauth.vk.com/blank.html&response_type=token';

function getToken() { window.open(AUTH_URL, '_blank'); }

async function login() {
    const url = document.getElementById('tokenUrl').value.trim();
    const pass = document.getElementById('password').value.trim();
    if (!url) { alert('Вставьте ссылку с токеном'); return; }
    if (!pass) { alert('Придумайте пароль для шифрования'); return; }

    const res = await fetch('/api/auth', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }

    token = data.token;
    currentUser = data.user;
    myVkId = data.user.id;
    password = pass;

    localStorage.setItem('vk_token', token);
    localStorage.setItem('vk_pass', pass);
    localStorage.setItem('vk_user', JSON.stringify(data.user));

    document.getElementById('loginScreen').classList.add('hidden');
    document.getElementById('setupModal').classList.remove('hidden');
}

async function setupEncryption() {
    document.getElementById('setupText').innerHTML = '<span class="loader"></span>Генерация ключей на телефоне...';
    document.getElementById('setupBtn').disabled = true;

    const ok = await initClientCrypto();
    if (ok) {
        document.getElementById('setupModal').classList.add('hidden');
        showDialogsScreen();
        loadDialogs();
        startPolling();
    } else {
        alert("Ошибка создания ключей!");
        document.getElementById('setupBtn').disabled = false;
    }
}

function showDialogsScreen() {
    document.getElementById('dialogsScreen').classList.remove('hidden');
    if (currentUser) {
        document.getElementById('headerAvatar').src = currentUser.photo || '';
        document.getElementById('headerTitle').textContent = currentUser.name || 'VK';
    }
}

async function loadDialogs() {
    const res = await fetch('/api/dialogs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) });
    const data = await res.json();
    if (data.error) return;
    dialogsData = data.dialogs;
    const list = document.getElementById('dialogsList'); list.innerHTML = '';
    
    for (let i = 0; i < data.dialogs.length; i++) {
        const d = data.dialogs[i];
        const div = document.createElement('div');
        div.className = 'dialog';
        div.onclick = () => openChat(i);
        const time = d.date ? new Date(d.date * 1000).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : '';
        
        let preview = d.last_message || '';
        if (preview.startsWith(ENCRYPT_PREFIX)) {
            preview = '🔒 Зашифрованное сообщение';
        }
        
        div.innerHTML = `<img class="dialog-avatar" src="${d.photo || 'https://vk.com/images/camera_100.png'}" onerror="this.src='https://vk.com/images/camera_100.png'"><div class="dialog-info"><div class="dialog-top"><div class="dialog-name">${escapeHtml(d.name)}</div><div class="dialog-time">${time}</div></div><div class="dialog-bottom"><div class="dialog-preview">${escapeHtml(preview)}</div>${d.unread > 0 ? `<div class="dialog-unread">${d.unread}</div>` : ''}</div></div>`;
        list.appendChild(div);
    }
}

async function openChat(index) {
    const d = dialogsData[index]; currentPeer = d.id;
    document.getElementById('chatTitle').textContent = d.name;
    document.getElementById('chatAvatar').src = d.photo || 'https://vk.com/images/camera_100.png';
    document.getElementById('chatScreen').classList.add('active');

    const peerKey = await getPeerPubKey(currentPeer);
    const status = document.getElementById('chatEncryptStatus');
    if (peerKey) {
        status.textContent = '🔒 Защищено (E2EE)';
        status.style.color = '#fff';
    } else {
        status.textContent = 'Обычный чат';
        status.style.color = '#888';
    }

    lastRenderedPeer = null;
    lastMessagesHash = "";
    cancelReply();
    cancelEdit();
    loadMessages();
}

function backToDialogs() {
    document.getElementById('chatScreen').classList.remove('active');
    currentPeer = null;
}

async function loadMessages() {
    if (!currentPeer) return;
    const res = await fetch('/api/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, peer_id: currentPeer }) });
    const data = await res.json();
    if (data.error || !data.messages) return;

    const msgs = data.messages.reverse();
    const currentHash = currentPeer + "_" + msgs.map(m => m.id + "_" + (m.text||'')).join("|");

    if (lastRenderedPeer === currentPeer && lastMessagesHash === currentHash) {
        return; // No change, don't wipe DOM!
    }

    lastRenderedPeer = currentPeer;
    lastMessagesHash = currentHash;

    const container = document.getElementById('messages');
    const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 120;

    container.innerHTML = '';
    for (const m of msgs) {
        renderMessageItemSync(container, m);
    }

    if (isAtBottom) {
        container.scrollTop = container.scrollHeight;
    }
}

function renderMessageItemSync(container, msg) {
    const wrapper = document.createElement('div');
    wrapper.className = 'msg-wrapper';

    const replyInd = document.createElement('div');
    replyInd.className = 'msg-reply-indicator';
    replyInd.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>`;
    wrapper.appendChild(replyInd);

    const div = document.createElement('div');
    const isEncrypted = msg.text && msg.text.startsWith(ENCRYPT_PREFIX);
    div.className = 'msg ' + (msg.out ? 'msg-out' : 'msg-in');
    div.id = 'msg-' + msg.id;

    let html = '';
    if (!msg.out && msg.name) html += `<div class="msg-author">${escapeHtml(msg.name)}</div>`;

    if (msg.reply_message) {
        const rm = msg.reply_message;
        const rName = rm.from_id === myVkId ? 'Вы' : (rm.name || 'Собеседник');
        let rText = rm.text || '';
        if (rText.startsWith(ENCRYPT_PREFIX)) rText = '🔒 Зашифрованное сообщение';
        html += `<div class="msg-reply-quote" onclick="scrollToMsg(${rm.id})"><div class="msg-reply-author">${escapeHtml(rName)}</div><div class="msg-reply-text">${escapeHtml(rText)}</div></div>`;
    }

    let displayText = msg.text || '';
    if (isEncrypted) {
        if (decryptedCache[msg.id]) {
            displayText = escapeHtml(decryptedCache[msg.id]);
        } else {
            displayText = '🔒 Расшифровка...';
            clientDecryptTextAsync(msg.id, msg.text);
        }
    } else {
        displayText = escapeHtml(displayText);
    }

    html += `<div class="msg-text" id="msg-text-${msg.id}">${displayText}</div>`;

    if (msg.attachments) {
        for (const a of msg.attachments) {
            if (a.type === 'photo') {
                const p = a.photo?.sizes?.find(s => s.type === 'x') || a.photo?.sizes?.[a.photo?.sizes?.length - 1];
                if (p) html += `<img class="msg-photo" src="${p.url}">`;
            }
            if (a.type === 'doc') {
                const doc = a.doc;
                const docId = `doc_${doc.owner_id}_${doc.id}`;
                const fileUrl = doc.url || '';
                
                if (doc.title && (doc.title.startsWith('enc_') || doc.ext === 'meow' || doc.ext === 'mur' || doc.ext === 'mec' || doc.ext === 'meg' || doc.ext === 'enc')) {
                    if (doc.ext === 'mec' || doc.title.includes('.mec')) {
                        html += `<div class="video-note-container" id="${docId}"><div class="video-note-overlay"><div class="loader"></div></div></div>`;
                    } else if (doc.ext === 'meg' || doc.title.includes('.meg')) {
                        html += `<div class="voice-message-container" id="${docId}"><div class="voice-play-btn"><span class="loader" style="margin:0;border-top-color:#000"></span></div><div class="voice-waveform-wrap"><div style="font-size:12px;color:#aaa">Расшифровка...</div></div></div>`;
                    } else {
                        html += `<div class="msg-file" id="${docId}"><span class="msg-file-icon">🔒</span><div class="msg-file-info"><div class="msg-file-name">Зашифрованный файл</div><div class="msg-file-size">Расшифровка...</div></div></div>`;
                    }
                    processEncryptedAttachment(docId, fileUrl);
                } else {
                    html += `<div class="msg-file"><span class="msg-file-icon">📎</span><div class="msg-file-info"><div class="msg-file-name">${escapeHtml(doc.title || 'Файл')}</div><div class="msg-file-size">${(doc.size / 1024).toFixed(1)} KB</div></div></div>`;
                }
            }
        }
    }

    const isEncBadge = isEncrypted ? `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>` : '';
    html += `<div class="msg-time">${isEncBadge} ${msg.date ? new Date(msg.date * 1000).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : ''}</div>`;
    
    div.innerHTML = html;
    wrapper.appendChild(div);

    setupSwipeAndTouch(wrapper, div, msg);
    container.appendChild(wrapper);
}

async function clientDecryptTextAsync(msgId, encryptedTextStr) {
    try {
        const jsonStr = encryptedTextStr.substring(ENCRYPT_PREFIX.length);
        const encObj = JSON.parse(jsonStr);
        const decBuf = await clientDecryptData(encObj);
        if (decBuf) {
            const plainText = new TextDecoder().decode(decBuf);
            decryptedCache[msgId] = plainText;
            const textElem = document.getElementById(`msg-text-${msgId}`);
            if (textElem) textElem.textContent = plainText;
        } else {
            const textElem = document.getElementById(`msg-text-${msgId}`);
            if (textElem) textElem.textContent = '🔒 Не удалось расшифровать';
        }
    } catch(e) {
        const textElem = document.getElementById(`msg-text-${msgId}`);
        if (textElem) textElem.textContent = '🔒 Ошибка расшифровки';
    }
}

function setupSwipeAndTouch(wrapper, div, msg) {
    let startX = 0, startY = 0;
    let currentX = 0;
    let isSwiping = false;
    let longPressTimer = null;

    div.addEventListener('touchstart', e => {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        currentX = 0;
        isSwiping = false;

        longPressTimer = setTimeout(() => {
            if (!isSwiping) {
                openContextMenu(msg);
                if (navigator.vibrate) navigator.vibrate(30);
            }
        }, 450);
    }, {passive: true});

    div.addEventListener('touchmove', e => {
        const diffX = e.touches[0].clientX - startX;
        const diffY = e.touches[0].clientY - startY;

        if (Math.abs(diffX) > Math.abs(diffY)) {
            if (diffX > 10) {
                isSwiping = true;
                clearTimeout(longPressTimer);
                currentX = Math.min(diffX, 70);
                div.style.transform = `translateX(${currentX}px)`;
                div.style.transition = 'none';

                const ind = wrapper.querySelector('.msg-reply-indicator');
                if (ind) ind.style.opacity = Math.min(currentX / 50, 1);
            }
        } else {
            clearTimeout(longPressTimer);
        }
    }, {passive: true});

    div.addEventListener('touchend', e => {
        clearTimeout(longPressTimer);
        div.style.transition = 'transform 0.22s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
        div.style.transform = 'translateX(0px)';

        const ind = wrapper.querySelector('.msg-reply-indicator');
        if (ind) ind.style.opacity = 0;

        if (currentX > 45) {
            setReply(msg);
            if (navigator.vibrate) navigator.vibrate(25);
        }
    });

    div.addEventListener('contextmenu', e => {
        e.preventDefault();
        openContextMenu(msg);
    });
}

/* =========================================================================
   MEDIA DECRYPTION & TG-STYLE PLAYERS (.mec & .meg)
   ========================================================================= */

async function processEncryptedAttachment(elemId, url) {
    if (!url) {
        const elem = document.getElementById(elemId);
        if (elem && elem.querySelector('.msg-file-size')) elem.querySelector('.msg-file-size').textContent = 'Ссылка недоступна';
        return;
    }

    if (decryptedCache[elemId]) {
        const elem = document.getElementById(elemId);
        if (elem) renderDecryptedMedia(elem, decryptedCache[elemId]);
        return;
    }

    try {
        const resp = await fetch(`/api/proxy_file?url=${encodeURIComponent(url)}`);
        if (!resp.ok) throw new Error("Proxy fetch error");
        const encArrayBuf = await resp.arrayBuffer();

        const view = new DataView(encArrayBuf);
        const headerLen = view.getUint32(0);
        const headerJsonBytes = new Uint8Array(encArrayBuf, 4, headerLen);
        const headerStr = new TextDecoder().decode(headerJsonBytes);
        const header = JSON.parse(headerStr);

        const encPayload = encArrayBuf.slice(4 + headerLen);

        const decPayloadBuf = await clientDecryptData({
            k1: header.k1,
            k2: header.k2,
            payload: bufToB64(encPayload)
        });

        if (!decPayloadBuf) throw new Error("Decryption failed");

        const blob = new Blob([decPayloadBuf], { type: header.mime || 'application/octet-stream' });
        const blobUrl = URL.createObjectURL(blob);
        decryptedCache[elemId] = { blobUrl, mime: header.mime, name: header.name, ext: (header.name||'').split('.').pop().toLowerCase() };

        const elem = document.getElementById(elemId);
        if (elem) renderDecryptedMedia(elem, decryptedCache[elemId]);
    } catch (e) {
        console.error("Failed to decrypt media:", e);
        const elem = document.getElementById(elemId);
        if (elem && elem.querySelector('.msg-file-size')) elem.querySelector('.msg-file-size').textContent = 'Ошибка расшифровки';
    }
}

function renderDecryptedMedia(elem, data) {
    if (data.ext === 'mec' || (data.mime && data.mime.startsWith('video/') && elem.classList.contains('video-note-container'))) {
        elem.innerHTML = `
            <video class="video-note-player" src="${data.blobUrl}" loop playsinline muted></video>
            <div class="video-note-overlay">
                <div class="video-note-btn">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" id="vbtn-${elem.id}"><polygon points="8 5 19 12 8 19 8 5"/></svg>
                </div>
            </div>
        `;
        const video = elem.querySelector('.video-note-player');
        const overlay = elem.querySelector('.video-note-overlay');
        const icon = elem.querySelector(`#vbtn-${elem.id}`);

        elem.onclick = () => {
            if (video.paused) {
                video.muted = false;
                video.play();
                overlay.classList.add('playing');
                icon.innerHTML = `<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>`;
            } else {
                video.pause();
                overlay.classList.remove('playing');
                icon.innerHTML = `<polygon points="8 5 19 12 8 19 8 5"/>`;
            }
        };
        return;
    }

    if (data.ext === 'meg' || (data.mime && data.mime.startsWith('audio/'))) {
        const audio = new Audio(data.blobUrl);
        elem.innerHTML = `
            <div class="voice-play-btn" id="vpbtn-${elem.id}">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="8 5 19 12 8 19 8 5"/></svg>
            </div>
            <div class="voice-waveform-wrap">
                <div class="voice-waveform" id="vw-${elem.id}"></div>
                <div class="voice-meta">
                    <span id="vt-${elem.id}">0:00</span>
                    <span>🔒 Voice</span>
                </div>
            </div>
        `;

        const wf = elem.querySelector(`#vw-${elem.id}`);
        const barHeights = [10,18,14,24,30,18,12,20,28,16,22,14,26,18,12,22,16,10,24,18];
        barHeights.forEach((h) => {
            const b = document.createElement('div');
            b.className = 'voice-bar';
            b.style.height = h + 'px';
            wf.appendChild(b);
        });

        const playBtn = elem.querySelector(`#vpbtn-${elem.id}`);
        const timeLabel = elem.querySelector(`#vt-${elem.id}`);
        const bars = wf.querySelectorAll('.voice-bar');

        audio.onloadedmetadata = () => {
            const mins = Math.floor(audio.duration / 60);
            const secs = Math.floor(audio.duration % 60);
            timeLabel.textContent = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
        };

        audio.ontimeupdate = () => {
            if (!audio.duration) return;
            const progress = audio.currentTime / audio.duration;
            const playedBars = Math.floor(progress * bars.length);
            bars.forEach((b, i) => {
                if (i <= playedBars) b.classList.add('played');
                else b.classList.remove('played');
            });
            const mins = Math.floor(audio.currentTime / 60);
            const secs = Math.floor(audio.currentTime % 60);
            timeLabel.textContent = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
        };

        audio.onended = () => {
            playBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="8 5 19 12 8 19 8 5"/></svg>`;
            bars.forEach(b => b.classList.remove('played'));
        };

        playBtn.onclick = () => {
            if (audio.paused) {
                audio.play();
                playBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`;
            } else {
                audio.pause();
                playBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="8 5 19 12 8 19 8 5"/></svg>`;
            }
        };
        return;
    }

    if (data.mime.startsWith('image/')) {
        const img = document.createElement('img');
        img.className = 'msg-photo';
        img.src = data.blobUrl;
        elem.replaceWith(img);
    } else if (data.mime.startsWith('video/')) {
        const vid = document.createElement('video');
        vid.className = 'msg-photo';
        vid.src = data.blobUrl;
        vid.controls = true;
        elem.replaceWith(vid);
    } else {
        elem.querySelector('.msg-file-size').textContent = 'Расшифровано (скачать)';
        elem.onclick = () => {
            const a = document.createElement('a');
            a.href = data.blobUrl;
            a.download = data.name || 'file';
            a.click();
        };
    }
}

function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

/* =========================================================================
   MESSAGING, REPLYING, EDITING & DELETING
   ========================================================================= */

function toggleInputIcons() {
    const val = document.getElementById('msgInput').value.trim();
    const sendBtn = document.getElementById('sendBtn');
    const vnoteBtn = document.getElementById('videoNoteBtn');
    const voiceBtn = document.getElementById('voiceBtn');

    if (val.length > 0) {
        sendBtn.classList.remove('hidden');
        vnoteBtn.classList.add('hidden');
        voiceBtn.classList.add('hidden');
    } else {
        sendBtn.classList.add('hidden');
        vnoteBtn.classList.remove('hidden');
        voiceBtn.classList.remove('hidden');
    }
}

function setReply(msg) {
    replyingMsg = msg;
    editingMsg = null;
    document.getElementById('editBanner').classList.add('hidden');
    
    const banner = document.getElementById('replyBanner');
    const author = document.getElementById('replyAuthor');
    const snippet = document.getElementById('replySnippet');

    author.textContent = msg.out ? 'В ответ самому себе' : (msg.name || 'В ответ');
    let text = msg.text || '';
    if (text.startsWith(ENCRYPT_PREFIX)) text = '🔒 Зашифрованное сообщение';
    snippet.textContent = text;
    banner.classList.remove('hidden');

    document.getElementById('msgInput').focus();
}

function cancelReply() {
    replyingMsg = null;
    document.getElementById('replyBanner').classList.add('hidden');
}

function setEdit(msg) {
    editingMsg = msg;
    replyingMsg = null;
    document.getElementById('replyBanner').classList.add('hidden');

    const banner = document.getElementById('editBanner');
    banner.classList.remove('hidden');

    let text = msg.text || '';
    if (text.startsWith(ENCRYPT_PREFIX) && decryptedCache[msg.id]) {
        text = decryptedCache[msg.id];
    }
    const input = document.getElementById('msgInput');
    input.value = text;
    toggleInputIcons();
    input.focus();
}

function cancelEdit() {
    editingMsg = null;
    document.getElementById('editBanner').classList.add('hidden');
    document.getElementById('msgInput').value = '';
    toggleInputIcons();
}

async function sendMessage() {
    const input = document.getElementById('msgInput');
    const text = input.value.trim();
    if (!text || !currentPeer) return;

    const btn = document.getElementById('sendBtn'); btn.disabled = true;
    let sendText = text;

    if (encryptionEnabled) {
        const peerKey = await getPeerPubKey(currentPeer);
        if (peerKey) {
            const plainBuf = new TextEncoder().encode(text).buffer;
            const encObj = await clientEncryptData(peerKey, plainBuf);
            sendText = ENCRYPT_PREFIX + JSON.stringify(encObj);
        }
    }

    if (editingMsg) {
        await fetch('/api/edit', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ token, peer_id: currentPeer, message_id: editingMsg.id, text: sendText })
        });
        cancelEdit();
    } else {
        const replyId = replyingMsg ? replyingMsg.id : null;
        await fetch('/api/send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ token, peer_id: currentPeer, text: sendText, reply_to: replyId })
        });
        cancelReply();
    }

    input.value = '';
    btn.disabled = false;
    toggleInputIcons();
    lastMessagesHash = ""; // force reload
    loadMessages();
}

/* =========================================================================
   VOICE RECORDING (.meg)
   ========================================================================= */

async function startVoiceRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        voiceRecorder = new MediaRecorder(stream);
        voiceChunks = [];

        voiceRecorder.ondataavailable = e => voiceChunks.push(e.data);
        voiceRecorder.start();

        document.getElementById('voiceRecordingBar').classList.remove('hidden');
        voiceSeconds = 0;
        document.getElementById('voiceTimer').textContent = '0:00';
        voiceTimerInterval = setInterval(() => {
            voiceSeconds++;
            const m = Math.floor(voiceSeconds / 60);
            const s = voiceSeconds % 60;
            document.getElementById('voiceTimer').textContent = `${m}:${s < 10 ? '0' : ''}${s}`;
        }, 1000);
    } catch(e) {
        alert("Не удалось получить доступ к микрофону");
    }
}

function cancelVoiceRecording() {
    if (voiceRecorder && voiceRecorder.state !== 'inactive') {
        voiceRecorder.stop();
        voiceRecorder.stream.getTracks().forEach(t => t.stop());
    }
    clearInterval(voiceTimerInterval);
    document.getElementById('voiceRecordingBar').classList.add('hidden');
}

async function stopAndSendVoice() {
    if (!voiceRecorder) return;
    voiceRecorder.onstop = async () => {
        voiceRecorder.stream.getTracks().forEach(t => t.stop());
        const audioBlob = new Blob(voiceChunks, { type: 'audio/webm' });
        await uploadEncryptedMedia(audioBlob, 'enc_voice.meg');
    };
    voiceRecorder.stop();
    clearInterval(voiceTimerInterval);
    document.getElementById('voiceRecordingBar').classList.add('hidden');
}

/* =========================================================================
   VIDEO NOTE RECORDING (.mec - TG Style "Кружочки")
   ========================================================================= */

async function openVideoNoteRecorder() {
    try {
        vnoteStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "user", width: { ideal: 480 }, height: { ideal: 480 } },
            audio: true
        });
        const video = document.getElementById('vnoteVideo');
        video.srcObject = vnoteStream;
        document.getElementById('videoNoteModal').classList.remove('hidden');
        document.getElementById('vnoteSendBtn').classList.add('hidden');
        document.getElementById('vnoteTimer').textContent = '0:00';
    } catch(e) {
        alert("Не удалось получить доступ к камере");
    }
}

function closeVideoNoteRecorder() {
    if (vnoteStream) {
        vnoteStream.getTracks().forEach(t => t.stop());
    }
    if (vnoteRecorder && vnoteRecorder.state !== 'inactive') {
        vnoteRecorder.stop();
    }
    clearInterval(vnoteTimerInterval);
    document.getElementById('videoNoteModal').classList.add('hidden');
}

function toggleVideoNoteRecord() {
    const recBtn = document.getElementById('vnoteRecBtn');
    if (!vnoteRecorder || vnoteRecorder.state === 'inactive') {
        vnoteRecorder = new MediaRecorder(vnoteStream, { mimeType: 'video/webm' });
        vnoteChunks = [];
        vnoteRecorder.ondataavailable = e => vnoteChunks.push(e.data);
        vnoteRecorder.start();

        recBtn.style.background = '#e53935';
        vnoteSeconds = 0;
        vnoteTimerInterval = setInterval(() => {
            vnoteSeconds++;
            const m = Math.floor(vnoteSeconds / 60);
            const s = vnoteSeconds % 60;
            document.getElementById('vnoteTimer').textContent = `${m}:${s < 10 ? '0' : ''}${s}`;
        }, 1000);
        document.getElementById('vnoteSendBtn').classList.remove('hidden');
    } else {
        vnoteRecorder.stop();
        clearInterval(vnoteTimerInterval);
    }
}

async function sendVideoNote() {
    if (vnoteRecorder && vnoteRecorder.state !== 'inactive') {
        vnoteRecorder.onstop = async () => {
            const videoBlob = new Blob(vnoteChunks, { type: 'video/webm' });
            closeVideoNoteRecorder();
            await uploadEncryptedMedia(videoBlob, 'enc_vnote.mec');
        };
        vnoteRecorder.stop();
    } else if (vnoteChunks.length > 0) {
        const videoBlob = new Blob(vnoteChunks, { type: 'video/webm' });
        closeVideoNoteRecorder();
        await uploadEncryptedMedia(videoBlob, 'enc_vnote.mec');
    }
}

async function uploadEncryptedMedia(blob, filename) {
    if (!currentPeer) return;
    const peerKey = await getPeerPubKey(currentPeer);
    if (!peerKey) { alert("Собеседник не имеет ключей для шифрования!"); return; }

    const arrayBuf = await blob.arrayBuffer();
    const encObj = await clientEncryptData(peerKey, arrayBuf);
    const payloadBuf = b64ToBuf(encObj.payload);

    const headerStr = JSON.stringify({ k1: encObj.k1, k2: encObj.k2, mime: blob.type, name: filename });
    const headerBytes = new TextEncoder().encode(headerStr);

    const totalLen = 4 + headerBytes.byteLength + payloadBuf.byteLength;
    const resultBuf = new ArrayBuffer(totalLen);
    const view = new DataView(resultBuf);
    view.setUint32(0, headerBytes.byteLength);

    const u8 = new Uint8Array(resultBuf);
    u8.set(headerBytes, 4);
    u8.set(new Uint8Array(payloadBuf), 4 + headerBytes.byteLength);

    const encBlob = new Blob([resultBuf], { type: 'application/octet-stream' });

    const formData = new FormData();
    formData.append('token', token);
    formData.append('peer_id', currentPeer);
    formData.append('file', encBlob, filename);

    await fetch('/api/upload_encrypted_doc', { method: 'POST', body: formData });
    lastMessagesHash = "";
    loadMessages();
}

async function handleFile(e) {
    const file = e.target.files[0];
    if (!file || !currentPeer) return;

    if (encryptionEnabled) {
        let ext = 'enc';
        if (file.type.startsWith('image/')) ext = 'meow';
        else if (file.type.startsWith('video/')) ext = 'mur';
        
        await uploadEncryptedMedia(file, `enc_${Date.now()}.${ext}`);
        return;
    }

    const formData = new FormData();
    formData.append('token', token);
    formData.append('peer_id', currentPeer);
    formData.append('file', file);
    await fetch('/api/upload_normal', { method: 'POST', body: formData });
    lastMessagesHash = "";
    loadMessages();
}

/* Context Menu & Deletion */
function openContextMenu(msg) {
    selectedMsg = msg;
    const contextModal = document.getElementById('contextModal');
    const editOpt = document.getElementById('contextEditOpt');

    if (msg.out) editOpt.classList.remove('hidden');
    else editOpt.classList.add('hidden');

    contextModal.classList.remove('hidden');
}

function closeContextMenu() {
    document.getElementById('contextModal').classList.add('hidden');
}

function replySelectedMessage() {
    closeContextMenu();
    if (selectedMsg) setReply(selectedMsg);
}

function editSelectedMessage() {
    closeContextMenu();
    if (selectedMsg) setEdit(selectedMsg);
}

function openDeleteModal() {
    closeContextMenu();
    document.getElementById('deleteModal').classList.remove('hidden');
}

function closeDeleteModal() {
    document.getElementById('deleteModal').classList.add('hidden');
}

function toggleDeleteCheckbox() {
    deleteForBoth = !deleteForBoth;
    const row = document.getElementById('deleteForBothRow');
    if (deleteForBoth) row.classList.add('active');
    else row.classList.remove('active');
}

async function confirmDeleteMessage() {
    if (!selectedMsg) return;
    await fetch('/api/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            token,
            message_ids: selectedMsg.id,
            delete_for_all: deleteForBoth ? 1 : 0
        })
    });
    closeDeleteModal();
    lastMessagesHash = "";
    loadMessages();
}

function toggleEncrypt() {
    encryptionEnabled = !encryptionEnabled;
    const btn = document.getElementById('encryptBtn');
    if (encryptionEnabled) btn.classList.add('active');
    else btn.classList.remove('active');
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => { if (currentPeer) loadMessages(); }, 3000);
}

function logout() {
    localStorage.clear();
    location.reload();
}

function showDialogs() {
    document.getElementById('chatScreen').classList.remove('active');
    loadDialogs();
}

function scrollToMsg(msgId) {
    const elem = document.getElementById('msg-' + msgId);
    if (elem) elem.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

document.getElementById('msgInput').addEventListener('keypress', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// Auto Login & Client Key Init
(async () => {
    if (token && password && localStorage.getItem('vk_user')) {
        currentUser = JSON.parse(localStorage.getItem('vk_user'));
        myVkId = currentUser.id;
        showDialogsScreen();
        const ok = await initClientCrypto();
        if (ok) {
            loadDialogs();
            startPolling();
        }
    }
})();
</script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/auth', methods=['POST'])
def auth():
    url = request.json.get('url', '')
    token_match = re.search(r'access_token=([^&]+)', url)
    if not token_match:
        return jsonify({'error': 'Токен не найден'}), 400
    token = token_match.group(1)
    user_info = vk_request('users.get', token, fields='photo_100,online')
    if isinstance(user_info, dict) and 'error' in user_info:
        return jsonify({'error': 'Неверный токен'}), 400
    user = user_info[0] if isinstance(user_info, list) else user_info
    return jsonify({
        'token': token,
        'user': {
            'id': user.get('id'),
            'name': user.get('first_name', '') + ' ' + user.get('last_name', ''),
            'photo': user.get('photo_100', ''),
            'online': user.get('online', 0)
        }
    })


@app.route('/api/keys/<vk_id>', methods=['GET'])
def get_key(vk_id):
    stored = firebase_get(f"keys/{vk_id}")
    if stored:
        return jsonify(stored)
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/keys/<vk_id>', methods=['POST'])
def save_key(vk_id):
    data = request.json
    data['created_at'] = datetime.now().isoformat()
    firebase_put(f"keys/{vk_id}", data)
    return jsonify({'ok': True})


@app.route('/api/dialogs', methods=['POST'])
def get_dialogs():
    token = request.json.get('token')
    result = vk_request('messages.getConversations', token, count=20, offset=0, extended=1)
    if isinstance(result, dict) and 'error' in result:
        return jsonify(result), 400
    dialogs = []
    profiles = {p['id']: p for p in result.get('profiles', [])}
    groups = {g['id']: g for g in result.get('groups', [])}
    for item in result.get('items', []):
        conv = item.get('conversation', {})
        msg = item.get('last_message', {})
        peer = conv.get('peer', {})
        peer_id = peer.get('id')
        peer_type = peer.get('type')
        name = "Unknown"
        photo = ""
        if peer_type == 'user':
            profile = profiles.get(peer_id, {})
            name = profile.get('first_name', '') + ' ' + profile.get('last_name', '')
            photo = profile.get('photo_100', '')
        elif peer_type == 'group':
            group = groups.get(-peer_id, {})
            name = group.get('name', 'Group')
            photo = group.get('photo_100', '')
        elif peer_type == 'chat':
            chat_settings = conv.get('chat_settings', {})
            name = chat_settings.get('title', 'Chat')
            photo = chat_settings.get('photo', {}).get('photo_100', '')
        dialogs.append({
            'id': peer_id,
            'type': peer_type,
            'name': name.strip(),
            'photo': photo,
            'unread': conv.get('unread_count', 0),
            'last_message': msg.get('text', ''),
            'date': msg.get('date', 0)
        })
    return jsonify({'dialogs': dialogs})


@app.route('/api/messages', methods=['POST'])
def get_messages():
    token = request.json.get('token')
    peer_id = request.json.get('peer_id')
    result = vk_request('messages.getHistory', token, peer_id=peer_id, count=50, offset=0, extended=1)
    if isinstance(result, dict) and 'error' in result:
        return jsonify(result), 400
    messages = []
    profiles = {p['id']: p for p in result.get('profiles', [])}
    for msg in result.get('items', []):
        from_id = msg.get('from_id', 0)
        profile = profiles.get(from_id, {})
        messages.append({
            'id': msg.get('id'),
            'text': msg.get('text', ''),
            'date': msg.get('date', 0),
            'from_id': from_id,
            'out': msg.get('out', 0),
            'name': profile.get('first_name', '') + ' ' + profile.get('last_name', ''),
            'photo': profile.get('photo_50', ''),
            'reply_message': msg.get('reply_message'),
            'attachments': msg.get('attachments', [])
        })
    return jsonify({'messages': messages})


@app.route('/api/send', methods=['POST'])
def send_message():
    token = request.json.get('token')
    peer_id = request.json.get('peer_id')
    text = request.json.get('text', '')
    reply_to = request.json.get('reply_to')

    params = {'peer_id': peer_id, 'message': text, 'random_id': 0}
    if reply_to:
        params['reply_to'] = reply_to

    result = vk_request('messages.send', token, **params)
    return jsonify({'result': result})


@app.route('/api/edit', methods=['POST'])
def edit_message():
    token = request.json.get('token')
    peer_id = request.json.get('peer_id')
    message_id = request.json.get('message_id')
    text = request.json.get('text', '')

    result = vk_request('messages.edit', token, peer_id=peer_id, message_id=message_id, message=text, keep_forward_messages=1)
    return jsonify({'result': result})


@app.route('/api/delete', methods=['POST'])
def delete_message():
    token = request.json.get('token')
    message_ids = request.json.get('message_ids')
    delete_for_all = request.json.get('delete_for_all', 1)

    result = vk_request('messages.delete', token, message_ids=message_ids, delete_for_all=delete_for_all)
    return jsonify({'result': result})


@app.route('/api/upload_encrypted_doc', methods=['POST'])
def upload_encrypted_doc():
    token = request.form.get('token')
    peer_id = request.form.get('peer_id')
    file = request.files.get('file')

    if not file:
        return jsonify({'error': 'No file'}), 400

    upload_server = vk_request('docs.getMessagesUploadServer', token, type='doc', peer_id=peer_id)
    if isinstance(upload_server, dict) and 'error' in upload_server:
        return jsonify(upload_server), 400

    upload_url = upload_server.get('upload_url')
    files = {'file': (file.filename, file.read(), 'application/octet-stream')}
    upload_resp = requests.post(upload_url, files=files, timeout=30).json()

    save_result = vk_request('docs.save', token, file=upload_resp.get('file'), title=file.filename)
    if isinstance(save_result, dict) and 'doc' in save_result:
        doc = save_result['doc']
        attachment = f"doc{doc['owner_id']}_{doc['id']}"
        vk_request('messages.send', token, peer_id=peer_id, attachment=attachment, random_id=0)
        return jsonify({'ok': True})

    return jsonify({'error': 'Upload failed'}), 400


@app.route('/api/upload_normal', methods=['POST'])
def upload_normal():
    token = request.form.get('token')
    peer_id = request.form.get('peer_id')
    file = request.files.get('file')

    if not file:
        return jsonify({'error': 'No file'}), 400

    filename = file.filename.lower()
    file_bytes = file.read()

    if filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
        upload_server = vk_request('photos.getMessagesUploadServer', token, peer_id=peer_id)
        if isinstance(upload_server, dict) and 'error' in upload_server:
            return jsonify(upload_server), 400

        upload_url = upload_server.get('upload_url')
        files = {'photo': (filename, BytesIO(file_bytes), file.content_type or 'image/jpeg')}
        upload_resp = requests.post(upload_url, files=files, timeout=30).json()

        save_result = vk_request('photos.saveMessagesPhoto', token,
            photo=upload_resp.get('photo'),
            server=upload_resp.get('server'),
            hash=upload_resp.get('hash')
        )

        if isinstance(save_result, list) and len(save_result) > 0:
            photo = save_result[0]
            attachment = f"photo{photo['owner_id']}_{photo['id']}"
            vk_request('messages.send', token, peer_id=peer_id, attachment=attachment, random_id=0)
            return jsonify({'ok': True})

    upload_server = vk_request('docs.getMessagesUploadServer', token, type='doc', peer_id=peer_id)
    if isinstance(upload_server, dict) and 'error' in upload_server:
        return jsonify(upload_server), 400

    upload_url = upload_server.get('upload_url')
    files = {'file': (filename, BytesIO(file_bytes), file.content_type or 'application/octet-stream')}
    upload_resp = requests.post(upload_url, files=files, timeout=30).json()

    save_result = vk_request('docs.save', token, file=upload_resp.get('file'), title=filename)
    if isinstance(save_result, dict) and 'doc' in save_result:
        doc = save_result['doc']
        attachment = f"doc{doc['owner_id']}_{doc['id']}"
        vk_request('messages.send', token, peer_id=peer_id, attachment=attachment, random_id=0)
        return jsonify({'ok': True})

    return jsonify({'error': 'Upload failed'}), 400


@app.route('/api/proxy_file')
def proxy_file():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL'}), 400
    try:
        resp = requests.get(url, timeout=30)
        return Response(resp.content, mimetype='application/octet-stream')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
