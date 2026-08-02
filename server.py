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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VK Client</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0e1621;color:#fff;height:100vh;overflow:hidden}
.app{display:flex;height:100vh}
.login-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;width:100%;height:100%;background:#17212b}
.login-screen h1{font-size:32px;margin-bottom:10px}
.login-screen p{color:#7f91a4;margin-bottom:30px}
.token-input{width:90%;max-width:400px;padding:15px;border:none;border-radius:10px;background:#242f3d;color:#fff;font-size:14px;margin-bottom:15px}
.btn{padding:15px 40px;border:none;border-radius:10px;background:#2b5278;color:#fff;font-size:16px;cursor:pointer}
.btn:hover{background:#3665a3}
.get-token-btn{background:#e94560;margin-bottom:15px}
.sidebar{width:350px;background:#17212b;border-right:1px solid #242f3d;display:flex;flex-direction:column}
.sidebar-header{padding:15px;background:#17212b;border-bottom:1px solid #242f3d;display:flex;align-items:center;gap:10px}
.user-avatar{width:40px;height:40px;border-radius:50%;object-fit:cover}
.user-name{font-weight:600;font-size:15px}
.user-status{font-size:12px;color:#7f91a4}
.dialogs-list{flex:1;overflow-y:auto}
.dialog{display:flex;align-items:center;padding:12px 15px;cursor:pointer;border-bottom:1px solid #242f3d}
.dialog:hover{background:#242f3d}
.dialog.active{background:#2b5278}
.dialog-avatar{width:50px;height:50px;border-radius:50%;object-fit:cover;margin-right:12px;background:#242f3d}
.dialog-info{flex:1;min-width:0}
.dialog-name{font-weight:600;font-size:14px;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dialog-preview{font-size:13px;color:#7f91a4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.unread-badge{background:#e94560;color:#fff;font-size:11px;padding:2px 7px;border-radius:10px;min-width:18px;text-align:center}
.chat{flex:1;display:flex;flex-direction:column;background:#0e1621}
.chat-header{padding:15px;background:#17212b;border-bottom:1px solid #242f3d;display:flex;align-items:center;gap:12px}
.chat-avatar{width:42px;height:42px;border-radius:50%;object-fit:cover}
.chat-title{font-weight:600;font-size:16px}
.messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:8px}
.message{max-width:70%;padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.4;word-wrap:break-word}
.message.in{align-self:flex-start;background:#182533;border-bottom-left-radius:4px}
.message.out{align-self:flex-end;background:#2b5278;border-bottom-right-radius:4px}
.message-author{font-size:12px;color:#e94560;margin-bottom:4px;font-weight:600}
.message-photo{max-width:100%;border-radius:8px;margin-top:5px}
.input-area{padding:15px;background:#17212b;border-top:1px solid #242f3d;display:flex;gap:10px;align-items:flex-end}
.message-input{flex:1;padding:12px 16px;border:none;border-radius:20px;background:#242f3d;color:#fff;font-size:14px;resize:none;max-height:100px}
.send-btn{padding:12px 20px;border:none;border-radius:20px;background:#2b5278;color:#fff;cursor:pointer;font-size:14px}
.hidden{display:none!important}
</style>
</head>
<body>
<div class="app">
<div class="login-screen" id="loginScreen">
<h1>VK Client</h1>
<p>Войдите через access token</p>
<button class="btn get-token-btn" onclick="getToken()">Получить токен</button>
<input type="text" class="token-input" id="tokenUrl" placeholder="Вставь ссылку с токеном сюда...">
<button class="btn" onclick="login()">Войти</button>
</div>
<div class="sidebar hidden" id="sidebar">
<div class="sidebar-header">
<img class="user-avatar" id="userAvatar" src="" alt="">
<div><div class="user-name" id="userName"></div><div class="user-status" id="userStatus">онлайн</div></div>
</div>
<div class="dialogs-list" id="dialogsList"></div>
</div>
<div class="chat hidden" id="chat">
<div class="chat-header">
<img class="chat-avatar" id="chatAvatar" src="" alt="">
<div class="chat-title" id="chatTitle">Выберите диалог</div>
</div>
<div class="messages" id="messages"></div>
<div class="input-area">
<textarea class="message-input" id="msgInput" placeholder="Сообщение..." rows="1"></textarea>
<button class="send-btn" onclick="sendMessage()">Отправить</button>
</div>
</div>
</div>
<script>
let token=localStorage.getItem('vk_token');
let currentPeer=null;
let currentUser=null;
const AUTH_URL='https://oauth.vk.com/authorize?client_id=2685278&scope=messages,audio,photos,video,docs,notes,pages,status,wall,groups,email,stats,notifications,offline&redirect_uri=https://oauth.vk.com/blank.html&display=page&response_type=token';
function getToken(){window.open(AUTH_URL,'_blank')}
async function login(){
const url=document.getElementById('tokenUrl').value.trim();
if(!url)return;
const res=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})});
const data=await res.json();
if(data.error){alert(data.error);return}
token=data.token;currentUser=data.user;localStorage.setItem('vk_token',token);
showApp();loadDialogs()
}
function showApp(){
document.getElementById('loginScreen').classList.add('hidden');
document.getElementById('sidebar').classList.remove('hidden');
document.getElementById('chat').classList.remove('hidden');
document.getElementById('userAvatar').src=currentUser.photo;
document.getElementById('userName').textContent=currentUser.name;
document.getElementById('userStatus').textContent=currentUser.online?'онлайн':'офлайн';
}
async function loadDialogs(){
const res=await fetch('/api/dialogs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token})});
const data=await res.json();
const list=document.getElementById('dialogsList');list.innerHTML='';
data.dialogs.forEach(d=>{
const div=document.createElement('div');div.className='dialog';div.onclick=()=>openDialog(d);
div.innerHTML=`<img class="dialog-avatar" src="${d.photo||'https://vk.com/images/camera_100.png'}" alt=""><div class="dialog-info"><div class="dialog-name">${d.name}</div><div class="dialog-preview">${d.last_message}</div></div>${d.unread>0?`<span class="unread-badge">${d.unread}</span>`:''}`;
list.appendChild(div)
})
}
async function openDialog(dialog){
currentPeer=dialog.id;
document.getElementById('chatTitle').textContent=dialog.name;
document.getElementById('chatAvatar').src=dialog.photo||'https://vk.com/images/camera_100.png';
const res=await fetch('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token,peer_id:currentPeer})});
const data=await res.json();
const container=document.getElementById('messages');container.innerHTML='';
data.messages.reverse().forEach(m=>addMessage(m));
container.scrollTop=container.scrollHeight
}
function addMessage(msg){
const container=document.getElementById('messages');
const div=document.createElement('div');div.className='message '+(msg.out?'out':'in');
let html='';
if(!msg.out&&msg.name)html+=`<div class="message-author">${msg.name}</div>`;
html+=`<div>${msg.text||''}</div>`;
msg.attachments.forEach(a=>{if(a.type==='photo'){const p=a.photo.sizes.find(s=>s.type==='x')||a.photo.sizes[a.photo.sizes.length-1];html+=`<img class="message-photo" src="${p.url}" alt="">`}});
div.innerHTML=html;container.appendChild(div)
}
async function sendMessage(){
const input=document.getElementById('msgInput');
const text=input.value.trim();
if(!text||!currentPeer)return;
await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token,peer_id:currentPeer,text:text})});
input.value='';
openDialog({id:currentPeer,name:document.getElementById('chatTitle').textContent,photo:document.getElementById('chatAvatar').src})
}
document.getElementById('msgInput').addEventListener('keypress',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});
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
            'last_message': msg.get('text', '')
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
