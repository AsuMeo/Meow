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
<title>VK Client - 100% Client-Side E2EE</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#000;color:#fff;height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased}
.app{height:100vh;display:flex;flex-direction:column;position:relative;overflow:hidden}

/* Login Screen */
.login-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;z-index:100;animation:fadeIn 0.3s ease-out}
.login-screen h1{font-size:26px;margin-bottom:6px;font-weight:700;color:#fff}
.login-screen p{color:#888;margin-bottom:24px;font-size:13px;text-align:center;max-width:320px}
.badge-e2e{background:#1c1c1e;color:#8e8e93;border:1px solid #2c2c2e;padding:6px 12px;border-radius:14px;font-size:12px;font-weight:600;margin-bottom:20px;display:inline-flex;align-items:center;gap:6px;transition:transform 0.2s}
.badge-e2e:hover{transform:scale(1.02)}
.token-input,.pass-input{width:100%;max-width:360px;padding:14px 16px;border:none;border-radius:14px;background:#161616;color:#fff;font-size:15px;margin-bottom:12px;outline:none;border:1px solid #2c2c2c;transition:border-color 0.2s, box-shadow 0.2s}
.token-input:focus,.pass-input:focus{border-color:#555;box-shadow:0 0 8px rgba(255,255,255,0.1)}
.token-input::placeholder,.pass-input::placeholder{color:#666}
.btn{width:100%;max-width:360px;padding:14px;border:none;border-radius:14px;background:#fff;color:#000;font-size:16px;font-weight:600;cursor:pointer;margin-bottom:8px;transition:all 0.15s active}
.btn:active{transform:scale(0.97);opacity:.85}
.btn-secondary{background:transparent;color:#fff;border:1px solid #333}
.btn-green{background:#2c2c2e;color:#fff;border:1px solid #3a3a3c}
.btn-danger{background:#ff3b30;color:#fff}

/* Header */
.header{height:54px;background:#0d0d0d;display:flex;align-items:center;padding:0 8px;border-bottom:1px solid #1c1c1c;flex-shrink:0;z-index:20}
.header-back{display:flex;align-items:center;gap:4px;padding:6px 10px;cursor:pointer;border-radius:12px;background:#1a1a1c;color:#fff;font-size:13px;font-weight:600;margin-right:8px;transition:background 0.2s}
.header-back:active{background:#2a2a2c}
.header-avatar{width:36px;height:36px;border-radius:50%;object-fit:cover;margin-right:10px;background:#222;cursor:pointer;transition:transform 0.2s}
.header-avatar:active{transform:scale(0.95)}
.header-info{flex:1;min-width:0;cursor:pointer}
.header-title{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.header-subtitle{font-size:12px;color:#888;display:flex;align-items:center;gap:4px}
.header-subtitle.e2e-on{color:#8e8e93}
.header-actions{display:flex;gap:4px}
.header-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;color:#777;transition:all 0.2s}
.header-btn:active{transform:scale(0.9)}
.header-btn.active{color:#fff}

/* Dialogs */
.dialogs-screen{flex:1;display:flex;flex-direction:column;overflow:hidden;animation:fadeIn 0.25s ease-out}
.dialogs-list{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.dialog{display:flex;align-items:center;padding:12px 14px;cursor:pointer;border-bottom:1px solid #111;transition:background 0.15s}
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
.chat-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;z-index:10;transform:translateX(100%);transition:transform 0.28s cubic-bezier(0.1, 0.9, 0.2, 1)}
.chat-screen.active{transform:translateX(0)}
.messages-wrapper{flex:1;position:relative;overflow:hidden;display:flex;flex-direction:column}
.messages{flex:1;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:8px;-webkit-overflow-scrolling:touch;scroll-behavior:smooth}

/* Upload Progress Banner */
.upload-status-banner{background:#1c1c1e;color:#fff;font-size:13px;padding:8px 14px;display:flex;align-items:center;justify-content:center;gap:8px;border-bottom:1px solid #2c2c2e;animation:slideDown 0.2s ease-out;z-index:15}

/* Message styling - STRICTLY NORMAL COLORS FOR ENCRYPTED MESSAGES */
.msg-container{position:relative;display:flex;width:100%;align-items:center;touch-action:pan-y;margin-bottom:2px}
.msg-swipe-bg{position:absolute;top:0;bottom:0;display:flex;align-items:center;justify-content:center;width:40px;opacity:0;transition:opacity 0.15s;color:#8e8e93;z-index:1}
.msg-swipe-right{right:-40px}

.msg{max-width:82%;padding:8px 12px;border-radius:18px;font-size:14px;line-height:1.4;word-wrap:break-word;position:relative;transition:transform 0.2s cubic-bezier(0.1, 0.8, 0.3, 1), background-color 0.2s;will-change:transform;animation:msgAppear 0.25s ease-out}
@keyframes msgAppear{from{opacity:0;transform:translateY(8px) scale(0.98)}to{opacity:1;transform:translateY(0) scale(1)}}

.msg-in{align-self:flex-start;background:#1c1c1e;border-bottom-left-radius:4px;color:#fff}
.msg-out{align-self:flex-end;background:#2c2c2e;border-bottom-right-radius:4px;color:#fff}
.msg-encrypted{/* strictly identical to normal message bubbles */}

/* Reply quote inside message */
.msg-reply-quote{background:rgba(255,255,255,0.08);border-left:3px solid #8e8e93;padding:4px 8px;border-radius:4px;margin-bottom:6px;font-size:12px;cursor:pointer}
.msg-reply-name{font-weight:600;color:#aaa;margin-bottom:2px;font-size:11px}
.msg-reply-text{color:#ddd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.msg-author{font-size:11px;color:#aaa;font-weight:600;margin-bottom:2px}
.msg-text{color:#fff;transition:opacity 0.2s}
.msg-time{font-size:10px;color:#888;margin-top:4px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:3px}

/* Decryption Shimmer Animation */
.decrypting-shimmer{position:relative;color:transparent!important;overflow:hidden;background:linear-gradient(90deg, #3a3a3c 25%, #666 50%, #3a3a3c 75%);background-size:200% 100%;-webkit-background-clip:text;animation:shimmer 1.2s infinite linear;border-radius:4px;display:inline-block;min-width:70px;min-height:16px}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}

.decrypted-pop{animation:decryptedPop 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)}
@keyframes decryptedPop{0%{opacity:0.4;transform:scale(0.97)}100%{opacity:1;transform:scale(1)}}

.msg-status{font-size:10px;margin-left:3px}

/* Media Attachments */
.msg-photo{max-width:100%;border-radius:12px;margin-top:6px;display:block;max-height:280px;object-fit:cover;cursor:pointer;background:#111;transition:transform 0.2s}
.msg-photo:active{transform:scale(0.98)}
.msg-video{max-width:100%;border-radius:12px;margin-top:6px;display:block;max-height:280px;background:#000}
.msg-file{background:rgba(255,255,255,.05);padding:10px;border-radius:12px;margin-top:6px;display:flex;align-items:center;gap:10px;transition:background 0.2s;cursor:pointer}
.msg-file:active{background:rgba(255,255,255,.1)}
.msg-file-icon{font-size:20px;display:flex;align-items:center;justify-content:center;width:32px;height:32px;background:rgba(255,255,255,0.1);border-radius:50%}
.msg-file-info{flex:1;min-width:0}
.msg-file-name{font-size:13px;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.msg-file-size{font-size:11px;color:#888}

/* TG Circle Video Message (.mec) */
.tg-circle-container{width:200px;height:200px;position:relative;border-radius:50%;overflow:hidden;margin-top:6px;background:#111;box-shadow:0 4px 15px rgba(0,0,0,0.5);transform:translateZ(0)}
.tg-circle-video{width:100%;height:100%;object-fit:cover;border-radius:50%;cursor:pointer;display:block}
.tg-circle-overlay{position:absolute;top:0;left:0;width:100%;height:100%;border-radius:50%;pointer-events:none;box-shadow:inset 0 0 0 2px rgba(255,255,255,0.15)}

/* TG Voice Message (.meg) */
.tg-voice-container{display:flex;align-items:center;gap:10px;padding:6px 0;width:220px;user-select:none}
.tg-voice-play-btn{width:38px;height:38px;border-radius:50%;background:#fff;color:#000;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:transform 0.15s, background 0.15s}
.tg-voice-play-btn:active{transform:scale(0.92)}
.tg-voice-wave-wrap{flex:1;display:flex;flex-direction:column;gap:4px}
.tg-voice-waveform{display:flex;align-items:center;gap:2px;height:24px;cursor:pointer}
.tg-voice-bar{flex:1;background:rgba(255,255,255,0.3);border-radius:2px;min-height:3px;transition:height 0.1s, background 0.15s}
.tg-voice-bar.active{background:#fff}
.tg-voice-info{display:flex;justify-content:space-between;font-size:10px;color:#aaa}

/* Input Bar & Actions */
.input-area-wrapper{background:#0d0d0d;border-top:1px solid #1a1a1a;display:flex;flex-direction:column;flex-shrink:0;z-index:15}

/* Reply & Edit Bar Above Input */
.reply-preview-bar{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#141416;border-bottom:1px solid #222;animation:slideDown 0.2s ease-out}
@keyframes slideDown{from{transform:translateY(-10px);opacity:0}to{transform:translateY(0);opacity:1}}
.reply-preview-info{flex:1;min-width:0;border-left:2px solid #8e8e93;padding-left:8px}
.reply-preview-title{font-size:12px;font-weight:600;color:#aaa}
.reply-preview-text{font-size:12px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.reply-preview-close{width:28px;height:28px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#888;border-radius:50%}
.reply-preview-close:active{background:#222}

.input-area{min-height:54px;display:flex;align-items:flex-end;padding:8px;gap:6px;position:relative}
.input-attach{width:38px;height:38px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;flex-shrink:0;color:#aaa;transition:transform 0.15s, color 0.15s}
.input-attach:active{transform:scale(0.9);background:#222;color:#fff}
.message-input{flex:1;padding:10px 14px;border:none;border-radius:20px;background:#1c1c1e;color:#fff;font-size:14px;outline:none;resize:none;max-height:100px;font-family:inherit;line-height:1.4;border:1px solid #2a2a2c;transition:border-color 0.2s}
.message-input:focus{border-color:#444}
.send-btn,.media-rec-btn{width:38px;height:38px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;border:none;color:#000;transition:transform 0.15s, background 0.2s}
.send-btn:active,.media-rec-btn:active{transform:scale(0.92)}
.send-btn:disabled{background:#222;color:#555}

/* Voice / Circle Recording UI Bar */
.recording-bar{display:flex;align-items:center;flex:1;padding:0 12px;height:38px;background:#1c1c1e;border-radius:20px;gap:10px;animation:fadeIn 0.2s ease-out}
.recording-dot{width:10px;height:10px;border-radius:50%;background:#ff3b30;animation:pulseDot 1s infinite alternate}
@keyframes pulseDot{from{opacity:0.3}to{opacity:1}}
.recording-timer{font-size:13px;font-weight:600;color:#fff;min-width:40px}
.recording-waves{flex:1;display:flex;align-items:center;gap:3px;height:18px;overflow:hidden}
.recording-wave-bar{flex:1;background:#555;border-radius:2px;height:4px;transition:height 0.1s}
.recording-cancel{font-size:13px;color:#ff3b30;cursor:pointer;font-weight:500;padding:4px 8px;border-radius:12px}
.recording-cancel:active{background:rgba(255,59,48,0.1)}

/* TG Circle Camera Modal / Video Controls */
.circle-recorder-modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:300;display:flex;flex-direction:column;align-items:center;justify-content:center;animation:fadeIn 0.2s ease-out}
.circle-preview-box{width:260px;height:260px;border-radius:50%;overflow:hidden;position:relative;box-shadow:0 0 30px rgba(0,0,0,0.8);border:4px solid #fff;background:#000}
.circle-preview-video{width:100%;height:100%;object-fit:cover}
.circle-tools-bar{display:flex;align-items:center;gap:16px;margin-top:20px}
.circle-tool-btn{width:44px;height:44px;border-radius:50%;background:#2c2c2e;color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:transform 0.15s, background 0.15s}
.circle-tool-btn:active{transform:scale(0.9);background:#3a3a3c}
.circle-tool-btn.active{background:#fff;color:#000}

.circle-rec-controls{margin-top:24px;display:flex;align-items:center;gap:24px}
.circle-btn-action{width:60px;height:60px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:transform 0.15s}
.circle-btn-action:active{transform:scale(0.9)}
.circle-btn-stop{background:#ff3b30;color:#fff;box-shadow:0 0 15px rgba(255,59,48,0.5)}
.circle-btn-cancel{background:#3a3a3c;color:#fff}

/* Bottom Nav */
.bottom-nav{height:50px;background:#0d0d0d;border-top:1px solid #1a1a1a;display:flex;justify-content:space-around;align-items:center;flex-shrink:0}
.nav-item{flex:1;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;cursor:pointer;color:#666;transition:color 0.2s}
.nav-item.active{color:#fff}
.nav-item span{font-size:10px}

/* Context Menu / Message Actions Sheet */
.action-sheet{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:250;display:flex;flex-direction:column;justify-content:flex-end;animation:fadeIn 0.2s ease-out}
.action-sheet-content{background:#1c1c1e;border-top-left-radius:20px;border-top-right-radius:20px;padding:16px;display:flex;flex-direction:column;gap:8px;animation:slideUp 0.25s cubic-bezier(0.1, 0.9, 0.2, 1)}
@keyframes slideUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.action-sheet-item{padding:14px 16px;border-radius:12px;background:#2c2c2e;color:#fff;font-size:15px;font-weight:500;display:flex;align-items:center;gap:12px;cursor:pointer;transition:background 0.15s}
.action-sheet-item:active{background:#3a3a3c}
.action-sheet-item.danger{color:#ff3b30}

/* Modals */
.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.85);display:flex;align-items:center;justify-content:center;z-index:200;padding:20px;animation:fadeIn 0.2s ease-out}
.modal-content{background:#161616;border-radius:20px;padding:24px;width:100%;max-width:380px;border:1px solid #282828;box-shadow:0 10px 30px rgba(0,0,0,0.5)}
.modal-title{font-size:18px;font-weight:600;margin-bottom:10px;color:#fff}
.modal-text{font-size:13px;color:#aaa;margin-bottom:20px;line-height:1.5}
.modal-checkbox{display:flex;align-items:center;gap:10px;margin-bottom:20px;font-size:14px;color:#ddd;cursor:pointer}
.modal-checkbox input{width:18px;height:18px;accent-color:#fff}

.file-input{display:none}
.hidden{display:none!important}
.loader{border:2px solid #333;border-top:2px solid #fff;border-radius:50%;width:16px;height:16px;animation:spin 0.8s linear infinite;display:inline-block;vertical-align:middle;margin-right:6px}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
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
<p>Шифрование происходит прямо на твоём телефоне. Сервер не имеет доступа к фото и сообщениям.</p>
<button class="btn btn-secondary" onclick="getToken()">1. Получить токен VK</button>
<input type="text" class="token-input" id="tokenUrl" placeholder="Вставь ссылку с токеном из адресной строки...">
<input type="password" class="pass-input" id="password" placeholder="Пароль для защиты ключей...">
<button class="btn" onclick="login()">Войти</button>
</div>

<!-- Setup Encryption Modal -->
<div class="modal hidden" id="setupModal">
<div class="modal-content">
<div class="modal-title">Генерация RSA/AES ключей</div>
<div class="modal-text" id="setupText">Генерируем уникальную пару ключей в вашем браузере... Приватный ключ шифруется локально с помощью Web Crypto API.</div>
<button class="btn btn-green" id="setupBtn" onclick="setupEncryption()">Создать ключи на телефоне</button>
</div>
</div>

<!-- Delete Confirmation Modal -->
<div class="modal hidden" id="deleteModal">
<div class="modal-content">
<div class="modal-title">Удаление сообщения</div>
<div class="modal-text">Вы уверены, что хотите удалить выбранное сообщение?</div>
<label class="modal-checkbox">
<input type="checkbox" id="deleteForAllCheck" checked>
<span>Удалить у всех (до 24 ч)</span>
</label>
<div style="display:flex;gap:8px;">
<button class="btn btn-secondary" style="flex:1" onclick="closeDeleteModal()">Отмена</button>
<button class="btn btn-danger" style="flex:1" onclick="confirmDeleteMessage()">Удалить</button>
</div>
</div>
</div>

<!-- Dialogs Screen -->
<div class="dialogs-screen hidden" id="dialogsScreen">
<div class="header">
<img class="header-avatar" id="headerAvatar" src="" alt="">
<div class="header-info">
<div class="header-title" id="headerTitle">VK</div>
<div class="header-subtitle e2e-on">
<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
Локальная защита
</div>
</div>
<div class="header-actions">
<div class="header-btn active" id="encryptBtn" onclick="toggleEncrypt()" title="Локальное шифрование">
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
<!-- PROMINENT BACK BUTTON TO EXIT CHAT -->
<div class="header-back" onclick="backToDialogs()" title="Выйти из чата">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
<span>Назад</span>
</div>
<img class="header-avatar" id="chatAvatar" onclick="backToDialogs()" src="" alt="">
<div class="header-info" onclick="backToDialogs()">
<div class="header-title" id="chatTitle"></div>
<div class="header-subtitle" id="chatEncryptStatus">E2EE Ready</div>
</div>
</div>

<!-- Uploading Progress Status Banner -->
<div class="upload-status-banner hidden" id="uploadStatusBanner">
<span class="loader"></span> <span id="uploadStatusText">Шифрование и отправка медиа...</span>
</div>

<div class="messages-wrapper">
<div class="messages" id="messages"></div>
</div>

<div class="input-area-wrapper">
<!-- Reply / Edit Preview Bar -->
<div class="reply-preview-bar hidden" id="replyPreviewBar">
<div class="reply-preview-info">
<div class="reply-preview-title" id="replyPreviewTitle">Ответ на сообщение</div>
<div class="reply-preview-text" id="replyPreviewText">...</div>
</div>
<div class="reply-preview-close" onclick="cancelReplyOrEdit()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
</div>
</div>

<!-- Normal Input Bar -->
<div class="input-area" id="inputAreaNormal">
<div class="input-attach" onclick="document.getElementById('fileInput').click()">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
</div>
<input type="file" class="file-input" id="fileInput" accept="image/*,video/*,*/*" onchange="handleFile(event)">

<textarea class="message-input" id="msgInput" placeholder="Сообщение..." rows="1" oninput="handleInputTyping()"></textarea>

<!-- Media Record Buttons -->
<button class="media-rec-btn" id="voiceRecBtn" onclick="startVoiceRecording()" title="Голосовое сообщение (.meg)">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
</button>

<button class="media-rec-btn" id="circleRecBtn" onclick="startCircleRecording()" title="Кружочек (.mec)">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><polygon points="10 8 16 12 10 16 10 8"/></svg>
</button>

<button class="send-btn hidden" id="sendBtn" onclick="sendMessage()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>
</div>

<!-- Voice Recording Bar -->
<div class="input-area hidden" id="inputAreaVoice">
<div class="recording-bar">
<div class="recording-dot"></div>
<div class="recording-timer" id="voiceTimer">0:00</div>
<div class="recording-waves" id="voiceWaveform">
<div class="recording-wave-bar" style="height:30%"></div>
<div class="recording-wave-bar" style="height:60%"></div>
<div class="recording-wave-bar" style="height:90%"></div>
<div class="recording-wave-bar" style="height:40%"></div>
<div class="recording-wave-bar" style="height:70%"></div>
<div class="recording-wave-bar" style="height:50%"></div>
<div class="recording-wave-bar" style="height:80%"></div>
</div>
<div class="recording-cancel" onclick="cancelVoiceRecording()">Отмена</div>
</div>
<button class="send-btn" style="background:#ff3b30;color:#fff" onclick="stopAndSendVoiceRecording()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>
</div>

</div>
</div>

<!-- Circle Video Camera Preview Modal with Flip & Flash Controls -->
<div class="circle-recorder-modal hidden" id="circleModal">
<div class="circle-preview-box">
<video class="circle-preview-video" id="circleVideoPreview" autoplay muted playsinline></video>
</div>

<div class="circle-tools-bar">
<!-- Camera Switch Button -->
<div class="circle-tool-btn" id="circleFlipBtn" onclick="switchCircleCamera()" title="Переключить камеру">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 10c0-4.418-3.582-8-8-8s-8 3.582-8 8c0 1.62.483 3.127 1.314 4.386L3 17l4.137-.966A7.962 7.962 0 0 0 12 18c4.418 0 8-3.582 8-8z"/><path d="M16 14l4 4-4 4"/></svg>
</div>

<div class="recording-timer" id="circleTimer" style="font-size:18px">0:00</div>

<!-- Torch / Flashlight Button -->
<div class="circle-tool-btn" id="circleTorchBtn" onclick="toggleCircleTorch()" title="Фонарик">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
</div>
</div>

<div class="circle-rec-controls">
<div class="circle-btn-action circle-btn-cancel" onclick="cancelCircleRecording()">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
</div>
<div class="circle-btn-action circle-btn-stop" onclick="stopAndSendCircleRecording()">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</div>
</div>
</div>

<!-- Action Sheet for Message Options -->
<div class="action-sheet hidden" id="actionSheet" onclick="closeActionSheet(event)">
<div class="action-sheet-content" onclick="event.stopPropagation()">
<div class="action-sheet-item" onclick="triggerReplyFromSheet()">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>
Ответить
</div>
<div class="action-sheet-item" id="editSheetItem" onclick="triggerEditFromSheet()">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
Редактировать
</div>
<div class="action-sheet-item danger" onclick="triggerDeleteFromSheet()">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
Удалить
</div>
<div class="action-sheet-item" style="justify-content:center;color:#888" onclick="closeActionSheet()">
Отмена
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

let localKeyPair = null; // { publicKey, privateKey, pubJwkStr }
let peerKeysCache = {}; // peer_id -> public JWK string
let decryptedCache = {}; // message/doc id -> blob URL / text

// State for Reply / Edit / Message Action
let replyToMsg = null;
let editMsg = null;
let selectedMsgForAction = null;

// Convert Buffers
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

// PBKDF2 Master Key derivation from User Password + Token
async function deriveMasterKey(pass, saltStr) {
    const enc = new TextEncoder();
    const keyMaterial = await window.crypto.subtle.importKey(
        "raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]
    );
    return await window.crypto.subtle.deriveKey(
        {
            name: "PBKDF2",
            salt: enc.encode(saltStr),
            iterations: 100000,
            hash: "SHA-256"
        },
        keyMaterial,
        { name: "AES-GCM", length: 256 },
        false,
        ["encrypt", "decrypt"]
    );
}

// AES-GCM Encrypt Buffer
async function encryptAESGCM(key, plainBuf) {
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, plainBuf);
    const combined = new Uint8Array(iv.byteLength + ciphertext.byteLength);
    combined.set(iv, 0);
    combined.set(new Uint8Array(ciphertext), iv.byteLength);
    return combined.buffer;
}

// AES-GCM Decrypt Buffer
async function decryptAESGCM(key, combinedBuf) {
    const bytes = new Uint8Array(combinedBuf);
    const iv = bytes.slice(0, 12);
    const ciphertext = bytes.slice(12);
    return await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
}

// Initialize Local Client Crypto Keys
async function initClientCrypto() {
    if (!myVkId || !password || !token) return false;
    
    const masterKey = await deriveMasterKey(password, myVkId + "_vk_e2ee_salt");
    
    // Check if keypair exists in Firebase via API
    const res = await fetch(`/api/keys/${myVkId}`);
    const stored = await res.json();
    
    if (stored && stored.public_key && stored.private_key_enc) {
        try {
            const privEncBuf = b64ToBuf(stored.private_key_enc);
            const privDecBuf = await decryptAESGCM(masterKey, privEncBuf);
            const privJwk = JSON.parse(new TextDecoder().decode(privDecBuf));
            const pubJwk = JSON.parse(stored.public_key);

            const publicKey = await window.crypto.subtle.importKey(
                "jwk", pubJwk, { name: "RSA-OAEP", hash: "SHA-256" }, true, ["encrypt"]
            );
            const privateKey = await window.crypto.subtle.importKey(
                "jwk", privJwk, { name: "RSA-OAEP", hash: "SHA-256" }, true, ["decrypt"]
            );

            localKeyPair = { publicKey, privateKey, pubJwkStr: stored.public_key };
            return true;
        } catch(e) {
            console.error("Local Key Decryption Failed:", e);
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

// Fetch Peer Public Key
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
        const key = await window.crypto.subtle.importKey(
            "jwk", pubJwk, { name: "RSA-OAEP", hash: "SHA-256" }, true, ["encrypt"]
        );
        peerKeysCache[peerId] = key;
        return key;
    }
    return null;
}

// Encrypt payload buffer for Peer & Self locally on client
async function clientEncryptData(peerKey, plainBuf) {
    const sessionKey = await window.crypto.subtle.generateKey(
        { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]
    );

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

// Decrypt payload locally on client
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

    const sessionKey = await window.crypto.subtle.importKey(
        "raw", rawSession, { name: "AES-GCM" }, false, ["decrypt"]
    );

    const decrypted = await decryptAESGCM(sessionKey, b64ToBuf(encObj.payload));
    return decrypted;
}

/* =========================================================================
   UI & APP LOGIC
   ========================================================================= */

const AUTH_URL = 'https://oauth.vk.com/authorize?client_id=2685278&scope=messages,audio,photos,video,docs,notes,pages,status,wall,groups,email,stats,notifications,offline&redirect_uri=https://oauth.vk.com/blank.html&response_type=token';

function getToken() { window.open(AUTH_URL, '_blank'); }

async function login() {
    const url = document.getElementById('tokenUrl').value.trim();
    const pass = document.getElementById('password').value.trim();
    if (!url) { alert('Вставишь ссылку с токеном'); return; }
    if (!pass) { alert('Придумай пароль для шифрования'); return; }

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
    document.getElementById('setupText').innerHTML = '<span class="loader"></span>Создание ключей на вашем смартфоне...';
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
        status.style.color = '#8e8e93';
    } else {
        status.textContent = 'Обычный чат (нет ключа у собеседника)';
        status.style.color = '#888';
    }

    cancelReplyOrEdit();
    loadMessages();
}

function backToDialogs() {
    document.getElementById('chatScreen').classList.remove('active');
    currentPeer = null;
    cancelReplyOrEdit();
}

// UPLOAD PROGRESS STATUS CONTROLS
function showUploadStatus(msg) {
    const banner = document.getElementById('uploadStatusBanner');
    const text = document.getElementById('uploadStatusText');
    if (banner && text) {
        text.textContent = msg || 'Шифрование и отправка медиа...';
        banner.classList.remove('hidden');
    }
}

function hideUploadStatus() {
    const banner = document.getElementById('uploadStatusBanner');
    if (banner) banner.classList.add('hidden');
}

async function loadMessages() {
    if (!currentPeer) return;
    const res = await fetch('/api/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, peer_id: currentPeer }) });
    const data = await res.json();
    const container = document.getElementById('messages');
    
    if (data.messages) {
        const msgs = data.messages.reverse();
        const msgIds = msgs.map(m => m.id).join(',');
        if (container.getAttribute('data-msg-hash') === msgIds) {
            return;
        }
        container.setAttribute('data-msg-hash', msgIds);
        container.innerHTML = '';
        
        for (const m of msgs) {
            await renderMessageItem(container, m);
        }
        container.scrollTop = container.scrollHeight;
    }
}

// RENDER MESSAGE ITEM WITH TELEGRAM-STYLE DESIGNS & SWIPE TO REPLY
async function renderMessageItem(container, msg) {
    const containerDiv = document.createElement('div');
    containerDiv.className = 'msg-container';
    
    const isEncrypted = msg.text && msg.text.startsWith(ENCRYPT_PREFIX);
    
    const swipeBgRight = document.createElement('div');
    swipeBgRight.className = 'msg-swipe-bg msg-swipe-right';
    swipeBgRight.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>`;

    const div = document.createElement('div');
    div.className = 'msg ' + (msg.out ? 'msg-out' : 'msg-in') + (isEncrypted ? ' msg-encrypted' : '');
    div.id = 'msg-' + msg.id;

    div.oncontextmenu = (e) => {
        e.preventDefault();
        openActionSheet(msg);
    };

    attachSwipeToReply(containerDiv, div, msg);

    let html = '';
    
    if (msg.reply_message) {
        const rMsg = msg.reply_message;
        const rAuthor = rMsg.name || (rMsg.from_id === myVkId ? 'Вы' : 'Собеседник');
        let rText = rMsg.text || 'Вложение';
        if (rText.startsWith(ENCRYPT_PREFIX)) rText = '🔒 Зашифрованное сообщение';
        html += `<div class="msg-reply-quote" onclick="scrollToMsg('${rMsg.id}')">
            <div class="msg-reply-name">${escapeHtml(rAuthor)}</div>
            <div class="msg-reply-text">${escapeHtml(rText)}</div>
        </div>`;
    }

    if (!msg.out && msg.name) html += `<div class="msg-author">${escapeHtml(msg.name)}</div>`;

    let displayText = msg.text || '';
    
    if (isEncrypted) {
        if (decryptedCache[msg.id]) {
            displayText = decryptedCache[msg.id];
            html += `<div class="msg-text">${escapeHtml(displayText)}</div>`;
        } else {
            html += `<div class="msg-text"><span class="decrypting-shimmer">🔐 Расшифровка...</span></div>`;
            
            setTimeout(async () => {
                try {
                    const encObj = JSON.parse(msg.text.substring(ENCRYPT_PREFIX.length));
                    const decBuf = await clientDecryptData(encObj);
                    if (decBuf) {
                        const plainText = new TextDecoder().decode(decBuf);
                        decryptedCache[msg.id] = plainText;
                        const textElem = document.getElementById('msg-' + msg.id)?.querySelector('.msg-text');
                        if (textElem) {
                            textElem.innerHTML = escapeHtml(plainText);
                            textElem.classList.add('decrypted-pop');
                        }
                    }
                } catch(e) {
                    const textElem = document.getElementById('msg-' + msg.id)?.querySelector('.msg-text');
                    if (textElem) textElem.textContent = '🔒 Не удалось расшифровать';
                }
            }, 30);
        }
    } else {
        html += `<div class="msg-text">${escapeHtml(displayText)}</div>`;
    }

    // Process attachments
    if (msg.attachments) {
        for (const a of msg.attachments) {
            if (a.type === 'photo') {
                const p = a.photo?.sizes?.find(s => s.type === 'x') || a.photo?.sizes?.[a.photo?.sizes?.length - 1];
                if (p) html += `<img class="msg-photo" src="${p.url}">`;
            }
            if (a.type === 'doc') {
                const doc = a.doc;
                const title = (doc.title || '').toLowerCase();
                const ext = (doc.ext || '').toLowerCase();

                if (title.startsWith('enc_') || ext === 'meow' || ext === 'mur' || ext === 'enc' || ext === 'mec' || ext === 'meg' || title.endsWith('.mec') || title.endsWith('.meg')) {
                    const docId = `doc_${doc.owner_id}_${doc.id}`;
                    
                    if (ext === 'mec' || title.endsWith('.mec')) {
                        html += `<div class="tg-circle-container" id="${docId}">
                            <div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;font-size:12px"><span class="loader"></span>Расшифровка кружочка...</div>
                        </div>`;
                    } else if (ext === 'meg' || title.endsWith('.meg')) {
                        html += `<div class="tg-voice-container" id="${docId}">
                            <div class="tg-voice-play-btn"><span class="loader"></span></div>
                            <div class="tg-voice-wave-wrap">
                                <div class="tg-voice-waveform"><div class="tg-voice-bar active" style="height:50%"></div></div>
                                <div class="tg-voice-info"><span>🔒 Расшифровка...</span></div>
                            </div>
                        </div>`;
                    } else {
                        html += `<div class="msg-file" id="${docId}"><span class="msg-file-icon">🔒</span><div class="msg-file-info"><div class="msg-file-name">Зашифрованный файл</div><div class="msg-file-size">Локальная расшифровка...</div></div></div>`;
                    }

                    setTimeout(() => processEncryptedAttachment(docId, doc.url, ext || title), 30);

                } else {
                    html += `<div class="msg-file"><span class="msg-file-icon">📎</span><div class="msg-file-info"><div class="msg-file-name">${escapeHtml(doc.title || 'Файл')}</div><div class="msg-file-size">${(doc.size / 1024).toFixed(1)} KB</div></div></div>`;
                }
            }
        }
    }

    const msgTime = msg.date ? new Date(msg.date * 1000).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : '';
    html += `<div class="msg-time">${msgTime} ${msg.out ? '<span class="msg-status">✓</span>' : ''}</div>`;
    
    div.innerHTML = html;
    containerDiv.appendChild(div);
    containerDiv.appendChild(swipeBgRight);
    container.appendChild(containerDiv);
}

// SWIPE TO REPLY GESTURE
function attachSwipeToReply(container, elem, msg) {
    let startX = 0;
    let currentX = 0;
    let isDragging = false;
    const swipeBg = container.querySelector('.msg-swipe-right');

    elem.addEventListener('touchstart', (e) => {
        startX = e.touches[0].clientX;
        isDragging = true;
    }, { passive: true });

    elem.addEventListener('touchmove', (e) => {
        if (!isDragging) return;
        currentX = e.touches[0].clientX - startX;
        
        if (currentX < 0 && currentX > -100) {
            elem.style.transform = `translateX(${currentX}px)`;
            if (swipeBg) {
                swipeBg.style.opacity = Math.min(1, Math.abs(currentX) / 50);
            }
        }
    }, { passive: true });

    elem.addEventListener('touchend', () => {
        if (!isDragging) return;
        isDragging = false;
        
        if (currentX < -50) {
            if (navigator.vibrate) navigator.vibrate(15);
            setReplyToMessage(msg);
        }
        
        elem.style.transform = 'translateX(0px)';
        if (swipeBg) swipeBg.style.opacity = '0';
        currentX = 0;
    });
}

// ACTION SHEET FOR MESSAGES
function openActionSheet(msg) {
    selectedMsgForAction = msg;
    const editBtn = document.getElementById('editSheetItem');
    if (msg.out) {
        editBtn.classList.remove('hidden');
    } else {
        editBtn.classList.add('hidden');
    }
    document.getElementById('actionSheet').classList.remove('hidden');
}

function closeActionSheet(e) {
    document.getElementById('actionSheet').classList.add('hidden');
}

function triggerReplyFromSheet() {
    closeActionSheet();
    if (selectedMsgForAction) setReplyToMessage(selectedMsgForAction);
}

function triggerEditFromSheet() {
    closeActionSheet();
    if (selectedMsgForAction && selectedMsgForAction.out) {
        startEditingMessage(selectedMsgForAction);
    }
}

function triggerDeleteFromSheet() {
    closeActionSheet();
    if (selectedMsgForAction) {
        document.getElementById('deleteModal').classList.remove('hidden');
    }
}

function closeDeleteModal() {
    document.getElementById('deleteModal').classList.add('hidden');
}

async function confirmDeleteMessage() {
    if (!selectedMsgForAction) return;
    const deleteForAll = document.getElementById('deleteForAllCheck').checked ? 1 : 0;
    
    closeDeleteModal();
    
    await fetch('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            token: token,
            message_ids: selectedMsgForAction.id,
            delete_for_all: deleteForAll
        })
    });

    const elem = document.getElementById(`msg-${selectedMsgForAction.id}`);
    if (elem) elem.closest('.msg-container').remove();
    selectedMsgForAction = null;
}

// REPLY & EDIT PREVIEW BAR CONTROLS
function setReplyToMessage(msg) {
    cancelReplyOrEdit();
    replyToMsg = msg;
    const title = document.getElementById('replyPreviewTitle');
    const text = document.getElementById('replyPreviewText');
    const author = msg.name || (msg.out ? 'Вы' : 'Собеседник');
    
    title.textContent = `Ответ на сообщение (${author})`;
    let previewText = msg.text || 'Вложение';
    if (previewText.startsWith(ENCRYPT_PREFIX)) previewText = '🔒 Зашифрованное сообщение';
    text.textContent = previewText;
    
    document.getElementById('replyPreviewBar').classList.remove('hidden');
    document.getElementById('msgInput').focus();
}

function startEditingMessage(msg) {
    cancelReplyOrEdit();
    editMsg = msg;
    const title = document.getElementById('replyPreviewTitle');
    const text = document.getElementById('replyPreviewText');
    
    title.textContent = 'Редактирование сообщения';
    let plainText = msg.text || '';
    if (decryptedCache[msg.id]) plainText = decryptedCache[msg.id];
    
    text.textContent = plainText;
    document.getElementById('msgInput').value = plainText;
    document.getElementById('replyPreviewBar').classList.remove('hidden');
    handleInputTyping();
    document.getElementById('msgInput').focus();
}

function cancelReplyOrEdit() {
    replyToMsg = null;
    editMsg = null;
    document.getElementById('replyPreviewBar').classList.add('hidden');
}

function scrollToMsg(msgId) {
    const elem = document.getElementById(`msg-${msgId}`);
    if (elem) {
        elem.scrollIntoView({ behavior: 'smooth', block: 'center' });
        elem.style.backgroundColor = '#3a3a3c';
        setTimeout(() => { elem.style.backgroundColor = ''; }, 1000);
    }
}

// DECRYPT & RENDER ATTACHMENT MEDIA (PHOTOS, VIDEOS, .MEC CIRCLE, .MEG VOICE)
async function processEncryptedAttachment(elemId, url, extInfo) {
    const elem = document.getElementById(elemId);
    if (!elem) return;

    if (decryptedCache[elemId]) {
        renderDecryptedMedia(elem, decryptedCache[elemId]);
        return;
    }

    try {
        const resp = await fetch(`/api/proxy_file?url=${encodeURIComponent(url)}`);
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
        decryptedCache[elemId] = { blobUrl, mime: header.mime, name: header.name, extInfo };

        renderDecryptedMedia(elem, decryptedCache[elemId]);

    } catch (e) {
        console.error("Failed to decrypt media:", e);
        if (elem.querySelector('.msg-file-size')) elem.querySelector('.msg-file-size').textContent = 'Ошибка расшифровки';
    }
}

function renderDecryptedMedia(elem, data) {
    const isCircle = (data.name && data.name.endsWith('.mec')) || data.mime.includes('mec') || (data.extInfo && data.extInfo.includes('mec'));
    const isVoice = (data.name && data.name.endsWith('.meg')) || data.mime.includes('meg') || (data.extInfo && data.extInfo.includes('meg'));

    if (isCircle) {
        const container = document.createElement('div');
        container.className = 'tg-circle-container';
        
        const video = document.createElement('video');
        video.className = 'tg-circle-video';
        video.src = data.blobUrl;
        video.loop = true;
        video.playsInline = true;
        video.setAttribute('playsinline', '');
        video.setAttribute('webkit-playsinline', '');
        video.autoplay = true;

        const overlay = document.createElement('div');
        overlay.className = 'tg-circle-overlay';

        container.appendChild(video);
        container.appendChild(overlay);

        container.onclick = () => {
            video.muted = !video.muted;
            if (video.paused) video.play();
        };

        elem.replaceWith(container);

    } else if (isVoice) {
        const container = document.createElement('div');
        container.className = 'tg-voice-container';

        const audio = new Audio(data.blobUrl);
        
        container.innerHTML = `
            <div class="tg-voice-play-btn">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </div>
            <div class="tg-voice-wave-wrap">
                <div class="tg-voice-waveform">
                    <div class="tg-voice-bar active" style="height:40%"></div>
                    <div class="tg-voice-bar active" style="height:70%"></div>
                    <div class="tg-voice-bar active" style="height:100%"></div>
                    <div class="tg-voice-bar active" style="height:60%"></div>
                    <div class="tg-voice-bar" style="height:80%"></div>
                    <div class="tg-voice-bar" style="height:50%"></div>
                    <div class="tg-voice-bar" style="height:90%"></div>
                    <div class="tg-voice-bar" style="height:30%"></div>
                </div>
                <div class="tg-voice-info">
                    <span class="v-time">0:00</span>
                    <span>🎤 Голосовое</span>
                </div>
            </div>
        `;

        const playBtn = container.querySelector('.tg-voice-play-btn');
        const timeStr = container.querySelector('.v-time');

        audio.onloadedmetadata = () => {
            const m = Math.floor(audio.duration / 60);
            const s = Math.floor(audio.duration % 60).toString().padStart(2, '0');
            timeStr.textContent = `${m}:${s}`;
        };

        audio.ontimeupdate = () => {
            const cur = Math.floor(audio.currentTime);
            const m = Math.floor(cur / 60);
            const s = Math.floor(cur % 60).toString().padStart(2, '0');
            timeStr.textContent = `${m}:${s}`;
        };

        audio.onended = () => {
            playBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        };

        playBtn.onclick = () => {
            if (audio.paused) {
                audio.play();
                playBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`;
            } else {
                audio.pause();
                playBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
            }
        };

        elem.replaceWith(container);

    } else if (data.mime.startsWith('image/')) {
        const img = document.createElement('img');
        img.className = 'msg-photo';
        img.src = data.blobUrl;
        elem.replaceWith(img);
    } else if (data.mime.startsWith('video/')) {
        const vid = document.createElement('video');
        vid.className = 'msg-video';
        vid.src = data.blobUrl;
        vid.controls = true;
        elem.replaceWith(vid);
    } else {
        if (elem.querySelector('.msg-file-size')) {
            elem.querySelector('.msg-file-size').textContent = 'Расшифровано (нажмите для скачивания)';
            elem.onclick = () => {
                const a = document.createElement('a');
                a.href = data.blobUrl;
                a.download = data.name || 'file';
                a.click();
            };
        }
    }
}

function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

// INPUT TYPING TOGGLE MEDIA / SEND BUTTONS
function handleInputTyping() {
    const val = document.getElementById('msgInput').value.trim();
    const sendBtn = document.getElementById('sendBtn');
    const voiceBtn = document.getElementById('voiceRecBtn');
    const circleBtn = document.getElementById('circleRecBtn');

    if (val.length > 0 || editMsg) {
        sendBtn.classList.remove('hidden');
        voiceBtn.classList.add('hidden');
        circleBtn.classList.add('hidden');
    } else {
        sendBtn.classList.add('hidden');
        voiceBtn.classList.remove('hidden');
        circleBtn.classList.remove('hidden');
    }
}

// SEND / EDIT MESSAGE LOGIC
async function sendMessage() {
    const input = document.getElementById('msgInput');
    const text = input.value.trim();
    if (!text || !currentPeer) return;

    const btn = document.getElementById('sendBtn'); btn.disabled = true;

    if (editMsg) {
        let sendText = text;
        if (encryptionEnabled) {
            const peerKey = await getPeerPubKey(currentPeer);
            if (peerKey) {
                const plainBuf = new TextEncoder().encode(text).buffer;
                const encObj = await clientEncryptData(peerKey, plainBuf);
                sendText = ENCRYPT_PREFIX + JSON.stringify(encObj);
            }
        }

        await fetch('/api/edit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, peer_id: currentPeer, message_id: editMsg.id, text: sendText })
        });

        decryptedCache[editMsg.id] = text;
        cancelReplyOrEdit();
        input.value = '';
        btn.disabled = false;
        handleInputTyping();
        loadMessages();
        return;
    }

    let sendText = text;
    if (encryptionEnabled) {
        const peerKey = await getPeerPubKey(currentPeer);
        if (peerKey) {
            const plainBuf = new TextEncoder().encode(text).buffer;
            const encObj = await clientEncryptData(peerKey, plainBuf);
            sendText = ENCRYPT_PREFIX + JSON.stringify(encObj);
        }
    }

    const payload = {
        token,
        peer_id: currentPeer,
        text: sendText
    };

    if (replyToMsg) {
        payload.reply_to = replyToMsg.id;
    }

    await fetch('/api/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    input.value = '';
    btn.disabled = false;
    cancelReplyOrEdit();
    handleInputTyping();
    loadMessages();
}

// SUPPORTED MEDIA RECORDER MIME TYPES FOR ANDROID / ALL BROWSERS
function getSupportedMimeType(kind) {
    if (kind === 'video') {
        const types = [
            'video/webm;codecs=vp8,opus',
            'video/webm',
            'video/mp4',
            'video/3gpp'
        ];
        for (let t of types) {
            if (window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t;
        }
        return '';
    } else {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/mp4',
            'audio/aac',
            'audio/ogg'
        ];
        for (let t of types) {
            if (window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t;
        }
        return '';
    }
}

// RECORDING VOICE MESSAGES (.MEG)
let voiceRecorder = null;
let voiceChunks = [];
let voiceTimerInterval = null;
let voiceSeconds = 0;

async function startVoiceRecording() {
    try {
        const mimeType = getSupportedMimeType('audio');
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        voiceChunks = [];
        const options = mimeType ? { mimeType } : {};
        voiceRecorder = new MediaRecorder(stream, options);

        voiceRecorder.ondataavailable = e => {
            if (e.data && e.data.size > 0) voiceChunks.push(e.data);
        };
        voiceRecorder.start(100);

        document.getElementById('inputAreaNormal').classList.add('hidden');
        document.getElementById('inputAreaVoice').classList.remove('hidden');

        voiceSeconds = 0;
        document.getElementById('voiceTimer').textContent = '0:00';
        voiceTimerInterval = setInterval(() => {
            voiceSeconds++;
            const m = Math.floor(voiceSeconds / 60);
            const s = (voiceSeconds % 60).toString().padStart(2, '0');
            document.getElementById('voiceTimer').textContent = `${m}:${s}`;
        }, 1000);

    } catch(e) {
        console.error(e);
        alert("Ошибка доступа к микрофону");
    }
}

function cancelVoiceRecording() {
    if (voiceRecorder && voiceRecorder.state !== 'inactive') voiceRecorder.stop();
    if (voiceTimerInterval) clearInterval(voiceTimerInterval);
    document.getElementById('inputAreaVoice').classList.add('hidden');
    document.getElementById('inputAreaNormal').classList.remove('hidden');
}

async function stopAndSendVoiceRecording() {
    if (!voiceRecorder) return;
    
    voiceRecorder.onstop = async () => {
        if (voiceTimerInterval) clearInterval(voiceTimerInterval);
        document.getElementById('inputAreaVoice').classList.add('hidden');
        document.getElementById('inputAreaNormal').classList.remove('hidden');

        showUploadStatus("🔐 Шифрование и отправка голосового...");
        try {
            const blob = new Blob(voiceChunks, { type: voiceRecorder.mimeType || 'audio/webm' });
            await uploadEncryptedMedia(blob, `voice_${Date.now()}.meg`, blob.type || 'audio/webm');
        } finally {
            hideUploadStatus();
        }
    };

    voiceRecorder.stop();
}

// RECORDING CIRCLE VIDEO MESSAGES (.MEC) WITH CAMERA SWITCH & TORCH
let circleRecorder = null;
let circleChunks = [];
let circleStream = null;
let circleTimerInterval = null;
let circleSeconds = 0;
let circleFacingMode = 'user'; // 'user' (front) or 'environment' (back)
let isTorchOn = false;

async function getCircleMediaStream() {
    // Android Robust getUserMedia fallback ladder
    const videoConstraints = {
        facingMode: circleFacingMode,
        width: { ideal: 480 },
        height: { ideal: 480 }
    };

    try {
        return await navigator.mediaDevices.getUserMedia({ video: videoConstraints, audio: true });
    } catch(e1) {
        try {
            return await navigator.mediaDevices.getUserMedia({ video: { facingMode: circleFacingMode }, audio: true });
        } catch(e2) {
            return await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        }
    }
}

async function startCircleRecording() {
    try {
        circleStream = await getCircleMediaStream();
        circleChunks = [];
        
        const videoElem = document.getElementById('circleVideoPreview');
        videoElem.srcObject = circleStream;
        videoElem.play();

        // Style mirror for front camera
        if (circleFacingMode === 'user') {
            videoElem.style.transform = 'scaleX(-1)';
        } else {
            videoElem.style.transform = 'none';
        }

        document.getElementById('circleModal').classList.remove('hidden');

        const mimeType = getSupportedMimeType('video');
        const options = mimeType ? { mimeType } : {};
        circleRecorder = new MediaRecorder(circleStream, options);

        circleRecorder.ondataavailable = e => {
            if (e.data && e.data.size > 0) circleChunks.push(e.data);
        };
        circleRecorder.start(100);

        circleSeconds = 0;
        document.getElementById('circleTimer').textContent = '0:00';
        circleTimerInterval = setInterval(() => {
            circleSeconds++;
            const m = Math.floor(circleSeconds / 60);
            const s = (circleSeconds % 60).toString().padStart(2, '0');
            document.getElementById('circleTimer').textContent = `${m}:${s}`;
        }, 1000);

    } catch(e) {
        console.error("Circle Record Error:", e);
        alert("Ошибка доступа к камере или микрофону!");
    }
}

async function switchCircleCamera() {
    if (circleTimerInterval) clearInterval(circleTimerInterval);
    circleFacingMode = (circleFacingMode === 'user') ? 'environment' : 'user';
    
    if (circleStream) {
        circleStream.getTracks().forEach(t => t.stop());
    }
    
    startCircleRecording();
}

async function toggleCircleTorch() {
    if (!circleStream) return;
    const videoTrack = circleStream.getVideoTracks()[0];
    if (!videoTrack) return;

    try {
        const capabilities = videoTrack.getCapabilities ? videoTrack.getCapabilities() : {};
        if (capabilities.torch) {
            isTorchOn = !isTorchOn;
            await videoTrack.applyConstraints({ advanced: [{ torch: isTorchOn }] });
            const torchBtn = document.getElementById('circleTorchBtn');
            if (torchBtn) {
                if (isTorchOn) torchBtn.classList.add('active');
                else torchBtn.classList.remove('active');
            }
        } else {
            alert("Фонарик не поддерживается этой камерой");
        }
    } catch(e) {
        alert("Не удалось включить фонарик");
    }
}

function cancelCircleRecording() {
    if (circleRecorder && circleRecorder.state !== 'inactive') circleRecorder.stop();
    if (circleStream) circleStream.getTracks().forEach(t => t.stop());
    if (circleTimerInterval) clearInterval(circleTimerInterval);
    document.getElementById('circleModal').classList.add('hidden');
}

async function stopAndSendCircleRecording() {
    if (!circleRecorder) return;

    circleRecorder.onstop = async () => {
        if (circleStream) circleStream.getTracks().forEach(t => t.stop());
        if (circleTimerInterval) clearInterval(circleTimerInterval);
        document.getElementById('circleModal').classList.add('hidden');

        showUploadStatus("🔐 Шифрование и отправка кружочка...");
        try {
            const blob = new Blob(circleChunks, { type: circleRecorder.mimeType || 'video/webm' });
            await uploadEncryptedMedia(blob, `circle_${Date.now()}.mec`, blob.type || 'video/webm');
        } finally {
            hideUploadStatus();
        }
    };

    circleRecorder.stop();
}

// HELPER: ENCRYPT & UPLOAD MEDIA BINARY (.MEC, .MEG, PHOTOS, FILES)
async function uploadEncryptedMedia(blob, filename, mimeType) {
    if (!currentPeer) return;

    const peerKey = await getPeerPubKey(currentPeer);
    if (!peerKey) {
        alert("У собеседника нет публичного ключа шифрования!");
        return;
    }

    const fileArrayBuf = await blob.arrayBuffer();

    // Encrypt payload locally
    const encObj = await clientEncryptData(peerKey, fileArrayBuf);
    const payloadBuf = b64ToBuf(encObj.payload);

    // Envelope Header JSON
    const headerStr = JSON.stringify({
        k1: encObj.k1,
        k2: encObj.k2,
        mime: mimeType,
        name: filename
    });
    const headerBytes = new TextEncoder().encode(headerStr);

    const totalLen = 4 + headerBytes.byteLength + payloadBuf.byteLength;
    const resultBuf = new ArrayBuffer(totalLen);
    const view = new DataView(resultBuf);
    
    view.setUint32(0, headerBytes.byteLength);

    const u8 = new Uint8Array(resultBuf);
    u8.set(headerBytes, 4);
    u8.set(new Uint8Array(payloadBuf), 4 + headerBytes.byteLength);

    const encBlob = new Blob([resultBuf], { type: 'application/octet-stream' });

    // DETERMINE EXTENSION FOR VK ENCRYPTED DOC TITLE
    let ext = 'enc';
    if (filename.endsWith('.mec') || mimeType.includes('mec')) ext = 'mec';
    else if (filename.endsWith('.meg') || mimeType.includes('meg')) ext = 'meg';
    else if (mimeType.startsWith('image/')) ext = 'meow';
    else if (mimeType.startsWith('video/')) ext = 'mur';

    const vkFileName = `enc_${Date.now()}.${ext}`;

    const formData = new FormData();
    formData.append('token', token);
    formData.append('peer_id', currentPeer);
    formData.append('file', encBlob, vkFileName);

    await fetch('/api/upload_encrypted_doc', { method: 'POST', body: formData });
    loadMessages();
}

// HANDLE GENERAL FILE / PHOTO UPLOAD
async function handleFile(e) {
    const file = e.target.files[0];
    if (!file || !currentPeer) return;

    const btn = document.getElementById('sendBtn'); if (btn) btn.disabled = true;

    showUploadStatus("🔐 Шифрование и загрузка файла...");

    try {
        if (encryptionEnabled) {
            const peerKey = await getPeerPubKey(currentPeer);
            if (peerKey) {
                await uploadEncryptedMedia(file, file.name, file.type || 'application/octet-stream');
                if (btn) btn.disabled = false;
                e.target.value = '';
                return;
            }
        }

        // Unencrypted normal upload
        const formData = new FormData();
        formData.append('token', token);
        formData.append('peer_id', currentPeer);
        formData.append('file', file);
        await fetch('/api/upload_normal', { method: 'POST', body: formData });

        if (btn) btn.disabled = false;
        e.target.value = '';
        loadMessages();
    } finally {
        hideUploadStatus();
    }
}

function toggleEncrypt() {
    encryptionEnabled = !encryptionEnabled;
    const btn = document.getElementById('encryptBtn');
    if (encryptionEnabled) {
        btn.classList.add('active');
    } else {
        btn.classList.remove('active');
    }
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => { if (currentPeer) loadMessages(); }, 2500);
}

function logout() {
    localStorage.clear();
    location.reload();
}

function showDialogs() {
    document.getElementById('chatScreen').classList.remove('active');
    loadDialogs();
}

document.getElementById('msgInput').addEventListener('keypress', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// Auto Login & Initialize Client Keys
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
    """Retrieve public key and encrypted private key for user from Firebase"""
    stored = firebase_get(f"keys/{vk_id}")
    if stored:
        return jsonify(stored)
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/keys/<vk_id>', methods=['POST'])
def save_key(vk_id):
    """Store public key and locally-encrypted private key in Firebase"""
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
            'attachments': msg.get('attachments', []),
            'reply_message': msg.get('reply_message')
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
    result = vk_request('messages.edit', token, peer_id=peer_id, message_id=message_id, message=text)
    return jsonify({'result': result})


@app.route('/api/delete', methods=['POST'])
def delete_message():
    token = request.json.get('token')
    message_ids = request.json.get('message_ids')
    delete_for_all = request.json.get('delete_for_all', 1)
    result = vk_request('messages.delete', token, message_ids=str(message_ids), delete_for_all=delete_for_all)
    return jsonify({'result': result})


@app.route('/api/upload_encrypted_doc', methods=['POST'])
def upload_encrypted_doc():
    """Upload pre-encrypted file binary directly as VK Document attachment"""
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
    """Normal unencrypted upload proxy"""
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

    save_result = vk_result = vk_request('docs.save', token, file=upload_resp.get('file'), title=filename)
    if isinstance(save_result, dict) and 'doc' in save_result:
        doc = save_result['doc']
        attachment = f"doc{doc['owner_id']}_{doc['id']}"
        vk_request('messages.send', token, peer_id=peer_id, attachment=attachment, random_id=0)
        return jsonify({'ok': True})

    return jsonify({'error': 'Upload failed'}), 400


@app.route('/api/proxy_file')
def proxy_file():
    """Proxy encrypted attachments to bypass browser CORS on VK CDN"""
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
