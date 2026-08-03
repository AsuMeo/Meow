from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
import os, json, zipfile, io, base64, tempfile, shutil, subprocess, sys, math
from pathlib import Path
import numpy as np
import cv2
from scipy.spatial import cKDTree

app = FastAPI()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>Memento — Пространственная запись</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
  background:#020204; color:#e0e0e5;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  overflow:hidden; touch-action:none;
}
#app { height:100vh; display:flex; flex-direction:column; }

/* RECORD */
#recordScreen { flex:1; display:flex; flex-direction:column; position:relative; }
#videoPreview {
  position:absolute; top:0; left:0; width:100%; height:100%;
  object-fit:cover; opacity:0.5; z-index:1;
}
#depthCanvas {
  position:absolute; top:0; left:0; width:100%; height:100%;
  z-index:2; opacity:0.3; pointer-events:none;
}
#recUI {
  position:absolute; top:0; left:0; width:100%; height:100%;
  z-index:3; pointer-events:none;
  display:flex; flex-direction:column; justify-content:space-between; padding:20px;
}
#statusBar {
  background:rgba(0,0,0,0.8); border-radius:12px; padding:10px 14px;
  font-size:0.7rem; color:#a855f7; font-family:monospace;
  backdrop-filter:blur(10px); border:1px solid #2a1a4a;
  display:flex; justify-content:space-between;
}
#recBtn {
  width:70px; height:70px; border-radius:50%;
  background:linear-gradient(135deg,#ef4444,#dc2626);
  margin:0 auto; box-shadow:0 0 40px rgba(239,68,68,0.6);
  display:flex; align-items:center; justify-content:center;
  font-size:1.8rem; border:4px solid rgba(255,255,255,0.2);
  cursor:pointer; pointer-events:auto; transition:all 0.2s;
}
#recBtn.recording { animation:pulse 1s infinite; border-color:#fff; }
@keyframes pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.12)} }
#recBtn.processing { background:linear-gradient(135deg,#f59e0b,#d97706); animation:none; }

.controls {
  position:absolute; bottom:25px; left:0; width:100%;
  display:flex; justify-content:center; gap:15px; z-index:10;
  pointer-events:auto;
}
.btn {
  background:linear-gradient(135deg,#7c3aed,#a855f7);
  color:#fff; border:none; padding:14px 28px;
  border-radius:50px; font-size:0.95rem; font-weight:600;
  cursor:pointer; box-shadow:0 4px 20px rgba(124,58,237,0.4);
}
.btn:disabled { opacity:0.3; cursor:not-allowed; }
.btn-secondary { background:#1a1a2e; border:1px solid #2a1a4a; }

/* VIEWER */
#viewerScreen { flex:1; display:none; position:relative; }
#threeCanvas { width:100%; height:100%; display:block; }
#viewerUI {
  position:absolute; top:0; left:0; width:100%; padding:15px;
  z-index:10; pointer-events:none;
}
#viewerInfo {
  background:rgba(0,0,0,0.7); border-radius:12px; padding:10px 14px;
  font-size:0.7rem; color:#a855f7; backdrop-filter:blur(10px);
  border:1px solid #2a1a4a; display:inline-block;
}
#viewerControls {
  position:absolute; bottom:20px; left:0; width:100%;
  display:flex; justify-content:center; gap:12px; z-index:10;
  pointer-events:auto;
}
#loading {
  position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
  color:#a855f7; font-size:1.1rem; z-index:20; text-align:center;
}
#loading .spinner {
  width:40px; height:40px; border:3px solid #2a1a4a;
  border-top-color:#a855f7; border-radius:50%;
  animation:spin 1s linear infinite; margin:0 auto 10px;
}
@keyframes spin { to { transform:rotate(360deg); } }

