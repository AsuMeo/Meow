import os
import json
import random
import string
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', ''.join(random.choices(string.ascii_letters + string.digits, k=32)))

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ===== БЕСПЛАТНЫЕ STUN/TURN СЕРВЕРА =====
ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
    {"urls": "stun:stun2.l.google.com:19302"},
    {"urls": "stun:stun3.l.google.com:19302"},
    {"urls": "stun:stun4.l.google.com:19302"},
    {"urls": "stun:stun.ekiga.net"},
    {"urls": "stun:stun.ideasip.com"},
    {"urls": "stun:stun.schlund.de"},
    {"urls": "stun:stun.voiparound.com"},
    {"urls": "stun:stun.voipbuster.com"},
    {"urls": "stun:stun.voipstunt.com"},
    {"urls": "stun:stun.voxgratia.org"},
    {"urls": "stun:stun.xten.com"},
    {"urls": "stun:openrelay.metered.ca:80"},
    {"urls": "turn:openrelay.metered.ca:80", "username": "openrelayproject", "credential": "openrelayproject"},
    {"urls": "turn:openrelay.metered.ca:443", "username": "openrelayproject", "credential": "openrelayproject"},
    {"urls": "turn:openrelay.metered.ca:443?transport=tcp", "username": "openrelayproject", "credential": "openrelayproject"},
    {"urls": "stun:stun.relay.metered.ca:80"},
    {"urls": "turn:global.relay.metered.ca:80", "username": "openrelayproject", "credential": "openrelayproject"},
    {"urls": "turn:global.relay.metered.ca:443", "username": "openrelayproject", "credential": "openrelayproject"},
    {"urls": "turn:global.relay.metered.ca:443?transport=tcp", "username": "openrelayproject", "credential": "openrelayproject"},
]

# Активные комнаты: {room_id: {peer1_id, peer2_id, status}}
active_rooms = {}

# Статусы пользователей: {vk_id: {status, last_seen, socket_id}}
user_statuses = {}

# История звонков: {vk_id: [call_records]}
call_history = {}

def generate_room_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

@app.route('/')
def index():
    return render_template_string(CALL_HTML)

@app.route('/api/ice_config')
def get_ice_config():
    return jsonify({"iceServers": ICE_SERVERS})

@app.route('/api/call_history/<vk_id>')
def get_call_history(vk_id):
    return jsonify({"history": call_history.get(vk_id, [])})

@socketio.on('connect')
def handle_connect():
    emit('connected', {'socket_id': request.sid})

@socketio.on('register')
def handle_register(data):
    vk_id = data.get('vk_id')
    name = data.get('name', 'Unknown')
    photo = data.get('photo', '')
    if vk_id:
        user_statuses[vk_id] = {
            'socket_id': request.sid,
            'name': name,
            'photo': photo,
            'status': 'online',
            'in_call': False,
            'room_id': None,
            'last_seen': datetime.now().isoformat()
        }
        emit('registered', {'vk_id': vk_id, 'status': 'online'})
        broadcast_user_status(vk_id)

@socketio.on('disconnect')
def handle_disconnect():
    for vk_id, info in list(user_statuses.items()):
        if info.get('socket_id') == request.sid:
            info['status'] = 'offline'
            info['last_seen'] = datetime.now().isoformat()
            if info.get('in_call') and info.get('room_id'):
                end_call(info['room_id'], vk_id)
            broadcast_user_status(vk_id)
            break

@socketio.on('call_request')
def handle_call_request(data):
    caller_id = data.get('caller_id')
    target_id = data.get('target_id')
    call_type = data.get('call_type', 'audio')

    target = user_statuses.get(target_id)
    caller = user_statuses.get(caller_id)

    if not target:
        emit('call_error', {'error': 'Пользователь не в сети', 'target_id': target_id})
        return

    if target.get('in_call'):
        emit('call_error', {'error': 'Пользователь уже в звонке', 'target_id': target_id})
        return

    room_id = generate_room_id()
    active_rooms[room_id] = {
        'caller_id': caller_id,
        'target_id': target_id,
        'status': 'ringing',
        'call_type': call_type,
        'start_time': None,
        'created_at': datetime.now().isoformat()
    }

    caller['room_id'] = room_id
    target['room_id'] = room_id

    emit('incoming_call', {
        'room_id': room_id,
        'caller_id': caller_id,
        'caller_name': caller.get('name', 'Unknown'),
        'caller_photo': caller.get('photo', ''),
        'call_type': call_type
    }, room=target['socket_id'])

    emit('call_ringing', {
        'room_id': room_id,
        'target_id': target_id,
        'target_name': target.get('name', 'Unknown')
    })

@socketio.on('call_accept')
def handle_call_accept(data):
    room_id = data.get('room_id')
    room = active_rooms.get(room_id)
    if not room:
        emit('call_error', {'error': 'Комната не найдена'})
        return

    room['status'] = 'connected'
    room['start_time'] = datetime.now().isoformat()

    caller = user_statuses.get(room['caller_id'])
    target = user_statuses.get(room['target_id'])

    if caller:
        caller['in_call'] = True
        emit('call_connected', {
            'room_id': room_id,
            'peer_id': room['target_id'],
            'peer_name': target.get('name', '') if target else '',
            'call_type': room['call_type']
        }, room=caller['socket_id'])

    if target:
        target['in_call'] = True
        emit('call_connected', {
            'room_id': room_id,
            'peer_id': room['caller_id'],
            'peer_name': caller.get('name', '') if caller else '',
            'call_type': room['call_type']
        }, room=target['socket_id'])

