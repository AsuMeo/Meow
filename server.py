import os, json, random, math, time
from flask import Flask, request
from flask_socketio import SocketIO, emit

app = Flask(__name__, static_folder='.')
app.config['SECRET_KEY'] = 'terraria-like-game-secret-2026-fixed-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)

# === HARDCODED FIREBASE CLIENT CONFIG (for frontend only) ===
FIREBASE_API_KEY = "AIzaSyBm0mIvHVznIeF2PoFk6dtdaiT5r877wyA"
FIREBASE_AUTH_DOMAIN = "meow-874ce.firebaseapp.com"
FIREBASE_DATABASE_URL = "https://meow-874ce-default-rtdb.europe-west1.firebasedatabase.app"
FIREBASE_PROJECT_ID = "meow-874ce"

# === SIMPLE FILE-BASED STORAGE (works on Railway ephemeral disk) ===
DATA_FILE = '/tmp/game_data.json'

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'players': {}, 'world': {}}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
    except:
        pass

game_data = load_data()

# === GAME CONFIG ===
CHUNK_SIZE = 16
WORLD_HEIGHT = 256
WORLD_WIDTH = 4096
SEED = 42
random.seed(SEED)

# === WORLD DATA ===
world_blocks = {}
players = {}
player_sids = {}

# Load world from file if exists
for key, chunk in game_data.get('world', {}).items():
    parts = key.split('_')
    if len(parts) == 2:
        world_blocks[(int(parts[0]), int(parts[1]))] = chunk

# === BLOCK TYPES ===
BLOCKS = {
    0: {'name': 'air', 'solid': False, 'color': 'transparent'},
    1: {'name': 'dirt', 'solid': True, 'color': '#8B5A2B'},
    2: {'name': 'grass', 'solid': True, 'color': '#4CAF50'},
    3: {'name': 'stone', 'solid': True, 'color': '#808080'},
    4: {'name': 'wood', 'solid': True, 'color': '#8B6914'},
    5: {'name': 'sand', 'solid': True, 'color': '#F0E68C'},
    6: {'name': 'water', 'solid': False, 'color': '#2196F3'},
    7: {'name': 'coal', 'solid': True, 'color': '#2F2F2F'},
    8: {'name': 'iron', 'solid': True, 'color': '#B87333'},
    9: {'name': 'gold', 'solid': True, 'color': '#FFD700'},
    10: {'name': 'diamond', 'solid': True, 'color': '#00CED1'},
    11: {'name': 'torch', 'solid': False, 'color': '#FF9800'},
    12: {'name': 'leaf', 'solid': False, 'color': '#228B22'},
    13: {'name': 'brick', 'solid': True, 'color': '#B22222'},
    14: {'name': 'glass', 'solid': False, 'color': '#87CEEB'},
    15: {'name': 'bedrock', 'solid': True, 'color': '#1a1a1a'},
}

# === PROCEDURAL WORLD ===
def get_chunk(cx, cy):
    if (cx, cy) not in world_blocks:
        world_blocks[(cx, cy)] = generate_chunk(cx, cy)
    return world_blocks[(cx, cy)]

def generate_chunk(cx, cy):
    chunk = [[0]*CHUNK_SIZE for _ in range(CHUNK_SIZE)]
    base_y = WORLD_HEIGHT // 2
    for lx in range(CHUNK_SIZE):
        wx = cx * CHUNK_SIZE + lx
        height = base_y + int(math.sin(wx * 0.05) * 8 + math.sin(wx * 0.13) * 4 + random.uniform(-2, 2))
        for ly in range(CHUNK_SIZE):
            wy = cy * CHUNK_SIZE + ly
            if wy > WORLD_HEIGHT - 5:
                chunk[ly][lx] = 15
            elif wy > height + 20:
                r = random.random()
                if r < 0.02: chunk[ly][lx] = 10
                elif r < 0.05: chunk[ly][lx] = 9
                elif r < 0.10: chunk[ly][lx] = 8
                elif r < 0.15: chunk[ly][lx] = 7
                else: chunk[ly][lx] = 3
            elif wy > height + 3:
                chunk[ly][lx] = 3
            elif wy == height:
                chunk[ly][lx] = 2
            elif wy > height - 3 and wy < height:
                chunk[ly][lx] = 1
            elif wy >= height - 8 and wy < height - 3:
                chunk[ly][lx] = 1
            elif wy < height - 8:
                chunk[ly][lx] = 3
    for lx in range(2, CHUNK_SIZE - 2):
        wx = cx * CHUNK_SIZE + lx
        height = base_y + int(math.sin(wx * 0.05) * 8 + math.sin(wx * 0.13) * 4)
        tree_h = random.randint(3, 6)
        if random.random() < 0.06:
            for th in range(1, tree_h + 1):
                tcy = (height - th) // CHUNK_SIZE
                tly = (height - th) % CHUNK_SIZE
                if tcy == cy:
                    chunk[tly][lx] = 4
            for ly_off in range(-1, 2):
                for lx_off in range(-1, 2):
                    lcy = (height - tree_h + ly_off) // CHUNK_SIZE
                    lly = (height - tree_h + ly_off) % CHUNK_SIZE
                    llx = lx + lx_off
                    if lcy == cy and 0 <= lly < CHUNK_SIZE and 0 <= llx < CHUNK_SIZE:
                        if chunk[lly][llx] == 0:
                            chunk[lly][llx] = 12
    return chunk

def get_block(wx, wy):
    cx, lx = divmod(wx, CHUNK_SIZE)
    cy, ly = divmod(wy, CHUNK_SIZE)
    chunk = get_chunk(cx, cy)
    if 0 <= ly < CHUNK_SIZE and 0 <= lx < CHUNK_SIZE:
        return chunk[ly][lx]
    return 0

