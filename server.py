from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import os, json, zipfile, io, base64, tempfile, shutil, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image
import cv2

app = FastAPI()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# ========== HTML INTERFACE ==========
HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>Memento — Запись 3D-сцены</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
  background:#050508; color:#e0e0e5;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  overflow:hidden; touch-action:none;
}
#app { height:100vh; display:flex; flex-direction:column; }

/* === RECORD SCREEN === */
#recordScreen { flex:1; display:flex; flex-direction:column; position:relative; }
#videoPreview {
  position:absolute; top:0; left:0; width:100%; height:100%;
  object-fit:cover; opacity:0.6; z-index:1;
}
#overlay {
  position:absolute; top:0; left:0; width:100%; height:100%;
  z-index:2; pointer-events:none;
  display:flex; flex-direction:column; justify-content:space-between; padding:20px;
}
#gyroData {
  background:rgba(0,0,0,0.7); border-radius:12px; padding:12px;
  font-size:0.75rem; color:#a855f7; font-family:monospace;
  backdrop-filter:blur(10px); border:1px solid #2a1a4a;
}
#recIndicator {
  width:60px; height:60px; border-radius:50%;
  background:linear-gradient(135deg,#ef4444,#dc2626);
  margin:0 auto; box-shadow:0 0 30px rgba(239,68,68,0.5);
  display:flex; align-items:center; justify-content:center;
  font-size:1.5rem; transition:transform 0.2s;
}
#recIndicator.recording { animation:pulse 1s infinite; }
@keyframes pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.1)} }

.controls {
  position:absolute; bottom:30px; left:0; width:100%;
  display:flex; justify-content:center; gap:20px; z-index:10;
}
.btn {
  background:linear-gradient(135deg,#7c3aed,#a855f7);
  color:#fff; border:none; padding:16px 32px;
  border-radius:50px; font-size:1rem; font-weight:600;
  cursor:pointer; box-shadow:0 4px 20px rgba(124,58,237,0.4);
}
.btn:disabled { opacity:0.4; cursor:not-allowed; }
.btn-secondary {
  background:#1a1a2e; border:1px solid #2a1a4a;
}

/* === VIEWER SCREEN === */
#viewerScreen { flex:1; display:none; position:relative; }
#threeCanvas { width:100%; height:100%; display:block; }
#viewerControls {
  position:absolute; bottom:20px; left:0; width:100%;
  display:flex; justify-content:center; gap:15px; z-index:10;
}
#loading {
  position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
  color:#a855f7; font-size:1.2rem; z-index:20;
}

/* === GALLERY === */
#galleryScreen { flex:1; display:none; overflow-y:auto; padding:20px; }
.memoCard {
  background:#111118; border:1px solid #1e1e2e; border-radius:16px;
  padding:16px; margin-bottom:12px; display:flex; gap:15px; align-items:center;
}
.memoCard .thumb {
  width:60px; height:60px; border-radius:12px; background:#2a1a4a;
  display:flex; align-items:center; justify-content:center; font-size:1.5rem;
}
.memoCard .info { flex:1; }
.memoCard .info h4 { color:#c084fc; font-size:0.95rem; }
.memoCard .info p { color:#666; font-size:0.75rem; margin-top:4px; }
.memoCard .actions { display:flex; gap:8px; }
.memoCard .actions button {
  background:#2a1a4a; color:#c084fc; border:none;
  padding:8px 16px; border-radius:10px; font-size:0.8rem; cursor:pointer;
}

/* === NAV === */
#nav {
  display:flex; justify-content:space-around; padding:12px;
  background:#0a0a12; border-top:1px solid #1e1e2e; z-index:100;
}
#nav button {
  background:none; border:none; color:#555; font-size:0.8rem;
  display:flex; flex-direction:column; align-items:center; gap:4px;
  cursor:pointer;
}
#nav button.active { color:#a855f7; }
#nav button .icon { font-size:1.3rem; }

