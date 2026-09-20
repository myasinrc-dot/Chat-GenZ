@app.route('/add_contact', methods=['POST'])
def add_contact():
    if 'user_id' not in session: return redirect(url_for('login'))
    pin_teman = request.form.get('pin_teman')
    user_id = session['user_id']
    user_aktif = User.query.get(user_id)
    teman = User.query.filter_by(pin=pin_teman).first()
    if teman and teman.id != user_id:
        if not Contact.query.filter_by(user_id=user_id, friend_id=teman.id).first():
            db.session.add(Contact(user_id=user_id, friend_id=teman.id))
            db.session.add(Contact(user_id=teman.id, friend_id=user_id))
            db.session.commit()
            # Mengirim data profil lengkap penambah kontak secara realtime
            socketio.emit('kontak_baru', {
                'id': user_aktif.id,
                'nama': user_aktif.nama,
                'foto_profil': user_aktif.foto_profil,
                'pin': user_aktif.pin
            }, room=f"user_{teman.id}")
    return redirect(url_for('chat'))