def set_block(wx, wy, block_id):
    cx, lx = divmod(wx, CHUNK_SIZE)
    cy, ly = divmod(wy, CHUNK_SIZE)
    chunk = get_chunk(cx, cy)
    if 0 <= ly < CHUNK_SIZE and 0 <= lx < CHUNK_SIZE:
        chunk[ly][lx] = block_id
        return True
    return False

# === PHYSICS ===
PLAYER_W = 0.8
PLAYER_H = 1.8
GRAVITY = 0.6
JUMP_VELOCITY = -12
MOVE_SPEED = 0.5
MAX_SPEED = 6
FRICTION = 0.85

def is_solid(bx, by):
    b = get_block(bx, by)
    return BLOCKS.get(b, {}).get('solid', False)

def check_collision(px, py):
    for by in range(int(py), int(py + PLAYER_H) + 1):
        for bx in range(int(px), int(px + PLAYER_W) + 1):
            if is_solid(bx, by):
                return True
    return False

def resolve_collision(px, py, vx, vy):
    new_x = px + vx
    if check_collision(new_x, py):
        if vx > 0:
            new_x = int(new_x + PLAYER_W) - PLAYER_W - 0.01
        elif vx < 0:
            new_x = int(new_x) + 1 + 0.01
        vx = 0
    new_y = py + vy
    on_ground = False
    if check_collision(new_x, new_y):
        if vy > 0:
            new_y = int(new_y + PLAYER_H) - PLAYER_H - 0.01
            on_ground = True
        elif vy < 0:
            new_y = int(new_y) + 1 + 0.01
        vy = 0
    new_x = max(0, min(WORLD_WIDTH - PLAYER_W, new_x))
    new_y = max(0, min(WORLD_HEIGHT - PLAYER_H, new_y))
    return new_x, new_y, vx, vy, on_ground

# === GAME LOOP ===
def game_loop():
    while True:
        socketio.sleep(0.016)
        for sid, p in list(players.items()):
            p['vy'] += GRAVITY * 0.016 * 60
            p['vy'] = min(p['vy'], 20)
            p['vx'] *= FRICTION
            if abs(p['vx']) < 0.01:
                p['vx'] = 0
            p['x'], p['y'], p['vx'], p['vy'], on_ground = resolve_collision(p['x'], p['y'], p['vx'], p['vy'])
            p['on_ground'] = on_ground
            if abs(p['vx']) > 0.1:
                p['anim'] = 'walk'
            else:
                p['anim'] = 'idle'
            p['x'] = max(0, min(WORLD_WIDTH - PLAYER_W, p['x']))
            p['y'] = max(0, min(WORLD_HEIGHT - PLAYER_H, p['y']))

socketio.start_background_task(game_loop)

# === SOCKET EVENTS ===
@app.route('/')
def index():
    return HTML_PAGE

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    emit('init', {
        'world_width': WORLD_WIDTH,
        'world_height': WORLD_HEIGHT,
        'chunk_size': CHUNK_SIZE,
        'blocks': BLOCKS
    })

