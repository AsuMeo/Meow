import math
import os
import random
import threading
import time
from collections import deque

from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "living-world-v3")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                    ping_interval=20, ping_timeout=60, logger=False, engineio_logger=False)

TILE, WORLD_W, WORLD_H = 32, 300, 100
PHYSICS_HZ, NETWORK_HZ = 30, 15
DT = 1.0 / PHYSICS_HZ
MAX_PLAYERS = 100
BLOCKS = {
    1: {"name": "Трава", "solid": True}, 2: {"name": "Земля", "solid": True},
    3: {"name": "Камень", "solid": True}, 4: {"name": "Дерево", "solid": True},
    5: {"name": "Листва", "solid": False}, 6: {"name": "Кирпич", "solid": True},
    7: {"name": "Светокамень", "solid": True},
}
MOB_INFO = {
    "bunny": {"name": "КРОЛИК", "w": 22, "h": 19, "hp": 35, "speed": 28, "damage": 0, "xp": 8},
    "deer": {"name": "ОЛЕНЬ", "w": 30, "h": 39, "hp": 75, "speed": 48, "damage": 0, "xp": 14},
    "zombie": {"name": "ЗОМБИ", "w": 25, "h": 42, "hp": 110, "speed": 72, "damage": 10, "xp": 30},
    "slime": {"name": "СЛИЗЕНЬ", "w": 28, "h": 22, "hp": 65, "speed": 55, "damage": 7, "xp": 18},
    "vampire": {"name": "ВАМПИР", "w": 27, "h": 44, "hp": 350, "speed": 165, "damage": 18, "xp": 120},
}

lock = threading.RLock()
loop_guard = threading.Lock()
loop_started = False
players, controls, entities, world = {}, {}, {}, {}
chat_log = deque(maxlen=40)
next_entity_id = 1
world_time = .22
weather = "clear"
weather_timer = 70.0


def clamp(v, lo, hi): return max(lo, min(hi, v))


def generate_world():
    rng = random.Random(73412026)
    result, heights = {}, []
    h = 43
    for x in range(WORLD_W):
        # Волны + небольшой случайный рельеф без резких непроходимых стен.
        target = 42 + math.sin(x / 18) * 3 + math.sin(x / 47) * 4
        if x % 4 == 0: h += clamp(target - h, -1, 1) + rng.choice([-.35, 0, 0, .35])
        h = int(clamp(round(h), 29, 56)); heights.append(h)
    for x, surface in enumerate(heights):
        result[(x, surface)] = 1
        for y in range(surface + 1, min(WORLD_H, surface + 5)): result[(x, y)] = 2
        for y in range(surface + 5, WORLD_H): result[(x, y)] = 3
    # Пещеры: простые эллипсы, не затрагивающие поверхность.
    for _ in range(75):
        cx, cy = rng.randrange(8, WORLD_W - 8), rng.randrange(53, 90)
        rx, ry = rng.randrange(2, 7), rng.randrange(2, 5)
        for x in range(cx-rx, cx+rx+1):
            for y in range(cy-ry, cy+ry+1):
                if ((x-cx)/rx)**2 + ((y-cy)/ry)**2 < 1: result.pop((x, y), None)
    # Безопасная зона появления.
    for x in range(90, 112):
        for y in range(max(0, heights[x]-9), heights[x]): result.pop((x, y), None)
    # Деревья и светящиеся кристаллы в пещерах.
    for x in range(9, WORLD_W-8, 13):
        if 86 <= x <= 116: continue
        s, th = heights[x], rng.randint(3, 5)
        for dy in range(1, th+1): result[(x, s-dy)] = 4
        top = s-th
        for dx in range(-2, 3):
            for dy in range(-2, 2):
                if abs(dx)+abs(dy) <= 3: result[(x+dx, top+dy)] = 5
    for _ in range(80):
        x, y = rng.randrange(5, WORLD_W-5), rng.randrange(58, 93)
        if (x, y) in result: result[(x, y)] = 7
    return result


world = generate_world()


def is_solid(tx, ty):
    if tx < 0 or tx >= WORLD_W or ty >= WORLD_H: return True
    if ty < 0: return False
    return BLOCKS.get(world.get((tx, ty), 0), {}).get("solid", False)


def collides(x, y, w, h):
    for tx in range(math.floor(x/TILE), math.floor((x+w-.01)/TILE)+1):
        for ty in range(math.floor(y/TILE), math.floor((y+h-.01)/TILE)+1):
            if is_solid(tx, ty): return True
    return False


def surface_y(tx):
    tx = int(clamp(tx, 0, WORLD_W-1))
    for y in range(WORLD_H):
        if is_solid(tx, y): return y
    return WORLD_H-1


def spawn_point(tx=100, height=42): return tx*TILE+4, surface_y(tx)*TILE-height


def move_body(b, dt):
    dx, dy = b["vx"]*dt, b["vy"]*dt
    steps = max(1, math.ceil(max(abs(dx), abs(dy))/7))
    sx, sy = dx/steps, dy/steps
    b["grounded"] = False
    for _ in range(steps):
        nx = b["x"]+sx
        if not collides(nx, b["y"], b["w"], b["h"]): b["x"] = nx
        else: b["vx"], sx = 0, 0
        ny = b["y"]+sy
        if not collides(b["x"], ny, b["w"], b["h"]): b["y"] = ny
        else:
            if sy > 0: b["grounded"] = True
            b["vy"], sy = 0, 0
    b["x"] = clamp(b["x"], 0, WORLD_W*TILE-b["w"])
    if b["y"] > WORLD_H*TILE+100: b["dead"] = True