/* GALLERY */
#galleryScreen { flex:1; display:none; overflow-y:auto; padding:20px; }
#galleryScreen h2 { color:#a855f7; margin-bottom:16px; font-size:1.2rem; }
.memoCard {
  background:#0d0d14; border:1px solid #1a1a2a; border-radius:16px;
  padding:14px; margin-bottom:10px; display:flex; gap:12px; align-items:center;
}
.memoCard .thumb {
  width:56px; height:56px; border-radius:12px; background:linear-gradient(135deg,#1a1033,#2a1a4a);
  display:flex; align-items:center; justify-content:center; font-size:1.4rem; flex-shrink:0;
}
.memoCard .info { flex:1; min-width:0; }
.memoCard .info h4 { color:#c084fc; font-size:0.9rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.memoCard .info p { color:#555; font-size:0.7rem; margin-top:3px; }
.memoCard .actions { display:flex; gap:6px; flex-shrink:0; }
.memoCard .actions button {
  background:#1a1033; color:#a855f7; border:1px solid #2a1a4a;
  padding:8px 14px; border-radius:10px; font-size:0.75rem; cursor:pointer;
}

/* NAV */
#nav {
  display:flex; justify-content:space-around; padding:10px;
  background:#050508; border-top:1px solid #111118; z-index:100;
}
#nav button {
  background:none; border:none; color:#333; font-size:0.7rem;
  display:flex; flex-direction:column; align-items:center; gap:3px;
  cursor:pointer; padding:6px 20px;
}
#nav button.active { color:#a855f7; }
#nav button .icon { font-size:1.2rem; }

/* TUTORIAL OVERLAY */
#tutorial {
  position:fixed; top:0; left:0; width:100%; height:100%;
  background:rgba(0,0,0,0.9); z-index:1000;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  padding:30px; text-align:center;
}
#tutorial h3 { color:#a855f7; font-size:1.3rem; margin-bottom:15px; }
#tutorial p { color:#888; font-size:0.9rem; margin-bottom:8px; line-height:1.5; }
#tutorial .btn { margin-top:20px; }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
<div id="app">

<!-- TUTORIAL -->
<div id="tutorial">
  <h3>🧠 Memento</h3>
  <p>Записывай пространственные воспоминания.</p>
  <p>1. Нажми красную кнопку и медленно обойди объект</p>
  <p>2. Мы построим 3D-сцену из твоего видео</p>
  <p>3. Смотри: крути пальцем, приближай, обходи</p>
  <button class="btn" onclick="closeTutorial()">Понял, поехали</button>
</div>

<!-- RECORD -->
<div id="recordScreen">
  <video id="videoPreview" autoplay playsinline muted></video>
  <canvas id="depthCanvas"></canvas>
  <div id="recUI">
    <div id="statusBar">
      <span id="gyroText">Gyro: —</span>
      <span id="fpsText">FPS: —</span>
    </div>
    <div></div>
    <div style="text-align:center;">
      <div id="recBtn" onclick="toggleRecord()">●</div>
      <p style="color:#888; font-size:0.75rem; margin-top:10px;" id="recHint">Нажми для записи</p>
    </div>
  </div>
  <div class="controls">
    <button class="btn btn-secondary" id="btnStop" onclick="stopRecord()" disabled>■ Стоп</button>
  </div>
</div>

<!-- VIEWER -->
<div id="viewerScreen">
  <canvas id="threeCanvas"></canvas>
  <div id="viewerUI">
    <div id="viewerInfo">🖐 Листай пальцем · 🤏 Зумь pinch · 📱 Наклоняй телефон</div>
  </div>
  <div id="loading" style="display:none;">
    <div class="spinner"></div>
    <div>Строим 3D-сцену...</div>
  </div>
  <div id="viewerControls">
    <button class="btn" onclick="resetView()">↺ Сброс</button>
    <button class="btn btn-secondary" onclick="showScreen('gallery')">← Назад</button>
  </div>
</div>

<!-- GALLERY -->
<div id="galleryScreen">
  <h2>🎞 Мои Memento</h2>
  <div id="memoList"></div>
</div>

<!-- NAV -->
<div id="nav">
  <button class="active" onclick="showScreen('record')" id="navRecord">
    <span class="icon">📷</span>Запись
  </button>
  <button onclick="showScreen('gallery')" id="navGallery">
    <span class="icon">🎞</span>Галерея
  </button>
</div>
</div>

<script>
// ========== GLOBALS ==========
let mediaRecorder, recordedChunks = [];
let gyroHistory = [], frameHistory = [];
let isRecording = false, isProcessing = false;
let stream = null, videoEl, depthCtx;
let currentMemoId = null;
let scene, camera, renderer, pointsGroup, controls = {};
let animId;