@socketio.on('auth')
def handle_auth(data):
    print(f"Auth received from {request.sid}: {data}")
    uid = data.get('uid', '')
    name = data.get('name', 'Player')

    # Load from file storage
    saved = game_data.get('players', {}).get(uid, {})
    x = saved.get('x', WORLD_WIDTH // 2)
    y = saved.get('y', WORLD_HEIGHT // 2 - 20)

    players[request.sid] = {
        'x': x, 'y': y, 'vx': 0, 'vy': 0,
        'uid': uid, 'name': name, 'facing': 1, 'anim': 'idle',
        'on_ground': False, 'inventory': {1: 99, 2: 99, 3: 50, 4: 50, 11: 20}
    }
    player_sids[uid] = request.sid

    # Send chunks around spawn
    cx = int(x) // CHUNK_SIZE
    cy = int(y) // CHUNK_SIZE
    for dcx in range(-3, 4):
        for dcy in range(-3, 4):
            chunk = get_chunk(cx + dcx, cy + dcy)
            emit('chunk', {'cx': cx + dcx, 'cy': cy + dcy, 'data': chunk})

    # Send other players
    for sid2, p2 in players.items():
        if sid2 != request.sid:
            emit('player_join', {
                'sid': sid2, 'x': p2['x'], 'y': p2['y'],
                'name': p2['name'], 'facing': p2['facing'], 'anim': p2['anim']
            })

    # Notify others about new player
    p = players[request.sid]
    emit('player_join', {
        'sid': request.sid, 'x': p['x'], 'y': p['y'],
        'name': p['name'], 'facing': p['facing'], 'anim': p['anim']
    }, broadcast=True, include_self=False)

    emit('auth_ok', {'x': p['x'], 'y': p['y']})
    print(f"Auth OK sent to {request.sid}")

@socketio.on('move')
def handle_move(data):
    if request.sid not in players:
        return
    p = players[request.sid]
    dir_x = data.get('dx', 0)
    jump = data.get('jump', False)
    if dir_x != 0:
        p['vx'] += dir_x * MOVE_SPEED
        p['vx'] = max(-MAX_SPEED, min(MAX_SPEED, p['vx']))
        p['facing'] = 1 if dir_x > 0 else -1
    if jump and p['on_ground']:
        p['vy'] = JUMP_VELOCITY
        p['on_ground'] = False

@socketio.on('place_block')
def handle_place(data):
    if request.sid not in players:
        return
    bx = data.get('x', 0)
    by = data.get('y', 0)
    block_id = data.get('block', 1)
    p = players[request.sid]
    dist = math.sqrt((p['x'] - bx)**2 + (p['y'] - by)**2)
    if dist > 8:
        return
    if set_block(bx, by, block_id):
        emit('block_update', {'x': bx, 'y': by, 'block': block_id}, broadcast=True)

@socketio.on('break_block')
def handle_break(data):
    if request.sid not in players:
        return
    bx = data.get('x', 0)
    by = data.get('y', 0)
    p = players[request.sid]
    dist = math.sqrt((p['x'] - bx)**2 + (p['y'] - by)**2)
    if dist > 8:
        return
    if set_block(bx, by, 0):
        emit('block_update', {'x': bx, 'y': by, 'block': 0}, broadcast=True)

@socketio.on('request_chunks')
def handle_chunks(data):
    cx = data.get('cx', 0)
    cy = data.get('cy', 0)
    for dcx in range(-3, 4):
        for dcy in range(-3, 4):
            chunk = get_chunk(cx + dcx, cy + dcy)
            emit('chunk', {'cx': cx + dcx, 'cy': cy + dcy, 'data': chunk})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    if request.sid in players:
        p = players[request.sid]
        # Save to file
        if 'players' not in game_data:
            game_data['players'] = {}
        game_data['players'][p['uid']] = {'x': p['x'], 'y': p['y'], 'last_seen': time.time()}
        save_data(game_data)
        del player_sids[p['uid']]
        del players[request.sid]
    emit('player_leave', {'sid': request.sid}, broadcast=True, include_self=False)

# === BROADCAST LOOP ===
def broadcast_loop():
    while True:
        socketio.sleep(0.05)
        if players:
            state = {
                sid: {
                    'x': p['x'], 'y': p['y'], 'vx': p['vx'], 'vy': p['vy'],
                    'facing': p['facing'], 'anim': p['anim'], 'name': p['name']
                }
                for sid, p in players.items()
            }
            socketio.emit('players_state', state)

socketio.start_background_task(broadcast_loop)

# === SAVE LOOP ===
def save_loop():
    while True:
        socketio.sleep(30)
        try:
            game_data['world'] = {f"{cx}_{cy}": chunk for (cx, cy), chunk in world_blocks.items()}
            save_data(game_data)
            print("World saved to file")
        except Exception as e:
            print(f"Save error: {e}")

socketio.start_background_task(save_loop)

# ===================== HTML PAGE =====================
HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>TerraBlock Online</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-database-compat.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body {
  width: 100%; height: 100%; overflow: hidden;
  background: #0a0a0a; font-family: 'Segoe UI', system-ui, sans-serif;
  touch-action: none; user-select: none; -webkit-user-select: none;
}
#gameCanvas {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  image-rendering: pixelated; image-rendering: crisp-edges;
}
#ui-layer {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 10;
}
#ui-layer > * { pointer-events: auto; }

#authScreen {
  position: fixed; inset: 0; background: linear-gradient(180deg, #0d1b2a 0%, #1b2838 50%, #0d1b2a 100%);
  display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100;
  gap: 16px; padding: 20px;
}
#authScreen h1 {
  font-size: clamp(28px, 8vw, 52px); color: #4fc3f7; text-shadow: 0 0 20px rgba(79,195,247,0.5);
  letter-spacing: 4px; margin-bottom: 10px;
}
#authScreen .subtitle { color: #90a4ae; font-size: 14px; margin-bottom: 20px; text-align: center; }
.auth-input {
  width: min(300px, 80vw); padding: 14px 18px; border-radius: 12px;
  border: 2px solid #37474f; background: rgba(13,27,42,0.8); color: #fff;
  font-size: 16px; outline: none; transition: border-color 0.3s;
}
.auth-input:focus { border-color: #4fc3f7; }
.auth-btn {
  width: min(300px, 80vw); padding: 14px; border-radius: 12px; border: none;
  background: linear-gradient(135deg, #0288d1, #4fc3f7); color: #fff;
  font-size: 16px; font-weight: bold; cursor: pointer; transition: transform 0.1s, box-shadow 0.3s;
  box-shadow: 0 4px 15px rgba(2,136,209,0.4);
}
.auth-btn:active { transform: scale(0.97); }
.auth-btn.secondary { background: linear-gradient(135deg, #455a64, #607d8b); }
.auth-error { color: #ef5350; font-size: 13px; min-height: 18px; }

#mobileControls {
  position: fixed; bottom: 0; left: 0; width: 100%; height: 180px;
  display: flex; justify-content: space-between; align-items: flex-end;
  padding: 10px 15px 25px; z-index: 20; pointer-events: none;
}
#mobileControls > * { pointer-events: auto; }
.dpad {
  display: grid; grid-template-columns: 55px 55px 55px;
  grid-template-rows: 55px 55px; gap: 4px;
}
.dpad-btn {
  width: 55px; height: 55px; border-radius: 14px;
  background: rgba(255,255,255,0.12); border: 2px solid rgba(255,255,255,0.2);
  color: #fff; font-size: 22px; display: flex; align-items: center; justify-content: center;
  cursor: pointer; backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
  transition: background 0.1s, transform 0.05s; touch-action: manipulation;
}
.dpad-btn:active { background: rgba(79,195,247,0.4); transform: scale(0.92); }
.dpad-btn.empty { visibility: hidden; }

.action-btns {
  display: flex; flex-direction: column; gap: 10px; align-items: flex-end;
}
.action-btn {
  width: 65px; height: 65px; border-radius: 50%;
  background: rgba(255,255,255,0.12); border: 2px solid rgba(255,255,255,0.2);
  color: #fff; font-size: 13px; font-weight: bold;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; backdrop-filter: blur(8px); touch-action: manipulation;
  transition: background 0.1s, transform 0.05s;
}
.action-btn.jump { background: rgba(76,175,80,0.25); border-color: rgba(76,175,80,0.5); }
.action-btn.jump:active { background: rgba(76,175,80,0.6); }
.action-btn.break { background: rgba(239,83,80,0.25); border-color: rgba(239,83,80,0.5); }
.action-btn.break:active { background: rgba(239,83,80,0.6); }
.action-btn.place { background: rgba(33,150,243,0.25); border-color: rgba(33,150,243,0.5); }
.action-btn.place:active { background: rgba(33,150,243,0.6); }

#hotbar {
  position: fixed; bottom: 195px; left: 50%; transform: translateX(-50%);
  display: flex; gap: 6px; z-index: 20;
}
.hotbar-slot {
  width: 48px; height: 48px; border-radius: 10px;
  background: rgba(0,0,0,0.5); border: 2px solid rgba(255,255,255,0.15);
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; color: #fff; cursor: pointer; position: relative;
  backdrop-filter: blur(4px);
}
.hotbar-slot.active { border-color: #4fc3f7; box-shadow: 0 0 10px rgba(79,195,247,0.4); }
.hotbar-slot .block-preview { width: 28px; height: 28px; border-radius: 4px; }
.hotbar-slot .slot-num { position: absolute; top: 2px; left: 4px; font-size: 9px; color: rgba(255,255,255,0.6); }

#topBar {
  position: fixed; top: 0; left: 0; width: 100%;
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; z-index: 20; background: rgba(0,0,0,0.3);
  backdrop-filter: blur(4px);
}
#topBar .player-info { color: #fff; font-size: 13px; }
#topBar .coords { color: #90a4ae; font-size: 11px; }
#fullscreenBtn {
  padding: 6px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2);
  background: rgba(0,0,0,0.4); color: #fff; font-size: 12px; cursor: pointer;
}

#playerList {
  position: fixed; top: 45px; right: 10px;
  background: rgba(0,0,0,0.6); border-radius: 10px;
  padding: 8px 12px; color: #fff; font-size: 12px;
  max-width: 150px; backdrop-filter: blur(4px);
}
#playerList .pl-title { color: #4fc3f7; font-weight: bold; margin-bottom: 4px; font-size: 11px; }
#playerList .pl-item { padding: 2px 0; opacity: 0.9; }