def xp_needed(level): return 80 + (level-1)*55


def add_xp(p, amount):
    p["xp"] += amount
    leveled = False
    while p["xp"] >= xp_needed(p["level"]):
        p["xp"] -= xp_needed(p["level"]); p["level"] += 1; leveled = True
        p["max_hp"] += 12; p["hp"] = p["max_hp"]
    if leveled:
        socketio.emit("effect", {"type":"level", "id":p["id"], "level":p["level"]})


def player_public(p):
    return {k: p[k] for k in ("id","name","color","w","h","hp","max_hp","facing","level","xp")} | {
        "x":round(p["x"],1), "y":round(p["y"],1), "vx":round(p["vx"],1), "vy":round(p["vy"],1),
        "need":xp_needed(p["level"]), "dash_cd":round(max(0,p["dash_cd"]),1)}


def entity_public(e):
    return {"id":e["id"], "kind":e["kind"], "name":e["name"], "x":round(e["x"],1),
            "y":round(e["y"],1), "vx":round(e["vx"],1), "vy":round(e["vy"],1),
            "w":e["w"], "h":e["h"], "hp":e["hp"], "max_hp":e["max_hp"],
            "facing":e["facing"], "dash":round(e["dash_flash"],2)}


def make_entity(kind, tx):
    global next_entity_id
    s = MOB_INFO[kind]; sy = surface_y(tx)
    e = {"id":next_entity_id,"kind":kind,"name":s["name"],"x":tx*TILE+2,"y":sy*TILE-s["h"],
         "vx":0.,"vy":0.,"w":s["w"],"h":s["h"],"hp":s["hp"],"max_hp":s["hp"],
         "speed":s["speed"],"damage":s["damage"],"xp_reward":s["xp"],"grounded":False,"dead":False,
         "facing":random.choice([-1,1]),"think":random.uniform(.5,2.5),"attack_cd":0.,"dash_cd":3.,
         "dash_flash":0.,"last_hit":None}
    entities[next_entity_id] = e; next_entity_id += 1


def seed_entities():
    for kind, count in (("bunny",12),("deer",6),("zombie",10),("slime",9),("vampire",2)):
        for _ in range(count):
            make_entity(kind, random.choice(list(range(12,82))+list(range(120,288))))
seed_entities()


def respawn(p):
    p["x"],p["y"] = spawn_point(); p["vx"]=p["vy"]=0; p["hp"]=p["max_hp"]; p["invuln"]=2.; p["dead"]=False


def hurt_player(p, amount, source_x):
    if p["invuln"] > 0: return
    p["hp"] -= amount; p["invuln"] = .7; p["vx"] = 230 if p["x"]>source_x else -230; p["vy"]=-230
    socketio.emit("effect", {"type":"damage","id":p["id"],"value":amount})
    if p["hp"] <= 0: respawn(p)


def update_player(p, c, dt):
    p["invuln"] = max(0,p["invuln"]-dt); p["dash_cd"] = max(0,p["dash_cd"]-dt)
    p["coyote"] = .11 if p["grounded"] else max(0,p["coyote"]-dt)
    if p["grounded"]: p["air_jumps"] = 1 if p["level"] >= 3 else 0
    direction = int(clamp(c.get("x",0),-1,1))
    if direction: p["facing"] = direction
    speed = 260 + min(60,(p["level"]-1)*4)
    target = direction*speed; accel = 2100 if p["grounded"] else 1150
    if not direction: accel = 2600 if p["grounded"] else 600
    p["vx"] += clamp(target-p["vx"],-accel*dt,accel*dt)
    if c.pop("jump_request",False): p["jump_buffer"] = .14
    p["jump_buffer"] = max(0,p["jump_buffer"]-dt)
    if p["jump_buffer"] > 0:
        if p["coyote"] > 0:
            p["vy"]=-465; p["coyote"]=0; p["jump_buffer"]=0; p["grounded"]=False
        elif p["air_jumps"] > 0:
            p["vy"]=-430; p["air_jumps"]-=1; p["jump_buffer"]=0
            socketio.emit("effect", {"type":"doublejump","id":p["id"]})
    if c.pop("dash_request",False) and p["level"] >= 5 and p["dash_cd"] <= 0:
        p["vx"] = p["facing"]*650; p["dash_cd"] = 2.2; p["invuln"] = .18
        socketio.emit("effect", {"type":"dash","id":p["id"]})
    if not c.get("jump_held") and p["vy"] < -170: p["vy"] += 1400*dt
    p["vy"] = min(900,p["vy"]+1150*dt); move_body(p,dt)
    if p.get("dead"): respawn(p)


def nearest_player(e, radius):
    best, bd = None, radius*radius
    for p in players.values():
        dx=(p["x"]+p["w"]/2)-(e["x"]+e["w"]/2); dy=(p["y"]+p["h"]/2)-(e["y"]+e["h"]/2); d=dx*dx+dy*dy
        if d < bd: best,bd=p,d
    return best


