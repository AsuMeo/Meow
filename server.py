import os
import random
import time
import threading
from collections import deque
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading', ping_interval=20, ping_timeout=60)

# One shared in-memory world. For a multi-process deployment, replace this with Redis.
TILE = 32
WORLD_W = 300
WORLD_H = 100
TICK = 1 / 30
MAX_PLAYERS = 100

# 0 air, 1 grass, 2 dirt, 3 stone, 4 wood
BLOCKS = {
    1: {'name': 'Трава', 'color': '#55b957', 'solid': True},
    2: {'name': 'Земля', 'color': '#9a633d', 'solid': True},
    3: {'name': 'Камень', 'color': '#777b86', 'solid': True},
    4: {'name': 'Дерево', 'color': '#9c6338', 'solid': True},
}

world_lock = threading.RLock()
world = {}
players = {}
inputs = {}
chat_messages = deque(maxlen=50)
last_tick = time.time()


def generate_world():
    rng = random.Random(20260804)
    heights = []
    h = 42
    for x in range(WORLD_W):
        h += rng.choice([-1, 0, 0, 0, 1])
        h = max(28, min(55, h))
        heights.append(h)

    result = {}
    for x, surface in enumerate(heights):
        result[(x, surface)] = 1
        for y in range(surface + 1, min(WORLD_H, surface + 5)):
            result[(x, y)] = 2
        for y in range(surface + 5, WORLD_H):
            result[(x, y)] = 3

    # Small trees, leaving spawn area clear.
    for x in range(8, WORLD_W - 8, 13):
        if 80 < x < 120:
            continue
        surface = heights[x]
        for y in range(surface - 1, max(2, surface - 5), -1):
            result[(x, y)] = 4
        for dx in (-1, 0, 1):
            for dy in (-5, -6):
                result[(x + dx, surface + dy)] = 4
    return result


world = generate_world()


def clamp(v, low, high):
    return max(low, min(high, v))


def spawn_point():
    x = 100
    with world_lock:
        for y in range(2, WORLD_H - 2):
            if (x, y) in world and (x, y - 1) not in world:
                return x * TILE + 4, (y - 2) * TILE
    return 100 * TILE, 20 * TILE


def player_public(p):
    return {
        'id': p['id'], 'name': p['name'], 'x': round(p['x'], 1), 'y': round(p['y'], 1),
        'vx': round(p['vx'], 1), 'vy': round(p['vy'], 1), 'color': p['color'],
        'w': p['w'], 'h': p['h'],
    }


def is_solid(tx, ty):
    if tx < 0 or tx >= WORLD_W or ty >= WORLD_H:
        return True
    return ty >= 0 and (tx, ty) in world and BLOCKS.get(world[(tx, ty)], {}).get('solid', False)


