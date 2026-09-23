import os
import random
import string
import base64
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_bebas_123'

# Masa aktif sesi login diset 10 tahun (3650 hari)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=3650)

app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads')
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Mendukung PostgreSQL Cloud dan SQLite Lokal
db_uri = os.environ.get('DATABASE_URL', 'sqlite:///chatgenz.db')
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Mode async gevent untuk kompatibilitas penuh dengan Gunicorn & WebSocket
socketio = SocketIO(app, async_mode='gevent', manage_session=False, cors_allowed_origins="*", max_http_buffer_size=100000000, ping_timeout=10, ping_interval=5)

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
    status_note = db.Column(db.String(255), nullable=True)
    status_type = db.Column(db.String(10), default='text')
    note_expires_at = db.Column(db.DateTime, nullable=True)

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_grup = db.Column(db.String(50), nullable=False)
    kode_grup = db.Column(db.String(8), unique=True, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    foto_profil = db.Column(db.String(120), default='default.png')

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
    reply_to_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)
    is_view_once = db.Column(db.Boolean, default=False)
    is_opened = db.Column(db.Boolean, default=False)

class MessageRead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=get_waktu_wita)

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)

with app.app_context():
    db.create_all()
    try:
        engine = db.engine
        inspector = inspect(engine)
        user_cols = [c['name'] for c in inspector.get_columns('user')]
        with engine.begin() as conn:
            if 'status_note' not in user_cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN status_note VARCHAR(255)"))
            if 'status_type' not in user_cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN status_type VARCHAR(10) DEFAULT 'text'"))
            if 'note_expires_at' not in user_cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN note_expires_at DATETIME"))
            
            msg_cols = [c['name'] for c in inspector.get_columns('message')]
            if 'reply_to_id' not in msg_cols:
                conn.execute(text("ALTER TABLE message ADD COLUMN reply_to_id INTEGER"))
            if 'is_view_once' not in msg_cols:
                conn.execute(text("ALTER TABLE message ADD COLUMN is_view_once BOOLEAN DEFAULT 0"))
            if 'is_opened' not in msg_cols:
                conn.execute(text("ALTER TABLE message ADD COLUMN is_opened BOOLEAN DEFAULT 0"))
    except Exception as e:
        print("Migration notice:", e)

def get_foto_url(foto_profil, nama):
    foto = foto_profil if foto_profil else 'default.png'
    name = nama if nama else 'Pengguna'
    if foto == 'default.png':
        return f"https://ui-avatars.com/api/?name={name}&background=random"
    return url_for('static', filename=f"uploads/{foto}")

def get_group_foto_url(foto_profil, nama_grup):
    foto = foto_profil if foto_profil else 'default.png'
    name = nama_grup if nama_grup else 'Grup'
    if foto == 'default.png':
        return f"https://ui-avatars.com/api/?name={name}&background=075e54&color=fff"
    return url_for('static', filename=f"uploads/{foto}")

def generate_pin(length=8, is_group=False):
    karakter = string.ascii_uppercase + string.digits
    while True:
        kode = ''.join(random.choices(karakter, k=length))
        if not (Group.query.filter_by(kode_grup=kode).first() if is_group else User.query.filter_by(pin=kode).first()):
            return kode

