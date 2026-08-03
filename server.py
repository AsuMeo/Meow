import asyncio
import websockets
import json
import random
import math
import os

# ============ WORLD ============
WORLD_SIZE = 300
GRAVITY = -30

players = {}
objects = []
next_obj_id = 1

# Generate world objects (stones, crystals)
for i in range(80):
    obj = {
        'id': next_obj_id,
        'type': random.choice(['cube', 'sphere']),
        'x': random.uniform(-WORLD_SIZE/2, WORLD_SIZE/2),
        'y': random.uniform(1, 8),
        'z': random.uniform(-WORLD_SIZE/2, WORLD_SIZE/2),
        'vx': 0, 'vy': 0, 'vz': 0,
        'radius': random.uniform(0.4, 1.2),
        'color': [random.uniform(0.5,1), random.uniform(0.3,0.8), random.uniform(0.2,0.6)],
        'static': False,
        'glow': 0
    }
    next_obj_id += 1
    objects.append(obj)

def get_ground_height(x, z):
    return math.sin(x * 0.03) * 1.5 + math.cos(z * 0.03) * 1.5 + math.sin(x * 0.1 + z * 0.08) * 0.3

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
                obj['vx'] = obj.get('vx', 0) * 0.7
                obj['vz'] = obj.get('vz', 0) * 0.7

async def physics_loop():
    while True:
        update_physics(1/60)
        await asyncio.sleep(1/60)

# ============ WEBSOCKET ============
async def ws_handler(websocket, path):
    pid = id(websocket)
    players[pid] = {
        'ws': websocket,
        'x': random.uniform(-20, 20),
        'y': 5,
        'z': random.uniform(-20, 20),
        'yaw': 0, 'pitch': 0,
        'name': 'Player',
        'last_update': asyncio.get_event_loop().time()
    }

    try:
        await websocket.send(json.dumps({
            'type': 'state',
            'id': pid,
            'players': {k: {kk:vv for kk,vv in v.items() if kk != 'ws'} for k,v in players.items()},
            'objects': objects
        }))

        for p in players.values():
            if p['ws'] != websocket and p['ws'].open:
                try:
                    await p['ws'].send(json.dumps({
                        'type': 'player_join',
                        'id': pid,
                        'data': {k:v for k,v in players[pid].items() if k != 'ws'}
                    }))
                except:
                    pass

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
                    strength = data.get('strength', 15)
                    obj = next((o for o in objects if o['id'] == obj_id), None)
                    if obj:
                        obj['static'] = False
                        obj['vx'] = fx * strength
                        obj['vy'] = fy * strength
                        obj['vz'] = fz * strength
                        obj['glow'] = 0
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

            except:
                pass

    except:
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

# ============ HTTP with embedded HTML ============
from aiohttp import web

HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>Magic World 3D</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:100%; height:100%; overflow:hidden; background:#87CEEB; }
  canvas { display:block; width:100%; height:100%; }
  #ui {
    position:fixed; top:0; left:0; width:100%; height:100%;
    pointer-events:none; z-index:10;
  }
  #joystick {
    position:absolute; bottom:25px; left:25px;
    width:140px; height:140px; pointer-events:auto;
    touch-action:none;
  }
  #joystick-base {
    position:absolute; width:140px; height:140px;
    border-radius:50%; background:rgba(255,255,255,0.15);
    border:3px solid rgba(255,255,255,0.4);
  }
  #joystick-knob {
    position:absolute; width:55px; height:55px;
    border-radius:50%; background:rgba(100,200,255,0.7);
    top:42.5px; left:42.5px;
    box-shadow:0 0 15px rgba(100,200,255,0.5);
  }
  #magic-btn {
    position:absolute; bottom:25px; right:25px;
    width:85px; height:85px; border-radius:50%;
    background:rgba(180,80,255,0.5); border:3px solid rgba(200,100,255,0.8);
    pointer-events:auto; display:flex; align-items:center; justify-content:center;
    color:#fff; font-size:13px; font-family:sans-serif; user-select:none;
    touch-action:none; font-weight:bold;
  }
  #magic-btn.active { background:rgba(220,100,255,0.8); box-shadow:0 0 20px rgba(220,100,255,0.6); }
  #jump-btn {
    position:absolute; bottom:130px; right:30px;
    width:60px; height:60px; border-radius:50%;
    background:rgba(80,200,120,0.5); border:3px solid rgba(100,220,140,0.8);
    pointer-events:auto; display:flex; align-items:center; justify-content:center;
    color:#fff; font-size:20px; font-family:sans-serif; user-select:none;
    touch-action:none;
  }
  #jump-btn:active { background:rgba(80,200,120,0.8); }
  #name-input {
    position:fixed; top:0; left:0; width:100%; height:100%;
    background:linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    z-index:100; pointer-events:auto;
  }
  #name-input h1 {
    color:#fff; font-family:sans-serif; font-size:28px; margin-bottom:30px;
    text-shadow:0 0 20px rgba(100,200,255,0.5);
  }
  #name-input input {
    padding:15px 20px; font-size:20px; border-radius:12px; border:none;
    margin:15px 0; width:250px; text-align:center; background:rgba(255,255,255,0.1);
    color:#fff; outline:none;
  }
  #name-input input::placeholder { color:rgba(255,255,255,0.4); }
  #name-input button {
    padding:15px 50px; font-size:18px; border-radius:12px;
    border:none; background:linear-gradient(135deg, #667eea, #764ba2);
    color:#fff; cursor:pointer; font-weight:bold; margin-top:20px;
    box-shadow:0 5px 20px rgba(102,126,234,0.4);
  }
  #stats {
    position:fixed; top:10px; left:10px;
    color:#0f0; font-family:monospace; font-size:14px;
    text-shadow:0 0 5px #0f0; z-index:10; pointer-events:none;
  }
  #crosshair {
    position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
    width:24px; height:24px; pointer-events:none; z-index:5;
  }
  #crosshair::before, #crosshair::after {
    content:''; position:absolute; background:rgba(255,255,255,0.7);
  }
  #crosshair::before { width:2px; height:24px; left:11px; top:0; }
  #crosshair::after { width:24px; height:2px; left:0; top:11px; }
  #magic-indicator {
    position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
    width:40px; height:40px; border-radius:50%;
    border:2px solid rgba(200,100,255,0.8); pointer-events:none;
    opacity:0; transition:opacity 0.2s; z-index:6;
  }
  #magic-indicator.active { opacity:1; }
</style>
</head>
<body>
<div id="name-input">
  <h1>✨ Magic World 3D</h1>
  <input type="text" id="nick" placeholder="Твоё имя" maxlength="12" value="Player">
  <button onclick="startGame()">🎮 ИГРАТЬ</button>
</div>

<div id="ui" style="display:none;">
  <div id="stats">Онлайн: 1 | Пинг: -- | FPS: --</div>
  <div id="crosshair"></div>
  <div id="magic-indicator"></div>
  <div id="joystick">
    <div id="joystick-base"></div>
    <div id="joystick-knob"></div>
  </div>
  <div id="jump-btn">⬆</div>
  <div id="magic-btn">✨ МАГИЯ</div>
</div>

<canvas id="gl"></canvas>

