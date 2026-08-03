from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit, join_room
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

users_online = {}

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>Meow Audio Call</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-database-compat.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',sans-serif}
body{background:#0d1117;color:#c9d1d9;height:100vh;overflow:hidden}
#app{display:flex;height:100vh}
#sidebar{width:280px;background:#161b22;border-right:1px solid #30363d;display:flex;flex-direction:column}
#sidebar h2{padding:16px 20px;font-size:16px;color:#58a6ff;border-bottom:1px solid #30363d}
#userList{flex:1;overflow-y:auto;padding:8px}
.userItem{display:flex;align-items:center;padding:10px 12px;border-radius:8px;cursor:pointer;transition:.2s;margin-bottom:4px}
.userItem:hover{background:#21262d}
.userItem .avatar{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;margin-right:12px}
.userItem .info{flex:1}
.userItem .name{font-size:14px;font-weight:500}
.userItem .status{font-size:11px;color:#8b949e}
.userItem .callBtn{width:32px;height:32px;border-radius:50%;background:#238636;border:none;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:.2s}
.userItem .callBtn:hover{background:#2ea043;transform:scale(1.1)}
.userItem .callBtn:active{transform:scale(0.95)}
#authScreen{position:fixed;top:0;left:0;width:100%;height:100%;background:#0d1117;z-index:1000;display:flex;align-items:center;justify-content:center}
.authBox{background:#161b22;border:1px solid #30363d;border-radius:16px;padding:40px;width:360px;max-width:90%}
.authBox h1{text-align:center;margin-bottom:24px;color:#58a6ff;font-size:24px}
.authBox input{width:100%;padding:12px 16px;margin-bottom:12px;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;font-size:14px;outline:none;transition:.2s}
.authBox input:focus{border-color:#58a6ff}
.authBox button{width:100%;padding:12px;background:#238636;border:none;border-radius:8px;color:#fff;font-size:15px;font-weight:600;cursor:pointer;transition:.2s}
.authBox button:hover{background:#2ea043}
.authBox .switch{text-align:center;margin-top:16px;font-size:13px;color:#8b949e;cursor:pointer}
.authBox .switch span{color:#58a6ff}
.authBox .error{color:#f85149;font-size:13px;margin-top:8px;text-align:center;min-height:18px}
#mainArea{flex:1;display:flex;flex-direction:column}
#topBar{height:56px;background:#161b22;border-bottom:1px solid #30363d;display:flex;align-items:center;padding:0 20px;justify-content:space-between}
#topBar .title{font-size:16px;font-weight:600}
#topBar .userInfo{display:flex;align-items:center;gap:12px}
#topBar .logoutBtn{padding:6px 14px;background:#da3633;border:none;border-radius:6px;color:#fff;font-size:12px;cursor:pointer}
#chatArea{flex:1;display:flex;flex-direction:column;position:relative}
#callOverlay{position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(13,17,23,0.95);z-index:50;display:none;flex-direction:column;align-items:center;justify-content:center}
#callOverlay.active{display:flex}
.callAvatar{width:120px;height:120px;border-radius:50%;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:48px;font-weight:bold;margin-bottom:24px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}
.callStatus{font-size:20px;margin-bottom:32px;color:#8b949e}
.callControls{display:flex;gap:16px}
.callControls button{width:60px;height:60px;border-radius:50%;border:none;cursor:pointer;font-size:24px;transition:.2s;display:flex;align-items:center;justify-content:center}
.callControls .accept{background:#238636;color:#fff}
.callControls .accept:hover{background:#2ea043}
.callControls .decline{background:#da3633;color:#fff}
.callControls .decline:hover{background:#f85149}
.callControls .end{background:#da3633;color:#fff}
.callControls .end:hover{background:#f85149}
.callControls .mute{background:#30363d;color:#fff}
.callControls .mute:hover{background:#484f58}
#audioContainer{display:none}
#incomingCall{position:fixed;top:20px;right:20px;background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px 20px;z-index:200;display:none;align-items:center;gap:16px;box-shadow:0 8px 32px rgba(0,0,0,0.5);animation:slideIn 0.3s ease}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
#incomingCall .caller{font-weight:600}
#incomingCall .callerBtns{display:flex;gap:8px}
#incomingCall .callerBtns button{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}
#incomingCall .callerBtns .acceptCall{background:#238636;color:#fff}
#incomingCall .callerBtns .declineCall{background:#da3633;color:#fff}
#searchBox{padding:12px 16px;border-bottom:1px solid #30363d}
#searchBox input{width:100%;padding:10px 14px;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;font-size:13px;outline:none}
#searchBox input:focus{border-color:#58a6ff}
#currentCallInfo{position:absolute;bottom:20px;left:50%;transform:translateX(-50%);background:#161b22;border:1px solid #30363d;border-radius:12px;padding:12px 24px;display:none;align-items:center;gap:16px;z-index:40}
#currentCallInfo.active{display:flex}
#currentCallInfo .callTimer{font-family:monospace;font-size:18px;color:#58a6ff}
#currentCallInfo .callName{font-weight:600}
.callBarBtns{display:flex;gap:8px}
.callBarBtns button{width:36px;height:36px;border-radius:50%;border:none;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center}
.callBarBtns .muteBtn{background:#30363d;color:#fff}
.callBarBtns .endBtn{background:#da3633;color:#fff}
#noAuthMsg{flex:1;display:flex;align-items:center;justify-content:center;color:#8b949e;font-size:16px}
#messagesArea{flex:1;padding:20px;overflow-y:auto}
.msg{margin-bottom:12px;padding:12px 16px;border-radius:12px;max-width:70%;word-break:break-word}
.msg.sent{margin-left:auto;background:#238636}
.msg.received{background:#21262d}
#msgInputArea{padding:16px 20px;border-top:1px solid #30363d;display:flex;gap:12px}
#msgInputArea input{flex:1;padding:12px 16px;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;font-size:14px;outline:none}
#msgInputArea button{padding:12px 20px;background:#58a6ff;border:none;border-radius:8px;color:#fff;font-weight:600;cursor:pointer}
#msgInputArea button:hover{background:#79c0ff}
</style>
</head>
<body>
<div id="authScreen">
  <div class="authBox">
    <h1>Meow Audio</h1>
    <div id="authForm">
      <input type="text" id="authUsername" placeholder="Имя пользователя" autocomplete="off">
      <input type="password" id="authPassword" placeholder="Пароль">
      <button id="authBtn">Войти</button>
      <div class="error" id="authError"></div>
      <div class="switch" id="authSwitch">Нет аккаунта? <span>Зарегистрироваться</span></div>
    </div>
  </div>
</div>

<div id="app" style="display:none">
  <div id="sidebar">
    <h2>Пользователи</h2>
    <div id="searchBox"><input type="text" id="searchInput" placeholder="Поиск пользователя..."></div>
    <div id="userList"></div>
  </div>
  <div id="mainArea">
    <div id="topBar">
      <div class="title" id="chatTitle">Выберите пользователя</div>
      <div class="userInfo">
        <span id="myName"></span>
        <button class="logoutBtn" id="logoutBtn">Выйти</button>
      </div>
    </div>
    <div id="chatArea">
      <div id="noAuthMsg">Выберите пользователя из списка слева</div>
      <div id="messagesArea" style="display:none"></div>
      <div id="msgInputArea" style="display:none">
        <input type="text" id="msgInput" placeholder="Написать сообщение...">
        <button id="sendMsg">➤</button>
      </div>
      <div id="callOverlay">
        <div class="callAvatar" id="callAvatar">?</div>
        <div class="callStatus" id="callStatus">Вызов...</div>
        <div class="callControls" id="callControls"></div>
      </div>
      <div id="currentCallInfo">
        <span class="callName" id="callName">User</span>
        <span class="callTimer" id="callTimer">00:00</span>
        <div class="callBarBtns">
          <button class="muteBtn" id="muteBtn">🎤</button>
          <button class="endBtn" id="endBtn">📞</button>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="incomingCall">
  <div>
    <div class="caller" id="callerName">User</div>
    <div style="font-size:12px;color:#8b949e">Входящий звонок</div>
  </div>
  <div class="callerBtns">
    <button class="acceptCall" id="acceptCall">✓</button>
    <button class="declineCall" id="declineCall">✕</button>
  </div>
</div>

<div id="audioContainer"></div>

<script>
const firebaseConfig = {
  apiKey: "AIzaSyBm0mIvHVznIeF2PoFk6dtdaiT5r877wyA",
  authDomain: "meow-874ce.firebaseapp.com",
  databaseURL: "https://meow-874ce-default-rtdb.europe-west1.firebasedatabase.app",
  projectId: "meow-874ce",
  storageBucket: "meow-874ce.firebasestorage.app",
  messagingSenderId: "471541334599",
  appId: "1:471541334599:web:567af3e7dbe70a37572762"
};

firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();
const db = firebase.database();

const socket = io();

let currentUser = null;
let currentChat = null;
let localStream = null;
let peerConnection = null;
let callTimer = null;
let callSeconds = 0;
let isMuted = false;
let isRegister = false;
let incomingCallData = null;
let iceCandidatesQueue = [];

const servers = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
    { urls: "stun:stun2.l.google.com:19302" }
  ]
};

document.getElementById('authBtn').onclick = async () => {
  const username = document.getElementById('authUsername').value.trim().toLowerCase();
  const password = document.getElementById('authPassword').value;
  const err = document.getElementById('authError');
  if(!username || !password){err.textContent='Заполните все поля';return;}
  const email = username + "@meow.app";
  try{
    if(isRegister){
      const snap = await db.ref('users/' + username).once('value');
      if(snap.exists()){err.textContent='Имя занято';return;}
      const cred = await auth.createUserWithEmailAndPassword(email, password);
      await db.ref('users/' + username).set({uid: cred.user.uid, online: true, lastSeen: Date.now()});
      currentUser = username;
    } else {
      await auth.signInWithEmailAndPassword(email, password);
      currentUser = username;
      await db.ref('users/' + username).update({online: true, lastSeen: Date.now()});
    }
    startApp();
  } catch(e){err.textContent = e.message;}
};

document.getElementById('authSwitch').onclick = () => {
  isRegister = !isRegister;
  document.getElementById('authBtn').textContent = isRegister ? 'Зарегистрироваться' : 'Войти';
  document.getElementById('authSwitch').innerHTML = isRegister ? 'Уже есть аккаунт? <span>Войти</span>' : 'Нет аккаунта? <span>Зарегистрироваться</span>';
};

async function startApp(){
  document.getElementById('authScreen').style.display='none';
  document.getElementById('app').style.display='flex';
  document.getElementById('myName').textContent = currentUser;
  socket.emit('join', {username: currentUser});
  const userRef = db.ref('users/' + currentUser);
  userRef.onDisconnect().update({online: false, lastSeen: Date.now()});
  await userRef.update({online: true});
  loadUsers();
}

function loadUsers(){
  db.ref('users').on('value', snap => {
    renderUsers(snap.val() || {});
  });
}

function renderUsers(users){
  const list = document.getElementById('userList');
  const search = document.getElementById('searchInput').value.toLowerCase();
  list.innerHTML = '';
  Object.entries(users).forEach(([name, data]) => {
    if(name === currentUser) return;
    if(search && !name.includes(search)) return;
    const div = document.createElement('div');
    div.className = 'userItem';
    div.innerHTML = `
      <div class="avatar">${name[0].toUpperCase()}</div>
      <div class="info">
        <div class="name">${name}</div>
        <div class="status">${data.online ? 'онлайн' : timeAgo(data.lastSeen)}</div>
      </div>
      <button class="callBtn" data-user="${name}">📞</button>
    `;
    div.querySelector('.callBtn').onclick = (e) => {e.stopPropagation(); startCall(name);};
    div.onclick = () => openChat(name);
    list.appendChild(div);
  });
}

document.getElementById('searchInput').oninput = () => {
  db.ref('users').once('value', snap => renderUsers(snap.val() || {}));
};

function timeAgo(ts){
  if(!ts) return 'давно';
  const s = Math.floor((Date.now()-ts)/1000);
  if(s<60) return 'только что';
  if(s<3600) return Math.floor(s/60)+' мин назад';
  if(s<86400) return Math.floor(s/3600)+' ч назад';
  return Math.floor(s/86400)+' дн назад';
}

function openChat(name){
  currentChat = name;
  document.getElementById('chatTitle').textContent = name;
  document.getElementById('noAuthMsg').style.display='none';
  document.getElementById('messagesArea').style.display='block';
  document.getElementById('msgInputArea').style.display='flex';
  document.getElementById('messagesArea').innerHTML='';
  const chatId = [currentUser, name].sort().join('_');
  db.ref('chats/' + chatId).on('child_added', snap => {
    const msg = snap.val();
    appendMsg(msg.from, msg.text);
  });
}

function appendMsg(from, text){
  const area = document.getElementById('messagesArea');
  const div = document.createElement('div');
  div.className = 'msg ' + (from===currentUser?'sent':'received');
  div.textContent = text;
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

document.getElementById('sendMsg').onclick = sendMsg;
document.getElementById('msgInput').onkeypress = e => {if(e.key==='Enter') sendMsg();};

function sendMsg(){
  const input = document.getElementById('msgInput');
  const text = input.value.trim();
  if(!text || !currentChat) return;
  const chatId = [currentUser, currentChat].sort().join('_');
  db.ref('chats/' + chatId).push({from: currentUser, text, ts: Date.now()});
  input.value='';
}

async function startCall(target){
  currentChat = target;
  try{
    localStream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
  } catch(e){alert('Нет доступа к микрофону'); return;}
  peerConnection = new RTCPeerConnection(servers);
  localStream.getTracks().forEach(t => peerConnection.addTrack(t, localStream));
  peerConnection.ontrack = e => {
    const audio = document.createElement('audio');
    audio.srcObject = e.streams[0];
    audio.autoplay = true;
    document.getElementById('audioContainer').appendChild(audio);
  };
  peerConnection.onicecandidate = e => {
    if(e.candidate) socket.emit('ice-candidate', {to: target, candidate: e.candidate});
  };
  const offer = await peerConnection.createOffer();
  await peerConnection.setLocalDescription(offer);
  socket.emit('call-offer', {to: target, from: currentUser, offer});
  showCallOverlay(target, 'outgoing');
}

function showCallOverlay(name, type){
  const overlay = document.getElementById('callOverlay');
  document.getElementById('callAvatar').textContent = name[0].toUpperCase();
  document.getElementById('callStatus').textContent = type==='outgoing' ? 'Звоним ' + name + '...' : 'Входящий звонок от ' + name;
  const controls = document.getElementById('callControls');
  controls.innerHTML = '';
  if(type==='outgoing'){
    const end = document.createElement('button');
    end.className='end'; end.textContent='📞';
    end.onclick = endCall;
    controls.appendChild(end);
  } else {
    const accept = document.createElement('button');
    accept.className='accept'; accept.textContent='✓';
    accept.onclick = () => acceptIncoming(name);
    const decline = document.createElement('button');
    decline.className='decline'; decline.textContent='✕';
    decline.onclick = () => {socket.emit('call-reject', {to: name}); endCall();};
    controls.appendChild(accept);
    controls.appendChild(decline);
  }
  overlay.classList.add('active');
}

socket.on('call-offer', async data => {
  incomingCallData = data;
  document.getElementById('callerName').textContent = data.from;
  document.getElementById('incomingCall').style.display = 'flex';
});

document.getElementById('acceptCall').onclick = () => {
  if(incomingCallData) acceptIncoming(incomingCallData.from);
  document.getElementById('incomingCall').style.display = 'none';
};

document.getElementById('declineCall').onclick = () => {
  if(incomingCallData) socket.emit('call-reject', {to: incomingCallData.from});
  document.getElementById('incomingCall').style.display = 'none';
  incomingCallData = null;
};

async function acceptIncoming(from){
  document.getElementById('callOverlay').classList.remove('active');
  try{
    localStream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
  } catch(e){alert('Нет доступа к микрофону'); return;}
  peerConnection = new RTCPeerConnection(servers);
  localStream.getTracks().forEach(t => peerConnection.addTrack(t, localStream));
  peerConnection.ontrack = e => {
    const audio = document.createElement('audio');
    audio.srcObject = e.streams[0];
    audio.autoplay = true;
    document.getElementById('audioContainer').appendChild(audio);
  };
  peerConnection.onicecandidate = e => {
    if(e.candidate) socket.emit('ice-candidate', {to: from, candidate: e.candidate});
  };
  await peerConnection.setRemoteDescription(new RTCSessionDescription(incomingCallData.offer));
  iceCandidatesQueue.forEach(c => peerConnection.addIceCandidate(new RTCIceCandidate(c)));
  iceCandidatesQueue = [];
  const answer = await peerConnection.createAnswer();
  await peerConnection.setLocalDescription(answer);
  socket.emit('call-answer', {to: from, answer});
  startCallTimer(from);
  incomingCallData = null;
}

socket.on('call-answer', async data => {
  await peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
  document.getElementById('callOverlay').classList.remove('active');
  startCallTimer(currentChat);
});

socket.on('call-reject', () => { endCall(); alert('Звонок отклонен'); });

socket.on('ice-candidate', async data => {
  if(peerConnection && peerConnection.remoteDescription){
    await peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
  } else {
    iceCandidatesQueue.push(data.candidate);
  }
});

socket.on('call-end', () => { endCall(); });

function startCallTimer(name){
  callSeconds = 0;
  document.getElementById('currentCallInfo').classList.add('active');
  document.getElementById('callName').textContent = name;
  callTimer = setInterval(() => {
    callSeconds++;
    const m = String(Math.floor(callSeconds/60)).padStart(2,'0');
    const s = String(callSeconds%60).padStart(2,'0');
    document.getElementById('callTimer').textContent = m+':'+s;
  }, 1000);
}

function endCall(){
  if(peerConnection){ peerConnection.close(); peerConnection = null; }
  if(localStream){ localStream.getTracks().forEach(t => t.stop()); localStream = null; }
  if(callTimer){clearInterval(callTimer); callTimer=null;}
  document.getElementById('callOverlay').classList.remove('active');
  document.getElementById('currentCallInfo').classList.remove('active');
  document.getElementById('audioContainer').innerHTML = '';
  iceCandidatesQueue = [];
  if(currentChat) socket.emit('call-end', {to: currentChat});
}

document.getElementById('endBtn').onclick = endCall;

document.getElementById('muteBtn').onclick = () => {
  isMuted = !isMuted;
  if(localStream){ localStream.getAudioTracks().forEach(t => t.enabled = !isMuted); }
  document.getElementById('muteBtn').textContent = isMuted ? '🚫' : '🎤';
};

document.getElementById('logoutBtn').onclick = async () => {
  await db.ref('users/' + currentUser).update({online: false, lastSeen: Date.now()});
  await auth.signOut();
  location.reload();
};
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@socketio.on('join')
def handle_join(data):
    users_online[data['username']] = request.sid
    join_room(data['username'])

@socketio.on('call-offer')
def handle_offer(data):
    emit('call-offer', data, room=data['to'])

@socketio.on('call-answer')
def handle_answer(data):
    emit('call-answer', data, room=data['to'])

@socketio.on('call-reject')
def handle_reject(data):
    emit('call-reject', {}, room=data['to'])

@socketio.on('ice-candidate')
def handle_ice(data):
    emit('ice-candidate', data, room=data['to'])

@socketio.on('call-end')
def handle_end(data):
    emit('call-end', {}, room=data['to'])

@socketio.on('disconnect')
def handle_disconnect():
    for u, sid in list(users_online.items()):
        if sid == request.sid:
            del users_online[u]
            break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
