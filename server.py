import os
import tempfile
import numpy as np
import soundfile as sf
import librosa
import pyworld as pw
from flask import Flask, request, render_template_string, send_file
from pedalboard import Pedalboard, Compressor, Gain, HighpassFilter, LowShelfFilter, HighShelfFilter
from pydub import AudioSegment

app = Flask(__name__)
UPLOAD_FOLDER = tempfile.mkdtemp()

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voice Changer — Девочка</title>
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
        .controls { margin-bottom: 25px; }
        .control-group { margin-bottom: 18px; }
        .control-label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 0.9rem;
            color: #b0b0b0;
        }
        .control-label span { color: #ff6b9d; font-weight: 600; }
        input[type="range"] {
            width: 100%;
            -webkit-appearance: none;
            height: 8px;
            border-radius: 4px;
            background: rgba(255,255,255,0.1);
            outline: none;
        }
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: linear-gradient(135deg, #ff6b9d, #c44569);
            cursor: pointer;
            box-shadow: 0 2px 10px rgba(255,107,157,0.5);
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
        <p class="subtitle">Преврати свой голос в голос милой девочки</p>

        <div class="info-box">
            💡 <strong>Твой голос детский</strong> — настройки оптимизированы. 
            Pitch +6, Formant +4, Speed 1.15x — идеально для девочки 14-16 лет.
            <br><br>
            🔒 <strong>Безопасно:</strong> оригинал невозможно восстановить.
        </div>

        <div class="upload-area" onclick="document.getElementById('file').click()">
            <input type="file" id="file" accept="audio/*" onchange="fileSelected(this)">
            <div class="upload-icon">📁</div>
            <div class="upload-text">Нажми или перетащи <span>аудиофайл</span></div>
            <div class="file-name" id="fileName"></div>
        </div>

        <div class="controls">
            <div class="control-group">
                <div class="control-label">
                    <span>Pitch (тон)</span>
                    <span id="pitchVal">+6</span>
                </div>
                <input type="range" id="pitch" min="-12" max="12" value="6" step="1" oninput="updateVal('pitchVal', this.value)">
            </div>
            <div class="control-group">
                <div class="control-label">
                    <span>Formant (тембр)</span>
                    <span id="formantVal">+4</span>
                </div>
                <input type="range" id="formant" min="-8" max="8" value="4" step="1" oninput="updateVal('formantVal', this.value)">
            </div>
            <div class="control-group">
                <div class="control-label">
                    <span>Speed (скорость)</span>
                    <span id="speedVal">1.15x</span>
                </div>
                <input type="range" id="speed" min="0.5" max="2.0" value="1.15" step="0.05" oninput="updateVal('speedVal', this.value + 'x')">
            </div>
            <div class="control-group">
                <div class="control-label">
                    <span>Cuteness (милость)</span>
                    <span id="cuteVal">80%</span>
                </div>
                <input type="range" id="cute" min="0" max="100" value="80" step="5" oninput="updateVal('cuteVal', this.value + '%')">
            </div>
        </div>

        <button class="preset-btn" id="convertBtn" onclick="convert()" disabled>✨ Конвертировать</button>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Обрабатываю голос... ⏳</p>
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

        function updateVal(id, val) {
            document.getElementById(id).textContent = val;
        }

        function convert() {
            if (!selectedFile) return;

            document.getElementById('loading').style.display = 'block';
            document.getElementById('error').style.display = 'none';
            document.getElementById('result').style.display = 'none';
            document.getElementById('convertBtn').disabled = true;

            const formData = new FormData();
            formData.append('audio', selectedFile);
            formData.append('pitch', document.getElementById('pitch').value);
            formData.append('formant', document.getElementById('formant').value);
            formData.append('speed', document.getElementById('speed').value);
            formData.append('cute', document.getElementById('cute').value);

            fetch('/convert', { method: 'POST', body: formData })
                .then(r => {
                    if (!r.ok) throw new Error('Ошибка сервера');
                    return r.blob();
                })
                .then(blob => {
                    const url = URL.createObjectURL(blob);
                    document.getElementById('resultAudio').src = url;
                    document.getElementById('downloadBtn').href = url;
                    document.getElementById('downloadBtn').download = 'cute_voice_' + selectedFile.name;
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


def apply_voice_change(audio_path, pitch_shift=6, formant_shift=4, speed=1.15, cute=80):
    """Превращает мужской/детский голос в женский/девочку через pyworld."""

    # Загружаем аудио
    y, sr = librosa.load(audio_path, sr=24000, mono=True)

    # 1. Изменяем скорость
    if speed != 1.0:
        y = librosa.effects.time_stretch(y, rate=speed)

    # 2. WORLD vocoder — pitch + formant
    f0, sp, ap = pw.wav2world(y.astype(np.float64), sr)

    # Pitch shift (тон)
    f0_new = f0 * (2 ** (pitch_shift / 12))
    f0_new[f0 == 0] = 0

    # Formant shift (тембр)
    sp_new = np.zeros_like(sp)
    for i in range(sp.shape[0]):
        if f0[i] == 0:
            sp_new[i] = sp[i]
            continue
        shift_factor = 2 ** (formant_shift / 12)
        freq_axis = np.linspace(0, sr // 2, sp.shape[1])
        new_freq_axis = freq_axis * shift_factor
        sp_new[i] = np.interp(freq_axis, new_freq_axis, sp[i], left=sp[i][0], right=sp[i][-1])

    # Синтез
    y_world = pw.synthesize(f0_new, sp_new, ap, sr)

    # 3. Доп. pitch shift
    y_shifted = librosa.effects.pitch_shift(
        y_world.astype(np.float32), sr=sr, n_steps=pitch_shift * 0.3
    )

    # 4. Педалборд
    cute_factor = cute / 100.0
    board = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=180 + cute_factor * 120),
        LowShelfFilter(cutoff_frequency_hz=250, gain_db=-3 - cute_factor * 4),
        HighShelfFilter(cutoff_frequency_hz=3000, gain_db=2 + cute_factor * 4),
        Compressor(threshold_db=-20, ratio=3.0),
        Gain(gain_db=2),
    ])

    y_final = board(y_shifted, sr)
    y_final = y_final / np.max(np.abs(y_final)) * 0.95

    return y_final, sr


@app.route('/')
def index():
    return render_template_string(HTML_PAGE)


@app.route('/convert', methods=['POST'])
def convert():
    if 'audio' not in request.files:
        return 'No file', 400

    file = request.files['audio']
    pitch = float(request.form.get('pitch', 6))
    formant = float(request.form.get('formant', 4))
    speed = float(request.form.get('speed', 1.15))
    cute = float(request.form.get('cute', 80))

    input_path = os.path.join(UPLOAD_FOLDER, 'input.wav')
    file.save(input_path)

    try:
        audio = AudioSegment.from_file(input_path)
        audio.export(input_path, format='wav')
    except:
        pass

    y_out, sr = apply_voice_change(input_path, pitch, formant, speed, cute)

    output_path = os.path.join(UPLOAD_FOLDER, 'output.wav')
    sf.write(output_path, y_out, sr)

    return send_file(output_path, mimetype='audio/wav', as_attachment=False)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