#loadingScreen {
  position: fixed; inset: 0; background: #0a0a0a;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  z-index: 200; color: #4fc3f7; gap: 15px;
}
.spinner {
  width: 50px; height: 50px; border: 3px solid rgba(79,195,247,0.2);
  border-top-color: #4fc3f7; border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

#blockMenu {
  position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  background: rgba(13,27,42,0.95); border-radius: 16px;
  padding: 16px; display: none; grid-template-columns: repeat(4, 1fr);
  gap: 8px; z-index: 50; max-width: 300px; backdrop-filter: blur(10px);
  border: 1px solid rgba(255,255,255,0.1);
}
.block-option {
  width: 60px; height: 60px; border-radius: 10px;
  background: rgba(255,255,255,0.08); border: 2px solid transparent;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  cursor: pointer; color: #fff; font-size: 10px; gap: 4px;
}
.block-option:hover { border-color: #4fc3f7; }
.block-option .bprev { width: 28px; height: 28px; border-radius: 4px; }

#musicToggle {
  position: fixed; top: 45px; left: 10px;
  padding: 6px 12px; border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.2);
  background: rgba(0,0,0,0.4); color: #fff; font-size: 12px;
  cursor: pointer; z-index: 20;
}

#touchArea {
  position: fixed; inset: 0; z-index: 5; pointer-events: auto;
}
</style>
</head>
<body>

<div id="loadingScreen">
  <div class="spinner"></div>
  <div>Loading world...</div>
</div>

<div id="authScreen">
  <h1>TERRABLOCK</h1>
  <div class="subtitle">Online sandbox 2D like Terraria<br>One world for all players</div>
  <input type="email" id="email" class="auth-input" placeholder="Email" autocomplete="email">
  <input type="password" id="password" class="auth-input" placeholder="Password" autocomplete="current-password">
  <div class="auth-error" id="authError"></div>
  <button class="auth-btn" id="loginBtn">Login</button>
  <button class="auth-btn secondary" id="registerBtn">Register</button>
</div>

<canvas id="gameCanvas"></canvas>
<div id="touchArea"></div>

<div id="ui-layer">
  <div id="topBar">
    <div>
      <div class="player-info" id="playerName">Player</div>
      <div class="coords" id="coords">0, 0</div>
    </div>
    <button id="fullscreenBtn">Fullscreen</button>
  </div>

  <button id="musicToggle">Music</button>

  <div id="playerList">
    <div class="pl-title">Online</div>
    <div id="plItems"></div>
  </div>

  <div id="hotbar"></div>

  <div id="mobileControls">
    <div class="dpad">
      <div class="dpad-btn empty"></div>
      <div class="dpad-btn" id="btnUp" data-dir="0,-1">&#9650;</div>
      <div class="dpad-btn empty"></div>
      <div class="dpad-btn" id="btnLeft" data-dir="-1,0">&#9664;</div>
      <div class="dpad-btn empty"></div>
      <div class="dpad-btn" id="btnRight" data-dir="1,0">&#9654;</div>
    </div>
    <div class="action-btns">
      <div class="action-btn jump" id="btnJump">JUMP</div>
      <div style="display:flex;gap:8px;">
        <div class="action-btn break" id="btnBreak">&#128296;</div>
        <div class="action-btn place" id="btnPlace">&#11035;</div>
      </div>
    </div>
  </div>

  <div id="blockMenu"></div>