def format_message(p):
    sender = User.query.get(p.sender_id)
    reply_info = None
    if p.reply_to_id:
        parent = Message.query.get(p.reply_to_id)
        if parent:
            p_sender = User.query.get(parent.sender_id)
            p_text = parent.pesan if not (parent.is_view_once and parent.is_opened) else "Pesan Sekali Lihat"
            if parent.tipe == 'image': p_text = "📷 Foto"
            elif parent.tipe == 'audio': p_text = "🎵 Pesan Suara"
            reply_info = {
                'id': parent.id,
                'sender_name': p_sender.nama if (p_sender and p_sender.nama) else 'Pengguna',
                'pesan': p_text
            }
            
    reactions = Reaction.query.filter_by(message_id=p.id).all()
    rx_list = [{'user_id': r.user_id, 'emoji': r.emoji} for r in reactions]
    
    pesan_content = p.pesan
    if p.is_view_once and p.is_opened:
        pesan_content = "opened"

    return {
        'id': p.id,
        'sender_id': p.sender_id,
        'sender_name': sender.nama if (sender and sender.nama) else 'Pengguna',
        'receiver_id': p.receiver_id,
        'group_id': p.group_id,
        'pesan': pesan_content,
        'tipe': p.tipe,
        'waktu': p.waktu.isoformat() if p.waktu else get_waktu_wita().isoformat(),
        'diterima': p.diterima,
        'dibaca': p.dibaca,
        'reply_to': reply_info,
        'is_view_once': p.is_view_once,
        'is_opened': p.is_opened,
        'reactions': rx_list
    }

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: return redirect(url_for('chat'))
    if request.method == 'POST':
        raw_hp = request.form.get('nomor_hp', '')
        # Normalisasi nomor HP agar selalu seragam (hapus spasi, strip, dan samakan +62/62)
        nomor_hp = raw_hp.strip().replace(' ', '').replace('-', '').replace('+', '')
        if nomor_hp.startswith('62'):
            nomor_hp = '0' + nomor_hp[2:]

        if not nomor_hp:
            return render_template('login.html')

        user = User.query.filter_by(nomor_hp=nomor_hp).first()
        if not user:
            user = User(nomor_hp=nomor_hp, pin=generate_pin())
            db.session.add(user)
            
        user.last_seen = get_waktu_wita()
        db.session.commit()
        
        session.permanent = True
        session['user_id'] = user.id
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/chat')
def chat():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user: return redirect(url_for('login'))
    
    now = get_waktu_wita()
    my_note = user.status_note if (user.note_expires_at and user.note_expires_at > now) else ""
    my_type = user.status_type if (user.note_expires_at and user.note_expires_at > now) else "text"
    
    my_story = {
        'content': my_note or "",
        'type': my_type or "text"
    }

    my_foto = get_foto_url(user.foto_profil, user.nama)

    daftar_teman = []
    for relasi in Contact.query.filter_by(user_id=user.id).all():
        teman = User.query.get(relasi.friend_id)
        if teman:
            unread = Message.query.filter_by(sender_id=teman.id, receiver_id=user.id, group_id=None, dibaca=False).count()
            is_online = user_connections.get(teman.id, 0) > 0
            last_seen = "Online" if is_online else (teman.last_seen.strftime("%d/%m/%Y %H:%M") if teman.last_seen else "")
            has_story = bool(teman.note_expires_at and teman.note_expires_at > now and teman.status_note)
            teman_foto = get_foto_url(teman.foto_profil, teman.nama)
            daftar_teman.append({
                'user': teman,
                'foto_url': teman_foto,
                'unread': unread,
                'is_online': is_online,
                'last_seen_str': last_seen,
                'has_story': has_story,
                'story_content': teman.status_note if has_story else "",
                'story_type': teman.status_type or "text"
            })

    daftar_grup = []
    for m in GroupMember.query.filter_by(user_id=user.id).all():
        g = Group.query.get(m.group_id)
        if g:
            unread = Message.query.filter(Message.group_id == g.id, Message.id > m.last_read_id).count()
            g_foto = get_group_foto_url(g.foto_profil, g.nama_grup)
            daftar_grup.append({
                'group': g,
                'foto_url': g_foto,
                'unread': unread
            })

    return render_template('index.html', user_aktif=user, my_foto=my_foto, my_story=my_story, daftar_teman=daftar_teman, daftar_grup=daftar_grup)

