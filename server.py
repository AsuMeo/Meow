import os
import tempfile
import numpy as np
import soundfile as sf
from flask import Flask, request, render_template_string, send_file
from pydub import AudioSegment

app = Flask(__name__)
UPLOAD_FOLDER = tempfile.mkdtemp()

# Lazy load TTS model
_tts_model = None

def get_tts_model():
    global _tts_model
    if _tts_model is None:
        from TTS.api import TTS
        print("Loading FreeVC24 model... (first time, ~1.6GB)")
        _tts_model = TTS("voice_conversion_models/multilingual/vctk/freevc24")
        print("Model loaded!")
    return _tts_model


HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voice Changer — FreeVC24</title>
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
        .upload-area {
            border: 2px dashed rgba(255,107,157,0.4);
            border-radius: 16px;
            padding: 40px 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            margin-bottom: 25px;
            position: relative;
        }
        .upload-area:hover {
            border-color: #ff6b9d;
            background: rgba(255,107,157,0.05);
        }
        .upload-area input { display: none; }
        .upload-icon { font-size: 3rem; margin-bottom: 10px; }
        .upload-text { color: #a0a0a0; font-size: 0.95rem; }
        .upload-text span { color: #ff6b9d; font-weight: 600; }
        .file-name {
            color: #ff6b9d;
            font-weight: 600;
            margin-top: 10px;
            display: none;
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
        .loading .info {
            color: #8892b0;
            font-size: 0.75rem;
            margin-top: 8px;
        }
        .error {
            color: #ff4757;
            text-align: center;
            margin-top: 15px;
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
    </style>
</head>
<body>
    <div class="container">
        <h1>🎙️ Voice Changer</h1>
        <p class="subtitle">AI Voice Conversion — FreeVC24</p>

        <div class="info-box">
            💡 <strong>FreeVC24</strong> — нейросеть, которая реально меняет голос.
            Твой голос → голос девушки. Не просто pitch shift, а полная конвертация тембра.
            <br><br>
            🔒 <strong>Первый запуск:</strong> модель ~1.6GB скачивается на сервер (1-2 мин).
            <br>
            ⏱️ <strong>Обработка:</strong> ~5-10 сек на 1 сек аудио (CPU).
        </div>

        <div class="upload-area" onclick="document.getElementById('file').click()">
            <input type="file" id="file" accept="audio/*" onchange="fileSelected(this)">
            <div class="upload-icon">📁</div>
            <div class="upload-text">Нажми или перетащи <span>аудиофайл</span></div>
            <div class="file-name" id="fileName"></div>
        </div>

        <button class="preset-btn" id="convertBtn" onclick="convert()" disabled>✨ Конвертировать в девочку</button>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Обрабатываю нейросетью... ⏳</p>
            <p class="info">Модель загружается при первом запуске (~1.6GB)</p>
        </div>

        <div class="error" id="error"></div>

        <div class="result" id="result">
            <h3>🎀 Готово! Твой новый голос:</h3>
            <audio id="resultAudio" controls></audio>
            <a href="" class="download-btn" id="downloadBtn" download>⬇️ Скачать результат</a>
        </div>
    </div>

    <script>
        let selectedFile = null;

        function fileSelected(input) {
            if (input.files.length > 0) {
                selectedFile = input.files[0];
                document.getElementById('fileName').textContent = selectedFile.name;
                document.getElementById('fileName').style.display = 'block';
                document.getElementById('convertBtn').disabled = false;
            }
        }

        function convert() {
            if (!selectedFile) return;

            document.getElementById('loading').style.display = 'block';
            document.getElementById('error').style.display = 'none';
            document.getElementById('result').style.display = 'none';
            document.getElementById('convertBtn').disabled = true;

            const formData = new FormData();
            formData.append('audio', selectedFile);

            fetch('/convert', { method: 'POST', body: formData })
                .then(r => {
                    if (!r.ok) throw new Error('Ошибка сервера: ' + r.status);
                    return r.blob();
                })
                .then(blob => {
                    const url = URL.createObjectURL(blob);
                    document.getElementById('resultAudio').src = url;
                    document.getElementById('downloadBtn').href = url;
                    document.getElementById('downloadBtn').download = 'female_voice_' + selectedFile.name;
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

        const uploadArea = document.querySelector('.upload-area');
        uploadArea.addEventListener('dragover', e => { e.preventDefault(); uploadArea.style.borderColor = '#ff6b9d'; });
        uploadArea.addEventListener('dragleave', () => { uploadArea.style.borderColor = 'rgba(255,107,157,0.4)'; });
        uploadArea.addEventListener('drop', e => {
            e.preventDefault();
            uploadArea.style.borderColor = 'rgba(255,107,157,0.4)';
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                document.getElementById('file').files = files;
                fileSelected(document.getElementById('file'));
            }
        });
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_PAGE)


@app.route('/convert', methods=['POST'])
def convert():
    if 'audio' not in request.files:
        return 'No file', 400

    file = request.files['audio']

    # Сохраняем входной файл
    input_path = os.path.join(UPLOAD_FOLDER, 'input.wav')
    file.save(input_path)

    # Конвертируем в wav 24kHz mono
    try:
        audio = AudioSegment.from_file(input_path)
        audio = audio.set_frame_rate(24000).set_channels(1)
        audio.export(input_path, format='wav')
    except Exception as e:
        return f'Audio conversion error: {e}', 400

    # Загружаем модель (lazy)
    try:
        tts = get_tts_model()
    except Exception as e:
        return f'Model load error: {e}', 500

    # Voice conversion
    output_path = os.path.join(UPLOAD_FOLDER, 'output.wav')
    reference_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference.wav')

    try:
        tts.voice_conversion_to_file(
            source_wav=input_path,
            target_wav=reference_path,
            file_path=output_path
        )
    except Exception as e:
        return f'Conversion error: {e}', 500

    return send_file(output_path, mimetype='audio/wav', as_attachment=False)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
