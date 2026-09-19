import os
import random
import string
import base64
from datetime import datetime, timedelta
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

socketio = SocketIO(app, async_mode='eventlet', manage_session=False, cors_allowed_origins="*", max_http_buffer_size=100000000)

online_users = set()

# Waktu lokal WITA (UTC+8) agar last seen akurat sesuai lokasi Anda
def get_waktu_wita():
    return datetime.utcnow() + timedelta(hours=8)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nomor_hp = db.Column(db.String(20), unique=True, nullable=False)
    pin = db.Column(db.String(8), unique=True, nullable=False)
    nama = db.Column(db.String(50), default='Pengguna Baru')
    foto_profil = db.Column(db.String(120), default='default.png')
    last_seen = db.Column(db.DateTime, default=get_waktu_wita)

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
    last_read_id = db.Column(db.Integer, default=0) # Untuk notif badge grup

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    pesan = db.Column(db.Text, nullable=False)
    tipe = db.Column(db.String(10), default='text')
    waktu = db.Column(db.DateTime, default=get_waktu_wita)
    diterima = db.Column(db.Boolean, default=False)
    dibaca = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

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
            user.last_seen = get_waktu_wita()
            db.session.commit()
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
    
    # Update status online ketika memuat dashboard
    user_aktif.last_seen = get_waktu_wita()
    db.session.commit()
    
    daftar_kontak_relasi = Contact.query.filter_by(user_id=user_sekarang_id).all()
    daftar_teman = []
    for relasi in daftar_kontak_relasi:
        teman = User.query.get(relasi.friend_id)
        if teman:
            unread_count = Message.query.filter_by(sender_id=teman.id, receiver_id=user_sekarang_id, group_id=None, dibaca=False).count()
            is_online = teman.id in online_users
            last_seen_str = "Online"
            if not is_online and teman.last_seen:
                last_seen_str = teman.last_seen.strftime("Terakhir online: %d/%m/%Y jam %H:%M")
                
            daftar_teman.append({'user': teman, 'unread': unread_count, 'is_online': is_online, 'last_seen_str': last_seen_str})

    keanggotaan = GroupMember.query.filter_by(user_id=user_sekarang_id).all()
    daftar_grup = []
    for m in keanggotaan:
        g = Group.query.get(m.group_id)
        if g:
            # Hitung pesan grup yang masuk setelah last_read_id
            unread_grup = Message.query.filter(Message.group_id == g.id, Message.id > m.last_read_id).count()
            daftar_grup.append({'group': g, 'unread': unread_grup})

    return render_template('index.html', user_aktif=user_aktif, daftar_teman=daftar_teman, daftar_grup=daftar_grup)

@app.route('/room/private/<int:friend_id>')
def room_private(friend_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    user_aktif = User.query.get(user_id)
    teman = User.query.get(friend_id)
    if not teman: return redirect(url_for('chat'))
    
    pesan_list = Message.query.filter_by(sender_id=friend_id, receiver_id=user_id, group_id=None, dibaca=False).all()
    if pesan_list:
        for p in pesan_list:
            p.diterima = True
            p.dibaca = True
        db.session.commit()
        socketio.emit('pesan_dibaca', {'reader_id': user_id, 'partner_id': friend_id}, room=f"user_{friend_id}")

    is_online = friend_id in online_users
    last_seen_str = "Online" if is_online else (teman.last_seen.strftime("Terakhir online: %d/%m/%Y jam %H:%M") if teman.last_seen else "")

    return render_template('room.html', user_aktif=user_aktif, target=teman, tipe='private', is_online=is_online, last_seen_str=last_seen_str)

@app.route('/room/group/<int:group_id>')
def room_group(group_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    user_aktif = User.query.get(user_id)
    grup = Group.query.get(group_id)
    member = GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
    if not grup or not member: return redirect(url_for('chat'))
    
    # Update last_read_id grup saat user masuk room
    last_msg = Message.query.filter_by(group_id=group_id).order_by(Message.id.desc()).first()
    if last_msg:
        member.last_read_id = last_msg.id
        db.session.commit()

    return render_template('room.html', user_aktif=user_aktif, target=grup, tipe='group', is_online=True, last_seen_str="Grup Chat")

@app.route('/get_messages/<int:friend_id>')
def get_messages(friend_id):
    if 'user_id' not in session: return jsonify([])
    user_id = session['user_id']
    pesan_list = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == friend_id) & (Message.group_id == None)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == user_id) & (Message.group_id == None))
    ).order_by(Message.waktu.asc()).all()
    return jsonify([{'id': p.id, 'sender_id': p.sender_id, 'pesan': p.pesan, 'tipe': p.tipe, 'diterima': p.diterima, 'dibaca': p.dibaca} for p in pesan_list])

@app.route('/get_group_messages/<int:group_id>')
def get_group_messages(group_id):
    if 'user_id' not in session: return jsonify([])
    pesan_list = Message.query.filter_by(group_id=group_id).order_by(Message.waktu.asc()).all()
    result = []
    for p in pesan_list:
        sender = User.query.get(p.sender_id)
        result.append({'id': p.id, 'sender_id': p.sender_id, 'sender_name': sender.nama if sender else 'Unknown', 'pesan': p.pesan, 'tipe': p.tipe})
    return jsonify(result)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    nama_baru = request.form.get('nama')
    foto = request.files.get('foto')
    if nama_baru: user.nama = nama_baru
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
    if 'user_id' not in session: return redirect(url_for('login'))
    pin_teman = request.form.get('pin_teman')
    user_sekarang_id = session['user_id']
    teman = User.query.filter_by(pin=pin_teman).first()
    if teman and teman.id != user_sekarang_id:
        if not Contact.query.filter_by(user_id=user_sekarang_id, friend_id=teman.id).first():
            db.session.add(Contact(user_id=user_sekarang_id, friend_id=teman.id))
            db.session.add(Contact(user_id=teman.id, friend_id=user_sekarang_id))
            db.session.commit()
            socketio.emit('kontak_baru', {'user_id': user_sekarang_id}, room=f"user_{teman.id}")
    return redirect(url_for('chat'))