@app.route('/update_note', methods=['POST'])
def update_note():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    note_text = request.form.get('note', '').strip()
    media_file = request.files.get('media')
    
    status_content = ""
    status_type = "text"

    if media_file and media_file.filename != '':
        filename = secure_filename(media_file.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        new_filename = f"story_{user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
        media_file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
        status_content = new_filename
        if ext in ['mp4', 'mov', 'webm', 'mkv']:
            status_type = 'video'
        else:
            status_type = 'image'
    elif note_text:
        status_content = note_text[:200]
        status_type = 'text'

    user.status_note = status_content
    user.status_type = status_type
    user.note_expires_at = get_waktu_wita() + timedelta(hours=24) if status_content else None
    db.session.commit()
    
    payload = {
        'user_id': user.id,
        'nama': user.nama or 'Pengguna',
        'foto_profil': user.foto_profil or 'default.png',
        'status_note': user.status_note,
        'status_type': user.status_type,
        'has_story': bool(user.status_note)
    }
    
    contacts = Contact.query.filter_by(user_id=user.id).all()
    for c in contacts:
        socketio.emit('note_updated', payload, room=f"user_{c.friend_id}")
    socketio.emit('note_updated', payload, room=f"user_{user.id}")
    return redirect(url_for('chat'))

@app.route('/room/private/<int:friend_id>')
def room_private(friend_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    teman = User.query.get(friend_id)
    if not teman: return redirect(url_for('chat'))
    
    unread_msgs = Message.query.filter_by(sender_id=friend_id, receiver_id=user_id, group_id=None, dibaca=False).all()
    if unread_msgs:
        for p in unread_msgs:
            p.diterima = True
            p.dibaca = True
            socketio.emit('pesan_dibaca', {'reader_id': user_id, 'partner_id': friend_id, 'message_id': p.id}, room=f"user_{friend_id}")
        db.session.commit()
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
        if last_msg.id > member.last_read_id:
            member.last_read_id = last_msg.id
            db.session.commit()
        
        unmarked = Message.query.filter(Message.group_id == group_id, Message.id <= member.last_read_id).all()
        for msg in unmarked:
            if not MessageRead.query.filter_by(message_id=msg.id, user_id=user_id).first():
                db.session.add(MessageRead(message_id=msg.id, user_id=user_id))
        db.session.commit()
        
        socketio.emit('reset_badge_group', {'group_id': group_id}, room=f"user_{user_id}")
        
        total_members = GroupMember.query.filter_by(group_id=group_id).count()
        read_count = GroupMember.query.filter(GroupMember.group_id == group_id, GroupMember.last_read_id >= last_msg.id).count()
        if read_count >= total_members:
            socketio.emit('group_msg_read_all', {'group_id': group_id, 'message_id': last_msg.id}, room=f"group_{group_id}")
        
        socketio.emit('group_read_updated', {'group_id': group_id, 'user_id': user_id}, room=f"group_{group_id}")

    return render_template('room.html', user_aktif=User.query.get(user_id), target=grup, tipe='group', is_online=True, last_seen_str="Grup Chat")

@app.route('/get_messages/<int:friend_id>')
def get_messages(friend_id):
    user_id = session.get('user_id')
    pesan_list = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == friend_id) & (Message.group_id == None)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == user_id) & (Message.group_id == None))
    ).order_by(Message.waktu.asc()).all()
    return jsonify([format_message(p) for p in pesan_list])

@app.route('/get_group_messages/<int:group_id>')
def get_group_messages(group_id):
    pesan_list = Message.query.filter_by(group_id=group_id).order_by(Message.waktu.asc()).all()
    total_members = GroupMember.query.filter_by(group_id=group_id).count()
    result = []
    for p in pesan_list:
        fmt = format_message(p)
        read_count = GroupMember.query.filter(GroupMember.group_id == group_id, GroupMember.last_read_id >= p.id).count()
        fmt['is_read_all'] = (read_count >= total_members)
        result.append(fmt)
    return jsonify(result)

