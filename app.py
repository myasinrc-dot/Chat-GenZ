from flask import Flask, render_template_string, request, redirect, url_for

app = Flask(__name__)

# Daftar sementara untuk menyimpan pesan chat
messages = [
    {"sender": "Sistem", "text": "Selamat datang di Web Chat Publik ala WhatsApp!"}
]

# Template HTML dengan desain ala WhatsApp
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WhatsApp Clone Publik</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #efeae2; margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; height: 100vh; }
        .chat-container { width: 100%; max-width: 480px; height: 100%; max-height: 850px; background: #efeae2; display: flex; flex-direction: column; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
        .chat-header { background: #00a884; color: white; padding: 15px; font-size: 18px; font-weight: bold; display: flex; align-items: center; }
        .chat-box { flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .message { max-width: 75%; padding: 10px 14px; border-radius: 7.5px; position: relative; font-size: 14px; line-height: 1.4; word-wrap: break-word; background: #ffffff; box-shadow: 0 1px 0.5px rgba(0,0,0,0.13); }
        .message.user { align-self: flex-end; background: #d9fdd3; }
        .message.system { align-self: center; background: #ffeecd; font-size: 12px; color: #555; }
        .sender { font-weight: bold; font-size: 12px; color: #005c4b; margin-bottom: 3px; }
        .chat-input-form { background: #f0f2f5; padding: 10px; display: flex; gap: 8px; align-items: center; }
        .chat-input-form input { flex: 1; padding: 10px 14px; border: none; border-radius: 20px; outline: none; font-size: 14px; background: #ffffff; }
        .chat-input-form button { background: #00a884; color: white; border: none; padding: 10px 16px; border-radius: 50%; cursor: pointer; font-weight: bold; display: flex; align-items: center; justify-content: center; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">💬 WhatsApp Publik</div>
        <div class="chat-box" id="chatBox">
            {% for msg in messages %}
                <div class="message {% if msg.sender == 'Kamu' %}user{% elif msg.sender == 'Sistem' %}system{% endif %}">
                    <div class="sender">{{ msg.sender }}</div>
                    <div>{{ msg.text }}</div>
                </div>
            {% endfor %}
        </div>
        <form class="chat-input-form" method="POST" action="/send">
            <input type="text" name="sender" placeholder="Nama kamu..." required style="max-width: 110px;">
            <input type="text" name="text" placeholder="Ketik pesan..." required autocomplete="off">
            <button type="submit">➤</button>
        </form>
    </div>
    <script>
        // Auto scroll ke pesan terbaru
        const chatBox = document.getElementById('chatBox');
        chatBox.scrollTop = chatBox.scrollHeight;
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, messages=messages)

@app.route('/send', methods=['POST'])
def send():
    sender = request.form.get('sender')
    text = request.form.get('text')
    if sender and text:
        messages.append({"sender": sender, "text": text})
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

