import os
import re
import json
import base64
import hashlib
import secrets
import requests
from io import BytesIO
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, request, jsonify, session
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', os.urandom(32).hex())

VK_API = "https://api.vk.com/method"
API_VERSION = "5.199"

# Firebase config from env
FIREBASE_DB_URL = os.environ.get('FIREBASE_DB_URL', '')
FIREBASE_API_KEY = os.environ.get('FIREBASE_API_KEY', '')


def firebase_get(path):
    """GET from Firebase Realtime Database"""
    if not FIREBASE_DB_URL:
        return None
    url = f"{FIREBASE_DB_URL}/{path}.json"
    try:
        resp = requests.get(url, timeout=10)
        return resp.json()
    except:
        return None


def firebase_put(path, data):
    """PUT to Firebase Realtime Database"""
    if not FIREBASE_DB_URL:
        return False
    url = f"{FIREBASE_DB_URL}/{path}.json"
    try:
        resp = requests.put(url, json=data, timeout=10)
        return resp.status_code == 200
    except:
        return False


def derive_key(password, token):
    """Derive encryption key from password + VK token"""
    salt = hashlib.sha256(token.encode()).digest()[:16]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key


def encrypt_data(key, data):
    """Encrypt data with AES-GCM"""
    aesgcm = AESGCM(base64.urlsafe_b64decode(key))
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, data.encode('utf-8'), None)
    return base64.b64encode(nonce + ciphertext).decode('utf-8')


def decrypt_data(key, encrypted_data):
    """Decrypt data with AES-GCM"""
    try:
        raw = base64.b64decode(encrypted_data)
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(base64.urlsafe_b64decode(key))
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    except:
        return None


def get_or_create_keys(vk_id, token, password):
    """Get or create encryption keys for user"""
    key = derive_key(password, token)

    # Check if keys exist in Firebase
    stored = firebase_get(f"keys/{vk_id}")
    if stored and stored.get('public_key'):
        return {
            'key': key,
            'public_key': stored['public_key'],
            'private_key_enc': stored.get('private_key_enc')
        }

    # Generate new key pair
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    # Encrypt private key with derived key
    private_key_enc = encrypt_data(key, private_pem)

    # Store in Firebase
    firebase_put(f"keys/{vk_id}", {
        'public_key': public_pem,
        'private_key_enc': private_key_enc,
        'created_at': datetime.now().isoformat()
    })

    return {
        'key': key,
        'public_key': public_pem,
        'private_key_enc': private_key_enc
    }


def get_peer_public_key(peer_vk_id):
    """Get peer's public key from Firebase"""
    stored = firebase_get(f"keys/{peer_vk_id}")
    if stored:
        return stored.get('public_key')
    return None


def encrypt_for_peer(public_key_pem, message):
    """Encrypt message for peer using their public key + AES session key"""
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import serialization, hashes

    public_key = serialization.load_pem_public_key(public_key_pem.encode())

    # Generate AES session key
    session_key = secrets.token_bytes(32)
    aesgcm = AESGCM(session_key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, message.encode('utf-8'), None)

    # Encrypt session key with RSA
    encrypted_key = public_key.encrypt(
        session_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )

    # Package: encrypted_key + nonce + ciphertext
    package = base64.b64encode(encrypted_key).decode() + ":" + base64.b64encode(nonce + ciphertext).decode()
    return package


def decrypt_from_peer(private_key_pem, package):
    """Decrypt message using private key"""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import serialization, hashes

    try:
        parts = package.split(":")
        if len(parts) != 2:
            return None

        encrypted_key = base64.b64decode(parts[0])
        encrypted_data = base64.b64decode(parts[1])

        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)

        # Decrypt session key
        session_key = private_key.decrypt(
            encrypted_key,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
        )

        # Decrypt message
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        aesgcm = AESGCM(session_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        return plaintext.decode('utf-8')
    except:
        return None


def encrypt_file(key, file_bytes):
    """Encrypt file bytes"""
    aesgcm = AESGCM(base64.urlsafe_b64decode(key))
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, file_bytes, None)
    return nonce + ciphertext


def decrypt_file(key, encrypted_bytes):
    """Decrypt file bytes"""
    try:
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        aesgcm = AESGCM(base64.urlsafe_b64decode(key))
        return aesgcm.decrypt(nonce, ciphertext, None)
    except:
        return None


