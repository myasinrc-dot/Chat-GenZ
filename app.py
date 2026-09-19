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
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads')
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatgenz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

socketio = SocketIO(app, async_mode='eventlet', manage_session=False, cors_allowed_origins="*", max_http_buffer_size=100000000, ping_timeout=60)

# Gunakan dict untuk melacak jumlah tab aktif per user agar tidak on-off
user_connections = {}

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
    last_read_id = db.Column(db.Integer, default=0)

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
        if not (Group.query.filter_by(kode_grup=kode).first() if is_group else User.query.filter_by(pin=kode).first()):
            return kode

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: return redirect(url_for('chat'))
    if request.method == 'POST':
        nomor_hp = request.form.get('nomor_hp')
        user = User.query.filter_by(nomor_hp=nomor_hp).first()
        if not user:
            user = User(nomor_hp=nomor_hp, pin=generate_pin())
            db.session.add(user)
        user.last_seen = get_waktu_wita()
        db.session.commit()
        session['user_id'] = user.id
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/chat')
def chat():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user: return redirect(url_for('login'))
    
    daftar_teman = []
    for relasi in Contact.query.filter_by(user_id=user.id).all():
        teman = User.query.get(relasi.friend_id)
        if teman:
            unread = Message.query.filter_by(sender_id=teman.id, receiver_id=user.id, group_id=None, dibaca=False).count()
            is_online = user_connections.get(teman.id, 0) > 0
            last_seen = "Online" if is_online else (teman.last_seen.strftime("%d/%m/%Y %H:%M") if teman.last_seen else "")
            daftar_teman.append({'user': teman, 'unread': unread, 'is_online': is_online, 'last_seen_str': last_seen})

    daftar_grup = []
    for m in GroupMember.query.filter_by(user_id=user.id).all():
        g = Group.query.get(m.group_id)
        if g:
            unread = Message.query.filter(Message.group_id == g.id, Message.id > m.last_read_id).count()
            daftar_grup.append({'group': g, 'unread': unread})

    return render_template('index.html', user_aktif=user, daftar_teman=daftar_teman, daftar_grup=daftar_grup)

@app.route('/room/private/<int:friend_id>')
def room_private(friend_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    teman = User.query.get(friend_id)
    if not teman: return redirect(url_for('chat'))
    
    # Tandai terbaca saat masuk room
    unread_msgs = Message.query.filter_by(sender_id=friend_id, receiver_id=user_id, group_id=None, dibaca=False).all()
    if unread_msgs:
        for p in unread_msgs:
            p.diterima = True
            p.dibaca = True
        db.session.commit()
        socketio.emit('pesan_dibaca', {'reader_id': user_id, 'partner_id': friend_id}, room=f"user_{friend_id}")
        socketio.emit('reset_badge', {'target_id': friend_id}, room=f"user_{user_id}")

    is_online = user_connections.get(friend_id, 0) > 0
    last_seen = "Online" if is_online else (teman.last_seen.strftime("%d/%m/%Y %H:%M") if teman.last_seen else "")
    return render_template('room.html', user_aktif=User.query.get(user_id), target=teman, tipe='private', is_online=is_online, last_seen_str=last_seen)

@app.route('/room/group/<int:group_id>')
def room_group(group_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    grup = Group.query.get(group_id)
    member = GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
    if not grup or not member: return redirect(url_for('chat'))
    
    last_msg = Message.query.filter_by(group_id=group_id).order_by(Message.id.desc()).first()
    if last_msg:
        member.last_read_id = last_msg.id
        db.session.commit()
        socketio.emit('reset_badge_group', {'group_id': group_id}, room=f"user_{user_id}")

    return render_template('room.html', user_aktif=User.query.get(user_id), target=grup, tipe='group', is_online=True, last_seen_str="Grup Chat")

@app.route('/get_messages/<int:friend_id>')
def get_messages(friend_id):
    user_id = session.get('user_id')
    pesan_list = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == friend_id) & (Message.group_id == None)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == user_id) & (Message.group_id == None))
    ).order_by(Message.waktu.asc()).all()
    return jsonify([{'id': p.id, 'sender_id': p.sender_id, 'pesan': p.pesan, 'tipe': p.tipe, 'diterima': p.diterima, 'dibaca': p.dibaca} for p in pesan_list])

@app.route('/get_group_messages/<int:group_id>')
def get_group_messages(group_id):
    pesan_list = Message.query.filter_by(group_id=group_id).order_by(Message.waktu.asc()).all()
    return jsonify([{'id': p.id, 'sender_id': p.sender_id, 'sender_name': User.query.get(p.sender_id).nama, 'pesan': p.pesan, 'tipe': p.tipe} for p in pesan_list])

