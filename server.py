import math
import os
import random
import threading
import time
from collections import deque

from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "terraria-online-secret")
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_interval=15,
    ping_timeout=45,
    logger=False,
    engineio_logger=False,
)

TILE = 32
WORLD_W = 300
WORLD_H = 100
TICK = 1.0 / 30.0
MAX_PLAYERS = 100

BLOCKS = {
    1: {"name": "Трава", "color": "#55b957", "solid": True},
    2: {"name": "Земля", "color": "#9a633d", "solid": True},
    3: {"name": "Камень", "color": "#777b86", "solid": True},
    4: {"name": "Дерево", "color": "#9c6338", "solid": True},
    5: {"name": "Листва", "color": "#3f934b", "solid": False},
}

lock = threading.RLock()
players = {}
inputs = {}
world = {}
entities = {}
chat_messages = deque(maxlen=40)
next_entity_id = 1
loop_started = False
loop_guard = threading.Lock()
world_clock = 0.22


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def generate_world():
    rng = random.Random(20260804)
    heights = []
    height = 43
    for x in range(WORLD_W):
        if x % 5 == 0:
            height += rng.choice([-1, 0, 0, 1])
        height = clamp(height, 29, 55)
        heights.append(height)

    result = {}
    for x, surface in enumerate(heights):
        result[(x, surface)] = 1
        for y in range(surface + 1, min(WORLD_H, surface + 5)):
            result[(x, y)] = 2
        for y in range(surface + 5, WORLD_H):
            result[(x, y)] = 3

    # Безопасная поляна появления.
    for x in range(91, 110):
        surface = heights[x]
        for y in range(surface - 10, surface):
            result.pop((x, y), None)

    for x in range(8, WORLD_W - 8, 13):
        if 86 <= x <= 115:
            continue
        surface = heights[x]
        trunk_h = rng.randint(3, 5)
        for dy in range(1, trunk_h + 1):
            result[(x, surface - dy)] = 4
        top = surface - trunk_h
        for dx in range(-2, 3):
            for dy in range(-2, 2):
                if abs(dx) + abs(dy) <= 3:
                    result[(x + dx, top + dy)] = 5
    return result


world = generate_world()


def surface_y(tx):
    tx = int(clamp(tx, 0, WORLD_W - 1))
    for ty in range(WORLD_H):
        if is_solid(tx, ty):
            return ty
    return WORLD_H - 1


def spawn_point(tx=100):
    sy = surface_y(tx)
    return tx * TILE + 4, sy * TILE - 46


def is_solid(tx, ty):
    if tx < 0 or tx >= WORLD_W or ty >= WORLD_H:
        return True
    if ty < 0:
        return False
    block = world.get((tx, ty), 0)
    return bool(BLOCKS.get(block, {}).get("solid"))


def collides(x, y, w, h):
    left = math.floor(x / TILE)
    right = math.floor((x + w - 0.01) / TILE)
    top = math.floor(y / TILE)
    bottom = math.floor((y + h - 0.01) / TILE)
    for tx in range(left, right + 1):
        for ty in range(top, bottom + 1):
            if is_solid(tx, ty):
                return True
    return False


def tile_overlaps_actor(tx, ty):
    ax, ay, aw, ah = tx * TILE, ty * TILE, TILE, TILE
    actors = list(players.values()) + list(entities.values())
    for p in actors:
        if ax < p["x"] + p["w"] and ax + aw > p["x"] and ay < p["y"] + p["h"] and ay + ah > p["y"]:
            return True
    return False


def move_body(body, dt):
    # Подшаги не дают пролетать сквозь блоки на большой скорости.
    dx = body["vx"] * dt
    dy = body["vy"] * dt
    steps = max(1, int(math.ceil(max(abs(dx), abs(dy)) / 7.0)))
    sx, sy = dx / steps, dy / steps
    body["grounded"] = False
    for _ in range(steps):
        nx = body["x"] + sx
        if not collides(nx, body["y"], body["w"], body["h"]):
            body["x"] = nx
        else:
            body["vx"] = 0
            sx = 0
        ny = body["y"] + sy
        if not collides(body["x"], ny, body["w"], body["h"]):
            body["y"] = ny
        else:
            if sy > 0:
                body["grounded"] = True
            body["vy"] = 0
            sy = 0
    body["x"] = clamp(body["x"], 0, WORLD_W * TILE - body["w"])
    if body["y"] > WORLD_H * TILE:
        body["dead"] = True


