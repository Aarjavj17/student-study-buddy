from flask import Flask, jsonify, request, session, render_template, g
import sqlite3
import hashlib
import os
from datetime import datetime, timedelta
import json
from database import get_db_connection, DB_PATH

app = Flask(__name__, template_folder='.')
app.secret_key = 'super-secret-student-buddy-key-2026-enjoy-studying'
app.permanent_session_lifetime = timedelta(days=7)

# Ensure database structure and content are synchronized on startup
from database import init_db
init_db()


# --- DATABASE LIFECYCLE ---
def get_db():
    if 'db' not in g:
        g.db = get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# --- HELPER FUNCTIONS ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_current_user():
    if 'user_id' not in session:
        return None
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],))
    return cursor.fetchone()

def update_user_stats(user_id, xp_gain=0, hours_gain=0.0):
    db = get_db()
    cursor = db.cursor()
    
    # Get current stats
    cursor.execute('SELECT xp, level, total_hours FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        return None, False
    
    new_xp = user['xp'] + xp_gain
    new_hours = user['total_hours'] + hours_gain
    
    # Level formula: level = (xp // 150) + 1
    new_level = (new_xp // 150) + 1
    leveled_up = new_level > user['level']
    
    cursor.execute('''
    UPDATE users 
    SET xp = ?, level = ?, total_hours = ? 
    WHERE id = ?
    ''', (new_xp, new_level, new_hours, user_id))
    
    db.commit()
    return {
        'xp': new_xp,
        'level': new_level,
        'total_hours': round(new_hours, 2),
        'xp_gain': xp_gain,
        'hours_gain': hours_gain
    }, leveled_up

def award_badge(user_id, badge_name):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute('''
        INSERT INTO user_badges (user_id, badge_name)
        VALUES (?, ?)
        ''', (user_id, badge_name))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        # Already unlocked
        return False

def update_streak(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT streak, last_study_date FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        return 0, False
        
    current_streak = user['streak']
    last_study = user['last_study_date']
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    new_streak = current_streak
    streak_updated = False
    
    if not last_study:
        new_streak = 1
        streak_updated = True
    elif last_study == yesterday_str:
        new_streak = current_streak + 1
        streak_updated = True
    elif last_study == today_str:
        # Already studied today, streak stays the same
        pass
    else:
        # Missed a day, reset streak to 1
        new_streak = 1
        streak_updated = True
        
    if streak_updated:
        cursor.execute('''
        UPDATE users 
        SET streak = ?, last_study_date = ? 
        WHERE id = ?
        ''', (new_streak, today_str, user_id))
        db.commit()
        
        # Check for streak achievements
        if new_streak >= 3:
            award_badge(user_id, 'Daily Champ 👑')
            
    return new_streak, streak_updated

# --- PAGES ---
@app.route('/')
def index():
    return render_template('index.html')

# --- API: AUTHENTICATION ---
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if len(username) < 3 or len(password) < 4:
        return jsonify({'error': 'Username (min 3 chars) and password (min 4 chars) required.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    # Check if user already exists
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        return jsonify({'error': 'Username already taken.'}), 409
        
    hashed_pw = hash_password(password)
    
    try:
        cursor.execute('''
        INSERT INTO users (username, password, xp, level, streak, total_hours)
        VALUES (?, ?, 0, 1, 0, 0.0)
        ''', (username, hashed_pw))
        db.commit()
        
        # Get new user ID
        user_id = cursor.lastrowid
        session.permanent = True
        session['user_id'] = user_id
        
        # Award welcome badge
        award_badge(user_id, 'Ignition Flame 🔥')
        
        return jsonify({'message': 'Registration successful!', 'user': {'id': user_id, 'username': username}})
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    
    if not user or user['password'] != hash_password(password):
        return jsonify({'error': 'Invalid username or password.'}), 401
        
    session.permanent = True
    session['user_id'] = user['id']
    
    return jsonify({
        'message': 'Login successful!',
        'user': {
            'id': user['id'],
            'username': user['username']
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'message': 'Logged out successfully.'})

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    user = get_current_user()
    if not user:
        return jsonify({'authenticated': False}), 401
    
    return jsonify({
        'authenticated': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'xp': user['xp'],
            'level': user['level'],
            'streak': user['streak'],
            'total_hours': round(user['total_hours'], 2)
        }
    })

# --- API: STUDY STATS & BADGES ---
@app.route('/api/stats', methods=['GET'])
def get_stats():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    # Fetch badges
    cursor.execute('SELECT badge_name, unlocked_at FROM user_badges WHERE user_id = ? ORDER BY unlocked_at DESC', (user['id'],))
    badges = [dict(row) for row in cursor.fetchall()]
    
    # Fetch quiz counts
    cursor.execute('SELECT COUNT(*) as count FROM quiz_attempts WHERE user_id = ?', (user['id'],))
    quizzes_done = cursor.fetchone()['count']
    
    # Fetch completed tasks count
    cursor.execute('SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND completed = 1', (user['id'],))
    tasks_done = cursor.fetchone()['count']
    
    return jsonify({
        'username': user['username'],
        'xp': user['xp'],
        'level': user['level'],
        'streak': user['streak'],
        'total_hours': round(user['total_hours'], 2),
        'quizzes_completed_count': quizzes_done,
        'tasks_completed_count': tasks_done,
        'badges': badges
    })

# --- API: STUDY PLANNER (TASKS) ---
@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'GET':
        cursor.execute('SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC', (user['id'],))
        tasks = [dict(row) for row in cursor.fetchall()]
        return jsonify(tasks)
        
    elif request.method == 'POST':
        data = request.json or {}
        title = data.get('title', '').strip()
        subject = data.get('subject', 'General').strip()
        
        if not title:
            return jsonify({'error': 'Task title is required.'}), 400
            
        cursor.execute('''
        INSERT INTO tasks (user_id, title, subject, completed)
        VALUES (?, ?, ?, 0)
        ''', (user['id'], title, subject))
        db.commit()
        
        new_id = cursor.lastrowid
        return jsonify({'id': new_id, 'title': title, 'subject': subject, 'completed': 0})

@app.route('/api/tasks/<int:task_id>', methods=['PUT', 'DELETE'])
def update_delete_task(task_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    # Ensure task belongs to user
    cursor.execute('SELECT * FROM tasks WHERE id = ? AND user_id = ?', (task_id, user['id']))
    task = cursor.fetchone()
    if not task:
        return jsonify({'error': 'Task not found.'}), 404
        
    if request.method == 'DELETE':
        cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        db.commit()
        return jsonify({'message': 'Task deleted successfully.'})
        
    elif request.method == 'PUT':
        data = request.json or {}
        completed = data.get('completed')
        
        if completed is None:
            return jsonify({'error': 'Completed status required.'}), 400
            
        new_status = 1 if completed else 0
        old_status = task['completed']
        
        cursor.execute('UPDATE tasks SET completed = ? WHERE id = ?', (new_status, task_id))
        db.commit()
        
        # Award or remove XP based on completion toggle
        xp_change = 0
        leveled_up = False
        stats = None
        
        if new_status == 1 and old_status == 0:
            xp_change = 15 # +15 XP for completing a planner task
        elif new_status == 0 and old_status == 1:
            xp_change = -15 # -15 XP if unchecked
            
        if xp_change != 0:
            stats, leveled_up = update_user_stats(user['id'], xp_gain=xp_change)
            
            # Check for completed tasks count badges
            cursor.execute('SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND completed = 1', (user['id'],))
            total_done = cursor.fetchone()['count']
            if total_done >= 5:
                award_badge(user['id'], 'Task Conqueror 🎯')
            
        return jsonify({
            'message': 'Task status updated.',
            'task': {'id': task_id, 'completed': new_status},
            'xp_change': xp_change,
            'leveled_up': leveled_up,
            'stats': stats
        })

# --- API: STUDY NOTES ---
@app.route('/api/notes/<topic_id>', methods=['GET', 'POST'])
def handle_notes(topic_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'GET':
        cursor.execute('SELECT content FROM notes WHERE user_id = ? AND topic_id = ?', (user['id'], topic_id))
        row = cursor.fetchone()
        content = row['content'] if row else ""
        return jsonify({'topic_id': topic_id, 'content': content})
        
    elif request.method == 'POST':
        data = request.json or {}
        content = data.get('content', '')
        
        # Insert or replace
        cursor.execute('''
        INSERT INTO notes (user_id, topic_id, content, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, topic_id) DO UPDATE SET content=excluded.content, updated_at=CURRENT_TIMESTAMP
        ''', (user['id'], topic_id, content))
        db.commit()
        
        # Award 5 XP for taking notes (if new note, let's say)
        # Check if notes existed before to keep XP gamification fair
        cursor.execute('SELECT COUNT(*) as count FROM notes WHERE user_id = ? AND topic_id = ?', (user['id'], topic_id))
        # Note: since we already saved it, count is always >= 1. Let's see if we want to reward 5 XP
        # We can award a small 5 XP for active studying, max once per write session or simply return
        stats, leveled_up = update_user_stats(user['id'], xp_gain=5)
        
        return jsonify({
            'message': 'Notes saved successfully.',
            'xp_change': 5,
            'stats': stats,
            'leveled_up': leveled_up
        })

# --- API: VIDEOS ---
@app.route('/api/videos', methods=['GET'])
def get_videos():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM videos')
    videos = [dict(row) for row in cursor.fetchall()]
    return jsonify(videos)

# --- API: QUIZZES ---
@app.route('/api/quizzes', methods=['GET'])
def get_quizzes():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM quiz_questions')
    rows = cursor.fetchall()
    
    # Group by topic_id
    quizzes = {}
    for row in rows:
        t_id = row['topic_id']
        if t_id not in quizzes:
            quizzes[t_id] = []
        quizzes[t_id].append({
            'id': row['id'],
            'question': row['question'],
            'options': json.loads(row['options']),
            'correct_index': row['correct_index']
        })
    return jsonify(quizzes)

@app.route('/api/quizzes/submit', methods=['POST'])
def submit_quiz():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    topic_id = data.get('topic_id')
    user_answers = data.get('answers', []) # list of indices e.g. [1, 0, 2...]
    
    if not topic_id or not isinstance(user_answers, list):
        return jsonify({'error': 'Topic ID and answers are required.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    # Get correct questions
    cursor.execute('SELECT id, correct_index FROM quiz_questions WHERE topic_id = ? ORDER BY id ASC', (topic_id,))
    questions = cursor.fetchall()
    
    if not questions:
        return jsonify({'error': 'No questions found for this topic.'}), 404
        
    score = 0
    total = len(questions)
    
    for i, q in enumerate(questions):
        if i < len(user_answers) and user_answers[i] == q['correct_index']:
            score += 1
            
    pct = (score / total) * 100 if total > 0 else 0
    
    # Record quiz attempt
    cursor.execute('''
    INSERT INTO quiz_attempts (user_id, topic_id, score, total)
    VALUES (?, ?, ?, ?)
    ''', (user['id'], topic_id, score, total))
    db.commit()
    
    # Gamification rewards
    # 1. Base XP: +10 XP per correct answer
    xp_gain = score * 10
    
    # 2. Performance bonus: +50 XP bonus for score >= 80%
    passed = pct >= 80
    if passed:
        xp_gain += 50
        
    stats, leveled_up = update_user_stats(user['id'], xp_gain=xp_gain)
    
    # Check badges
    new_badges = []
    
    # Badge: Perfect Score
    if pct == 100:
        if award_badge(user['id'], 'Perfect Score 🎯'):
            new_badges.append('Perfect Score 🎯')
            
    # Badge: Quiz Whiz (complete 3 quizzes)
    cursor.execute('SELECT COUNT(*) as count FROM quiz_attempts WHERE user_id = ?', (user['id'],))
    attempts_count = cursor.fetchone()['count']
    if attempts_count >= 3:
        if award_badge(user['id'], 'Quiz Whiz 🧠'):
            new_badges.append('Quiz Whiz 🧠')
            
    # Custom feedback message
    if pct < 80:
        feedback = "Nice try 😄 ek baar revise kar lo! Watch the video or review your notes, and try again to unlock the next topic."
    else:
        feedback = "Great job 🎉 next topic is unlocked! You've mastered this concept."
        
    return jsonify({
        'score': score,
        'total': total,
        'percentage': pct,
        'passed': passed,
        'feedback': feedback,
        'xp_gain': xp_gain,
        'stats': stats,
        'leveled_up': leveled_up,
        'new_badges': new_badges
    })

# --- API: STUDY TRACKER (POMODORO) ---
@app.route('/api/tracker/session', methods=['POST'])
def log_focus_session():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    duration_seconds = data.get('duration', 0) # e.g. 1500 for 25 mins
    
    if duration_seconds < 60:
        return jsonify({'error': 'Focus session must be at least 1 minute.'}), 400
        
    hours = duration_seconds / 3600.0
    
    # +50 XP for a standard 25min Pomodoro, scale XP linearly based on time (approx 2 XP per minute)
    xp_gain = max(5, int((duration_seconds / 60.0) * 2.0))
    
    # Update user total hours & XP
    stats, leveled_up = update_user_stats(user['id'], xp_gain=xp_gain, hours_gain=hours)
    
    # Update/check streak
    new_streak, streak_updated = update_streak(user['id'])
    if stats:
        stats['streak'] = new_streak
        
    # Check badges
    new_badges = []
    
    # Badge: Focus Scholar (3 focus sessions)
    # We can count total study hours. If total_hours >= 1.0
    if stats and stats['total_hours'] >= 1.0:
        if award_badge(user['id'], 'Focus Scholar ⏱️'):
            new_badges.append('Focus Scholar ⏱️')
            
    return jsonify({
        'message': 'Focus session logged successfully!',
        'duration_seconds': duration_seconds,
        'xp_gain': xp_gain,
        'hours_gain': round(hours, 2),
        'stats': stats,
        'leveled_up': leveled_up,
        'streak_updated': streak_updated,
        'new_badges': new_badges
    })

# --- API: CLASS RESOURCES ---
@app.route('/api/resources/<class_name>/<subject_name>', methods=['GET'])
def get_resources(class_name, subject_name):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
    SELECT * FROM class_resources 
    WHERE class_name = ? AND subject_name = ? 
    ORDER BY chapter_no ASC
    ''', (class_name, subject_name))
    resources = [dict(row) for row in cursor.fetchall()]
    return jsonify(resources)

@app.route('/api/resources/<int:resource_id>', methods=['POST'])
def update_resource(resource_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    ncert_url = data.get('ncert_url', '').strip()
    notes_url = data.get('notes_url', '').strip()
    exemplar_url = data.get('exemplar_url', '').strip()
    book_pdf_url = data.get('book_pdf_url', '').strip()
    formula_sheet_url = data.get('formula_sheet_url', '').strip()
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
    UPDATE class_resources 
    SET ncert_url = ?, notes_url = ?, exemplar_url = ?, book_pdf_url = ?, formula_sheet_url = ? 
    WHERE id = ?
    ''', (ncert_url, notes_url, exemplar_url, book_pdf_url, formula_sheet_url, resource_id))
    db.commit()
    
    return jsonify({'message': 'Resource links updated successfully.'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