</div>

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

const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
let socket = null;
let myUid = null;
let myName = 'Player';
let worldData = {};
let players = {};
let blocksInfo = {};
let chunkSize = 16;
let worldW = 4096, worldH = 256;
let camera = { x: 0, y: 0 };
let myPlayer = null;
let selectedBlock = 1;
let musicPlaying = false;
let audioCtx = null;
let musicGain = null;
let chunksReceived = 0;
let gameStarted = false;

const BLOCK_COLORS = {
  0: null,
  1: '#8B5A2B', 2: '#4CAF50', 3: '#808080', 4: '#8B6914',
  5: '#F0E68C', 6: 'rgba(33,150,243,0.7)', 7: '#2F2F2F',
  8: '#B87333', 9: '#FFD700', 10: '#00CED1', 11: '#FF9800',
  12: '#228B22', 13: '#B22222', 14: 'rgba(135,206,235,0.6)', 15: '#1a1a1a'
};

const HOTBAR_BLOCKS = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 13, 14];

function resize() {
  canvas.width = window.innerWidth * window.devicePixelRatio;
  canvas.height = window.innerHeight * window.devicePixelRatio;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  canvas.style.width = window.innerWidth + 'px';
  canvas.style.height = window.innerHeight + 'px';
}
window.addEventListener('resize', resize);
resize();

const authScreen = document.getElementById('authScreen');
const loadingScreen = document.getElementById('loadingScreen');
const emailIn = document.getElementById('email');
const passIn = document.getElementById('password');
const authError = document.getElementById('authError');

document.getElementById('loginBtn').onclick = () => {
  auth.signInWithEmailAndPassword(emailIn.value, passIn.value)
    .then(() => { authError.textContent = ''; })
    .catch(e => authError.textContent = e.message);
};

document.getElementById('registerBtn').onclick = () => {
  auth.createUserWithEmailAndPassword(emailIn.value, passIn.value)
    .then(() => { authError.textContent = ''; })
    .catch(e => authError.textContent = e.message);
};

auth.onAuthStateChanged(user => {
  if (user) {
    myUid = user.uid;
    myName = user.email.split('@')[0];
    document.getElementById('playerName').textContent = myName;
    authScreen.style.display = 'none';
    loadingScreen.style.display = 'flex';
    initSocket();
  }
});

function initSocket() {
  const wsUrl = window.location.origin;
  socket = io(wsUrl, { transports: ['websocket', 'polling'], reconnection: true });

  socket.on('connect', () => {
    console.log('Socket connected!');
  });

  socket.on('connect_error', (err) => {
    console.log('Socket error:', err.message);
  });

  socket.on('init', data => {
    console.log('Init received:', data);
    chunkSize = data.chunk_size;
    worldW = data.world_width;
    worldH = data.world_height;
    blocksInfo = data.blocks;
    socket.emit('auth', { uid: myUid, name: myName });
  });

  socket.on('auth_ok', data => {
    console.log('Auth OK! Starting game...');
    loadingScreen.style.display = 'none';
    myPlayer = { x: data.x, y: data.y };
    camera.x = data.x;
    camera.y = data.y;
    gameStarted = true;
    if (!window.gameLoopRunning) {
      window.gameLoopRunning = true;
      requestAnimationFrame(gameLoop);
    }
    initMusic();
  });

  socket.on('chunk', data => {
    worldData[data.cx + ',' + data.cy] = data.data;
    chunksReceived++;
  });

  socket.on('block_update', data => {
    const cx = Math.floor(data.x / chunkSize);
    const cy = Math.floor(data.y / chunkSize);
    const lx = data.x % chunkSize;
    const ly = data.y % chunkSize;
    const key = cx + ',' + cy;
    if (worldData[key]) {
      worldData[key][ly][lx] = data.block;
    }
  });

  socket.on('player_join', data => {
    players[data.sid] = {
      x: data.x, y: data.y, name: data.name,
      facing: data.facing || 1, anim: data.anim || 'idle',
      vx: 0, vy: 0
    };
    updatePlayerList();
  });

  socket.on('player_leave', data => {
    delete players[data.sid];
    updatePlayerList();
  });

  socket.on('players_state', state => {
    for (const sid in state) {
      if (sid === socket.id) {
        myPlayer = state[sid];
        camera.x += (state[sid].x - camera.x) * 0.15;
        camera.y += (state[sid].y - camera.y) * 0.15;
      } else if (players[sid]) {
        players[sid].x = state[sid].x;
        players[sid].y = state[sid].y;
        players[sid].vx = state[sid].vx;
        players[sid].vy = state[sid].vy;
        players[sid].facing = state[sid].facing;
        players[sid].anim = state[sid].anim;
      }
    }
  });
}

let moveDir = { x: 0, y: 0 };
let jumping = false;
let breaking = false;
let placing = false;

['btnLeft', 'btnRight', 'btnUp'].forEach(id => {
  const btn = document.getElementById(id);
  const parts = btn.dataset.dir.split(',');
  const dx = parseInt(parts[0]);
  const dy = parseInt(parts[1]);

  const start = (e) => { e.preventDefault(); moveDir.x += dx; if (dy) moveDir.y += dy; };
  const end = (e) => { e.preventDefault(); moveDir.x -= dx; if (dy) moveDir.y -= dy; };

  btn.addEventListener('touchstart', start, {passive: false});
  btn.addEventListener('touchend', end, {passive: false});
  btn.addEventListener('touchcancel', end, {passive: false});
  btn.addEventListener('mousedown', start);
  btn.addEventListener('mouseup', end);
  btn.addEventListener('mouseleave', end);
});