// ========== INIT ==========
function closeTutorial() {
  document.getElementById('tutorial').style.display = 'none';
  initCamera();
}

async function initCamera() {
  videoEl = document.getElementById('videoPreview');
  depthCtx = document.getElementById('depthCanvas').getContext('2d');

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: {ideal:1280}, height: {ideal:720}, frameRate: {ideal:30} },
      audio: { echoCancellation: false, noiseSuppression: false, sampleRate: 48000, channelCount: 2 }
    });
    videoEl.srcObject = stream;

    // Gyro
    if(window.DeviceOrientationEvent) {
      window.addEventListener('deviceorientation', onGyro, true);
    }
    if(typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
      try { await DeviceOrientationEvent.requestPermission(); } catch(e){}
    }

    // Motion
    if(window.DeviceMotionEvent) {
      window.addEventListener('devicemotion', onMotion, true);
    }

    startDepthPreview();
  } catch(e) { 
    alert('Камера недоступна: ' + e.message); 
  }
}

let lastGyro = {alpha:0, beta:0, gamma:0};
let lastMotion = {x:0, y:0, z:0};

function onGyro(e) {
  lastGyro = { alpha: e.alpha||0, beta: e.beta||0, gamma: e.gamma||0 };
  document.getElementById('gyroText').textContent = 
    `α:${lastGyro.alpha.toFixed(0)}° β:${lastGyro.beta.toFixed(0)}° γ:${lastGyro.gamma.toFixed(0)}°`;
}

function onMotion(e) {
  const a = e.accelerationIncludingGravity || e.acceleration || {x:0,y:0,z:0};
  lastMotion = { x: a.x||0, y: a.y||0, z: a.z||0 };
}

// ========== DEPTH PREVIEW (client-side stereo) ==========
let prevFrame = null;
function startDepthPreview() {
  const canvas = document.getElementById('depthCanvas');
  const ctx = canvas.getContext('2d');

  function process() {
    if(videoEl.readyState >= 2) {
      canvas.width = videoEl.videoWidth / 4;
      canvas.height = videoEl.videoHeight / 4;
      ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);

      if(isRecording) {
        // Capture frame data for depth estimation
        const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        frameHistory.push({
          t: Date.now(),
          data: imgData.data,
          width: canvas.width,
          height: canvas.height,
          gyro: {...lastGyro},
          motion: {...lastMotion}
        });

        gyroHistory.push({
          t: Date.now(),
          alpha: lastGyro.alpha, beta: lastGyro.beta, gamma: lastGyro.gamma,
          accX: lastMotion.x, accY: lastMotion.y, accZ: lastMotion.z
        });
      }
    }
    requestAnimationFrame(process);
  }
  process();
}

// ========== RECORDING ==========
async function toggleRecord() {
  if(isProcessing) return;
  if(!stream) { await initCamera(); return; }

  if(isRecording) {
    stopRecord();
    return;
  }

  recordedChunks = [];
  gyroHistory = [];
  frameHistory = [];
  isRecording = true;

  document.getElementById('recBtn').classList.add('recording');
  document.getElementById('recBtn').textContent = '■';
  document.getElementById('recHint').textContent = 'Идёт запись... Обойди объект';
  document.getElementById('btnStop').disabled = false;

  mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9,opus' });
  mediaRecorder.ondataavailable = e => { if(e.data.size>0) recordedChunks.push(e.data); };
  mediaRecorder.onstop = onRecordStop;
  mediaRecorder.start(200);
}

