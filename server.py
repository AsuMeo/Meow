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
.app{height:100vh;display:flex;flex-direction:column}

/* Login */
.login-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;z-index:100}
.login-screen h1{font-size:26px;margin-bottom:6px;font-weight:700;color:#fff}
.login-screen p{color:#888;margin-bottom:24px;font-size:13px;text-align:center;max-width:320px}
.badge-e2e{background:#1b381e;color:#4caf50;border:1px solid #2e7d32;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:600;margin-bottom:20px;display:inline-flex;align-items:center;gap:6px}
.token-input,.pass-input{width:100%;max-width:360px;padding:14px 16px;border:none;border-radius:14px;background:#161616;color:#fff;font-size:15px;margin-bottom:12px;outline:none;border:1px solid #2c2c2c}
.token-input::placeholder,.pass-input::placeholder{color:#666}
.btn{width:100%;max-width:360px;padding:14px;border:none;border-radius:14px;background:#fff;color:#000;font-size:16px;font-weight:600;cursor:pointer;margin-bottom:8px}
.btn:active{opacity:.8}
.btn-secondary{background:transparent;color:#fff;border:1px solid #333}
.btn-green{background:#4caf50;color:#fff}

/* Header */
.header{height:52px;background:#0d0d0d;display:flex;align-items:center;padding:0 12px;border-bottom:1px solid #1c1c1c;flex-shrink:0}
.header-back{width:36px;height:36px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%}
.header-back:active{background:#222}
.header-avatar{width:34px;height:34px;border-radius:50%;object-fit:cover;margin-right:10px;background:#222}
.header-info{flex:1;min-width:0}
.header-title{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.header-subtitle{font-size:12px;color:#888;display:flex;align-items:center;gap:4px}
.header-subtitle.e2e-on{color:#4caf50}
.header-actions{display:flex;gap:4px}
.header-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;color:#777}
.header-btn.active{color:#4caf50}

/* Dialogs */
.dialogs-screen{flex:1;display:flex;flex-direction:column;overflow:hidden}
.dialogs-list{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.dialog{display:flex;align-items:center;padding:12px 14px;cursor:pointer;border-bottom:1px solid #111}
.dialog:active{background:#111}
.dialog-avatar{width:50px;height:50px;border-radius:50%;object-fit:cover;margin-right:12px;flex-shrink:0;background:#222}
.dialog-info{flex:1;min-width:0}
.dialog-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px}
.dialog-name{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;margin-right:8px}
.dialog-time{font-size:11px;color:#666;flex-shrink:0}
.dialog-bottom{display:flex;align-items:center;gap:6px}
.dialog-preview{font-size:13px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.dialog-unread{min-width:18px;height:18px;border-radius:50%;background:#fff;color:#000;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;padding:0 5px;flex-shrink:0}
.dialog-lock{color:#4caf50;font-size:13px}

/* Chat */
.chat-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;z-index:10;transform:translateX(100%);transition:transform .2s ease}
.chat-screen.active{transform:translateX(0)}
.messages{flex:1;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:6px;-webkit-overflow-scrolling:touch}
.msg{max-width:82%;padding:8px 12px;border-radius:16px;font-size:14px;line-height:1.4;word-wrap:break-word;position:relative}
.msg-in{align-self:flex-start;background:#1c1c1e;border-bottom-left-radius:4px}
.msg-out{align-self:flex-end;background:#2c2c2e;border-bottom-right-radius:4px}
.msg-encrypted{border:1px solid #2e7d32;background:#0d2610}
.msg-out.msg-encrypted{background:#113815}
.msg-author{font-size:11px;color:#4caf50;font-weight:600;margin-bottom:2px}
.msg-text{color:#fff}
.msg-time{font-size:10px;color:#888;margin-top:4px;text-align:right}
.msg-photo{max-width:100%;border-radius:12px;margin-top:6px;display:block;max-height:280px;object-fit:cover;cursor:pointer;background:#111}
.msg-video{max-width:100%;border-radius:12px;margin-top:6px;display:block;max-height:280px;background:#000}
.msg-file{background:rgba(255,255,255,.05);padding:10px;border-radius:10px;margin-top:6px;display:flex;align-items:center;gap:10px}
.msg-file-icon{font-size:22px}
.msg-file-info{flex:1;min-width:0}
.msg-file-name{font-size:13px;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.msg-file-size{font-size:11px;color:#888}

/* Input */
.input-area{min-height:54px;background:#0d0d0d;border-top:1px solid #1a1a1a;display:flex;align-items:flex-end;padding:8px;gap:6px}
.input-attach{width:38px;height:38px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;flex-shrink:0;color:#aaa}
.input-attach:active{background:#222}
.message-input{flex:1;padding:10px 14px;border:none;border-radius:20px;background:#1c1c1e;color:#fff;font-size:14px;outline:none;resize:none;max-height:100px;font-family:inherit;line-height:1.4;border:1px solid #2a2a2c}
.send-btn{width:38px;height:38px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;border:none;color:#000}
.send-btn:active{transform:scale(.92)}
.send-btn:disabled{background:#222;color:#555}

/* Bottom nav */
.bottom-nav{height:50px;background:#0d0d0d;border-top:1px solid #1a1a1a;display:flex;justify-content:space-around;align-items:center;flex-shrink:0}
.nav-item{flex:1;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;cursor:pointer;color:#666}
.nav-item.active{color:#fff}
.nav-item span{font-size:10px}

/* Modal */
.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.85);display:flex;align-items:center;justify-content:center;z-index:200;padding:20px}
.modal-content{background:#161616;border-radius:20px;padding:24px;width:100%;max-width:380px;border:1px solid #282828}
.modal-title{font-size:18px;font-weight:600;margin-bottom:10px;color:#fff}
.modal-text{font-size:13px;color:#aaa;margin-bottom:20px;line-height:1.5}

.file-input{display:none}
.hidden{display:none!important}
.loader{border:2px solid #333;border-top:2px solid #4caf50;border-radius:50%;width:16px;height:16px;animation:spin 1s linear infinite;display:inline-block;vertical-align:middle;margin-right:6px}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
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

<div class="input-area">
<div class="input-attach" onclick="document.getElementById('fileInput').click()">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
</div>
<input type="file" class="file-input" id="fileInput" accept="image/*,video/*,*/*" onchange="handleFile(event)">
<textarea class="message-input" id="msgInput" placeholder="Сообщение..." rows="1"></textarea>
<button class="send-btn" id="sendBtn" onclick="sendMessage()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>
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
            // Decrypt private key locally on device
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
        // Generate new RSA keypair locally on device
        const keyPair = await window.crypto.subtle.generateKey(
            { name: "RSA-OAEP", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
            true, ["encrypt", "decrypt"]
        );

        const pubJwk = await window.crypto.subtle.exportKey("jwk", keyPair.publicKey);
        const privJwk = await window.crypto.subtle.exportKey("jwk", keyPair.privateKey);
        const pubJwkStr = JSON.stringify(pubJwk);

        // Encrypt private key locally before uploading backup to Firebase
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
    
    // If peer is self
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
    // Generate AES Session Key
    const sessionKey = await window.crypto.subtle.generateKey(
        { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]
    );

    // Encrypt payload with AES Session Key
    const encPayload = await encryptAESGCM(sessionKey, plainBuf);

    // Export raw session key
    const rawSession = await window.crypto.subtle.exportKey("raw", sessionKey);

    // Encrypt raw session key with Peer Public RSA Key
    const encKeyPeer = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, peerKey, rawSession);

    // Encrypt raw session key with Local Self Public RSA Key
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

    // Try decrypting k1 then k2 with local private key
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

    // Check peer key
    const peerKey = await getPeerPubKey(currentPeer);
    const status = document.getElementById('chatEncryptStatus');
    if (peerKey) {
        status.textContent = '🔒 Защищено (E2EE)';
        status.style.color = '#4caf50';
    } else {
        status.textContent = 'Обычный чат (нет ключа у собеседника)';
        status.style.color = '#888';
    }

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
    const container = document.getElementById('messages'); container.innerHTML = '';
    if (data.messages) {
        const msgs = data.messages.reverse();
        for (const m of msgs) {
            await renderMessageItem(container, m);
        }
    }
    container.scrollTop = container.scrollHeight;
}

async function renderMessageItem(container, msg) {
    const div = document.createElement('div');
    const isEncrypted = msg.text && msg.text.startsWith(ENCRYPT_PREFIX);
    div.className = 'msg ' + (msg.out ? 'msg-out' : 'msg-in') + (isEncrypted ? ' msg-encrypted' : '');
    div.id = 'msg-' + msg.id;

    let html = '';
    if (!msg.out && msg.name) html += `<div class="msg-author">${escapeHtml(msg.name)}</div>`;

    let displayText = msg.text || '';
    if (isEncrypted) {
        if (decryptedCache[msg.id]) {
            displayText = decryptedCache[msg.id];
        } else {
            displayText = '🔒 Расшифровка...';
            // Decrypt asynchronously
            setTimeout(async () => {
                try {
                    const encObj = JSON.parse(msg.text.substring(ENCRYPT_PREFIX.length));
                    const decBuf = await clientDecryptData(encObj);
                    if (decDecBuf = decBuf) {
                        const plainText = new TextDecoder().decode(decDecBuf);
                        decryptedCache[msg.id] = plainText;
                        const textElem = document.querySelector(`#msg-${msg.id} .msg-text`);
                        if (textElem) textElem.textContent = plainText;
                    }
                } catch(e) {
                    const textElem = document.querySelector(`#msg-${msg.id} .msg-text`);
                    if (textElem) textElem.textContent = '🔒 Не удалось расшифровать';
                }
            }, 10);
        }
    }

    html += `<div class="msg-text">${escapeHtml(displayText)}</div>`;

    // Process attachments
    if (msg.attachments) {
        for (const a of msg.attachments) {
            if (a.type === 'photo') {
                const p = a.photo?.sizes?.find(s => s.type === 'x') || a.photo?.sizes?.[a.photo?.sizes?.length - 1];
                if (p) html += `<img class="msg-photo" src="${p.url}">`;
            }
            if (a.type === 'doc') {
                const doc = a.doc;
                if (doc.title && (doc.title.startsWith('enc_') || doc.ext === 'meow' || doc.ext === 'mur' || doc.ext === 'enc')) {
                    const docId = `doc_${doc.owner_id}_${doc.id}`;
                    html += `<div class="msg-file" id="${docId}"><span class="msg-file-icon">🔒</span><div class="msg-file-info"><div class="msg-file-name">Зашифрованный медиафайл</div><div class="msg-file-size">Локальная расшифровка...</div></div></div>`;
                    
                    // Decrypt media asynchronously
                    setTimeout(() => processEncryptedAttachment(docId, doc.url), 10);
                } else {
                    html += `<div class="msg-file"><span class="msg-file-icon">📎</span><div class="msg-file-info"><div class="msg-file-name">${escapeHtml(doc.title || 'Файл')}</div><div class="msg-file-size">${(doc.size / 1024).toFixed(1)} KB</div></div></div>`;
                }
            }
        }
    }

    html += `<div class="msg-time">${msg.date ? new Date(msg.date * 1000).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : ''}</div>`;
    div.innerHTML = html;
    container.appendChild(div);
}

// Fetch & Decrypt Encrypted Attachment on Phone
async function processEncryptedAttachment(elemId, url) {
    const elem = document.getElementById(elemId);
    if (!elem) return;

    if (decryptedCache[elemId]) {
        renderDecryptedMedia(elem, decryptedCache[elemId]);
        return;
    }

    try {
        // Fetch binary through local proxy to avoid CORS
        const resp = await fetch(`/api/proxy_file?url=${encodeURIComponent(url)}`);
        const encArrayBuf = await resp.arrayBuffer();

        // Read binary header size (first 4 bytes uint32)
        const view = new DataView(encArrayBuf);
        const headerLen = view.getUint32(0);
        
        const headerJsonBytes = new Uint8Array(encArrayBuf, 4, headerLen);
        const headerStr = new TextDecoder().decode(headerJsonBytes);
        const header = JSON.parse(headerStr);

        const encPayload = encArrayBuf.slice(4 + headerLen);

        // Decrypt payload with client RSA private key
        const decPayloadBuf = await clientDecryptData({
            k1: header.k1,
            k2: header.k2,
            payload: bufToB64(encPayload)
        });

        if (!decPayloadBuf) throw new Error("Decryption failed");

        const blob = new Blob([decPayloadBuf], { type: header.mime || 'application/octet-stream' });
        const blobUrl = URL.createObjectURL(blob);
        decryptedCache[elemId] = { blobUrl, mime: header.mime, name: header.name };

        renderDecryptedMedia(elem, decryptedCache[elemId]);

    } catch (e) {
        console.error("Failed to decrypt media:", e);
        elem.querySelector('.msg-file-size').textContent = 'Ошибка расшифровки';
    }
}

function renderDecryptedMedia(elem, data) {
    if (data.mime.startsWith('image/')) {
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
        elem.querySelector('.msg-file-size').textContent = 'Расшифровано (нажмите для скачивания)';
        elem.onclick = () => {
            const a = document.createElement('a');
            a.href = data.blobUrl;
            a.download = data.name || 'file';
            a.click();
        };
    }
}

function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

async function sendMessage() {
    const input = document.getElementById('msgInput');
    const text = input.value.trim();
    if (!text || !currentPeer) return;

    const btn = document.getElementById('sendBtn'); btn.disabled = true;
    let sendText = text;

    if (encryptionEnabled) {
        const peerKey = await getPeerPubKey(currentPeer);
        if (peerKey) {
            // Encrypt text message locally on phone
            const plainBuf = new TextEncoder().encode(text).buffer;
            const encObj = await clientEncryptData(peerKey, plainBuf);
            sendText = ENCRYPT_PREFIX + JSON.stringify(encObj);
        }
    }

    await fetch('/api/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, peer_id: currentPeer, text: sendText }) });
    input.value = ''; btn.disabled = false;
    
    // Add message locally
    addLocalMessage(sendText);
}

function addLocalMessage(text) {
    const container = document.getElementById('messages');
    renderMessageItem(container, {
        id: 'loc_' + Date.now(),
        text: text,
        out: 1,
        date: Math.floor(Date.now() / 1000)
    });
    container.scrollTop = container.scrollHeight;
}

// Encrypt & Upload File 100% locally on phone
async function handleFile(e) {
    const file = e.target.files[0];
    if (!file || !currentPeer) return;

    const btn = document.getElementById('sendBtn'); btn.disabled = true;

    if (encryptionEnabled) {
        const peerKey = await getPeerPubKey(currentPeer);
        if (peerKey) {
            // Read file into ArrayBuffer locally
            const fileArrayBuf = await file.arrayBuffer();

            // Encrypt payload locally
            const encObj = await clientEncryptData(peerKey, fileArrayBuf);
            const payloadBuf = b64ToBuf(encObj.payload);

            // Construct Binary File with Header
            const headerStr = JSON.stringify({
                k1: encObj.k1,
                k2: encObj.k2,
                mime: file.type,
                name: file.name
            });
            const headerBytes = new TextEncoder().encode(headerStr);

            const totalLen = 4 + headerBytes.byteLength + payloadBuf.byteLength;
            const resultBuf = new ArrayBuffer(totalLen);
            const view = new DataView(resultBuf);
            
            // 4 bytes uint32 header length
            view.setUint32(0, headerBytes.byteLength);

            const u8 = new Uint8Array(resultBuf);
            u8.set(headerBytes, 4);
            u8.set(new Uint8Array(payloadBuf), 4 + headerBytes.byteLength);

            // Create encrypted blob
            const encBlob = new Blob([resultBuf], { type: 'application/octet-stream' });
            
            // Extension tag
            let ext = 'enc';
            if (file.type.startsWith('image/')) ext = 'meow';
            else if (file.type.startsWith('video/')) ext = 'mur';

            const formData = new FormData();
            formData.append('token', token);
            formData.append('peer_id', currentPeer);
            formData.append('file', encBlob, `enc_${Date.now()}.${ext}`);

            await fetch('/api/upload_encrypted_doc', { method: 'POST', body: formData });
            btn.disabled = false;
            loadMessages();
            return;
        }
    }

    // Unencrypted normal upload
    const formData = new FormData();
    formData.append('token', token);
    formData.append('peer_id', currentPeer);
    formData.append('file', file);
    await fetch('/api/upload_normal', { method: 'POST', body: formData });

    btn.disabled = false;
    loadMessages();
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
            'attachments': msg.get('attachments', [])
        })
    return jsonify({'messages': messages})


@app.route('/api/send', methods=['POST'])
def send_message():
    token = request.json.get('token')
    peer_id = request.json.get('peer_id')
    text = request.json.get('text', '')
    result = vk_request('messages.send', token, peer_id=peer_id, message=text, random_id=0)
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

    save_result = vk_request('docs.save', token, file=upload_resp.get('file'), title=filename)
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