<script>
// ============ CONFIG ============
const WS_URL = (location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws';
const WORLD_SIZE = 300;
const CHUNK_SIZE = 15;
const GRAVITY = -30;
const PLAYER_SPEED = 6;
const JUMP_FORCE = 12;

let canvas, gl, ws, playerId, players = {}, worldObjects = [], myName = '';
let cam = { x:0, y:5, z:0, yaw:0, pitch:0 };
let vel = { x:0, y:0, z:0 };
let onGround = false;
let joy = { active:false, dx:0, dy:0, originX:0, originY:0 };
let magic = { active:false, holding:false, targetObj:null };
let lastTime = 0, ping = 0, pingStart = 0, frameCount = 0, fps = 60;
let inputState = { forward:0, right:0, jump:false };
let lookTouchId = null, joyTouchId = null;

// ============ WEBGL ============
const vs = `
attribute vec3 aPos;
attribute vec3 aNorm;
uniform mat4 uMVP;
uniform mat4 uModel;
varying vec3 vNorm;
varying vec3 vPos;
varying float vDist;
void main(){
  vec4 wp = uModel * vec4(aPos,1.0);
  vPos = wp.xyz;
  vNorm = mat3(uModel) * aNorm;
  vDist = length(wp.xz);
  gl_Position = uMVP * vec4(aPos,1.0);
}`;

const fs = `
precision mediump float;
varying vec3 vNorm;
varying vec3 vPos;
varying float vDist;
uniform vec3 uColor;
uniform vec3 uLightDir;
uniform float uGlow;
uniform vec3 uSunColor;
void main(){
  vec3 N = normalize(vNorm);
  vec3 L = normalize(uLightDir);
  float diff = max(dot(N,L), 0.15);
  vec3 ambient = uColor * 0.3;
  vec3 lit = uColor * diff * uSunColor + ambient;
  if(uGlow > 0.0) lit += vec3(0.5,0.2,0.8) * uGlow;
  float fog = clamp(1.0 - vDist/120.0, 0.0, 1.0);
  vec3 sky = vec3(0.53,0.81,0.92);
  vec3 final = mix(sky * 0.3, lit, fog);
  gl_FragColor = vec4(final, 1.0);
}`;

let prog, aPos, aNorm, uMVP, uModel, uColor, uLightDir, uGlow, uSunColor;
let cubeBuf, sphereBuf;

function mat4() { return new Float32Array(16); }
function identity(m) {
  m[0]=1;m[1]=0;m[2]=0;m[3]=0; m[4]=0;m[5]=1;m[6]=0;m[7]=0;
  m[8]=0;m[9]=0;m[10]=1;m[11]=0; m[12]=0;m[13]=0;m[14]=0;m[15]=1;
  return m;
}
function perspective(m, fov, aspect, near, far) {
  const f = 1.0 / Math.tan(fov/2);
  const nf = 1 / (near - far);
  m[0]=f/aspect;m[1]=0;m[2]=0;m[3]=0;
  m[4]=0;m[5]=f;m[6]=0;m[7]=0;
  m[8]=0;m[9]=0;m[10]=(far+near)*nf;m[11]=-1;
  m[12]=0;m[13]=0;m[14]=2*far*near*nf;m[15]=0;
  return m;
}
function translate(m, x,y,z) {
  m[12]+=m[0]*x+m[4]*y+m[8]*z;
  m[13]+=m[1]*x+m[5]*y+m[9]*z;
  m[14]+=m[2]*x+m[6]*y+m[10]*z;
  m[15]+=m[3]*x+m[7]*y+m[11]*z;
  return m;
}
function rotateY(m, a) {
  const c=Math.cos(a), s=Math.sin(a);
  const a0=m[0],a4=m[4],a8=m[8],a12=m[12];
  m[0]=a0*c+m[2]*s; m[4]=a4*c+m[6]*s; m[8]=a8*c+m[10]*s; m[12]=a12*c+m[14]*s;
  m[2]=-a0*s+m[2]*c; m[6]=-a4*s+m[6]*c; m[10]=-a8*s+m[10]*c; m[14]=-a12*s+m[14]*c;
  return m;
}
function rotateX(m, a) {
  const c=Math.cos(a), s=Math.sin(a);
  const a1=m[1],a5=m[5],a9=m[9],a13=m[13];
  m[1]=a1*c+m[2]*s; m[5]=a5*c+m[6]*s; m[9]=a9*c+m[10]*s; m[13]=a13*c+m[14]*s;
  m[2]=-a1*s+m[2]*c; m[6]=-a5*s+m[6]*c; m[10]=-a9*s+m[10]*c; m[14]=-a13*s+m[14]*c;
  return m;
}
function scale3(m, sx,sy,sz) {
  m[0]*=sx; m[1]*=sx; m[2]*=sx; m[3]*=sx;
  m[4]*=sy; m[5]*=sy; m[6]*=sy; m[7]*=sy;
  m[8]*=sz; m[9]*=sz; m[10]*=sz; m[11]*=sz;
  return m;
}
function multiply(out, a, b) {
  const a00=a[0],a01=a[1],a02=a[2],a03=a[3];
  const a10=a[4],a11=a[5],a12=a[6],a13=a[7];
  const a20=a[8],a21=a[9],a22=a[10],a23=a[11];
  const a30=a[12],a31=a[13],a32=a[14],a33=a[15];
  let b0=b[0],b1=b[1],b2=b[2],b3=b[3];
  out[0]=b0*a00+b1*a10+b2*a20+b3*a30;
  out[1]=b0*a01+b1*a11+b2*a21+b3*a31;
  out[2]=b0*a02+b1*a12+b2*a22+b3*a32;
  out[3]=b0*a03+b1*a13+b2*a23+b3*a33;
  b0=b[4];b1=b[5];b2=b[6];b3=b[7];
  out[4]=b0*a00+b1*a10+b2*a20+b3*a30;
  out[5]=b0*a01+b1*a11+b2*a21+b3*a31;
  out[6]=b0*a02+b1*a12+b2*a22+b3*a32;
  out[7]=b0*a03+b1*a13+b2*a23+b3*a33;
  b0=b[8];b1=b[9];b2=b[10];b3=b[11];
  out[8]=b0*a00+b1*a10+b2*a20+b3*a30;
  out[9]=b0*a01+b1*a11+b2*a21+b3*a31;
  out[10]=b0*a02+b1*a12+b2*a22+b3*a32;
  out[11]=b0*a03+b1*a13+b2*a23+b3*a33;
  b0=b[12];b1=b[13];b2=b[14];b3=b[15];
  out[12]=b0*a00+b1*a10+b2*a20+b3*a30;
  out[13]=b0*a01+b1*a11+b2*a21+b3*a31;
  out[14]=b0*a02+b1*a12+b2*a22+b3*a32;
  out[15]=b0*a03+b1*a13+b2*a23+b3*a33;
  return out;
}

function compileShader(type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  return s;
}

function makeCube() {
  const verts=[], norms=[], inds=[];
  const faces=[[0,0,1],[0,0,-1],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0]];
  let vi=0;
  for(let f=0;f<6;f++){
    const n=faces[f];
    let ax=[0,0,0],ay=[0,0,0];
    if(Math.abs(n[2])>0.5){ax=[1,0,0];ay=[0,1,0];}
    else if(Math.abs(n[0])>0.5){ax=[0,0,1];ay=[0,1,0];}
    else{ax=[1,0,0];ay=[0,0,1];}
    const c=[n[0]*0.5,n[1]*0.5,n[2]*0.5];
    for(let i=0;i<4;i++){
      const sx=(i&1)?0.5:-0.5, sy=(i&2)?0.5:-0.5;
      verts.push(c[0]+ax[0]*sx+ay[0]*sy, c[1]+ax[1]*sx+ay[1]*sy, c[2]+ax[2]*sx+ay[2]*sy);
      norms.push(n[0],n[1],n[2]);
    }
    inds.push(vi,vi+1,vi+2, vi+1,vi+3,vi+2);
    vi+=4;
  }
  return{v:new Float32Array(verts),n:new Float32Array(norms),i:new Uint16Array(inds),count:36};
}

