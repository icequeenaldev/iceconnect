# BUILD: 2026-08-09-01
import os
from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, random, base64

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-key-change-this')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
db = SQLAlchemy(app)
socketio = SocketIO(app, max_http_buffer_size=10000000)

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    fullname = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    country = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.datetime.now)
    mood_color = db.Column(db.String(7), default='#00bfff')
    profile_pic = db.Column(db.String(500), default='https://ui-avatars.com/api/?name=User&background=random')
    xp = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    coins = db.Column(db.Integer, default=0)
    is_premium = db.Column(db.Boolean, default=False)
    followers = db.Column(db.Integer, default=0)
    is_admin = db.Column(db.Boolean, default=False)
    joined_date = db.Column(db.DateTime, default=datetime.datetime.now)

class DailyXP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    xp_earned = db.Column(db.Integer, default=0)
    date = db.Column(db.String(20), default=datetime.datetime.now().strftime("%Y-%m-%d"))

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter = db.Column(db.String(50), nullable=False)
    reported = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)
    resolved = db.Column(db.Boolean, default=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    image = db.Column(db.String(500), default='')  # Optional image
    likes = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(50), nullable=False)
    content = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)
    read = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(50), default='global')
    username = db.Column(db.String(50), nullable=False)
    country = db.Column(db.String(50), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

class TimeCapsule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    unlock_date = db.Column(db.DateTime, nullable=False)
    is_unlocked = db.Column(db.Boolean, default=False)

class Compliment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    receiver = db.Column(db.String(50), nullable=False)
    content = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)
    read = db.Column(db.Boolean, default=False)

class DailyPoll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(200), nullable=False)
    option1 = db.Column(db.String(100), nullable=False)
    option2 = db.Column(db.String(100), nullable=False)
    date_posted = db.Column(db.String(20), nullable=False)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    poll_id = db.Column(db.Integer, nullable=False)
    choice = db.Column(db.Integer, nullable=False)

# --- HELPER FUNCTIONS ---
def get_flag(country):
    flags = {
        'Nigeria': '🇳🇬', 'Ghana': '🇬🇭', 'Kenya': '🇰🇪', 'South Africa': '🇿🇦',
        'USA': '🇺🇸', 'UK': '🇬🇧', 'Canada': '🇨🇦', 'Brazil': '🇧🇷',
        'India': '🇮🇳', 'Japan': '🇯🇵', 'France': '🇫🇷', 'Germany': '🇩🇪'
    }
    return flags.get(country, '🌍')