@app.route('/create_group', methods=['POST'])
def create_group():
    if 'user_id' not in session: return redirect(url_for('login'))
    nama_grup = request.form.get('nama_grup')
    user_id = session['user_id']
    if nama_grup:
        grup_baru = Group(nama_grup=nama_grup, kode_grup=generate_pin(8, True), creator_id=user_id)
        db.session.add(grup_baru)
        db.session.commit()
        db.session.add(GroupMember(group_id=grup_baru.id, user_id=user_id))
        db.session.commit()
    return redirect(url_for('chat'))

@app.route('/join_group', methods=['POST'])
def join_group():
    if 'user_id' not in session: return redirect(url_for('login'))
    kode_grup = request.form.get('kode_grup')
    user_id = session['user_id']
    grup = Group.query.filter_by(kode_grup=kode_grup).first()
    if grup and not GroupMember.query.filter_by(group_id=grup.id, user_id=user_id).first():
        db.session.add(GroupMember(group_id=grup.id, user_id=user_id))
        db.session.commit()
    return redirect(url_for('chat'))

@app.route('/logout')
def logout():
    user = User.query.get(session.get('user_id'))
    if user:
        user.last_seen = get_waktu_wita()
        db.session.commit()
    session.clear()
    return redirect(url_for('login'))

@socketio.on('connect')
def handle_connect():
    user_id = request.args.get('user_id')
    if user_id:
        u_id = int(user_id)
        online_users.add(u_id)
        join_room(f"user_{u_id}")
        user = User.query.get(u_id)
        if user:
            user.last_seen = get_waktu_wita()
            db.session.commit()

        pending_msgs = Message.query.filter_by(receiver_id=u_id, diterima=False).all()
        for msg in pending_msgs:
            msg.diterima = True
            db.session.commit()
            socketio.emit('status_diterima', {'message_id': msg.id}, room=f"user_{msg.sender_id}")

        for m in GroupMember.query.filter_by(user_id=u_id).all():
            join_room(f"group_{m.group_id}")
            
        socketio.emit('user_status_change', {'user_id': u_id, 'status': 'online'})

@socketio.on('disconnect')
def handle_disconnect():
    user_id = request.args.get('user_id')
    if user_id:
        u_id = int(user_id)
        online_users.discard(u_id)
        user = User.query.get(u_id)
        if user:
            user.last_seen = get_waktu_wita()
            db.session.commit()
            socketio.emit('user_status_change', {
                'user_id': u_id, 
                'status': 'offline', 
                'last_seen': user.last_seen.strftime("Terakhir online: %d/%m/%Y jam %H:%M")
            })

@socketio.on('kirim_pesan_private')
def handle_private_message(data):
    sender_id, receiver_id, pesan_teks, tipe = int(data['sender_id']), int(data['receiver_id']), data['pesan'], data.get('tipe', 'text')

    if tipe == 'image' and 'base64,' in pesan_teks:
        header, encoded = pesan_teks.split("base64,", 1)
        ext = header.split('/')[1].split(';')[0] if 'image/' in header else 'jpg'
        filename = f"img_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    is_online = receiver_id in online_users
    pesan_baru = Message(sender_id=sender_id, receiver_id=receiver_id, pesan=pesan_teks, tipe=tipe, diterima=is_online, dibaca=False)
    db.session.add(pesan_baru)
    db.session.commit()
    
    chat_data = {'id': pesan_baru.id, 'sender_id': sender_id, 'receiver_id': receiver_id, 'pesan': pesan_teks, 'tipe': tipe, 'diterima': is_online, 'dibaca': False}
    emit('terima_pesan_private', chat_data, room=f"user_{receiver_id}")
    emit('terima_pesan_private', chat_data, room=f"user_{sender_id}")
    if is_online: emit('notif_pesan_baru', {'sender_id': sender_id}, room=f"user_{receiver_id}")

@socketio.on('kirim_pesan_grup')
def handle_group_message(data):
    sender_id, group_id, pesan_teks, tipe = int(data['sender_id']), int(data['group_id']), data['pesan'], data.get('tipe', 'text')

    if tipe == 'image' and 'base64,' in pesan_teks:
        header, encoded = pesan_teks.split("base64,", 1)
        ext = header.split('/')[1].split(';')[0] if 'image/' in header else 'jpg'
        filename = f"gimg_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    pesan_baru = Message(sender_id=sender_id, group_id=group_id, pesan=pesan_teks, tipe=tipe)
    db.session.add(pesan_baru)
    db.session.commit()

    sender = User.query.get(sender_id)
    chat_data = {'id': pesan_baru.id, 'sender_id': sender_id, 'sender_name': sender.nama if sender else 'Unknown', 'group_id': group_id, 'pesan': pesan_teks, 'tipe': tipe}
    
    emit('terima_pesan_grup', chat_data, room=f"group_{group_id}")
    emit('notif_grup_baru', {'group_id': group_id, 'sender_id': sender_id}, room=f"group_{group_id}")

@socketio.on('typing_private')
def handle_typing_private(data): emit('status_typing', {'sender_id': data['sender_id'], 'is_typing': data['is_typing']}, room=f"user_{data['receiver_id']}")

@socketio.on('typing_group')
def handle_typing_group(data): emit('status_typing_group', {'sender_id': data['sender_id'], 'sender_name': data['sender_name'], 'is_typing': data['is_typing']}, room=f"group_{data['group_id']}")

if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
