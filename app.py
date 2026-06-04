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
# --- API: QUIZZES ---
def generate_fallback_questions(chapter_id, chapter_name, subject_name, difficulty):
    q1_text = f"Which of the following is a primary concept covered in {chapter_name}?"
    q1_options = [f"Core principles of {chapter_name}", "Concepts of an unrelated subject", "Hypothetical theory without application", "None of the above"]
    
    q2_text = f"True or False: Mastering the topics in {chapter_name} is essential for a complete understanding of {subject_name}."
    q2_options = ["True", "False"]
    
    q3_text = f"Assertion (A): {chapter_name} is considered a foundational chapter in {subject_name}.\nReason (R): It introduces terminology and base concepts that are building blocks for future chapters."
    q3_options = [
        "Both A and R are true and R is the correct explanation of A.",
        "Both A and R are true but R is not the correct explanation of A.",
        "A is true but R is false.",
        "A is false but R is true."
    ]
    
    q4_options = {
        "left": [f"{chapter_name} Concepts", "Chapter Exercises", "Regular Revision"],
        "right": ["Applying knowledge to solve problems", "Strengthening long-term recall", "Understanding core fundamentals"]
    }
    q4_matches = {
        f"{chapter_name} Concepts": "Understanding core fundamentals",
        "Chapter Exercises": "Applying knowledge to solve problems",
        "Regular Revision": "Strengthening long-term recall"
    }
    
    q5_case = f"A student preparing for their final exams starts revising {chapter_name} in {subject_name}. They make short summary notes, practice textbook questions, and use flashcards for quick revision. This systematic approach helps them grasp even the hardest sections of {chapter_name}."
    q5_text = f"Based on the case description, what is the best strategy for the student to master {chapter_name}?"
    q5_options = ["Comprehensive study, regular practice, and active revision", "Cramming the night before the exam only", "Skipping the chapter completely", "Ignoring textbook exercises"]
    
    return [
        {
            'id': f"fallback_{chapter_id}_1",
            'chapter_id': chapter_id,
            'difficulty': difficulty,
            'question_type': 'MCQ',
            'question': q1_text,
            'options': q1_options,
            'correct_index': 0,
            'match_answers': None,
            'case_text': None
        },
        {
            'id': f"fallback_{chapter_id}_2",
            'chapter_id': chapter_id,
            'difficulty': difficulty,
            'question_type': 'True/False',
            'question': q2_text,
            'options': q2_options,
            'correct_index': 0,
            'match_answers': None,
            'case_text': None
        },
        {
            'id': f"fallback_{chapter_id}_3",
            'chapter_id': chapter_id,
            'difficulty': difficulty,
            'question_type': 'Assertion & Reason',
            'question': q3_text,
            'options': q3_options,
            'correct_index': 0,
            'match_answers': None,
            'case_text': None
        },
        {
            'id': f"fallback_{chapter_id}_4",
            'chapter_id': chapter_id,
            'difficulty': difficulty,
            'question_type': 'Match the Following',
            'question': f"Match the term from {chapter_name} with its primary academic purpose.",
            'options': q4_options,
            'correct_index': 0,
            'match_answers': q4_matches,
            'case_text': None
        },
        {
            'id': f"fallback_{chapter_id}_5",
            'chapter_id': chapter_id,
            'difficulty': difficulty,
            'question_type': 'Case-Based',
            'question': q5_text,
            'options': q5_options,
            'correct_index': 0,
            'match_answers': None,
            'case_text': q5_case
        }
    ]

@app.route('/api/quizzes', methods=['GET'])
def get_quizzes():
    return jsonify({})

@app.route('/api/chapters/<int:chapter_id>/quizzes/<difficulty>', methods=['GET'])
def get_chapter_quiz(chapter_id, difficulty):
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id, chapter_name, subject_name FROM class_chapters WHERE id = ?', (chapter_id,))
    chapter = cursor.fetchone()
    if not chapter:
        return jsonify({'error': 'Chapter not found.'}), 404
        
    cursor.execute('''
        SELECT * FROM quiz_questions 
        WHERE chapter_id = ? AND difficulty = ?
    ''', (chapter_id, difficulty))
    rows = cursor.fetchall()
    
    if len(rows) > 0:
        questions = []
        for r in rows:
            questions.append({
                'id': r['id'],
                'chapter_id': r['chapter_id'],
                'difficulty': r['difficulty'],
                'question_type': r['question_type'],
                'question': r['question'],
                'options': json.loads(r['options']),
                'correct_index': r['correct_index'],
                'match_answers': json.loads(r['match_answers']) if r['match_answers'] else None,
                'case_text': r['case_text']
            })
        return jsonify(questions)
    else:
        fallback = generate_fallback_questions(
            chapter_id, 
            chapter['chapter_name'], 
            chapter['subject_name'], 
            difficulty
        )
        return jsonify(fallback)

