import os
import tempfile
import numpy as np
import soundfile as sf
from flask import Flask, request, render_template_string, send_file
from pydub import AudioSegment

app = Flask(__name__)
UPLOAD_FOLDER = tempfile.mkdtemp()

# === МОДЕЛЬ ЗАГРУЖАЕТСЯ ПРИ СТАРТЕ СЕРВЕРА ===
print("=" * 50)
print("LOADING FreeVC24 MODEL...")
print("This happens during DEPLOY, not on user request.")
print("=" * 50)

from TTS.api import TTS
_tts_model = TTS("voice_conversion_models/multilingual/vctk/freevc24")

print("=" * 50)
print("MODEL LOADED! Ready for voice conversion.")
print("=" * 50)

# Хранилище reference аудио (в памяти + на диске)
REFERENCE_PATH = os.path.join(UPLOAD_FOLDER, 'user_reference.wav')
reference_loaded = False


def convert_to_wav_24k_mono(input_path, output_path):
    """Конвертирует любой аудиоформат в WAV 24kHz mono."""
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_frame_rate(24000).set_channels(1)
    audio.export(output_path, format='wav')


HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voice Cloner — FreeVC24</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            font-family: 'Segoe UI', system-ui, sans-serif;
            color: #e0e0e0;
            padding: 20px;
        }
        .container {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(20px);
            border-radius: 24px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 25px 50px rgba(0,0,0,0.4);
        }
        h1 {
            text-align: center;
            font-size: 1.8rem;
            margin-bottom: 8px;
            background: linear-gradient(90deg, #ff6b9d, #c44569);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle {
            text-align: center;
            color: #8892b0;
            font-size: 0.9rem;
            margin-bottom: 30px;
        }
        .step {
            margin-bottom: 25px;
            padding: 20px;
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.08);
        }
        .step h3 {
            color: #ff6b9d;
            margin-bottom: 12px;
            font-size: 1rem;
        }
        .upload-area {
            border: 2px dashed rgba(255,107,157,0.4);
            border-radius: 12px;
            padding: 25px 15px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
        }
        .upload-area:hover {
            border-color: #ff6b9d;
            background: rgba(255,107,157,0.05);
        }
        .upload-area input { display: none; }
        .upload-icon { font-size: 2rem; margin-bottom: 8px; }
        .upload-text { color: #a0a0a0; font-size: 0.85rem; }
        .upload-text span { color: #ff6b9d; font-weight: 600; }
        .file-name {
            color: #ff6b9d;
            font-weight: 600;
            margin-top: 8px;
            display: none;
            font-size: 0.85rem;
        }
        .preset-btn {
            background: linear-gradient(135deg, #ff6b9d, #c44569);
            border: none;
            color: white;
            padding: 14px 30px;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s;
            box-shadow: 0 4px 20px rgba(255,107,157,0.3);
        }
        .preset-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 25px rgba(255,107,157,0.5);
        }
        .preset-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        .result {
            margin-top: 25px;
            padding: 20px;
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.08);
            display: none;
        }
        .result h3 {
            color: #ff6b9d;
            margin-bottom: 12px;
            font-size: 1rem;
        }
        audio { width: 100%; border-radius: 8px; margin-bottom: 12px; }
        .download-btn {
            display: block;
            text-align: center;
            background: rgba(255,107,157,0.2);
            color: #ff6b9d;
            padding: 10px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            border: 1px solid rgba(255,107,157,0.3);
            transition: all 0.3s;
        }
        .download-btn:hover {
            background: rgba(255,107,157,0.3);
        }
        .loading {
            display: none;
            text-align: center;
            margin-top: 20px;
        }
        .loading .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid rgba(255,107,157,0.2);
            border-top-color: #ff6b9d;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 10px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .loading p { color: #ff6b9d; font-size: 0.9rem; }
        .error {
            color: #ff4757;
            text-align: center;
            margin-top: 15px;
            display: none;
            font-size: 0.9rem;
        }
        .success {
            color: #2ed573;
            text-align: center;
            margin-top: 10px;
            display: none;
            font-size: 0.9rem;
        }
        .info-box {
            background: rgba(255,107,157,0.08);
            border-left: 3px solid #ff6b9d;
            padding: 12px 15px;
            border-radius: 0 8px 8px 0;
            margin-bottom: 20px;
            font-size: 0.85rem;
            color: #c0c0c0;
            line-height: 1.5;
        }
        .status {
            text-align: center;
            padding: 8px;
            border-radius: 8px;
            margin-bottom: 15px;
            font-size: 0.85rem;
            font-weight: 600;
        }
        .status.ready { background: rgba(46,213,115,0.1); color: #2ed573; border: 1px solid rgba(46,213,115,0.3); }
        .status.wait { background: rgba(255,107,157,0.1); color: #ff6b9d; border: 1px solid rgba(255,107,157,0.3); }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎙️ Voice Cloner</h1>
        <p class="subtitle">Загрузи референс → загрузи свой голос → получи клон</p>

        <div class="info-box">
            💡 <strong>Как работает:</strong><br>
            1. Загрузи <strong>reference</strong> — аудио голоса, который хочешь склонировать (девушка).<br>
            2. Загрузи <strong>свой голос</strong> — что сказать этим голосом.<br>
            3. FreeVC24 скопирует тембр reference на твою речь.
        </div>

        <div class="status ready" id="modelStatus">✅ Модель загружена (при деплое)</div>

        <!-- Шаг 1: Reference -->
        <div class="step">
            <h3>Шаг 1: Reference (чей голос клонировать)</h3>
            <div class="upload-area" onclick="document.getElementById('refFile').click()">
                <input type="file" id="refFile" accept="audio/*" onchange="refSelected(this)">
                <div class="upload-icon">🎀</div>
                <div class="upload-text">Загрузи <span>reference голос</span> (девушка)</div>
                <div class="file-name" id="refFileName"></div>
            </div>
            <button class="preset-btn" id="uploadRefBtn" onclick="uploadRef()" disabled>📤 Загрузить reference</button>
            <div class="success" id="refSuccess">✅ Reference загружен!</div>
        </div>

        <!-- Шаг 2: Source -->
        <div class="step">
            <h3>Шаг 2: Твой голос (что сказать)</h3>
            <div class="upload-area" onclick="document.getElementById('srcFile').click()">
                <input type="file" id="srcFile" accept="audio/*" onchange="srcSelected(this)">
                <div class="upload-icon">🎙️</div>
                <div class="upload-text">Загрузи <span>свой голос</span></div>
                <div class="file-name" id="srcFileName"></div>
            </div>
            <button class="preset-btn" id="convertBtn" onclick="convert()" disabled>✨ Конвертировать</button>
        </div>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Обрабатываю нейросетью... ⏳</p>
        </div>

        <div class="error" id="error"></div>

        <div class="result" id="result">
            <h3>🎀 Готово! Клонированный голос:</h3>
            <audio id="resultAudio" controls></audio>
            <a href="" class="download-btn" id="downloadBtn" download>⬇️ Скачать результат</a>
        </div>
    </div>

    <script>
        let refFile = null;
        let srcFile = null;
        let refUploaded = false;

        function refSelected(input) {
            if (input.files.length > 0) {
                refFile = input.files[0];
                document.getElementById('refFileName').textContent = refFile.name;
                document.getElementById('refFileName').style.display = 'block';
                document.getElementById('uploadRefBtn').disabled = false;
            }
        }

        function srcSelected(input) {
            if (input.files.length > 0) {
                srcFile = input.files[0];
                document.getElementById('srcFileName').textContent = srcFile.name;
                document.getElementById('srcFileName').style.display = 'block';
                document.getElementById('convertBtn').disabled = !refUploaded;
            }
        }

        function uploadRef() {
            if (!refFile) return;

            document.getElementById('uploadRefBtn').disabled = true;
            document.getElementById('uploadRefBtn').textContent = 'Загрузка...';

            const formData = new FormData();
            formData.append('audio', refFile);

            fetch('/upload_reference', { method: 'POST', body: formData })
                .then(r => {
                    if (!r.ok) throw new Error('Ошибка: ' + r.status);
                    return r.json();
                })
                .then(data => {
                    refUploaded = true;
                    document.getElementById('refSuccess').style.display = 'block';
                    document.getElementById('uploadRefBtn').textContent = '✅ Reference загружен';
                    if (srcFile) document.getElementById('convertBtn').disabled = false;
                })
                .catch(err => {
                    document.getElementById('error').textContent = '❌ ' + err.message;
                    document.getElementById('error').style.display = 'block';
                    document.getElementById('uploadRefBtn').disabled = false;
                    document.getElementById('uploadRefBtn').textContent = '📤 Загрузить reference';
                });
        }

        function convert() {
            if (!srcFile || !refUploaded) return;

            document.getElementById('loading').style.display = 'block';
            document.getElementById('error').style.display = 'none';
            document.getElementById('result').style.display = 'none';
            document.getElementById('convertBtn').disabled = true;

            const formData = new FormData();
            formData.append('audio', srcFile);

            fetch('/convert', { method: 'POST', body: formData })
                .then(r => {
                    if (!r.ok) throw new Error('Ошибка сервера: ' + r.status);
                    return r.blob();
                })
                .then(blob => {
                    const url = URL.createObjectURL(blob);
                    document.getElementById('resultAudio').src = url;
                    document.getElementById('downloadBtn').href = url;
                    document.getElementById('downloadBtn').download = 'cloned_voice_' + srcFile.name;
                    document.getElementById('result').style.display = 'block';
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('convertBtn').disabled = false;
                })
                .catch(err => {
                    document.getElementById('error').textContent = '❌ ' + err.message;
                    document.getElementById('error').style.display = 'block';
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('convertBtn').disabled = false;
                });
        }

        // Drag & drop для обоих
        document.querySelectorAll('.upload-area').forEach(area => {
            area.addEventListener('dragover', e => { e.preventDefault(); area.style.borderColor = '#ff6b9d'; });
            area.addEventListener('dragleave', () => { area.style.borderColor = 'rgba(255,107,157,0.4)'; });
            area.addEventListener('drop', e => {
                e.preventDefault();
                area.style.borderColor = 'rgba(255,107,157,0.4)';
                const files = e.dataTransfer.files;
                const input = area.querySelector('input');
                if (files.length > 0) {
                    input.files = files;
                    input.dispatchEvent(new Event('change'));
                }
            });
        });
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_PAGE)


@app.route('/upload_reference', methods=['POST'])
def upload_reference():
    global reference_loaded
    if 'audio' not in request.files:
        return {'error': 'No file'}, 400

    file = request.files['audio']
    file.save(REFERENCE_PATH)

    try:
        convert_to_wav_24k_mono(REFERENCE_PATH, REFERENCE_PATH)
        reference_loaded = True
        return {'status': 'ok'}
    except Exception as e:
        return {'error': str(e)}, 400


@app.route('/convert', methods=['POST'])
def convert():
    if not reference_loaded:
        return 'Reference not uploaded. Upload reference first!', 400

    if 'audio' not in request.files:
        return 'No file', 400

    file = request.files['audio']

    # Сохраняем source
    source_path = os.path.join(UPLOAD_FOLDER, 'source.wav')
    file.save(source_path)

    try:
        convert_to_wav_24k_mono(source_path, source_path)
    except Exception as e:
        return f'Audio conversion error: {e}', 400

    # Voice conversion
    output_path = os.path.join(UPLOAD_FOLDER, 'output.wav')

    try:
        _tts_model.voice_conversion_to_file(
            source_wav=source_path,
            target_wav=REFERENCE_PATH,
            file_path=output_path
        )
    except Exception as e:
        return f'Conversion error: {e}', 500

    return send_file(output_path, mimetype='audio/wav', as_attachment=False)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