function stopRecord() {
  if(!isRecording) return;
  isRecording = false;
  document.getElementById('recBtn').classList.remove('recording');
  document.getElementById('recBtn').textContent = '●';
  document.getElementById('recHint').textContent = 'Обработка...';
  document.getElementById('recBtn').classList.add('processing');
  document.getElementById('btnStop').disabled = true;

  if(mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
}

async function onRecordStop() {
  isProcessing = true;
  const blob = new Blob(recordedChunks, { type: 'video/webm' });

  // Send frames as base64 images for server-side photogrammetry
  const form = new FormData();
  form.append('video', blob, 'capture.webm');
  form.append('gyro', JSON.stringify(gyroHistory));

  // Send keyframes for depth
  const keyframes = frameHistory.filter((_,i) => i % 3 === 0).slice(0, 60);
  for(let i=0; i<keyframes.length; i++) {
    const kf = keyframes[i];
    const canvas = document.createElement('canvas');
    canvas.width = kf.width; canvas.height = kf.height;
    const ctx = canvas.getContext('2d');
    const imgData = new ImageData(new Uint8ClampedArray(kf.data), kf.width, kf.height);
    ctx.putImageData(imgData, 0, 0);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.7);
    form.append(`frame_${i}`, dataUrl);
    form.append(`meta_${i}`, JSON.stringify({gyro:kf.gyro, motion:kf.motion, t:kf.t}));
  }

  try {
    const res = await fetch('/api/record', { method: 'POST', body: form });
    const data = await res.json();
    currentMemoId = data.memo_id;

    document.getElementById('recBtn').classList.remove('processing');
    document.getElementById('recHint').textContent = 'Готово! Перехожу в галерею...';
    setTimeout(() => { showScreen('gallery'); }, 500);
  } catch(e) { 
    alert('Ошибка: ' + e.message); 
    document.getElementById('recBtn').classList.remove('processing');
    document.getElementById('recHint').textContent = 'Нажми для записи';
  }
  isProcessing = false;
}

// ========== NAVIGATION ==========
function showScreen(name) {
  document.getElementById('recordScreen').style.display = 'none';
  document.getElementById('viewerScreen').style.display = 'none';
  document.getElementById('galleryScreen').style.display = 'none';
  document.getElementById('navRecord').classList.remove('active');
  document.getElementById('navGallery').classList.remove('active');

  if(name==='record') {
    document.getElementById('recordScreen').style.display='flex';
    document.getElementById('navRecord').classList.add('active');
    document.getElementById('recHint').textContent = 'Нажми для записи';
  } else if(name==='viewer') {
    document.getElementById('viewerScreen').style.display='flex';
  } else if(name==='gallery') {
    document.getElementById('galleryScreen').style.display='flex';
    document.getElementById('navGallery').classList.add('active');
    loadGallery();
  }
}

// ========== GALLERY ==========
async function loadGallery() {
  const res = await fetch('/api/list');
  const list = await res.json();
  const container = document.getElementById('memoList');
  container.innerHTML = '';

  if(list.length === 0) {
    container.innerHTML = '<p style="color:#444; text-align:center; padding:40px;">Нет записей. Сними первый Memento!</p>';
    return;
  }

  list.forEach(m => {
    const div = document.createElement('div');
    div.className = 'memoCard';
    div.innerHTML = `
      <div class="thumb">🧠</div>
      <div class="info">
        <h4>${m.id}</h4>
        <p>${new Date(m.time).toLocaleString('ru')} · ${m.points?.toLocaleString()||'?'} точек · ${(m.duration||0).toFixed(1)}s</p>
      </div>
      <div class="actions">
        <button onclick="viewMemo('${m.id}')">▶</button>
        <button onclick="downloadMemo('${m.id}')">⬇</button>
      </div>
    `;
    container.appendChild(div);
  });
}

// ========== VIEWER (Three.js with real depth) ==========
async function viewMemo(id) {
  showScreen('viewer');
  document.getElementById('loading').style.display = 'block';

  const res = await fetch('/api/memo/' + id);
  const memo = await res.json();

  initThreeViewer(memo);
  document.getElementById('loading').style.display = 'none';
}

