import os
import math
import random
import time
import threading
from collections import deque
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'blockworld-ultimate-2026-secret')

socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='threading',
    ping_interval=15,
    ping_timeout=45,
    logger=False,
    engineio_logger=False,
)

# --- Константы Мира ---
TILE = 32
WORLD_W = 350
WORLD_H = 120
TICK = 1 / 30
MAX_PLAYERS = 100

BLOCKS = {
    1: {'name': 'Трава', 'color': '#4caf50', 'top_color': '#81c784', 'solid': True},
    2: {'name': 'Земля', 'color': '#795548', 'solid': True},
    3: {'name': 'Камень', 'color': '#607d8b', 'solid': True},
    4: {'name': 'Дерево', 'color': '#5d4037', 'solid': True},
    5: {'name': 'Листва', 'color': '#388e3c', 'solid': False},
    6: {'name': 'Доски', 'color': '#a1887f', 'solid': True},
    7: {'name': 'Факел', 'color': '#ffb300', 'solid': False, 'light': True},
    8: {'name': 'Уголь', 'color': '#37474f', 'solid': True},
    9: {'name': 'Золото', 'color': '#ffd54f', 'solid': True},
}

world_lock = threading.RLock()
players = {}
inputs = {}
mobs = {}
world = {}
chat_messages = deque(maxlen=50)
drops = {}

next_mob_id = 1
next_drop_id = 1
world_time = 0.25  # 0.0 - 1.0 (День / Ночь)


def generate_world():
    rng = random.Random(20260804)
    heights = []
    height = 50

    for x in range(WORLD_W):
        height += rng.choice([-1, 0, 0, 0, 1, 0, -1, 1])
        height = max(35, min(75, height))
        heights.append(height)

    result = {}
    # Генерация почвы и руд
    for x, surface in enumerate(heights):
        result[(x, surface)] = 1  # Трава
        for y in range(surface + 1, min(WORLD_H, surface + 7)):
            result[(x, y)] = 2  # Земля
        for y in range(surface + 7, WORLD_H):
            ore_roll = rng.random()
            if ore_roll < 0.03:
                result[(x, y)] = 8  # Уголь
            elif ore_roll < 0.008:
                result[(x, y)] = 9  # Золото
            else:
                result[(x, y)] = 3  # Камень

    # Генерация пещер
    for _ in range(40):
        cx = rng.randint(10, WORLD_W - 10)
        cy = rng.randint(60, WORLD_H - 10)
        cr = rng.randint(3, 7)
        for dx in range(-cr, cr + 1):
            for dy in range(-cr, cr + 1):
                if dx * dx + dy * dy <= cr * cr:
                    tx, ty = cx + dx, cy + dy
                    if 0 <= tx < WORLD_W and 0 <= ty < WORLD_H:
                        result.pop((tx, ty), None)

    # Генерация деревьев
    for x in range(5, WORLD_W - 5, 8):
        if rng.random() > 0.4:
            surface = heights[x]
            tree_h = rng.randint(4, 7)
            for y in range(surface - 1, surface - 1 - tree_h, -1):
                if y > 0:
                    result[(x, y)] = 4  # Дерево
            # Крона
            top_y = surface - 1 - tree_h
            for dx in range(-2, 3):
                for dy in range(-2, 2):
                    tx, ty = x + dx, top_y + dy
                    if 0 <= tx < WORLD_W and 0 <= ty < WORLD_H and (tx, ty) not in result:
                        result[(tx, ty)] = 5  # Листва

    return result, heights


world, surface_heights = generate_world()


def is_solid(tx, ty):
    if tx < 0 or tx >= WORLD_W or ty >= WORLD_H:
        return True
    if ty < 0:
        return False
    block_type = world.get((tx, ty))
    if not block_type:
        return False
    return BLOCKS.get(block_type, {}).get('solid', False)


def collides_box(x, y, width, height):
    left = int(math.floor(x / TILE))
    right = int(math.floor((x + width - 0.01) / TILE))
    top = int(math.floor(y / TILE))
    bottom = int(math.floor((y + height - 0.01) / TILE))

    for tx in range(left, right + 1):
        for ty in range(top, bottom + 1):
            if is_solid(tx, ty):
                return True
    return False


def get_spawn_point():
    spawn_x = random.randint(100, 200)
    surface_y = surface_heights[spawn_x]
    return spawn_x * TILE, (surface_y - 2) * TILE


def spawn_mob(mtype, x=None, y=None):
    global next_mob_id
    if x is None or y is None:
        sx = random.randint(10, WORLD_W - 10)
        sy = surface_heights[sx] - 2
        x = sx * TILE
        y = sy * TILE

    mob_id = f"mob_{next_mob_id}"
    next_mob_id += 1

    configs = {
        'vampire': {'name': 'Вампир-Лорд (БОСС)', 'hp': 300, 'w': 28, 'h': 44, 'color': '#800020', 'speed': 130},
        'zombie': {'name': 'Зомби', 'hp': 70, 'w': 24, 'h': 40, 'color': '#388e3c', 'speed': 90},
        'slime': {'name': 'Слизень', 'hp': 40, 'w': 26, 'h': 22, 'color': '#00e676', 'speed': 70},
        'bunny': {'name': 'Кролик', 'hp': 20, 'w': 20, 'h': 18, 'color': '#ffffff', 'speed': 110},
    }
    cfg = configs.get(mtype, configs['zombie'])

    mobs[mob_id] = {
        'id': mob_id,
        'type': mtype,
        'name': cfg['name'],
        'x': x,
        'y': y,
        'vx': 0,
        'vy': 0,
        'w': cfg['w'],
        'h': cfg['h'],
        'hp': cfg['hp'],
        'max_hp': cfg['hp'],
        'color': cfg['color'],
        'speed': cfg['speed'],
        'grounded': False,
        'facing': 1,
        'dash_cooldown': 0,
        'dash_active': 0,
        'jump_cooldown': 0,
        'target_id': None,
    }
    return mob_id