@socketio.on('call_reject')
def handle_call_reject(data):
    room_id = data.get('room_id')
    reason = data.get('reason', 'rejected')
    room = active_rooms.get(room_id)
    if room:
        caller = user_statuses.get(room['caller_id'])
        if caller:
            emit('call_ended', {'room_id': room_id, 'reason': reason}, room=caller['socket_id'])
        cleanup_room(room_id)

@socketio.on('call_end')
def handle_call_end(data):
    room_id = data.get('room_id')
    end_call(room_id, data.get('vk_id'))

@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    room_id = data.get('room_id')
    target_id = data.get('target_id')
    offer = data.get('offer')
    target = user_statuses.get(target_id)
    if target:
        emit('webrtc_offer', {
            'room_id': room_id,
            'offer': offer,
            'from_id': data.get('from_id')
        }, room=target['socket_id'])

@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    room_id = data.get('room_id')
    target_id = data.get('target_id')
    answer = data.get('answer')
    target = user_statuses.get(target_id)
    if target:
        emit('webrtc_answer', {
            'room_id': room_id,
            'answer': answer,
            'from_id': data.get('from_id')
        }, room=target['socket_id'])

@socketio.on('webrtc_ice_candidate')
def handle_ice_candidate(data):
    room_id = data.get('room_id')
    target_id = data.get('target_id')
    candidate = data.get('candidate')
    target = user_statuses.get(target_id)
    if target:
        emit('webrtc_ice_candidate', {
            'room_id': room_id,
            'candidate': candidate,
            'from_id': data.get('from_id')
        }, room=target['socket_id'])

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data.get('room_id')
    join_room(room_id)
    emit('room_joined', {'room_id': room_id})

@socketio.on('leave_room')
def handle_leave_room(data):
    room_id = data.get('room_id')
    leave_room(room_id)

@socketio.on('get_user_status')
def handle_get_user_status(data):
    vk_id = data.get('vk_id')
    status = user_statuses.get(vk_id, {'status': 'offline'})
    emit('user_status', {'vk_id': vk_id, 'status': status})

def broadcast_user_status(vk_id):
    status = user_statuses.get(vk_id, {})
    emit('user_status_update', {
        'vk_id': vk_id,
        'status': status.get('status'),
        'in_call': status.get('in_call', False)
    }, broadcast=True, include_self=False)

def end_call(room_id, ended_by=None):
    room = active_rooms.get(room_id)
    if not room:
        return

    duration = 0
    if room.get('start_time'):
        start = datetime.fromisoformat(room['start_time'])
        duration = int((datetime.now() - start).total_seconds())

    caller_id = room['caller_id']
    target_id = room['target_id']

    record = {
        'room_id': room_id,
        'caller_id': caller_id,
        'target_id': target_id,
        'call_type': room.get('call_type', 'audio'),
        'duration': duration,
        'ended_by': ended_by,
        'ended_at': datetime.now().isoformat(),
        'status': 'completed' if duration > 0 else 'missed'
    }

    for uid in [caller_id, target_id]:
        if uid not in call_history:
            call_history[uid] = []
        call_history[uid].insert(0, record)
        if len(call_history[uid]) > 50:
            call_history[uid] = call_history[uid][:50]

    for uid in [caller_id, target_id]:
        user = user_statuses.get(uid)
        if user:
            user['in_call'] = False
            user['room_id'] = None
            if user.get('socket_id'):
                emit('call_ended', {
                    'room_id': room_id,
                    'duration': duration,
                    'reason': 'ended'
                }, room=user['socket_id'])

    cleanup_room(room_id)

def cleanup_room(room_id):
    if room_id in active_rooms:
        del active_rooms[room_id]

CALL_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#000000">
<title>VK Tsuyu Call</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;-webkit-touch-callout:none}
html,body{height:100%;overflow:hidden}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#000;color:#fff;-webkit-font-smoothing:antialiased;touch-action:manipulation}
.call-app{height:100vh;display:flex;flex-direction:column;position:relative;overflow:hidden}

.call-screen{position:fixed;top:0;left:0;width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:10;transition:opacity 0.3s ease,transform 0.3s ease}
.call-screen.hidden{opacity:0;pointer-events:none;transform:scale(0.95)}

.call-bg{position:absolute;top:0;left:0;width:100%;height:100%;background:#000;z-index:-1}
.call-bg-blur{position:absolute;top:0;left:0;width:100%;height:100%;background-size:cover;background-position:center;filter:blur(40px) brightness(0.3);z-index:-1;transition:background-image 0.5s ease}

.call-avatar{width:120px;height:120px;border-radius:50%;object-fit:cover;border:3px solid rgba(255,255,255,0.15);margin-bottom:20px;box-shadow:0 8px 32px rgba(0,0,0,0.5);transition:transform 0.3s ease}
.call-avatar.pulse{animation:avatarPulse 2s infinite ease-in-out}
@keyframes avatarPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}