@app.route('/get_group_members/<int:group_id>')
def get_group_members(group_id):
    if 'user_id' not in session: return jsonify([])
    members = GroupMember.query.filter_by(group_id=group_id).all()
    result = []
    for m in members:
        u = User.query.get(m.user_id)
        if u:
            result.append({'id': u.id, 'nama': u.nama or 'Pengguna', 'pin': u.pin, 'foto_profil': u.foto_profil or 'default.png'})
    return jsonify(result)

@app.route('/get_message_info/<int:message_id>')
def get_message_info(message_id):
    if 'user_id' not in session: return jsonify({'error': 'Unauthorized'})
    msg = Message.query.get(message_id)
    if not msg or not msg.group_id: return jsonify({'error': 'Not found'})
    
    group_id = msg.group_id
    all_members = GroupMember.query.filter_by(group_id=group_id).all()
    read_list = []
    delivered_list = []
    
    for mem in all_members:
        user = User.query.get(mem.user_id)
        if not user: continue
        read_record = MessageRead.query.filter_by(message_id=message_id, user_id=user.id).first()
        if read_record:
            read_list.append({'nama': user.nama or 'Pengguna', 'waktu': read_record.read_at.strftime("%H:%M - %d/%m/%Y") if read_record.read_at else ''})
        else:
            delivered_list.append({'nama': user.nama or 'Pengguna'})
            
    return jsonify({'read_by': read_list, 'delivered_to': delivered_list})

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
    
    contacts = Contact.query.filter_by(user_id=user.id).all()
    for c in contacts:
        socketio.emit('profile_updated', {'user_id': user.id, 'nama': user.nama, 'foto_profil': user.foto_profil}, room=f"user_{c.friend_id}")
    socketio.emit('profile_updated', {'user_id': user.id, 'nama': user.nama, 'foto_profil': user.foto_profil}, room=f"user_{user.id}")
    
    return redirect(url_for('chat'))

