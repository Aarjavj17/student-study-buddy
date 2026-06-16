from flask import Flask, jsonify, request, session, render_template, g
import sqlite3
import os
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from database import get_db_connection, DB_PATH, DATABASE_URL
from werkzeug.security import generate_password_hash, check_password_hash
import chatbot_nlp

app = Flask(__name__, template_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-student-buddy-key-2026-enjoy-studying')
app.permanent_session_lifetime = timedelta(days=7)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# Ensure database structure and content are synchronized on startup
from database import init_db
init_db()


# --- DATABASE LIFECYCLE ---
def get_db():
    if 'db' not in g:
        g.db = get_db_connection()
    else:
        # Verify connection is still alive (if PostgreSQL)
        if DATABASE_URL:
            try:
                cursor = g.db.real_conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
            except Exception:
                try:
                    g.db.close()
                except Exception:
                    pass
                g.db = get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

# --- HELPER FUNCTIONS ---
def get_current_user():
    if 'user_id' not in session:
        return None
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],))
    return cursor.fetchone()

def check_admin_permission():
    user = get_current_user()
    if not user or user['role'] not in ('admin', 'owner'):
        return False
    return True

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
    except Exception as e:
        classname = e.__class__.__name__
        if 'IntegrityError' in classname or 'UniqueViolation' in classname:
            # Already unlocked
            return False
        raise e

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

def save_file_to_db(filename, filepath):
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
            
        from database import get_db_connection
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("DELETE FROM uploaded_files WHERE filename = ?", (filename,))
        
        # Handle binary representation compatibly
        if DATABASE_URL:
            import psycopg2
            binary_data = psycopg2.Binary(data)
        else:
            binary_data = data
            
        cursor.execute("INSERT INTO uploaded_files (filename, file_data) VALUES (?, ?)", (filename, binary_data))
        db.commit()
        db.close()
        print(f"Successfully saved file {filename} to database.")
    except Exception as e:
        print(f"Error saving file {filename} to database: {e}")
        raise e

def pull_file_from_db(filename, local_path):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT file_data FROM uploaded_files WHERE filename = ?", (filename,))
        row = cursor.fetchone()
        if row and row['file_data']:
            data = row['file_data']
            if isinstance(data, memoryview):
                data = data.tobytes()
            elif hasattr(data, 'tobytes'):
                data = data.tobytes()
                
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(data)
            print(f"Successfully pulled and cached file {filename} from database.")
            return True
    except Exception as e:
        print(f"Error pulling file {filename} from database: {e}")
    return False

# --- PAGES ---
@app.route('/')
def index():
    return render_template('index.html')

# --- API: AUTHENTICATION ---
@app.route('/api/auth/send-email-otp', methods=['POST'])
def send_email_otp():
    data = request.json or {}
    email = data.get('email', '').strip()
    if '@' not in email or '.' not in email:
        return jsonify({'error': 'A valid email address is required.'}), 400
    
    import random
    otp = str(random.randint(100000, 999999))
    session['email_otp'] = otp
    session['email_otp_target'] = email
    
    print(f"[OTP DEBUG] Email OTP sent to {email}: {otp}")
    return jsonify({
        'message': 'OTP code sent to email.',
        'otp': otp
    })

@app.route('/api/auth/verify-email-otp', methods=['POST'])
def verify_email_otp():
    data = request.json or {}
    email = data.get('email', '').strip()
    otp = data.get('otp', '').strip()
    
    session_otp = session.get('email_otp')
    session_target = session.get('email_otp_target')
    
    if not session_otp or not session_target:
        return jsonify({'error': 'No OTP sent or OTP expired.'}), 400
        
    if email != session_target or otp != session_otp:
        return jsonify({'error': 'Invalid email verification code.'}), 400
        
    session['email_verified'] = True
    session['email_verified_target'] = email
    return jsonify({'message': 'Email verified successfully!'})