def get_level(xp):
    return (xp // 100) + 1

def add_xp_with_limit(username, amount, max_daily=50):
    user = User.query.filter_by(username=username).first()
    if not user:
        return
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    daily = DailyXP.query.filter_by(username=username, date=today).first()
    
    if not daily:
        daily = DailyXP(username=username, date=today)
        db.session.add(daily)
        db.session.commit()
    
    if daily.xp_earned + amount > max_daily:
        amount = max_daily - daily.xp_earned
        if amount <= 0:
            return
    
    user.xp += amount
    user.level = get_level(user.xp)
    daily.xp_earned += amount
    db.session.commit()

def add_xp(username, amount):
    user = User.query.filter_by(username=username).first()
    if user:
        user.xp += amount
        user.level = get_level(user.xp)
        db.session.commit()

# --- HOME PAGE (Dashboard with Rooms & Features) ---
HOME_HTML = '''
<!DOCTYPE html>
<html>
<head><title>IceConnect</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
    * { box-sizing: border-box; }
    body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}
    .container{padding:12px;max-width:100%;margin:auto;}
    
    /* TOP SEARCH BAR */
    .top-bar{display:flex;gap:10px;margin-bottom:15px;}
    .search-input{flex:1;padding:12px;border-radius:25px;border:none;background:#1a2a3e;color:white;font-size:14px;}
    .search-input::placeholder{color:#666;}
    .search-btn{padding:12px 18px;background:#00bfff;border:none;border-radius:25px;color:white;cursor:pointer;}
    
    /* POLL CARD */
    .poll-card{background:#1a2a3e;padding:15px;border-radius:15px;margin-bottom:15px;border-left:4px solid #00bfff;}
    .poll-question{font-size:16px;font-weight:bold;margin-bottom:10px;}
    .poll-options{display:flex;gap:10px;flex-wrap:wrap;}
    .poll-btn{padding:8px 15px;background:#2a3a5e;color:white;border:none;border-radius:20px;cursor:pointer;font-size:13px;}
    .poll-btn:hover{background:#00bfff;}
    
    /* WEEKLY WINNER BANNER */
    .winner-banner{background:linear-gradient(135deg, #1a2a3e, #2a3a5e);padding:15px;border-radius:15px;margin-bottom:15px;display:flex;align-items:center;gap:15px;border:1px solid #ffc107;}
    .winner-pic{width:50px;height:50px;border-radius:50%;border:2px solid gold;}
    .winner-text{font-size:14px;color:#ccc;}
    .winner-text strong{color:#ffc107;}
    
    /* FEED POSTS */
    .post-card{background:#1a2a3e;padding:15px;border-radius:15px;margin-bottom:15px;}
    .post-header{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
    .post-user{font-weight:bold;color:#00bfff;}
    .post-time{font-size:11px;color:#666;}
    .post-content{font-size:14px;margin-bottom:10px;color:#ddd;}
    .post-actions{display:flex;gap:20px;font-size:13px;color:#888;}
    .post-actions span{cursor:pointer;}
    .post-actions span:hover{color:#00bfff;}
    .empty-feed{text-align:center;padding:40px;color:#666;font-size:14px;}
    .empty-feed span{font-size:40px;display:block;margin-bottom:10px;}
</style>
</head>
<body>
<div class="container">
    
    <!-- TOP SEARCH BAR -->
    <div class="top-bar">
        <input type="text" class="search-input" id="searchInput" placeholder="🔍 Search users...">
        <button class="search-btn" onclick="searchUser()">Search</button>
    </div>
    
    <!-- DAILY POLL (Live) -->
    <div class="poll-card">
        <div class="poll-question">🗳️ {{ poll.question }}</div>
        <div class="poll-options">
            <button class="poll-btn" onclick="votePoll(1)">{{ poll.option1 }}</button>
            <button class="poll-btn" onclick="votePoll(2)">{{ poll.option2 }}</button>
        </div>
    </div>
    
    <!-- WEEKLY WINNER BANNER -->
    <div class="winner-banner">
        <img src="https://ui-avatars.com/api/?name=Guardian&background=random" class="winner-pic">
        <div class="winner-text">
            <strong>🏆 Glacier Guardian</strong><br>
            This week's winner is <strong>{{ weekly_winner }}</strong>!
        </div>
    </div>
    
    <!-- REAL ICE FEED (Dynamic Posts) -->
    <div id="feed-container">
        {% if posts %}
            {% for post in posts %}
            <div class="post-card" id="post-{{ post.id }}">
                <div class="post-header">
                    <span class="post-user">@{{ post.username }}</span>
                    <span class="post-time">{{ post.timestamp.strftime('%b %d, %I:%M %p') }}</span>
                </div>
                <div class="post-content">
                    {{ post.content }}
                    {% if post.image %}
                        <br><img src="{{ post.image }}" style="width:100%;border-radius:10px;margin-top:10px;">
                    {% endif %}
                </div>
                <div class="post-actions">
                    <span onclick="likePost({{ post.id }})">❤️ {{ post.likes }}</span>
                    <span onclick="toggleComment({{ post.id }})">💬 Comment</span>
                </div>
                <div id="comment-box-{{ post.id }}" style="display:none;margin-top:10px;">
                    <input type="text" id="comment-input-{{ post.id }}" placeholder="Write a comment..." style="width:70%;padding:8px;border-radius:5px;border:none;">
                    <button onclick="postComment({{ post.id }})" style="padding:8px 15px;background:#00bfff;border:none;border-radius:5px;color:white;cursor:pointer;">Post</button>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty-feed">
                <span>📭</span>
                No posts yet. Be the first to share something!
            </div>
        {% endif %}
    </div>
    
</div>

<!-- BOTTOM NAVIGATION BAR -->
<div class="bottom-nav">
    <a href="/" class="nav-item active"><span class="nav-icon">🏠</span>Home</a>
    <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
    <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
    <a href="/inbox" class="nav-item"><span class="nav-icon">📨</span>Inbox</a>
    <a href="/profile/{{current_user.username }}" class="nav-item"><span class="nav-icon">👤</span>Profile</a>
</div>

<script>
    function searchUser() {
        let query = document.getElementById('searchInput').value;
        if(query.trim() !== '') {
            window.location.href = '/search?q=' + encodeURIComponent(query);
        }
    }

    function votePoll(choice) {
        fetch('/vote/' + choice, {method: 'POST'})
        .then(() => location.reload());
    }

    function likePost(postId) {
        fetch('/like/' + postId, {method: 'POST'})
        .then(() => location.reload());
    }

    function toggleComment(postId) {
        let box = document.getElementById('comment-box-' + postId);
        box.style.display = box.style.display === 'none' ? 'block' : 'none';
    }

    function postComment(postId) {
        let input = document.getElementById('comment-input-' + postId);
        let content = input.value;
        if(content.trim() !== '') {
            fetch('/comment/' + postId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({content: content})
            })
            .then(() => location.reload());
        }
    }
</script>
</body>
</html>
'''
# --- HOME PAGE (Real Feed + Poll) ---
@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:  # ← This MUST be indented inside the function
        user = db.session.get(User, int(session['user_id']))
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
    except Exception:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    # ... All your existing HOME code continues here ...
    current_user = user
    # Get today's poll
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    poll = DailyPoll.query.filter_by(date_posted=today).first()
    if not poll:
        poll = DailyPoll(question="What's your favorite ice cream flavor?", option1="Vanilla", option2="Chocolate", date_posted=today)
        db.session.add(poll)
        db.session.commit()
    
    # Get all posts
    posts = Post.query.order_by(Post.timestamp.desc()).all()
    
    # Calculate unread notifications
    my_posts = Post.query.filter_by(username=user.username).all()
    unread_comments = Comment.query.filter(Comment.post_id.in_([p.id for p in my_posts]), Comment.read==False).count()
    unread_compliments = Compliment.query.filter_by(receiver=user.username, read=False).count()
    unread_count = unread_comments + unread_compliments
    
    weekly_winner = "IceQueenAL"
    
    # BUILD THE FEED HTML SAFELY
    feed_html = ""
    if posts:
        for p in posts:
            comments_html = ""
            comments = Comment.query.filter_by(post_id=p.id).order_by(Comment.timestamp).all()
            for c in comments:
                comments_html += f'<div style="background:#0b1a2e;padding:8px;border-radius:8px;margin-bottom:5px;font-size:13px;"><b style="color:#00bfff;">@{c.username}</b>: {c.content}</div>'
            
            feed_html += f'''
            <div class="post-card" id="post-{p.id}">
                <div class="post-header">
                    <span class="post-user">@{p.username}</span>
                    <span class="post-time">{p.timestamp.strftime('%b %d, %I:%M %p')}</span>
                </div>
                <div class="post-content">{p.content}</div>
                {f'<img src="{p.image}" class="post-image">' if p.image else ''}
                <div class="post-actions">
                    <span onclick="likePost({p.id})">❤️ {p.likes}</span>
                    <span onclick="toggleComment({p.id})">💬 Comment</span>
                </div>
                <div id="comment-box-{p.id}" style="display:none;margin-top:10px;">
                    <div id="comment-list-{p.id}">
                        {comments_html}
                    </div>
                    <input type="text" id="comment-input-{p.id}" placeholder="Write a comment..." style="width:60%;padding:8px;border-radius:5px;border:none;margin-top:8px;">
                    <button onclick="postComment({p.id})" style="padding:8px 15px;background:#00bfff;border:none;border-radius:5px;color:white;cursor:pointer;">Post</button>
                </div>
            </div>
            '''
    else:
        feed_html = '<div class="empty-feed"><span>📭</span>No posts yet. Be the first to share something!</div>'
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head><title>IceConnect</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        * { box-sizing: border-box; }
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}
        .container{padding:12px;max-width:100%;margin:auto;}
        .top-bar{display:flex;gap:10px;margin-bottom:15px;}
        .search-input{flex:1;padding:12px;border-radius:25px;border:none;background:#1a2a3e;color:white;font-size:14px;}
        .search-input::placeholder{color:#666;}
        .search-btn{padding:12px 18px;background:#00bfff;border:none;border-radius:25px;color:white;cursor:pointer;}
        .poll-card{background:#1a2a3e;padding:15px;border-radius:15px;margin-bottom:15px;border-left:4px solid #00bfff;}
        .poll-question{font-size:16px;font-weight:bold;margin-bottom:10px;}
        .poll-options{display:flex;gap:10px;flex-wrap:wrap;}
        .poll-btn{padding:8px 15px;background:#2a3a5e;color:white;border:none;border-radius:20px;cursor:pointer;font-size:13px;}
        .poll-btn:hover{background:#00bfff;}
        .winner-banner{background:linear-gradient(135deg, #1a2a3e, #2a3a5e);padding:15px;border-radius:15px;margin-bottom:15px;display:flex;align-items:center;gap:15px;border:1px solid #ffc107;}
        .winner-pic{width:50px;height:50px;border-radius:50%;border:2px solid gold;}
        .winner-text{font-size:14px;color:#ccc;}
        .winner-text strong{color:#ffc107;}
        .post-card{background:#1a2a3e;padding:15px;border-radius:15px;margin-bottom:15px;}
        .post-header{display:flex;align-items:center;gap:10px;margin-bottom:5px;}
        .post-user{font-weight:bold;color:#00bfff;}
        .post-time{font-size:11px;color:#666;}
        .post-content{font-size:14px;color:#ddd;margin:5px 0;}
        .post-image{width:100%;border-radius:10px;margin-top:10px;}
        .post-actions{display:flex;gap:20px;font-size:13px;color:#888;}
        .post-actions span{cursor:pointer;}
        .post-actions span:hover{color:#00bfff;}
        .empty-feed{text-align:center;padding:40px;color:#666;font-size:14px;}
        .empty-feed span{font-size:40px;display:block;margin-bottom:10px;}
        
        .bottom-nav{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;backdrop-filter:blur(8px);}
        .nav-item{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}
        .nav-item:hover,.nav-item.active{color:#00bfff;}
        .nav-icon{font-size:24px;margin-bottom:4px;}
        .badge{position:absolute;top:-5px;right:-5px;background:#ff5555;color:white;font-size:10px;border-radius:50%;padding:2px 6px;font-weight:bold;}
        .nav-item{position:relative;}
    </style>
    </head>
    <body>
    <div class="container">
        <div class="top-bar">
            <input type="text" class="search-input" id="searchInput" placeholder="🔍 Search users...">
            <button class="search-btn" onclick="searchUser()">Search</button>
        </div>
        
        <div class="poll-card">
            <div class="poll-question">🗳️ {{ poll.question }}</div>
            <div class="poll-options">
                <button class="poll-btn" onclick="votePoll(1)">{{ poll.option1 }}</button>
                <button class="poll-btn" onclick="votePoll(2)">{{ poll.option2 }}</button>
            </div>
        </div>
        
        <div class="winner-banner">
            <img src="https://ui-avatars.com/api/?name=Guardian&background=random" class="winner-pic">
            <div class="winner-text">
                <strong>🏆 Glacier Guardian</strong><br>
                This week's winner is <strong>''' + weekly_winner + '''</strong>!
            </div>
        </div>
        
        <div id="feed-container">
            ''' + feed_html + '''
        </div>
    </div>
    
    <div class="bottom-nav">
        <a href="/" class="nav-item active"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item">
            <span class="nav-icon">📨</span>Inbox
            <span class="badge">''' + str(unread_count) + '''</span>
        </a>
        <a href="/profile/''' + current_user.username + '''" class="nav-item"><span class="nav-icon">👤</span>Profile</a>
    </div>
    
    <script>
        function searchUser() { let q = document.getElementById('searchInput').value; if(q.trim()!='') window.location.href='/search?q='+encodeURIComponent(q); }
        function votePoll(c) { fetch('/vote/'+c,{method:'POST'}).then(()=>location.reload()); }
        function likePost(id) { fetch('/like/'+id,{method:'POST'}).then(()=>location.reload()); }
        function toggleComment(id) {
            let box = document.getElementById('comment-box-'+id);
            box.style.display = box.style.display === 'none' ? 'block' : 'none';
            fetch('/read/comments/'+id, {method:'POST'});
        }
        function postComment(id) {
            let input = document.getElementById('comment-input-'+id);
            let content = input.value;
            if(content.trim()!='') {
                fetch('/comment/'+id, {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({content:content})
                }).then(()=>location.reload());
            }
        }
    </script>
    </body>
    </html>
    ''', user=user, poll=poll, posts=posts, current_user=current_user)

# --- SIGNUP PAGE (Full Screen, Bold, Readable) ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        fullname = request.form['fullname']
        dob_year = int(request.form['dob_year'])
        dob_month = int(request.form['dob_month'])
        dob_day = int(request.form['dob_day'])
        gender = request.form['gender']
        country = request.form['country']
        password = request.form['password']
        terms_accepted = request.form.get('terms', False)
        
        if not terms_accepted:
            return "<h1>⛔ Access Denied</h1><p>You must accept the Terms & Conditions.</p>"
        
        # Calculate exact age
        import datetime
        today = datetime.datetime.now()
        age = today.year - dob_year - ((today.month, today.day) < (dob_month, dob_day))
        
        if age < 16:
            return "<h1>⛔ Access Denied</h1><p>You must be 16 or older.</p>"
        if User.query.filter_by(username=username).first():
            return "Username taken!"
        
        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, fullname=fullname, age=age, gender=gender, country=country, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        db.session.flush()
        session['user_id'] = new_user.id
        
        # Splash Screen
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head><title>Welcome</title>
<style>
    body{margin:0;padding:0;background:#0b1a2e;color:white;font-family:Arial;display:flex;justify-content:center;align-items:center;height:100vh;text-align:center;overflow:hidden;flex-direction:column;}
    .splash{animation:fadeOut 3s forwards;animation-delay:2.5s;opacity:1;}
    @keyframes fadeOut{0%{opacity:1;}100%{opacity:0;display:none;}}
    h1{font-size:3em;margin-bottom:5px;color:#00bfff;font-weight:bold;}
    h2{font-size:1.5em;margin-bottom:10px;color:#fff;}
    p{font-size:1.2em;color:#ccc;line-height:1.5;}
    .ice-icon{font-size:80px;display:block;margin-bottom:20px;}
</style>
<script>setTimeout(function(){ window.location.href = "/"; }, 3000);</script>
</head>
<body>
<div class="splash">
    <span class="ice-icon">🧊</span>
    <h1>Welcome to IceConnect</h1>
    <h2>{new_user.username}</h2>
    <p>Meet millions of people around the world, compete, and share your vibe.</p>
</div>
</body>
</html>
''')
    
    return '''
    <!DOCTYPE html>
    <html><head><title>Sign Up</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0;min-height:100vh;display:flex;justify-content:center;align-items:center;flex-direction:column;}
        .signup-container{width:90%;max-width:400px;padding:20px;background:#1a2a3e;border-radius:20px;margin:20px auto;}
        h1{text-align:center;font-size:28px;color:#00bfff;margin-bottom:20px;}
        input,select{width:100%;padding:14px;margin:10px 0;border-radius:10px;border:none;background:#0b1a2e;color:white;font-size:15px;box-sizing:border-box;}
        select{color:#ccc;appearance:none;}
        .dob-row{display:flex;gap:8px;}
        .dob-row select{flex:1;}
        .terms-box{background:#0b1a2e;border:1px solid #00bfff;border-radius:10px;height:100px;overflow-y:scroll;padding:12px;text-align:left;font-size:12px;color:#ccc;margin:15px 0;}
        .terms-box h3{color:#00bfff;margin:0;font-size:14px;}
        label{font-size:14px;display:flex;align-items:center;gap:10px;justify-content:center;margin:10px 0;color:#ccc;}
        button{width:100%;padding:16px;background:#00bfff;color:white;border:none;border-radius:12px;font-size:18px;font-weight:bold;cursor:pointer;}
        .login-link{color:#00bfff;text-decoration:none;display:block;text-align:center;margin-top:15px;font-size:15px;}
    </style>
    </head>
    <body>
    <div class="signup-container">
        <h1>🧊 Join IceConnect</h1>
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required>
            <input type="text" name="fullname" placeholder="Full Name" required>
            <div style="font-size:13px;color:#888;text-align:left;margin:5px 0;">Date of Birth</div>
            <div class="dob-row">
                <select name="dob_year" required><option value="">Year</option>''' + ''.join([f'<option value="{y}">{y}</option>' for y in range(1940, 2011)]) + '''</select>
                <select name="dob_month" required><option value="">Month</option>''' + ''.join([f'<option value="{m}">{m}</option>' for m in range(1, 13)]) + '''</select>
                <select name="dob_day" required><option value="">Day</option>''' + ''.join([f'<option value="{d}">{d}</option>' for d in range(1, 32)]) + '''</select>
            </div>
            <select name="gender"><option>Male</option><option>Female</option><option>Other</option></select>
            <input type="text" name="country" placeholder="Your Country" required>
            <input type="password" name="password" placeholder="Password" required>
            
            <div class="terms-box">
                <h3>📜 Terms & Conditions</h3>
                <p><b>1.</b> By creating an account, you agree to these Terms.</p>
                <p><b>2.</b> You must be 16 or older.</p>
                <p><b>3.</b> No hate speech, harassment, or spam.</p>
                <p><b>4.</b> We collect your username, age, and country. We do not sell your data.</p>
            </div>
            
            <label>
                <input type="checkbox" name="terms" required style="width:auto;margin:0;"> I agree to the Terms & Conditions.
            </label>
            
            <button type="submit">Create Account</button>
        </form>
        <a href="/login" class="login-link">Already a member? Log in</a>
    </div>
    </body>
    </html>
    '''

# --- CREATE ROOM PAGE ---
@app.route('/create_room', methods=['GET', 'POST'])
def create_room():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))
    
    
    if request.method == 'POST':
        room_name = request.form['room_name'].lower().replace(' ', '_')
        room_display = request.form['room_display']
        description = request.form['description']
        
        # Check if room already exists
        if Message.query.filter_by(room=room_name).first():
            return "A room with that name already exists!"
        
        # Create a dummy message to "register" the room in the database
        new_room = Message(room=room_name, username="SYSTEM", country="🌍", content=f"Welcome to {room_display}!")
        db.session.add(new_room)
        db.session.commit()
        
        return redirect(url_for('chatrooms'))
    
    return '''
    <!DOCTYPE html>
    <html><head><title>Create Room</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:20px;}
        .container{padding:12px;max-width:100%;margin:auto;}
        h1{color:#00bfff;}
        input,textarea{width:100%;padding:10px;border-radius:8px;border:none;margin:10px 0;box-sizing:border-box;}
        textarea{resize:none;height:80px;}
        .btn{width:100%;padding:12px;background:#00bfff;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:bold;font-size:16px;}
        a{color:#00bfff;text-decoration:none;display:block;margin-top:15px;text-align:center;}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>➕ Create a New Room</h1>
        <p style="color:#888;font-size:14px;">Create your own custom room for the IceConnect community!</p>
        <form method="POST">
            <input type="text" name="room_display" placeholder="Room Name (e.g. Anime Lovers)" required>
            <input type="text" name="room_name" placeholder="Unique ID (e.g. anime_lovers)" required>
            <textarea name="description" placeholder="Describe what this room is about..."></textarea>
            <button type="submit" class="btn">Create Room</button>
        </form>
        <a href="/chatrooms">⬅ Back to Chatrooms</a>
    </div>
    </body>
    </html>
    '''

# --- CHATROOMS PAGE (Fixed Session) ---
@app.route('/chatrooms')
def chatrooms():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user = db.session.get(User, int(session['user_id']))
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
    except Exception:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    search_query = request.args.get('q', '').lower()
    
    default_rooms = ['global', 'youth', 'premier', 'gaming', 'music', 'study']
    
    all_rooms = db.session.query(Message.room).distinct().all()
    user_rooms = [r[0] for r in all_rooms if r[0] not in default_rooms]
    
    room_names = default_rooms + user_rooms
    
    if search_query:
        room_names = [r for r in room_names if search_query in r.lower()]
    
    def get_room_stats(room_name):
        recent = datetime.datetime.now() - datetime.timedelta(minutes=10)
        count = Message.query.filter_by(room=room_name).filter(Message.timestamp > recent).count()
        if count > 10: vibe = "🔥 Buzzing"
        elif count > 3: vibe = "💬 Chatty"
        elif count > 0: vibe = "🗣️ Active"
        else: vibe = "😴 Quiet"
        return count, vibe
    
    def get_display_name(room_name):
        names = {
            'global': '🌍 Global Lounge', 'youth': '🧑‍🤝‍🧑 Youth Hub (16-25)',
            'premier': '👑 Premier Lounge (26+)', 'gaming': '🎮 Gamers Hub',
            'music': '🎵 Music & Vibes', 'study': '📚 Study Squad'
        }
        if room_name in names: return names[room_name]
        return room_name.replace('_', ' ').title()
    
    room_html = ""
    for r in room_names:
        c, v = get_room_stats(r)
        display_name = get_display_name(r)
        room_html += f'''
        <div class="room-wrapper" style="position:relative;">
            <a href="/chat/{r}" class="room-card">
                <div class="room-info">
                    <span class="room-name">{display_name}</span>
                    <span class="room-meta">Live: {c} users • {v}</span>
                </div>
                <span class="room-vibe">Enter ➡️</span>
            </a>
        </div>
        '''
    
    if not room_html:
        room_html = '<p style="color:#666;text-align:center;padding:20px;">No rooms found matching your search.</p>'
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head><title>Chatrooms</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        * {{ box-sizing: border-box; }}
        body{{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}}
        .container{{width:100%;max-width:600px;margin:auto;padding:12px;box-sizing:border-box;}}
        h1{{margin-top:10px;}}
        .room-card{{background:#1a2a3e;border-radius:15px;padding:15px;margin-bottom:15px;display:flex;justify-content:space-between;align-items:center;text-decoration:none;color:white;}}
        .room-info{{display:flex;flex-direction:column;}}
        .room-name{{font-size:18px;font-weight:bold;}}
        .room-meta{{font-size:12px;color:#888;}}
        .room-vibe{{font-size:11px;background:#2a3a5e;padding:4px 8px;border-radius:12px;color:#ccc;}}
        .btn{{padding:10px 20px;background:#00bfff;color:white;border:none;border-radius:8px;cursor:pointer;text-decoration:none;font-size:14px;}}
        .add-btn{{background:#6f42c1;}}
        .bottom-nav{{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;}}
        .nav-item{{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}}
        .nav-item:hover,.nav-item.active{{color:#00bfff;}}
        .nav-icon{{font-size:24px;margin-bottom:4px;}}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>💬 Chatrooms</h1>
        <form method="GET" action="/chatrooms" style="display:flex;gap:10px;margin-bottom:20px;">
            <input type="text" name="q" placeholder="Search rooms..." value="{search_query}" style="flex:1;padding:10px;border-radius:8px;border:none;">
            <button type="submit" class="btn">Search</button>
            <button type="button" class="btn add-btn" onclick="location.href='/create_room'">+ Add</button>
        </form>
        <div id="room-list">{room_html}</div>
    </div>
    <div class="bottom-nav">
        <a href="/" class="nav-item"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item active"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item"><span class="nav-icon">📨</span>Inbox</a>
        <a href="/profile/{user.username}" class="nav-item"><span class="nav-icon">👤</span>Profile</a>
    </div>
    </body>
    </html>
    '''
# --- LOGIN PAGE (Full Screen, Centered, Beautiful) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            user.online = True
            db.session.commit()
            return redirect(url_for('home'))
        return "Invalid login!"  # ← This should be indented 4 spaces
    return '''
    <!DOCTYPE html>
    <html><head><title>Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0;min-height:100vh;display:flex;justify-content:center;align-items:center;flex-direction:column;}
        .login-container{width:90%;max-width:400px;text-align:center;padding:20px;}
        h1{font-size:32px;color:#00bfff;margin-bottom:30px;font-weight:bold;letter-spacing:1px;}
        input{width:100%;padding:16px;margin:12px 0;border-radius:12px;border:none;background:#1a2a3e;color:white;font-size:16px;box-sizing:border-box;}
        input::placeholder{color:#888;}
        button{width:100%;padding:16px;background:#00bfff;color:white;border:none;border-radius:12px;font-size:18px;font-weight:bold;cursor:pointer;margin-top:10px;}
        .signup-link{color:#00bfff;text-decoration:none;display:block;margin-top:20px;font-size:15px;}
    </style>
    </head>
    <body>
    <div class="login-container">
        <h1>🧊 Welcome Back</h1>
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        <a href="/signup" class="signup-link">No account? Sign up here</a>
    </div>
    </body>
    </html>
    '''

# --- NEW FEATURES ROUTES ---
@app.route('/mood', methods=['GET', 'POST'])
def mood():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        user = db.session.get(User, int(session['user_id']))
        
        user.mood_color = request.form['color']
        db.session.commit()
        add_xp(user.username, 5)
        return redirect(url_for('home'))
    return '''
    <!DOCTYPE html>
    <html><head><title>Change Mood</title>
    <style>body{font-family:Arial;background:#0b1a2e;color:white;text-align:center;padding:20px;}
    .card{background:#1a2a3e;padding:30px;border-radius:15px;max-width:400px;margin:auto;}
    .btn{display:block;padding:15px;background:#00bfff;color:white;text-decoration:none;border-radius:8px;margin:10px 0;border:none;cursor:pointer;}
    input[type="color"]{width:100px;height:100px;border:none;background:none;cursor:pointer;}
    </style>
    </head>
    <body>
    <div class="card">
        <h1>🎨 Mood Aura</h1>
        <p>Pick a color that matches your vibe right now.</p>
        <form method="POST">
            <input type="color" name="color" value="#00bfff">
            <button type="submit" class="btn">Set My Aura</button>
        </form>
        <a href="/">⬅ Back</a>
    </div>
    </body>
    </html>
    '''

@app.route('/capsule', methods=['GET', 'POST'])
def capsule():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        user = db.session.get(User, int(session['user_id']))
    
        content = request.form['content']
        days = int(request.form['days'])
        unlock_date = datetime.datetime.now() + datetime.timedelta(days=days)
        capsule = TimeCapsule(username=user.username, content=content, unlock_date=unlock_date)
        db.session.add(capsule)
        db.session.commit()
        add_xp(user.username, 20)
        return f"Time capsule buried! It unlocks in {days} days."
    return '''
    <!DOCTYPE html>
    <html><head><title>Time Capsule</title>
    <style>body{font-family:Arial;background:#0b1a2e;color:white;text-align:center;padding:20px;}
    .card{background:#1a2a3e;padding:30px;border-radius:15px;max-width:400px;margin:auto;}
    .btn{display:block;padding:15px;background:#00bfff;color:white;text-decoration:none;border-radius:8px;margin:10px 0;border:none;cursor:pointer;}
    input,textarea{padding:10px;width:90%;border-radius:5px;border:none;margin:5px 0;}
    </style>
    </head>
    <body>
    <div class="card">
        <h1>📜 Bury a Time Capsule</h1>
        <p>Write a message that unlocks on a future date.</p>
        <form method="POST">
            <textarea name="content" placeholder="Write your message..." rows="3" required></textarea>
            <label>Unlock in:</label>
            <select name="days">
                <option value="7">7 days</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
            </select>
            <button type="submit" class="btn">Bury Capsule</button>
        </form>
        <a href="/">⬅ Back</a>
    </div>
    </body>
    </html>
    '''

@app.route('/compliment', methods=['GET', 'POST'])
def compliment():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        user = db.session.get(User, int(session['user_id']))
        
        receiver = request.form['receiver']
        content = request.form['content']
        last_hour = Compliment.query.filter_by(receiver=receiver).order_by(Compliment.timestamp.desc()).first()
        if last_hour and (datetime.datetime.now() - last_hour.timestamp).seconds < 3600:
            return "Please wait 1 hour before sending another compliment to this user."
        compliment = Compliment(receiver=receiver, content=content)
        db.session.add(compliment)
        db.session.commit()
        add_xp(user.username, 10)
        return "Anonymous compliment sent! 💖"
    return '''
    <!DOCTYPE html>
    <html><head><title>Send Compliment</title>
    <style>body{font-family:Arial;background:#0b1a2e;color:white;text-align:center;padding:20px;}
    .card{background:#1a2a3e;padding:30px;border-radius:15px;max-width:400px;margin:auto;}
    .btn{display:block;padding:15px;background:#00bfff;color:white;text-decoration:none;border-radius:8px;margin:10px 0;border:none;cursor:pointer;}
    input,textarea{padding:10px;width:90%;border-radius:5px;border:none;margin:5px 0;}
    </style>
    </head>
    <body>
    <div class="card">
        <h1>💖 Send Anonymous Compliment</h1>
        <p>Send a kind message to someone secretly.</p>
        <form method="POST">
            <input type="text" name="receiver" placeholder="Receiver's username" required>
            <textarea name="content" placeholder="Your kind message..." rows="2" required></textarea>
            <button type="submit" class="btn">Send Compliment</button>
        </form>
        <a href="/">⬅ Back</a>
    </div>
    </body>
    </html>
    '''
# --- SEARCH BAR ---
@app.route('/search', methods=['GET'])
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    query = request.args.get('q', '')
    results = User.query.filter(User.username.contains(query)).limit(10).all()
    html = '<h1>🔍 Search Users</h1><form><input type="text" name="q" placeholder="Search username..." value="' + query + '"><button type="submit">Search</button></form><div>'
    for u in results:
        html += f'<p><a href="/profile/{u.username}" style="color:#00bfff;">{u.username}</a> ({u.country})</p>'
    html += '</div><a href="/">⬅ Back</a>'
    return html

# --- DM SYSTEM ---
@app.route('/dm/<receiver>')
def dm_chat(receiver):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    sender = db.session.get(User, int(session['user_id'])).username
    room_name = '_'.join(sorted([sender, receiver]))
    return f"""
    <!DOCTYPE html>
    <html><head><title>DM with {receiver}</title>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <style>
        body{{background:#0b1a2e;color:white;font-family:Arial;padding:20px;}}
        #chat{{height:300px;border:1px solid #9b59b6;overflow-y:scroll;padding:10px;background:#1a2a3e;border-radius:10px;margin-bottom:10px;}}
        .msg{{padding:8px;border-bottom:1px solid #334;}}
        .user{{color:#9b59b6;font-weight:bold;}}
        input{{padding:10px;width:70%;border-radius:5px;border:none;}}
        button{{padding:10px;background:#9b59b6;color:white;border:none;border-radius:5px;cursor:pointer;}}
        a{{color:#9b59b6;text-decoration:none;display:block;margin-top:20px;}}
        #typing-indicator{{color:gray;font-style:italic;font-size:14px;display:none;margin-bottom:10px;}}
    </style>
    </head>
    <body>
    <h1>💬 DM with {receiver}</h1>
    <div id="typing-indicator"></div>
    <div id="chat"></div>
    <input id="msg" placeholder="Type a private message...">
    <button onclick="sendMsg()">Send</button>
    <a href="/">⬅ Back</a>
    <script>
        var socket = io();
        var sender = "{sender}";
        var receiver = "{receiver}";
        var room = "{room_name}";
        var typingTimeout;

        socket.on('connect', function() {{
            socket.emit('join_dm', {{sender: sender, receiver: receiver, room: room}});
        }});
        socket.on('load_dm_history', function(messages) {{
            var chat = document.getElementById('chat');
            messages.forEach(function(m) {{ addMessage(m[0], m[1]); }});
            chat.scrollTop = chat.scrollHeight;
        }});
        socket.on('dm_message', function(data) {{ addMessage(data[0], data[1]); }});
        socket.on('dm_typing', function(data) {{
            var indicator = document.getElementById('typing-indicator');
            indicator.innerText = data + ' is typing...';
            indicator.style.display = 'block';
            clearTimeout(typingTimeout);
            typingTimeout = setTimeout(() => {{
                indicator.style.display = 'none';
            }}, 2000);
        }});

        function addMessage(user, content) {{
            var chat = document.getElementById('chat');
            var newMsg = document.createElement('div');
            newMsg.className = 'msg';
            newMsg.innerHTML = '<span class="user">' + user + ':</span> ' + content;
            chat.appendChild(newMsg);
            chat.scrollTop = chat.scrollHeight;
        }}

        function sendMsg() {{
            var msg = document.getElementById('msg').value;
            if(msg.trim() !== '') {{
                socket.emit('send_dm', {{msg: msg, room: room, sender: sender, receiver: receiver}});
                document.getElementById('msg').value = '';
            }}
        }}

        document.getElementById('msg').addEventListener('input', function() {{
            socket.emit('dm_typing', {{room: room, sender: sender}});
        }});
        document.getElementById('msg').addEventListener('keypress', function (e) {{
            if (e.key === 'Enter') sendMsg();
        }});
    </script>
    </body>
    </html>
    """

# --- DM SOCKET EVENTS ---
@socketio.on('join_dm')
def handle_join_dm(data):
    room = data['room']
    join_room(room)
    emit('load_dm_history', [])

@socketio.on('send_dm')
def handle_dm_message(data):
    room = data['room']
    sender = data['sender']
    receiver = data['receiver']
    msg = data['msg']
    
    # Send live message to both users
    emit('dm_message', [sender, msg], room=room)
    
    # Save to database for profile inbox
    new_msg = Message(room=room, username=sender, country="", content=msg)
    db.session.add(new_msg)
    db.session.commit()

@socketio.on('dm_typing')
def handle_dm_typing(data):
    room = data['room']
    sender = data['sender']
    emit('dm_typing', [sender], room=room)

@app.route('/poll')
def poll():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    poll = DailyPoll.query.filter_by(date_posted=today).first()
    if not poll:
        q = random.choice([
            ("What's the best pizza topping?", "Pepperoni", "Cheese", "Chicken", "Vegetables"),
            ("Which country has the best music?", "Nigeria", "USA", "Brazil", "India"),
            ("What's the best movie of all time?", "Inception", "Black Panther", "Spirited Away", "The Godfather"),
            ("Who is the GOAT of football?", "Messi", "Ronaldo", "Salah", "Haaland"),
            ("What's your favorite social media?", "TikTok", "Instagram", "Snapchat", "X"),
            ("If you could travel anywhere, where?", "Japan", "Brazil", "Egypt", "New Zealand"),
            ("What's the best season?", "Summer", "Winter", "Spring", "Fall"),
            ("Who is the best rapper?", "Drake", "Kendrick Lamar", "Burna Boy", "J. Cole"),
            ("What's your dream job?", "Pilot", "Doctor", "Software Engineer", "YouTuber"),
            ("Which is better?", "Marvel", "DC", "Both", "Neither"),
            ("What's your favorite Gen Z slang?", "Slay", "No cap", "Fam", "It's giving"),
            ("What's the best food?", "Jollof Rice", "Pizza", "Sushi", "Tacos"),
            ("What's the best time to hang out?", "Morning", "Afternoon", "Evening", "Night"),
            ("What would you do with $1M?", "Travel", "Buy a house", "Invest", "Donate"),
            ("Which animal would you want as a pet?", "Dog", "Cat", "Parrot", "Snake"),
            ("What's the best thing about your country?", "The Food", "The Music", "The People", "The Scenery"),
            ("What's the most underrated fruit?", "Mango", "Pineapple", "Watermelon", "Guava"),
            ("If you could master one talent?", "Guitar", "Dancing", "Cooking", "Drawing"),
            ("Which is better: iOS or Android?", "iOS", "Android", "Both", "Neither"),
            ("What's the best holiday?", "Christmas", "New Year", "Easter", "Birthday")
        ]) 
        poll = DailyPoll(question=q[0], option1=q[1], option2=q[2], date_posted=today)
        db.session.add(poll)
        db.session.commit()
    has_voted = Vote.query.filter_by(username=user.username, poll_id=poll.id).first()
    return '''
    <!DOCTYPE html>
    <html><head><title>Daily Poll</title>
    <style>body{font-family:Arial;background:#0b1a2e;color:white;text-align:center;padding:20px;}
    .card{background:#1a2a3e;padding:30px;border-radius:15px;max-width:400px;margin:auto;}
    .btn{display:block;padding:15px;background:#00bfff;color:white;text-decoration:none;border-radius:8px;margin:10px 0;}
    </style>
    </head>
    <body>
    <div class="card">
        <h1>🗳️ Today's Poll</h1>
        <h3>''' + poll.question + '''</h3>
        ''' + ('<p style="color:gold;">✅ You voted today! +5 XP</p>' if has_voted else '<a href="/vote/' + str(poll.id) + '/1" class="btn">1. ' + poll.option1 + '</a><a href="/vote/' + str(poll.id) + '/2" class="btn">2. ' + poll.option2 + '</a>') + '''
        <a href="/">⬅ Back</a>
    </div>
    </body>
    </html>
    '''

@app.route('/vote/<poll_id>/<choice>')
def vote(poll_id, choice):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))

    if Vote.query.filter_by(username=user.username, poll_id=poll_id).first():
        return "You already voted today!"
    vote = Vote(username=user.username, poll_id=int(poll_id), choice=int(choice))
    db.session.add(vote)
    db.session.commit()
    add_xp(user.username, 5)
    return redirect(url_for('poll'))

# --- PROFILE PAGE (With Settings Gear Icon) ---
@app.route('/profile/<username>', methods=['GET', 'POST'])
def profile(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.filter_by(username=username).first()
    
    # 🔥 ADD THIS CHECK 🔥
    if not user:
        return "User not found", 404
    
    session_user = db.session.get(User, int(session['user_id']))
    if not session_user:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'post_image' in request.files or 'post_caption' in request.form:
            caption = request.form.get('post_caption', '')
            file = request.files.get('post_image')
            image_data = ''
            if file and file.filename != '':
                img_data = base64.b64encode(file.read()).decode('utf-8')
                image_data = f"data:{file.mimetype};base64,{img_data}"
            new_post = Post(username=user.username, content=caption, image=image_data)
            db.session.add(new_post)
            db.session.commit()
        elif 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file:
                img_data = base64.b64encode(file.read()).decode('utf-8')
                user.profile_pic = f"data:{file.mimetype};base64,{img_data}"
                db.session.commit()
        return redirect(url_for('profile', username=username))
    
    user_posts = Post.query.filter_by(username=user.username).order_by(Post.timestamp.desc()).all()
    post_html = ""
    for p in user_posts:
        post_html += f'''
        <div class="post-card">
            <div class="post-header">
                <span class="post-user">@{p.username}</span>
                <span class="post-time">{p.timestamp.strftime('%b %d, %I:%M %p')}</span>
            </div>
            <div class="post-content">{p.content}</div>
            {f'<img src="{p.image}" class="post-image">' if p.image else ''}
        </div>
        '''
    
    return '''
    <!DOCTYPE html>
    <html><head><title>''' + user.username + ''''s Profile</title>
    <style>
    body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}
    .container{width:100%;max-width:600px;margin:auto;padding:12px;box-sizing:border-box;}
    
    /* Profile Card */
    .card{background:#1a2a3e;padding:30px;border-radius:20px;position:relative;}
    
    /* Settings Gear Icon */
    .settings-gear{position:absolute;top:15px;right:15px;font-size:24px;color:#888;text-decoration:none;cursor:pointer;transition:0.3s;}
    .settings-gear:hover{color:#00bfff;transform:rotate(90deg);}
    
    .profile-img{width:120px;height:120px;border-radius:50%;border:5px solid ''' + user.mood_color + ''';object-fit:cover;display:block;margin:0 auto 15px auto;}
    .btn{display:block;padding:15px;background:#00bfff;color:white;text-decoration:none;border-radius:12px;margin:10px 0;text-align:center;font-weight:bold;}
    .btn-mood{background:#ffc107;color:#111;}
    .btn-capsule{background:#6f42c1;}
    .btn-compliment{background:#28a745;}
    .btn-poll{background:#ffc107;color:#111;}
    .btn-upload{background:#28a745;width:100%;padding:12px;border:none;border-radius:12px;color:white;cursor:pointer;font-weight:bold;}
    .post-input{width:100%;padding:12px;border-radius:12px;border:none;background:#0b1a2e;color:white;font-size:14px;margin:10px 0;resize:none;}
    .post-btn{background:#00bfff;color:white;border:none;border-radius:12px;padding:12px 24px;cursor:pointer;font-weight:bold;}
    .post-card{background:#1a2a3e;padding:15px;border-radius:15px;margin-bottom:15px;}
    .post-header{display:flex;align-items:center;gap:10px;margin-bottom:5px;}
    .post-user{font-weight:bold;color:#00bfff;}
    .post-time{font-size:11px;color:#666;}
    .post-content{font-size:14px;color:#ddd;margin:5px 0;}
    .post-image{width:100%;border-radius:10px;margin-top:10px;}
    
    .bottom-nav{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;backdrop-filter:blur(8px);}
    .nav-item{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}
    .nav-item:hover,.nav-item.active{color:#00bfff;}
    .nav-icon{font-size:24px;margin-bottom:4px;}
    </style>
    </head>
    <body>
    <div class="container">
        <div class="card">
            <!-- SETTINGS GEAR ICON -->
            <a href="/settings" class="settings-gear">⚙️</a>
            
            <img src="''' + user.profile_pic + '''" class="profile-img">
            <h1>''' + user.username + ' ' + get_flag(user.country) + '''</h1>
            <p style="color:#ccc;font-size:14px;">Level ''' + str(user.level) + ''' • ⭐ ''' + str(user.xp) + ''' XP • 💎 ''' + str(user.coins) + ''' Crystals</p>
            <hr style="border-color:#334;">
            
            <a href="/mood" class="btn btn-mood">🎨 Change Mood Aura</a>
            <a href="/capsule" class="btn btn-capsule">📜 Bury a Time Capsule</a>
            <a href="/compliment" class="btn btn-compliment">💖 Send Anonymous Compliment</a>
            <a href="/poll" class="btn btn-poll">🗳️ Vote in Today's Poll</a>
            
            <hr style="border-color:#334;">
            <h3 style="color:#ccc;font-size:14px;text-align:left;">📸 Create a Post</h3>
            <form method="POST" enctype="multipart/form-data">
                <input type="file" name="post_image" accept="image/*" style="color:#ccc;margin:10px 0;">
                <textarea name="post_caption" class="post-input" placeholder="Write a caption..." rows="2"></textarea>
                <button type="submit" class="post-btn">Post to Feed</button>
            </form>
            
            <hr style="border-color:#334;">
            <h3 style="color:#ccc;font-size:14px;text-align:left;">🖼️ Update Profile Picture</h3>
            <form method="POST" enctype="multipart/form-data">
                <input type="file" name="profile_pic" accept="image/*">
                <button type="submit" class="btn-upload">Upload Picture</button>
            </form>
            
            <hr style="border-color:#334;">
            <h3 style="color:#ccc;font-size:14px;text-align:left;">📰 Your Posts</h3>
            ''' + (post_html if post_html else '<p style="color:#666;text-align:center;">You haven\'t posted anything yet.</p>') + '''
        </div>
    </div>
    
    <div class="bottom-nav">
        <a href="/" class="nav-item"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item"><span class="nav-icon">📨</span>Inbox</a>
        <a href="/profile/''' + user.username + '''" class="nav-item active"><span class="nav-icon">👤</span>Profile</a>
    </div>
    </body>
    </html>
    '''

# --- CHAT ROOMS (With History, Highlight & Delete) ---
@app.route('/chat/<room_name>')
def chat_room(room_name):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))

    if room_name == 'youth' and user.age > 25:
        return "<h1>⛔ Access Denied</h1><p>Youth Hub is strictly for ages 16-25.</p>"
    if room_name == 'premier' and user.age < 26:
        return "<h1>⛔ Access Denied</h1><p>Premier Lounge is for ages 26 and above.</p>"
    
    room_titles = {'global':'🌍 Global Lounge', 'youth':'🧑‍🤝‍🧑 Youth Hub', 'premier':'👑 Premier Lounge', 'gaming':'🎮 Gamers Hub', 'music':'🎵 Music & Vibes', 'study':'📚 Study Squad'}
    title = room_titles.get(room_name, '🌍 Room')
    
    # Load history from database
    past_messages = Message.query.filter_by(room=room_name).order_by(Message.timestamp.desc()).limit(30).all()[::-1]
    history_html = "".join([f'<div class="msg" id="msg-{m.id}"><span class="user">{m.username}:</span> {m.content}</div>' for m in past_messages])
    
    return f"""
    <!DOCTYPE html>
    <html><head><title>{title}</title>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <style>
        body{{background:#0b1a2e;color:white;font-family:Arial;padding:20px;}}
        #chat{{height:300px;border:1px solid #00bfff;overflow-y:scroll;padding:10px;background:#1a2a3e;border-radius:10px;margin-bottom:10px;}}
        .msg{{padding:8px;border-bottom:1px solid #334;cursor:pointer;}}
        .msg:hover{{background:#2a3a4e;}}
        .highlight{{background:#ffcc00 !important;color:#111;}}
        .user{{color:#00bfff;font-weight:bold;}}
        .reply-box{{background:#334;padding:8px;border-radius:5px;margin-bottom:10px;display:none;color:#ccc;}}
        input{{padding:10px;width:60%;border-radius:5px;border:none;}}
        button{{padding:10px;background:#00bfff;color:white;border:none;border-radius:5px;cursor:pointer;}}
        a{{color:#00bfff;text-decoration:none;display:block;margin-top:20px;}}
        .report-btn{{color:#ff5555;text-decoration:none;font-size:12px;float:right;margin-top:5px;cursor:pointer;}}
        .delete-btn{{color:#ff5555;text-decoration:none;font-size:12px;float:right;margin-top:5px;cursor:pointer;margin-right:10px;}}
        #voice-btn{{padding:10px;background:#6f42c1;color:white;border:none;border-radius:8px;cursor:pointer;margin:5px;}}
        #voice-btn:active{{background:#ff5555;}}
    </style>
    </head>
    <body>
    <h1>{title} <span class="online-dot"></span> Online</h1>
    <div id="reply-box" class="reply-box">Replying to: <span id="reply-target"></span></div>
    <div id="chat">
        {history_html}
    </div>
    <input id="msg" placeholder="Type a message...">
    <button onclick="sendMsg()">Send</button>
    <button id="voice-btn" onmousedown="startRecording()" onmouseup="stopRecording()">🎤 Hold to Record</button>
    <a href="/">⬅ Back to Rooms</a>
    <script>
        var socket = io();
        var username = "{user.username}";
        var room = "{room_name}";
        var replyToId = null;
        var mediaRecorder;
        var audioChunks = [];
        var isRecording = false;

        async function startRecording() {{
            try {{
                const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                mediaRecorder = new MediaRecorder(stream);
                mediaRecorder.start();
                isRecording = true;
                document.getElementById('voice-btn').innerText = '🔴 Recording...';
                mediaRecorder.addEventListener('dataavailable', event => {{
                    audioChunks.push(event.data);
                }});
                mediaRecorder.addEventListener('stop', () => {{
                    const audioBlob = new Blob(audioChunks, {{ type: 'audio/wav' }});
                    const reader = new FileReader();
                    reader.readAsDataURL(audioBlob);
                    reader.onloadend = function() {{
                        socket.emit('send_voice', {{room: room, audio: reader.result}});
                    }};
                    audioChunks = [];
                }});
            }} catch (err) {{
                alert('Allow microphone access.');
            }}
        }}
        function stopRecording() {{
            if(isRecording && mediaRecorder) {{
                mediaRecorder.stop();
                isRecording = false;
                document.getElementById('voice-btn').innerText = '🎤 Hold to Record';
            }}
        }}

        socket.on('connect', function() {{
            socket.emit('join_room', {{username: username, country: "{user.country}", room: room}});
        }});
        socket.on('message', function(data) {{
            addMessage(data[0], data[1], data[2]);
        }});

        function addMessage(user, content, msgId) {{
            var chat = document.getElementById('chat');
            var newMsg = document.createElement('div');
            newMsg.className = 'msg';
            newMsg.id = 'msg-' + msgId;
            var reportBtn = '';
            var deleteBtn = '';
            if(user !== 'System') {{
                reportBtn = ' <a href="#" class="report-btn" onclick="alert(\\'Report sent to IceQueenAL.\\'); return false;">🚩 Report</a>';
                if(user === username) {{
                    deleteBtn = ' <a href="#" class="delete-btn" onclick="deleteMessage(\\'' + msgId + '\\'); return false;">🗑️</a>';
                }}
            }}
            newMsg.innerHTML = '<span class="user">' + user + ':</span> ' + content + reportBtn + deleteBtn;
            
            // Highlight / Unhighlight (Double Tap)
            var lastTap = 0;
            newMsg.onclick = function(e) {{
                if(e.target.tagName.toLowerCase() === 'a') return;
                var currentTime = new Date().getTime();
                var tapLength = currentTime - lastTap;
                if (tapLength < 300 && tapLength > 0) {{
                    this.classList.remove('highlight');
                    replyToId = null;
                    document.getElementById('reply-box').style.display = 'none';
                }} else {{
                    document.querySelectorAll('.msg').forEach(el => el.classList.remove('highlight'));
                    this.classList.add('highlight');
                    replyToId = msgId;
                    document.getElementById('reply-box').style.display = 'block';
                    document.getElementById('reply-target').innerText = user + ': ' + content.substring(0,20) + '...';
                }}
                lastTap = currentTime;
            }};
            chat.appendChild(newMsg);
            chat.scrollTop = chat.scrollHeight;
        }}

        function deleteMessage(msgId) {{
            if(confirm('Delete this message?')) {{
                socket.emit('delete_message', {{msg_id: msgId, room: room}});
                document.getElementById('msg-' + msgId).remove();
            }}
        }}

        function sendMsg() {{
            var msg = document.getElementById('msg').value;
            if(msg.trim() !== '') {{
                socket.emit('send_message', {{msg: msg, room: room, reply_id: replyToId}});
                document.getElementById('msg').value = '';
                document.getElementById('reply-box').style.display = 'none';
                replyToId = null;
                document.querySelectorAll('.msg').forEach(el => el.classList.remove('highlight'));
            }}
        }}
        document.getElementById('msg').addEventListener('keypress', function (e) {{
            if (e.key === 'Enter') sendMsg();
        }});
    </script>
    </body>
    </html>
    """

# --- SOCKET EVENTS ---
@socketio.on('join_room')
def handle_join_room(data):
    room = data['room']
    join_room(room)
    emit('message', ['System', f"{data['username']} joined the chat!", 0], room=room)

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user = db.session.get(User, int(session['user_id']))

        user.online = True
        db.session.commit()
        emit('user_status', {'username': user.username, 'online': True}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        user = db.session.get(User, int(session['user_id']))

        user.online = False
        db.session.commit()
        emit('user_status', {'username': user.username, 'online': False}, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    user = db.session.get(User, int(session['user_id']))

    room = data['room']
    reply_id = data.get('reply_id')
    reply_msg = Message.query.get(reply_id) if reply_id else None
    reply_user = reply_msg.username if reply_msg else None
    
    # Save message to Database (so history loads)
    new_msg = Message(room=room, username=user.username, country=user.country, content=data['msg'])
    db.session.add(new_msg)
    db.session.commit()
    add_xp(user.username, 2) # XP reward for messaging
    
    emit('message', [user.username, data['msg'], new_msg.id], room=room)

@socketio.on('send_voice')
def handle_voice(data):
    user = db.session.get(User, int(session['user_id']))

    room = data['room']
    # Save voice message to DB
    new_msg = Message(room=room, username=user.username, country=user.country, content=data['audio'])
    db.session.add(new_msg)
    db.session.commit()
    emit('voice_message', [user.username, user.country, data['audio']], room=room)

@socketio.on('delete_message')
def handle_delete(data):
    msg = Message.query.get(data['msg_id'])
    if msg:
        db.session.delete(msg)
        db.session.commit()
    emit('message_deleted', data['msg_id'], room=data['room'])

# --- COMPOSE PAGE (Send DM or Anonymous Compliment) ---
@app.route('/compose', methods=['GET', 'POST'])
def compose():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))

    
    if request.method == 'POST':
        recipient = request.form['recipient']
        msg = request.form['message']
        is_anonymous = request.form.get('anonymous', False)
        
        if is_anonymous:
            compliment = Compliment(receiver=recipient, content=msg)
            db.session.add(compliment)
            db.session.commit()
        else:
            # Send as DM
            room_name = '_'.join(sorted([user.username, recipient]))
            dm_msg = Message(room=room_name, username=user.username, country=user.country, content=msg)
            db.session.add(dm_msg)
            db.session.commit()
        
        return redirect(url_for('inbox'))
    
    return '''
    <!DOCTYPE html>
    <html><head><title>Compose</title>
    <style>
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:20px;}
        .container{max-width:100%;margin:auto;background:#1a2a3e;padding:30px;border-radius:20px;}
        h1{color:#00bfff;}
        input,textarea{width:100%;padding:10px;border-radius:8px;border:none;margin:10px 0;box-sizing:border-box;}
        .btn{width:100%;padding:12px;background:#00bfff;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:bold;font-size:16px;}
        .btn-anon{background:#6f42c1;}
        a{color:#00bfff;text-decoration:none;display:block;margin-top:15px;text-align:center;}
        label{display:flex;align-items:center;gap:10px;color:#ccc;font-size:14px;}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>✉️ Compose Message</h1>
        <form method="POST">
            <input type="text" name="recipient" placeholder="Enter recipient's username" required>
            <textarea name="message" placeholder="Write your message..." rows="3" required></textarea>
            <label>
                <input type="checkbox" name="anonymous" value="true">
                Send anonymously (Compliment)
            </label>
            <button type="submit" class="btn">Send</button>
        </form>
        <a href="/inbox">⬅ Back to Inbox</a>
    </div>
    </body>
    </html>
    '''

# --- INBOX PAGE (Fixed Session) ---
@app.route('/inbox')
def inbox():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user = db.session.get(User, int(session['user_id']))
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
    except Exception:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    # --- 1. COMPLIMENTS ---
    compliments = Compliment.query.filter_by(receiver=user.username).order_by(Compliment.timestamp.desc()).limit(10).all()
    compliment_html = ""
    if compliments:
        for c in compliments:
            compliment_html += f'''
            <div class="inbox-item">
                <div class="inbox-icon">💖</div>
                <div class="inbox-content">
                    <div class="inbox-title">Anonymous Compliment</div>
                    <div class="inbox-message">"{c.content}"</div>
                    <div class="inbox-time">{c.timestamp.strftime('%b %d, %I:%M %p')}</div>
                </div>
            </div>
            '''
    else:
        compliment_html = '<p style="color:#666;text-align:center;padding:20px;">No compliments yet. Spread some kindness! 💖</p>'
    
    # --- 2. DIRECT MESSAGES ---
    user_rooms = db.session.query(Message.room).filter(
        (Message.room.contains(user.username + '_')) | (Message.room.contains('_' + user.username))
    ).distinct().all()
    
    room_names = [r[0] for r in user_rooms]
    dm_threads = []
    
    for room in room_names:
        last_msg = Message.query.filter_by(room=room).order_by(Message.timestamp.desc()).first()
        if last_msg:
            parts = room.split('_')
            other_person = parts[1] if parts[0] == user.username else parts[0]
            dm_threads.append({
                'room': room,
                'other': other_person,
                'last_msg': last_msg.content,
                'time': last_msg.timestamp.strftime('%b %d, %I:%M %p'),
                'sender': last_msg.username
            })
    
    dm_threads.sort(key=lambda x: x['time'], reverse=True)
    
    dm_html = ""
    if dm_threads:
        for thread in dm_threads:
            label = "📤 Sent" if thread['sender'] == user.username else "📥 Received"
            dm_html += f'''
            <a href="/dm/{thread['other']}" style="text-decoration:none;color:white;">
                <div class="dm-thread">
                    <div class="dm-info">
                        <span class="dm-user">💬 {thread['other']}</span>
                        <span class="dm-preview">{thread['last_msg'][:50]}...</span>
                    </div>
                    <div class="dm-meta">
                        <span class="dm-label">{label}</span>
                        <span class="dm-time">{thread['time']}</span>
                    </div>
                </div>
            </a>
            '''
    else:
        dm_html = '<p style="color:#666;text-align:center;padding:20px;">No messages yet. Start a conversation!</p>'
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head><title>Inbox</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        *{{box-sizing:border-box;}}
        body{{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}}
        .container{{width:100%;max-width:600px;margin:auto;padding:12px;box-sizing:border-box;}}
        h1{{margin-top:10px;}}
        .tabs{{display:flex;gap:20px;margin-bottom:15px;border-bottom:1px solid #334;padding-bottom:10px;}}
        .tab{{font-weight:bold;cursor:pointer;color:#888;padding-bottom:10px;margin-bottom:-11px;}}
        .tab.active{{color:#00bfff;border-bottom:2px solid #00bfff;}}
        .inbox-item{{background:#1a2a3e;border-radius:12px;padding:15px;margin-bottom:12px;display:flex;align-items:flex-start;gap:15px;}}
        .inbox-icon{{font-size:24px;margin-top:2px;}}
        .inbox-content{{flex:1;}}
        .inbox-title{{font-weight:bold;color:#00bfff;font-size:15px;}}
        .inbox-message{{font-size:14px;color:#ddd;margin:4px 0;}}
        .inbox-time{{font-size:11px;color:#666;}}
        .dm-thread{{background:#1a2a3e;border-radius:12px;padding:15px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;}}
        .dm-user{{font-weight:bold;font-size:16px;color:#00bfff;}}
        .dm-preview{{font-size:13px;color:#888;display:block;margin-top:4px;}}
        .dm-meta{{text-align:right;font-size:12px;color:#666;}}
        .dm-label{{display:block;font-size:11px;}}
        .tab-content{{display:none;}}
        .tab-content.active{{display:block;}}
        .compose-btn{{background:#28a745;color:white;border:none;border-radius:30px;padding:10px 20px;cursor:pointer;font-weight:bold;float:right;margin-top:10px;text-decoration:none;}}
        .bottom-nav{{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;}}
        .nav-item{{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}}
        .nav-item:hover,.nav-item.active{{color:#00bfff;}}
        .nav-icon{{font-size:24px;margin-bottom:4px;}}
    </style>
    </head>
    <body>
    <div class="container">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <h1>📨 Inbox</h1>
            <a href="/compose" class="compose-btn">+ Compose</a>
        </div>
        <div class="tabs">
            <div class="tab active" onclick="switchInboxTab('compliments')">💖 Compliments</div>
            <div class="tab" onclick="switchInboxTab('messages')">💬 Messages</div>
            <div class="tab" onclick="switchInboxTab('notifications')">🔔 Notifications</div>
        </div>
        <div id="compliments" class="tab-content active">{compliment_html}</div>
        <div id="messages" class="tab-content">
            <div style="max-height:500px;overflow-y:auto;">
                {dm_html}
            </div>
        </div>
        <div id="notifications" class="tab-content">
            <div style="background:#1a2a3e;border-radius:12px;padding:30px;text-align:center;">
                <div style="font-size:40px;">🔔</div>
                <p style="color:#888;font-size:14px;">System notifications will appear here.</p>
            </div>
        </div>
    </div>
    <script>
        function switchInboxTab(tabId) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelector(`.tab[onclick="switchInboxTab('${{tabId}}')"]`).classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }}
    </script>
    <div class="bottom-nav">
        <a href="/" class="nav-item"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item active"><span class="nav-icon">📨</span>Inbox</a>
        <a href="/profile/{user.username}" class="nav-item"><span class="nav-icon">👤</span>Profile</a>
    </div>
    </body>
    </html>
    '''
# --- LEADERBOARD PAGE (With Nav Bar) ---
@app.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user = db.session.get(User, int(session['user_id']))
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
    except Exception:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    current_user = user
    rising_stars = User.query.filter_by(is_premium=False).order_by(User.xp.desc()).limit(10).all()
    youth_peak = User.query.filter(User.is_premium==True, User.age.between(16, 25)).order_by(User.xp.desc()).limit(10).all()
    premier_peak = User.query.filter(User.is_premium==True, User.age >= 26).order_by(User.xp.desc()).limit(10).all()
    
    def generate_table(users, tier_name):
        if not users:
            return "<p style='color:#888;text-align:center;'>No users in this tier yet.</p>"
        html = '<div style="background:#1a2a3e;border-radius:15px;padding:15px;">'
        html += '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #334;color:#888;font-size:13px;">'
        html += '<span>#</span><span>User</span><span>Title</span><span>XP</span></div>'
        for i, u in enumerate(users):
            rank = i + 1
            medal = ''
            title = ''
            if rank == 1:
                medal = '🥇'
                if tier_name == 'rising': title = 'The Shard Champion'
                elif tier_name == 'youth': title = 'The Frost Prince / Princess'
                elif tier_name == 'premier': title = 'The Glacier Emperor / Empress'
            elif rank == 2:
                medal = '🥈'
                if tier_name == 'rising': title = 'The Frostling'
                elif tier_name == 'youth': title = 'The Ice Knight'
                elif tier_name == 'premier': title = 'The Frost Commander'
            elif rank == 3:
                medal = '🥉'
                if tier_name == 'rising': title = 'The Glimmer'
                elif tier_name == 'youth': title = 'The Snow Scout'
                elif tier_name == 'premier': title = 'The Crystal Duke / Duchess'
            else:
                medal = f'{rank}'
                if tier_name == 'rising': title = 'The Ice Seeker'
                elif tier_name == 'youth': title = 'The Frost Guardian'
                elif tier_name == 'premier': title = 'The Crystal Guard'
            html += f'''
            <div class="rank-card">
                <div style="display:flex;align-items:center;gap:12px;flex:1;">
                    <span style="width:30px;font-weight:bold;color:#888;">{medal}</span>
                    <img src="{u.profile_pic}" class="rank-avatar">
                    <div class="rank-info">
                        <div class="rank-name">{u.username}</div>
                        <div class="rank-xp">{title}</div>
                    </div>
                </div>
                <div style="font-size:14px;color:#888;">⭐ {u.xp}</div>
            </div>
            '''
        html += '</div>'
        return html
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head><title>Leaderboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        *{{box-sizing:border-box;}}
        body{{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}}
        .container{{width:100%;max-width:600px;margin:auto;padding:12px;box-sizing:border-box;}}
        h1{{margin-top:10px;}}
        .tabs{{display:flex;gap:5px;margin-bottom:20px;overflow-x:auto;}}
        .tab{{flex:1;min-width:80px;padding:8px 5px;text-align:center;background:#1a2a3e;border-radius:10px;cursor:pointer;color:#888;font-size:12px;font-weight:bold;}}
        .tab.active{{background:#00bfff;color:white;}}
        .rank-card{{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:10px;margin-bottom:8px;background:#1a2a3e;}}
        .rank-avatar{{width:35px;height:35px;border-radius:50%;object-fit:cover;}}
        .rank-info{{display:flex;flex-direction:column;}}
        .rank-name{{font-weight:bold;color:#00bfff;font-size:14px;}}
        .rank-xp{{font-size:11px;color:#888;}}
        .tab-content{{display:none;}}
        .tab-content.active{{display:block;}}
        .bottom-nav{{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;}}
        .nav-item{{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}}
        .nav-item:hover,.nav-item.active{{color:#00bfff;}}
        .nav-icon{{font-size:24px;margin-bottom:4px;}}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>🏆 Leaderboard</h1>
        <div class="tabs">
            <div class="tab active" onclick="switchTab('rising')">🌟 Rising Stars</div>
            <div class="tab" onclick="switchTab('youth')">🧊 Youth Ice Peak</div>
            <div class="tab" onclick="switchTab('premier')">👑 Premier Ice Peak</div>
            <div class="tab" onclick="switchTab('guardian')">🏔️ Hall of Guardians</div>
        </div>
        <div id="rising" class="tab-content active">{generate_table(rising_stars, 'rising')}</div>
        <div id="youth" class="tab-content">{generate_table(youth_peak, 'youth')}</div>
        <div id="premier" class="tab-content">{generate_table(premier_peak, 'premier')}</div>
        <div id="guardian" class="tab-content">
            <div style="background:#1a2a3e;border-radius:15px;padding:20px;text-align:center;border:2px solid gold;">
                <div style="font-size:40px;">👑</div>
                <h2 style="color:gold;">The Glacier Guardian</h2>
                <p style="color:#888;">The weekly champion will be displayed here.</p>
            </div>
        </div>
        <hr style="border-color:#334;margin:20px 0;">
        <div style="text-align:center;font-size:13px;color:#888;">Your XP: ⭐ {current_user.xp}</div>
    </div>
    
    <script>
        function switchTab(tabId) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelector(`.tab[onclick="switchTab('${{tabId}}')"]`).classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }}
    </script>
    
    <div class="bottom-nav">
        <a href="/" class="nav-item"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item active"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item"><span class="nav-icon">📨</span>Inbox</a>
        <a href="/profile/{current_user.username}" class="nav-item"><span class="nav-icon">👤</span>Profile</a>
    </div>
    </body>
    </html>
    '''

# --- PROFILE ROOMS DISPLAY ---
@app.route('/profile_rooms/<username>')
def profile_rooms(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(username=username).first()
    if not user:
        return "User not found!"
    
    # Get rooms created by this user
    all_rooms = db.session.query(Message.room).distinct().all()
    room_names = [r[0] for r in all_rooms]
    user_rooms = [r for r in room_names if r.startswith(user.username + '_')]
    
    html = f'<h2 style="color:#00bfff;">🏠 Rooms Created by {username}</h2>'
    for r in user_rooms:
        display_name = r.replace('_', ' ').title()
        html += f'<a href="/chat/{r}" style="display:block;background:#1a2a3e;padding:15px;border-radius:10px;margin:10px 0;text-decoration:none;color:white;">{display_name}</a>'
    
    return html + '<a href="/" style="color:#00bfff;text-decoration:none;display:block;margin-top:20px;">⬅ Back</a>'

# --- SETTINGS PAGE (Full Screen, Fixed Session, Beautiful) ---
@app.route('/settings')
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.session.get(User, int(session['user_id']))
    if not user:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    html_part = f'''
    <!DOCTYPE html>
    <html><head><title>Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body{{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}}
        .container{{padding:15px;width:100%;max-width:600px;margin:auto;box-sizing:border-box;}}
        .header{{display:flex;align-items:center;gap:15px;margin-bottom:20px;}}
        .back-btn{{color:#00bfff;text-decoration:none;font-size:24px;}}
        h1{{margin:0;font-size:24px;}}
        .settings-item{{display:flex;align-items:center;justify-content:space-between;padding:15px;background:#1a2a3e;border-radius:12px;margin-bottom:10px;text-decoration:none;color:white;}}
        .settings-item:hover{{background:#2a3a5e;}}
        .settings-icon{{font-size:20px;margin-right:15px;}}
        .settings-text{{flex:1;font-size:15px;}}
        .settings-arrow{{color:#888;font-size:14px;}}
        .section-title{{color:#888;font-size:13px;margin:20px 0 10px 5px;text-transform:uppercase;letter-spacing:1px;}}
        .bottom-nav{{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;backdrop-filter:blur(8px);}}
        .nav-item{{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}}
        .nav-item:hover,.nav-item.active{{color:#00bfff;}}
        .nav-icon{{font-size:24px;margin-bottom:4px;}}
    </style>
    </head>
    <body>
    <div class="container">
        <div class="header">
            <a href="/profile/{user.username}" class="back-btn">⬅</a>
            <h1>⚙️ Settings</h1>
        </div>
        
        <div class="section-title">Account</div>
        <a href="/profile/{user.username}" class="settings-item">
            <span class="settings-icon">👤</span>
            <span class="settings-text">Profile</span>
            <span class="settings-arrow">›</span>
        </a>
        <a href="/mood" class="settings-item">
            <span class="settings-icon">🎨</span>
            <span class="settings-text">Mood Aura</span>
            <span class="settings-arrow">›</span>
        </a>
        
        <div class="section-title">Privacy</div>
        <a href="/privacy" class="settings-item">
            <span class="settings-icon">🔒</span>
            <span class="settings-text">Privacy & Security</span>
            <span class="settings-arrow">›</span>
        </a>
        <a href="/blocked" class="settings-item">
            <span class="settings-icon">🚫</span>
            <span class="settings-text">Blocked Users</span>
            <span class="settings-arrow">›</span>
        </a>
        
        <div class="section-title">About & Support</div>
        <a href="/about" class="settings-item">
            <span class="settings-icon">🧊</span>
            <span class="settings-text">About IceConnect</span>
            <span class="settings-arrow">›</span>
        </a>
        <a href="#" class="settings-item" onclick="openFeedback()">
            <span class="settings-icon">💬</span>
            <span class="settings-text">Send Feedback & Rating</span>
            <span class="settings-arrow">›</span>
        </a>
        
        <div class="section-title">Account Actions</div>
        <a href="/logout" class="settings-item" style="color:#ff5555;">
            <span class="settings-icon">🚪</span>
            <span class="settings-text">Logout</span>
            <span class="settings-arrow">›</span>
        </a>
        <a href="#" class="settings-item" style="color:#ff5555;" onclick="if(confirm('Are you sure you want to delete your account? This cannot be undone.')){{alert('Account deletion coming soon!')}}">
            <span class="settings-icon">🗑️</span>
            <span class="settings-text">Delete Account</span>
            <span class="settings-arrow">›</span>
        </a>
    </div>
    
    <div class="bottom-nav">
        <a href="/" class="nav-item"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item"><span class="nav-icon">📨</span>Inbox</a>
        <a href="/profile/{user.username}" class="nav-item active"><span class="nav-icon">👤</span>Profile</a>
    </div>
    
    <div id="feedbackModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:9999;justify-content:center;align-items:center;">
        <div style="background:#1a2a3e;padding:30px;border-radius:20px;max-width:400px;width:90%;">
            <h2 style="color:#00bfff;margin-top:0;">💬 Send Feedback</h2>
            <p style="color:#888;font-size:14px;">Help us improve IceConnect!</p>
            <div style="font-size:30px;margin:15px 0;cursor:pointer;">
                <span onclick="setRating(1)">☆</span><span onclick="setRating(2)">☆</span><span onclick="setRating(3)">☆</span><span onclick="setRating(4)">☆</span><span onclick="setRating(5)">☆</span>
            </div>
            <textarea id="feedbackMsg" placeholder="Write your thoughts here..." style="width:100%;padding:10px;border-radius:10px;border:none;margin:10px 0;height:80px;resize:none;"></textarea>
            <button onclick="submitFeedback()" style="width:100%;padding:12px;background:#00bfff;color:white;border:none;border-radius:10px;font-weight:bold;cursor:pointer;">Send Feedback</button>
            <button onclick="closeFeedback()" style="width:100%;padding:10px;background:transparent;color:#888;border:none;margin-top:10px;cursor:pointer;">Cancel</button>
        </div>
    </div>
    </body>
    </html>
    '''
    
    script_part = '''
    <script>
        let currentRating = 0;
        function setRating(n) {
            currentRating = n;
            let stars = document.querySelectorAll('#feedbackModal span');
            stars.forEach((s, i) => s.innerText = i < n ? '⭐' : '☆');
        }
        function openFeedback() {
            document.getElementById('feedbackModal').style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }
        function closeFeedback() {
            document.getElementById('feedbackModal').style.display = 'none';
            document.body.style.overflow = 'auto';
        }
        function submitFeedback() {
            let msg = document.getElementById('feedbackMsg').value;
            if(currentRating === 0) { 
                alert('Please select a rating!'); 
                return; 
            }
            if(msg.trim() === '') { 
                alert('Please write a message!'); 
                return; 
            }
            fetch('/feedback', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({rating: currentRating, message: msg})
            }).then(() => {
                alert('✅ Thank you for your feedback!');
                closeFeedback();
                document.getElementById('feedbackMsg').value = '';
                setRating(0);
            });
        }
    </script>
    '''
    
    return html_part + script_part

    
# --- ABOUT PAGE (The long professional version) ---
@app.route('/about')
def about():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return '''
    <!DOCTYPE html>
    <html><head><title>About IceConnect</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:20px;}
        .container{max-width:100%;margin:auto;background:#1a2a3e;padding:30px;border-radius:20px;}
        h1{color:#00bfff;border-bottom:1px solid #334;padding-bottom:10px;}
        h3{color:#00bfff;margin-top:20px;}
        p{color:#ddd;line-height:1.6;font-size:15px;}
        a{color:#00bfff;text-decoration:none;display:inline-block;margin-top:20px;}
        .footer{border-top:1px solid #334;padding-top:20px;margin-top:30px;text-align:center;color:#666;font-size:13px;}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>🧊 About IceConnect</h1>
        
        <h3>What is IceConnect?</h3>
        <p>IceConnect is a global, gamified social platform designed exclusively for users aged 16 and above. It is not a social media feed. It is a digital community hub where users connect, compete, create, and belong. By blending real-time messaging with RPG-style achievements, trivia tournaments, and anonymous kindness features, IceConnect fills a massive void in the current social media landscape: the need for safe, meaningful, and fun human interaction.</p>
        
        <h3>Why was IceConnect created?</h3>
        <p>IceConnect was born out of a personal observation: Today's social media platforms are designed for passive scrolling, not active connection. Teenagers and young adults are lonelier than ever, despite having more apps than ever. They are bombarded with algorithms, ads, and toxic echo chambers. They are not looking for more content—they are looking for real friends.</p>
        
        <h3>What makes IceConnect different?</h3>
        <p>IceConnect gives users something they cannot get anywhere else: Status they can earn, not buy. Safety they can trust, through age gates, active moderation, and anonymous kindness. Connection they can feel, through real people, real conversations, and real friendships. It is not an app they scroll on. It is an app they live in.</p>
        
        <h3>Who built IceConnect?</h3>
        <p>IceConnect was founded in 2026 by a visionary developer with a simple belief: that the internet should be a place where people connect meaningfully, not just scroll endlessly. The platform was built entirely from scratch—one line of code, one feature, one community at a time. IceConnect is independently developed, passionately maintained, and growing with heart.</p>
        
        <h3>Our Mission</h3>
        <p>To cultivate a safe, engaging, and rewarding digital environment where people from every corner of the world can build meaningful relationships, express their individuality, and grow through shared experiences.</p>
        
        <h3>Core Values</h3>
        <p><b>Safety First:</b> Every feature is designed with user protection and data privacy as a non-negotiable foundation.<br>
        <b>Authenticity:</b> We prioritize genuine interaction over passive consumption.<br>
        <b>Innovation:</b> We continuously evolve the platform with user feedback.<br>
        <b>Global Citizenship:</b> IceConnect transcends borders, connecting cultures across continents.</p>
        
        <h3>Contact</h3>
        <p>For business inquiries, press, partnerships, or investments, reach out directly:<br>
        <b>📧 icequeenal.dev@gmail.com</b></p>
        
        <div class="footer">
            <b>IceConnect™</b> — Created by IQAL Studios Ltd.<br>
            © 2026 All Rights Reserved.
        </div>
        <a href="/settings">⬅ Back to Settings</a>
    </div>
    </body>
    </html>
    '''

# --- FEEDBACK SUBMISSION ---
@app.route('/feedback', methods=['POST'])
def feedback():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    data = request.get_json()
    user = db.session.get(User, int(session['user_id']))

    
    feedback_msg = f"{user.username} rated {data['rating']} stars: {data['message']}"
    with open('feedback_log.txt', 'a') as f:
        f.write(feedback_msg + '\n')
    
    return "Feedback saved"

# --- PRIVACY & SECURITY SETTINGS ---
@app.route('/privacy')
def privacy():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        user = db.session.get(User, int(session['user_id']))
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
    except Exception:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head><title>Privacy & Security</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        * { box-sizing: border-box; }
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}
        .container{width:100%;max-width:600px;margin:auto;padding:12px;box-sizing:border-box;}
        .card{background:#1a2a3e;padding:20px;border-radius:15px;margin-bottom:15px;}
        h1{color:#00bfff;}
        .setting-item{display:flex;justify-content:space-between;padding:15px 0;border-bottom:1px solid #334;}
        .setting-item:last-child{border-bottom:none;}
        .btn{background:#00bfff;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;}
        .bottom-nav{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;}
        .nav-item{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}
        .nav-item:hover,.nav-item.active{color:#00bfff;}
        .nav-icon{font-size:24px;margin-bottom:4px;}
    </style>
    </head>
    <body>
    <div class="container">
        <div class="card">
            <h1>🔒 Privacy & Security</h1>
            <div class="setting-item">
                <span>🔐 Two-Factor Authentication</span>
                <span style="color:#888;">Coming Soon</span>
            </div>
            <div class="setting-item">
                <span>👁️ Who can see my profile</span>
                <span style="color:#888;">Everyone</span>
            </div>
            <div class="setting-item">
                <span>📧 Email Notifications</span>
                <span style="color:#888;">On</span>
            </div>
            <div class="setting-item">
                <span>🗑️ Delete Account</span>
                <button class="btn" style="background:#ff5555;" onclick="alert('Are you sure? This cannot be undone.')">Delete</button>
            </div>
        </div>
        <a href="/settings" style="color:#00bfff;text-decoration:none;display:block;text-align:center;margin-top:10px;">⬅ Back to Settings</a>
    </div>
    <div class="bottom-nav">
        <a href="/" class="nav-item"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item"><span class="nav-icon">📨</span>Inbox</a>
        <a href="/profile/''' + user.username + '''" class="nav-item"><span class="nav-icon">👤</span>Profile</a>
    </div>
    </body>
    </html>
    ''')

@app.route('/blocked')
def blocked():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        user = db.session.get(User, int(session['user_id']))
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
    except Exception:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head><title>Blocked Users</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        * { box-sizing: border-box; }
        body{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:0 0 90px 0;}
        .container{width:100%;max-width:600px;margin:auto;padding:12px;box-sizing:border-box;}
        .card{background:#1a2a3e;padding:20px;border-radius:15px;margin-bottom:15px;}
        h1{color:#00bfff;}
        .blocked-user{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #334;}
        .blocked-user:last-child{border-bottom:none;}
        .unblock-btn{background:#ff5555;color:white;border:none;padding:5px 15px;border-radius:5px;cursor:pointer;}
        .bottom-nav{position:fixed;bottom:0;left:0;width:100%;background:#0f1a2b;display:flex;justify-content:space-around;padding:12px 0 20px 0;border-top:1px solid #1a2a3e;z-index:999;}
        .nav-item{color:#777;text-decoration:none;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;flex:1;}
        .nav-item:hover,.nav-item.active{color:#00bfff;}
        .nav-icon{font-size:24px;margin-bottom:4px;}
    </style>
    </head>
    <body>
    <div class="container">
        <div class="card">
            <h1>🚫 Blocked Users</h1>
            <p style="color:#888;text-align:center;padding:20px;">You haven't blocked any users yet.</p>
        </div>
        <a href="/settings" style="color:#00bfff;text-decoration:none;display:block;text-align:center;margin-top:10px;">⬅ Back to Settings</a>
    </div>
    <div class="bottom-nav">
        <a href="/" class="nav-item"><span class="nav-icon">🏠</span>Home</a>
        <a href="/chatrooms" class="nav-item"><span class="nav-icon">💬</span>Chatrooms</a>
        <a href="/leaderboard" class="nav-item"><span class="nav-icon">🏆</span>Leaderboard</a>
        <a href="/inbox" class="nav-item"><span class="nav-icon">📨</span>Inbox</a>
        <a href="/profile/''' + user.username + '''" class="nav-item"><span class="nav-icon">👤</span>Profile</a>
    </div>
    </body>
    </html>
    ''')
 
# --- DELETE ROOM ---
@app.route('/delete_room/<room_name>')
def delete_room(room_name):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))

    
    # Only allow the creator to delete the room
    if not room_name.startswith(user.username + '_'):
        return "You are not the creator of this room."
    
    # Delete all messages in this room
    Message.query.filter_by(room=room_name).delete()
    db.session.commit()
    
    return redirect(url_for('chatrooms'))

# --- LIKE POST ---
@app.route('/like/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    post = Post.query.get(post_id)
    if post:
        post.likes += 1
        db.session.commit()
    return "Liked"

# --- COMMENT POST ---
@app.route('/comment/<int:post_id>', methods=['POST'])
def comment_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))

    data = request.get_json()
    content = data.get('content')
    if content:
        comment = Comment(post_id=post_id, username=user.username, content=content)
        db.session.add(comment)
        db.session.commit()
    return "Commented"

# --- MARK COMMENTS AS READ ---
@app.route('/read/comments/<int:post_id>', methods=['POST'])
def read_comments(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    comments = Comment.query.filter_by(post_id=post_id).all()
    for c in comments:
        c.read = True
    db.session.commit()
    return "OK"


# --- FOUNDER'S ADMIN PANEL (Top Secret) ---
@app.route('/admin')
def admin_panel():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, int(session['user_id']))

    
    # ONLY THE FOUNDER CAN ACCESS THIS
    if user.username != 'IceQueenAL':
        return "<h1>⛔ Access Denied</h1><p>This page is for the Founder only.</p>"
    
    # Collect Data
    total_users = User.query.count()
    active_today = User.query.filter(User.last_seen > datetime.datetime.now() - datetime.timedelta(days=1)).count()
    total_premium = User.query.filter_by(is_premium=True).count()
    reports = Report.query.filter_by(resolved=False).order_by(Report.timestamp.desc()).limit(10).all()    
    
    # Read Feedback from file
    feedback_entries = []
    try:
        with open('feedback_log.txt', 'r') as f:
            feedback_entries = f.readlines()
    except:
        feedback_entries = ["No feedback yet."]
    
    return f'''
    <!DOCTYPE html>
    <html><head><title>Founder Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body{{font-family:Arial;background:#0b1a2e;color:white;margin:0;padding:20px;}}
        .container{{max-width:100%;margin:auto;background:#1a2a3e;padding:30px;border-radius:20px;}}
        h1{{color:#00bfff;border-bottom:1px solid #334;padding-bottom:10px;}}
        .stat{{background:#2a3a5e;padding:15px;border-radius:10px;margin:10px 0;display:flex;justify-content:space-between;align-items:center;}}
        .stat-number{{font-size:24px;font-weight:bold;color:#00bfff;}}
        .feedback-item{{background:#0b1a2e;padding:10px;border-radius:8px;margin:8px 0;font-size:14px;color:#ccc;}}
        a{{color:#00bfff;text-decoration:none;display:block;margin-top:20px;}}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>🛡️ Founder Admin Panel</h1>
        
        <div class="stat">Total Registered Users <span class="stat-number">{total_users}</span></div>
        <div class="stat">Active Users (Last 24h) <span class="stat-number">{active_today}</span></div>
        <div class="stat">Premium Subscribers <span class="stat-number">{total_premium}</span></div>
        
        <hr style="border-color:#334;">
        <h3>📬 Recent Feedback</h3>
        <hr style="border-color:#334;">
        <h3>🚩 Pending Reports</h3>
        {''.join([f'<div class="feedback-item">User <b>{r.reported}</b> reported by {r.reporter}: {r.reason}</div>' for r in reports]) if reports else '<p style="color:#888;">No pending reports.</p>'}
        {''.join([f'<div class="feedback-item">{f}</div>' for f in feedback_entries[-10:]])}
        
        <hr style="border-color:#334;">
        <p style="color:#888;text-align:center;font-size:13px;">🔒 Only the Founder can see this page.</p>
        <a href="/">⬅ Back to App</a>
    </div>
    </body>
    </html>
    '''

# --- REPORT SYSTEM ---
@app.route('/report', methods=['POST'])
def report_user():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    report = Report(
        reporter=session.get('username'),
        reported=data['reported'],
        reason=data['reason']
    )
    db.session.add(report)
    db.session.commit()
    return jsonify({'success': True})

# --- TEMPORARY DATABASE SETUP ROUTE ---
@app.route('/setup_db')
def setup_db():
    with app.app_context():
        db.create_all()
    return "✅ Database tables created successfully! You can now go back to the app."

# --- LOGOUT ---
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# --- RUN APP ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("✅ Database connected and tables created!")
    socketio.run(app, host='0.0.0.0', port=5000)