def update_entity(e, dt):
    e["think"]-=dt; e["attack_cd"]=max(0,e["attack_cd"]-dt); e["dash_cd"]=max(0,e["dash_cd"]-dt); e["dash_flash"]=max(0,e["dash_flash"]-dt)
    target=nearest_player(e,750 if e["kind"]=="vampire" else 470)
    if e["kind"] in ("bunny","deer"):
        if e["think"]<=0: e["think"]=random.uniform(1.2,4); e["facing"]=random.choice([-1,0,1])
        if target and abs(target["x"]-e["x"])<150: e["facing"]=-1 if target["x"]>e["x"] else 1
        tv=e["facing"]*e["speed"]
    elif e["kind"]=="slime":
        if target: e["facing"]=1 if target["x"]>e["x"] else -1
        if e["grounded"] and e["think"]<=0:
            e["think"]=random.uniform(.8,1.4); e["vy"]=-330; e["vx"]=e["facing"]*e["speed"]*2
        tv=e["vx"]*.94
    else:
        if target:
            e["facing"]=1 if target["x"]>e["x"] else -1; tv=e["facing"]*e["speed"]
            if e["kind"]=="vampire" and e["dash_cd"]<=0 and abs(target["x"]-e["x"])<450:
                # Рывок ровно до 5 блоков, с проверкой стен.
                for _ in range(20):
                    nx=e["x"]+e["facing"]*(5*TILE/20)
                    if collides(nx,e["y"],e["w"],e["h"]): break
                    e["x"]=nx
                e["dash_cd"]=3.; e["dash_flash"] = .35
        else: tv=0
    e["vx"] += clamp(tv-e["vx"],-750*dt,750*dt)
    ahead=e["x"]+(e["w"]+5 if e["facing"]>0 else -5)
    if e["grounded"] and collides(ahead,e["y"]+4,3,e["h"]-4): e["vy"]=-370
    if e["kind"]=="bunny" and e["grounded"] and random.random()<.016: e["vy"]=-300
    e["vy"]=min(850,e["vy"]+1100*dt); move_body(e,dt)
    if target and e["damage"] and e["attack_cd"]<=0:
        if abs((e["x"]+e["w"]/2)-(target["x"]+target["w"]/2))<34 and abs(e["y"]-target["y"])<48:
            hurt_player(target,e["damage"],e["x"]); e["attack_cd"] = .85


def do_attack(sid):
    p=players.get(sid)
    if not p or p["attack_cd"]>0:return
    p["attack_cd"] = .3
    cx=p["x"]+p["w"]/2+p["facing"]*40; cy=p["y"]+p["h"]/2
    hit=[]
    for e in entities.values():
        ex,ey=e["x"]+e["w"]/2,e["y"]+e["h"]/2
        if abs(ex-cx)<55 and abs(ey-cy)<48:
            damage=24+min(35,p["level"]*3); e["hp"]-=damage; e["last_hit"]=sid; e["vx"]=p["facing"]*260; e["vy"]=-180
            hit.append({"id":e["id"],"value":damage})
    socketio.emit("effect", {"type":"attack","id":sid,"hits":hit,"facing":p["facing"]})