@app.route('/api/auth/send-mobile-otp', methods=['POST'])
def send_mobile_otp():
    data = request.json or {}
    mobile = data.get('mobile', '').strip()
    import re
    if not re.match(r'^\d{10}$', mobile):
        return jsonify({'error': 'A valid 10-digit mobile number is required.'}), 400
        
    import random
    otp = str(random.randint(100000, 999999))
    session['mobile_otp'] = otp
    session['mobile_otp_target'] = mobile
    
    print(f"[OTP DEBUG] Mobile OTP sent to {mobile}: {otp}")
    return jsonify({
        'message': 'OTP code sent to mobile number.',
        'otp': otp
    })

@app.route('/api/auth/verify-mobile-otp', methods=['POST'])
def verify_mobile_otp():
    data = request.json or {}
    mobile = data.get('mobile', '').strip()
    otp = data.get('otp', '').strip()
    
    session_otp = session.get('mobile_otp')
    session_target = session.get('mobile_otp_target')
    
    if not session_otp or not session_target:
        return jsonify({'error': 'No OTP sent or OTP expired.'}), 400
        
    if mobile != session_target or otp != session_otp:
        return jsonify({'error': 'Invalid mobile verification code.'}), 400
        
    session['mobile_verified'] = True
    session['mobile_verified_target'] = mobile
    return jsonify({'message': 'Mobile number verified successfully!'})

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    email = data.get('email', '').strip()
    mobile = data.get('mobile', '').strip()
    class_name = data.get('class_name', 'Class 9').strip()
    
    if len(username) < 3 or len(password) < 4:
        return jsonify({'error': 'Username (min 3 chars) and password (min 4 chars) required.'}), 400
        
    if not first_name or not last_name:
        return jsonify({'error': 'First name and last name are required.'}), 400
        
    if class_name not in ('Class 9', 'Class 10'):
        return jsonify({'error': 'Invalid class selection.'}), 400
        
    # Ensure mobile has been verified in session
    if not session.get('mobile_verified') or session.get('mobile_verified_target') != mobile:
        return jsonify({'error': 'Mobile number verification required.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    # Check if user already exists
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        return jsonify({'error': 'Username already taken.'}), 409
        
    hashed_pw = generate_password_hash(password)
    
    try:
        cursor.execute('''
        INSERT INTO users (username, password, xp, level, streak, total_hours, role, first_name, last_name, email, mobile, class_name)
        VALUES (?, ?, 0, 1, 0, 0.0, 'student', ?, ?, ?, ?, ?)
        ''', (
            username,
            hashed_pw,
            first_name,
            last_name,
            email,
            mobile,
            class_name
        ))
        db.commit()
        
        user_id = cursor.lastrowid
        
        # Clear verification sessions
        session.pop('email_otp', None)
        session.pop('email_otp_target', None)
        session.pop('email_verified', None)
        session.pop('email_verified_target', None)
        session.pop('mobile_otp', None)
        session.pop('mobile_otp_target', None)
        session.pop('mobile_verified', None)
        session.pop('mobile_verified_target', None)
        
        # Log user in
        session.permanent = True
        session['user_id'] = user_id
        
        # Award welcome badge
        award_badge(user_id, 'Ignition Flame 🔥')
        
        return jsonify({
            'message': 'Registration successful!',
            'user': {
                'id': user_id,
                'username': username,
                'role': 'student',
                'avatar': '',
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'mobile': mobile,
                'class_name': class_name
            }
        })
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    identifier = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not identifier or not password:
        return jsonify({'error': 'Username/Email/Mobile and Password are required.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT * FROM users 
        WHERE username = ? OR email = ? OR mobile = ?
    ''', (identifier, identifier, identifier))
    user = cursor.fetchone()
    
    if not user or not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid credentials or password.'}), 401
        
    session.permanent = True
    session['user_id'] = user['id']
    
    try:
        cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
        db.commit()
    except Exception:
        pass
    
    return jsonify({
        'message': 'Login successful!',
        'user': {
            'id': user['id'],
            'username': user['username'],
            'role': user['role'],
            'avatar': user['avatar'] or '',
            'first_name': user['first_name'] or '',
            'last_name': user['last_name'] or '',
            'email': user['email'] or '',
            'mobile': user['mobile'] or '',
            'class_name': user['class_name'] or 'Class 9'
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
            'total_hours': round(user['total_hours'], 2),
            'role': user['role'],
            'avatar': user['avatar'] or '',
            'first_name': user['first_name'] or '',
            'last_name': user['last_name'] or '',
            'email': user['email'] or '',
            'mobile': user['mobile'] or '',
            'class_name': user['class_name'] or 'Class 9'
        }
    })

@app.route('/api/auth/heartbeat', methods=['POST'])
def heartbeat():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
        db.commit()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/forgot-password/request', methods=['POST'])
def forgot_password_request():
    data = request.json or {}
    identifier = data.get('identifier', '').strip()
    
    if not identifier:
        return jsonify({'error': 'Username or mobile number is required.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT id, username, mobile FROM users 
        WHERE username = ? OR mobile = ? OR email = ?
    ''', (identifier, identifier, identifier))
    user = cursor.fetchone()
    
    if not user:
        return jsonify({'error': 'Account not found. Please verify your details.'}), 404
        
    mobile = user['mobile']
    if not mobile or len(mobile) < 10:
        return jsonify({'error': 'No registered mobile number found for this account.'}), 400
        
    import random
    otp = str(random.randint(100000, 999999))
    session['reset_user_id'] = user['id']
    session['reset_otp'] = otp
    session['reset_otp_verified'] = False
    
    masked_mobile = "******" + mobile[-4:]
    
    print(f"[OTP DEBUG] Password Reset OTP for @{user['username']} ({mobile}): {otp}")
    return jsonify({
        'success': True,
        'masked_mobile': masked_mobile,
        'username': user['username'],
        'otp': otp
    })

@app.route('/api/auth/forgot-password/verify', methods=['POST'])
def forgot_password_verify():
    data = request.json or {}
    otp = data.get('otp', '').strip()
    
    session_otp = session.get('reset_otp')
    if not session_otp:
        return jsonify({'error': 'Reset session expired or not requested.'}), 400
        
    if otp != session_otp:
        return jsonify({'error': 'Invalid verification code.'}), 400
        
    session['reset_otp_verified'] = True
    return jsonify({'success': True, 'message': 'OTP verified successfully.'})

@app.route('/api/auth/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    if not session.get('reset_otp_verified'):
        return jsonify({'error': 'Unauthorized. OTP verification required.'}), 403
        
    data = request.json or {}
    new_password = data.get('new_password', '').strip()
    
    if not new_password or len(new_password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters.'}), 400
        
    user_id = session.get('reset_user_id')
    if not user_id:
        return jsonify({'error': 'Reset session expired.'}), 400
        
    password_hash = generate_password_hash(new_password)
    
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET password = ? WHERE id = ?", (password_hash, user_id))
        db.commit()
        
        session.pop('reset_otp', None)
        session.pop('reset_user_id', None)
        session.pop('reset_otp_verified', None)
        
        return jsonify({'success': True, 'message': 'Password reset successfully!'})
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/admin/stats', methods=['GET'])
def get_admin_stats():
    if not check_admin_permission():
        return jsonify({'error': 'Unauthorized'}), 403
        
    db = get_db()
    cursor = db.cursor()
    
    try:
        # 1. Total Registered Users
        cursor.execute("SELECT COUNT(*) as count FROM users")
        total_users = cursor.fetchone()['count']
        
        # 2. Total Study Time (hours)
        cursor.execute("SELECT SUM(total_hours) as sum_hours FROM users")
        sum_hours = cursor.fetchone()['sum_hours'] or 0.0
        
        # 3. Total XP
        cursor.execute("SELECT SUM(xp) as sum_xp FROM users")
        sum_xp = cursor.fetchone()['sum_xp'] or 0
        
        # 4. Class counts
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE class_name = 'Class 9'")
        class9_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE class_name = 'Class 10'")
        class10_count = cursor.fetchone()['count']
        
        # 5. Online users count (active within 120 seconds)
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE last_active >= datetime('now', '-120 seconds')")
        online_users = cursor.fetchone()['count']
        
        # 6. List of all users
        cursor.execute("SELECT id, username, first_name, last_name, email, mobile, class_name, xp, level, streak, total_hours, last_active FROM users ORDER BY id ASC")
        users_rows = cursor.fetchall()
        
        import datetime
        now = datetime.datetime.utcnow()
        users_list = []
        for row in users_rows:
            is_online = False
            last_active_str = row['last_active']
            if last_active_str:
                try:
                    last_active_dt = datetime.datetime.strptime(last_active_str, '%Y-%m-%d %H:%M:%S')
                    diff = (now - last_active_dt).total_seconds()
                    if diff < 120:
                        is_online = True
                except Exception:
                    pass
                    
            users_list.append({
                'id': row['id'],
                'username': row['username'],
                'first_name': row['first_name'] or '',
                'last_name': row['last_name'] or '',
                'email': row['email'] or '',
                'mobile': row['mobile'] or '',
                'class_name': row['class_name'] or 'Class 9',
                'xp': row['xp'] or 0,
                'level': row['level'] or 1,
                'streak': row['streak'] or 0,
                'total_hours': row['total_hours'] or 0.0,
                'is_online': is_online
            })
            
        return jsonify({
            'total_users': total_users,
            'total_hours': round(sum_hours, 2),
            'total_xp': sum_xp,
            'class9_count': class9_count,
            'class10_count': class10_count,
            'online_users': online_users,
            'users': users_list
        })
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    if not check_admin_permission():
        return jsonify({'error': 'Unauthorized'}), 403
        
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Check if user exists and is not deleting themselves
        current_user = get_current_user()
        if current_user and current_user['id'] == user_id:
            return jsonify({'error': 'You cannot delete your own admin account!'}), 400
            
        # Delete from users and child tables
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        cursor.execute("DELETE FROM tasks WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM notes WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM quiz_attempts WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_badges WHERE user_id = ?", (user_id,))
        
        db.commit()
        return jsonify({'message': 'User deleted successfully!'})
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/auth/avatar', methods=['POST'])
def update_avatar():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    db = get_db()
    cursor = db.cursor()
    
    avatar_val = ""
    
    if 'file' in request.files:
        file = request.files['file']
        if file.filename != '':
            allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif'}
            _, ext = os.path.splitext(file.filename.lower())
            if ext not in allowed_extensions:
                return jsonify({'error': 'Unsupported file type. Only images (.png, .jpg, .jpeg, .gif) are allowed.'}), 400
                
            uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(uploads_dir, exist_ok=True)
            
            filename = f"avatar_{user['id']}{ext}"
            filepath = os.path.join(uploads_dir, filename)
            
            for existing_ext in allowed_extensions:
                old_file = os.path.join(uploads_dir, f"avatar_{user['id']}{existing_ext}")
                if os.path.exists(old_file):
                    try:
                        os.remove(old_file)
                    except Exception:
                        pass
                        
            file.save(filepath)
            save_file_to_db(filename, filepath)
            avatar_val = f"/static/uploads/{filename}"
            
    elif request.is_json:
        data = request.json or {}
        avatar_val = data.get('avatar', '').strip()
        
    if not avatar_val:
        avatar_val = request.form.get('avatar', '').strip()
        
    if not avatar_val:
        return jsonify({'error': 'No avatar image or emoji provided.'}), 400
        
    cursor.execute('UPDATE users SET avatar = ? WHERE id = ?', (avatar_val, user['id']))
    db.commit()
    
    return jsonify({
        'message': 'Avatar updated successfully!',
        'avatar': avatar_val
    })

@app.route('/api/auth/class', methods=['POST'])
def update_class():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized.'}), 401
        
    if user['role'] not in ('admin', 'owner'):
        return jsonify({'error': 'Forbidden. Only administrators can switch classes.'}), 403
        
    data = request.json or {}
    class_name = data.get('class_name', '').strip()
    
    if class_name not in ('Class 9', 'Class 10'):
        return jsonify({'error': 'Invalid class selection.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute('UPDATE users SET class_name = ? WHERE id = ?', (class_name, user['id']))
        db.commit()
        return jsonify({
            'message': 'Class updated successfully!',
            'class_name': class_name
        })
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/auth/change-password', methods=['POST'])
def change_password():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()
    
    if not current_password or not new_password or not confirm_password:
        return jsonify({'error': 'All password fields are required.'}), 400
        
    if new_password != confirm_password:
        return jsonify({'error': 'New password and confirm password do not match.'}), 400
        
    if len(new_password) < 4:
        return jsonify({'error': 'New password must be at least 4 characters.'}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    # Verify current password
    if not check_password_hash(user['password'], current_password):
        return jsonify({'error': 'Incorrect current password.'}), 401
        
    # Check if new password is same as current password
    if check_password_hash(user['password'], new_password):
        return jsonify({'error': 'New password cannot be the same as your current password.'}), 400
        
    hashed_pw = generate_password_hash(new_password)
    cursor.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_pw, user['id']))
    db.commit()
    
    return jsonify({'message': 'Password changed successfully!'})

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
        'badges': badges,
        'role': user['role'],
        'avatar': user['avatar'] or '',
        'first_name': user['first_name'] or '',
        'last_name': user['last_name'] or '',
        'email': user['email'] or '',
        'mobile': user['mobile'] or '',
        'class_name': user['class_name'] or 'Class 9'
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

# --- API: AI STUDY BUDDY CHATBOT ---
@app.route('/api/chat', methods=['POST'])
def handle_chat():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorised.'}), 401
        
    data = request.json or {}
    message = data.get('message', '').strip()
    history = data.get('history', [])
    
    if not message:
        return jsonify({'error': 'Message cannot be empty.'}), 400
        
    # 1. Search syllabus context from DB
    matched_context = chatbot_nlp.search_syllabus_context(message, DB_PATH)
    
    # 2. Check general intent
    general_reply = chatbot_nlp.get_general_intent_reply(message)
    
    api_key = os.environ.get('GEMINI_API_KEY')
    
    if api_key:
        try:
            import urllib.request
            import urllib.error
            import json
            
            contents = []
            for h in history:
                role = "user" if h.get('role') == 'user' else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": h.get('text', '')}]
                })
            
            contents.append({
                "role": "user",
                "parts": [{"text": message}]
            })
            
            system_instruction_text = (
                "You are 'Buddy', a friendly, encouraging, and highly intelligent AI study companion for Class 9 and 10 students. "
                "Your goal is to help them learn with no pressure, using positive reinforcement. "
                "Explain complex math, science, and history concepts in simple, easy-to-understand language. "
                "Use bullet points, formatting, and emojis to keep things fun. Encourage active recall, notes taking, "
                "and regular breaks. Be friendly, lighthearted, and always supportive."
            )
            
            if matched_context:
                ch = matched_context['chapter']
                notes = matched_context['notes']
                system_instruction_text += (
                    f"\n\n[RAG Context: The student is asking about Chapter {ch['chapter_no']}: '{ch['chapter_name']}' "
                    f"of '{ch['subject_name']}' (Class {ch['class_name']}). "
                )
                if notes:
                    system_instruction_text += f"The student's written notes for this chapter are: '{notes}'. "
                system_instruction_text += (
                    "Incorporate this context naturally into your explanation, and reference their specific chapter "
                    "or notes to help them study!]"
                )
            
            payload = {
                "contents": contents,
                "systemInstruction": {
                    "parts": [{"text": system_instruction_text}]
                },
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 800
                }
            }
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                candidates = res_data.get('candidates', [])
                if candidates:
                    content = candidates[0].get('content', {})
                    parts = content.get('parts', [])
                    if parts:
                        reply = parts[0].get('text', 'Oops, I got empty content back.')
                        return jsonify({'reply': reply, 'live': True})
                        
                return jsonify({'reply': "I received your message, but the model response was empty.", 'live': True})
                
        except urllib.error.HTTPError as he:
            error_msg = he.read().decode('utf-8')
            print(f"Gemini API HTTP Error: {error_msg}")
        except Exception as e:
            print(f"Gemini API Error: {str(e)}")
            
    # --- Local NLP Fallback (When API Key is missing or failed) ---
    if matched_context:
        reply = chatbot_nlp.generate_local_nlp_response(matched_context)
    elif general_reply:
        reply = general_reply
    else:
        reply = ("I'm here to support you! 🌟\n\n"
                 "I couldn't find a direct match in your syllabus for that query. "
                 "Try asking me about specific topics like **'Explain Netaji Ka Chashma'** or **'Science Cell'**!\n\n"
                 "Or type **'give me a study tip'** or **'tell me a joke'** to clear your mind!")
                 
    reply += "\n\n*(Note: Set the `GEMINI_API_KEY` environment variable and restart the server to enable live AI responses from Gemini!)*"
    return jsonify({'reply': reply, 'live': False})

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
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
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
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
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
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
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
        cr.id as resource_id, cr.resource_type, cr.file_path, cr.resource_title
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
            res_list = chapters_dict[ch_id]['resources'].setdefault(row['resource_type'], [])
            res_list.append({
                'id': row['resource_id'],
                'file_path': row['file_path'],
                'resource_title': row['resource_title'] or ''
            })
            
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
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
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
    
    import uuid
    unique_suffix = uuid.uuid4().hex[:8]
    filename = f"resource_{chapter_id}_{resource_type}_{unique_suffix}{ext}"
    filepath = os.path.join(uploads_dir, filename)
    file.save(filepath)
    save_file_to_db(filename, filepath)
    file_path = f"/static/uploads/{filename}"
    
    resource_title = request.form.get('resource_title', '').strip()
    if not resource_title:
        resource_title, _ = os.path.splitext(file.filename)
    
    db = get_db()
    cursor = db.cursor()
    
    # Confirm chapter exists
    cursor.execute('SELECT id FROM class_chapters WHERE id = ?', (chapter_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Chapter not found.'}), 404
        
    cursor.execute('''
    INSERT INTO chapter_resources (chapter_id, resource_type, file_path, resource_title)
    VALUES (?, ?, ?, ?)
    ''', (chapter_id, resource_type, file_path, resource_title))
    db.commit()
    
    return jsonify({
        'message': 'Resource uploaded successfully.',
        'file_path': file_path,
        'resource_title': resource_title
    })

@app.route('/api/chapters/<int:chapter_id>/resources/<resource_type>', methods=['DELETE'])
def delete_chapter_resource(chapter_id, resource_type):
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
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
                
    filename = os.path.basename(file_path)
    try:
        cursor.execute('DELETE FROM uploaded_files WHERE filename = ?', (filename,))
    except Exception:
        pass
    cursor.execute('DELETE FROM chapter_resources WHERE chapter_id = ? AND resource_type = ?', (chapter_id, resource_type))
    db.commit()
    
    return jsonify({'message': 'Resource deleted successfully.'})

@app.route('/api/resources/<int:resource_id>', methods=['DELETE'])
def delete_specific_resource(resource_id):
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT file_path FROM chapter_resources WHERE id = ?', (resource_id,))
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
                
    filename = os.path.basename(file_path)
    try:
        cursor.execute('DELETE FROM uploaded_files WHERE filename = ?', (filename,))
    except Exception:
        pass
    cursor.execute('DELETE FROM chapter_resources WHERE id = ?', (resource_id,))
    db.commit()
    
    return jsonify({'message': 'Resource deleted successfully.'})

# --- API: SAMPLE PAPERS ---
@app.route('/api/sample-papers/<class_name>/<subject_name>', methods=['GET'])
def get_sample_papers(class_name, subject_name):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
    SELECT id, class_name, subject_name, paper_title, file_path, created_at
    FROM sample_papers
    WHERE class_name = ? AND subject_name = ?
    ORDER BY created_at DESC
    ''', (class_name, subject_name))
    rows = cursor.fetchall()
    return jsonify([dict(row) for row in rows])

@app.route('/api/sample-papers/<class_name>/<subject_name>', methods=['POST'])
def upload_sample_paper(class_name, subject_name):
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in request.'}), 400
        
    file = request.files['file']
    paper_title = request.form.get('paper_title', '').strip()
    
    if file.filename == '':
        return jsonify({'error': 'No selected file.'}), 400
        
    if not paper_title:
        return jsonify({'error': 'Paper title is required.'}), 400
        
    allowed_extensions = {'.pdf', '.png', '.jpg', '.jpeg'}
    _, ext = os.path.splitext(file.filename.lower())
    if ext not in allowed_extensions:
        return jsonify({'error': 'Unsupported file type. Only PDF and images (.png, .jpg, .jpeg) are allowed.'}), 400
        
    uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    
    import uuid
    filename = f"sample_paper_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(uploads_dir, filename)
    file.save(filepath)
    save_file_to_db(filename, filepath)
    file_path = f"/static/uploads/{filename}"
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
    INSERT INTO sample_papers (class_name, subject_name, paper_title, file_path)
    VALUES (?, ?, ?, ?)
    ''', (class_name, subject_name, paper_title, file_path))
    db.commit()
    
    new_id = cursor.lastrowid
    return jsonify({
        'message': 'Sample paper uploaded successfully.',
        'sample_paper': {
            'id': new_id,
            'class_name': class_name,
            'subject_name': subject_name,
            'paper_title': paper_title,
            'file_path': file_path
        }
    })

@app.route('/api/sample-papers/<int:paper_id>', methods=['DELETE'])
def delete_sample_paper(paper_id):
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT file_path FROM sample_papers WHERE id = ?', (paper_id,))
    row = cursor.fetchone()
    if not row:
        return jsonify({'error': 'Sample paper not found.'}), 404
        
    file_path = row['file_path']
    if file_path.startswith('/static/'):
        disk_path = os.path.join(app.root_path, file_path.lstrip('/'))
        if os.path.exists(disk_path):
            try:
                os.remove(disk_path)
            except Exception as e:
                print(f"Warning: Could not remove file {disk_path}: {e}")
                
    filename = os.path.basename(file_path)
    try:
        cursor.execute('DELETE FROM uploaded_files WHERE filename = ?', (filename,))
    except Exception:
        pass
    cursor.execute('DELETE FROM sample_papers WHERE id = ?', (paper_id,))
    db.commit()
    
    return jsonify({'message': 'Sample paper deleted successfully.'})

@app.route('/api/chapters/<int:chapter_id>/videos', methods=['POST'])
def add_chapter_video(chapter_id):
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
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
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
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
    if not check_admin_permission():
        return jsonify({'error': 'Forbidden. Only administrators and owners can modify content.'}), 403
        
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT id FROM chapter_videos WHERE id = ?', (video_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Video not found.'}), 404
        
    cursor.execute('DELETE FROM chapter_videos WHERE id = ?', (video_id,))
    db.commit()
    
    return jsonify({'message': 'Video deleted successfully.'})

@app.route('/static/uploads/<path:filename>')
def serve_secure_upload(filename):
    from flask import send_from_directory
    # Allow avatar images without login
    if filename.startswith('avatar_'):
        local_path = os.path.join(app.root_path, 'static', 'uploads', filename)
        if not os.path.exists(local_path):
            pull_file_from_db(filename, local_path)
        return send_from_directory(os.path.join(app.root_path, 'static', 'uploads'), filename)
        
    local_path = os.path.join(app.root_path, 'static', 'uploads', filename)
    if not os.path.exists(local_path):
        pull_file_from_db(filename, local_path)
        
    response = send_from_directory(os.path.join(app.root_path, 'static', 'uploads'), filename)
    # Explicitly set headers for PDF to view inline in browser
    if filename.lower().endswith('.pdf'):
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'inline'
    return response

if __name__ == '__main__':
    import ssl_helper
    ssl_context = ssl_helper.get_ssl_context()

    # Auto-open browser tab after 1.2 seconds to ensure the server is listening
    def open_browser():
        import webbrowser
        import time
        time.sleep(1.2)
        url = "https://127.0.0.1:5000/" if ssl_context else "http://127.0.0.1:5000/"
        print(f"\n[Auto Open] Opening browser to: {url}")
        webbrowser.open(url)
        
    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    if ssl_context:
        print("[HTTPS] Starting secure Flask development server...")
        app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000, ssl_context=ssl_context)
    else:
        print("[HTTP Warning] Starting standard insecure Flask development server...")
        app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
