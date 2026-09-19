import os
import random
import string
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_bebas_123'

# KONFIGURASI FOLDER UNTUK MENYIMPAN FOTO PROFIL
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# KONFIGURASI DATABASE
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatgenz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# TABEL USER
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nomor_hp = db.Column(db.String(20), unique=True, nullable=False)
    pin = db.Column(db.String(8), unique=True, nullable=False)
    nama = db.Column(db.String(50), default='Pengguna Baru')
    foto_profil = db.Column(db.String(120), default='default.png')

# TABEL KONTAK (TEMAN)
class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# TABEL PESAN (DITAMBAHKAN KOLOM DIBACA)
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pesan = db.Column(db.Text, nullable=False)
    waktu = db.Column(db.DateTime, default=datetime.utcnow)
    dibaca = db.Column(db.Boolean, default=False)

# BUAT DATABASE
with app.app_context():
    db.create_all()

# KONFIGURASI SOCKET
socketio = SocketIO(app, async_mode='eventlet', manage_session=False, cors_allowed_origins="*")

def generate_pin():
    karakter = string.ascii_uppercase + string.digits
    while True:
        pin_baru = ''.join(random.choices(karakter, k=8))
        if not User.query.filter_by(pin=pin_baru).first():
            return pin_baru

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('chat'))

    if request.method == 'POST':
        nomor_hp = request.form.get('nomor_hp')
        user = User.query.filter_by(nomor_hp=nomor_hp).first()

        if user:
            session['user_id'] = user.id
        else:
            pin_baru = generate_pin()
            user_baru = User(nomor_hp=nomor_hp, pin=pin_baru)
            db.session.add(user_baru)
            db.session.commit()
            session['user_id'] = user_baru.id
            
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_sekarang_id = session['user_id']
    user_aktif = User.query.get(user_sekarang_id)
    
    if not user_aktif:
        session.clear()
        return redirect(url_for('login'))
    
    daftar_kontak_relasi = Contact.query.filter_by(user_id=user_sekarang_id).all()
    daftar_teman = []
    for relasi in daftar_kontak_relasi:
        teman = User.query.get(relasi.friend_id)
        if teman:
            # Hitung pesan yang belum dibaca dari teman ini
            unread_count = Message.query.filter_by(sender_id=teman.id, receiver_id=user_sekarang_id, dibaca=False).count()
            daftar_teman.append({'user': teman, 'unread': unread_count})

    return render_template('index.html', user_aktif=user_aktif, daftar_teman=daftar_teman)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user = User.query.get(session['user_id'])
    nama_baru = request.form.get('nama')
    foto = request.files.get('foto')
    
    if nama_baru:
        user.nama = nama_baru
        
    if foto and foto.filename != '':
        filename = secure_filename(foto.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
        new_filename = f"user_{user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
        
        foto.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
        user.foto_profil = new_filename
        
    db.session.commit()
    return redirect(url_for('chat'))

@app.route('/add_contact', methods=['POST'])
def add_contact():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    pin_teman = request.form.get('pin_teman')
    user_sekarang_id = session['user_id']
    teman = User.query.filter_by(pin=pin_teman).first()

    if teman:
        if teman.id == user_sekarang_id:
            return "Tidak bisa menambahkan PIN sendiri!", 400
        
        sudah_berteman = Contact.query.filter_by(user_id=user_sekarang_id, friend_id=teman.id).first()
        if sudah_berteman:
            return "Sudah ada di kontak!", 400

        db.session.add(Contact(user_id=user_sekarang_id, friend_id=teman.id))
        db.session.add(Contact(user_id=teman.id, friend_id=user_sekarang_id))
        db.session.commit()
        return redirect(url_for('chat'))
    else:
        return "PIN tidak ditemukan!", 404

@app.route('/get_chat/<int:friend_id>')
def get_chat(friend_id):
    if 'user_id' not in session:
        return jsonify([])
    
    user_id = session['user_id']
    
    # Tandai semua pesan dari teman ini menjadi terbaca (dibaca = True)
    pesan_belum_dibaca = Message.query.filter_by(sender_id=friend_id, receiver_id=user_id, dibaca=False).all()
    for p in pesan_belum_dibaca:
        p.dibaca = True
    db.session.commit()

    pesan_list = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == user_id))
    ).order_by(Message.waktu.asc()).all()

    return jsonify([{'sender_id': p.sender_id, 'pesan': p.pesan} for p in pesan_list])

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@socketio.on('connect')
def handle_connect():
    user_id = request.args.get('user_id')
    if user_id:
        join_room(f"user_{user_id}")

@socketio.on('kirim_pesan_private')
def handle_private_message(data):
    sender_id = data['sender_id']
    receiver_id = data['receiver_id']
    pesan_teks = data['pesan']

    # Pesan baru default dibaca = False
    pesan_baru = Message(sender_id=sender_id, receiver_id=receiver_id, pesan=pesan_teks, dibaca=False)
    db.session.add(pesan_baru)
    db.session.commit()

    chat_data = {'sender_id': sender_id, 'receiver_id': receiver_id, 'pesan': pesan_teks}
    emit('terima_pesan_private', chat_data, room=f"user_{receiver_id}")
    emit('terima_pesan_private', chat_data, room=f"user_{sender_id}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host="0.0.0.0", port=port)