function initThreeViewer(memo) {
  const canvas = document.getElementById('threeCanvas');
  if(animId) cancelAnimationFrame(animId);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x020204);
  scene.fog = new THREE.FogExp2(0x020204, 0.15);

  camera = new THREE.PerspectiveCamera(70, window.innerWidth/window.innerHeight, 0.01, 50);
  camera.position.set(0, 0, 2.5);

  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputEncoding = THREE.sRGBEncoding;

  pointsGroup = new THREE.Group();
  scene.add(pointsGroup);

  // Build point cloud from memo data
  if(memo.point_cloud && memo.point_cloud.length > 0) {
    const pc = memo.point_cloud;
    const positions = new Float32Array(pc.length * 3);
    const colors = new Float32Array(pc.length * 3);
    const sizes = new Float32Array(pc.length);

    for(let i=0; i<pc.length; i++) {
      positions[i*3] = pc[i].x;
      positions[i*3+1] = pc[i].y;
      positions[i*3+2] = pc[i].z;
      colors[i*3] = pc[i].r / 255;
      colors[i*3+1] = pc[i].g / 255;
      colors[i*3+2] = pc[i].b / 255;
      sizes[i] = Math.max(0.005, 0.02 / (1 + Math.abs(pc[i].z)));
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const material = new THREE.PointsMaterial({
      size: 0.015,
      vertexColors: true,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending
    });

    const points = new THREE.Points(geometry, material);
    pointsGroup.add(points);

    // Auto-center
    geometry.computeBoundingBox();
    const center = new THREE.Vector3();
    geometry.boundingBox.getCenter(center);
    pointsGroup.position.sub(center);

    // Camera distance based on scene size
    const size = new THREE.Vector3();
    geometry.boundingBox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);
    camera.position.z = maxDim * 0.8;
  }

  // Lights
  const ambient = new THREE.AmbientLight(0x404060, 0.5);
  scene.add(ambient);
  const pointLight = new THREE.PointLight(0xa855f7, 0.8, 20);
  pointLight.position.set(2, 3, 4);
  scene.add(pointLight);
  const pointLight2 = new THREE.PointLight(0x3b82f6, 0.5, 20);
  pointLight2.position.set(-2, -1, 3);
  scene.add(pointLight2);

  // Audio
  if(memo.audio_url) {
    const audio = new Audio(memo.audio_url);
    audio.loop = true;
    audio.volume = 0.7;
    audio.play().catch(()=>{});
  }

  // Touch controls
  let isDragging = false, lastX = 0, lastY = 0;
  let spherical = new THREE.Spherical(2.5, Math.PI/2, 0);
  let targetSpherical = new THREE.Spherical(2.5, Math.PI/2, 0);

  canvas.addEventListener('touchstart', e => {
    isDragging = true;
    lastX = e.touches[0].clientX;
    lastY = e.touches[0].clientY;
  }, {passive:false});

  canvas.addEventListener('touchmove', e => {
    e.preventDefault();
    if(!isDragging) return;
    const dx = e.touches[0].clientX - lastX;
    const dy = e.touches[0].clientY - lastY;
    targetSpherical.theta -= dx * 0.008;
    targetSpherical.phi -= dy * 0.008;
    targetSpherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, targetSpherical.phi));
    lastX = e.touches[0].clientX;
    lastY = e.touches[0].clientY;
  }, {passive:false});

  canvas.addEventListener('touchend', () => isDragging = false);

  // Pinch zoom
  let lastPinchDist = 0;
  canvas.addEventListener('touchstart', e => {
    if(e.touches.length === 2) {
      lastPinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
    }
  }, {passive:false});

  canvas.addEventListener('touchmove', e => {
    if(e.touches.length === 2) {
      e.preventDefault();
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      const delta = dist - lastPinchDist;
      targetSpherical.radius -= delta * 0.01;
      targetSpherical.radius = Math.max(0.3, Math.min(10, targetSpherical.radius));
      lastPinchDist = dist;
    }
  }, {passive:false});

  // Gyro camera (optional, when not dragging)
  let useGyro = true;
  window.addEventListener('deviceorientation', e => {
    if(isDragging || !useGyro) return;
    if(e.alpha === null) return;
    targetSpherical.theta = THREE.MathUtils.degToRad(e.alpha);
    targetSpherical.phi = THREE.MathUtils.degToRad(90 - e.beta);
  }, true);

  // Smooth camera
  function updateCamera() {
    spherical.radius += (targetSpherical.radius - spherical.radius) * 0.1;
    spherical.theta += (targetSpherical.theta - spherical.theta) * 0.1;
    spherical.phi += (targetSpherical.phi - spherical.phi) * 0.1;

    camera.position.setFromSpherical(spherical);
    camera.lookAt(0, 0, 0);
  }

  // Auto-rotate slowly when idle
  let idleTime = 0;
  function animate() {
    animId = requestAnimationFrame(animate);

    if(!isDragging) {
      idleTime++;
      if(idleTime > 180) {
        targetSpherical.theta += 0.002;
      }
    } else {
      idleTime = 0;
    }

    updateCamera();

    // Subtle point animation
    if(pointsGroup.children[0]) {
      pointsGroup.rotation.y += 0.0003;
    }

    renderer.render(scene, camera);
  }
  animate();

  // Resize
  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });
}