# Начальный спавн мобов
for _ in range(8):
    spawn_mob('zombie')
for _ in range(10):
    spawn_mob('bunny')
for _ in range(6):
    spawn_mob('slime')
spawn_mob('vampire', x=120 * TILE, y=(surface_heights[120] - 3) * TILE)


def physics_step(entity, dt, target_vx, wants_jump):
    gravity = 1150.0
    jump_speed = 460.0

    # Гравитация
    entity['vy'] += gravity * dt
    if entity['vy'] > 950.0:
        entity['vy'] = 950.0

    # Прыжок
    if wants_jump and entity['grounded']:
        entity['vy'] = -jump_speed
        entity['grounded'] = False

    # Движение по X с АВТО-СТУПЕНЬКОЙ (Auto-step 1 block)
    entity['vx'] = target_vx
    dx = entity['vx'] * dt

    if dx != 0:
        new_x = entity['x'] + dx
        if not collides_box(new_x, entity['y'], entity['w'], entity['h']):
            entity['x'] = new_x
        else:
            # Пробуем авто-подъем на 1 блок вверх (как в Terraria!)
            step_h = TILE + 1
            if entity['grounded'] and not collides_box(new_x, entity['y'] - step_h, entity['w'], entity['h']):
                entity['y'] -= step_h
                entity['x'] = new_x
            else:
                # Плавный прижим к стене
                step_dir = 1.0 if dx > 0 else -1.0
                while not collides_box(entity['x'] + step_dir, entity['y'], entity['w'], entity['h']):
                    entity['x'] += step_dir
                entity['vx'] = 0

    # Движение по Y
    dy = entity['vy'] * dt
    if dy != 0:
        new_y = entity['y'] + dy
        if not collides_box(entity['x'], new_y, entity['w'], entity['h']):
            entity['y'] = new_y
            entity['grounded'] = False
        else:
            if entity['vy'] > 0:
                entity['grounded'] = True
                entity['y'] = math.floor((entity['y'] + entity['h']) / TILE) * TILE - entity['h']
            elif entity['vy'] < 0:
                entity['y'] = math.ceil(entity['y'] / TILE) * TILE
            entity['vy'] = 0

    # Ограничения карты
    entity['x'] = max(0, min((WORLD_W - 1) * TILE - entity['w'], entity['x']))
    entity['y'] = max(0, min((WORLD_H - 1) * TILE - entity['h'], entity['y']))


