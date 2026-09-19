import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_bebas_123'

socketio = SocketIO(
    app,
    async_mode='eventlet',
    manage_session=False,
    cors_allowed_origins="*"
)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print("Client terhubung!")

@socketio.on('disconnect')
def handle_disconnect():
    print("Client terputus!")

@socketio.on('kirim_pesan')
def handle_send_message(data):
    print(f"Pesan diterima: {data}")
    emit('terima_pesan', data, broadcast=True)

if __name__ == '__main__':
    # Mengambil port otomatis dari Render, atau default ke 5000
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host="0.0.0.0", port=port)