function makeSphere(segs){
  const verts=[], norms=[], inds=[];
  for(let lat=0;lat<=segs;lat++){
    const theta=lat*Math.PI/segs, sinT=Math.sin(theta), cosT=Math.cos(theta);
    for(let lon=0;lon<=segs;lon++){
      const phi=lon*2*Math.PI/segs, sinP=Math.sin(phi), cosP=Math.cos(phi);
      const x=cosP*sinT, y=cosT, z=sinP*sinT;
      verts.push(x,y,z); norms.push(x,y,z);
    }
  }
  for(let lat=0;lat<segs;lat++){
    for(let lon=0;lon<segs;lon++){
      const a=lat*(segs+1)+lon, b=a+segs+1;
      inds.push(a,b,a+1, b,b+1,a+1);
    }
  }
  return{v:new Float32Array(verts),n:new Float32Array(norms),i:new Uint16Array(inds),count:inds.length};
}

function uploadBuf(data,type){
  const b=gl.createBuffer();
  gl.bindBuffer(type,b);
  gl.bufferData(type,data,gl.STATIC_DRAW);
  return b;
}

function initGL(){
  canvas=document.getElementById('gl');
  gl=canvas.getContext('webgl',{antialias:false,alpha:false});
  if(!gl){alert('WebGL не поддерживается');return;}
  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.CULL_FACE);
  gl.clearColor(0.53,0.81,0.92,1);

  prog=gl.createProgram();
  gl.attachShader(prog,compileShader(gl.VERTEX_SHADER,vs));
  gl.attachShader(prog,compileShader(gl.FRAGMENT_SHADER,fs));
  gl.linkProgram(prog);
  gl.useProgram(prog);

  aPos=gl.getAttribLocation(prog,'aPos');
  aNorm=gl.getAttribLocation(prog,'aNorm');
  uMVP=gl.getUniformLocation(prog,'uMVP');
  uModel=gl.getUniformLocation(prog,'uModel');
  uColor=gl.getUniformLocation(prog,'uColor');
  uLightDir=gl.getUniformLocation(prog,'uLightDir');
  uGlow=gl.getUniformLocation(prog,'uGlow');
  uSunColor=gl.getUniformLocation(prog,'uSunColor');

  cubeBuf=makeCube();
  cubeBuf.vb=uploadBuf(cubeBuf.v,gl.ARRAY_BUFFER);
  cubeBuf.nb=uploadBuf(cubeBuf.n,gl.ARRAY_BUFFER);
  cubeBuf.ib=uploadBuf(cubeBuf.i,gl.ELEMENT_ARRAY_BUFFER);

  sphereBuf=makeSphere(10);
  sphereBuf.vb=uploadBuf(sphereBuf.v,gl.ARRAY_BUFFER);
  sphereBuf.nb=uploadBuf(sphereBuf.n,gl.ARRAY_BUFFER);
  sphereBuf.ib=uploadBuf(sphereBuf.i,gl.ELEMENT_ARRAY_BUFFER);
}