def update_mobs(dt):
    alive_players = [p for p in players.values() if p['hp'] > 0]
    vampire_exists = False

    for mob_id, mob in list(mobs.items()):
        if mob['type'] == 'vampire':
            vampire_exists = True

        # Поиск ближайшего игрока
        nearest_p = None
        min_dist = 999999
        for p in alive_players:
            dist = math.hypot(p['x'] - mob['x'], p['y'] - mob['y'])
            if dist < min_dist:
                min_dist = dist
                nearest_p = p

        target_vx = 0
        wants_jump = False

        if mob['type'] == 'vampire':
            mob['dash_cooldown'] -= dt
            if mob['dash_active'] > 0:
                mob['dash_active'] -= dt

            if nearest_p and min_dist < 500:
                dir_x = 1 if nearest_p['x'] > mob['x'] else -1
                mob['facing'] = dir_x

                # СУПЕР СПОСОБНОСТЬ: РЫВОК НА 5 БЛОКОВ (160 px) РАЗ В 3 СЕКУНДЫ!
                if mob['dash_cooldown'] <= 0:
                    mob['dash_cooldown'] = 3.0
                    mob['dash_active'] = 0.35
                    # Импульсный рывок вперед со звуком и спецэффектами
                    mob['vx'] = dir_x * 900.0
                    socketio.emit('vampire_dash', {'id': mob['id'], 'x': mob['x'], 'y': mob['y'], 'dir': dir_x})

                if mob['dash_active'] > 0:
                    target_vx = mob['facing'] * 850.0
                else:
                    target_vx = mob['facing'] * mob['speed']

                if collides_box(mob['x'] + mob['facing'] * 8, mob['y'], mob['w'], mob['h']) and mob['grounded']:
                    wants_jump = True

                # Атака игрока при столкновении
                if min_dist < 32:
                    dmg = 35 if mob['dash_active'] > 0 else 18
                    damage_player(nearest_p, dmg, knock_dir=mob['facing'])

        elif mob['type'] == 'zombie':
            if nearest_p and min_dist < 380:
                dir_x = 1 if nearest_p['x'] > mob['x'] else -1
                mob['facing'] = dir_x
                target_vx = dir_x * mob['speed']
                if collides_box(mob['x'] + dir_x * 8, mob['y'], mob['w'], mob['h']) and mob['grounded']:
                    wants_jump = True

                if min_dist < 28:
                    damage_player(nearest_p, 12, knock_dir=dir_x)

        elif mob['type'] == 'slime':
            mob['jump_cooldown'] -= dt
            if nearest_p and min_dist < 320:
                dir_x = 1 if nearest_p['x'] > mob['x'] else -1
                mob['facing'] = dir_x
                if mob['grounded'] and mob['jump_cooldown'] <= 0:
                    mob['jump_cooldown'] = 1.4
                    wants_jump = True
                    target_vx = dir_x * 220.0
                elif not mob['grounded']:
                    target_vx = mob['facing'] * 180.0

                if min_dist < 26:
                    damage_player(nearest_p, 8, knock_dir=dir_x)

        elif mob['type'] == 'bunny':
            if nearest_p and min_dist < 140:
                dir_x = -1 if nearest_p['x'] > mob['x'] else 1
                mob['facing'] = dir_x
                target_vx = dir_x * mob['speed']
                if mob['grounded'] and random.random() < 0.05:
                    wants_jump = True
            else:
                if random.random() < 0.02:
                    mob['facing'] = random.choice([-1, 1])
                if random.random() < 0.3:
                    target_vx = mob['facing'] * 40.0

        physics_step(mob, dt, target_vx, wants_jump)

    # Гарантируем спавн Вампира-Босса, если умер
    if not vampire_exists and len(alive_players) > 0:
        if random.random() < 0.01:
            p = random.choice(alive_players)
            bx = clamp(p['x'] + random.choice([-300, 300]), 100, (WORLD_W - 10) * TILE)
            by = surface_heights[int(bx // TILE)] * TILE - 100
            spawn_mob('vampire', bx, by)
            socketio.emit('notice', {'text': '⚠️ ВАМПИР-ЛОРД ВОССТАЛ ИЗ ТЬМЫ!', 'color': '#ff1744'})


def damage_player(player, dmg, knock_dir=0):
    if player['hp'] <= 0 or player.get('invul', 0) > 0:
        return
    player['hp'] -= dmg
    player['invul'] = 0.5  # Время неуязвимости (сек)
    player['vx'] += knock_dir * 250.0
    player['vy'] = -200.0

    socketio.emit('effect', {'type': 'damage', 'x': player['x'], 'y': player['y'], 'val': f"-{dmg}"})

    if player['hp'] <= 0:
        player['hp'] = 0
        socketio.emit('notice', {'text': f"☠️ {player['name']} погиб в бою!", 'color': '#ff5252'})
        # Спавн респавна через 2 сек
        threading.Timer(2.0, respawn_player, args=[player['id']]).start()


def respawn_player(sid):
    with world_lock:
        if sid in players:
            p = players[sid]
            rx, ry = get_spawn_point()
            p['x'] = rx
            p['y'] = ry
            p['hp'] = 100
            p['vx'] = 0
            p['vy'] = 0


def clamp(val, low, high):
    return max(low, min(high, val))


def player_public(p):
    return {
        'id': p['id'],
        'name': p['name'],
        'x': round(p['x'], 1),
        'y': round(p['y'], 1),
        'vx': round(p['vx'], 1),
        'vy': round(p['vy'], 1),
        'hp': p['hp'],
        'max_hp': p['max_hp'],
        'color': p['color'],
        'w': p['w'],
        'h': p['h'],
        'facing': p['facing'],
        'sprinting': p['sprinting'],
        'holding': p['holding'],
    }


def update_players(dt):
    for sid, p in list(players.items()):
        if p['hp'] <= 0:
            continue

        if p.get('invul', 0) > 0:
            p['invul'] -= dt

        ctrl = inputs.get(sid, {})

        # Движение / Бег
        dir_x = clamp(int(ctrl.get('x', 0)), -1, 1)
        sprint = bool(ctrl.get('sprint', False))
        p['sprinting'] = sprint

        speed = 310.0 if sprint else 210.0
        target_vx = dir_x * speed

        if dir_x != 0:
            p['facing'] = dir_x

        wants_jump = False
        if ctrl.get('jump_request'):
            wants_jump = True
            ctrl['jump_request'] = False

        physics_step(p, dt, target_vx, wants_jump)


def game_loop():
    global world_time
    last_time = time.perf_counter()

    while True:
        now = time.perf_counter()
        dt = min(0.1, now - last_time)
        last_time = now

        # Время суток
        world_time = (world_time + dt / 300.0) % 1.0  # Полный цикл 5 минут

        with world_lock:
            update_players(dt)
            update_mobs(dt)

            state = {
                'time': round(world_time, 4),
                'players': [player_public(p) for p in players.values()],
                'mobs': list(mobs.values()),
            }

        socketio.emit('state', state)
        socketio.sleep(TICK)


@app.route('/')
def index():
    return render_template_string(PAGE)


@socketio.on('connect')
def connect_player():
    sid = request.sid
    with world_lock:
        if len(players) >= MAX_PLAYERS:
            return False

        sx, sy = get_spawn_point()
        player = {
            'id': sid,
            'name': f'Герой-{random.randint(100, 999)}',
            'x': sx,
            'y': sy,
            'vx': 0,
            'vy': 0,
            'w': 22,
            'h': 42,
            'hp': 100,
            'max_hp': 100,
            'grounded': False,
            'facing': 1,
            'sprinting': False,
            'holding': 1,
            'color': random.choice(['#e53935', '#d81b60', '#8e24aa', '#1e88e5', '#43a047', '#fb8c00']),
        }
        players[sid] = player
        inputs[sid] = {'x': 0, 'sprint': False, 'jump_request': False}

        initial = {
            'w': WORLD_W,
            'h': WORLD_H,
            'tile': TILE,
            'blocks': [{'x': x, 'y': y, 'type': b} for (x, y), b in world.items()],
            'players': [player_public(p) for p in players.values()],
            'mobs': list(mobs.values()),
            'chat': list(chat_messages),
            'time': world_time,
            'you_id': sid,
        }

    emit('init', initial)
    socketio.emit('notice', {'text': f"⚔️ {player['name']} зашёл в мир!", 'color': '#81c784'})


@socketio.on('disconnect')
def disconnect_player():
    sid = request.sid
    with world_lock:
        p = players.pop(sid, None)
        inputs.pop(sid, None)
    if p:
        socketio.emit('notice', {'text': f"👋 {p['name']} покинул мир", 'color': '#b0bec5'})


@socketio.on('input')
def handle_input(data):
    sid = request.sid
    if not data or sid not in players:
        return
    with world_lock:
        ctrl = inputs.setdefault(sid, {'x': 0, 'sprint': False, 'jump_request': False})
        ctrl['x'] = clamp(int(data.get('x', 0)), -1, 1)
        ctrl['sprint'] = bool(data.get('sprint', False))
        if bool(data.get('jump')):
            ctrl['jump_request'] = True


@socketio.on('set_holding')
def set_holding(data):
    sid = request.sid
    with world_lock:
        if sid in players:
            players[sid]['holding'] = int(data.get('slot', 1))


@socketio.on('attack_mob')
def attack_mob(data):
    sid = request.sid
    mob_id = str(data.get('id', ''))
    with world_lock:
        p = players.get(sid)
        m = mobs.get(mob_id)
        if not p or not m or p['hp'] <= 0:
            return

        dist = math.hypot(p['x'] - m['x'], p['y'] - m['y'])
        if dist <= TILE * 3.5:
            damage = random.randint(22, 35)
            if p['holding'] == 1:  # Меч
                damage += 15

            m['hp'] -= damage
            knock_dir = 1 if m['x'] > p['x'] else -1
            m['vx'] += knock_dir * 300.0
            m['vy'] = -180.0

            socketio.emit('effect', {'type': 'damage', 'x': m['x'], 'y': m['y'], 'val': f"-{damage}"})

            if m['hp'] <= 0:
                socketio.emit('notice', {'text': f"💥 {p['name']} уничтожил {m['name']}!", 'color': '#ffd54f'})
                mobs.pop(mob_id, None)


@socketio.on('edit_block')
def edit_block(data):
    sid = request.sid
    try:
        tx = int(data.get('x'))
        ty = int(data.get('y'))
        action = str(data.get('action', 'place'))
        btype = int(data.get('type', 2))
    except (TypeError, ValueError):
        return

    with world_lock:
        p = players.get(sid)
        if not p or p['hp'] <= 0:
            return

        # Проверка дистации (7 блоков)
        cx = (p['x'] + p['w'] / 2) / TILE
        cy = (p['y'] + p['h'] / 2) / TILE
        if (tx - cx) ** 2 + (ty - cy) ** 2 > 64:
            return

        if action == 'break':
            if (tx, ty) in world:
                del world[(tx, ty)]
                socketio.emit('world_patch', {'x': tx, 'y': ty, 'type': 0})
        elif action == 'place' and btype in BLOCKS and (tx, ty) not in world:
            # Проверка, чтобы не застроить игрока
            bx = tx * TILE
            by = ty * TILE
            if not (bx < p['x'] + p['w'] and bx + TILE > p['x'] and by < p['y'] + p['h'] and by + TILE > p['y']):
                world[(tx, ty)] = btype
                socketio.emit('world_patch', {'x': tx, 'y': ty, 'type': btype})


@socketio.on('chat')
def handle_chat(data):
    sid = request.sid
    text = str((data or {}).get('text', '')).strip()[:140]
    with world_lock:
        p = players.get(sid)
        if not p or not text:
            return
        msg = {'name': p['name'], 'text': text, 'color': p['color']}
        chat_messages.append(msg)
    socketio.emit('chat', msg)


@socketio.on('set_name')
def set_name(data):
    sid = request.sid
    name = str((data or {}).get('name', '')).strip()[:18]
    if name:
        with world_lock:
            if sid in players:
                players[sid]['name'] = name


# Запуск игрового потока
threading.Thread(target=game_loop, daemon=True).start()


# --- FRONTEND (HTML5 CANVAS ENGINE + WEBAUDIO + CONTROLS) ---
PAGE = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>BlockWorld Genshin Terraria Railway</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none}
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#090a0f;color:#fff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
#game{position:fixed;inset:0;width:100vw;height:100vh;display:block;touch-action:none;image-rendering:pixelated}

/* HUD UI */
.hud{position:fixed;z-index:10;inset:0;pointer-events:none;display:flex;flex-direction:column;justify-content:space-between;padding:12px}
.top-bar{display:flex;justify-content:space-between;align-items:flex-start}
.card{background:rgba(18,24,38,0.85);border:1px solid rgba(255,255,255,0.15);backdrop-filter:blur(10px);border-radius:14px;padding:10px 14px;pointer-events:auto;box-shadow:0 8px 32px rgba(0,0,0,0.4)}
.hp-bar-box{width:180px;height:16px;background:#1a2332;border-radius:8px;overflow:hidden;border:1px solid #ffffff22;margin-top:4px}
.hp-fill{height:100%;background:linear-gradient(90deg, #ff1744, #ff5252);width:100%;transition:width 0.2s}
.player-name{font-weight:900;font-size:14px;color:#ffd166;display:flex;align-items:center;gap:6px}

.btn-audio{background:#ffd166;color:#111;border:0;border-radius:8px;padding:6px 12px;font-weight:800;cursor:pointer;font-size:12px}

/* HOTBAR */
.hotbar{display:flex;gap:6px;background:rgba(15,20,30,0.85);padding:6px;border-radius:12px;border:1px solid rgba(255,255,255,0.15);pointer-events:auto;margin:0 auto}
.slot{width:44px;height:44px;border-radius:8px;background:#20293a;border:2px solid transparent;display:flex;align-items:center;justify-content:center;font-size:20px;cursor:pointer;position:relative}
.slot.active{border-color:#ffd166;background:#32415d;transform:scale(1.08)}
.slot-num{position:absolute;top:2px;left:4px;font-size:10px;color:#aaa}

/* MOBILE CONTROLS */
.controls{display:flex;justify-content:space-between;align-items:flex-end;pointer-events:none;width:100%}
.dpad,.act-btns{display:flex;gap:12px;pointer-events:auto}
.btn-ctl{width:62px;height:62px;border-radius:50%;background:rgba(20,28,45,0.85);border:1.5px solid rgba(255,255,255,0.25);color:#fff;font-size:26px;font-weight:900;display:flex;align-items:center;justify-content:center;box-shadow:0 6px 20px rgba(0,0,0,0.5);touch-action:none}
.btn-ctl:active,.btn-ctl.active{background:#ffb300;color:#111;transform:scale(0.92)}
.btn-ctl.sprint.active{background:#ff1744;color:#fff}

/* CHAT */
.chat-box{position:fixed;left:12px;bottom:90px;width:320px;z-index:11;pointer-events:none}
.chat-logs{max-height:120px;overflow-y:auto;display:flex;flex-direction:column;gap:4px;margin-bottom:6px;text-shadow:0 1px 3px #000}
.chat-msg{font-size:12px;background:rgba(0,0,0,0.4);padding:3px 8px;border-radius:6px;width:fit-content}
.chat-form{display:flex;gap:6px;pointer-events:auto}
.chat-input{flex:1;background:rgba(20,28,45,0.9);border:1px solid #ffffff33;border-radius:8px;padding:8px;color:#fff;outline:none}
</style>
</head>
<body>

<canvas id="game"></canvas>

<div class="hud">
  <div class="top-bar">
    <div class="card">
      <div class="player-name">⚔️ <span id="p-name">Загрузка...</span></div>
      <div class="hp-bar-box"><div id="hp-fill" class="hp-fill"></div></div>
      <div style="font-size:10px;color:#aaa;margin-top:3px" id="online-cnt">Онлайн: 1</div>
    </div>
    
    <div class="card" style="display:flex;gap:8px;align-items:center">
      <button class="btn-audio" onclick="toggleAudio()">🎵 Музыка: Вкл</button>
      <button class="btn-audio" style="background:#4fc3f7" onclick="changeName()">✏️ Имя</button>
    </div>
  </div>

  <div class="hotbar" id="hotbar">
    <div class="slot active" onclick="selectSlot(1)"><span class="slot-num">1</span>⚔️</div>
    <div class="slot" onclick="selectSlot(2)"><span class="slot-num">2</span>⛏️</div>
    <div class="slot" onclick="selectSlot(3)"><span class="slot-num">3</span>🌱</div>
    <div class="slot" onclick="selectSlot(4)"><span class="slot-num">4</span>🟫</div>
    <div class="slot" onclick="selectSlot(5)"><span class="slot-num">5</span>🪙</div>
    <div class="slot" onclick="selectSlot(6)"><span class="slot-num">6</span>🪵</div>
    <div class="slot" onclick="selectSlot(7)"><span class="slot-num">7</span>🕯️</div>
  </div>

  <div class="controls">
    <div class="dpad">
      <div class="btn-ctl" id="btn-left">◀</div>
      <div class="btn-ctl" id="btn-right">▶</div>
      <div class="btn-ctl sprint" id="btn-sprint" style="font-size:16px">⚡БЕГ</div>
    </div>
    <div class="act-btns">
      <div class="btn-ctl" id="btn-mode" style="font-size:18px">⛏️</div>
      <div class="btn-ctl" id="btn-jump">▲</div>
    </div>
  </div>
</div>

<div class="chat-box">
  <div class="chat-logs" id="chat-logs"></div>
  <form class="chat-form" onsubmit="sendChat(event)">
    <input class="chat-input" id="chat-in" placeholder="Написать в чат..." maxlength="120">
  </form>
</div>

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
const socket = io({transports:['websocket','polling']});
const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');

let T = 32, worldW = 350, worldH = 120;
let blocks = new Map();
let players = new Map();
let mobs = new Map();
let myId = null;
let camera = {x:0, y:0};
let worldTime = 0.25;

// Управление
let keyState = {left:false, right:false, jump:false, sprint:false};
let buildMode = 'break'; // break или place
let selectedSlot = 1;
let damageTexts = [];

// Слот -> ИД блока
const slotBlocks = {3:1, 4:2, 5:3, 6:4, 7:7};
const blockColors = {1:'#4caf50', 2:'#795548', 3:'#607d8b', 4:'#5d4037', 5:'#2e7d32', 6:'#a1887f', 7:'#ffb300', 8:'#37474f', 9:'#ffd54f'};

function resize(){
  const d = Math.min(devicePixelRatio || 1, 2);
  canvas.width = innerWidth * d;
  canvas.height = innerHeight * d;
  ctx.setTransform(d, 0, 0, d, 0, 0);
}
addEventListener('resize', resize);
resize();

function k(x,y){return x+','+y}

// --- WEBAUDIO GENSHIN MUSIC ENGINE ---
let audioCtx = None = null;
let audioEnabled = true;

function initAudio(){
  if(audioCtx) return;
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  playGenshinAmbient();
}

function toggleAudio(){
  if(!audioCtx) initAudio();
  audioEnabled = !audioEnabled;
  if(audioCtx){
    if(audioEnabled) audioCtx.resume();
    else audioCtx.suspend();
  }
  document.querySelector('.btn-audio').textContent = audioEnabled ? '🎵 Музыка: Вкл' : '🔇 Музыка: Выкл';
}

// Генерация атмосферной мелодии Геншин Импакт на WebAudio Synthesizer
function playGenshinAmbient(){
  if(!audioCtx) return;
  
  // Пентатоника Геншина (Dorian/Lydian atmospheric scale)
  const notes = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25, 783.99];
  
  function playNote(){
    if(!audioEnabled) { setTimeout(playNote, 2000); return; }
    
    let osc = audioCtx.createOscillator();
    let gain = audioCtx.createGain();
    
    let freq = notes[Math.floor(Math.random() * notes.length)];
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
    
    gain.gain.setValueAtTime(0.001, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.08, audioCtx.currentTime + 0.4);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 3.5);
    
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    
    osc.start();
    osc.stop(audioCtx.currentTime + 3.6);
    
    setTimeout(playNote, 800 + Math.random() * 1600);
  }
  playNote();
}

function playSfx(type){
  if(!audioCtx || !audioEnabled) return;
  let osc = audioCtx.createOscillator();
  let g = audioCtx.createGain();
  osc.connect(g); g.connect(audioCtx.destination);
  let t = audioCtx.currentTime;
  
  if(type === 'jump'){
    osc.frequency.setValueAtTime(150, t);
    osc.frequency.exponentialRampToValueAtTime(400, t + 0.15);
    g.gain.setValueAtTime(0.1, t); g.gain.linearRampToValueAtTime(0, t + 0.15);
    osc.start(t); osc.stop(t + 0.15);
  } else if(type === 'vampire_dash'){
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(400, t);
    osc.frequency.exponentialRampToValueAtTime(80, t + 0.35);
    g.gain.setValueAtTime(0.2, t); g.gain.linearRampToValueAtTime(0, t + 0.35);
    osc.start(t); osc.stop(t + 0.35);
  } else if(type === 'hit'){
    osc.type = 'square';
    osc.frequency.setValueAtTime(120, t);
    g.gain.setValueAtTime(0.15, t); g.gain.linearRampToValueAtTime(0, t + 0.1);
    osc.start(t); osc.stop(t + 0.1);
  }
}

// --- ВВОД И УПРАВЛЕНИЕ (ПК + ТАЧ) ---
function sendInputs(){
  let x = 0;
  if(keyState.left) x -= 1;
  if(keyState.right) x += 1;
  socket.emit('input', {x: x, sprint: keyState.sprint, jump: keyState.jump});
}

setInterval(sendInputs, 40);

// Клавиатура ПК
addEventListener('keydown', e => {
  initAudio();
  if(document.activeElement.id === 'chat-in') return;
  if(e.code==='KeyA'||e.code==='ArrowLeft') keyState.left = true;
  if(e.code==='KeyD'||e.code==='ArrowRight') keyState.right = true;
  if(e.code==='KeyW'||e.code==='Space'||e.code==='ArrowUp'){
    if(!keyState.jump) playSfx('jump');
    keyState.jump = true;
  }
  if(e.shiftKey) keyState.sprint = true;
  
  if(e.key >= '1' && e.key <= '7') selectSlot(parseInt(e.key));
  sendInputs();
});

addEventListener('keyup', e => {
  if(e.code==='KeyA'||e.code==='ArrowLeft') keyState.left = false;
  if(e.code==='KeyD'||e.code==='ArrowRight') keyState.right = false;
  if(e.code==='KeyW'||e.code==='Space'||e.code==='ArrowUp') keyState.jump = false;
  if(!e.shiftKey) keyState.sprint = false;
  sendInputs();
});

// Кнопки на мобильном экранчике
function bindBtn(id, key){
  const el = document.getElementById(id);
  const start = e => {
    e.preventDefault();
    initAudio();
    el.classList.add('active');
    keyState[key] = true;
    if(key==='jump') playSfx('jump');
    sendInputs();
  };
  const end = e => {
    e.preventDefault();
    el.classList.remove('active');
    keyState[key] = false;
    sendInputs();
  };
  el.addEventListener('pointerdown', start);
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
}

bindBtn('btn-left', 'left');
bindBtn('btn-right', 'right');
bindBtn('btn-jump', 'jump');

// Бег на кнопку
const btnSprint = document.getElementById('btn-sprint');
btnSprint.addEventListener('pointerdown', e => {
  e.preventDefault();
  keyState.sprint = !keyState.sprint;
  btnSprint.classList.toggle('active', keyState.sprint);
  sendInputs();
});

document.getElementById('btn-mode').addEventListener('click', () => {
  buildMode = buildMode === 'break' ? 'place' : 'break';
  document.getElementById('btn-mode').textContent = buildMode === 'break' ? '⛏️' : '🧱';
});

function selectSlot(num){
  selectedSlot = num;
  document.querySelectorAll('.slot').forEach((s, idx) => {
    s.classList.toggle('active', idx + 1 === num);
  });
  socket.emit('set_holding', {slot: num});
}

function changeName(){
  const n = prompt('Введите имя героя:', '');
  if(n) socket.emit('set_name', {name: n});
}

function sendChat(e){
  e.preventDefault();
  const input = document.getElementById('chat-in');
  if(input.value.trim()){
    socket.emit('chat', {text: input.value.trim()});
    input.value = '';
  }
}

// Клик по миру (атака мобов или разрушение/постройка)
canvas.addEventListener('pointerdown', e => {
  if(e.target !== canvas) return;
  initAudio();
  const rect = canvas.getBoundingClientRect();
  const clickX = e.clientX - rect.left + camera.x;
  const clickY = e.clientY - rect.top + camera.y;

  // Проверяем клик по мобам для атаки
  let attacked = false;
  mobs.forEach(m => {
    if(clickX >= m.x - 15 && clickX <= m.x + m.w + 15 && clickY >= m.y - 15 && clickY <= m.y + m.h + 15){
      socket.emit('attack_mob', {id: m.id});
      playSfx('hit');
      attacked = true;
    }
  });

  if(!attacked){
    const tx = Math.floor(clickX / T);
    const ty = Math.floor(clickY / T);
    
    if(selectedSlot === 1 || selectedSlot === 2 || buildMode === 'break'){
      socket.emit('edit_block', {x: tx, y: ty, action: 'break'});
    } else {
      const btype = slotBlocks[selectedSlot] || 2;
      socket.emit('edit_block', {x: tx, y: ty, action: 'place', type: btype});
    }
  }
});

// --- SOCKET EVENTS ---
socket.on('init', d => {
  worldW = d.w; worldH = d.h; T = d.tile; myId = d.you_id;
  d.blocks.forEach(b => blocks.set(k(b.x, b.y), b.type));
  d.mobs.forEach(m => mobs.set(m.id, m));
  d.players.forEach(p => players.set(p.id, p));
  d.chat.forEach(addChatMsg);
});

socket.on('state', d => {
  worldTime = d.time;
  mobs.clear();
  d.mobs.forEach(m => mobs.set(m.id, m));
  d.players.forEach(p => players.set(p.id, p));

  const me = players.get(myId);
  if(me){
    document.getElementById('p-name').textContent = me.name;
    document.getElementById('hp-fill').style.width = (me.hp / me.max_hp * 100) + '%';
  }
  document.getElementById('online-cnt').textContent = 'Онлайн: ' + players.size;
});

socket.on('world_patch', b => {
  if(b.type) blocks.set(k(b.x, b.y), b.type);
  else blocks.delete(k(b.x, b.y));
});

socket.on('vampire_dash', d => {
  playSfx('vampire_dash');
  damageTexts.push({x: d.x, y: d.y - 20, text: '⚡ РЫВОК ВАМПИРА!', color: '#ff1744', life: 1.0});
});

socket.on('effect', e => {
  if(e.type === 'damage'){
    damageTexts.push({x: e.x, y: e.y, text: e.val, color: '#ff5252', life: 0.8});
  }
});

socket.on('chat', addChatMsg);
socket.on('notice', i => addChatMsg({name: 'Мир', text: i.text, color: i.color || '#ffd166'}));

function addChatMsg(m){
  const box = document.getElementById('chat-logs');
  const el = document.createElement('div');
  el.className = 'chat-msg';
  el.innerHTML = `<b style="color:${m.color||'#fff'}">${escapeHtml(m.name)}:</b> ${escapeHtml(m.text)}`;
  box.appendChild(el);
  while(box.children.length > 8) box.firstChild.remove();
  box.scrollTop = box.scrollHeight;
}

function escapeHtml(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// --- ОТРИСОВКА И РЕНДЕРИНГ ИГРЫ ---
function draw(){
  const w = innerWidth, h = innerHeight;
  ctx.clearRect(0, 0, w, h);

  // Камера следит за игроком
  const me = players.get(myId);
  if(me){
    camera.x += (me.x + me.w / 2 - w / 2 - camera.x) * 0.1;
    camera.y += (me.y + me.h / 2 - h / 2 - camera.y) * 0.1;
    camera.x = Math.max(0, Math.min(worldW * T - w, camera.x));
    camera.y = Math.max(0, Math.min(worldH * T - h, camera.y));
  }

  // Небо Геншин Импакт (Динамическая смена дня и ночи)
  let skyGrad = ctx.createLinearGradient(0, 0, 0, h);
  if(worldTime >= 0.2 && worldTime <= 0.75){ // День
    skyGrad.addColorStop(0, '#4fc3f7');
    skyGrad.addColorStop(1, '#e1f5fe');
  } else { // Ночь
    skyGrad.addColorStop(0, '#0a0e1a');
    skyGrad.addColorStop(1, '#1a233a');
  }
  ctx.fillStyle = skyGrad;
  ctx.fillRect(0, 0, w, h);

  // Отрисовка блоков мира
  const x0 = Math.floor(camera.x / T) - 1;
  const x1 = Math.ceil((camera.x + w) / T) + 1;
  const y0 = Math.floor(camera.y / T) - 1;
  const y1 = Math.ceil((camera.y + h) / T) + 1;

  for(let y = y0; y <= y1; y++){
    for(let x = x0; x <= x1; x++){
      const b = blocks.get(k(x, y));
      if(!b) continue;

      const px = x * T - camera.x;
      const py = y * T - camera.y;

      ctx.fillStyle = blockColors[b] || '#777';
      ctx.fillRect(px, py, T, T);

      // Красивые контуры блоков
      ctx.strokeStyle = 'rgba(0,0,0,0.15)';
      ctx.strokeRect(px, py, T, T);

      // Шапка травы
      if(b === 1){
        ctx.fillStyle = '#81c784';
        ctx.fillRect(px, py, T, 5);
      }
    }
  }

  // Отрисовка Мобцов и Босса
  mobs.forEach(m => {
    const px = m.x - camera.x;
    const py = m.y - camera.y;

    if(m.type === 'vampire'){
      // ВАМПИР-ЛОРД (СУПЕР БОСС)
      ctx.fillStyle = m.dash_active > 0 ? '#ff1744' : '#800020';
      ctx.fillRect(px, py, m.w, m.h);
      // Плащ
      ctx.fillStyle = '#111';
      ctx.fillRect(px - (m.facing === 1 ? 6 : -2), py + 8, 8, m.h - 8);
      // Светящиеся красные глаза
      ctx.fillStyle = '#ff1744';
      ctx.fillRect(px + (m.facing === 1 ? 16 : 4), py + 8, 5, 4);

      // Аура рывка
      if(m.dash_active > 0){
        ctx.strokeStyle = '#ff1744';
        ctx.lineWidth = 3;
        ctx.strokeRect(px - 6, py - 6, m.w + 12, m.h + 12);
      }
    } else if(m.type === 'zombie'){
      ctx.fillStyle = '#388e3c';
      ctx.fillRect(px, py, m.w, m.h);
      ctx.fillStyle = '#1b5e20';
      ctx.fillRect(px + (m.facing === 1 ? 14 : 2), py + 6, 4, 4);
    } else if(m.type === 'slime'){
      ctx.fillStyle = '#00e676';
      ctx.fillRect(px, py, m.w, m.h);
    } else if(m.type === 'bunny'){
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(px, py, m.w, m.h);
      // Ушки
      ctx.fillRect(px + 2, py - 6, 4, 6);
      ctx.fillRect(px + m.w - 6, py - 6, 4, 6);
    }

    // Полоска HP Моба
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fillRect(px, py - 10, m.w, 5);
    ctx.fillStyle = m.type === 'vampire' ? '#ff1744' : '#4caf50';
    ctx.fillRect(px, py - 10, (m.hp / m.max_hp) * m.w, 5);

    // Имя Моба
    ctx.font = 'bold 10px sans-serif';
    ctx.fillStyle = m.type === 'vampire' ? '#ff1744' : '#fff';
    ctx.textAlign = 'center';
    ctx.fillText(m.name, px + m.w / 2, py - 14);
  });

  // Отрисовка Игроков
  players.forEach(p => {
    if(p.hp <= 0) return;
    const px = p.x - camera.x;
    const py = p.y - camera.y;

    // Тело
    ctx.fillStyle = p.color;
    ctx.fillRect(px, py, p.w, p.h);

    // Голова
    ctx.fillStyle = '#ffcc80';
    ctx.fillRect(px + 3, py + 4, p.w - 6, 12);

    // Глаза
    ctx.fillStyle = '#111';
    const eyeX = p.facing === 1 ? px + p.w - 7 : px + 3;
    ctx.fillRect(eyeX, py + 8, 3, 3);

    // Оружие в руках
    if(p.holding === 1){ // Меч
      ctx.fillStyle = '#e0e0e0';
      const swordX = p.facing === 1 ? px + p.w : px - 12;
      ctx.fillRect(swordX, py + 16, 12, 4);
    }

    // Имя игрока
    ctx.font = 'bold 12px sans-serif';
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.shadowColor = '#000';
    ctx.shadowBlur = 4;
    ctx.fillText(p.name, px + p.w / 2, py - 8);
    ctx.shadowBlur = 0;
  });

  // Всплывающий текст урона
  for(let i = damageTexts.length - 1; i >= 0; i--){
    let dt = damageTexts[i];
    dt.life -= 0.03;
    dt.y -= 0.8;
    ctx.font = '900 16px sans-serif';
    ctx.fillStyle = dt.color;
    ctx.textAlign = 'center';
    ctx.fillText(dt.text, dt.x - camera.x, dt.y - camera.y);
    if(dt.life <= 0) damageTexts.splice(i, 1);
  }

  requestAnimationFrame(draw);
}

draw();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
