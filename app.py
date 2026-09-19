from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_bebas_123'

# Inisialisasi SocketIO dengan async_mode eventlet
socketio = SocketIO(app, async_mode='eventlet')

@app.route('/')
def index():
    return render_template('index.html')

# Event ketika ada pesan dikirim dari client
@socketio.on('kirim_pesan')
def handle_send_message(data):
    # Menyebarkan pesan ke semua client yang terhubung secara real-time
    emit('terima_pesan', data, broadcast=True)

if __name__ == '__main__':
    # Menjalankan aplikasi menggunakan socketio.run
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