def player_public(p):
    return {
        "id": p["id"], "name": p["name"], "x": round(p["x"], 1), "y": round(p["y"], 1),
        "vx": round(p["vx"], 1), "vy": round(p["vy"], 1), "w": p["w"], "h": p["h"],
        "color": p["color"], "hp": p["hp"], "max_hp": p["max_hp"], "facing": p["facing"],
    }


def entity_public(e):
    return {
        "id": e["id"], "kind": e["kind"], "x": round(e["x"], 1), "y": round(e["y"], 1),
        "vx": round(e["vx"], 1), "vy": round(e["vy"], 1), "w": e["w"], "h": e["h"],
        "hp": e["hp"], "max_hp": e["max_hp"], "facing": e["facing"],
        "dash": round(max(0, e.get("dash_flash", 0)), 2),
    }


def make_entity(kind, tx):
    global next_entity_id
    specs = {
        "bunny": (22, 19, 35, 25, 0),
        "deer": (30, 39, 70, 50, 0),
        "zombie": (25, 42, 100, 80, 10),
        "vampire": (27, 44, 320, 175, 18),
    }
    w, h, hp, speed, damage = specs[kind]
    sy = surface_y(tx)
    e = {
        "id": next_entity_id, "kind": kind, "x": tx * TILE + 2, "y": sy * TILE - h,
        "vx": 0.0, "vy": 0.0, "w": w, "h": h, "hp": hp, "max_hp": hp,
        "speed": speed, "damage": damage, "grounded": False, "dead": False,
        "facing": random.choice([-1, 1]), "think": random.uniform(0.5, 2.0),
        "attack_cd": 0.0, "dash_cd": 3.0, "dash_flash": 0.0,
    }
    entities[next_entity_id] = e
    next_entity_id += 1


def seed_entities():
    for kind, count in (("bunny", 16), ("deer", 8), ("zombie", 12), ("vampire", 2)):
        for _ in range(count):
            tx = random.choice(list(range(12, 82)) + list(range(120, WORLD_W - 12)))
            make_entity(kind, tx)


seed_entities()


def respawn_player(p):
    p["x"], p["y"] = spawn_point()
    p["vx"] = p["vy"] = 0
    p["hp"] = p["max_hp"]
    p["invuln"] = 2.0


def damage_player(p, amount, source_x):
    if p["invuln"] > 0:
        return
    p["hp"] -= amount
    p["invuln"] = 0.7
    p["vx"] = 220 if p["x"] > source_x else -220
    p["vy"] = -230
    if p["hp"] <= 0:
        respawn_player(p)


def update_player(p, control, dt):
    p["invuln"] = max(0, p["invuln"] - dt)
    p["coyote"] = 0.11 if p["grounded"] else max(0, p["coyote"] - dt)
    direction = int(clamp(control.get("x", 0), -1, 1))
    if direction:
        p["facing"] = direction
    target = direction * 245.0
    accel = 1900.0 if p["grounded"] else 1050.0
    if direction == 0:
        accel = 2400.0 if p["grounded"] else 500.0
    change = clamp(target - p["vx"], -accel * dt, accel * dt)
    p["vx"] += change

    if control.get("jump_request"):
        p["jump_buffer"] = 0.13
    control["jump_request"] = False
    p["jump_buffer"] = max(0, p["jump_buffer"] - dt)
    if p["jump_buffer"] > 0 and p["coyote"] > 0:
        p["vy"] = -455.0
        p["grounded"] = False
        p["coyote"] = 0
        p["jump_buffer"] = 0
    # Переменная высота прыжка, как в Terraria.
    if not control.get("jump_held") and p["vy"] < -170:
        p["vy"] += 1350 * dt
    p["vy"] = min(900, p["vy"] + 1150 * dt)
    move_body(p, dt)
    if p.get("dead"):
        p["dead"] = False
        respawn_player(p)


