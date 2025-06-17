from flask import Flask, render_template, request, redirect, session, jsonify
from flask_socketio import SocketIO, emit, join_room
import os, json, random, string

app = Flask(__name__)
app.secret_key = 'supersecretkey'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

USERS_FILE = 'users.json'
FRIEND_REQUESTS_FILE = 'friend_requests.json'

# -------------------- Utility Functions --------------------

def load_users():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump([], f)
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def load_friend_requests():
    if not os.path.exists(FRIEND_REQUESTS_FILE):
        with open(FRIEND_REQUESTS_FILE, 'w') as f:
            json.dump({}, f)
    with open(FRIEND_REQUESTS_FILE, 'r') as f:
        return json.load(f)

def save_friend_requests(data):
    with open(FRIEND_REQUESTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def generate_unique_code(existing_codes):
    while True:
        code = ''.join(random.choices(string.digits, k=10))
        if code not in existing_codes:
            return code

def get_room(code1, code2):
    return '-'.join(sorted([code1, code2]))

# -------------------- Routes --------------------

@app.route('/')
def splash():
    return render_template('splash.html')

@app.route('/check-login')
def check_login():
    return jsonify({"logged_in": 'user' in session})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        dob = request.form['dob']
        bio = request.form['bio']
        thought = request.form['thought']
        avatar = request.form['avatar']

        if not name or not dob or not thought or not avatar:
            return "Please fill all required fields."

        users = load_users()
        existing_codes = [u['code'] for u in users]
        code = generate_unique_code(existing_codes)

        session['temp_user'] = {
            'name': name,
            'dob': dob,
            'bio': bio,
            'thought': thought,
            'avatar': avatar,
            'code': code
        }

        return render_template('show_code.html', code=code)
    return render_template('register.html')

@app.route('/secure-code', methods=['POST'])
def secure_code():
    if 'temp_user' not in session:
        return redirect('/register')

    password = request.form.get('password')
    if not password:
        return "Password is required."

    user = session.pop('temp_user')
    user['password'] = password
    user['friends'] = []

    users = load_users()
    users.append(user)
    save_users(users)

    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        code = request.form['code']
        password = request.form['password']

        users = load_users()
        for u in users:
            if u['code'] == code and u['password'] == password:
                session['user'] = u
                return redirect('/list')

        return render_template('login.html', error="Invalid code or password.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/list')
def list_users():
    if 'user' not in session:
        return redirect('/login')

    users = load_users()
    user = session['user']
    requests = load_friend_requests()
    user_code = user['code']
    received_requests = requests.get(user_code, [])

    updated_user = next((u for u in users if u['code'] == user_code), None)
    session['user'] = updated_user

    return render_template('list.html', user=updated_user, users=users, requests=received_requests)

@app.route('/add-friend', methods=['POST'])
def add_friend():
    if 'user' not in session:
        return redirect('/login')

    sender_code = session['user']['code']
    target_code = request.form.get('friend_code')

    if not target_code:
        return redirect('/list')

    requests = load_friend_requests()
    if target_code not in requests:
        requests[target_code] = []

    if sender_code not in requests[target_code]:
        requests[target_code].append(sender_code)
        save_friend_requests(requests)

    return redirect('/list')

@app.route('/accept-friend', methods=['POST'])
def accept_friend():
    if 'user' not in session:
        return redirect('/login')

    receiver_code = session['user']['code']
    sender_code = request.form.get('friend_code')

    users = load_users()
    requests = load_friend_requests()

    for u in users:
        if u['code'] == receiver_code and sender_code not in u.get('friends', []):
            u['friends'].append(sender_code)
        if u['code'] == sender_code and receiver_code not in u.get('friends', []):
            u['friends'].append(receiver_code)

    save_users(users)

    if receiver_code in requests:
        if sender_code in requests[receiver_code]:
            requests[receiver_code].remove(sender_code)
        if not requests[receiver_code]:
            del requests[receiver_code]
    save_friend_requests(requests)

    return redirect('/list')

@app.route('/ignore-friend', methods=['POST'])
def ignore_friend():
    if 'user' not in session:
        return redirect('/login')

    receiver_code = session['user']['code']
    sender_code = request.form.get('friend_code')

    requests = load_friend_requests()
    if receiver_code in requests and sender_code in requests[receiver_code]:
        requests[receiver_code].remove(sender_code)
        if not requests[receiver_code]:
            del requests[receiver_code]
        save_friend_requests(requests)

    return redirect('/list')

@app.route('/chat/<code>')
def chat(code):
    if 'user' not in session:
        return redirect('/login')

    users = load_users()
    friend = next((u for u in users if u['code'] == code), None)
    user = session['user']

    if not friend:
        return "Friend not found", 404

    return render_template('chat.html', user=user, friend=friend)

# -------------------- Socket.IO Events --------------------

@socketio.on('join')
def on_join(data):
    try:
        user = data['user']
        friend = data['friend']
        room = get_room(user, friend)
        join_room(room)
        print(f"{user} joined room {room}")
    except KeyError as e:
        print(f"[join] Missing field: {e}")

@socketio.on('send_message')
def handle_message(data):
    user = data.get('user')
    friend = data.get('friend')
    message = data.get('message')
    message_id = data.get('id')
    time = data.get('time')

    if not user or not friend or not message or not message_id:
        print(f"[send_message] Missing data: {data}")
        return

    room = get_room(user, friend)
    emit('receive_message', {
        'user': user,
        'friend': friend,
        'message': message,
        'id': message_id,
        'time': time
    }, room=room)

@socketio.on('delete_message')
def handle_delete_message(data):
    user = data.get('user')
    friend = data.get('friend')
    msg_id = data.get('id')
    if not user or not friend or not msg_id:
        print(f"[delete_message] Incomplete data: {data}")
        return

    room = get_room(user, friend)
    emit('message_deleted', {'id': msg_id}, room=room)

# Online Status Handling
online_users = set()

@socketio.on('user_online')
def handle_user_online(user_code):
    online_users.add(user_code)
    socketio.emit('user_status', {'user': user_code, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    for user in list(online_users):
        online_users.remove(user)
        socketio.emit('user_status', {'user': user, 'status': 'offline'}, broadcast=True)

@app.route("/update-profile", methods=["POST"])
def update_profile():
    if "user" not in session:
        return redirect("/login")

    name = request.form.get("name")
    bio = request.form.get("bio", "")
    thought = request.form.get("thought")

    with open("users.json", "r+") as f:
        data = json.load(f)
        for user in data:
            if user["code"] == session["user"]["code"]:
                user["name"] = name
                user["bio"] = bio
                user["thought"] = thought
                session["user"] = user
                break
        f.seek(0)
        json.dump(data, f, indent=2)
        f.truncate()

    return redirect("/list")

# -------------------- Run --------------------

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)