/* === HIDDEN === */
.hidden { display:none !important; }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
<div id="app">

<!-- RECORD -->
<div id="recordScreen">
  <video id="videoPreview" autoplay playsinline muted></video>
  <div id="overlay">
    <div id="gyroData">α:0° β:0° γ:0°</div>
    <div id="recIndicator">●</div>
    <div></div>
  </div>
  <div class="controls">
    <button class="btn" id="btnRecord" onclick="toggleRecord()">▶ Записать</button>
    <button class="btn btn-secondary" id="btnStop" onclick="stopRecord()" disabled>■ Стоп</button>
  </div>
</div>

<!-- VIEWER -->
<div id="viewerScreen">
  <canvas id="threeCanvas"></canvas>
  <div id="loading">Загрузка 3D-сцены...</div>
  <div id="viewerControls">
    <button class="btn" onclick="resetCamera()">↺ Сброс</button>
    <button class="btn btn-secondary" onclick="showScreen('gallery')">← Назад</button>
  </div>
</div>

<!-- GALLERY -->
<div id="galleryScreen">
  <h2 style="color:#a855f7; margin-bottom:20px; font-size:1.3rem;">🧠 Мои Memento</h2>
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
let gyroHistory = [];
let isRecording = false;
let stream = null;
let audioContext, audioStream, audioRecorder;
let currentMemoId = null;
let scene, camera, renderer, pointsMesh, audioSource;

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
  } else if(name==='viewer') {
    document.getElementById('viewerScreen').style.display='flex';
  } else if(name==='gallery') {
    document.getElementById('galleryScreen').style.display='flex';
    document.getElementById('navGallery').classList.add('active');
    loadGallery();
  }
}

// ========== CAMERA + GYRO ==========
async function initCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: {ideal:1280}, height: {ideal:720} },
      audio: { echoCancellation: false, noiseSuppression: false, sampleRate: 48000 }
    });
    document.getElementById('videoPreview').srcObject = stream;

    // Audio context for spatial
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    audioStream = audioContext.createMediaStreamSource(stream);

    // Gyro
    if(window.DeviceOrientationEvent) {
      window.addEventListener('deviceorientation', onGyro);
    }
    if(typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
      await DeviceOrientationEvent.requestPermission();
    }
  } catch(e) { alert('Камера недоступна: '+e.message); }
}

function onGyro(e) {
  const txt = `α:${(e.alpha||0).toFixed(1)}° β:${(e.beta||0).toFixed(1)}° γ:${(e.gamma||0).toFixed(1)}°`;
  document.getElementById('gyroData').textContent = txt;
  if(isRecording) {
    gyroHistory.push({
      t: Date.now(),
      alpha: e.alpha||0, beta: e.beta||0, gamma: e.gamma||0,
      acc: {x:0,y:0,z:0} // placeholder for accel
    });
  }
}

// ========== RECORDING ==========
async function toggleRecord() {
  if(!stream) await initCamera();
  recordedChunks = [];
  gyroHistory = [];
  isRecording = true;

  document.getElementById('btnRecord').disabled = true;
  document.getElementById('btnStop').disabled = false;
  document.getElementById('recIndicator').classList.add('recording');

  // Video
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9' });
  mediaRecorder.ondataavailable = e => { if(e.data.size>0) recordedChunks.push(e.data); };
  mediaRecorder.onstop = onRecordStop;
  mediaRecorder.start(100);

  // Audio capture separately for spatial processing
  // (simplified: we use video audio track, server extracts)
}