function drawMesh(buf,model,color,glow){
  const proj=mat4(); perspective(proj,Math.PI/3,canvas.width/canvas.height,0.1,300);
  const view=mat4(); identity(view);
  rotateX(view,cam.pitch); rotateY(view,cam.yaw);
  translate(view,-cam.x,-cam.y,-cam.z);
  const mvp=mat4(); multiply(mvp,proj,view);
  multiply(mvp,mvp,model);

  gl.uniformMatrix4fv(uMVP,false,mvp);
  gl.uniformMatrix4fv(uModel,false,model);
  gl.uniform3f(uColor,color[0],color[1],color[2]);
  gl.uniform3f(uLightDir,0.3,-0.8,0.2);
  gl.uniform1f(uGlow,glow||0);
  gl.uniform3f(uSunColor,1.0,0.95,0.8);

  gl.bindBuffer(gl.ARRAY_BUFFER,buf.vb);
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,buf.nb);
  gl.enableVertexAttribArray(aNorm);
  gl.vertexAttribPointer(aNorm,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,buf.ib);
  gl.drawElements(gl.TRIANGLES,buf.count,gl.UNSIGNED_SHORT,0);
}

// ============ WORLD ============
function getGroundHeight(x,z){
  return Math.sin(x*0.03)*1.5+Math.cos(z*0.03)*1.5+Math.sin(x*0.1+z*0.08)*0.3;
}

const chunkCache={};
function getChunk(cx,cz){
  const key=cx+","+cz;
  if(chunkCache[key])return chunkCache[key];
  const seed=(cx*73856093)^(cz*19349663);
  const hasTree=(seed%7)===0;
  const hasRock=(seed%11)===3;
  const hasFlower=(seed%5)===1;
  chunkCache[key]={hasTree,hasRock,hasFlower,seed};
  return chunkCache[key];
}

function drawWorld(){
  const chunkX=Math.floor(cam.x/CHUNK_SIZE);
  const chunkZ=Math.floor(cam.z/CHUNK_SIZE);
  for(let cx=chunkX-4;cx<=chunkX+4;cx++){
    for(let cz=chunkZ-4;cz<=chunkZ+4;cz++){
      const chunk=getChunk(cx,cz);
      const baseX=cx*CHUNK_SIZE, baseZ=cz*CHUNK_SIZE;
      // Ground tiles
      for(let i=0;i<3;i++){
        for(let j=0;j<3;j++){
          const px=baseX+i*5, pz=baseZ+j*5;
          const h=getGroundHeight(px,pz);
          const m=mat4(); identity(m);
          translate(m,px,h-0.5,pz);
          scale3(m,5,1,5);
          const g=0.25+Math.sin(px*0.1)*0.08;
          const grassColor=[g*0.6, 0.5+g*0.4, g*0.3];
          drawMesh(cubeBuf,m,grassColor,0);
          // Dirt below
          const dirt=mat4(); identity(dirt);
          translate(dirt,px,h-2,pz);
          scale3(dirt,5,2,5);
          drawMesh(cubeBuf,dirt,[0.4,0.3,0.2],0);
        }
      }
      // Tree
      if(chunk.hasTree){
        const tx=baseX+7, tz=baseZ+8;
        const th=getGroundHeight(tx,tz);
        const trunk=mat4(); identity(trunk);
        translate(trunk,tx,th+2,tz);
        scale3(trunk,0.5,4,0.5);
        drawMesh(cubeBuf,trunk,[0.45,0.3,0.15],0);
        // Leaves
        for(let ly=0;ly<3;ly++){
          const leaves=mat4(); identity(leaves);
          translate(leaves,tx,th+5+ly*0.8,tz);
          const ls=2.5-ly*0.5;
          scale3(leaves,ls,ls*0.6,ls);
          drawMesh(sphereBuf,leaves,[0.15,0.55+ly*0.05,0.15],0);
        }
      }
      // Rock
      if(chunk.hasRock){
        const rx=baseX+12, rz=baseZ+5;
        const rh=getGroundHeight(rx,rz);
        const rock=mat4(); identity(rock);
        translate(rock,rx,rh+0.6,rz);
        scale3(rock,1.5,1,1.5);
        drawMesh(cubeBuf,rock,[0.5,0.5,0.52],0);
      }
      // Flowers
      if(chunk.hasFlower){
        const fx=baseX+3, fz=baseZ+11;
        const fh=getGroundHeight(fx,fz);
        const flower=mat4(); identity(flower);
        translate(flower,fx,fh+0.3,fz);
        scale3(flower,0.15,0.3,0.15);
        drawMesh(cubeBuf,flower,[0.9,0.2,0.3],0);
      }
    }
  }
}