.call-name{font-size:24px;font-weight:700;margin-bottom:6px;text-align:center;padding:0 20px}
.call-status{font-size:15px;color:#8e8e93;margin-bottom:40px;text-align:center}
.call-status.ringing{color:#0a84ff;animation:statusBlink 1.5s infinite}
.call-status.connecting{color:#34c759}
.call-status.in-call{color:#34c759}
@keyframes statusBlink{0%,100%{opacity:1}50%{opacity:0.5}}

.call-timer{font-size:18px;color:#fff;font-weight:600;margin-bottom:30px;font-variant-numeric:tabular-nums}

.call-controls{display:flex;align-items:center;gap:24px;margin-top:auto;margin-bottom:60px;padding:0 30px}
.call-btn{width:64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all 0.15s ease;border:none;outline:none;position:relative}
.call-btn:active{transform:scale(0.92)}
.call-btn svg{width:26px;height:26px}

.call-btn-mute{background:#2c2c2e;color:#fff}
.call-btn-mute.active{background:#0a84ff}
.call-btn-speaker{background:#2c2c2e;color:#fff}
.call-btn-speaker.active{background:#0a84ff}
.call-btn-video{background:#2c2c2e;color:#fff}
.call-btn-video.active{background:#0a84ff}
.call-btn-end{background:#ff3b30;color:#fff;width:72px;height:72px;box-shadow:0 4px 20px rgba(255,59,48,0.4)}
.call-btn-end:active{box-shadow:0 2px 10px rgba(255,59,48,0.3)}
.call-btn-accept{background:#34c759;color:#fff;width:72px;height:72px;box-shadow:0 4px 20px rgba(52,199,89,0.4)}
.call-btn-accept:active{box-shadow:0 2px 10px rgba(52,199,89,0.3)}
.call-btn-decline{background:#ff3b30;color:#fff;width:64px;height:64px}
.call-btn-flip{background:#2c2c2e;color:#fff}

.call-video-grid{position:fixed;top:0;left:0;width:100%;height:100%;z-index:5;display:grid;gap:2px;background:#000}
.call-video-grid.audio{grid-template-columns:1fr;grid-template-rows:1fr}
.call-video-grid.video{grid-template-columns:1fr;grid-template-rows:1fr 1fr}
.call-video-grid.video-peer-large{grid-template-columns:1fr;grid-template-rows:1fr 120px}
.call-video-grid.video-peer-large .local-video{grid-row:2}
.call-video-grid.video-peer-large .remote-video{grid-row:1}

.local-video,.remote-video{width:100%;height:100%;object-fit:cover;background:#111}
.local-video.mirror{transform:scaleX(-1)}
.local-video.pip{position:fixed;bottom:80px;right:12px;width:100px;height:140px;border-radius:12px;object-fit:cover;z-index:20;border:2px solid rgba(255,255,255,0.2);box-shadow:0 4px 16px rgba(0,0,0,0.5)}

.call-peer-info{position:fixed;top:16px;left:0;width:100%;text-align:center;z-index:15;padding:0 20px;pointer-events:none}
.call-peer-info .call-name{font-size:18px;margin-bottom:2px;text-shadow:0 2px 8px rgba(0,0,0,0.8)}
.call-peer-info .call-timer{font-size:14px;color:#8e8e93;margin-bottom:0;text-shadow:0 2px 8px rgba(0,0,0,0.8)}

.call-network-indicator{position:fixed;top:16px;right:16px;z-index:20;display:flex;align-items:center;gap:6px;background:rgba(0,0,0,0.6);padding:6px 10px;border-radius:12px;backdrop-filter:blur(8px)}
.call-network-dot{width:8px;height:8px;border-radius:50%;background:#34c759}
.call-network-dot.weak{background:#ff9500}
.call-network-dot.bad{background:#ff3b30}
.call-network-text{font-size:11px;color:#8e8e93}

.call-signal-bars{display:flex;align-items:flex-end;gap:2px;height:12px}
.call-signal-bar{width:3px;border-radius:1px;background:rgba(255,255,255,0.3);transition:background 0.3s ease}
.call-signal-bar.active{background:#34c759}
.call-signal-bar.weak{background:#ff9500}
.call-signal-bar.bad{background:#ff3b30}

.call-toast{position:fixed;top:60px;left:50%;transform:translateX(-50%) translateY(-20px);background:rgba(28,28,30,0.95);border:1px solid #3a3a3c;color:#fff;padding:10px 18px;border-radius:20px;font-size:13px;font-weight:500;z-index:100;opacity:0;transition:all 0.3s ease;pointer-events:none;white-space:nowrap;backdrop-filter:blur(8px)}
.call-toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

.call-permission-modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:200;display:flex;align-items:center;justify-content:center;padding:30px}
.call-permission-content{background:#1c1c1e;border-radius:20px;padding:30px 24px;max-width:340px;width:100%;text-align:center;border:1px solid #2c2c2e}
.call-permission-icon{width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:#2c2c2e;display:flex;align-items:center;justify-content:center}
.call-permission-icon svg{width:32px;height:32px;color:#0a84ff}
.call-permission-title{font-size:18px;font-weight:700;margin-bottom:8px}
.call-permission-text{font-size:14px;color:#8e8e93;margin-bottom:24px;line-height:1.5}
.call-permission-btn{width:100%;padding:14px;border:none;border-radius:14px;background:#0a84ff;color:#fff;font-size:16px;font-weight:600;cursor:pointer}
.call-permission-btn:active{opacity:0.8}

.call-setup-screen{position:fixed;top:0;left:0;width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;z-index:50}
.call-setup-title{font-size:22px;font-weight:700;margin-bottom:8px}
.call-setup-text{font-size:14px;color:#8e8e93;margin-bottom:30px;text-align:center;max-width:300px;line-height:1.5}
.call-setup-peer{display:flex;align-items:center;gap:14px;background:#1c1c1e;padding:14px 16px;border-radius:16px;width:100%;max-width:340px;margin-bottom:24px;border:1px solid #2c2c2e}
.call-setup-peer img{width:48px;height:48px;border-radius:50%;object-fit:cover;background:#222}
.call-setup-peer-info{flex:1;min-width:0}
.call-setup-peer-name{font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.call-setup-peer-status{font-size:13px;color:#8e8e93;margin-top:2px}
.call-setup-btns{display:flex;gap:16px;margin-top:8px}
.call-setup-btns .call-btn-accept,.call-setup-btns .call-btn-decline{width:64px;height:64px}

.call-back-btn{position:fixed;top:16px;left:16px;z-index:30;width:40px;height:40px;border-radius:50%;background:rgba(255,255,255,0.1);display:flex;align-items:center;justify-content:center;cursor:pointer;color:#fff;border:none}
.call-back-btn:active{background:rgba(255,255,255,0.2)}
.call-back-btn svg{width:22px;height:22px}

.call-mini-controls{position:fixed;bottom:0;left:0;width:100%;padding:16px 20px 40px;display:flex;justify-content:center;gap:20px;z-index:20;background:linear-gradient(to top,rgba(0,0,0,0.8) 0%,rgba(0,0,0,0) 100%)}
.call-mini-controls .call-btn{width:52px;height:52px}
.call-mini-controls .call-btn svg{width:22px;height:22px}

.call-ring-animation{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:200px;height:200px;z-index:-1}
.call-ring{position:absolute;top:0;left:0;width:100%;height:100%;border-radius:50%;border:2px solid rgba(10,132,255,0.3);animation:ringExpand 2s infinite ease-out}
.call-ring:nth-child(2){animation-delay:0.6s}
.call-ring:nth-child(3){animation-delay:1.2s}
@keyframes ringExpand{0%{transform:scale(0.8);opacity:1}100%{transform:scale(1.6);opacity:0}}

.call-waveform{position:fixed;bottom:100px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:3px;height:30px;z-index:15}
.call-waveform-bar{width:3px;border-radius:2px;background:rgba(255,255,255,0.4);animation:waveform 0.8s infinite ease-in-out alternate}
.call-waveform-bar:nth-child(1){height:40%;animation-delay:0s}
.call-waveform-bar:nth-child(2){height:70%;animation-delay:0.1s}
.call-waveform-bar:nth-child(3){height:100%;animation-delay:0.2s}
.call-waveform-bar:nth-child(4){height:60%;animation-delay:0.3s}
.call-waveform-bar:nth-child(5){height:80%;animation-delay:0.15s}
@keyframes waveform{0%{transform:scaleY(0.3);opacity:0.4}100%{transform:scaleY(1);opacity:1}}

.loader{border:2px solid #333;border-top:2px solid #fff;border-radius:50%;width:20px;height:20px;animation:spin 0.6s linear infinite;display:inline-block;vertical-align:middle}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}

@media (max-width:380px){
.call-controls{gap:16px}
.call-btn{width:56px;height:56px}
.call-btn-end,.call-btn-accept{width:64px;height:64px}
.call-avatar{width:100px;height:100px}
}

@media (orientation:landscape) and (max-height:500px){
.call-avatar{width:80px;height:80px;margin-bottom:12px}
.call-name{font-size:18px}
.call-status{margin-bottom:20px}
.call-controls{margin-bottom:20px}
.call-video-grid.video{grid-template-columns:1fr 1fr;grid-template-rows:1fr}
.call-video-grid.video-peer-large{grid-template-columns:1fr 120px;grid-template-rows:1fr}
.call-video-grid.video-peer-large .local-video{grid-column:2;grid-row:1}
.call-video-grid.video-peer-large .remote-video{grid-column:1;grid-row:1}
}
</style>
</head>
<body>
<div class="call-app">
<div id="testCallBar" style="position:fixed;top:0;left:0;width:100%;background:#0a84ff;color:#fff;text-align:center;padding:8px;font-size:13px;font-weight:600;z-index:300;cursor:pointer" onclick="startTestCall()">
🧪 РЕЖИМ ТЕСТИРОВАНИЯ: Нажмите для тестового звонка (2 вкладки = 1 ID)
</div>

<div class="call-permission-modal hidden" id="permModal">
<div class="call-permission-content">
<div class="call-permission-icon">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
</div>
<div class="call-permission-title">Разрешить доступ</div>
<div class="call-permission-text">Для звонков необходим доступ к микрофону и камере. Все данные передаются напрямую между устройствами (P2P).</div>
</div>
</div>

<div class="call-setup-screen hidden" id="setupScreen">
<div class="call-setup-title">Входящий звонок</div>
<div class="call-setup-text">Кто-то звонит вам через VK Tsuyu</div>
<div class="call-setup-peer" id="setupPeer">
<img src="" id="setupPeerImg" alt="">
<div class="call-setup-peer-info">
<div class="call-setup-peer-name" id="setupPeerName">...</div>
<div class="call-setup-peer-status" id="setupPeerStatus">Входящий звонок</div>
</div>
</div>
<div class="call-setup-btns">
<div class="call-btn call-btn-decline" onclick="declineCall()">
<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
</div>
<div class="call-btn call-btn-accept" onclick="acceptCall()">
<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
</div>
</div>
</div>

<div class="call-screen hidden" id="outgoingScreen">
<div class="call-bg-blur" id="outgoingBg"></div>
<div class="call-ring-animation"><div class="call-ring"></div><div class="call-ring"></div><div class="call-ring"></div></div>
<img class="call-avatar pulse" id="outgoingAvatar" src="" alt="">
<div class="call-name" id="outgoingName">...</div>
<div class="call-status ringing" id="outgoingStatus">Вызов...</div>
<div class="call-controls">
<div class="call-btn call-btn-mute" id="outgoingMuteBtn" onclick="toggleMute()">
<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
</div>
<div class="call-btn call-btn-speaker" id="outgoingSpeakerBtn" onclick="toggleSpeaker()">
<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
</div>
<div class="call-btn call-btn-end" onclick="endCall()">
<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
</div>
</div>
</div>

<div class="call-screen hidden" id="activeScreen">
<div class="call-video-grid audio" id="videoGrid">
<video class="remote-video" id="remoteVideo" autoplay playsinline></video>
<video class="local-video mirror" id="localVideo" autoplay playsinline muted></video>
</div>

<button class="call-back-btn" onclick="goBack()">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
</button>

<div class="call-peer-info">
<div class="call-name" id="activeName">...</div>
<div class="call-timer" id="activeTimer">0:00</div>
</div>

<div class="call-network-indicator">
<div class="call-signal-bars" id="signalBars">
<div class="call-signal-bar"></div>
<div class="call-signal-bar"></div>
<div class="call-signal-bar"></div>
<div class="call-signal-bar"></div>
</div>
<span class="call-network-text" id="networkText">Отлично</span>
</div>

<div class="call-waveform hidden" id="waveform">
<div class="call-waveform-bar"></div>
<div class="call-waveform-bar"></div>
<div class="call-waveform-bar"></div>
<div class="call-waveform-bar"></div>
<div class="call-waveform-bar"></div>
</div>

<div class="call-mini-controls" id="activeControls">
<div class="call-btn call-btn-mute" id="activeMuteBtn" onclick="toggleMute()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
</div>
<div class="call-btn call-btn-speaker" id="activeSpeakerBtn" onclick="toggleSpeaker()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
</div>
<div class="call-btn call-btn-video" id="activeVideoBtn" onclick="toggleVideo()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
</div>
<div class="call-btn call-btn-flip" id="flipBtn" onclick="flipCamera()">
<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 10c0-4.418-3.582-8-8-8s-8 3.582-8 8"/><path d="M4 14c0 4.418 3.582 8 8 8s8-3.582 8-8"/><polyline points="1 7 4 10 7 7"/><polyline points="23 17 20 14 17 17"/></svg>
</div>
<div class="call-btn call-btn-end" onclick="endCall()">
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
</div>
</div>
</div>

<div class="call-toast" id="callToast"></div>
</div>

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
const urlParams = new URLSearchParams(window.location.search);
const peerId = urlParams.get('peer');
const myVkId = localStorage.getItem('vk_my_id') || '';
const myName = localStorage.getItem('vk_my_name') || 'Я';
const myPhoto = localStorage.getItem('vk_my_photo') || '';
const callType = urlParams.get('type') || 'audio';
const isIncoming = urlParams.get('incoming') === '1';
const roomIdFromUrl = urlParams.get('room') || '';

let socket = null;
let pc = null;
let localStream = null;
let remoteStream = null;
let currentRoomId = roomIdFromUrl;
let callStartTime = null;
let callTimerInterval = null;
let isMuted = false;
let isSpeakerOn = false;
let isVideoEnabled = callType === 'video';
let isCallActive = false;
let currentFacingMode = 'user';
let iceServers = [];
let reconnectAttempts = 0;
let maxReconnectAttempts = 5;
let pendingCandidates = [];
let statsInterval = null;
let audioContext = null;
let audioAnalyser = null;
let dataChannel = null;
let networkQuality = 'good';

async function init() {
    await autoRequestPermissions();
    const iceRes = await fetch('/api/ice_config');
    const iceData = await iceRes.json();
    iceServers = iceData.iceServers || [];

    socket = io({transports: ['websocket', 'polling'], reconnection: true, reconnectionAttempts: maxReconnectAttempts, reconnectionDelay: 1000});

    socket.on('connect', () => {
        reconnectAttempts = 0;
        socket.emit('register', {vk_id: myVkId, name: myName, photo: myPhoto});
        if (isIncoming && roomIdFromUrl) {
            socket.emit('join_room', {room_id: roomIdFromUrl});
            showSetupScreen();
        } else if (peerId && !isIncoming) {
            setTimeout(() => startCallToPeer(), 500);
        }
    });

    socket.on('disconnect', () => {
        showToast('Соединение потеряно...');
    });

    socket.on('call_error', (data) => {
        showToast(data.error || 'Ошибка звонка');
        setTimeout(goBack, 2000);
    });

    socket.on('incoming_call', (data) => {
        currentRoomId = data.room_id;
        showSetupScreen(data);
    });

    socket.on('call_ringing', (data) => {
        showOutgoingScreen(data);
    });

    socket.on('call_connected', (data) => {
        showActiveScreen(data);
    });

    socket.on('call_ended', (data) => {
        showToast('Звонок завершен' + (data.duration ? ' (' + formatDuration(data.duration) + ')' : ''));
        cleanupAndExit();
    });

    socket.on('webrtc_offer', async (data) => {
        await handleOffer(data.offer, data.from_id);
    });

    socket.on('webrtc_answer', async (data) => {
        await handleAnswer(data.answer);
    });

    socket.on('webrtc_ice_candidate', async (data) => {
        await handleIceCandidate(data.candidate);
    });
}

async function requestPermissions() {
    try {
        const constraints = {
            audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true},
            video: isVideoEnabled ? {facingMode: 'user', width: {ideal: 640}, height: {ideal: 480}} : false
        };
        localStream = await navigator.mediaDevices.getUserMedia(constraints);
        document.getElementById('permModal').classList.add('hidden');
        if (isIncoming) {
            showSetupScreen();
        } else {
            showOutgoingScreen();
        }
    } catch(e) {
        showToast('Доступ к микрофону/камере отклонен');
    }
}
async function autoRequestPermissions() {
    try {
        const constraints = {
            audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true},
            video: isVideoEnabled ? {facingMode: 'user', width: {ideal: 640}, height: {ideal: 480}} : false
        };
        localStream = await navigator.mediaDevices.getUserMedia(constraints);
        document.getElementById('permModal').classList.add('hidden');
    } catch(e) {
        showToast('Доступ к микрофону/камере отклонен');
    }
}

async function startCallToPeer() {
    if (!localStream) {
        try {
            const constraints = {
                audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true},
                video: isVideoEnabled ? {facingMode: 'user', width: {ideal: 640}, height: {ideal: 480}} : false
            };
            localStream = await navigator.mediaDevices.getUserMedia(constraints);
        } catch(e) {
            showToast('Не удалось получить доступ к микрофону');
            return;
        }
    }

    document.getElementById('outgoingName').textContent = 'Вызов...';
    document.getElementById('outgoingAvatar').src = 'https://vk.com/images/camera_100.png';
    document.getElementById('outgoingScreen').classList.remove('hidden');

    try {
        const res = await fetch('/api/peer_status', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token: localStorage.getItem('vk_token'), peer_id: peerId})
        });
        const peerData = await res.json();
        document.getElementById('outgoingName').textContent = peerData.name || 'Собеседник';
        if (peerData.photo) {
            document.getElementById('outgoingAvatar').src = peerData.photo;
            document.getElementById('outgoingBg').style.backgroundImage = `url('${peerData.photo}')`;
        }
    } catch(e) {}

    socket.emit('call_request', {caller_id: myVkId, target_id: peerId, call_type: callType});
}

function showSetupScreen(data) {
    const screen = document.getElementById('setupScreen');
    screen.classList.remove('hidden');
    if (data) {
        document.getElementById('setupPeerName').textContent = data.caller_name || 'Неизвестно';
        document.getElementById('setupPeerImg').src = data.caller_photo || 'https://vk.com/images/camera_100.png';
        document.getElementById('setupPeerStatus').textContent = data.call_type === 'video' ? 'Видеозвонок' : 'Аудиозвонок';
    }
}

function showOutgoingScreen(data) {
    document.getElementById('setupScreen').classList.add('hidden');
    document.getElementById('outgoingScreen').classList.remove('hidden');
    if (data && data.target_name) {
        document.getElementById('outgoingName').textContent = data.target_name;
    }
}

async function acceptCall() {
    if (!localStream) {
        try {
            const constraints = {
                audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true},
                video: isVideoEnabled ? {facingMode: 'user'} : false
            };
            localStream = await navigator.mediaDevices.getUserMedia(constraints);
        } catch(e) {
            showToast('Не удалось получить доступ к микрофону');
            return;
        }
    }
    socket.emit('call_accept', {room_id: currentRoomId});
    document.getElementById('setupScreen').classList.add('hidden');
}

function declineCall() {
    socket.emit('call_reject', {room_id: currentRoomId, reason: 'rejected'});
    goBack();
}

async function showActiveScreen(data) {
    isCallActive = true;
    callStartTime = Date.now();
    document.getElementById('outgoingScreen').classList.add('hidden');
    document.getElementById('setupScreen').classList.add('hidden');
    document.getElementById('activeScreen').classList.remove('hidden');

    const grid = document.getElementById('videoGrid');
    if (isVideoEnabled) {
        grid.className = 'call-video-grid video';
        document.getElementById('localVideo').srcObject = localStream;
        document.getElementById('localVideo').classList.remove('hidden');
    } else {
        grid.className = 'call-video-grid audio';
        document.getElementById('localVideo').classList.add('hidden');
    }

    document.getElementById('activeName').textContent = data.peer_name || 'Собеседник';
    startCallTimer();
    await createPeerConnection(data.peer_id);

    if (!isIncoming) {
        const offer = await pc.createOffer({offerToReceiveAudio: true, offerToReceiveVideo: isVideoEnabled});
        await pc.setLocalDescription(offer);
        socket.emit('webrtc_offer', {room_id: currentRoomId, offer: offer, target_id: data.peer_id, from_id: myVkId});
    }

    startNetworkMonitoring();
}

async function createPeerConnection(targetId) {
    const config = {iceServers: iceServers, iceCandidatePoolSize: 10};
    pc = new RTCPeerConnection(config);

    pc.onicecandidate = (e) => {
        if (e.candidate) {
            socket.emit('webrtc_ice_candidate', {
                room_id: currentRoomId,
                candidate: e.candidate,
                target_id: targetId,
                from_id: myVkId
            });
        }
    };

    pc.ontrack = (e) => {
        remoteStream = e.streams[0];
        const remoteVideo = document.getElementById('remoteVideo');
        remoteVideo.srcObject = remoteStream;
        remoteVideo.onloadedmetadata = () => {
            remoteVideo.play().catch(()=>{});
        };
    };

    pc.onconnectionstatechange = () => {
        const state = pc.connectionState;
        if (state === 'connected') {
            showToast('Соединение установлено');
            document.getElementById('outgoingStatus').textContent = 'В разговоре';
            document.getElementById('outgoingStatus').className = 'call-status in-call';
        } else if (state === 'failed' || state === 'disconnected') {
            showToast('Соединение прервано');
            setTimeout(() => { if (isCallActive) endCall(); }, 3000);
        }
    };

    pc.oniceconnectionstatechange = () => {
        const state = pc.iceConnectionState;
        if (state === 'connected' || state === 'completed') {
            document.getElementById('waveform').classList.remove('hidden');
        } else if (state === 'failed') {
            pc.restartIce();
        }
    };

    localStream.getTracks().forEach(track => {
        pc.addTrack(track, localStream);
    });

    try {
        dataChannel = pc.createDataChannel('stats', {ordered: false, maxRetransmits: 0});
        dataChannel.onmessage = (e) => {
            try {
                const stats = JSON.parse(e.data);
                updateNetworkQuality(stats);
            } catch(err) {}
        };
    } catch(e) {}
}

async function handleOffer(offer, fromId) {
    if (!pc) await createPeerConnection(fromId);
    await pc.setRemoteDescription(new RTCSessionDescription(offer));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    socket.emit('webrtc_answer', {room_id: currentRoomId, answer: answer, target_id: fromId, from_id: myVkId});
}

async function handleAnswer(answer) {
    await pc.setRemoteDescription(new RTCSessionDescription(answer));
}

async function handleIceCandidate(candidate) {
    try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
    } catch(e) {
        pendingCandidates.push(candidate);
    }
}

function toggleMute() {
    if (!localStream) return;
    isMuted = !isMuted;
    localStream.getAudioTracks().forEach(t => t.enabled = !isMuted);
    document.querySelectorAll('.call-btn-mute').forEach(btn => {
        btn.classList.toggle('active', isMuted);
    });
    showToast(isMuted ? 'Микрофон выключен' : 'Микрофон включен');
}

function toggleSpeaker() {
    isSpeakerOn = !isSpeakerOn;
    const audioElem = document.getElementById('remoteVideo');
    if (audioElem && audioElem.setSinkId && typeof audioElem.setSinkId === 'function') {
        navigator.mediaDevices.enumerateDevices().then(devices => {
            const speaker = devices.find(d => d.kind === 'audiooutput' && d.label.toLowerCase().includes('speaker'));
            if (speaker) {
                audioElem.setSinkId(speaker.deviceId).catch(()=>{});
            }
        });
    }
    document.querySelectorAll('.call-btn-speaker').forEach(btn => {
        btn.classList.toggle('active', isSpeakerOn);
    });
    showToast(isSpeakerOn ? 'Громкая связь' : 'Тихий режим');
}

async function toggleVideo() {
    if (!localStream) return;
    const videoTrack = localStream.getVideoTracks()[0];
    if (videoTrack) {
        videoTrack.enabled = !videoTrack.enabled;
        isVideoEnabled = videoTrack.enabled;
    } else if (!isVideoEnabled) {
        try {
            const newStream = await navigator.mediaDevices.getUserMedia({video: {facingMode: currentFacingMode}});
            const newTrack = newStream.getVideoTracks()[0];
            localStream.addTrack(newTrack);
            if (pc) {
                const sender = pc.getSenders().find(s => s.track && s.track.kind === 'video');
                if (sender) sender.replaceTrack(newTrack);
                else pc.addTrack(newTrack, localStream);
            }
            isVideoEnabled = true;
        } catch(e) {
            showToast('Камера недоступна');
            return;
        }
    }

    const grid = document.getElementById('videoGrid');
    const localVideo = document.getElementById('localVideo');
    if (isVideoEnabled) {
        grid.className = 'call-video-grid video';
        localVideo.classList.remove('hidden');
        localVideo.srcObject = localStream;
    } else {
        grid.className = 'call-video-grid audio';
        localVideo.classList.add('hidden');
    }
    document.getElementById('activeVideoBtn').classList.toggle('active', isVideoEnabled);
}

async function flipCamera() {
    currentFacingMode = currentFacingMode === 'user' ? 'environment' : 'user';
    if (!localStream) return;
    const videoTrack = localStream.getVideoTracks()[0];
    if (!videoTrack) return;
    try {
        const newStream = await navigator.mediaDevices.getUserMedia({video: {facingMode: currentFacingMode}});
        const newTrack = newStream.getVideoTracks()[0];
        if (pc) {
            const sender = pc.getSenders().find(s => s.track === videoTrack);
            if (sender) await sender.replaceTrack(newTrack);
        }
        localStream.removeTrack(videoTrack);
        videoTrack.stop();
        localStream.addTrack(newTrack);
        const localVideo = document.getElementById('localVideo');
        localVideo.srcObject = localStream;
        localVideo.classList.toggle('mirror', currentFacingMode === 'user');
    } catch(e) {
        showToast('Не удалось переключить камеру');
    }
}

function endCall() {
    socket.emit('call_end', {room_id: currentRoomId, vk_id: myVkId});
    cleanupAndExit();
}

function cleanupAndExit() {
    isCallActive = false;
    if (callTimerInterval) clearInterval(callTimerInterval);
    if (statsInterval) clearInterval(statsInterval);
    if (pc) {
        pc.close();
        pc = null;
    }
    if (localStream) {
        localStream.getTracks().forEach(t => t.stop());
        localStream = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    remoteStream = null;
    pendingCandidates = [];
    if (socket) {
        socket.disconnect();
    }
    setTimeout(goBack, 1500);
}

function goBack() {
    window.location.href = '/';
}

function startCallTimer() {
    callTimerInterval = setInterval(() => {
        if (!callStartTime) return;
        const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
        document.getElementById('activeTimer').textContent = formatDuration(elapsed);
    }, 1000);
}

function formatDuration(sec) {
    const m = Math.floor(sec / 60);
    const s = (sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

function showToast(msg) {
    const toast = document.getElementById('callToast');
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

function startNetworkMonitoring() {
    statsInterval = setInterval(async () => {
        if (!pc || pc.connectionState !== 'connected') return;
        try {
            const stats = await pc.getStats();
            let packetsLost = 0;
            let packetsReceived = 0;
            let jitter = 0;
            let rtt = 0;

            stats.forEach(report => {
                if (report.type === 'inbound-rtp' && report.kind === 'audio') {
                    packetsLost = report.packetsLost || 0;
                    packetsReceived = report.packetsReceived || 1;
                    jitter = report.jitter || 0;
                }
                if (report.type === 'candidate-pair' && report.state === 'succeeded') {
                    rtt = report.currentRoundTripTime || 0;
                }
            });

            const lossRate = packetsReceived > 0 ? packetsLost / (packetsLost + packetsReceived) : 0;
            updateSignalBars(lossRate, rtt, jitter);

            if (dataChannel && dataChannel.readyState === 'open') {
                dataChannel.send(JSON.stringify({lossRate, rtt, jitter}));
            }
        } catch(e) {}
    }, 2000);
}

function updateSignalBars(lossRate, rtt, jitter) {
    const bars = document.querySelectorAll('#signalBars .call-signal-bar');
    const text = document.getElementById('networkText');
    const dot = document.querySelector('.call-network-dot');

    let activeCount = 4;
    let quality = 'Отлично';

    if (lossRate > 0.05 || rtt > 0.3 || jitter > 0.1) {
        activeCount = 2;
        quality = 'Среднее';
        networkQuality = 'weak';
    }
    if (lossRate > 0.15 || rtt > 0.6 || jitter > 0.2) {
        activeCount = 1;
        quality = 'Плохое';
        networkQuality = 'bad';
    }
    if (lossRate > 0.3 || rtt > 1.0) {
        activeCount = 0;
        quality = 'Очень плохое';
        networkQuality = 'bad';
    }

    bars.forEach((bar, i) => {
        bar.classList.toggle('active', i < activeCount);
        bar.classList.toggle('weak', networkQuality === 'weak' && i < activeCount);
        bar.classList.toggle('bad', networkQuality === 'bad' && i < activeCount);
    });

    text.textContent = quality;
    if (dot) {
        dot.className = 'call-network-dot';
        if (networkQuality === 'weak') dot.classList.add('weak');
        if (networkQuality === 'bad') dot.classList.add('bad');
    }
}

function updateNetworkQuality(peerStats) {
    const combinedLoss = (peerStats.lossRate || 0);
    const combinedRtt = (peerStats.rtt || 0);
    updateSignalBars(combinedLoss, combinedRtt, 0);
}

window.onbeforeunload = () => {
    if (isCallActive) {
        socket.emit('call_end', {room_id: currentRoomId, vk_id: myVkId});
    }
};

document.addEventListener('visibilitychange', () => {
    if (document.hidden && isCallActive && localStream) {
        localStream.getAudioTracks().forEach(t => t.enabled = false);
    } else if (!document.hidden && isCallActive && localStream && !isMuted) {
        localStream.getAudioTracks().forEach(t => t.enabled = true);
    }
});

init();
</script>
</body>
</html>
"""

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8081)), debug=False)