function stopRecord() {
  if(mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  isRecording = false;
  document.getElementById('recIndicator').classList.remove('recording');
}

async function onRecordStop() {
  document.getElementById('btnRecord').disabled = false;
  document.getElementById('btnStop').disabled = true;

  const blob = new Blob(recordedChunks, { type: 'video/webm' });
  const form = new FormData();
  form.append('video', blob, 'capture.webm');
  form.append('gyro', JSON.stringify(gyroHistory));

  // Show uploading
  document.getElementById('recIndicator').textContent = '⏳';

  try {
    const res = await fetch('/api/record', { method: 'POST', body: form });
    const data = await res.json();
    currentMemoId = data.memo_id;
    alert('✅ Memento сохранён! ID: ' + currentMemoId);
    showScreen('gallery');
  } catch(e) { alert('Ошибка: '+e.message); }
  document.getElementById('recIndicator').textContent = '●';
}

// ========== GALLERY ==========
async function loadGallery() {
  const res = await fetch('/api/list');
  const list = await res.json();
  const container = document.getElementById('memoList');
  container.innerHTML = '';
  list.forEach(m => {
    const div = document.createElement('div');
    div.className = 'memoCard';
    div.innerHTML = `
      <div class="thumb">🧠</div>
      <div class="info">
        <h4>${m.id}</h4>
        <p>${new Date(m.time).toLocaleString()} · ${m.frames} кадров · ${m.duration}s</p>
      </div>
      <div class="actions">
        <button onclick="viewMemo('${m.id}')">▶ Смотреть</button>
        <button onclick="downloadMemo('${m.id}')">⬇</button>
      </div>
    `;
    container.appendChild(div);
  });
}

// ========== VIEWER (Three.js) ==========
async function viewMemo(id) {
  showScreen('viewer');
  document.getElementById('loading').style.display = 'block';

  // Fetch memo data
  const res = await fetch('/api/memo/' + id);
  const memo = await res.json();

  initThree(memo);
  document.getElementById('loading').style.display = 'none';
}

function initThree(memo) {
  const canvas = document.getElementById('threeCanvas');

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x050508);

  camera = new THREE.PerspectiveCamera(75, window.innerWidth/window.innerHeight, 0.1, 1000);
  camera.position.set(0, 0, 2);

  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  // Point cloud from memo frames
  const positions = [];
  const colors = [];

  if(memo.point_cloud && memo.point_cloud.length > 0) {
    memo.point_cloud.forEach(p => {
      positions.push(p.x, p.y, p.z);
      colors.push(p.r/255, p.g/255, p.b/255);
    });
  } else {
    // Fallback: grid of points
    for(let i=0; i<5000; i++) {
      positions.push((Math.random()-0.5)*4, (Math.random()-0.5)*4, (Math.random()-0.5)*4);
      colors.push(Math.random(), Math.random(), Math.random());
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({ size: 0.02, vertexColors: true, sizeAttenuation: true });
  pointsMesh = new THREE.Points(geometry, material);
  scene.add(pointsMesh);

  // Lights
  const light = new THREE.PointLight(0xa855f7, 1, 100);
  light.position.set(0, 5, 5);
  scene.add(light);
  scene.add(new THREE.AmbientLight(0x222222));

  // Audio
  if(memo.audio_url) {
    const audio = new Audio(memo.audio_url);
    audio.loop = true;
    audio.play().catch(()=>{});
  }

  // Controls via touch
  let isDragging = false, lastX = 0, lastY = 0;
  let rotX = 0, rotY = 0;

  canvas.addEventListener('touchstart', e => {
    isDragging = true;
    lastX = e.touches[0].clientX;
    lastY = e.touches[0].clientY;
  });
  canvas.addEventListener('touchmove', e => {
    if(!isDragging) return;
    const dx = e.touches[0].clientX - lastX;
    const dy = e.touches[0].clientY - lastY;
    rotY += dx * 0.01;
    rotX += dy * 0.01;
    camera.rotation.x = rotX;
    camera.rotation.y = rotY;
    lastX = e.touches[0].clientX;
    lastY = e.touches[0].clientY;
  });
  canvas.addEventListener('touchend', () => isDragging = false);

  // Gyro for camera rotation (if available)
  window.addEventListener('deviceorientation', e => {
    if(!e.alpha) return;
    camera.rotation.y = THREE.MathUtils.degToRad(e.alpha);
    camera.rotation.x = THREE.MathUtils.degToRad(e.beta - 90);
  });

  animate();
}

function animate() {
  requestAnimationFrame(animate);
  if(pointsMesh) pointsMesh.rotation.y += 0.001;
  renderer.render(scene, camera);
}

function resetCamera() {
  camera.position.set(0, 0, 2);
  camera.rotation.set(0, 0, 0);
}

function downloadMemo(id) {
  window.open('/api/download/' + id, '_blank');
}

// Init
initCamera();
</script>
</body>
</html>
"""

# ========== FASTAPI ROUTES ==========

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

    # Extract frames + build point cloud
    frames_dir = memo_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    frame_count = 0
    point_cloud = []

    while True:
        ret, frame = cap.read()
        if not ret: break
        if frame_count % 5 == 0:  # every 5th frame
            h, w = frame.shape[:2]
            # Resize for speed
            small = cv2.resize(frame, (w//4, h//4))
            # Simple depth estimation from motion (placeholder: use color intensity as pseudo-depth)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            # Sample points
            for y in range(0, small.shape[0], 8):
                for x in range(0, small.shape[1], 8):
                    b, g, r = small[y, x]
                    z = gray[y, x] / 255.0 * 2.0  # pseudo depth
                    # Normalize coords
                    nx = (x / small.shape[1] - 0.5) * 4
                    ny = -(y / small.shape[0] - 0.5) * 3
                    point_cloud.append({
                        "x": nx, "y": ny, "z": z - 1,
                        "r": int(r), "g": int(g), "b": int(b)
                    })

            cv2.imwrite(str(frames_dir / f"frame_{frame_count:04d}.jpg"), frame)
        frame_count += 1
    cap.release()

    # Build memo metadata
    meta = {
        "id": memo_id,
        "time": int(os.path.getmtime(str(video_path)) * 1000),
        "frames": frame_count,
        "duration": frame_count / 30.0,
        "point_cloud": point_cloud[:5000],  # limit for mobile
        "audio_url": f"/api/audio/{memo_id}",
        "gyro_samples": len(gyro_data)
    }
    with open(memo_dir / "meta.json", "w") as f:
        json.dump(meta, f)

    # Build .memo container (zip with glTF-like structure)
    memo_file = memo_dir / f"{memo_id}.memo"
    with zipfile.ZipFile(memo_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(memo_dir / "meta.json"), "meta.json")
        zf.write(str(video_path), "video.webm")
        zf.write(str(memo_dir / "gyro.json"), "gyro.json")
        # Add point cloud as binary
        pc_bytes = np.array([[p["x"],p["y"],p["z"],p["r"],p["g"],p["b"]] for p in point_cloud[:5000]], dtype=np.float32).tobytes()
        zf.writestr("point_cloud.bin", pc_bytes)

    return {"memo_id": memo_id, "status": "ok"}

@app.get("/api/list")
def api_list():
    memos = []
    for d in UPLOAD_DIR.iterdir():
        if d.is_dir() and (d / "meta.json").exists():
            with open(d / "meta.json") as f:
                meta = json.load(f)
            memos.append(meta)
    return sorted(memos, key=lambda x: x["time"], reverse=True)

@app.get("/api/memo/{memo_id}")
def api_get_memo(memo_id: str):
    memo_dir = UPLOAD_DIR / memo_id
    with open(memo_dir / "meta.json") as f:
        return json.load(f)

@app.get("/api/audio/{memo_id}")
def api_audio(memo_id: str):
    video_path = UPLOAD_DIR / memo_id / "video.webm"
    # Extract audio from webm (simplified: return video, browser plays audio track)
    return FileResponse(str(video_path), media_type="video/webm")

@app.get("/api/download/{memo_id}")
def api_download(memo_id: str):
    memo_file = UPLOAD_DIR / memo_id / f"{memo_id}.memo"
    return FileResponse(str(memo_file), media_type="application/octet-stream", filename=f"{memo_id}.memo")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
