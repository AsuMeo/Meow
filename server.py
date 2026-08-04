import os
import random
import time
import threading
from collections import deque
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'blockworld-mobile-secret')
socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='threading',
    ping_interval=15,
    ping_timeout=45,
    logger=False,
    engineio_logger=False,
)

TILE = 32
WORLD_W = 300
WORLD_H = 100
TICK = 1 / 30
MAX_PLAYERS = 100

BLOCKS = {
    1: {'name': 'Трава', 'color': '#55b957', 'solid': True},
    2: {'name': 'Земля', 'color': '#9a633d', 'solid': True},
    3: {'name': 'Камень', 'color': '#777b86', 'solid': True},
    4: {'name': 'Дерево', 'color': '#9c6338', 'solid': True},
}

world_lock = threading.RLock()
players = {}
inputs = {}
world = {}
chat_messages = deque(maxlen=40)


def generate_world():
    rng = random.Random(20260804)
    heights = []
    height = 42

    for x in range(WORLD_W):
        height += rng.choice([-1, 0, 0, 0, 1])
        height = max(28, min(55, height))
        heights.append(height)

    result = {}
    for x, surface in enumerate(heights):
        result[(x, surface)] = 1
        for y in range(surface + 1, min(WORLD_H, surface + 5)):
            result[(x, y)] = 2
        for y in range(surface + 5, WORLD_H):
            result[(x, y)] = 3

    for x in range(10, WORLD_W - 10, 14):
        if 85 <= x <= 115:
            continue
        surface = heights[x]
        for y in range(surface - 1, max(1, surface - 5), -1):
            result[(x, y)] = 4
        for dx in (-1, 0, 1):
            for dy in (-5, -6):
                if 0 <= x + dx < WORLD_W:
                    result[(x + dx, surface + dy)] = 4

    return result


world = generate_world()


def clamp(value, low, high):
    return max(low, min(high, value))


def spawn_point():
    spawn_x = 100
    for y in range(2, WORLD_H - 2):
        if (spawn_x, y) in world and (spawn_x, y - 1) not in world:
            return spawn_x * TILE + 4, (y - 2) * TILE
    return spawn_x * TILE, 20 * TILE


def player_public(player):
    return {
        'id': player['id'],
        'name': player['name'],
        'x': round(player['x'], 2),
        'y': round(player['y'], 2),
        'vx': round(player['vx'], 2),
        'vy': round(player['vy'], 2),
        'color': player['color'],
        'w': player['w'],
        'h': player['h'],
    }


def is_solid(tx, ty):
    if tx < 0 or tx >= WORLD_W or ty >= WORLD_H:
        return True
    if ty < 0:
        return False
    return (tx, ty) in world and BLOCKS.get(world[(tx, ty)], {}).get('solid', False)


