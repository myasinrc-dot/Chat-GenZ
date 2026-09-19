import os
import random
import string
import base64
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_bebas_123'

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatgenz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nomor_hp = db.Column(db.String(20), unique=True, nullable=False)
    pin = db.Column(db.String(8), unique=True, nullable=False)
    nama = db.Column(db.String(50), default='Pengguna Baru')
    foto_profil = db.Column(db.String(120), default='default.png')

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_grup = db.Column(db.String(50), nullable=False)
    kode_grup = db.Column(db.String(8), unique=True, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    pesan = db.Column(db.Text, nullable=False)
    tipe = db.Column(db.String(10), default='text')
    waktu = db.Column(db.DateTime, default=datetime.utcnow)
    diterima = db.Column(db.Boolean, default=False)  # Centang 2 abu-abu
    dibaca = db.Column(db.Boolean, default=False)    # Centang 2 biru

with app.app_context():
    db.create_all()

socketio = SocketIO(app, async_mode='eventlet', manage_session=False, cors_allowed_origins="*")

def generate_pin(length=8, is_group=False):
    karakter = string.ascii_uppercase + string.digits
    while True:
        kode = ''.join(random.choices(karakter, k=length))
        if not is_group:
            if not User.query.filter_by(pin=kode).first():
                return kode
        else:
            if not Group.query.filter_by(kode_grup=kode).first():
                return kode

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
            pin_baru = generate_pin(8, False)
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
            unread_count = Message.query.filter_by(sender_id=teman.id, receiver_id=user_sekarang_id, group_id=None, dibaca=False).count()
            daftar_teman.append({'user': teman, 'unread': unread_count})

    keanggotaan = GroupMember.query.filter_by(user_id=user_sekarang_id).all()
    daftar_grup = []
    for m in keanggotaan:
        g = Group.query.get(m.group_id)
        if g:
            daftar_grup.append({'group': g})

    return render_template('index.html', user_aktif=user_aktif, daftar_teman=daftar_teman, daftar_grup=daftar_grup)

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
            return redirect(url_for('chat'))

        db.session.add(Contact(user_id=user_sekarang_id, friend_id=teman.id))
        db.session.add(Contact(user_id=teman.id, friend_id=user_sekarang_id))
        db.session.commit()

        # Emit real-time ke teman agar kontak langsung masuk tanpa refresh!
        socketio.emit('kontak_baru', {'user_id': user_sekarang_id}, room=f"user_{teman.id}")

        return redirect(url_for('chat'))
    else:
        return "PIN tidak ditemukan!", 404

@app.route('/create_group', methods=['POST'])
def create_group():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    nama_grup = request.form.get('nama_grup')
    user_id = session['user_id']
    if nama_grup:
        kode_grup = generate_pin(8, True)
        grup_baru = Group(nama_grup=nama_grup, kode_grup=kode_grup, creator_id=user_id)
        db.session.add(grup_baru)
        db.session.commit()
        db.session.add(GroupMember(group_id=grup_baru.id, user_id=user_id))
        db.session.commit()
    return redirect(url_for('chat'))

@app.route('/join_group', methods=['POST'])
def join_group():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    kode_grup = request.form.get('kode_grup')
    user_id = session['user_id']
    grup = Group.query.filter_by(kode_grup=kode_grup).first()
    if grup:
        sudah_gabung = GroupMember.query.filter_by(group_id=grup.id, user_id=user_id).first()
        if not sudah_gabung:
            db.session.add(GroupMember(group_id=grup.id, user_id=user_id))
            db.session.commit()
        return redirect(url_for('chat'))
    else:
        return "Kode Grup tidak ditemukan!", 404

@app.route('/get_chat/<int:friend_id>')
def get_chat(friend_id):
    if 'user_id' not in session:
        return jsonify([])
    user_id = session['user_id']
    
    # Tandai semua pesan dari teman ini menjadi Diterima dan Dibaca
    pesan_list_db = Message.query.filter_by(sender_id=friend_id, receiver_id=user_id, group_id=None).all()
    ada_update = False
    for p in pesan_list_db:
        if not p.diterima or not p.dibaca:
            p.diterima = True
            p.dibaca = True
            ada_update = True
    if ada_update:
        db.session.commit()
        socketio.emit('pesan_dibaca', {'reader_id': user_id, 'partner_id': friend_id}, room=f"user_{friend_id}")

    pesan_list = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == friend_id) & (Message.group_id == None)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == user_id) & (Message.group_id == None))
    ).order_by(Message.waktu.asc()).all()

    return jsonify([{
        'id': p.id,
        'sender_id': p.sender_id,
        'pesan': p.pesan,
        'tipe': p.tipe,
        'diterima': p.diterima,
        'dibaca': p.dibaca
    } for p in pesan_list])