function resetView() {
  if(!camera) return;
  camera.position.set(0, 0, 2.5);
  camera.lookAt(0, 0, 0);
}

function downloadMemo(id) {
  window.open('/api/download/' + id, '_blank');
}
</script>
</body>
</html>
"""

# ========== PHOTOGRAMMETRY BACKEND ==========

def extract_frames(video_path, output_dir, every_n=3, max_frames=60):
    """Extract keyframes from video"""
    cap = cv2.VideoCapture(str(video_path))
    frames = []
    count = 0
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret: break
        if frame_idx % every_n == 0 and count < max_frames:
            path = output_dir / f"frame_{count:04d}.jpg"
            cv2.imwrite(str(path), frame)
            frames.append({"path": path, "idx": frame_idx, "image": frame})
            count += 1
        frame_idx += 1
    cap.release()
    return frames

def detect_features(image, max_features=500):
    """Detect ORB features in image"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=max_features)
    kp, des = orb.detectAndCompute(gray, None)
    return kp, des

def match_features(des1, des2):
    """Match ORB features between two frames"""
    if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
        return []
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    matches = sorted(matches, key=lambda x: x.distance)
    return matches[:min(50, len(matches))]

def triangulate_points(kp1, kp2, matches, K, R, t):
    """Triangulate 3D points from matched features"""
    if len(matches) < 8:
        return []

    pts1 = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    pts2 = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

    # Essential matrix
    E, mask = cv2.findEssentialMat(pts1, pts2, K, method=cv2.RANSAC, prob=0.999, threshold=1.0)
    if E is None or mask is None:
        return []

    mask = mask.ravel().astype(bool)
    pts1 = pts1[mask]
    pts2 = pts2[mask]

    if len(pts1) < 5:
        return []

    # Recover pose
    _, R_rel, t_rel, mask_pose = cv2.recoverPose(E, pts1, pts2, K)

    # Projection matrices
    P1 = K @ np.hstack([np.eye(3), np.zeros((3,1))])
    P2 = K @ np.hstack([R_rel, t_rel])

    # Triangulate
    pts4D = cv2.triangulatePoints(P1, P2, pts1.T, pts2.T)
    pts3D = pts4D[:3] / pts4D[3]
    pts3D = pts3D.T

    # Filter: remove points behind camera and too far
    valid = (pts3D[:,2] > 0.1) & (pts3D[:,2] < 20) &             (np.abs(pts3D[:,0]) < 10) & (np.abs(pts3D[:,1]) < 10)
    pts3D = pts3D[valid]

    return pts3D