def nearest_player(e, radius=520):
    best, best_d = None, radius * radius
    for p in players.values():
        dx = (p["x"] + p["w"] / 2) - (e["x"] + e["w"] / 2)
        dy = (p["y"] + p["h"] / 2) - (e["y"] + e["h"] / 2)
        d = dx * dx + dy * dy
        if d < best_d:
            best, best_d = p, d
    return best


def update_entity(e, dt):
    e["think"] -= dt
    e["attack_cd"] = max(0, e["attack_cd"] - dt)
    e["dash_cd"] = max(0, e["dash_cd"] - dt)
    e["dash_flash"] = max(0, e["dash_flash"] - dt)
    target = nearest_player(e, 700 if e["kind"] == "vampire" else 480)

    if e["kind"] in ("bunny", "deer"):
        if e["think"] <= 0:
            e["think"] = random.uniform(1.2, 3.8)
            e["facing"] = random.choice([-1, 0, 1])
        if target and abs(target["x"] - e["x"]) < 150:
            e["facing"] = -1 if target["x"] > e["x"] else 1
        target_vx = e["facing"] * e["speed"]
    else:
        if target:
            e["facing"] = 1 if target["x"] > e["x"] else -1
            target_vx = e["facing"] * e["speed"]
            # Вампир делает настоящий рывок ровно на 5 блоков раз в 3 секунды.
            if e["kind"] == "vampire" and e["dash_cd"] <= 0 and abs(target["x"] - e["x"]) < 430:
                distance = 5 * TILE * e["facing"]
                steps = 20
                for _ in range(steps):
                    nx = e["x"] + distance / steps
                    if collides(nx, e["y"], e["w"], e["h"]):
                        break
                    e["x"] = nx
                e["dash_cd"] = 3.0
                e["dash_flash"] = 0.35
        else:
            target_vx = 0

    e["vx"] += clamp(target_vx - e["vx"], -700 * dt, 700 * dt)
    # Автопрыжок мобов через препятствия.
    ahead = e["x"] + (e["w"] + 5 if e["facing"] > 0 else -5)
    if e["grounded"] and collides(ahead, e["y"] + 4, 3, e["h"] - 4):
        e["vy"] = -360
    if e["kind"] == "bunny" and e["grounded"] and random.random() < 0.018:
        e["vy"] = -300
    e["vy"] = min(850, e["vy"] + 1100 * dt)
    move_body(e, dt)

    if target and e["damage"] and e["attack_cd"] <= 0:
        if abs((e["x"] + e["w"] / 2) - (target["x"] + target["w"] / 2)) < 34 and abs(e["y"] - target["y"]) < 46:
            damage_player(target, e["damage"], e["x"])
            e["attack_cd"] = 0.85


def attack(sid):
    p = players.get(sid)
    if not p or p["attack_cd"] > 0:
        return
    p["attack_cd"] = 0.35
    cx = p["x"] + p["w"] / 2 + p["facing"] * 35
    cy = p["y"] + p["h"] / 2
    for e in list(entities.values()):
        ex, ey = e["x"] + e["w"] / 2, e["y"] + e["h"] / 2
        if abs(ex - cx) < 50 and abs(ey - cy) < 45:
            e["hp"] -= 28
            e["vx"] = p["facing"] * 250
            e["vy"] = -180


def game_loop():
    global world_clock
    spawn_timer = 0.0
    while True:
        started = time.perf_counter()
        with lock:
            world_clock = (world_clock + TICK / 180.0) % 1.0
            for sid, p in list(players.items()):
                p["attack_cd"] = max(0, p["attack_cd"] - TICK)
                update_player(p, inputs.setdefault(sid, {"x": 0, "jump_request": False, "jump_held": False}), TICK)
            for eid, e in list(entities.items()):
                update_entity(e, TICK)
                if e["hp"] <= 0 or e.get("dead"):
                    entities.pop(eid, None)
            spawn_timer += TICK
            if spawn_timer > 8 and len(entities) < 38:
                spawn_timer = 0
                make_entity(random.choice(["bunny", "deer", "zombie"]), random.choice(list(range(15, 82)) + list(range(120, 285))))
            state = {
                "players": [player_public(p) for p in players.values()],
                "entities": [entity_public(e) for e in entities.values()],
                "time": round(world_clock, 4),
            }
        socketio.emit("state", state)
        elapsed = time.perf_counter() - started
        socketio.sleep(max(0.001, TICK - elapsed))