function drawSun(){
  const m=mat4(); identity(m);
  translate(m,cam.x+50,80,cam.z-30);
  scale3(m,8,8,8);
  drawMesh(sphereBuf,m,[1.0,0.9,0.4],0.3);
}

function drawPlayer(p,isMe){
  if(isMe)return;
  const col=[1.0,0.3,0.2];
  // Body
  const body=mat4(); identity(body);
  translate(body,p.x,p.y+0.8,p.z);
  scale3(body,0.5,1.2,0.3);
  drawMesh(cubeBuf,body,col,0);
  // Head
  const head=mat4(); identity(head);
  translate(head,p.x,p.y+1.8,p.z);
  scale3(head,0.3,0.3,0.3);
  drawMesh(sphereBuf,head,[0.9,0.8,0.7],0);
}

function drawObjects(){
  for(const obj of worldObjects){
    const m=mat4(); identity(m);
    translate(m,obj.x,obj.y,obj.z);
    const s=obj.radius||0.5;
    scale3(m,s,s,s);
    const glow=obj.glow||0;
    if(obj.type==='sphere'){
      drawMesh(sphereBuf,m,obj.color||[0.8,0.6,0.2],glow);
    }else{
      drawMesh(cubeBuf,m,obj.color||[0.6,0.6,0.6],glow);
    }
  }
}

// ============ PHYSICS ============
function updatePhysics(dt){
  const speed=PLAYER_SPEED;
  const fy=Math.sin(cam.yaw), fx=Math.cos(cam.yaw);
  vel.x=(inputState.forward*fy+inputState.right*fx)*speed;
  vel.z=(inputState.forward*fx-inputState.right*fy)*speed;

  if(inputState.jump&&onGround){
    vel.y=JUMP_FORCE;
    onGround=false;
    inputState.jump=false;
  }

  vel.y+=GRAVITY*dt;
  cam.x+=vel.x*dt;
  cam.y+=vel.y*dt;
  cam.z+=vel.z*dt;

  const gh=getGroundHeight(cam.x,cam.z);
  if(cam.y<gh+1.7){
    cam.y=gh+1.7;
    vel.y=0;
    onGround=true;
  }else{
    onGround=false;
  }

  for(const obj of worldObjects){
    if(!obj.static){
      obj.vy=(obj.vy||0)+GRAVITY*dt;
      obj.x+=(obj.vx||0)*dt;
      obj.y+=obj.vy*dt;
      obj.z+=(obj.vz||0)*dt;
      const ogh=getGroundHeight(obj.x,obj.z);
      if(obj.y<ogh+(obj.radius||0.5)){
        obj.y=ogh+(obj.radius||0.5);
        obj.vy=0;
        obj.vx=(obj.vx||0)*0.7;
        obj.vz=(obj.vz||0)*0.7;
      }
    }
  }
}