def game_loop():
    global world_time, weather, weather_timer
    tick, spawn_timer = 0, 0.
    while True:
        start=time.perf_counter()
        with lock:
            tick+=1; world_time=(world_time+DT/210)%1; weather_timer-=DT
            if weather_timer<=0:
                weather=random.choices(["clear","rain"],[3,1])[0]; weather_timer=random.uniform(55,110)
            for sid,p in list(players.items()):
                p["attack_cd"]=max(0,p["attack_cd"]-DT); update_player(p,controls.setdefault(sid,{}),DT)
            for eid,e in list(entities.items()):
                update_entity(e,DT)
                if e["hp"]<=0 or e.get("dead"):
                    killer=players.get(e.get("last_hit"));
                    if killer: add_xp(killer,e["xp_reward"])
                    socketio.emit("effect", {"type":"death","id":eid,"xp":e["xp_reward"],"killer":e.get("last_hit")})
                    entities.pop(eid,None)
            spawn_timer+=DT
            if spawn_timer>7 and len(entities)<42:
                spawn_timer=0; make_entity(random.choice(["bunny","deer","zombie","slime"]),random.choice(list(range(12,82))+list(range(120,288))))
            # Физика 30 Hz, сеть 15 Hz: меньше трафика и очередей, движение остаётся точным.
            if tick % (PHYSICS_HZ//NETWORK_HZ)==0:
                state={"players":[player_public(p) for p in players.values()],"entities":[entity_public(e) for e in entities.values()],"time":round(world_time,4),"weather":weather}
            else: state=None
        if state: socketio.emit("state",state)
        socketio.sleep(max(.001,DT-(time.perf_counter()-start)))


def ensure_loop():
    global loop_started
    with loop_guard:
        if not loop_started: loop_started=True; socketio.start_background_task(game_loop)


@app.route("/")
def index(): ensure_loop(); return PAGE

@app.route("/health")
def health(): return {"ok":True,"players":len(players),"mobs":len(entities)}

@socketio.on("connect")
def connect_player():
    ensure_loop(); sid=request.sid
    with lock:
        if len(players)>=MAX_PLAYERS:return False
        x,y=spawn_point(); p={"id":sid,"name":f"Игрок-{random.randint(100,999)}","x":x,"y":y,"vx":0.,"vy":0.,"w":24,"h":42,"grounded":False,"dead":False,
        "color":random.choice(["#ff6b6b","#ffd166","#4dd4ac","#6ea8fe","#d28cff"]),"hp":100,"max_hp":100,"invuln":1.,"attack_cd":0.,"dash_cd":0.,
        "facing":1,"coyote":0.,"jump_buffer":0.,"air_jumps":0,"level":1,"xp":0}
        players[sid]=p; controls[sid]={"x":0,"jump_held":False,"jump_request":False,"dash_request":False}
        init={"w":WORLD_W,"h":WORLD_H,"tile":TILE,"blocks":[[x,y,b] for (x,y),b in world.items()],"players":[player_public(q) for q in players.values()],
              "entities":[entity_public(e) for e in entities.values()],"you":player_public(p),"chat":list(chat_log),"time":world_time,"weather":weather}
    emit("init",init); socketio.emit("notice",{"text":f"{p['name']} появился в мире"})

@socketio.on("disconnect")
def disconnect_player():
    with lock: p=players.pop(request.sid,None); controls.pop(request.sid,None)
    if p: socketio.emit("notice",{"text":f"{p['name']} вышел"})

@socketio.on("set_name")
def set_name(data):
    name=str((data or {}).get("name","")).strip()[:18]
    with lock:
        if name and request.sid in players: players[request.sid]["name"]=name; emit("you",player_public(players[request.sid]))

@socketio.on("input")
def input_event(data):
    data=data or {}
    with lock:
        c=controls.get(request.sid)
        if c is None:return
        try:c["x"]=int(clamp(int(data.get("x",0)),-1,1))
        except (ValueError,TypeError):c["x"]=0
        held=bool(data.get("jump"))
        if held and not c["jump_held"]:c["jump_request"]=True
        c["jump_held"]=held

@socketio.on("dash")
def dash_event():
    with lock:
        if request.sid in controls: controls[request.sid]["dash_request"]=True

@socketio.on("attack")
def attack_event():
    with lock: do_attack(request.sid)

@socketio.on("edit_block")
def edit_block(data):
    try: tx,ty=int(data.get("x")),int(data.get("y")); action=str(data.get("action")); bt=int(data.get("type",2))
    except (ValueError,TypeError,AttributeError):return
    with lock:
        p=players.get(request.sid)
        if not p or not(0<=tx<WORLD_W and 0<=ty<WORLD_H):return
        if ((tx+.5)*TILE-(p["x"]+p["w"]/2))**2+((ty+.5)*TILE-(p["y"]+p["h"]/2))**2>(7*TILE)**2:return
        if action=="break" and (tx,ty) in world:
            old=world.pop((tx,ty)); add_xp(p,1); socketio.emit("world_patch",{"x":tx,"y":ty,"type":0,"by":request.sid,"old":old})
        elif action=="place" and bt in BLOCKS and (tx,ty) not in world:
            ax,ay=tx*TILE,ty*TILE
            occupied=any(ax<q["x"]+q["w"] and ax+TILE>q["x"] and ay<q["y"]+q["h"] and ay+TILE>q["y"] for q in list(players.values())+list(entities.values()))
            if not occupied: world[(tx,ty)]=bt; socketio.emit("world_patch",{"x":tx,"y":ty,"type":bt,"by":request.sid})

@socketio.on("chat")
def chat(data):
    text=str((data or {}).get("text","")).strip()[:160]
    with lock:
        p=players.get(request.sid)
        if not p or not text:return
        msg={"name":p["name"],"text":text,"color":p["color"]};chat_log.append(msg)
    socketio.emit("chat",msg)


PAGE = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover"><title>Living World RTX</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#080d19;color:#fff;font-family:Inter,system-ui,Arial;touch-action:none}body{user-select:none}canvas{position:fixed;inset:0;width:100%;height:100%;image-rendering:pixelated}.hud{position:fixed;z-index:5;inset:10px 10px auto;display:flex;justify-content:space-between;pointer-events:none}.glass{pointer-events:auto;background:linear-gradient(145deg,#14223ee8,#0c1428dd);border:1px solid #8dc8ff42;border-radius:16px;padding:9px 11px;box-shadow:0 8px 28px #0008,inset 0 1px #ffffff1e;backdrop-filter:blur(10px)}.logo{font-weight:1000;color:#ffe178;letter-spacing:1px;text-shadow:0 0 15px #ffc83d88}.tiny{font-size:11px;color:#c5d6ef}.name{display:flex;gap:5px;margin-top:5px}.name input{width:105px;background:#071023;color:#fff;border:1px solid #8dc8ff38;border-radius:8px;padding:5px;outline:0}.button{border:1px solid #ffe47755;border-radius:8px;background:linear-gradient(#ffe486,#e9ad35);color:#182034;font-weight:900;padding:5px 8px}.stats{width:190px}.row{display:flex;justify-content:space-between;font-size:12px;font-weight:800}.bar{height:11px;background:#060b16;border:1px solid #ffffff25;border-radius:8px;overflow:hidden;margin:4px 0}.fill{height:100%;transition:width .15s}.health{background:linear-gradient(90deg,#df294e,#ff6b7b);box-shadow:0 0 9px #ff315c}.xp{background:linear-gradient(90deg,#6959e8,#55c5ff);box-shadow:0 0 9px #58adff}.controls{position:fixed;z-index:7;left:17px;right:17px;bottom:max(15px,env(safe-area-inset-bottom));display:flex;justify-content:space-between;align-items:end;pointer-events:none}.group{display:flex;gap:9px;align-items:end;pointer-events:auto}.control{width:64px;height:64px;border:1px solid #b9dcff55;border-radius:50%;background:linear-gradient(145deg,#1d3358e8,#0c172ce8);color:#fff;font-size:25px;font-weight:1000;box-shadow:0 7px 20px #0009,inset 0 1px #fff2;touch-action:none}.control.on{transform:scale(.93);background:#345f96}.control.small{width:48px;height:48px;font-size:17px}.hit{background:linear-gradient(145deg,#8d284b,#40182e)}.dash{background:linear-gradient(145deg,#6247bb,#282156)}.hotbar{position:fixed;z-index:8;left:50%;bottom:max(14px,env(safe-area-inset-bottom));transform:translateX(-50%);display:flex;gap:5px;padding:6px}.slot{width:42px;height:42px;border:1px solid #acd8ff55;border-radius:9px;background:#0d1830dd;color:#fff;font-weight:900;box-shadow:0 4px 13px #0008}.slot.sel{border:2px solid #ffe477;transform:translateY(-4px);box-shadow:0 0 16px #ffd75b88}.chat{position:fixed;z-index:6;left:10px;bottom:90px;width:min(340px,45vw);pointer-events:none}.log{max-height:100px;overflow:hidden;text-shadow:0 2px 3px #000}.line{font-size:12px}.chatform{display:flex;gap:4px;margin-top:4px;pointer-events:auto}.chatinput{min-width:0;flex:1;background:#0b1429dd;border:1px solid #9ccfff42;border-radius:9px;color:#fff;padding:7px}.toast{position:fixed;z-index:12;left:50%;top:25%;transform:translate(-50%,-50%);font-size:25px;font-weight:1000;color:#ffe474;text-shadow:0 3px 12px #000;opacity:0;transition:.3s}.toast.show{opacity:1;top:22%}.rotate{display:none;position:fixed;z-index:30;inset:0;background:#07101f;align-items:center;justify-content:center;text-align:center;font-size:21px;font-weight:900}@media(orientation:portrait) and (max-width:700px){.rotate{display:flex}.hud,.controls,.chat,.hotbar{display:none}}@media(max-height:440px){.control{width:53px;height:53px}.control.small{width:42px;height:42px}.chat{bottom:68px}.glass{padding:6px 8px}.slot{width:36px;height:36px}.hotbar{padding:3px}.tiny.hide{display:none}}
</style></head><body><canvas id="game"></canvas><div class="rotate">Поверни телефон горизонтально ↔</div><div id="toast" class="toast"></div>
<div class="hud"><div class="glass"><div class="logo">LIVING WORLD ✦</div><div id="online" class="tiny">Подключение…</div><div class="name"><input id="name" maxlength="18" placeholder="Имя"><button class="button" onclick="setName()">OK</button></div><button id="music" class="button" style="width:100%;margin-top:5px">♫ Музыка</button></div><div class="glass stats"><div class="row"><span id="level">УРОВЕНЬ 1</span><span id="clock">День</span></div><div class="bar"><div id="hp" class="fill health"></div></div><div class="row tiny"><span id="hptext">100/100 HP</span><span id="weather">Ясно</span></div><div class="bar"><div id="xp" class="fill xp"></div></div><div id="xptext" class="tiny">0/80 XP</div><div class="tiny hide">Ур.3: двойной прыжок · Ур.5: рывок Q</div></div></div>
<div class="controls"><div class="group"><button id="left" class="control">◀</button><button id="right" class="control">▶</button></div><div class="group"><button id="mode" class="control small">⛏</button><button id="dash" class="control small dash">➤</button><button id="hit" class="control hit">⚔</button><button id="jump" class="control">▲</button></div></div>
<div id="hotbar" class="hotbar glass"><button class="slot sel" data-b="2">▰</button><button class="slot" data-b="3">◆</button><button class="slot" data-b="4">▥</button><button class="slot" data-b="6">▦</button><button class="slot" data-b="7">✦</button></div>
<div class="chat"><div id="log" class="log"></div><form class="chatform" onsubmit="sendChat(event)"><input id="chatinput" class="chatinput" maxlength="160" placeholder="Чат мира"><button class="button">➤</button></form></div>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script><script>
const socket=io({transports:['websocket','polling'],upgrade:true,reconnection:true});const C=document.getElementById('game'),X=C.getContext('2d',{alpha:false});
let W=300,H=100,T=32,blocks=new Map,players=new Map,mobs=new Map,me=null,cam={x:0,y:0},tm=.2,weather='clear',selected=2,mode='place';let L=false,R=false,J=false,lastSend=0,particles=[],floaters=[],rain=[];const colors={1:'#4ead55',2:'#875637',3:'#687181',4:'#83502d',5:'#338547',6:'#a95645',7:'#73e5d2'};
function resize(){let d=Math.min(devicePixelRatio||1,1.6);C.width=innerWidth*d;C.height=innerHeight*d;C.style.width=innerWidth+'px';C.style.height=innerHeight+'px';X.setTransform(d,0,0,d,0,0)}addEventListener('resize',resize);resize();const K=(x,y)=>x+','+y;
const esc=s=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));function line(i){let e=document.createElement('div');e.className='line';e.innerHTML='<b style="color:'+esc(i.color||'#ffe477')+'">'+esc(i.name||'Мир')+':</b> '+esc(i.text||'');log.appendChild(e);while(log.children.length>7)log.firstChild.remove();setTimeout(()=>e.remove(),12000)}function setName(){let v=name.value.trim();if(v)socket.emit('set_name',{name:v})}function sendChat(e){e.preventDefault();let v=chatinput.value.trim();if(v)socket.emit('chat',{text:v});chatinput.value=''}
function dir(){return(R?1:0)-(L?1:0)}function input(force=false){let now=performance.now();if(force||now-lastSend>45){socket.emit('input',{x:dir(),jump:J});lastSend=now}}function hold(id,side){let b=document.getElementById(id);b.onpointerdown=e=>{e.preventDefault();b.setPointerCapture?.(e.pointerId);b.classList.add('on');side<0?L=true:R=true;input(true)};let up=e=>{e.preventDefault();b.classList.remove('on');side<0?L=false:R=false;input(true)};b.onpointerup=up;b.onpointercancel=up}hold('left',-1);hold('right',1);jump.onpointerdown=e=>{e.preventDefault();jump.setPointerCapture?.(e.pointerId);jump.classList.add('on');J=true;input(true)};jump.onpointerup=jump.onpointercancel=e=>{e.preventDefault();jump.classList.remove('on');J=false;input(true)};hit.onpointerdown=e=>{e.preventDefault();socket.emit('attack');hit.classList.add('on')};hit.onpointerup=hit.onpointercancel=()=>hit.classList.remove('on');dash.onpointerdown=e=>{e.preventDefault();socket.emit('dash');dash.classList.add('on')};dash.onpointerup=dash.onpointercancel=()=>dash.classList.remove('on');mode.onclick=()=>{mode=mode==='place'?'break':'place';document.getElementById('mode').textContent=mode==='place'?'⛏':'＋'};
document.querySelectorAll('.slot').forEach(s=>s.onclick=()=>{document.querySelectorAll('.slot').forEach(q=>q.classList.remove('sel'));s.classList.add('sel');selected=+s.dataset.b;mode='place';document.getElementById('mode').textContent='⛏'});
addEventListener('keydown',e=>{if(document.activeElement.tagName==='INPUT')return;if(['KeyA','ArrowLeft'].includes(e.code))L=true;if(['KeyD','ArrowRight'].includes(e.code))R=true;if(['Space','KeyW','ArrowUp'].includes(e.code)){e.preventDefault();J=true}if(e.code==='KeyF')socket.emit('attack');if(['KeyQ','ShiftLeft'].includes(e.code))socket.emit('dash');if(/^Digit[1-5]$/.test(e.code))document.querySelectorAll('.slot')[+e.code.at(-1)-1]?.click();input(true)});addEventListener('keyup',e=>{if(['KeyA','ArrowLeft'].includes(e.code))L=false;if(['KeyD','ArrowRight'].includes(e.code))R=false;if(['Space','KeyW','ArrowUp'].includes(e.code))J=false;input(true)});addEventListener('blur',()=>{L=R=J=false;input(true)});setInterval(input,50);
function edit(e){if(!me)return;e.preventDefault();let tx=Math.floor((e.clientX+cam.x)/T),ty=Math.floor((e.clientY+cam.y)/T),action=e.button===2?'break':mode;let old=blocks.get(K(tx,ty));if(action==='break'&&old)blocks.delete(K(tx,ty));else if(action==='place'&&!old)blocks.set(K(tx,ty),selected);socket.emit('edit_block',{x:tx,y:ty,action:action,type:selected});burst(tx*T+T/2,ty*T+T/2,action==='break'?'#c9b08b':'#9cecff',8)}C.onpointerdown=edit;C.oncontextmenu=e=>e.preventDefault();
function prep(o){o.rx=o.x;o.ry=o.y;return o}socket.on('connect',()=>online.textContent='● Онлайн · '+Math.round(socket.io.engine?.ping||0)+' ms');socket.on('disconnect',()=>online.textContent='Переподключение…');socket.on('init',d=>{W=d.w;H=d.h;T=d.tile;blocks.clear();d.blocks.forEach(b=>blocks.set(K(b[0],b[1]),b[2]));players.clear();d.players.forEach(p=>players.set(p.id,prep(p)));mobs.clear();d.entities.forEach(m=>mobs.set(m.id,prep(m)));me=players.get(d.you.id)||prep(d.you);players.set(me.id,me);tm=d.time;weather=d.weather;name.value=me.name;d.chat.forEach(line)});socket.on('you',p=>{let old=players.get(p.id);Object.assign(old||p,p);me=old||p;players.set(p.id,me)});socket.on('state',d=>{let ps=new Set;d.players.forEach(p=>{ps.add(p.id);let o=players.get(p.id);if(o){p.rx=o.rx;p.ry=o.ry;Object.assign(o,p)}else players.set(p.id,prep(p));if(me&&p.id===me.id)me=players.get(p.id)});for(let id of players.keys())if(!ps.has(id))players.delete(id);let ms=new Set;d.entities.forEach(m=>{ms.add(m.id);let o=mobs.get(m.id);if(o)Object.assign(o,m);else mobs.set(m.id,prep(m))});for(let id of mobs.keys())if(!ms.has(id))mobs.delete(id);tm=d.time;weather=d.weather});socket.on('world_patch',b=>{b.type?blocks.set(K(b.x,b.y),b.type):blocks.delete(K(b.x,b.y));burst(b.x*T+T/2,b.y*T+T/2,b.type?'#8cefff':'#d0a97e',10)});socket.on('chat',line);socket.on('notice',i=>line({text:i.text}));socket.on('effect',e=>{let o=players.get(e.id)||mobs.get(e.id);if(e.type==='level'&&e.id===me?.id)toastMsg('УРОВЕНЬ '+e.level+'!');if(e.type==='damage'&&o)floater(o.x,o.y,'-'+e.value,'#ff5577');if(e.type==='death'){let o=mobs.get(e.id);if(o)burst(o.x,o.y,'#ff537c',18);if(e.killer===me?.id)floater(me.x,me.y,'+'+e.xp+' XP','#71cfff')}if((e.type==='dash'||e.type==='doublejump')&&o)burst(o.x,o.y,'#8b7cff',14);if(e.type==='attack'){let p=players.get(e.id);if(p)burst(p.x+p.facing*25,p.y+20,'#fff1a8',6);e.hits?.forEach(h=>{let m=mobs.get(h.id);if(m)floater(m.x,m.y,'-'+h.value,'#ffcf61')})}});
function toastMsg(s){toast.textContent=s;toast.classList.add('show');setTimeout(()=>toast.classList.remove('show'),1800)}function burst(x,y,c,n){for(let i=0;i<n;i++)particles.push({x,y,vx:(Math.random()-.5)*180,vy:(Math.random()-.8)*170,c,t:.7})}function floater(x,y,s,c){floaters.push({x,y,s,c,t:1})}
// Лёгкая оригинальная процедурная музыка.
let ac=null,mt=null,ni=0,mel=[0,4,7,11,7,4,2,7,9,5,2,0,4,9,7,2];function tone(f,w,d,v,type='sine'){let o=ac.createOscillator(),g=ac.createGain();o.type=type;o.frequency.value=f;g.gain.setValueAtTime(.0001,w);g.gain.linearRampToValueAtTime(v,w+.1);g.gain.exponentialRampToValueAtTime(.0001,w+d);o.connect(g).connect(ac.destination);o.start(w);o.stop(w+d+.05)}function musicLoop(){let n=ac.currentTime+.03;for(let i=0;i<4;i++){let f=220*2**(mel[(ni+i)%mel.length]/12);tone(f,n+i*.55,1,.02);tone(f/2,n+i*.55,1.2,.01,'triangle')}ni=(ni+4)%mel.length}music.onclick=async()=>{if(ac){clearInterval(mt);ac.close();ac=null;music.textContent='♫ Музыка'}else{ac=new(AudioContext||webkitAudioContext);await ac.resume();musicLoop();mt=setInterval(musicLoop,2100);music.textContent='■ Музыка'}};
function solid(tx,ty){if(tx<0||tx>=W||ty>=H)return true;if(ty<0)return false;return [1,2,3,4,6,7].includes(blocks.get(K(tx,ty)))}function collision(x,y,w,h){for(let tx=Math.floor(x/T);tx<=Math.floor((x+w-.1)/T);tx++)for(let ty=Math.floor(y/T);ty<=Math.floor((y+h-.1)/T);ty++)if(solid(tx,ty))return true;return false}
// Клиентское предсказание только для картинки своего героя; сервер остаётся главным.
function predict(dt){if(!me)return;let d=dir(),target=d*(260+Math.min(60,(me.level-1)*4)),a=d?1100:600;me.rx??=me.x;me.ry??=me.y;me.pvx??=me.vx;me.pvy??=me.vy;me.pvx+=Math.max(-a*dt,Math.min(a*dt,target-me.pvx));me.pvy=Math.min(900,me.pvy+1150*dt);let nx=me.rx+me.pvx*dt;if(!collision(nx,me.ry,me.w,me.h))me.rx=nx;else me.pvx=0;let ny=me.ry+me.pvy*dt;if(!collision(me.rx,ny,me.w,me.h))me.ry=ny;else me.pvy=0;let err=Math.hypot(me.x-me.rx,me.y-me.ry);if(err>100){me.rx=me.x;me.ry=me.y;me.pvx=me.vx;me.pvy=me.vy}else{me.rx+=(me.x-me.rx)*Math.min(1,dt*6);me.ry+=(me.y-me.ry)*Math.min(1,dt*6);me.pvx+=(me.vx-me.pvx)*Math.min(1,dt*4);me.pvy+=(me.vy-me.pvy)*Math.min(1,dt*4)}}
function rect(x,y,w,h,c){X.fillStyle=c;X.fillRect(Math.round(x),Math.round(y),w,h)}function label(s,x,y,c='#fff'){X.font='bold 11px system-ui';X.textAlign='center';X.lineWidth=3;X.strokeStyle='#07101f';X.strokeText(s,x,y);X.fillStyle=c;X.fillText(s,x,y)}function mobDraw(e){let x=e.rx-cam.x,y=e.ry-cam.y;if(e.dash>0){X.globalAlpha=.18;rect(x-e.facing*38,y,e.w,e.h,'#cc70ff');X.globalAlpha=1}if(e.kind==='bunny'){rect(x,y+7,e.w,e.h-7,'#eee');rect(x+(e.facing>0?13:3),y,5,12,'#eee');rect(x+(e.facing>0?18:7),y+11,3,3,'#222')}else if(e.kind==='deer'){rect(x+4,y+10,e.w-8,e.h-13,'#ad7040');rect(x+(e.facing>0?19:0),y,e.w-9,18,'#c58952');rect(x+6,y+e.h-8,4,12,'#5f3a25');rect(x+21,y+e.h-8,4,12,'#5f3a25')}else if(e.kind==='zombie'){rect(x,y,e.w,e.h,'#456c4c');rect(x+4,y+3,e.w-8,13,'#78aa72');rect(x+7,y+7,3,3,'#ff365c');rect(x+16,y+7,3,3,'#ff365c')}else if(e.kind==='slime'){X.fillStyle='#50d6ac';X.beginPath();X.roundRect(x,y,e.w,e.h,10);X.fill();rect(x+7,y+8,3,3,'#11252b');rect(x+18,y+8,3,3,'#11252b')}else{rect(x,y,e.w,e.h,'#24132e');rect(x+3,y+2,e.w-6,15,'#ded4e5');rect(x+7,y+7,3,3,'#ff1744');rect(x+17,y+7,3,3,'#ff1744');rect(x-4,y+13,e.w+8,7,'#731d47')}label(e.name,x+e.w/2,y-14,e.kind==='vampire'?'#ff668e':'#fff');if(e.hp<e.max_hp){rect(x,y-9,e.w,4,'#361421');rect(x,y-9,e.w*e.hp/e.max_hp,4,'#f04468')}}
let prev=performance.now();function draw(now){let dt=Math.min(.04,(now-prev)/1000);prev=now;predict(dt);let w=innerWidth,h=innerHeight,sun=Math.max(0,Math.sin(tm*Math.PI*2)),night=1-sun,g=X.createLinearGradient(0,0,0,h);g.addColorStop(0,night>.65?'#08122f':'#4b9fd5');g.addColorStop(1,night>.65?'#292d5b':'#d2edff');X.fillStyle=g;X.fillRect(0,0,w,h);let ox=tm*w*1.4-w*.2,oy=90-Math.sin(tm*Math.PI)*58;X.shadowBlur=35;X.shadowColor=night>.65?'#aec8ff':'#ffe179';X.fillStyle=night>.65?'#e4edff':'#ffe58c';X.beginPath();X.arc(ox,oy,night>.65?17:25,0,7);X.fill();X.shadowBlur=0;if(me){let tx=me.rx+me.w/2-w/2,ty=me.ry+me.h/2-h*.56;cam.x+=(tx-cam.x)*Math.min(1,dt*8);cam.y+=(ty-cam.y)*Math.min(1,dt*8);cam.x=Math.max(0,Math.min(W*T-w,cam.x));cam.y=Math.max(0,Math.min(H*T-h,cam.y));hp.style.width=100*me.hp/me.max_hp+'%';hptext.textContent=me.hp+'/'+me.max_hp+' HP';xp.style.width=100*me.xp/me.need+'%';xptext.textContent=me.xp+'/'+me.need+' XP';level.textContent='УРОВЕНЬ '+me.level}clock.textContent=night>.62?'Ночь':'День';document.getElementById('weather').textContent=weather==='rain'?'Дождь':'Ясно';let x0=Math.floor(cam.x/T)-1,x1=Math.ceil((cam.x+w)/T)+1,y0=Math.floor(cam.y/T)-1,y1=Math.ceil((cam.y+h)/T)+1;for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){let b=blocks.get(K(x,y));if(!b)continue;let px=x*T-cam.x,py=y*T-cam.y,c=colors[b]||'#888';rect(px+3,py+5,T-3,T-3,'#0005');let bg=X.createLinearGradient(px,py,px+T,py+T);bg.addColorStop(0,c);bg.addColorStop(1,'#263042');X.fillStyle=bg;X.fillRect(px,py,T,T);X.strokeStyle='#ffffff12';X.strokeRect(px+.5,py+.5,T-1,T-1);if(b===1)rect(px,py,T,5,'#86df70');if(b===7){X.shadowBlur=14;X.shadowColor='#73ffe1';rect(px+7,py+7,18,18,'#8effe7');X.shadowBlur=0}}mobs.forEach(e=>{e.rx+=(e.x-e.rx)*Math.min(1,dt*11);e.ry+=(e.y-e.ry)*Math.min(1,dt*11);mobDraw(e)});players.forEach(p=>{if(p!==me){p.rx+=(p.x-p.rx)*Math.min(1,dt*11);p.ry+=(p.y-p.ry)*Math.min(1,dt*11)}let x=p.rx-cam.x,y=p.ry-cam.y;rect(x+3,y+5,p.w,p.h,'#0006');rect(x,y,p.w,p.h,p.color);rect(x+4,y+3,p.w-8,13,'#ffd9b5');rect(x+(p.facing>0?p.w-9:6),y+7,3,3,'#111');label('Lv.'+p.level+' '+p.name,x+p.w/2,y-8,p===me?'#ffe477':'#fff')});for(let i=particles.length-1;i>=0;i--){let p=particles[i];p.t-=dt;p.x+=p.vx*dt;p.y+=p.vy*dt;p.vy+=300*dt;X.globalAlpha=Math.max(0,p.t/.7);rect(p.x-cam.x,p.y-cam.y,4,4,p.c);if(p.t<=0)particles.splice(i,1)}X.globalAlpha=1;for(let i=floaters.length-1;i>=0;i--){let f=floaters[i];f.t-=dt;f.y-=35*dt;label(f.s,f.x-cam.x,f.y-cam.y,f.c);if(f.t<=0)floaters.splice(i,1)}if(weather==='rain'){while(rain.length<80)rain.push({x:Math.random()*w,y:Math.random()*h,s:350+Math.random()*250});X.strokeStyle='#a7ceff88';X.lineWidth=1;X.beginPath();rain.forEach(r=>{r.y+=r.s*dt;r.x-=r.s*.18*dt;if(r.y>h){r.y=-20;r.x=Math.random()*w}X.moveTo(r.x,r.y);X.lineTo(r.x-5,r.y+14)});X.stroke()}else rain.length=0;if(night>.08){X.fillStyle=`rgba(4,8,30,${night*.34})`;X.fillRect(0,0,w,h);/* дешёвое локальное освещение */let lg=X.createRadialGradient(w/2,h*.55,25,w/2,h*.55,230);lg.addColorStop(0,'rgba(255,222,145,.16)');lg.addColorStop(1,'rgba(0,0,0,0)');X.fillStyle=lg;X.fillRect(0,0,w,h)}requestAnimationFrame(draw)}requestAnimationFrame(draw);try{screen.orientation?.lock?.('landscape').catch(()=>{})}catch(e){}
</script></body></html>'''

if __name__ == "__main__":
    ensure_loop()
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT","8080")), allow_unsafe_werkzeug=True)