@socketio.on('connect')
def handle_connect():
    u_id = request.args.get('user_id')
    if u_id:
        u_id = int(u_id)
        user_connections[u_id] = user_connections.get(u_id, 0) + 1
        join_room(f"user_{u_id}")
        
        if user_connections[u_id] == 1:
            user = User.query.get(u_id)
            if user:
                user.last_seen = get_waktu_wita()
                db.session.commit()
            socketio.emit('user_status_change', {'user_id': u_id, 'status': 'online'})
            
        pending_msgs = Message.query.filter_by(receiver_id=u_id, diterima=False).all()
        for msg in pending_msgs:
            msg.diterima = True
            socketio.emit('status_diterima', {'message_id': msg.id}, room=f"user_{msg.sender_id}")
        db.session.commit()

        for m in GroupMember.query.filter_by(user_id=u_id).all():
            join_room(f"group_{m.group_id}")

@socketio.on('disconnect')
def handle_disconnect():
    u_id = request.args.get('user_id')
    if u_id:
        u_id = int(u_id)
        if u_id in user_connections:
            user_connections[u_id] -= 1
            if user_connections[u_id] <= 0:
                del user_connections[u_id]
                user = User.query.get(u_id)
                if user:
                    user.last_seen = get_waktu_wita()
                    db.session.commit()
                    socketio.emit('user_status_change', {'user_id': u_id, 'status': 'offline', 'last_seen': user.last_seen.strftime("%d/%m/%Y %H:%M")})

@socketio.on('kirim_pesan_private')
def handle_private_message(data):
    sender_id, receiver_id, pesan_teks, tipe = int(data['sender_id']), int(data['receiver_id']), data['pesan'], data.get('tipe', 'text')

    if tipe == 'image' and 'base64,' in pesan_teks:
        header, encoded = pesan_teks.split("base64,", 1)
        ext = header.split('/')[1].split(';')[0] if 'image/' in header else 'jpg'
        filename = f"img_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    is_online = user_connections.get(receiver_id, 0) > 0
    pesan_baru = Message(sender_id=sender_id, receiver_id=receiver_id, pesan=pesan_teks, tipe=tipe, diterima=is_online, dibaca=False)
    db.session.add(pesan_baru)
    db.session.commit()
    
    chat_data = {'id': pesan_baru.id, 'sender_id': sender_id, 'receiver_id': receiver_id, 'pesan': pesan_teks, 'tipe': tipe, 'diterima': is_online, 'dibaca': False}
    
    # Broadcast ke pengirim dan penerima tanpa refresh
    emit('terima_pesan_private', chat_data, room=f"user_{sender_id}")
    emit('terima_pesan_private', chat_data, room=f"user_{receiver_id}")
    emit('notif_pesan_baru', {'sender_id': sender_id}, room=f"user_{receiver_id}")

@socketio.on('pesan_terbaca_langsung')
def handle_read(data):
    # Mengubah status pesan langsung jadi Centang 2 Biru jika room terbuka
    msg_id = data['message_id']
    msg = Message.query.get(msg_id)
    if msg:
        msg.diterima = True
        msg.dibaca = True
        db.session.commit()
        socketio.emit('pesan_dibaca', {'reader_id': msg.receiver_id, 'partner_id': msg.sender_id, 'message_id': msg_id}, room=f"user_{msg.sender_id}")

@socketio.on('kirim_pesan_grup')
def handle_group_message(data):
    sender_id, group_id, pesan_teks, tipe = int(data['sender_id']), int(data['group_id']), data['pesan'], data.get('tipe', 'text')
    
    # Simpan Gambar
    if tipe == 'image' and 'base64,' in pesan_teks:
        header, encoded = pesan_teks.split("base64,", 1)
        ext = header.split('/')[1].split(';')[0] if 'image/' in header else 'jpg'
        filename = f"gimg_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    pesan_baru = Message(sender_id=sender_id, group_id=group_id, pesan=pesan_teks, tipe=tipe)
    db.session.add(pesan_baru)
    
    # Auto-update last_read_id si pengirim agar dia tidak dapat notif angka untuk pesannya sendiri
    m = GroupMember.query.filter_by(group_id=group_id, user_id=sender_id).first()
    if m:
        m.last_read_id = pesan_baru.id
        
    db.session.commit()

    sender = User.query.get(sender_id)
    chat_data = {'id': pesan_baru.id, 'sender_id': sender_id, 'sender_name': sender.nama, 'group_id': group_id, 'pesan': pesan_teks, 'tipe': tipe}
    
    emit('terima_pesan_grup', chat_data, room=f"group_{group_id}")
    emit('notif_grup_baru', {'group_id': group_id, 'sender_id': sender_id}, room=f"group_{group_id}")

if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