// ============ INPUT ============
function setupInput(){
  const joyEl=document.getElementById('joystick');
  const knob=document.getElementById('joystick-knob');
  const magicBtn=document.getElementById('magic-btn');
  const jumpBtn=document.getElementById('jump-btn');

  // JOYSTICK
  joyEl.addEventListener('touchstart',e=>{
    e.preventDefault();
    if(e.touches.length>0){
      const t=e.touches[0];
      joyTouchId=t.identifier;
      const rect=joyEl.getBoundingClientRect();
      joy.active=true;
      joy.originX=rect.left+70;
      joy.originY=rect.top+70;
    }
  },{passive:false});

  document.addEventListener('touchmove',e=>{
    for(let i=0;i<e.changedTouches.length;i++){
      const t=e.changedTouches[i];
      if(t.identifier===joyTouchId&&joy.active){
        e.preventDefault();
        let dx=t.clientX-joy.originX;
        let dy=t.clientY-joy.originY;
        const dist=Math.sqrt(dx*dx+dy*dy);
        const maxDist=50;
        if(dist>maxDist){dx=dx/dist*maxDist;dy=dy/dist*maxDist;}
        knob.style.transform='translate('+dx+'px,'+dy+'px)';
        joy.dx=dx/maxDist;
        joy.dy=dy/maxDist;
        inputState.forward=-joy.dy;
        inputState.right=joy.dx;
      }
    }
  },{passive:false});

  document.addEventListener('touchend',e=>{
    for(let i=0;i<e.changedTouches.length;i++){
      if(e.changedTouches[i].identifier===joyTouchId){
        joy.active=false;
        joyTouchId=null;
        knob.style.transform='translate(0,0)';
        inputState.forward=0;
        inputState.right=0;
      }
    }
  });

  // LOOK (right side of screen)
  document.addEventListener('touchstart',e=>{
    for(let i=0;i<e.changedTouches.length;i++){
      const t=e.changedTouches[i];
      if(t.identifier!==joyTouchId&&t.clientX>window.innerWidth*0.35&&t.clientY<window.innerHeight-180){
        lookTouchId=t.identifier;
      }
    }
  },{passive:false});

  let lastLookX=0,lastLookY=0;
  document.addEventListener('touchmove',e=>{
    for(let i=0;i<e.changedTouches.length;i++){
      const t=e.changedTouches[i];
      if(t.identifier===lookTouchId){
        e.preventDefault();
        const sens=0.004;
        if(lastLookX!==0){
          cam.yaw+=(t.clientX-lastLookX)*sens;
          cam.pitch+=(t.clientY-lastLookY)*sens;
          cam.pitch=Math.max(-1.4,Math.min(1.4,cam.pitch));
        }
        lastLookX=t.clientX;
        lastLookY=t.clientY;
      }
    }
  },{passive:false});

  document.addEventListener('touchend',e=>{
    for(let i=0;i<e.changedTouches.length;i++){
      if(e.changedTouches[i].identifier===lookTouchId){
        lookTouchId=null;
        lastLookX=0;
        lastLookY=0;
      }
    }
  });

  // JUMP
  jumpBtn.addEventListener('touchstart',e=>{
    e.preventDefault();
    if(onGround) inputState.jump=true;
  },{passive:false});

  // MAGIC
  magicBtn.addEventListener('touchstart',e=>{
    e.preventDefault();
    magic.active=true;
    magicBtn.classList.add('active');
    document.getElementById('magic-indicator').classList.add('active');
    // Find object in crosshair
    const fwd=[Math.sin(cam.yaw)*Math.cos(cam.pitch),-Math.sin(cam.pitch),Math.cos(cam.yaw)*Math.cos(cam.pitch)];
    let best=null,bestDist=999;
    for(const obj of worldObjects){
      const dx=obj.x-cam.x,dy=obj.y-cam.y,dz=obj.z-cam.z;
      const dist=Math.sqrt(dx*dx+dy*dy+dz*dz);
      if(dist>25||dist<1)continue;
      const dot=(dx*fwd[0]+dy*fwd[1]+dz*fwd[2])/dist;
      if(dot>0.92&&dist<bestDist){best=obj;bestDist=dist;}
    }
    if(best){
      magic.holding=true;
      magic.targetObj=best;
      best.static=true;
      best.glow=1;
      if(ws&&ws.readyState===1){
        ws.send(JSON.stringify({type:'magic_hold',obj_id:best.id}));
      }
    }
  },{passive:false});

  magicBtn.addEventListener('touchend',e=>{
    e.preventDefault();
    magicBtn.classList.remove('active');
    document.getElementById('magic-indicator').classList.remove('active');
    if(magic.holding&&magic.targetObj){
      magic.targetObj.static=false;
      magic.targetObj.glow=0;
      // Flick force
      const fwd=[Math.sin(cam.yaw)*Math.cos(cam.pitch),-Math.sin(cam.pitch)+0.3,Math.cos(cam.yaw)*Math.cos(cam.pitch)];
      const strength=12;
      magic.targetObj.vx=fwd[0]*strength;
      magic.targetObj.vy=fwd[1]*strength;
      magic.targetObj.vz=fwd[2]*strength;
      if(ws&&ws.readyState===1){
        ws.send(JSON.stringify({
          type:'magic_flick',obj_id:magic.targetObj.id,
          fx:fwd[0],fy:fwd[1],fz:fwd[2],strength:strength
        }));
      }
      magic.targetObj=null;
    }
    magic.active=false;
    magic.holding=false;
  });
}