def ensure_loop():
    global loop_started
    with loop_guard:
        if not loop_started:
            loop_started = True
            socketio.start_background_task(game_loop)


@app.route("/")
def index():
    ensure_loop()
    return render_template_string(PAGE)


@app.route("/health")
def health():
    return {"ok": True, "players": len(players), "entities": len(entities)}


@socketio.on("connect")
def on_connect():
    ensure_loop()
    sid = request.sid
    with lock:
        if len(players) >= MAX_PLAYERS:
            return False
        x, y = spawn_point()
        p = {
            "id": sid, "name": f"Игрок-{random.randint(100, 999)}", "x": x, "y": y,
            "vx": 0.0, "vy": 0.0, "w": 24, "h": 42, "grounded": False, "dead": False,
            "color": random.choice(["#ff6b6b", "#ffd166", "#4dd4ac", "#6ea8fe", "#d28cff"]),
            "hp": 100, "max_hp": 100, "invuln": 1.0, "attack_cd": 0.0,
            "facing": 1, "coyote": 0.0, "jump_buffer": 0.0,
        }
        players[sid] = p
        inputs[sid] = {"x": 0, "jump_request": False, "jump_held": False}
        initial = {
            "w": WORLD_W, "h": WORLD_H, "tile": TILE,
            "blocks": [{"x": x, "y": y, "type": b} for (x, y), b in world.items()],
            "players": [player_public(v) for v in players.values()],
            "entities": [entity_public(e) for e in entities.values()],
            "you": player_public(p), "chat": list(chat_messages), "time": world_clock,
        }
    emit("init", initial)
    socketio.emit("notice", {"text": f"{p['name']} появился в мире"})


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    with lock:
        p = players.pop(sid, None)
        inputs.pop(sid, None)
    if p:
        socketio.emit("notice", {"text": f"{p['name']} вышел"})


@socketio.on("set_name")
def set_name(data):
    name = str((data or {}).get("name", "")).strip()[:18]
    if not name:
        return
    with lock:
        if request.sid in players:
            players[request.sid]["name"] = name
            emit("you", player_public(players[request.sid]))


@socketio.on("input")
def receive_input(data):
    data = data or {}
    with lock:
        c = inputs.get(request.sid)
        if c is None:
            return
        try:
            c["x"] = int(clamp(int(data.get("x", 0)), -1, 1))
        except (TypeError, ValueError):
            c["x"] = 0
        held = bool(data.get("jump", False))
        if held and not c["jump_held"]:
            c["jump_request"] = True
        c["jump_held"] = held


@socketio.on("attack")
def receive_attack():
    with lock:
        attack(request.sid)


@socketio.on("edit_block")
def edit_block(data):
    try:
        tx, ty = int(data.get("x")), int(data.get("y"))
        action = str(data.get("action", "place"))
        block_type = int(data.get("type", 2))
    except (TypeError, ValueError, AttributeError):
        return
    with lock:
        p = players.get(request.sid)
        if not p or not (0 <= tx < WORLD_W and 0 <= ty < WORLD_H):
            return
        px, py = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
        if (px - (tx + .5) * TILE) ** 2 + (py - (ty + .5) * TILE) ** 2 > (7 * TILE) ** 2:
            return
        if action == "break" and (tx, ty) in world:
            world.pop((tx, ty), None)
            socketio.emit("world_patch", {"x": tx, "y": ty, "type": 0})
        elif action == "place" and block_type in BLOCKS and (tx, ty) not in world and not tile_overlaps_actor(tx, ty):
            world[(tx, ty)] = block_type
            socketio.emit("world_patch", {"x": tx, "y": ty, "type": block_type})


@socketio.on("chat")
def chat(data):
    text = str((data or {}).get("text", "")).strip()[:160]
    with lock:
        p = players.get(request.sid)
        if not p or not text:
            return
        msg = {"name": p["name"], "text": text, "color": p["color"]}
        chat_messages.append(msg)
    socketio.emit("chat", msg)