def collides(x, y, w, h):
    left = int(x // TILE)
    right = int((x + w - 0.01) // TILE)
    top = int(y // TILE)
    bottom = int((y + h - 0.01) // TILE)
    return any(is_solid(tx, ty) for tx in range(left, right + 1) for ty in range(top, bottom + 1))


def move_player(p, inp):
    speed = 230.0
    gravity = 900.0
    jump = 420.0
    p['vx'] = float(inp.get('x', 0)) * speed
    if inp.get('jump') and p['grounded']:
        p['vy'] = -jump
        p['grounded'] = False
    p['vy'] = min(p['vy'] + gravity * TICK, 850)

    nx = p['x'] + p['vx'] * TICK
    if not collides(nx, p['y'], p['w'], p['h']):
        p['x'] = nx
    else:
        step = 1 if p['vx'] > 0 else -1
        while abs(nx - p['x']) > 0.1 and not collides(p['x'] + step, p['y'], p['w'], p['h']):
            p['x'] += step
            nx = p['x'] + p['vx'] * TICK
        p['vx'] = 0

    old_y = p['y']
    ny = p['y'] + p['vy'] * TICK
    if not collides(p['x'], ny, p['w'], p['h']):
        p['y'] = ny
        p['grounded'] = False
    else:
        if p['vy'] > 0:
            p['grounded'] = True
            p['y'] = int((p['y'] + p['h']) // TILE) * TILE - p['h']
        p['vy'] = 0
    p['x'] = clamp(p['x'], 0, WORLD_W * TILE - p['w'])
    p['y'] = clamp(p['y'], 0, WORLD_H * TILE - p['h'])


def valid_tile(tx, ty):
    return 0 <= tx < WORLD_W and 0 <= ty < WORLD_H


def can_reach(p, tx, ty):
    cx = p['x'] + p['w'] / 2
    cy = p['y'] + p['h'] / 2
    return ((tx + 0.5) * TILE - cx) ** 2 + ((ty + 0.5) * TILE - cy) ** 2 <= (TILE * 7) ** 2


def broadcast_world_patch(patch):
    if patch:
        socketio.emit('world_patch', patch)


def game_loop():
    global last_tick
    while True:
        start = time.time()
        with world_lock:
            for sid, p in list(players.items()):
                move_player(p, inputs.get(sid, {}))
            snapshot = {'players': [player_public(p) for p in players.values()]}
        socketio.emit('state', snapshot)
        elapsed = time.time() - start
        socketio.sleep(max(0.001, TICK - elapsed))


@app.route('/')
def index():
    return render_template_string(PAGE)


@socketio.on('connect')
def on_connect():
    if len(players) >= MAX_PLAYERS:
        return False
    sid = __import__('flask').request.sid
    x, y = spawn_point()
    with world_lock:
        players[sid] = {
            'id': sid, 'name': f'Игрок-{random.randint(100, 999)}', 'x': x, 'y': y,
            'vx': 0, 'vy': 0, 'w': 24, 'h': 30, 'grounded': False,
            'color': random.choice(['#ff6b6b', '#ffd166', '#4dd4ac', '#6ea8fe', '#d28cff']),
        }
        inputs[sid] = {}
        initial = {'w': WORLD_W, 'h': WORLD_H, 'tile': TILE,
                   'blocks': [{'x': x, 'y': y, 'type': t} for (x, y), t in world.items()],
                   'players': [player_public(p) for p in players.values()],
                   'chat': list(chat_messages)}
    emit('init', initial)
    socketio.emit('notice', {'text': f"{players[sid]['name']} зашёл в мир"})


@socketio.on('disconnect')
def on_disconnect():
    sid = __import__('flask').request.sid
    with world_lock:
        old = players.pop(sid, None)
        inputs.pop(sid, None)
    if old:
        socketio.emit('notice', {'text': f"{old['name']} вышел из мира"})


@socketio.on('set_name')
def set_name(data):
    sid = __import__('flask').request.sid
    name = str((data or {}).get('name', '')).strip()[:18]
    if not name:
        return
    with world_lock:
        if sid in players:
            players[sid]['name'] = name
            emit('you', player_public(players[sid]))


@socketio.on('input')
def on_input(data):
    sid = __import__('flask').request.sid
    data = data or {}
    with world_lock:
        if sid in players:
            inputs[sid] = {'x': clamp(int(data.get('x', 0)), -1, 1), 'jump': bool(data.get('jump'))}


@socketio.on('edit_block')
def edit_block(data):
    sid = __import__('flask').request.sid
    try:
        tx, ty = int(data.get('x')), int(data.get('y'))
        action = str(data.get('action', 'place'))
        block_type = int(data.get('type', 2))
    except (TypeError, ValueError):
        return
    with world_lock:
        p = players.get(sid)
        if not p or not valid_tile(tx, ty) or not can_reach(p, tx, ty):
            return
        if action == 'break':
            if (tx, ty) in world:
                del world[(tx, ty)]
                broadcast_world_patch({'x': tx, 'y': ty, 'type': 0})
        elif action == 'place' and block_type in BLOCKS and (tx, ty) not in world:
            # Do not allow placing a block inside a player.
            if not collides(tx * TILE, ty * TILE, 1, 1):
                world[(tx, ty)] = block_type
                broadcast_world_patch({'x': tx, 'y': ty, 'type': block_type})


@socketio.on('chat')
def on_chat(data):
    sid = __import__('flask').request.sid
    text = str((data or {}).get('text', '')).strip()[:160]
    with world_lock:
        p = players.get(sid)
        if not p or not text:
            return
        item = {'name': p['name'], 'text': text, 'color': p['color']}
        chat_messages.append(item)
    socketio.emit('chat', item)


PAGE = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>BlockWorld Online</title>
<style>
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#10131b;color:#fff;font-family:Inter,system-ui,Arial}#game{display:block;width:100vw;height:100vh;image-rendering:pixelated;cursor:crosshair}.hud{position:fixed;z-index:3;top:12px;left:12px;right:12px;display:flex;justify-content:space-between;pointer-events:none}.panel{pointer-events:auto;background:#10131bcc;border:1px solid #ffffff22;border-radius:12px;padding:9px 11px;backdrop-filter:blur(8px);font-size:13px}.title{font-weight:800;color:#ffd166}.help{color:#bfc8d6;line-height:1.45}.name{margin-top:7px;display:flex;gap:6px}.name input,.chatInput{background:#202634;border:1px solid #ffffff22;color:#fff;border-radius:8px;padding:6px 8px;outline:0}.name button,.send{background:#ffd166;color:#151820;border:0;border-radius:8px;padding:6px 9px;font-weight:700}.chat{position:fixed;z-index:4;left:12px;bottom:12px;width:min(370px,calc(100vw - 24px));pointer-events:none}.chatlog{max-height:145px;overflow:hidden;display:flex;flex-direction:column;gap:3px;margin-bottom:6px;text-shadow:0 1px 2px #000}.chatline{font-size:13px}.chatForm{display:flex;gap:6px;pointer-events:auto}.chatInput{flex:1;min-width:0}.mobile{display:none;position:fixed;z-index:5;bottom:18px;right:18px;gap:10px}.mobile button{width:54px;height:54px;border-radius:50%;border:1px solid #fff4;background:#151a27dd;color:#fff;font-size:22px}@media(max-width:700px){.help{display:none}.mobile{display:flex}.chat{bottom:84px}.panel{font-size:12px}}
</style></head><body><canvas id="game"></canvas>
<div class="hud"><div class="panel"><div class="title">BLOCKWORLD ONLINE</div><div id="online">Подключение...</div><div class="name"><input id="name" maxlength="18" placeholder="Имя игрока"><button onclick="setName()">OK</button></div></div><div class="panel help">A/D или ←/→ — бег<br>W/Пробел — прыжок<br>ЛКМ — поставить блок<br>ПКМ — сломать блок<br>1/2/3 — выбрать блок</div></div>
<div class="chat"><div id="chatlog" class="chatlog"></div><form class="chatForm" onsubmit="sendChat(event)"><input id="chatInput" class="chatInput" maxlength="160" autocomplete="off" placeholder="Чат мира..."><button class="send">➤</button></form></div>
<div class="mobile"><button ontouchstart="mobileLeft=1" ontouchend="mobileLeft=0">◀</button><button ontouchstart="mobileJump=1" ontouchend="mobileJump=0">▲</button><button ontouchstart="mobileRight=1" ontouchend="mobileRight=0">▶</button></div>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script><script>
const socket=io({transports:['websocket','polling']});const c=document.getElementById('game'),ctx=c.getContext('2d');let W=300,H=100,T=32,blocks=new Map(),players=new Map(),me=null,camera={x:0,y:0},selected=2,keys={},mobileLeft=0,mobileRight=0,mobileJump=0;
const colors={1:'#55b957',2:'#9a633d',3:'#777b86',4:'#9c6338'};
function resize(){c.width=innerWidth*devicePixelRatio;c.height=innerHeight*devicePixelRatio;c.style.width=innerWidth+'px';c.style.height=innerHeight+'px';ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0)}addEventListener('resize',resize);resize();
function key(x,y){return x+','+y}function addChat(i){let e=document.createElement('div');e.className='chatline';e.innerHTML='<b style="color:'+safe(i.color||'#fff')+'">'+safe(i.name||'')+':</b> '+safe(i.text||i.text);let l=document.getElementById('chatlog');l.appendChild(e);while(l.children.length>8)l.firstChild.remove();setTimeout(()=>e.remove(),12000)}function safe(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function setName(){let n=document.getElementById('name').value.trim();if(n)socket.emit('set_name',{name:n})}function sendChat(e){e.preventDefault();let i=document.getElementById('chatInput'),t=i.value.trim();if(t){socket.emit('chat',{text:t});i.value=''}}
socket.on('connect',()=>document.getElementById('online').textContent='Онлайн: подключено');socket.on('disconnect',()=>document.getElementById('online').textContent='Соединение потеряно');socket.on('init',d=>{W=d.w;H=d.h;T=d.tile;d.blocks.forEach(b=>blocks.set(key(b.x,b.y),b.type));d.players.forEach(p=>players.set(p.id,p));d.chat.forEach(addChat)});socket.on('you',p=>{me=p;players.set(p.id,p);document.getElementById('name').value=p.name});socket.on('state',d=>{d.players.forEach(p=>{players.set(p.id,p);if(p.id===me?.id)me=p})});socket.on('world_patch',b=>{b.type?blocks.set(key(b.x,b.y),b.type):blocks.delete(key(b.x,b.y))});socket.on('chat',addChat);socket.on('notice',i=>{let e={name:'Мир',text:i.text,color:'#ffd166'};addChat(e)});
addEventListener('keydown',e=>{keys[e.key.toLowerCase()]=1;if([' ','arrowup','arrowdown'].includes(e.key.toLowerCase()))e.preventDefault();if(e.key==='1')selected=1;if(e.key==='2')selected=2;if(e.key==='3')selected=3;if(e.key==='4')selected=4});addEventListener('keyup',e=>keys[e.key.toLowerCase()]=0);
c.addEventListener('contextmenu',e=>e.preventDefault());c.addEventListener('mousedown',e=>{if(!me)return;let r=c.getBoundingClientRect(),tx=Math.floor((e.clientX+camera.x)/T),ty=Math.floor((e.clientY+camera.y)/T);socket.emit('edit_block',{x:tx,y:ty,action:e.button===2?'break':'place',type:selected})});
setInterval(()=>{let x=(keys.a||keys.arrowleft||mobileLeft)?-1:((keys.d||keys.arrowright||mobileRight)?1:0),jump=!!(keys.w||keys[' ']||keys.arrowup||mobileJump);socket.emit('input',{x,jump})},33);
function draw(){let ww=innerWidth,hh=innerHeight;ctx.clearRect(0,0,ww,hh);let sky=ctx.createLinearGradient(0,0,0,hh);sky.addColorStop(0,'#6bb9e8');sky.addColorStop(1,'#d3edff');ctx.fillStyle=sky;ctx.fillRect(0,0,ww,hh);if(me){camera.x=me.x+me.w/2-ww/2;camera.y=me.y+me.h/2-hh/2;camera.x=Math.max(0,Math.min(W*T-ww,camera.x));camera.y=Math.max(0,Math.min(H*T-hh,camera.y))}let x0=Math.floor(camera.x/T)-1,x1=Math.ceil((camera.x+ww)/T)+1,y0=Math.floor(camera.y/T)-1,y1=Math.ceil((camera.y+hh)/T)+1;for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){let b=blocks.get(key(x,y));if(b){ctx.fillStyle=colors[b]||'#888';ctx.fillRect(x*T-camera.x,y*T-camera.y,T,T);ctx.strokeStyle='#0002';ctx.strokeRect(x*T-camera.x,y*T-camera.y,T,T);if(b===1){ctx.fillStyle='#79dc70';ctx.fillRect(x*T-camera.x,y*T-camera.y,T,4)}}}players.forEach(p=>{let px=p.x-camera.x,py=p.y-camera.y;ctx.fillStyle=p.color;ctx.fillRect(px,py,p.w,p.h);ctx.fillStyle='#ffe0bd';ctx.fillRect(px+5,py+3,p.w-10,10);ctx.fillStyle='#111';ctx.fillRect(px+8,py+6,3,3);ctx.fillRect(px+16,py+6,3,3);ctx.font='12px system-ui';ctx.textAlign='center';ctx.fillStyle='#fff';ctx.strokeStyle='#111';ctx.lineWidth=3;ctx.strokeText(p.name,px+p.w/2,py-7);ctx.fillText(p.name,px+p.w/2,py-7)});ctx.textAlign='left';ctx.fillStyle='#10131bcc';ctx.fillRect(12,innerHeight-55,150,43);ctx.fillStyle='#fff';ctx.font='12px system-ui';ctx.fillText('Блок: '+selected+'  |  Игроков: '+players.size,20,innerHeight-31);requestAnimationFrame(draw)}draw();
</script></body></html>'''

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8080')), allow_unsafe_werkzeug=True)