@app.route('/get_group_chat/<int:group_id>')
def get_group_chat(group_id):
    if 'user_id' not in session:
        return jsonify([])
    user_id = session['user_id']
    member = GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
    if not member:
        return jsonify([])
    
    pesan_list = Message.query.filter_by(group_id=group_id).order_by(Message.waktu.asc()).all()
    result = []
    for p in pesan_list:
        sender = User.query.get(p.sender_id)
        result.append({
            'id': p.id,
            'sender_id': p.sender_id,
            'sender_name': sender.nama if sender else 'Unknown',
            'pesan': p.pesan,
            'tipe': p.tipe
        })
    return jsonify(result)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@socketio.on('connect')
def handle_connect():
    user_id = request.args.get('user_id')
    if user_id:
        join_room(f"user_{user_id}")
        members = GroupMember.query.filter_by(user_id=user_id).all()
        for m in members:
            join_room(f"group_{m.group_id}")

@socketio.on('kirim_pesan_private')
def handle_private_message(data):
    sender_id = int(data['sender_id'])
    receiver_id = int(data['receiver_id'])
    pesan_teks = data['pesan']
    tipe = data.get('tipe', 'text')

    if tipe == 'image' and pesan_teks.startswith('data:image'):
        header, encoded = pesan_teks.split(",", 1)
        ext = header.split('/')[1].split(';')[0]
        filename = f"img_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    # Default diterima=False, dibaca=False -> Centang 1
    pesan_baru = Message(sender_id=sender_id, receiver_id=receiver_id, pesan=pesan_teks, tipe=tipe, diterima=False, dibaca=False)
    db.session.add(pesan_baru)
    db.session.commit()

    chat_data = {
        'id': pesan_baru.id,
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'pesan': pesan_teks,
        'tipe': tipe,
        'diterima': False,
        'dibaca': False
    }

    emit('terima_pesan_private', chat_data, room=f"user_{receiver_id}")
    emit('terima_pesan_private', chat_data, room=f"user_{sender_id}")

@socketio.on('pesan_diterima_client')
def handle_pesan_diterima(data):
    msg_id = data.get('message_id')
    sender_id = data.get('sender_id')
    msg = Message.query.get(msg_id)
    if msg and not msg.diterima:
        msg.diterima = True
        db.session.commit()
        socketio.emit('status_diterima', {'message_id': msg_id}, room=f"user_{sender_id}")

@socketio.on('kirim_pesan_grup')
def handle_group_message(data):
    sender_id = int(data['sender_id'])
    group_id = int(data['group_id'])
    pesan_teks = data['pesan']
    tipe = data.get('tipe', 'text')

    if tipe == 'image' and pesan_teks.startswith('data:image'):
        header, encoded = pesan_teks.split(",", 1)
        ext = header.split('/')[1].split(';')[0]
        filename = f"gimg_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    pesan_baru = Message(sender_id=sender_id, group_id=group_id, pesan=pesan_teks, tipe=tipe)
    db.session.add(pesan_baru)
    db.session.commit()

    sender = User.query.get(sender_id)
    chat_data = {
        'id': pesan_baru.id,
        'sender_id': sender_id,
        'sender_name': sender.nama if sender else 'Unknown',
        'group_id': group_id,
        'pesan': pesan_teks,
        'tipe': tipe
    }

    emit('terima_pesan_grup', chat_data, room=f"group_{group_id}")

@socketio.on('typing_private')
def handle_typing_private(data):
    receiver_id = data['receiver_id']
    sender_id = data['sender_id']
    is_typing = data['is_typing']
    emit('status_typing', {'sender_id': sender_id, 'is_typing': is_typing}, room=f"user_{receiver_id}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host="0.0.0.0", port=port)