const btnJump = document.getElementById('btnJump');
btnJump.addEventListener('touchstart', (e) => { e.preventDefault(); jumping = true; }, {passive: false});
btnJump.addEventListener('touchend', (e) => { e.preventDefault(); jumping = false; }, {passive: false});
btnJump.addEventListener('mousedown', () => jumping = true);
btnJump.addEventListener('mouseup', () => jumping = false);

const btnBreak = document.getElementById('btnBreak');
const btnPlace = document.getElementById('btnPlace');

btnBreak.addEventListener('touchstart', (e) => { e.preventDefault(); breaking = true; }, {passive: false});
btnBreak.addEventListener('touchend', (e) => { e.preventDefault(); breaking = false; }, {passive: false});
btnBreak.addEventListener('mousedown', () => breaking = true);
btnBreak.addEventListener('mouseup', () => breaking = false);

btnPlace.addEventListener('touchstart', (e) => { e.preventDefault(); placing = true; }, {passive: false});
btnPlace.addEventListener('touchend', (e) => { e.preventDefault(); placing = false; }, {passive: false});
btnPlace.addEventListener('mousedown', () => placing = true);
btnPlace.addEventListener('mouseup', () => placing = false);

let lastTouchBlock = null;

document.getElementById('touchArea').addEventListener('touchstart', (e) => {
  const touch = e.touches[0];
  const block = screenToBlock(touch.clientX, touch.clientY);
  if (block) {
    lastTouchBlock = block;
    socket.emit('break_block', { x: block.x, y: block.y });
  }
}, {passive: false});

document.getElementById('touchArea').addEventListener('touchmove', (e) => {
  e.preventDefault();
}, {passive: false});

const keys = {};
window.addEventListener('keydown', e => {
  keys[e.code] = true;
  if (e.code === 'Space') jumping = true;
  if (e.code === 'KeyA' || e.code === 'ArrowLeft') moveDir.x = -1;
  if (e.code === 'KeyD' || e.code === 'ArrowRight') moveDir.x = 1;
  if (e.code === 'Digit1') selectedBlock = HOTBAR_BLOCKS[0];
  if (e.code === 'Digit2') selectedBlock = HOTBAR_BLOCKS[1];
  if (e.code === 'Digit3') selectedBlock = HOTBAR_BLOCKS[2];
  if (e.code === 'Digit4') selectedBlock = HOTBAR_BLOCKS[3];
  if (e.code === 'Digit5') selectedBlock = HOTBAR_BLOCKS[4];
  updateHotbar();
});
window.addEventListener('keyup', e => {
  keys[e.code] = false;
  if (e.code === 'Space') jumping = false;
  if (e.code === 'KeyA' || e.code === 'ArrowLeft') moveDir.x = 0;
  if (e.code === 'KeyD' || e.code === 'ArrowRight') moveDir.x = 0;
});

canvas.addEventListener('mousedown', e => {
  const block = screenToBlock(e.clientX, e.clientY);
  if (!block) return;
  if (e.button === 0) {
    socket.emit('break_block', { x: block.x, y: block.y });
  } else if (e.button === 2) {
    socket.emit('place_block', { x: block.x, y: block.y, block: selectedBlock });
  }
});
canvas.addEventListener('contextmenu', e => e.preventDefault());

setInterval(() => {
  if (socket && socket.connected) {
    socket.emit('move', { dx: moveDir.x, jump: jumping });
    if (breaking && lastTouchBlock) {
      socket.emit('break_block', { x: lastTouchBlock.x, y: lastTouchBlock.y });
    }
    if (placing && lastTouchBlock) {
      socket.emit('place_block', { x: lastTouchBlock.x, y: lastTouchBlock.y, block: selectedBlock });
    }
  }
}, 16);

function initHotbar() {
  const hb = document.getElementById('hotbar');
  hb.innerHTML = '';
  HOTBAR_BLOCKS.forEach((bid, i) => {
    const slot = document.createElement('div');
    slot.className = 'hotbar-slot' + (bid === selectedBlock ? ' active' : '');
    slot.innerHTML = '<div class="slot-num">' + (i+1) + '</div><div class="block-preview" style="background:' + (BLOCK_COLORS[bid] || '#555') + '"></div>';
    slot.onclick = () => { selectedBlock = bid; updateHotbar(); };
    hb.appendChild(slot);
  });
}
function updateHotbar() {
  const slots = document.querySelectorAll('.hotbar-slot');
  slots.forEach((s, i) => {
    s.classList.toggle('active', HOTBAR_BLOCKS[i] === selectedBlock);
  });
}
initHotbar();

document.getElementById('fullscreenBtn').onclick = () => {
  const el = document.documentElement;
  if (el.requestFullscreen) el.requestFullscreen();
  else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
  else if (el.msRequestFullscreen) el.msRequestFullscreen();
};

function updatePlayerList() {
  const pl = document.getElementById('plItems');
  pl.innerHTML = '';
  const count = Object.keys(players).length + (myPlayer ? 1 : 0);
  document.querySelector('#playerList .pl-title').textContent = 'Online (' + count + ')';
  if (myPlayer) {
    pl.innerHTML += '<div class="pl-item">&#9679; ' + myName + ' (you)</div>';
  }
  for (const sid in players) {
    pl.innerHTML += '<div class="pl-item">&#9679; ' + players[sid].name + '</div>';
  }
}

function updateCoords() {
  if (myPlayer) {
    document.getElementById('coords').textContent = Math.floor(myPlayer.x) + ', ' + Math.floor(myPlayer.y);
  }
}

const TILE_SIZE = 32;