@app.route('/update_group/<int:group_id>', methods=['POST'])
def update_group(group_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    grup = Group.query.get(group_id)
    if not grup: return redirect(url_for('chat'))
    
    nama_baru = request.form.get('nama_grup')
    foto = request.files.get('foto')
    if nama_baru: grup.nama_grup = nama_baru
    if foto and foto.filename != '':
        filename = secure_filename(foto.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
        new_filename = f"group_{grup.id}_{int(datetime.utcnow().timestamp())}.{ext}"
        foto.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
        grup.foto_profil = new_filename
    db.session.commit()
    socketio.emit('group_info_updated', {'group_id': grup.id, 'nama_grup': grup.nama_grup, 'foto_profil': grup.foto_profil}, room=f"group_{group_id}")
    return redirect(url_for('room_group', group_id=group_id))

@app.route('/add_contact', methods=['POST'])
def add_contact():
    if 'user_id' not in session: return redirect(url_for('login'))
    pin_teman = request.form.get('pin_teman')
    user_id = session['user_id']
    teman = User.query.filter_by(pin=pin_teman).first()
    if teman and teman.id != user_id:
        if not Contact.query.filter_by(user_id=user_id, friend_id=teman.id).first():
            db.session.add(Contact(user_id=user_id, friend_id=teman.id))
            db.session.add(Contact(user_id=teman.id, friend_id=user_id))
            db.session.commit()
            
            user_aktif = User.query.get(user_id)
            has_story = bool(user_aktif.note_expires_at and user_aktif.note_expires_at > get_waktu_wita() and user_aktif.status_note)
            socketio.emit('kontak_baru', {
                'id': user_aktif.id,
                'nama': user_aktif.nama or 'Pengguna',
                'pin': user_aktif.pin,
                'foto_profil': user_aktif.foto_profil or 'default.png',
                'has_story': has_story,
                'story_content': user_aktif.status_note if has_story else "",
                'story_type': user_aktif.status_type if has_story else "text"
            }, room=f"user_{teman.id}")
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
    session.clear()
    return redirect(url_for('login'))

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
        if pending_msgs:
            for msg in pending_msgs:
                msg.diterima = True
                socketio.emit('status_diterima', {'message_id': msg.id}, room=f"user_{msg.sender_id}")
            db.session.commit()
            socketio.emit('sync_offline_notifications', room=f"user_{u_id}")

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
                    socketio.emit('user_status_change', {
                        'user_id': u_id, 
                        'status': 'offline', 
                        'last_seen': user.last_seen.strftime("%d/%m/%Y %H:%M") if user.last_seen else ""
                    })

@socketio.on('kirim_pesan_private')
def handle_private_message(data):
    sender_id, receiver_id = int(data['sender_id']), int(data['receiver_id'])
    pesan_teks, tipe = data['pesan'], data.get('tipe', 'text')
    reply_to_id = data.get('reply_to_id')
    is_view_once = bool(data.get('is_view_once', False))

    if tipe == 'image' and 'base64,' in pesan_teks:
        header, encoded = pesan_teks.split("base64,", 1)
        ext = header.split('/')[1].split(';')[0] if 'image/' in header else 'jpg'
        filename = f"img_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename
    elif tipe == 'audio' and 'base64,' in pesan_teks:
        _, encoded = pesan_teks.split("base64,", 1)
        filename = f"audio_{sender_id}_{int(datetime.utcnow().timestamp())}.webm"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    is_online = user_connections.get(receiver_id, 0) > 0
    pesan_baru = Message(
        sender_id=sender_id, receiver_id=receiver_id, pesan=pesan_teks, tipe=tipe,
        diterima=is_online, dibaca=False, reply_to_id=reply_to_id, is_view_once=is_view_once
    )
    db.session.add(pesan_baru)
    db.session.commit()
    
    chat_data = format_message(pesan_baru)
    
    emit('terima_pesan_private', chat_data, room=f"user_{sender_id}")
    emit('terima_pesan_private', chat_data, room=f"user_{receiver_id}")
    emit('notif_pesan_baru', {'sender_id': sender_id}, room=f"user_{receiver_id}")

@socketio.on('kirim_pesan_grup')
def handle_group_message(data):
    sender_id, group_id = int(data['sender_id']), int(data['group_id'])
    pesan_teks, tipe = data['pesan'], data.get('tipe', 'text')
    reply_to_id = data.get('reply_to_id')
    is_view_once = bool(data.get('is_view_once', False))
    
    if tipe == 'image' and 'base64,' in pesan_teks:
        header, encoded = pesan_teks.split("base64,", 1)
        ext = header.split('/')[1].split(';')[0] if 'image/' in header else 'jpg'
        filename = f"gimg_{sender_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename
    elif tipe == 'audio' and 'base64,' in pesan_teks:
        _, encoded = pesan_teks.split("base64,", 1)
        filename = f"gaudio_{sender_id}_{int(datetime.utcnow().timestamp())}.webm"
        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as fh: fh.write(base64.b64decode(encoded))
        pesan_teks = filename

    pesan_baru = Message(
        sender_id=sender_id, group_id=group_id, pesan=pesan_teks, tipe=tipe,
        reply_to_id=reply_to_id, is_view_once=is_view_once
    )
    db.session.add(pesan_baru)
    db.session.commit()
    
    m = GroupMember.query.filter_by(group_id=group_id, user_id=sender_id).first()
    if m: 
        m.last_read_id = pesan_baru.id
        db.session.commit()

    if not MessageRead.query.filter_by(message_id=pesan_baru.id, user_id=sender_id).first():
        db.session.add(MessageRead(message_id=pesan_baru.id, user_id=sender_id))
        db.session.commit()

    chat_data = format_message(pesan_baru)
    
    emit('terima_pesan_grup', chat_data, room=f"group_{group_id}")
    emit('notif_grup_baru', {'group_id': group_id, 'sender_id': sender_id}, room=f"group_{group_id}")

@socketio.on('toggle_reaction')
def handle_reaction(data):
    msg_id = int(data['message_id'])
    user_id = int(data['user_id'])
    emoji = data['emoji']
    
    msg = Message.query.get(msg_id)
    if not msg: return
    
    rx = Reaction.query.filter_by(message_id=msg_id, user_id=user_id).first()
    if rx:
        if rx.emoji == emoji:
            db.session.delete(rx)
        else:
            rx.emoji = emoji
    else:
        db.session.add(Reaction(message_id=msg_id, user_id=user_id, emoji=emoji))
    db.session.commit()
    
    all_rx = [{'user_id': r.user_id, 'emoji': r.emoji} for r in Reaction.query.filter_by(message_id=msg_id).all()]
    out = {'message_id': msg_id, 'reactions': all_rx}
    
    if msg.group_id:
        emit('reaction_updated', out, room=f"group_{msg.group_id}")
    else:
        emit('reaction_updated', out, room=f"user_{msg.sender_id}")
        emit('reaction_updated', out, room=f"user_{msg.receiver_id}")

@socketio.on('open_view_once')
def handle_open_view_once(data):
    msg_id = int(data['message_id'])
    msg = Message.query.get(msg_id)
    if msg and msg.is_view_once and not msg.is_opened:
        msg.is_opened = True
        db.session.commit()
        out = {'message_id': msg.id, 'pesan': msg.pesan, 'tipe': msg.tipe}
        if msg.group_id:
            emit('view_once_opened', out, room=f"group_{msg.group_id}")
        else:
            emit('view_once_opened', out, room=f"user_{msg.sender_id}")
            emit('view_once_opened', out, room=f"user_{msg.receiver_id}")

@socketio.on('pesan_terbaca_langsung')
def handle_read(data):
    msg_id = data['message_id']
    msg = Message.query.get(msg_id)
    if msg:
        msg.diterima = True
        msg.dibaca = True
        db.session.commit()
        socketio.emit('pesan_dibaca', {'reader_id': msg.receiver_id, 'partner_id': msg.sender_id, 'message_id': msg_id}, room=f"user_{msg.sender_id}")

@socketio.on('update_group_read')
def handle_group_read(data):
    group_id = int(data['group_id'])
    user_id = int(data['user_id'])
    member = GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
    last_msg = Message.query.filter_by(group_id=group_id).order_by(Message.id.desc()).first()
    if member and last_msg:
        if last_msg.id > member.last_read_id:
            member.last_read_id = last_msg.id
            db.session.commit()
        
        unmarked_msgs = Message.query.filter(Message.group_id == group_id, Message.id <= member.last_read_id).all()
        for msg in unmarked_msgs:
            if not MessageRead.query.filter_by(message_id=msg.id, user_id=user_id).first():
                db.session.add(MessageRead(message_id=msg.id, user_id=user_id))
        db.session.commit()
        
        total_members = GroupMember.query.filter_by(group_id=group_id).count()
        read_count = GroupMember.query.filter(GroupMember.group_id == group_id, GroupMember.last_read_id >= last_msg.id).count()
        if read_count >= total_members:
            socketio.emit('group_msg_read_all', {'group_id': group_id, 'message_id': last_msg.id}, room=f"group_{group_id}")
        
        socketio.emit('group_read_updated', {'group_id': group_id, 'user_id': user_id}, room=f"group_{group_id}")

@socketio.on('typing_private')
def handle_typing_private(data):
    emit('status_typing', {'sender_id': data['sender_id'], 'is_typing': data['is_typing']}, room=f"user_{data['receiver_id']}")

@socketio.on('typing_group')
def handle_typing_group(data):
    emit('status_typing_group', {'sender_id': data['sender_id'], 'sender_name': data['sender_name'], 'is_typing': data['is_typing']}, room=f"group_{data['group_id']}")

if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))

