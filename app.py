from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_bebas_123'

# Konfigurasi SocketIO eksplisit untuk menangani proxy Render dan mencegah timeout
socketio = SocketIO(
    app,
    async_mode='gevent',
    manage_session=False,
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True
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
    socketio.run(app, host="0.0.0.0", port=5000)