PAGE = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-capable" content="yes">
<title>Живой мир Online</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#101522;color:#fff;font-family:system-ui,Arial;touch-action:none}body{user-select:none;-webkit-user-select:none}#game{position:fixed;inset:0;width:100vw;height:100vh;display:block;image-rendering:pixelated;touch-action:none}.top{position:fixed;z-index:5;top:max(8px,env(safe-area-inset-top));left:10px;right:10px;display:flex;justify-content:space-between;pointer-events:none}.panel{background:#101827dc;border:1px solid #ffffff2d;border-radius:13px;padding:8px 10px;backdrop-filter:blur(8px);font-size:12px;pointer-events:auto;box-shadow:0 5px 20px #0004}.title{font-weight:950;color:#ffd166;letter-spacing:.7px}.name{display:flex;gap:5px;margin-top:5px}.name input{width:112px;background:#202b40;color:#fff;border:1px solid #ffffff25;border-radius:7px;padding:5px;outline:none}.btn,.send{border:0;border-radius:7px;background:#ffd166;color:#171b25;font-weight:900;padding:5px 8px}.stats{text-align:right}.hpbar{width:150px;height:13px;background:#2a1720;border:1px solid #fff4;border-radius:8px;overflow:hidden;margin-top:4px}.hp{height:100%;background:linear-gradient(90deg,#e33,#ff7373);width:100%;transition:width .15s}.controls{position:fixed;z-index:6;left:18px;right:18px;bottom:max(16px,env(safe-area-inset-bottom));display:flex;justify-content:space-between;align-items:end;pointer-events:none}.pad,.actions{display:flex;gap:10px;pointer-events:auto;align-items:end}.control{width:66px;height:66px;border:1px solid #ffffff44;border-radius:50%;background:#101827df;color:#fff;font-size:27px;font-weight:900;box-shadow:0 5px 18px #0006;touch-action:none}.control.on{background:#48658f;transform:scale(.94)}.small{width:49px;height:49px;font-size:19px}.attack{background:#6d2939e8}.selected{border-color:#ffd166;color:#ffd166}.chat{position:fixed;z-index:7;left:10px;bottom:92px;width:min(370px,calc(100vw - 20px));pointer-events:none}.log{max-height:105px;overflow:hidden;text-shadow:0 1px 3px #000}.line{font-size:12px;margin:2px 0}.chatform{display:flex;gap:5px;margin-top:5px;pointer-events:auto}.chatinput{flex:1;min-width:0;background:#101827dc;color:#fff;border:1px solid #ffffff25;border-radius:8px;padding:7px;outline:none}.music{margin-top:5px;width:100%}.rotate{display:none;position:fixed;z-index:20;inset:0;background:#10131b;align-items:center;justify-content:center;text-align:center;padding:30px;font-size:20px;font-weight:900}@media(orientation:portrait) and (max-width:700px){.rotate{display:flex}.top,.controls,.chat{display:none}}@media(max-height:430px){.stats .hint{display:none}.control{width:55px;height:55px}.small{width:44px;height:44px}.chat{bottom:72px}}
</style></head><body>
<div class="rotate">Поверни телефон горизонтально ↔</div><canvas id="game"></canvas>
<div class="top"><div class="panel"><div class="title">ЖИВОЙ МИР ONLINE</div><div id="online">Подключение…</div><div class="name"><input id="name" maxlength="18" placeholder="Имя"><button class="btn" onclick="setName()">OK</button></div><button id="music" class="btn music">♫ Включить музыку</button></div><div class="panel stats"><b id="clock">День</b><div class="hpbar"><div id="hp" class="hp"></div></div><div id="hptext">100 / 100 HP</div><div class="hint">A/D или ◀▶ · Space прыжок · F атака</div></div></div>
<div class="controls"><div class="pad"><button id="left" class="control">◀</button><button id="right" class="control">▶</button></div><div class="actions"><button id="mode" class="control small selected">＋</button><button id="hit" class="control attack">⚔</button><button id="jump" class="control">▲</button></div></div>
<div class="chat"><div id="log" class="log"></div><form class="chatform" onsubmit="sendChat(event)"><input id="chatinput" class="chatinput" maxlength="160" placeholder="Чат мира"><button class="send">➤</button></form></div>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script><script>
const socket=io({transports:['websocket','polling'],upgrade:true});
const canvas=document.getElementById('game'),ctx=canvas.getContext('2d');
let worldW=300,worldH=100,T=32,blocks=new Map(),players=new Map(),mobs=new Map(),me=null,camera={x:0,y:0},worldTime=.2;
let leftHeld=false,rightHeld=false,jumpHeld=false,editMode='place',selectedBlock=2,lastTouch=0;
const colors={1:'#55b957',2:'#9a633d',3:'#777b86',4:'#9c6338',5:'#3f934b'};
function resize(){const d=Math.min(devicePixelRatio||1,2);canvas.width=innerWidth*d;canvas.height=innerHeight*d;canvas.style.width=innerWidth+'px';canvas.style.height=innerHeight+'px';ctx.setTransform(d,0,0,d,0,0)}addEventListener('resize',resize);resize();
const key=(x,y)=>x+','+y;const esc=s=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function addLine(i){const e=document.createElement('div');e.className='line';e.innerHTML='<b style="color:'+esc(i.color||'#fff')+'">'+esc(i.name||'Мир')+':</b> '+esc(i.text||'');const l=document.getElementById('log');l.appendChild(e);while(l.children.length>7)l.firstChild.remove();setTimeout(()=>e.remove(),13000)}
function setName(){let n=document.getElementById('name').value.trim();if(n)socket.emit('set_name',{name:n})}function sendChat(e){e.preventDefault();let i=document.getElementById('chatinput'),t=i.value.trim();if(t)socket.emit('chat',{text:t});i.value=''}
function direction(){return (rightHeld?1:0)-(leftHeld?1:0)}function sendInput(){socket.emit('input',{x:direction(),jump:jumpHeld})}
function bindHold(id,side){const b=document.getElementById(id);const down=e=>{e.preventDefault();b.setPointerCapture?.(e.pointerId);b.classList.add('on');if(side<0)leftHeld=true;else rightHeld=true;sendInput()};const up=e=>{e.preventDefault();b.classList.remove('on');if(side<0)leftHeld=false;else rightHeld=false;sendInput()};b.addEventListener('pointerdown',down);b.addEventListener('pointerup',up);b.addEventListener('pointercancel',up)}bindHold('left',-1);bindHold('right',1);
const jump=document.getElementById('jump');jump.onpointerdown=e=>{e.preventDefault();jump.setPointerCapture?.(e.pointerId);jump.classList.add('on');jumpHeld=true;sendInput()};function jumpUp(e){e.preventDefault();jump.classList.remove('on');jumpHeld=false;sendInput()}jump.onpointerup=jumpUp;jump.onpointercancel=jumpUp;
const hit=document.getElementById('hit');hit.onpointerdown=e=>{e.preventDefault();hit.classList.add('on');socket.emit('attack')};hit.onpointerup=()=>hit.classList.remove('on');hit.onpointercancel=()=>hit.classList.remove('on');
document.getElementById('mode').onpointerdown=e=>{e.preventDefault();editMode=editMode==='place'?'break':'place';e.currentTarget.textContent=editMode==='place'?'＋':'−';e.currentTarget.classList.toggle('selected',editMode==='place')};
addEventListener('keydown',e=>{if(document.activeElement.tagName==='INPUT')return;if(e.code==='KeyA'||e.code==='ArrowLeft')leftHeld=true;if(e.code==='KeyD'||e.code==='ArrowRight')rightHeld=true;if(e.code==='Space'||e.code==='KeyW'||e.code==='ArrowUp'){e.preventDefault();jumpHeld=true}if(e.code==='KeyF')socket.emit('attack');sendInput()});addEventListener('keyup',e=>{if(e.code==='KeyA'||e.code==='ArrowLeft')leftHeld=false;if(e.code==='KeyD'||e.code==='ArrowRight')rightHeld=false;if(e.code==='Space'||e.code==='KeyW'||e.code==='ArrowUp')jumpHeld=false;sendInput()});addEventListener('blur',()=>{leftHeld=rightHeld=jumpHeld=false;sendInput()});setInterval(sendInput,50);
canvas.onpointerdown=e=>{if(e.pointerType==='mouse'&&e.button===0)return;if(Date.now()-lastTouch<100)return;lastTouch=Date.now();e.preventDefault();let tx=Math.floor((e.clientX+camera.x)/T),ty=Math.floor((e.clientY+camera.y)/T);socket.emit('edit_block',{x:tx,y:ty,action:editMode,type:selectedBlock})};canvas.oncontextmenu=e=>e.preventDefault();
socket.on('connect',()=>online.textContent='Онлайн: подключено');socket.on('disconnect',()=>online.textContent='Переподключение…');socket.on('init',d=>{worldW=d.w;worldH=d.h;T=d.tile;blocks.clear();d.blocks.forEach(b=>blocks.set(key(b.x,b.y),b.type));players.clear();d.players.forEach(p=>players.set(p.id,p));mobs.clear();d.entities.forEach(e=>mobs.set(e.id,e));me=d.you;players.set(me.id,me);worldTime=d.time;name.value=me.name;d.chat.forEach(addLine)});socket.on('you',p=>{me=p;players.set(p.id,p);name.value=p.name});socket.on('state',d=>{let seen=new Set;d.players.forEach(p=>{seen.add(p.id);players.set(p.id,p);if(me&&p.id===me.id)me=p});for(const id of players.keys())if(!seen.has(id))players.delete(id);mobs.clear();d.entities.forEach(e=>mobs.set(e.id,e));worldTime=d.time});socket.on('world_patch',b=>b.type?blocks.set(key(b.x,b.y),b.type):blocks.delete(key(b.x,b.y)));socket.on('chat',addLine);socket.on('notice',i=>addLine({name:'Мир',text:i.text,color:'#ffd166'}));
// Оригинальная процедурная музыка: никаких чужих аудиофайлов и проблем с copyright.
let audio=null,musicTimer=null,noteIndex=0;const melody=[0,4,7,11,7,4,2,7,9,5,2,0,4,9,7,2];function tone(freq,when,dur,vol,type='sine'){let o=audio.createOscillator(),g=audio.createGain();o.type=type;o.frequency.value=freq;g.gain.setValueAtTime(0,when);g.gain.linearRampToValueAtTime(vol,when+.12);g.gain.exponentialRampToValueAtTime(.0001,when+dur);o.connect(g).connect(audio.destination);o.start(when);o.stop(when+dur+.05)}function scheduleMusic(){if(!audio)return;let now=audio.currentTime+.05;for(let i=0;i<4;i++){let n=melody[(noteIndex+i)%melody.length],f=220*Math.pow(2,n/12);tone(f,now+i*.55,.95,.025,'sine');tone(f/2,now+i*.55,1.2,.012,'triangle')}noteIndex=(noteIndex+4)%melody.length}music.onclick=async()=>{if(audio){audio.close();audio=null;clearInterval(musicTimer);music.textContent='♫ Включить музыку';return}audio=new (window.AudioContext||window.webkitAudioContext)();await audio.resume();scheduleMusic();musicTimer=setInterval(scheduleMusic,2100);music.textContent='■ Выключить музыку'};
function rect(x,y,w,h,c){ctx.fillStyle=c;ctx.fillRect(Math.round(x),Math.round(y),w,h)}function label(text,x,y,color='#fff'){ctx.font='12px system-ui';ctx.textAlign='center';ctx.lineWidth=3;ctx.strokeStyle='#111';ctx.strokeText(text,x,y);ctx.fillStyle=color;ctx.fillText(text,x,y)}
function drawMob(e){let x=e.x-camera.x,y=e.y-camera.y,f=e.facing||1;if(e.dash>0){ctx.globalAlpha=.22;rect(x-f*35,y,e.w,e.h,'#c972ff');ctx.globalAlpha=1}if(e.kind==='bunny'){rect(x,y+7,e.w,e.h-7,'#eee');rect(x+(f>0?13:3),y,5,12,'#eee');rect(x+(f>0?18:8),y+11,3,3,'#222')}else if(e.kind==='deer'){rect(x+4,y+10,e.w-8,e.h-13,'#b77a45');rect(x+(f>0?20:0),y,e.w-9,18,'#c58a51');rect(x+(f>0?24:4),y+5,3,3,'#111');rect(x+6,y+e.h-8,4,12,'#704426');rect(x+21,y+e.h-8,4,12,'#704426')}else if(e.kind==='zombie'){rect(x,y,e.w,e.h,'#527e54');rect(x+4,y+3,e.w-8,13,'#7eaf73');rect(x+7,y+7,3,3,'#ff5252');rect(x+16,y+7,3,3,'#ff5252')}else{rect(x,y,e.w,e.h,'#29162f');rect(x+3,y+2,e.w-6,15,'#ded4e5');rect(x+7,y+7,3,3,'#ff1744');rect(x+17,y+7,3,3,'#ff1744');rect(x-4,y+13,e.w+8,7,'#6f1d42');label('ВАМПИР',x+e.w/2,y-15,'#ff5d89')}if(e.hp<e.max_hp){rect(x,y-8,e.w,4,'#42151c');rect(x,y-8,e.w*(e.hp/e.max_hp),4,'#ef445c')}}
function draw(){let w=innerWidth,h=innerHeight;ctx.clearRect(0,0,w,h);let sun=Math.max(0,Math.sin(worldTime*Math.PI*2));let night=1-sun;let sky=ctx.createLinearGradient(0,0,0,h);sky.addColorStop(0,night>.65?'#111b42':'#58abe0');sky.addColorStop(1,night>.65?'#31345e':'#d4efff');ctx.fillStyle=sky;ctx.fillRect(0,0,w,h);let orbX=(worldTime*w*1.4)-w*.2,orbY=85-Math.sin(worldTime*Math.PI)*55;ctx.beginPath();ctx.arc(orbX,orbY,night>.65?18:25,0,Math.PI*2);ctx.fillStyle=night>.65?'#e7edff':'#ffe898';ctx.fill();if(me){let tx=me.x+me.w/2-w/2,ty=me.y+me.h/2-h*.56;camera.x+=(tx-camera.x)*.14;camera.y+=(ty-camera.y)*.14;camera.x=Math.max(0,Math.min(worldW*T-w,camera.x));camera.y=Math.max(0,Math.min(worldH*T-h,camera.y));hp.style.width=(100*me.hp/me.max_hp)+'%';hptext.textContent=me.hp+' / '+me.max_hp+' HP'}clock.textContent=night>.62?'Ночь — враги активны':'День';let x0=Math.floor(camera.x/T)-1,x1=Math.ceil((camera.x+w)/T)+1,y0=Math.floor(camera.y/T)-1,y1=Math.ceil((camera.y+h)/T)+1;for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){let b=blocks.get(key(x,y));if(!b)continue;let px=x*T-camera.x,py=y*T-camera.y;rect(px,py,T,T,colors[b]||'#888');ctx.strokeStyle='#0002';ctx.strokeRect(px,py,T,T);if(b===1)rect(px,py,T,5,'#8ae177');if(b===3){ctx.fillStyle='#ffffff12';ctx.fillRect(px+5,py+7,8,3)}}mobs.forEach(drawMob);players.forEach(p=>{let x=p.x-camera.x,y=p.y-camera.y;if(p.hp<=0)return;rect(x,y,p.w,p.h,p.color);rect(x+4,y+3,p.w-8,13,'#ffd9b5');let eye=p.facing>0?p.w-9:6;rect(x+eye,y+7,3,3,'#171923');label(p.name,x+p.w/2,y-7,p.id===me?.id?'#ffd166':'#fff')});if(night>.1){ctx.fillStyle=`rgba(8,12,38,${night*.42})`;ctx.fillRect(0,0,w,h)}requestAnimationFrame(draw)}draw();
try{screen.orientation?.lock?.('landscape').catch(()=>{})}catch(e){}
</script></body></html>'''


if __name__ == "__main__":
    ensure_loop()
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        allow_unsafe_werkzeug=True,
    )