function screenToBlock(sx, sy) {
  const px = camera.x - window.innerWidth / 2 / TILE_SIZE + sx / TILE_SIZE;
  const py = camera.y - window.innerHeight / 2 / TILE_SIZE + sy / TILE_SIZE;
  return { x: Math.floor(px), y: Math.floor(py) };
}

function blockToScreen(bx, by) {
  const sx = (bx - camera.x) * TILE_SIZE + window.innerWidth / 2;
  const sy = (by - camera.y) * TILE_SIZE + window.innerHeight / 2;
  return { x: sx, y: sy };
}

function drawBlock(bx, by, blockId) {
  const pos = blockToScreen(bx, by);
  const size = TILE_SIZE;
  if (pos.x < -size || pos.x > window.innerWidth + size ||
      pos.y < -size || pos.y > window.innerHeight + size) return;
  const color = BLOCK_COLORS[blockId];
  if (!color) return;
  ctx.fillStyle = color;
  ctx.fillRect(pos.x, pos.y, size, size);
  if (blockId !== 0 && blockId !== 6 && blockId !== 14) {
    ctx.fillStyle = 'rgba(0,0,0,0.15)';
    ctx.fillRect(pos.x, pos.y + size - 3, size, 3);
    ctx.fillRect(pos.x + size - 3, pos.y, 3, size);
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fillRect(pos.x, pos.y, size, 3);
    ctx.fillRect(pos.x, pos.y, 3, size);
  }
  if (blockId === 11) {
    const glow = ctx.createRadialGradient(pos.x + size/2, pos.y + size/2, 2, pos.x + size/2, pos.y + size/2, 80);
    glow.addColorStop(0, 'rgba(255,152,0,0.3)');
    glow.addColorStop(1, 'rgba(255,152,0,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(pos.x - 60, pos.y - 60, size + 120, size + 120);
  }
}

function drawPlayer(p, isMe) {
  const pos = blockToScreen(p.x, p.y);
  const w = TILE_SIZE * 0.8;
  const h = TILE_SIZE * 1.8;
  ctx.fillStyle = isMe ? '#4fc3f7' : '#ef5350';
  ctx.fillRect(pos.x, pos.y, w, h);
  ctx.fillStyle = '#ffcc80';
  ctx.fillRect(pos.x + 2, pos.y - 8, w - 4, 10);
  ctx.fillStyle = '#333';
  const eyeOff = p.facing > 0 ? 4 : 2;
  ctx.fillRect(pos.x + eyeOff, pos.y - 5, 3, 3);
  ctx.fillRect(pos.x + eyeOff + 6, pos.y - 5, 3, 3);
  ctx.fillStyle = isMe ? '#29b6f6' : '#e53935';
  const armSwing = Math.sin(Date.now() / 150) * 4;
  ctx.fillRect(pos.x - 4, pos.y + 6 + (p.anim === 'walk' ? armSwing : 0), 4, 10);
  ctx.fillRect(pos.x + w, pos.y + 6 - (p.anim === 'walk' ? armSwing : 0), 4, 10);
  ctx.fillStyle = '#5d4037';
  const legSwing = p.anim === 'walk' ? Math.sin(Date.now() / 100) * 5 : 0;
  ctx.fillRect(pos.x + 2, pos.y + h - 2, 8, 6 + legSwing);
  ctx.fillRect(pos.x + w - 10, pos.y + h - 2, 8, 6 - legSwing);
  if (!isMe) {
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.font = 'bold 11px sans-serif';
    const tw = ctx.measureText(p.name).width;
    ctx.fillRect(pos.x + w/2 - tw/2 - 4, pos.y - 22, tw + 8, 16);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.fillText(p.name, pos.x + w/2, pos.y - 10);
  }
}

function drawSky() {
  const grad = ctx.createLinearGradient(0, 0, 0, window.innerHeight);
  grad.addColorStop(0, '#0d1b2a');
  grad.addColorStop(0.4, '#1b2838');
  grad.addColorStop(1, '#2d4a3e');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
  ctx.fillStyle = '#fff';
  for (let i = 0; i < 80; i++) {
    const sx = (i * 137.5 + camera.x * 0.1) % window.innerWidth;
    const sy = (i * 73.3) % (window.innerHeight * 0.5);
    const alpha = 0.3 + Math.sin(Date.now() / 1000 + i) * 0.3;
    ctx.globalAlpha = alpha;
    ctx.fillRect(sx, sy, 1.5, 1.5);
  }
  ctx.globalAlpha = 1;
  const moonX = window.innerWidth * 0.8;
  const moonY = window.innerHeight * 0.15;
  ctx.fillStyle = '#fffde7';
  ctx.beginPath();
  ctx.arc(moonX, moonY, 25, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#0d1b2a';
  ctx.beginPath();
  ctx.arc(moonX - 8, moonY - 5, 22, 0, Math.PI * 2);
  ctx.fill();
}

function drawGrid() {
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth = 1;
  const startX = Math.floor(camera.x - window.innerWidth / 2 / TILE_SIZE);
  const endX = Math.floor(camera.x + window.innerWidth / 2 / TILE_SIZE) + 1;
  const startY = Math.floor(camera.y - window.innerHeight / 2 / TILE_SIZE);
  const endY = Math.floor(camera.y + window.innerHeight / 2 / TILE_SIZE) + 1;
  for (let bx = startX; bx <= endX; bx++) {
    const pos = blockToScreen(bx, 0);
    ctx.beginPath();
    ctx.moveTo(pos.x, 0);
    ctx.lineTo(pos.x, window.innerHeight);
    ctx.stroke();
  }
  for (let by = startY; by <= endY; by++) {
    const pos = blockToScreen(0, by);
    ctx.beginPath();
    ctx.moveTo(0, pos.y);
    ctx.lineTo(window.innerWidth, pos.y);
    ctx.stroke();
  }
}

function drawWorld() {
  const startX = Math.floor(camera.x - window.innerWidth / 2 / TILE_SIZE) - 1;
  const endX = Math.floor(camera.x + window.innerWidth / 2 / TILE_SIZE) + 2;
  const startY = Math.floor(camera.y - window.innerHeight / 2 / TILE_SIZE) - 1;
  const endY = Math.floor(camera.y + window.innerHeight / 2 / TILE_SIZE) + 2;
  for (let bx = startX; bx <= endX; bx++) {
    for (let by = startY; by <= endY; by++) {
      if (bx < 0 || bx >= worldW || by < 0 || by >= worldH) continue;
      const cx = Math.floor(bx / chunkSize);
      const cy = Math.floor(by / chunkSize);
      const lx = bx % chunkSize;
      const ly = by % chunkSize;
      const chunk = worldData[cx + ',' + cy];
      if (chunk) {
        drawBlock(bx, by, chunk[ly][lx]);
      }
    }
  }
}

function gameLoop() {
  ctx.clearRect(0, 0, canvas.width / window.devicePixelRatio, canvas.height / window.devicePixelRatio);
  drawSky();
  drawGrid();
  drawWorld();
  for (const sid in players) {
    drawPlayer(players[sid], false);
  }
  if (myPlayer) {
    drawPlayer(myPlayer, true);
  }
  const cx = window.innerWidth / 2;
  const cy = window.innerHeight / 2;
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(cx - 8, cy); ctx.lineTo(cx + 8, cy);
  ctx.moveTo(cx, cy - 8); ctx.lineTo(cx, cy + 8);
  ctx.stroke();
  updateCoords();
  requestChunks();
  requestAnimationFrame(gameLoop);
}

let lastChunkRequest = 0;
function requestChunks() {
  const now = Date.now();
  if (now - lastChunkRequest < 500) return;
  lastChunkRequest = now;
  if (!socket || !myPlayer) return;
  const cx = Math.floor(myPlayer.x / chunkSize);
  const cy = Math.floor(myPlayer.y / chunkSize);
  socket.emit('request_chunks', { cx: cx, cy: cy });
}

function initMusic() {
  document.getElementById('musicToggle').onclick = toggleMusic;
}

function toggleMusic() {
  if (!musicPlaying) {
    startMusic();
    musicPlaying = true;
    document.getElementById('musicToggle').textContent = 'Mute';
  } else {
    stopMusic();
    musicPlaying = false;
    document.getElementById('musicToggle').textContent = 'Music';
  }
}

function startMusic() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  musicGain = audioCtx.createGain();
  musicGain.gain.value = 0.15;
  musicGain.connect(audioCtx.destination);
  playAmbientLoop();
}

function stopMusic() {
  if (musicGain) {
    musicGain.gain.setValueAtTime(musicGain.gain.value, audioCtx.currentTime);
    musicGain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 1);
    setTimeout(() => { musicGain = null; }, 1000);
  }
}