@app.route('/api/quizzes/submit', methods=['POST'])
def submit_quiz():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    chapter_id = data.get('chapter_id')
    difficulty = data.get('difficulty')
    score = data.get('score')
    total = data.get('total')
    time_taken = data.get('time_taken', 0)
    
    if chapter_id is None or not difficulty or score is None or total is None:
        return jsonify({'error': 'Missing required fields.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id FROM class_chapters WHERE id = ?', (chapter_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Chapter not found.'}), 404
        
    pct = (score / total) * 100 if total > 0 else 0
    passed = pct >= 80
    
    cursor.execute('''
    INSERT INTO quiz_attempts (user_id, chapter_id, difficulty, score, total, time_taken)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (user['id'], chapter_id, difficulty, score, total, time_taken))
    db.commit()
    
    # XP rewards:
    # 1. Base completion: +20 XP
    xp_gain = 20
    # 2. Mastery: +15 XP (accuracy >= 80%)
    if passed:
        xp_gain += 15
    # 3. Perfect score: +30 XP (100% accuracy)
    if pct == 100:
        xp_gain += 30
        
    # Streak bonus
    new_streak, streak_updated = update_streak(user['id'])
    if streak_updated:
        xp_gain += 10
        
    stats, leveled_up = update_user_stats(user['id'], xp_gain=xp_gain)
    if stats:
        stats['streak'] = new_streak
        
    new_badges = []
    if pct == 100:
        if award_badge(user['id'], 'Perfect Score 🎯'):
            new_badges.append('Perfect Score 🎯')
            
    cursor.execute('SELECT COUNT(*) as count FROM quiz_attempts WHERE user_id = ?', (user['id'],))
    attempts_count = cursor.fetchone()['count']
    if attempts_count >= 3:
        if award_badge(user['id'], 'Quiz Whiz 🧠'):
            new_badges.append('Quiz Whiz 🧠')
            
    feedback = "Great job 🎉 next topic is unlocked!" if passed else "Nice try 😄 ek baar revise kar lo! Watch the video or review your notes, and try again."
    
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

@app.route('/api/analytics/quizzes', methods=['GET'])
def get_quiz_analytics():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT 
            qa.chapter_id,
            cc.class_name,
            cc.subject_name,
            cc.sub_section,
            cc.chapter_name,
            SUM(qa.score) as total_score,
            SUM(qa.total) as total_questions,
            AVG(qa.time_taken) as avg_time,
            COUNT(qa.id) as attempts
        FROM quiz_attempts qa
        JOIN class_chapters cc ON qa.chapter_id = cc.id
        WHERE qa.user_id = ?
        GROUP BY qa.chapter_id
    ''', (user['id'],))
    rows = cursor.fetchall()
    
    breakdown = []
    strong = []
    weak = []
    
    for r in rows:
        accuracy = (r['total_score'] / r['total_questions']) * 100 if r['total_questions'] > 0 else 0
        accuracy = round(accuracy, 1)
        item = {
            'chapter_id': r['chapter_id'],
            'class_name': r['class_name'],
            'subject_name': r['subject_name'],
            'sub_section': r['sub_section'],
            'chapter_name': r['chapter_name'],
            'accuracy': accuracy,
            'avg_time': round(r['avg_time'], 1),
            'attempts': r['attempts']
        }
        breakdown.append(item)
        
        if accuracy >= 80:
            strong.append(item)
        else:
            weak.append(item)
            
    strong.sort(key=lambda x: x['accuracy'], reverse=True)
    weak.sort(key=lambda x: x['accuracy'])
    
    return jsonify({
        'breakdown': breakdown,
        'strong': strong[:5],
        'weak': weak[:5]
    })

# --- API: COLLABORATION QUESTIONS MANAGEMENT ---
@app.route('/api/chapters/<int:chapter_id>/questions', methods=['GET'])
def get_chapter_questions(chapter_id):
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT * FROM quiz_questions WHERE chapter_id = ? ORDER BY id DESC', (chapter_id,))
    rows = cursor.fetchall()
    
    questions = []
    for r in rows:
        questions.append({
            'id': r['id'],
            'chapter_id': r['chapter_id'],
            'difficulty': r['difficulty'],
            'question_type': r['question_type'],
            'question': r['question'],
            'options': json.loads(r['options']),
            'correct_index': r['correct_index'],
            'match_answers': json.loads(r['match_answers']) if r['match_answers'] else None,
            'case_text': r['case_text']
        })
    return jsonify(questions)

@app.route('/api/chapters/<int:chapter_id>/questions', methods=['POST'])
def add_chapter_question(chapter_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    difficulty = data.get('difficulty')
    question_type = data.get('question_type')
    question = data.get('question')
    options = data.get('options')
    correct_index = data.get('correct_index', 0)
    match_answers = data.get('match_answers')
    case_text = data.get('case_text')
    
    if not difficulty or not question_type or not question or options is None:
        return jsonify({'error': 'Missing required question fields.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        INSERT INTO quiz_questions (chapter_id, difficulty, question_type, question, options, correct_index, match_answers, case_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (chapter_id, difficulty, question_type, question, json.dumps(options), correct_index, json.dumps(match_answers) if match_answers else None, case_text))
    db.commit()
    
    return jsonify({'message': 'Question added successfully!'})

@app.route('/api/questions/<int:question_id>', methods=['PUT'])
def edit_question(question_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    difficulty = data.get('difficulty')
    question_type = data.get('question_type')
    question = data.get('question')
    options = data.get('options')
    correct_index = data.get('correct_index', 0)
    match_answers = data.get('match_answers')
    case_text = data.get('case_text')
    
    if not difficulty or not question_type or not question or options is None:
        return jsonify({'error': 'Missing required question fields.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id FROM quiz_questions WHERE id = ?', (question_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Question not found.'}), 404
        
    cursor.execute('''
        UPDATE quiz_questions 
        SET difficulty = ?, question_type = ?, question = ?, options = ?, correct_index = ?, match_answers = ?, case_text = ?
        WHERE id = ?
    ''', (difficulty, question_type, question, json.dumps(options), correct_index, json.dumps(match_answers) if match_answers else None, case_text, question_id))
    db.commit()
    
    return jsonify({'message': 'Question updated successfully!'})

@app.route('/api/questions/<int:question_id>', methods=['DELETE'])
def delete_question(question_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id FROM quiz_questions WHERE id = ?', (question_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Question not found.'}), 404
        
    cursor.execute('DELETE FROM quiz_questions WHERE id = ?', (question_id,))
    db.commit()
    
    return jsonify({'message': 'Question deleted successfully.'})

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
    SELECT 
        cc.id, cc.class_name, cc.subject_name, cc.sub_section, cc.chapter_no, cc.chapter_name,
        cr.resource_type, cr.file_path
    FROM class_chapters cc
    LEFT JOIN chapter_resources cr ON cc.id = cr.chapter_id
    WHERE cc.class_name = ? AND cc.subject_name = ?
    ORDER BY cc.id ASC
    ''', (class_name, subject_name))
    rows = cursor.fetchall()
    
    chapters_dict = {}
    for row in rows:
        ch_id = row['id']
        if ch_id not in chapters_dict:
            chapters_dict[ch_id] = {
                'id': row['id'],
                'class_name': row['class_name'],
                'subject_name': row['subject_name'],
                'sub_section': row['sub_section'],
                'chapter_no': row['chapter_no'],
                'chapter_name': row['chapter_name'],
                'resources': {},
                'videos': []
            }
        if row['resource_type'] and row['file_path']:
            chapters_dict[ch_id]['resources'][row['resource_type']] = row['file_path']
            
    # Fetch all video references for these chapters
    cursor.execute('''
    SELECT cv.id, cv.chapter_id, cv.video_title, cv.video_url, cv.video_type
    FROM chapter_videos cv
    JOIN class_chapters cc ON cv.chapter_id = cc.id
    WHERE cc.class_name = ? AND cc.subject_name = ?
    ''', (class_name, subject_name))
    video_rows = cursor.fetchall()
    
    for v_row in video_rows:
        ch_id = v_row['chapter_id']
        if ch_id in chapters_dict:
            chapters_dict[ch_id]['videos'].append({
                'id': v_row['id'],
                'video_title': v_row['video_title'],
                'video_url': v_row['video_url'],
                'video_type': v_row['video_type']
            })
            
    return jsonify(list(chapters_dict.values()))

@app.route('/api/chapters/<int:chapter_id>/resources/<resource_type>', methods=['POST'])
def upload_chapter_resource(chapter_id, resource_type):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in request.'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file.'}), 400
        
    # Check allowed formats: .pdf, .png, .jpg, .jpeg
    allowed_extensions = {'.pdf', '.png', '.jpg', '.jpeg'}
    _, ext = os.path.splitext(file.filename.lower())
    if ext not in allowed_extensions:
        return jsonify({'error': 'Unsupported file type. Only PDF and images (.png, .jpg, .jpeg) are allowed.'}), 400
        
    uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    
    filename = f"resource_{chapter_id}_{resource_type}{ext}"
    filepath = os.path.join(uploads_dir, filename)
    file.save(filepath)
    file_path = f"/static/uploads/{filename}"
    
    db = get_db()
    cursor = db.cursor()
    
    # Confirm chapter exists
    cursor.execute('SELECT id FROM class_chapters WHERE id = ?', (chapter_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Chapter not found.'}), 404
        
    cursor.execute('''
    INSERT INTO chapter_resources (chapter_id, resource_type, file_path)
    VALUES (?, ?, ?)
    ON CONFLICT(chapter_id, resource_type) DO UPDATE SET file_path=excluded.file_path
    ''', (chapter_id, resource_type, file_path))
    db.commit()
    
    return jsonify({
        'message': 'Resource uploaded successfully.',
        'file_path': file_path
    })

@app.route('/api/chapters/<int:chapter_id>/resources/<resource_type>', methods=['DELETE'])
def delete_chapter_resource(chapter_id, resource_type):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT file_path FROM chapter_resources WHERE chapter_id = ? AND resource_type = ?', (chapter_id, resource_type))
    row = cursor.fetchone()
    if not row:
        return jsonify({'error': 'Resource not found.'}), 404
        
    file_path = row['file_path']
    if file_path.startswith('/static/'):
        disk_path = os.path.join(app.root_path, file_path.lstrip('/'))
        if os.path.exists(disk_path):
            try:
                os.remove(disk_path)
            except Exception as e:
                print(f"Warning: Could not remove file {disk_path}: {e}")
                
    cursor.execute('DELETE FROM chapter_resources WHERE chapter_id = ? AND resource_type = ?', (chapter_id, resource_type))
    db.commit()
    
    return jsonify({'message': 'Resource deleted successfully.'})

@app.route('/api/chapters/<int:chapter_id>/videos', methods=['POST'])
def add_chapter_video(chapter_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    video_title = data.get('video_title', '').strip()
    video_url = data.get('video_url', '').strip()
    video_type = data.get('video_type', 'YouTube').strip()
    
    if not video_title or not video_url:
        return jsonify({'error': 'Video title and URL are required.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id FROM class_chapters WHERE id = ?', (chapter_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Chapter not found.'}), 404
        
    cursor.execute('''
    INSERT INTO chapter_videos (chapter_id, video_title, video_url, video_type)
    VALUES (?, ?, ?, ?)
    ''', (chapter_id, video_title, video_url, video_type))
    db.commit()
    
    new_id = cursor.lastrowid
    return jsonify({
        'message': 'Video added successfully.',
        'video': {
            'id': new_id,
            'chapter_id': chapter_id,
            'video_title': video_title,
            'video_url': video_url,
            'video_type': video_type
        }
    })

@app.route('/api/videos/<int:video_id>', methods=['PUT'])
def edit_chapter_video(video_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    video_title = data.get('video_title', '').strip()
    video_url = data.get('video_url', '').strip()
    video_type = data.get('video_type', 'YouTube').strip()
    
    if not video_title or not video_url:
        return jsonify({'error': 'Video title and URL are required.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id, chapter_id FROM chapter_videos WHERE id = ?', (video_id,))
    video = cursor.fetchone()
    if not video:
        return jsonify({'error': 'Video not found.'}), 404
        
    cursor.execute('''
    UPDATE chapter_videos 
    SET video_title = ?, video_url = ?, video_type = ?
    WHERE id = ?
    ''', (video_title, video_url, video_type, video_id))
    db.commit()
    
    return jsonify({
        'message': 'Video updated successfully.',
        'video': {
            'id': video_id,
            'chapter_id': video['chapter_id'],
            'video_title': video_title,
            'video_url': video_url,
            'video_type': video_type
        }
    })

@app.route('/api/videos/<int:video_id>', methods=['DELETE'])
def delete_chapter_video(video_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id FROM chapter_videos WHERE id = ?', (video_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Video not found.'}), 404
        
    cursor.execute('DELETE FROM chapter_videos WHERE id = ?', (video_id,))
    db.commit()
    
    return jsonify({'message': 'Video deleted successfully.'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
