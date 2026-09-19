from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_bebas_123'

# Inisialisasi SocketIO dengan CORS terbuka untuk semua asal domain (www maupun non-www)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print("Client berhasil terhubung via Socket.IO")

@socketio.on('disconnect')
def handle_disconnect():
    print("Client terputus dari Socket.IO")

# Event ketika ada pesan dikirim dari client
@socketio.on('kirim_pesan')
def handle_send_message(data):
    print(f"Pesan diterima di server: {data}")
    # Menyebarkan pesan ke semua client yang terhubung secara real-time
    emit('terima_pesan', data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

