import os
import re
import requests
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

VK_API = "https://api.vk.com/method"
API_VERSION = "5.199"

HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>VK Client</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#0e1621;color:#fff;height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased}
.app{height:100vh;display:flex;flex-direction:column}

/* Login */
.login-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#17212b;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;z-index:100}
.login-screen h1{font-size:28px;margin-bottom:8px;font-weight:600}
.login-screen p{color:#7f91a4;margin-bottom:40px;font-size:15px}
.token-input{width:100%;max-width:380px;padding:14px 16px;border:none;border-radius:12px;background:#242f3d;color:#fff;font-size:15px;margin-bottom:12px;outline:none}
.token-input::placeholder{color:#5e6b7a}
.btn{width:100%;max-width:380px;padding:14px;border:none;border-radius:12px;background:#2b5278;color:#fff;font-size:16px;font-weight:500;cursor:pointer;transition:all .2s;margin-bottom:10px}
.btn:active{transform:scale(.97)}
.btn-primary{background:#2b5278}
.btn-secondary{background:#e94560}

/* Header */
.header{height:56px;background:#17212b;display:flex;align-items:center;padding:0 16px;border-bottom:1px solid #242f3d;flex-shrink:0}
.header-back{width:40px;height:40px;display:flex;align-items:center;justify-content:center;cursor:pointer;margin-right:8px}
.header-avatar{width:36px;height:36px;border-radius:50%;object-fit:cover;margin-right:12px;background:#242f3d}
.header-info{flex:1;min-width:0}
.header-title{font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.header-subtitle{font-size:13px;color:#7f91a4}
.header-actions{display:flex;gap:8px}
.header-btn{width:40px;height:40px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer}
.header-btn:active{background:#242f3d}

/* Dialogs list */
.dialogs-screen{flex:1;display:flex;flex-direction:column;overflow:hidden}
.dialogs-list{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.dialog{display:flex;align-items:center;padding:12px 16px;cursor:pointer;transition:background .15s;border-bottom:1px solid #1a2330}
.dialog:active{background:#1a2330}
.dialog-avatar{width:52px;height:52px;border-radius:50%;object-fit:cover;margin-right:14px;flex-shrink:0;background:#242f3d}
.dialog-info{flex:1;min-width:0}
.dialog-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px}
.dialog-name{font-size:15px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;margin-right:8px}
.dialog-time{font-size:12px;color:#5e6b7a;flex-shrink:0}
.dialog-bottom{display:flex;align-items:center;gap:6px}
.dialog-preview{font-size:14px;color:#7f91a4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.dialog-unread{min-width:20px;height:20px;border-radius:10px;background:#e94560;color:#fff;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center;padding:0 6px;flex-shrink:0}
.dialog-check{color:#4fc3f7;font-size:12px}

/* Chat */
.chat-screen{position:fixed;top:0;left:0;width:100%;height:100%;background:#0e1621;display:flex;flex-direction:column;z-index:10;transform:translateX(100%);transition:transform .25s ease}
.chat-screen.active{transform:translateX(0)}
.messages{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:4px;-webkit-overflow-scrolling:touch}
.msg{max-width:85%;padding:8px 12px;border-radius:16px;font-size:15px;line-height:1.35;word-wrap:break-word;position:relative;animation:msgIn .2s ease}
@keyframes msgIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.msg-in{align-self:flex-start;background:#182533;border-bottom-left-radius:4px}
.msg-out{align-self:flex-end;background:#2b5278;border-bottom-right-radius:4px}
.msg-author{font-size:13px;color:#e94560;font-weight:600;margin-bottom:2px}
.msg-text{color:#fff}
.msg-time{font-size:11px;color:rgba(255,255,255,.5);margin-top:2px;text-align:right}
.msg-photo{max-width:100%;border-radius:12px;margin-top:4px;display:block}

/* Input */
.input-area{min-height:56px;background:#17212b;border-top:1px solid #242f3d;display:flex;align-items:flex-end;padding:8px 12px;gap:8px}
.input-attach{width:40px;height:40px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;flex-shrink:0;color:#7f91a4}
.input-attach:active{background:#242f3d}
.message-input{flex:1;padding:10px 16px;border:none;border-radius:20px;background:#242f3d;color:#fff;font-size:15px;outline:none;resize:none;max-height:120px;font-family:inherit;line-height:1.4}
.send-btn{width:40px;height:40px;border-radius:50%;background:#2b5278;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;border:none;color:#fff}
.send-btn:active{background:#3665a3;transform:scale(.95)}
.send-btn:disabled{background:#1a2330;color:#5e6b7a}

/* Bottom nav */
.bottom-nav{height:56px;background:#17212b;border-top:1px solid #242f3d;display:flex;justify-content:space-around;align-items:center;flex-shrink:0}
.nav-item{flex:1;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;cursor:pointer;color:#5e6b7a}
.nav-item.active{color:#4fc3f7}
.nav-item span{font-size:11px}

/* Hidden */
.hidden{display:none!important}
</style>
</head>
<body>
<div class="app">

<!-- Login -->
<div class="login-screen" id="loginScreen">
<h1>VK Client</h1>
<p>Вход через access token</p>
<button class="btn btn-secondary" onclick="getToken()">Получить токен</button>
<input type="text" class="token-input" id="tokenUrl" placeholder="Вставь ссылку с токеном...">
<button class="btn btn-primary" onclick="login()">Войти</button>
</div>

<!-- Dialogs -->
<div class="dialogs-screen hidden" id="dialogsScreen">
<div class="header">
<img class="header-avatar" id="headerAvatar" src="" alt="">
<div class="header-info">
<div class="header-title" id="headerTitle">VK Client</div>
<div class="header-subtitle" id="headerStatus">онлайн</div>
</div>
</div>
<div class="dialogs-list" id="dialogsList"></div>
<div class="bottom-nav">
<div class="nav-item active" onclick="showDialogs()">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
<span>Чаты</span>
</div>
<div class="nav-item">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
<span>Поиск</span>
</div>
<div class="nav-item">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
<span>Профиль</span>
</div>
</div>
</div>

<!-- Chat -->
<div class="chat-screen" id="chatScreen">
<div class="header">
<div class="header-back" onclick="backToDialogs()">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
</div>
<img class="header-avatar" id="chatAvatar" src="" alt="">
<div class="header-info">
<div class="header-title" id="chatTitle"></div>
<div class="header-subtitle">онлайн</div>
</div>
</div>
<div class="messages" id="messages"></div>
<div class="input-area">
<div class="input-attach">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
</div>
<textarea class="message-input" id="msgInput" placeholder="Сообщение" rows="1"></textarea>
<button class="send-btn" id="sendBtn" onclick="sendMessage()">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
</button>
</div>
</div>

</div>

<script>
let token=localStorage.getItem('vk_token');
let currentPeer=null;
let currentUser=null;
let dialogsData=[];

const AUTH_URL='https://oauth.vk.com/authorize?client_id=2685278&scope=messages,audio,photos,video,docs,notes,pages,status,wall,groups,email,stats,notifications,offline&redirect_uri=https://oauth.vk.com/blank.html&display=page&response_type=token';

function getToken(){window.open(AUTH_URL,'_blank')}

async function login(){
const url=document.getElementById('tokenUrl').value.trim();
if(!url){alert('Вставь ссылку с токеном');return}
const res=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
const data=await res.json();
if(data.error){alert(data.error);return}
token=data.token;currentUser=data.user;localStorage.setItem('vk_token',token);
showDialogsScreen();loadDialogs()
}

function showDialogsScreen(){
document.getElementById('loginScreen').classList.add('hidden');
document.getElementById('dialogsScreen').classList.remove('hidden');
document.getElementById('headerAvatar').src=currentUser.photo||'';
document.getElementById('headerTitle').textContent=currentUser.name||'VK';
document.getElementById('headerStatus').textContent=currentUser.online?'онлайн':'офлайн'
}

async function loadDialogs(){
const res=await fetch('/api/dialogs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
const data=await res.json();
if(data.error){alert('Ошибка загрузки диалогов');return}
dialogsData=data.dialogs;
const list=document.getElementById('dialogsList');list.innerHTML='';
data.dialogs.forEach((d,i)=>{
const div=document.createElement('div');div.className='dialog';div.onclick=()=>openChat(i);
const time=d.date?new Date(d.date*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'}):'';
div.innerHTML=`<img class="dialog-avatar" src="${d.photo||'https://vk.com/images/camera_100.png'}" onerror="this.src='https://vk.com/images/camera_100.png'" alt=""><div class="dialog-info"><div class="dialog-top"><div class="dialog-name">${d.name}</div><div class="dialog-time">${time}</div></div><div class="dialog-bottom"><div class="dialog-preview">${d.last_message||''}</div>${d.unread>0?`<div class="dialog-unread">${d.unread}</div>`:''}</div></div>`;
list.appendChild(div)
})
}

function openChat(index){
const d=dialogsData[index];currentPeer=d.id;
document.getElementById('chatTitle').textContent=d.name;
document.getElementById('chatAvatar').src=d.photo||'https://vk.com/images/camera_100.png';
document.getElementById('chatScreen').classList.add('active');
loadMessages()
}

function backToDialogs(){
document.getElementById('chatScreen').classList.remove('active');
currentPeer=null
}

async function loadMessages(){
if(!currentPeer)return;
const res=await fetch('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,peer_id:currentPeer})});
const data=await res.json();
const container=document.getElementById('messages');container.innerHTML='';
if(data.messages)data.messages.reverse().forEach(m=>addMessage(m));
container.scrollTop=container.scrollHeight
}

function addMessage(msg){
const container=document.getElementById('messages');
const div=document.createElement('div');
div.className='msg '+(msg.out?'msg-out':'msg-in');
let html='';
if(!msg.out&&msg.name)html+=`<div class="msg-author">${msg.name}</div>`;
html+=`<div class="msg-text">${escapeHtml(msg.text||'')}</div>`;
if(msg.attachments)msg.attachments.forEach(a=>{if(a.type==='photo'){const p=a.photo?.sizes?.find(s=>s.type==='x')||a.photo?.sizes?.[a.photo.sizes.length-1];if(p)html+=`<img class="msg-photo" src="${p.url}" alt="">`}});
html+=`<div class="msg-time">${msg.date?new Date(msg.date*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'}):''}</div>`;
div.innerHTML=html;container.appendChild(div)
}

function escapeHtml(text){
const div=document.createElement('div');div.textContent=text;return div.innerHTML
}

async function sendMessage(){
const input=document.getElementById('msgInput');
const text=input.value.trim();
if(!text||!currentPeer)return;
const btn=document.getElementById('sendBtn');btn.disabled=true;
await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,peer_id:currentPeer,text})});
input.value='';btn.disabled=false;
addMessage({text:text,out:1,date:Math.floor(Date.now()/1000)});
document.getElementById('messages').scrollTop=999999
}

document.getElementById('msgInput').addEventListener('keypress',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});

// Auto login
if(token)login()
</script>
</body>
</html>
"""

def vk_request(method, token, **params):
    params['access_token'] = token
    params['v'] = API_VERSION
    try:
        resp = requests.get(f"{VK_API}/{method}", params=params, timeout=30)
        data = resp.json()
        return data.get('response', data.get('error'))
    except Exception as e:
        return {'error': str(e)}

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
