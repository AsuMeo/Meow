import asyncio
import websockets
import json
import random
import math
import os

# ============ WORLD ============
WORLD_SIZE = 200
GRAVITY = -25

players = {}
objects = []
next_obj_id = 1

# Generate world objects
for i in range(50):
    obj = {
        'id': next_obj_id,
        'type': 'cube' if random.random() > 0.3 else 'sphere',
        'x': random.uniform(-WORLD_SIZE/2, WORLD_SIZE/2),
        'y': random.uniform(2, 10),
        'z': random.uniform(-WORLD_SIZE/2, WORLD_SIZE/2),
        'vx': 0, 'vy': 0, 'vz': 0,
        'radius': random.uniform(0.3, 1.0),
        'color': [random.random(), random.random(), random.random()],
        'static': False,
        'glow': 0
    }
    next_obj_id += 1
    objects.append(obj)

def get_ground_height(x, z):
    return math.sin(x * 0.05) * 2 + math.cos(z * 0.05) * 2 + math.sin(x * 0.2 + z * 0.15) * 0.5

def update_physics(dt):
    for obj in objects:
        if not obj.get('static', False):
            obj['vy'] = obj.get('vy', 0) + GRAVITY * dt
            obj['x'] += obj.get('vx', 0) * dt
            obj['y'] += obj['vy'] * dt
            obj['z'] += obj.get('vz', 0) * dt
            gh = get_ground_height(obj['x'], obj['z'])
            if obj['y'] < gh + obj.get('radius', 0.5):
                obj['y'] = gh + obj.get('radius', 0.5)
                obj['vy'] = 0
                obj['vx'] = obj.get('vx', 0) * 0.8
                obj['vz'] = obj.get('vz', 0) * 0.8

async def physics_loop():
    while True:
        update_physics(1/60)
        await asyncio.sleep(1/60)

# ============ WEBSOCKET ============
async def handler(websocket, path):
    pid = id(websocket)
    players[pid] = {
        'ws': websocket,
        'x': 0, 'y': 5, 'z': 0,
        'yaw': 0, 'pitch': 0,
        'name': 'Player',
        'last_update': asyncio.get_event_loop().time()
    }

    try:
        # Send initial state
        await websocket.send(json.dumps({
            'type': 'state',
            'id': pid,
            'players': {k: {kk:vv for kk,vv in v.items() if kk != 'ws'} for k,v in players.items()},
            'objects': objects
        }))

        # Notify others
        for p in players.values():
            if p['ws'] != websocket and p['ws'].open:
                await p['ws'].send(json.dumps({
                    'type': 'player_join',
                    'id': pid,
                    'data': {k:v for k,v in players[pid].items() if k != 'ws'}
                }))

        async for msg in websocket:
            try:
                data = json.loads(msg)

                if data['type'] == 'join':
                    players[pid]['name'] = data.get('name', 'Player')

                elif data['type'] == 'update':
                    players[pid]['x'] = data.get('x', players[pid]['x'])
                    players[pid]['y'] = data.get('y', players[pid]['y'])
                    players[pid]['z'] = data.get('z', players[pid]['z'])
                    players[pid]['yaw'] = data.get('yaw', players[pid]['yaw'])
                    players[pid]['pitch'] = data.get('pitch', players[pid]['pitch'])
                    players[pid]['last_update'] = asyncio.get_event_loop().time()

                    # Broadcast to others
                    broadcast = json.dumps({
                        'type': 'player_update',
                        'id': pid,
                        'data': {k:v for k,v in players[pid].items() if k != 'ws'}
                    })
                    for p in players.values():
                        if p['ws'] != websocket and p['ws'].open:
                            try:
                                await p['ws'].send(broadcast)
                            except:
                                pass

                elif data['type'] == 'magic_flick':
                    obj_id = data.get('obj_id')
                    fx, fy, fz = data.get('fx', 0), data.get('fy', 0), data.get('fz', 0)
                    strength = data.get('strength', 10)
                    obj = next((o for o in objects if o['id'] == obj_id), None)
                    if obj:
                        obj['static'] = False
                        obj['vx'] = fx * strength
                        obj['vy'] = fy * strength
                        obj['vz'] = fz * strength
                        obj['glow'] = 0
                        # Broadcast
                        broadcast = json.dumps({
                            'type': 'object_update',
                            'id': obj_id,
                            'x': obj['x'], 'y': obj['y'], 'z': obj['z'],
                            'vx': obj['vx'], 'vy': obj['vy'], 'vz': obj['vz']
                        })
                        for p in players.values():
                            if p['ws'].open:
                                try:
                                    await p['ws'].send(broadcast)
                                except:
                                    pass

                elif data['type'] == 'magic_hold':
                    obj_id = data.get('obj_id')
                    obj = next((o for o in objects if o['id'] == obj_id), None)
                    if obj:
                        obj['static'] = True
                        obj['glow'] = 1

                elif data['type'] == 'magic_move':
                    obj_id = data.get('obj_id')
                    obj = next((o for o in objects if o['id'] == obj_id), None)
                    if obj and obj.get('static'):
                        obj['x'] = data.get('x', obj['x'])
                        obj['y'] = data.get('y', obj['y'])
                        obj['z'] = data.get('z', obj['z'])

                elif data['type'] == 'ping':
                    await websocket.send(json.dumps({'type': 'pong'}))

            except json.JSONDecodeError:
                pass

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if pid in players:
            del players[pid]
        for p in players.values():
            if p['ws'].open:
                try:
                    await p['ws'].send(json.dumps({'type': 'player_leave', 'id': pid}))
                except:
                    pass

# ============ HTTP ============
from aiohttp import web

async def index_handler(request):
    with open('index.html', 'r', encoding='utf-8') as f:
        return web.Response(text=f.read(), content_type='text/html')

async def start_servers():
    app = web.Application()
    app.router.add_get('/', index_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
    await site.start()
    print(f'HTTP server started on port {os.environ.get("PORT", 8080)}')

    ws_server = await websockets.serve(handler, '0.0.0.0', int(os.environ.get('PORT', 8080))+1)
    print(f'WS server started on port {int(os.environ.get("PORT", 8080))+1}')

    await physics_loop()

if __name__ == '__main__':
    asyncio.run(start_servers())