def collides(x, y, width, height):
    left = int(x // TILE)
    right = int((x + width - 0.01) // TILE)
    top = int(y // TILE)
    bottom = int((y + height - 0.01) // TILE)
    for tx in range(left, right + 1):
        for ty in range(top, bottom + 1):
            if is_solid(tx, ty):
                return True
    return False


def move_player(player, control):
    speed = 230.0
    gravity = 1000.0
    jump_speed = 430.0

    direction = clamp(int(control.get('x', 0)), -1, 1)
    player['vx'] = direction * speed

    # jump_request is latched on the server, so a short mobile tap cannot be lost.
    if control.get('jump_request') and player['grounded']:
        player['vy'] = -jump_speed
        player['grounded'] = False
    control['jump_request'] = False

    player['vy'] = min(player['vy'] + gravity * TICK, 900.0)

    new_x = player['x'] + player['vx'] * TICK
    if not collides(new_x, player['y'], player['w'], player['h']):
        player['x'] = new_x
    else:
        player['vx'] = 0

    new_y = player['y'] + player['vy'] * TICK
    if not collides(player['x'], new_y, player['w'], player['h']):
        player['y'] = new_y
        player['grounded'] = False
    else:
        if player['vy'] > 0:
            player['grounded'] = True
            player['y'] = int((player['y'] + player['h']) // TILE) * TILE - player['h']
        player['vy'] = 0

    player['x'] = clamp(player['x'], 0, WORLD_W * TILE - player['w'])
    player['y'] = clamp(player['y'], 0, WORLD_H * TILE - player['h'])


def valid_tile(tx, ty):
    return 0 <= tx < WORLD_W and 0 <= ty < WORLD_H


def can_reach(player, tx, ty):
    center_x = player['x'] + player['w'] / 2
    center_y = player['y'] + player['h'] / 2
    target_x = (tx + 0.5) * TILE
    target_y = (ty + 0.5) * TILE
    return (target_x - center_x) ** 2 + (target_y - center_y) ** 2 <= (TILE * 7) ** 2


def game_loop():
    while True:
        started = time.perf_counter()
        with world_lock:
            for sid, player in list(players.items()):
                move_player(player, inputs.setdefault(sid, {'x': 0, 'jump_request': False}))
            state = {'players': [player_public(p) for p in players.values()]}
        socketio.emit('state', state)
        elapsed = time.perf_counter() - started
        socketio.sleep(max(0.001, TICK - elapsed))


@app.route('/')
def index():
    return render_template_string(PAGE)


@socketio.on('connect')
def connect_player():
    sid = request.sid
    with world_lock:
        if len(players) >= MAX_PLAYERS:
            return False
        x, y = spawn_point()
        player = {
            'id': sid,
            'name': f'Игрок-{random.randint(100, 999)}',
            'x': x,
            'y': y,
            'vx': 0,
            'vy': 0,
            'w': 24,
            'h': 30,
            'grounded': False,
            'color': random.choice(['#ff6b6b', '#ffd166', '#4dd4ac', '#6ea8fe', '#d28cff']),
        }
        players[sid] = player
        inputs[sid] = {'x': 0, 'jump_request': False}
        initial = {
            'w': WORLD_W,
            'h': WORLD_H,
            'tile': TILE,
            'blocks': [{'x': x, 'y': y, 'type': block} for (x, y), block in world.items()],
            'players': [player_public(p) for p in players.values()],
            'chat': list(chat_messages),
        }

    emit('init', initial)
    socketio.emit('notice', {'text': f"{player['name']} зашёл в мир"})


@socketio.on('disconnect')
def disconnect_player():
    sid = request.sid
    with world_lock:
        old = players.pop(sid, None)
        inputs.pop(sid, None)
    if old:
        socketio.emit('notice', {'text': f"{old['name']} вышел из мира"})


@socketio.on('set_name')
def set_name(data):
    sid = request.sid
    name = str((data or {}).get('name', '')).strip()[:18]
    if not name:
        return
    with world_lock:
        if sid in players:
            players[sid]['name'] = name
            emit('you', player_public(players[sid]))


@socketio.on('input')
def receive_input(data):
    sid = request.sid
    data = data or {}
    with world_lock:
        if sid not in players:
            return
        control = inputs.setdefault(sid, {'x': 0, 'jump_request': False})
        control['x'] = clamp(int(data.get('x', 0)), -1, 1)
        if bool(data.get('jump')):
            control['jump_request'] = True


@socketio.on('edit_block')
def edit_block(data):
    sid = request.sid
    try:
        tx = int(data.get('x'))
        ty = int(data.get('y'))
        action = str(data.get('action', 'place'))
        block_type = int(data.get('type', 2))
    except (TypeError, ValueError, AttributeError):
        return

    with world_lock:
        player = players.get(sid)
        if not player or not valid_tile(tx, ty) or not can_reach(player, tx, ty):
            return

        if action == 'break':
            if (tx, ty) in world:
                del world[(tx, ty)]
                socketio.emit('world_patch', {'x': tx, 'y': ty, 'type': 0})
        elif action == 'place' and block_type in BLOCKS and (tx, ty) not in world:
            # Prevent placing directly inside the player.
            if not collides(tx * TILE + 1, ty * TILE + 1, TILE - 2, TILE - 2):
                world[(tx, ty)] = block_type
                socketio.emit('world_patch', {'x': tx, 'y': ty, 'type': block_type})


@socketio.on('chat')
def chat(data):
    sid = request.sid
    text = str((data or {}).get('text', '')).strip()[:160]
    with world_lock:
        player = players.get(sid)
        if not player or not text:
            return
        message = {'name': player['name'], 'text': text, 'color': player['color']}
        chat_messages.append(message)
    socketio.emit('chat', message)


PAGE = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>BlockWorld Mobile</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#111;color:#fff;font-family:system-ui,Arial;touch-action:none}
body{user-select:none;-webkit-user-select:none}
#game{position:fixed;inset:0;width:100vw;height:100vh;display:block;image-rendering:pixelated;touch-action:none}
.top{position:fixed;z-index:5;top:env(safe-area-inset-top,10px);left:10px;right:10px;display:flex;justify-content:space-between;pointer-events:none}
.panel{background:#111827dd;border:1px solid #ffffff26;border-radius:12px;padding:8px 10px;backdrop-filter:blur(8px);font-size:12px;pointer-events:auto}
.title{font-weight:900;color:#ffd166}.help{color:#d5dbea;text-align:right;line-height:1.35}
.name{display:flex;gap:5px;margin-top:6px}.name input{width:115px;background:#20283a;color:#fff;border:1px solid #ffffff25;border-radius:7px;padding:5px;outline:none}.name button,.send{border:0;border-radius:7px;background:#ffd166;color:#141923;font-weight:800;padding:5px 8px}
.controls{position:fixed;z-index:6;left:18px;right:18px;bottom:calc(18px + env(safe-area-inset-bottom));display:flex;justify-content:space-between;align-items:end;pointer-events:none}
.pad,.actions{display:flex;gap:10px;pointer-events:auto}.control{width:64px;height:64px;border:1px solid #ffffff35;border-radius:50%;background:#111827dd;color:#fff;font-size:27px;font-weight:800;box-shadow:0 5px 18px #0005;touch-action:none}.control:active,.control.on{background:#3c5477;transform:scale(.95)}
.actions{align-items:end}.small{width:48px;height:48px;font-size:18px}.selected{border-color:#ffd166;color:#ffd166}
.chat{position:fixed;z-index:7;left:10px;bottom:92px;width:min(370px,calc(100vw - 20px));pointer-events:none}.log{max-height:115px;overflow:hidden;text-shadow:0 1px 2px #000}.line{font-size:12px;margin:2px 0}.chatform{display:flex;gap:5px;margin-top:5px;pointer-events:auto}.chatinput{flex:1;min-width:0;background:#111827dd;color:#fff;border:1px solid #ffffff25;border-radius:8px;padding:7px;outline:none}
.rotate{display:none;position:fixed;z-index:20;inset:0;background:#10131b;color:#fff;align-items:center;justify-content:center;text-align:center;padding:30px;font-size:20px;font-weight:800}
@media(orientation:portrait){.rotate{display:flex}.top,.controls,.chat{display:none}}
@media(max-height:430px){.help{display:none}.control{width:54px;height:54px}.small{width:43px;height:43px}.chat{bottom:75px}}
</style>
</head>
<body>
<div class="rotate">Поверните телефон горизонтально<br>↔</div>
<canvas id="game"></canvas>
<div class="top"><div class="panel"><div class="title">BLOCKWORLD</div><div id="online">Подключение...</div><div class="name"><input id="name" maxlength="18" placeholder="Имя"><button onclick="setName()">OK</button></div></div><div class="panel help">◀ ▶ — движение<br>▲ — прыжок<br>Кнопка блока — режим</div></div>
<div class="controls"><div class="pad"><button id="left" class="control">◀</button><button id="right" class="control">▶</button></div><div class="actions"><button id="mode" class="control small selected">＋</button><button id="jump" class="control">▲</button></div></div>
<div class="chat"><div id="log" class="log"></div><form class="chatform" onsubmit="sendChat(event)"><input id="chatinput" class="chatinput" maxlength="160" placeholder="Чат мира"><button class="send">➤</button></form></div>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
const socket=io({transports:['websocket','polling'],upgrade:true});
const canvas=document.getElementById('game'),ctx=canvas.getContext('2d');
let worldW=300,worldH=100,T=32,blocks=new Map(),players=new Map(),me=null,camera={x:0,y:0};
let direction=0,jumpHeld=false,editMode='place',selectedBlock=2,lastTouch=0;
const colors={1:'#55b957',2:'#9a633d',3:'#777b86',4:'#9c6338'};
function resize(){const d=Math.min(devicePixelRatio||1,2);canvas.width=innerWidth*d;canvas.height=innerHeight*d;canvas.style.width=innerWidth+'px';canvas.style.height=innerHeight+'px';ctx.setTransform(d,0,0,d,0,0)}addEventListener('resize',resize);resize();
function k(x,y){return x+','+y}function safe(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function addLine(i){const e=document.createElement('div');e.className='line';e.innerHTML='<b style="color:'+safe(i.color||'#fff')+'">'+safe(i.name||'')+':</b> '+safe(i.text||'');const l=document.getElementById('log');l.appendChild(e);while(l.children.length>7)l.firstChild.remove();setTimeout(()=>e.remove(),12000)}
function setName(){const n=document.getElementById('name').value.trim();if(n)socket.emit('set_name',{name:n})}function sendChat(e){e.preventDefault();const i=document.getElementById('chatinput'),t=i.value.trim();if(t){socket.emit('chat',{text:t});i.value=''}}
function setDirection(v){direction=v;sendInput()}function sendInput(){socket.emit('input',{x:direction,jump:jumpHeld})}
function bindHold(id,v){const b=document.getElementById(id);const down=e=>{e.preventDefault();b.classList.add('on');setDirection(v)};const up=e=>{e.preventDefault();b.classList.remove('on');if(direction===v)setDirection(0)};b.addEventListener('pointerdown',down);b.addEventListener('pointerup',up);b.addEventListener('pointercancel',up);b.addEventListener('pointerleave',up)}
bindHold('left',-1);bindHold('right',1);
const jump=document.getElementById('jump');const jumpDown=e=>{e.preventDefault();jump.classList.add('on');jumpHeld=true;sendInput()};const jumpUp=e=>{e.preventDefault();jump.classList.remove('on');jumpHeld=false;sendInput()};jump.addEventListener('pointerdown',jumpDown);jump.addEventListener('pointerup',jumpUp);jump.addEventListener('pointercancel',jumpUp);jump.addEventListener('pointerleave',jumpUp);
document.getElementById('mode').addEventListener('pointerdown',e=>{e.preventDefault();editMode=editMode==='place'?'break':'place';e.currentTarget.textContent=editMode==='place'?'＋':'−';e.currentTarget.classList.toggle('selected',editMode==='place')});
setInterval(sendInput,50);
function touchEdit(e){if(e.target!==canvas)return;const r=canvas.getBoundingClientRect(),tx=Math.floor((e.clientX+camera.x)/T),ty=Math.floor((e.clientY+camera.y)/T);socket.emit('edit_block',{x:tx,y:ty,action:editMode,type:selectedBlock})}
canvas.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse')return;e.preventDefault();if(Date.now()-lastTouch<120)return;lastTouch=Date.now();touchEdit(e)});
canvas.addEventListener('contextmenu',e=>e.preventDefault());
socket.on('connect',()=>document.getElementById('online').textContent='Онлайн: подключено');socket.on('disconnect',()=>document.getElementById('online').textContent='Соединение потеряно');
socket.on('init',d=>{worldW=d.w;worldH=d.h;T=d.tile;d.blocks.forEach(b=>blocks.set(k(b.x,b.y),b.type));d.players.forEach(p=>players.set(p.id,p));d.chat.forEach(addLine)});socket.on('you',p=>{me=p;players.set(p.id,p);document.getElementById('name').value=p.name});socket.on('state',d=>{d.players.forEach(p=>{players.set(p.id,p);if(me&&p.id===me.id)me=p})});socket.on('world_patch',b=>{if(b.type)blocks.set(k(b.x,b.y),b.type);else blocks.delete(k(b.x,b.y))});socket.on('chat',addLine);socket.on('notice',i=>addLine({name:'Мир',text:i.text,color:'#ffd166'}));
function draw(){const w=innerWidth,h=innerHeight;ctx.clearRect(0,0,w,h);const sky=ctx.createLinearGradient(0,0,0,h);sky.addColorStop(0,'#65b4e5');sky.addColorStop(1,'#d5efff');ctx.fillStyle=sky;ctx.fillRect(0,0,w,h);if(me){camera.x=me.x+me.w/2-w/2;camera.y=me.y+me.h/2-h/2;camera.x=Math.max(0,Math.min(worldW*T-w,camera.x));camera.y=Math.max(0,Math.min(worldH*T-h,camera.y))}const x0=Math.floor(camera.x/T)-1,x1=Math.ceil((camera.x+w)/T)+1,y0=Math.floor(camera.y/T)-1,y1=Math.ceil((camera.y+h)/T)+1;for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){const b=blocks.get(k(x,y));if(!b)continue;ctx.fillStyle=colors[b]||'#888';ctx.fillRect(x*T-camera.x,y*T-camera.y,T,T);ctx.strokeStyle='#0002';ctx.strokeRect(x*T-camera.x,y*T-camera.y,T,T);if(b===1){ctx.fillStyle='#86df77';ctx.fillRect(x*T-camera.x,y*T-camera.y,T,4)}}players.forEach(p=>{const x=p.x-camera.x,y=p.y-camera.y;ctx.fillStyle=p.color;ctx.fillRect(x,y,p.w,p.h);ctx.fillStyle='#ffe0bd';ctx.fillRect(x+5,y+3,p.w-10,10);ctx.fillStyle='#111';ctx.fillRect(x+8,y+6,3,3);ctx.fillRect(x+16,y+6,3,3);ctx.font='12px system-ui';ctx.textAlign='center';ctx.lineWidth=3;ctx.strokeStyle='#111';ctx.strokeText(p.name,x+p.w/2,y-7);ctx.fillStyle='#fff';ctx.fillText(p.name,x+p.w/2,y-7)});ctx.textAlign='left';requestAnimationFrame(draw)}draw();
try{if(screen.orientation&&screen.orientation.lock)screen.orientation.lock('landscape').catch(()=>{})}catch(e){}
</script>
</body></html>'''


if __name__ == '__main__':
    socketio.run(
        app,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', '8080')),
        allow_unsafe_werkzeug=True,
    )