// ============ NETWORK ============
function connectWS(){
  ws=new WebSocket(WS_URL);
  ws.onopen=()=>{
    ws.send(JSON.stringify({type:'join',name:myName}));
    setInterval(()=>{
      pingStart=Date.now();
      ws.send(JSON.stringify({type:'ping'}));
    },2000);
  };
  ws.onmessage=e=>{
    const msg=JSON.parse(e.data);
    if(msg.type==='state'){
      playerId=msg.id;
      if(msg.players){
        for(const id in msg.players){
          if(id!=playerId) players[id]=msg.players[id];
        }
      }
      if(msg.objects) worldObjects=msg.objects;
    }else if(msg.type==='player_join'){
      players[msg.id]=msg.data;
    }else if(msg.type==='player_leave'){
      delete players[msg.id];
    }else if(msg.type==='player_update'){
      if(msg.id!=playerId) players[msg.id]=msg.data;
    }else if(msg.type==='object_update'){
      const obj=worldObjects.find(o=>o.id===msg.id);
      if(obj){obj.x=msg.x;obj.y=msg.y;obj.z=msg.z;obj.vx=msg.vx;obj.vy=msg.vy;obj.vz=msg.vz;}
    }else if(msg.type==='pong'){
      ping=Date.now()-pingStart;
    }
  };
  ws.onclose=()=>{setTimeout(connectWS,3000);};
}

function sendState(){
  if(ws&&ws.readyState===1){
    ws.send(JSON.stringify({
      type:'update',
      x:cam.x,y:cam.y,z:cam.z,
      yaw:cam.yaw,pitch:cam.pitch
    }));
  }
}

// ============ MAIN LOOP ============
let lastSend=0;
function render(time){
  const dt=Math.min((time-lastTime)/1000,0.05);
  lastTime=time;
  frameCount++;
  if(frameCount%30===0) fps=Math.round(1000/dt/30);

  canvas.width=window.innerWidth;
  canvas.height=window.innerHeight;
  gl.viewport(0,0,canvas.width,canvas.height);
  gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);

  updatePhysics(dt);
  drawWorld();
  drawSun();
  for(const id in players) drawPlayer(players[id],false);
  drawObjects();

  if(time-lastSend>50){sendState();lastSend=time;}

  document.getElementById('stats').textContent=
    'Онлайн: '+(Object.keys(players).length+1)+' | Пинг: '+ping+'ms | FPS: '+fps;

  requestAnimationFrame(render);
}

// ============ AUDIO ============
let audioCtx, bgmOsc, bgmGain;
function initAudio(){
  audioCtx=new(window.AudioContext||window.webkitAudioContext)();
  // Simple ambient pad (Genshin-like)
  const freqs=[261.63,329.63,392.00,523.25];
  bgmGain=audioCtx.createGain();
  bgmGain.gain.value=0.03;
  bgmGain.connect(audioCtx.destination);

  freqs.forEach((f,i)=>{
    const osc=audioCtx.createOscillator();
    osc.type='sine';
    osc.frequency.value=f;
    const g=audioCtx.createGain();
    g.gain.value=0.3;
    osc.connect(g);
    g.connect(bgmGain);
    osc.start();
    // LFO for ambient feel
    const lfo=audioCtx.createOscillator();
    lfo.type='sine';
    lfo.frequency.value=0.1+i*0.05;
    const lfoGain=audioCtx.createGain();
    lfoGain.gain.value=0.1;
    lfo.connect(lfoGain);
    lfoGain.connect(g.gain);
    lfo.start();
  });
}

function startGame(){
  myName=document.getElementById('nick').value||'Player';
  document.getElementById('name-input').style.display='none';
  document.getElementById('ui').style.display='block';
  initGL();
  setupInput();
  initAudio();
  connectWS();
  requestAnimationFrame(render);
}
</script>
</body>
</html>"""

async def index_handler(request):
    return web.Response(text=HTML_PAGE, content_type='text/html')

async def start_servers():
    app = web.Application()
    app.router.add_get('/', index_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'HTTP server on port {port}')

    ws_server = await websockets.serve(ws_handler, '0.0.0.0', port)
    print(f'WS server on port {port}')

    await physics_loop()

if __name__ == '__main__':
    asyncio.run(start_servers())