function playAmbientLoop() {
  if (!musicGain) return;
  const scale = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25, 783.99, 880.00];

  function playNote(freq, dur, delay) {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, audioCtx.currentTime + delay);
    gain.gain.linearRampToValueAtTime(0.08, audioCtx.currentTime + delay + 0.5);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + delay + dur);
    osc.connect(gain);
    gain.connect(musicGain);
    osc.start(audioCtx.currentTime + delay);
    osc.stop(audioCtx.currentTime + delay + dur);
  }

  function playArp() {
    if (!musicGain) return;
    const base = scale[Math.floor(Math.random() * 5)];
    const pattern = [0, 2, 4, 2, 0, -2, 0, 2];
    pattern.forEach((off, i) => {
      const idx = Math.max(0, Math.min(scale.length - 1, scale.indexOf(base) + off));
      playNote(scale[idx], 2, i * 0.8);
    });
    setTimeout(playArp, 7000);
  }

  function playPad() {
    if (!musicGain) return;
    for (let i = 0; i < 3; i++) {
      const freq = scale[Math.floor(Math.random() * scale.length)];
      playNote(freq, 6, i * 0.3);
    }
    setTimeout(playPad, 8000);
  }

  playArp();
  playPad();
}

function initBlockMenu() {
  const menu = document.getElementById('blockMenu');
  for (const bid in BLOCK_COLORS) {
    if (bid === '0') continue;
    const opt = document.createElement('div');
    opt.className = 'block-option';
    const bname = (blocksInfo[bid] && blocksInfo[bid].name) ? blocksInfo[bid].name : bid;
    opt.innerHTML = '<div class="bprev" style="background:' + BLOCK_COLORS[bid] + '"></div><div>' + bname + '</div>';
    opt.onclick = () => { selectedBlock = parseInt(bid); updateHotbar(); menu.style.display = 'none'; };
    menu.appendChild(opt);
  }
}

let placeLongPress = null;
btnPlace.addEventListener('touchstart', (e) => {
  placeLongPress = setTimeout(() => {
    const menu = document.getElementById('blockMenu');
    menu.style.display = menu.style.display === 'grid' ? 'none' : 'grid';
  }, 600);
}, {passive: false});
btnPlace.addEventListener('touchend', () => { clearTimeout(placeLongPress); });

initBlockMenu();

document.addEventListener('gesturestart', e => e.preventDefault());
document.addEventListener('gesturechange', e => e.preventDefault());
document.addEventListener('gestureend', e => e.preventDefault());
</script>
</body>
</html>"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