def build_point_cloud_from_video(video_path, gyro_data=None):
    """Build real 3D point cloud from video using photogrammetry"""

    temp_dir = Path(tempfile.mkdtemp())
    try:
        frames = extract_frames(video_path, temp_dir, every_n=3, max_frames=40)
        if len(frames) < 2:
            return []

        # Camera intrinsics (estimate for typical phone camera)
        h, w = frames[0]["image"].shape[:2]
        fx = fy = max(w, h) * 0.8  # approximate focal length
        cx, cy = w / 2, h / 2
        K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])

        all_points = []
        all_colors = []

        # Detect features in all frames
        frame_features = []
        for f in frames:
            kp, des = detect_features(f["image"])
            frame_features.append({"kp": kp, "des": des, "image": f["image"]})

        # Match consecutive frames and triangulate
        for i in range(len(frame_features) - 1):
            f1 = frame_features[i]
            f2 = frame_features[i + 1]

            matches = match_features(f1["des"], f2["des"])
            if len(matches) < 10:
                continue

            pts3D = triangulate_points(f1["kp"], f2["kp"], matches, K, None, None)
            if len(pts3D) == 0:
                continue

            # Get colors from first frame
            for pt in pts3D:
                x, y = int(f1["kp"][matches[0].queryIdx].pt[0]), int(f1["kp"][matches[0].queryIdx].pt[1])
                x = max(0, min(w-1, x))
                y = max(0, min(h-1, y))
                b, g, r = f1["image"][y, x]

                all_points.append([pt[0], pt[1], pt[2]])
                all_colors.append([int(r), int(g), int(b)])

        # Downsample if too many points
        if len(all_points) > 15000:
            indices = np.random.choice(len(all_points), 15000, replace=False)
            all_points = [all_points[i] for i in indices]
            all_colors = [all_colors[i] for i in indices]

        # Build result
        result = []
        for pt, col in zip(all_points, all_colors):
            result.append({
                "x": float(pt[0]), "y": float(pt[1]), "z": float(pt[2]),
                "r": int(col[0]), "g": int(col[1]), "b": int(col[2])
            })

        return result

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ========== API ROUTES ==========

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE

@app.post("/api/record")
async def api_record(video: UploadFile = File(...), gyro: str = Form(...)):
    memo_id = f"memo_{os.urandom(4).hex()}"
    memo_dir = UPLOAD_DIR / memo_id
    memo_dir.mkdir(exist_ok=True)

    # Save video
    video_path = memo_dir / "video.webm"
    with open(video_path, "wb") as f:
        f.write(await video.read())

    # Save gyro
    gyro_data = json.loads(gyro)
    with open(memo_dir / "gyro.json", "w") as f:
        json.dump(gyro_data, f)

    # Build real point cloud
    point_cloud = build_point_cloud_from_video(video_path, gyro_data)

    # Get video info
    cap = cv2.VideoCapture(str(video_path))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    duration = frame_count / fps
    cap.release()

    # Build memo metadata
    meta = {
        "id": memo_id,
        "time": int(os.path.getmtime(str(video_path)) * 1000),
        "frames": frame_count,
        "duration": round(duration, 2),
        "points": len(point_cloud),
        "point_cloud": point_cloud,
        "audio_url": f"/api/audio/{memo_id}",
        "gyro_samples": len(gyro_data)
    }
    with open(memo_dir / "meta.json", "w") as f:
        json.dump(meta, f)

    # Build .memo container
    memo_file = memo_dir / f"{memo_id}.memo"
    with zipfile.ZipFile(memo_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(memo_dir / "meta.json"), "meta.json")
        zf.write(str(video_path), "video.webm")
        zf.write(str(memo_dir / "gyro.json"), "gyro.json")
        # Point cloud as binary
        if point_cloud:
            pc_bytes = np.array([[p["x"],p["y"],p["z"],p["r"],p["g"],p["b"]] for p in point_cloud], dtype=np.float32).tobytes()
            zf.writestr("point_cloud.bin", pc_bytes)

    return {"memo_id": memo_id, "status": "ok", "points": len(point_cloud)}

@app.get("/api/list")
def api_list():
    memos = []
    for d in sorted(UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if d.is_dir() and (d / "meta.json").exists():
            with open(d / "meta.json") as f:
                meta = json.load(f)
            memos.append({
                "id": meta["id"],
                "time": meta["time"],
                "points": meta.get("points", 0),
                "duration": meta.get("duration", 0)
            })
    return memos

@app.get("/api/memo/{memo_id}")
def api_get_memo(memo_id: str):
    memo_dir = UPLOAD_DIR / memo_id
    with open(memo_dir / "meta.json") as f:
        return json.load(f)

@app.get("/api/audio/{memo_id}")
def api_audio(memo_id: str):
    video_path = UPLOAD_DIR / memo_id / "video.webm"
    return FileResponse(str(video_path), media_type="video/webm")

@app.get("/api/download/{memo_id}")
def api_download(memo_id: str):
    memo_file = UPLOAD_DIR / memo_id / f"{memo_id}.memo"
    return FileResponse(str(memo_file), media_type="application/octet-stream", filename=f"{memo_id}.memo")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