def vk_request(method, token, **params):
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
<title>VK Client E2EE</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#000;color:#fff;height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased}
.app{height:100vh;display:flex;flex-direction:column}

/* Login */
.login-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;z-index:100}
.login-screen h1{font-size:28px;margin-bottom:8px;font-weight:700}
.login-screen p{color:#666;margin-bottom:30px;font-size:14px}
.token-input,.pass-input{width:100%;max-width:360px;padding:14px 16px;border:none;border-radius:14px;background:#1a1a1a;color:#fff;font-size:15px;margin-bottom:10px;outline:none;border:1px solid #333}
.token-input::placeholder,.pass-input::placeholder{color:#555}
.btn{width:100%;max-width:360px;padding:14px;border:none;border-radius:14px;background:#fff;color:#000;font-size:16px;font-weight:600;cursor:pointer;margin-bottom:8px}
.btn:active{opacity:.7}
.btn-secondary{background:transparent;color:#fff;border:1px solid #444}
.btn-green{background:#4caf50;color:#fff}

/* Header */
.header{height:52px;background:#000;display:flex;align-items:center;padding:0 12px;border-bottom:1px solid #1a1a1a;flex-shrink:0}
.header-back{width:36px;height:36px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%}
.header-back:active{background:#1a1a1a}
.header-avatar{width:32px;height:32px;border-radius:50%;object-fit:cover;margin-right:10px;background:#1a1a1a}
.header-info{flex:1;min-width:0}
.header-title{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.header-subtitle{font-size:12px;color:#666}
.header-actions{display:flex;gap:4px}
.header-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;color:#fff}
.header-btn:active{background:#1a1a1a}
.header-btn.active{color:#4caf50}

/* Dialogs */
.dialogs-screen{flex:1;display:flex;flex-direction:column;overflow:hidden}
.dialogs-list{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.dialog{display:flex;align-items:center;padding:10px 14px;cursor:pointer}
.dialog:active{background:#0d0d0d}
.dialog-avatar{width:50px;height:50px;border-radius:50%;object-fit:cover;margin-right:12px;flex-shrink:0;background:#1a1a1a}
.dialog-info{flex:1;min-width:0}
.dialog-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px}
.dialog-name{font-size:15px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;margin-right:8px}
.dialog-time{font-size:11px;color:#555;flex-shrink:0}
.dialog-bottom{display:flex;align-items:center;gap:6px}
.dialog-preview{font-size:13px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.dialog-unread{min-width:18px;height:18px;border-radius:50%;background:#fff;color:#000;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;padding:0 5px;flex-shrink:0}
.dialog-lock{color:#4caf50;font-size:12px}

/* Chat */
.chat-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;z-index:10;transform:translateX(100%);transition:transform .2s ease}
.chat-screen.active{transform:translateX(0)}
.messages{flex:1;overflow-y:auto;padding:8px 12px;display:flex;flex-direction:column;gap:3px;-webkit-overflow-scrolling:touch}
.msg{max-width:82%;padding:7px 11px;border-radius:16px;font-size:14px;line-height:1.4;word-wrap:break-word;animation:msgIn .15s ease}
@keyframes msgIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.msg-in{align-self:flex-start;background:#1a1a1a;border-bottom-left-radius:4px}
.msg-out{align-self:flex-end;background:#333;border-bottom-right-radius:4px}
.msg-encrypted{border:1px solid #4caf50}
.msg-author{font-size:11px;color:#ff6b6b;font-weight:600;margin-bottom:2px}
.msg-text{color:#fff}
.msg-time{font-size:10px;color:#666;margin-top:2px;text-align:right}
.msg-photo{max-width:100%;border-radius:12px;margin-top:4px;display:block;max-height:250px;object-fit:cover}
.msg-file{background:#1a1a1a;padding:10px 14px;border-radius:12px;margin-top:4px;display:flex;align-items:center;gap:10px}
.msg-file-icon{font-size:24px}
.msg-file-info{flex:1}
.msg-file-name{font-size:13px;color:#fff}
.msg-file-size{font-size:11px;color:#666}

/* Input */
.input-area{min-height:52px;background:#000;border-top:1px solid #1a1a1a;display:flex;align-items:flex-end;padding:6px 8px;gap:4px}
.input-attach{width:40px;height:40px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;flex-shrink:0;color:#666}
.input-attach:active{background:#1a1a1a}
.message-input{flex:1;padding:9px 14px;border:none;border-radius:18px;background:#1a1a1a;color:#fff;font-size:14px;outline:none;resize:none;max-height:100px;font-family:inherit;line-height:1.4;border:1px solid #222}
.send-btn{width:40px;height:40px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;border:none;color:#000}
.send-btn:active{transform:scale(.9)}
.send-btn:disabled{background:#222;color:#555}

/* Bottom nav */
.bottom-nav{height:50px;background:#000;border-top:1px solid #1a1a1a;display:flex;justify-content:space-around;align-items:center;flex-shrink:0}
.nav-item{flex:1;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;cursor:pointer;color:#555}
.nav-item.active{color:#fff}
.nav-item span{font-size:10px}

/* Encryption toggle */
.encrypt-toggle{position:fixed;bottom:70px;right:16px;width:48px;height:48px;border-radius:50%;background:#4caf50;color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:50;box-shadow:0 4px 12px rgba(76,175,80,.4);font-size:20px;transition:all .2s}
.encrypt-toggle.off{background:#666;box-shadow:0 4px 12px rgba(102,102,102,.4)}
.encrypt-toggle:active{transform:scale(.9)}

/* Setup encryption modal */
.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.9);display:flex;align-items:center;justify-content:center;z-index:200;padding:20px}
.modal-content{background:#1a1a1a;border-radius:20px;padding:24px;width:100%;max-width:380px}
.modal-title{font-size:18px;font-weight:600;margin-bottom:12px}
.modal-text{font-size:14px;color:#aaa;margin-bottom:20px;line-height:1.5}

.file-input{display:none}
.hidden{display:none!important}
</style>
</head>
<body>
<div class="app">

<!-- Login -->
<div class="login-screen" id="loginScreen">
<h1>VK Client</h1>
<p>Шифрованные сообщения</p>
<button class="btn btn-secondary" onclick="getToken()">Получить токен VK</button>
<input type="text" class="token-input" id="tokenUrl" placeholder="Вставь ссылку с токеном...">
<input type="password" class="pass-input" id="password" placeholder="Придумай пароль для шифрования...">
<button class="btn" onclick="login()">Войти</button>
</div>

<!-- Setup Encryption -->
<div class="modal hidden" id="setupModal">
<div class="modal-content">
<div class="modal-title">Настройка шифрования</div>
<div class="modal-text">Создаём ключи шифрования. Это займёт секунду. Пароль + токен = ваш уникальный ключ. Ключи хранятся в облаке, переписка защищена.</div>
<button class="btn btn-green" onclick="setupEncryption()">Создать ключи</button>
</div>
</div>

<!-- Dialogs -->
<div class="dialogs-screen hidden" id="dialogsScreen">
<div class="header">
<img class="header-avatar" id="headerAvatar" src="" alt="">
<div class="header-info">
<div class="header-title" id="headerTitle">VK</div>
<div class="header-subtitle" id="headerStatus">онлайн</div>
</div>
<div class="header-actions">
<div class="header-btn" id="encryptBtn" onclick="toggleEncrypt()" title="Шифрование">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
</div>
</div>
</div>
<div class="dialogs-list" id="dialogsList"></div>
<div class="bottom-nav">
<div class="nav-item active" onclick="showDialogs()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
<span>Чаты</span>
</div>
<div class="nav-item">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
<span>Поиск</span>
</div>
<div class="nav-item" onclick="logout()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
<span>Выход</span>
</div>
</div>
</div>

<!-- Chat -->
<div class="chat-screen" id="chatScreen">
<div class="header">
<div class="header-back" onclick="backToDialogs()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
</div>
<img class="header-avatar" id="chatAvatar" src="" alt="">
<div class="header-info">
<div class="header-title" id="chatTitle"></div>
<div class="header-subtitle" id="chatEncryptStatus">Обычный чат</div>
</div>
</div>
<div class="messages" id="messages"></div>
<div class="input-area">
<div class="input-attach" onclick="document.getElementById('fileInput').click()">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
</div>
<input type="file" class="file-input" id="fileInput" accept="image/*,video/*" onchange="handleFile(event)">
<textarea class="message-input" id="msgInput" placeholder="Сообщение" rows="1"></textarea>
<button class="send-btn" id="sendBtn" onclick="sendMessage()">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>
</div>
</div>

</div>

<script>
let token=localStorage.getItem('vk_token');
let password=localStorage.getItem('vk_pass');
let currentPeer=null;
let currentUser=null;
let dialogsData=[];
let pollInterval=null;
let encryptionEnabled=false;
let myVkId=null;
let peerKeys={}; // cached peer public keys

const AUTH_URL='https://oauth.vk.com/authorize?client_id=2685278&scope=messages,audio,photos,video,docs,notes,pages,status,wall,groups,email,stats,notifications,offline&redirect_uri=https://oauth.vk.com/blank.html&display=page&response_type=token';

function getToken(){window.open(AUTH_URL,'_blank')}

async function login(){
const url=document.getElementById('tokenUrl').value.trim();
const pass=document.getElementById('password').value.trim();
if(!url){alert('Вставь ссылку с токеном');return}
if(!pass){alert('Придумай пароль для шифрования');return}

const res=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
const data=await res.json();
if(data.error){alert(data.error);return}

token=data.token;
currentUser=data.user;
myVkId=data.user.id;
password=pass;
localStorage.setItem('vk_token',token);
localStorage.setItem('vk_pass',pass);
localStorage.setItem('vk_user',JSON.stringify(data.user));

// Show setup encryption modal
document.getElementById('loginScreen').classList.add('hidden');
document.getElementById('setupModal').classList.remove('hidden');
}

async function setupEncryption(){
document.querySelector('#setupModal .modal-text').textContent='Создание ключей...';
const res=await fetch('/api/setup_keys',{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({token:token,vk_id:myVkId,password:password})
});
const data=await res.json();
if(data.error){alert(data.error);return}

document.getElementById('setupModal').classList.add('hidden');
showDialogsScreen();
loadDialogs();
startPolling();
encryptionEnabled=true;
updateEncryptUI();
}

function showDialogsScreen(){
document.getElementById('dialogsScreen').classList.remove('hidden');
if(currentUser){
document.getElementById('headerAvatar').src=currentUser.photo||'';
document.getElementById('headerTitle').textContent=currentUser.name||'VK';
document.getElementById('headerStatus').textContent=currentUser.online?'онлайн':'офлайн';
}
}

async function loadDialogs(){
const res=await fetch('/api/dialogs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
const data=await res.json();
if(data.error)return;
dialogsData=data.dialogs;
const list=document.getElementById('dialogsList');list.innerHTML='';
data.dialogs.forEach((d,i)=>{
const div=document.createElement('div');div.className='dialog';div.onclick=()=>openChat(i);
const time=d.date?new Date(d.date*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'}):'';
const hasKey=peerKeys[d.id]?'🔒':'';
div.innerHTML=`<img class="dialog-avatar" src="${d.photo||'https://vk.com/images/camera_100.png'}" onerror="this.src='https://vk.com/images/camera_100.png'" alt=""><div class="dialog-info"><div class="dialog-top"><div class="dialog-name">${d.name}</div><div class="dialog-time">${time}</div></div><div class="dialog-bottom"><div class="dialog-preview">${d.last_message||''}</div><span class="dialog-lock">${hasKey}</span>${d.unread>0?`<div class="dialog-unread">${d.unread}</div>`:''}</div></div>`;
list.appendChild(div)
})
}

async function openChat(index){
const d=dialogsData[index];currentPeer=d.id;
document.getElementById('chatTitle').textContent=d.name;
document.getElementById('chatAvatar').src=d.photo||'https://vk.com/images/camera_100.png';
document.getElementById('chatScreen').classList.add('active');

// Check if peer has encryption keys
const keyRes=await fetch('/api/check_peer_key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({peer_id:currentPeer})});
const keyData=await keyRes.json();
if(keyData.has_key){
peerKeys[currentPeer]=true;
document.getElementById('chatEncryptStatus').textContent='🔒 Защищено';
} else {
document.getElementById('chatEncryptStatus').textContent='Обычный чат';
}

loadMessages();
}

function backToDialogs(){
document.getElementById('chatScreen').classList.remove('active');
currentPeer=null;
}

async function loadMessages(){
if(!currentPeer)return;
const res=await fetch('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,peer_id:currentPeer})});
const data=await res.json();
const container=document.getElementById('messages');container.innerHTML='';
if(data.messages)data.messages.reverse().forEach(m=>addMessage(m));
container.scrollTop=container.scrollHeight;
}

function addMessage(msg){
const container=document.getElementById('messages');
const div=document.createElement('div');
const isEncrypted=msg.text&&msg.text.startsWith('ENC:');
div.className='msg '+(msg.out?'msg-out':'msg-in')+(isEncrypted?' msg-encrypted':'');
let html='';
if(!msg.out&&msg.name)html+=`<div class="msg-author">${msg.name}</div>`;

let displayText=msg.text||'';
if(isEncrypted){
displayText='🔒 Зашифровано';
}

html+=`<div class="msg-text">${escapeHtml(displayText)}</div>`;

if(msg.attachments)msg.attachments.forEach(a=>{
if(a.type==='photo'){const p=a.photo?.sizes?.find(s=>s.type==='x')||a.photo?.sizes?.[a.photo?.sizes?.length-1];if(p)html+=`<img class="msg-photo" src="${p.url}" alt="">`}
if(a.type==='doc'){
const ext=a.doc?.ext||'';
if(ext==='meow')html+=`<div class="msg-file"><span class="msg-file-icon">🔒</span><div class="msg-file-info"><div class="msg-file-name">Зашифрованное фото</div><div class="msg-file-size">.meow</div></div></div>`;
else if(ext==='mur')html+=`<div class="msg-file"><span class="msg-file-icon">🔒</span><div class="msg-file-info"><div class="msg-file-name">Зашифрованное видео</div><div class="msg-file-size">.mur</div></div></div>`;
else html+=`<div class="msg-file"><span class="msg-file-icon">📎</span><div class="msg-file-info"><div class="msg-file-name">${a.doc?.title||'Файл'}</div><div class="msg-file-size">${(a.doc?.size/1024).toFixed(1)} KB</div></div></div>`;
}
});

html+=`<div class="msg-time">${msg.date?new Date(msg.date*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'}):''}</div>`;
div.innerHTML=html;container.appendChild(div);
}

function escapeHtml(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}

async function sendMessage(){
const input=document.getElementById('msgInput');
const text=input.value.trim();
if(!text||!currentPeer)return;

const btn=document.getElementById('sendBtn');btn.disabled=true;

let sendText=text;
if(encryptionEnabled&&peerKeys[currentPeer]){
// Encrypt message
const encRes=await fetch('/api/encrypt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token,peer_id:currentPeer,text:text})});
const encData=await encRes.json();
if(encData.encrypted)sendText='ENC:'+encData.encrypted;
}

await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,peer_id:currentPeer,text:sendText})});
input.value='';btn.disabled=false;
addMessage({text:sendText,out:1,date:Math.floor(Date.now()/1000)});
document.getElementById('messages').scrollTop=999999;
}

async function handleFile(e){
const file=e.target.files[0];
if(!file||!currentPeer)return;
const btn=document.getElementById('sendBtn');btn.disabled=true;

const formData=new FormData();
formData.append('token',token);
formData.append('peer_id',currentPeer);
formData.append('file',file);
formData.append('encrypt',encryptionEnabled&&peerKeys[currentPeer]?'1':'0');

await fetch('/api/upload',{method:'POST',body:formData});
btn.disabled=false;
loadMessages();
}

function toggleEncrypt(){
encryptionEnabled=!encryptionEnabled;
updateEncryptUI();
}

function updateEncryptUI(){
const btn=document.getElementById('encryptBtn');
if(encryptionEnabled){
btn.classList.add('active');
btn.style.color='#4caf50';
} else {
btn.classList.remove('active');
btn.style.color='#fff';
}
}

function startPolling(){
if(pollInterval)clearInterval(pollInterval);
pollInterval=setInterval(()=>{if(currentPeer)loadMessages()},3000);
}

function logout(){
localStorage.clear();
location.reload();
}

function showDialogs(){
document.getElementById('chatScreen').classList.remove('active');
loadDialogs();
}

document.getElementById('msgInput').addEventListener('keypress',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});

// Auto login
if(token&&password){
currentUser=JSON.parse(localStorage.getItem('vk_user')||'{}');
myVkId=currentUser.id;
showDialogsScreen();
loadDialogs();
startPolling();
encryptionEnabled=true;
updateEncryptUI();
}
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


@app.route('/api/setup_keys', methods=['POST'])
def setup_keys():
    data = request.json
    token = data.get('token')
    vk_id = data.get('vk_id')
    password = data.get('password')

    if not all([token, vk_id, password]):
        return jsonify({'error': 'Missing params'}), 400

    keys = get_or_create_keys(vk_id, token, password)
    return jsonify({'ok': True, 'public_key': keys['public_key'][:50] + '...'})


@app.route('/api/check_peer_key', methods=['POST'])
def check_peer_key():
    peer_id = request.json.get('peer_id')
    key = get_peer_public_key(peer_id)
    return jsonify({'has_key': key is not None})


@app.route('/api/encrypt', methods=['POST'])
def encrypt_message():
    data = request.json
    token = data.get('token')
    peer_id = data.get('peer_id')
    text = data.get('text')

    pub_key = get_peer_public_key(peer_id)
    if not pub_key:
        return jsonify({'error': 'Peer has no encryption key'}), 400

    encrypted = encrypt_for_peer(pub_key, text)
    return jsonify({'encrypted': encrypted})


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


@app.route('/api/upload', methods=['POST'])
def upload_file():
    token = request.form.get('token')
    peer_id = request.form.get('peer_id')
    encrypt = request.form.get('encrypt') == '1'
    file = request.files.get('file')

    if not file:
        return jsonify({'error': 'No file'}), 400

    filename = file.filename.lower()
    file_bytes = file.read()

    # Encrypt if enabled
    if encrypt:
        # Derive key from token (simplified — in production use proper key exchange)
        key = hashlib.sha256(token.encode()).digest()
        key_b64 = base64.urlsafe_b64encode(key)
        encrypted = encrypt_file(key_b64, file_bytes)
        file_bytes = encrypted

        # Determine extension
        if filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            ext = 'meow'
            mime = 'application/octet-stream'
        elif filename.endswith(('.mp4', '.avi', '.mov', '.mkv')):
            ext = 'mur'
            mime = 'application/octet-stream'
        else:
            ext = 'enc'
            mime = 'application/octet-stream'

        # Upload as document with custom extension
        upload_server = vk_request('docs.getMessagesUploadServer', token, type='doc', peer_id=peer_id)
        if isinstance(upload_server, dict) and 'error' in upload_server:
            return jsonify(upload_server), 400

        upload_url = upload_server.get('upload_url')
        files = {'file': (f'encrypted.{ext}', BytesIO(file_bytes), mime)}
        upload_resp = requests.post(upload_url, files=files, timeout=30).json()

        save_result = vk_request('docs.save', token, file=upload_resp.get('file'), title=f'encrypted.{ext}')
        if isinstance(save_result, dict) and 'doc' in save_result:
            doc = save_result['doc']
            attachment = f"doc{doc['owner_id']}_{doc['id']}"
            vk_request('messages.send', token, peer_id=peer_id, attachment=attachment, random_id=0)
            return jsonify({'ok': True})

    else:
        # Normal upload
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

        elif filename.endswith(('.mp4', '.avi', '.mov', '.mkv')):
            upload_server = vk_request('video.save', token, name=filename, peer_id=peer_id)
            if isinstance(upload_server, dict) and 'error' in upload_server:
                return jsonify(upload_server), 400

            upload_url = upload_server.get('upload_url')
            files = {'video_file': (filename, BytesIO(file_bytes), file.content_type or 'video/mp4')}
            requests.post(upload_url, files=files, timeout=60)

            video = upload_server
            attachment = f"video{video['owner_id']}_{video['video_id']}"
            vk_request('messages.send', token, peer_id=peer_id, attachment=attachment, random_id=0)
            return jsonify({'ok': True})

        else:
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
