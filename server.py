import os
import re
import requests
import json
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

VK_API = "https://api.vk.com/method"
API_VERSION = "5.199"


def vk_request(method, token, **params):
    """Запрос к VK API"""
    params['access_token'] = token
    params['v'] = API_VERSION
    try:
        resp = requests.get(f"{VK_API}/{method}", params=params, timeout=30)
        data = resp.json()
        return data.get('response', data.get('error'))
    except Exception as e:
        return {'error': str(e)}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/auth', methods=['POST'])
def auth():
    """Авторизация по токену из URL"""
    data = request.json
    url = data.get('url', '')

    # Вытаскиваем токен из URL
    token_match = re.search(r'access_token=([^&]+)', url)
    if not token_match:
        return jsonify({'error': 'Токен не найден в URL'}), 400

    token = token_match.group(1)

    # Проверяем токен
    user_info = vk_request('users.get', token, fields='photo_100,online')
    if isinstance(user_info, dict) and 'error' in user_info:
        return jsonify({'error': 'Неверный токен'}), 400

    user = user_info[0] if isinstance(user_info, list) else user_info

    return jsonify({
        'token': token,
        'user': {
            'id': user.get('id'),
            'name': user.get('first_name', '') + ' ' + user.get('last_name', ''),
            'photo': user.get('photo_100', ''),
            'online': user.get('online', 0)
        }
    })


@app.route('/api/dialogs', methods=['POST'])
def get_dialogs():
    """Получение списка диалогов"""
    token = request.json.get('token')
    offset = request.json.get('offset', 0)

    result = vk_request('messages.getConversations', token, count=20, offset=offset, extended=1)

    if isinstance(result, dict) and 'error' in result:
        return jsonify(result), 400

    dialogs = []
    profiles = {p['id']: p for p in result.get('profiles', [])}
    groups = {g['id']: g for g in result.get('groups', [])}

    for item in result.get('items', []):
        conv = item.get('conversation', {})
        msg = item.get('last_message', {})
        peer = conv.get('peer', {})
        peer_id = peer.get('id')
        peer_type = peer.get('type')

        # Определяем имя и аватарку
        name = "Unknown"
        photo = ""

        if peer_type == 'user':
            profile = profiles.get(peer_id, {})
            name = profile.get('first_name', '') + ' ' + profile.get('last_name', '')
            photo = profile.get('photo_100', '')
        elif peer_type == 'group':
            group = groups.get(-peer_id, {})
            name = group.get('name', 'Group')
            photo = group.get('photo_100', '')
        elif peer_type == 'chat':
            chat_settings = conv.get('chat_settings', {})
            name = chat_settings.get('title', 'Chat')
            photo = chat_settings.get('photo', {}).get('photo_100', '')

        dialogs.append({
            'id': peer_id,
            'type': peer_type,
            'name': name.strip(),
            'photo': photo,
            'unread': conv.get('unread_count', 0),
            'last_message': msg.get('text', ''),
            'date': msg.get('date', 0),
            'from_id': msg.get('from_id', 0)
        })

    return jsonify({'dialogs': dialogs})


@app.route('/api/messages', methods=['POST'])
def get_messages():
    """Получение сообщений диалога"""
    token = request.json.get('token')
    peer_id = request.json.get('peer_id')
    offset = request.json.get('offset', 0)

    result = vk_request('messages.getHistory', token, peer_id=peer_id, count=50, offset=offset, extended=1)

    if isinstance(result, dict) and 'error' in result:
        return jsonify(result), 400

    messages = []
    profiles = {p['id']: p for p in result.get('profiles', [])}

    for msg in result.get('items', []):
        from_id = msg.get('from_id', 0)
        profile = profiles.get(from_id, {})

        messages.append({
            'id': msg.get('id'),
            'text': msg.get('text', ''),
            'date': msg.get('date', 0),
            'from_id': from_id,
            'out': msg.get('out', 0),
            'name': profile.get('first_name', '') + ' ' + profile.get('last_name', ''),
            'photo': profile.get('photo_50', ''),
            'attachments': msg.get('attachments', [])
        })

    return jsonify({'messages': messages})


@app.route('/api/send', methods=['POST'])
def send_message():
    """Отправка сообщения"""
    token = request.json.get('token')
    peer_id = request.json.get('peer_id')
    text = request.json.get('text', '')

    result = vk_request('messages.send', token, peer_id=peer_id, message=text, random_id=0)

    return jsonify({'result': result})


@app.route('/api/upload_photo', methods=['POST'])
def upload_photo():
    """Загрузка фото"""
    token = request.json.get('token')
    peer_id = request.json.get('peer_id')
    photo_data = request.json.get('photo')  # base64

    # Получаем сервер для загрузки
    upload_server = vk_request('photos.getMessagesUploadServer', token, peer_id=peer_id)
    if isinstance(upload_server, dict) and 'error' in upload_server:
        return jsonify(upload_server), 400

    upload_url = upload_server.get('upload_url')

    # Загружаем фото
    import base64
    photo_bytes = base64.b64decode(photo_data.split(',')[1])
    files = {'photo': ('photo.jpg', photo_bytes, 'image/jpeg')}

    upload_resp = requests.post(upload_url, files=files, timeout=30).json()

    # Сохраняем
    save_result = vk_request('photos.saveMessagesPhoto', token, 
        photo=upload_resp.get('photo'),
        server=upload_resp.get('server'),
        hash=upload_resp.get('hash')
    )

    if isinstance(save_result, list) and len(save_result) > 0:
        photo = save_result[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"

        # Отправляем сообщение с фото
        result = vk_request('messages.send', token, peer_id=peer_id, attachment=attachment, random_id=0)
        return jsonify({'result': result})

    return jsonify({'error': 'Failed to save photo'}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
