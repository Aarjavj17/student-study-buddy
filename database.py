import sqlite3
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL') or 'postgresql://neondb_owner:npg_NU0pyKsj7rqh@ep-withered-unit-ajm7krwi-pooler.c-3.us-east-2.aws.neon.tech/neondb?channel_binding=require&sslmode=require'

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    
    class PostgreSQLCursorWrapper:
        def __init__(self, real_cursor):
            self.real_cursor = real_cursor
            self._lastrowid = None

        def execute(self, query, params=None):
            # Translate '?' placeholder to '%s'
            query_translated = query.replace('?', '%s')

            # Translate AUTOINCREMENT keyword for tables creation (specifically during init_db)
            query_translated = query_translated.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
            query_translated = query_translated.replace('REAL', 'DOUBLE PRECISION')
            query_translated = query_translated.replace('BLOB', 'BYTEA')
            
            # Translate sqlite_master table check to PostgreSQL equivalent
            if 'sqlite_master' in query:
                query_translated = """
                    SELECT tablename as name 
                    FROM pg_catalog.pg_tables 
                    WHERE schemaname = 'public' AND tablename = 'class_resources'
                """

            # Translate SQLite migration queries (e.g. PRAGMA table_info)
            if 'PRAGMA table_info(users)' in query or 'PRAGMA table_info("users")' in query or 'PRAGMA table_info' in query:
                # Mock output format of sqlite3 PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
                query_translated = """
                    SELECT 0 as cid, column_name as name, data_type as type, 
                           case when is_nullable = 'NO' then 1 else 0 end as notnull, 
                           column_default as dflt_value, 0 as pk
                    FROM information_schema.columns
                    WHERE table_name = 'users'
                """

            # Handle INSERT OR REPLACE upserts for SQLite compatibility
            if 'INSERT OR REPLACE INTO videos' in query:
                query_translated = """
                    INSERT INTO videos (id, title, subject, youtube_id, description)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        subject = EXCLUDED.subject,
                        youtube_id = EXCLUDED.youtube_id,
                        description = EXCLUDED.description
                """
            elif 'INSERT OR REPLACE' in query:
                query_translated = query_translated.replace('INSERT OR REPLACE', 'INSERT')

            # Handle lastrowid capture by appending RETURNING id to INSERTs
            is_insert = query_translated.strip().upper().startswith('INSERT')
            has_id_col = 'uploaded_files' not in query_translated.lower()
            if is_insert and has_id_col and 'RETURNING' not in query_translated.upper():
                query_translated = query_translated.rstrip('; \t\n') + ' RETURNING id'
                if params is not None:
                    self.real_cursor.execute(query_translated, params)
                else:
                    self.real_cursor.execute(query_translated)
                try:
                    row = self.real_cursor.fetchone()
                    if row:
                        self._lastrowid = row[0]
                except Exception:
                    pass
            else:
                if params is not None:
                    self.real_cursor.execute(query_translated, params)
                else:
                    self.real_cursor.execute(query_translated)

        def fetchone(self):
            return self.real_cursor.fetchone()

        def fetchall(self):
            return self.real_cursor.fetchall()

        @property
        def lastrowid(self):
            return self._lastrowid

    class PostgreSQLConnectionWrapper:
        def __init__(self, real_conn):
            self.real_conn = real_conn
            self.row_factory = None

        def cursor(self):
            # DictCursor provides dictionary-like access matching sqlite3.Row
            cursor = self.real_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            return PostgreSQLCursorWrapper(cursor)

        def commit(self):
            self.real_conn.commit()

        def rollback(self):
            self.real_conn.rollback()

        def close(self):
            self.real_conn.close()

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL Mode
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        
        import time
        max_retries = 10
        for i in range(max_retries):
            try:
                conn = psycopg2.connect(url)
                return PostgreSQLConnectionWrapper(conn)
            except Exception as e:
                print(f"Database connection attempt {i+1} failed: {e}")
                if i < max_retries - 1:
                    time.sleep(3)
                else:
                    raise e
    else:
        # SQLite Mode
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        streak INTEGER DEFAULT 0,
        last_study_date TEXT,
        total_hours REAL DEFAULT 0.0,
        role TEXT DEFAULT 'student',
        avatar TEXT DEFAULT '',
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT '',
        email TEXT DEFAULT '',
        mobile TEXT DEFAULT '',
        class_name TEXT DEFAULT 'Class 9'
    )
    ''')
    
    # Check if role & avatar columns exist (migration check)
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'role' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'student'")
        conn.commit()
    if 'avatar' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''")
        conn.commit()
    if 'first_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''")
        conn.commit()
    if 'last_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT DEFAULT ''")
        conn.commit()
    if 'email' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
        conn.commit()
    if 'mobile' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN mobile TEXT DEFAULT ''")
        conn.commit()
    if 'class_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN class_name TEXT DEFAULT 'Class 9'")
        conn.commit()
    if 'last_active' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP")
        conn.commit()

    # Create class_chapters first for Foreign Key reference order in PostgreSQL
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS class_chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_name TEXT NOT NULL,
        subject_name TEXT NOT NULL,
        sub_section TEXT DEFAULT '',
        chapter_no INTEGER NOT NULL,
        chapter_name TEXT NOT NULL
    )
    ''')

    # 2. Tasks Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        subject TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')
    
    # 3. Notes Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        topic_id TEXT NOT NULL,
        content TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, topic_id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')
    
    # 4. Quiz Attempts Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quiz_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        chapter_id INTEGER NOT NULL,
        difficulty TEXT NOT NULL,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        time_taken INTEGER NOT NULL, -- duration in seconds
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(chapter_id) REFERENCES class_chapters(id) ON DELETE CASCADE
    )
    ''')
    
    # 5. User Badges Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        badge_name TEXT NOT NULL,
        unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, badge_name),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')
    
    # 6. Videos Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        subject TEXT NOT NULL,
        youtube_id TEXT NOT NULL,
        description TEXT NOT NULL
    )
    ''')
    
    # 7. Quiz Questions Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quiz_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        difficulty TEXT NOT NULL,
        question_type TEXT NOT NULL,
        question TEXT NOT NULL,
        options TEXT NOT NULL,          -- JSON string (list of options or match object)
        correct_index INTEGER DEFAULT 0,
        match_answers TEXT,             -- JSON string mapping (for Match the Following)
        case_text TEXT,                 -- For Case-Based questions
        FOREIGN KEY(chapter_id) REFERENCES class_chapters(id) ON DELETE CASCADE
    )
    ''')
    
    # Clean up obsolete class_resources table if it exists
    cursor.execute("DROP TABLE IF EXISTS class_resources")
    conn.commit()
    
    # --- SEED DEFAULT DATA ---
    
    # Seed Videos
    videos_data = [
        ('maths_algebra', 'Introduction to Algebra Basics', 'Maths', 'NybHckSEQBI', 'Learn the fundamental rules of Algebra, variables, and solving simple equations with Math Antics.'),
        ('science_gravity', 'What is Gravity & How It Works', 'Science', 'yjSNU6YC1s0', 'A beginner friendly animation explaining gravity, acceleration on earth, and how mass attracts mass.'),
        ('science_reactions', 'Types of Chemical Reactions', 'Science', 'T4K86v_yQNg', 'Understand synthesis, decomposition, single displacement, double displacement, and combustion reactions.')
    ]
    
    for v_id, title, sub, yt_id, desc in videos_data:
        cursor.execute('''
        INSERT OR REPLACE INTO videos (id, title, subject, youtube_id, description)
        VALUES (?, ?, ?, ?, ?)
        ''', (v_id, title, sub, yt_id, desc))
    conn.commit()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chapter_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        resource_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        resource_title TEXT DEFAULT '',
        FOREIGN KEY(chapter_id) REFERENCES class_chapters(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chapter_videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        video_title TEXT NOT NULL,
        video_url TEXT NOT NULL,
        video_type TEXT DEFAULT 'YouTube',
        FOREIGN KEY(chapter_id) REFERENCES class_chapters(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sample_papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_name TEXT NOT NULL,
        subject_name TEXT NOT NULL,
        paper_title TEXT NOT NULL,
        file_path TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS uploaded_files (
        filename TEXT PRIMARY KEY,
        file_data BLOB
    )
    ''')
    conn.commit()
    
    # --- SEED DEFAULT DATA ---
    
    # Seed default admin user
    from werkzeug.security import generate_password_hash
    admin_hash = generate_password_hash('admin123')
    cursor.execute("SELECT id, password FROM users WHERE username = 'admin'")
    row = cursor.fetchone()
    if not row:
        cursor.execute('''
            INSERT INTO users (username, password, xp, level, streak, total_hours, role, email, mobile)
            VALUES ('admin', ?, 0, 1, 0, 0.0, 'admin', 'admin@gmail.com', '9999999999')
        ''', (admin_hash,))
    else:
        current_hash = row['password']
        if not current_hash.startswith('pbkdf2:') and not current_hash.startswith('scrypt:'):
            cursor.execute("UPDATE users SET password = ? WHERE id = ?", (admin_hash, row['id']))
        cursor.execute("UPDATE users SET email = 'admin@gmail.com', mobile = '9999999999' WHERE username = 'admin'")

    # Seed Videos
    videos_data = [
        ('maths_algebra', 'Introduction to Algebra Basics', 'Maths', 'NybHckSEQBI', 'Learn the fundamental rules of Algebra, variables, and solving simple equations with Math Antics.'),
        ('science_gravity', 'What is Gravity & How It Works', 'Science', 'yjSNU6YC1s0', 'A beginner friendly animation explaining gravity, acceleration on earth, and how mass attracts mass.'),
        ('science_reactions', 'Types of Chemical Reactions', 'Science', 'T4K86v_yQNg', 'Understand synthesis, decomposition, single displacement, double displacement, and combustion reactions.')
    ]
    
    for v_id, title, sub, yt_id, desc in videos_data:
        cursor.execute('''
        INSERT OR REPLACE INTO videos (id, title, subject, youtube_id, description)
        VALUES (?, ?, ?, ?, ?)
        ''', (v_id, title, sub, yt_id, desc))
        

        
    # Seed Complete Class 9 and Class 10 Syllabus Chapters
    class_chapters_data = [
        # === CLASS 9 ===
        # Mathematics
        ('Class 9', 'Mathematics', '', 1, 'Number Systems'),
        ('Class 9', 'Mathematics', '', 2, 'Polynomials'),
        ('Class 9', 'Mathematics', '', 3, 'Coordinate Geometry'),
        ('Class 9', 'Mathematics', '', 4, 'Linear Equations in Two Variables'),
        ('Class 9', 'Mathematics', '', 5, "Introduction to Euclid's Geometry"),
        ('Class 9', 'Mathematics', '', 6, 'Lines and Angles'),
        ('Class 9', 'Mathematics', '', 7, 'Triangles'),
        ('Class 9', 'Mathematics', '', 8, 'Quadrilaterals'),
        ('Class 9', 'Mathematics', '', 9, 'Areas of Parallelograms and Triangles'),
        ('Class 9', 'Mathematics', '', 10, 'Circles'),
        ('Class 9', 'Mathematics', '', 11, 'Constructions'),
        ('Class 9', 'Mathematics', '', 12, "Heron's Formula"),
        ('Class 9', 'Mathematics', '', 13, 'Surface Areas and Volumes'),
        ('Class 9', 'Mathematics', '', 14, 'Statistics'),
        ('Class 9', 'Mathematics', '', 15, 'Probability'),
        
        # Science - Biology
        ('Class 9', 'Science', 'Biology', 1, 'Cell'),
        ('Class 9', 'Science', 'Biology', 2, 'Tissues'),
        ('Class 9', 'Science', 'Biology', 3, 'Reproduction'),
        ('Class 9', 'Science', 'Biology', 4, 'Diversity'),
        # Science - Chemistry
        ('Class 9', 'Science', 'Chemistry', 5, 'Exploring Mixtures and Their Separation'),
        ('Class 9', 'Science', 'Chemistry', 6, 'Structure of an Atom'),
        ('Class 9', 'Science', 'Chemistry', 7, 'Atoms and Molecules'),
        # Science - Physics
        ('Class 9', 'Science', 'Physics', 8, 'Motion'),
        ('Class 9', 'Science', 'Physics', 9, 'Force and Laws of Motion'),
        ('Class 9', 'Science', 'Physics', 10, 'Work, Energy and Simple Machines'),
        ('Class 9', 'Science', 'Physics', 11, 'Sound'),
        # Science - Earth Science
        ('Class 9', 'Science', 'Earth Science', 12, 'Earth as a System: Energy, Matter and Life'),
        
        # Social Science - History
        ('Class 9', 'Social Science', 'History', 1, 'The French Revolution'),
        ('Class 9', 'Social Science', 'History', 2, 'Socialism in Europe and the Russian Revolution'),
        ('Class 9', 'Social Science', 'History', 3, 'Nazism and the Rise of Hitler'),
        ('Class 9', 'Social Science', 'History', 4, 'Forest Society and Colonialism'),
        ('Class 9', 'Social Science', 'History', 5, 'Pastoralists in the Modern World'),
        # Social Science - Geography
        ('Class 9', 'Social Science', 'Geography', 6, 'India – Size and Location'),
        ('Class 9', 'Social Science', 'Geography', 7, 'Physical Features of India'),
        ('Class 9', 'Social Science', 'Geography', 8, 'Drainage'),
        ('Class 9', 'Social Science', 'Geography', 9, 'Climate'),
        ('Class 9', 'Social Science', 'Geography', 10, 'Natural Vegetation and Wildlife'),
        ('Class 9', 'Social Science', 'Geography', 11, 'Population'),
        # Social Science - Political Science
        ('Class 9', 'Social Science', 'Political Science', 12, 'What is Democracy? Why Democracy?'),
        ('Class 9', 'Social Science', 'Political Science', 13, 'Constitutional Design'),
        ('Class 9', 'Social Science', 'Political Science', 14, 'Electoral Politics'),
        ('Class 9', 'Social Science', 'Political Science', 15, 'Working of Institutions'),
        ('Class 9', 'Social Science', 'Political Science', 16, 'Democratic Rights'),
        # Social Science - Economics
        ('Class 9', 'Social Science', 'Economics', 17, 'The Story of Village Palampur'),
        ('Class 9', 'Social Science', 'Economics', 18, 'People as Resource'),
        ('Class 9', 'Social Science', 'Economics', 19, 'Poverty as a Challenge'),
        ('Class 9', 'Social Science', 'Economics', 20, 'Food Security in India'),
        
        # English - Beehive
        ('Class 9', 'English', 'Beehive', 1, 'The Fun They Had'),
        ('Class 9', 'English', 'Beehive', 2, 'The Sound of Music'),
        ('Class 9', 'English', 'Beehive', 3, 'The Little Girl'),
        ('Class 9', 'English', 'Beehive', 4, 'A Truly Beautiful Mind'),
        ('Class 9', 'English', 'Beehive', 5, 'The Snake and the Mirror'),
        ('Class 9', 'English', 'Beehive', 6, 'My Childhood'),
        ('Class 9', 'English', 'Beehive', 7, 'Reach for the Top'),
        ('Class 9', 'English', 'Beehive', 8, 'Kathmandu'),
        ('Class 9', 'English', 'Beehive', 9, 'If I Were You'),
        # English - Poetry
        ('Class 9', 'English', 'Poetry', 10, 'The Road Not Taken'),
        ('Class 9', 'English', 'Poetry', 11, 'Wind'),
        ('Class 9', 'English', 'Poetry', 12, 'Rain on the Roof'),
        ('Class 9', 'English', 'Poetry', 13, 'The Lake Isle of Innisfree'),
        ('Class 9', 'English', 'Poetry', 14, 'A Legend of the Northland'),
        ('Class 9', 'English', 'Poetry', 15, 'No Men Are Foreign'),
        ('Class 9', 'English', 'Poetry', 16, 'On Killing a Tree'),
        ('Class 9', 'English', 'Poetry', 17, 'A Slumber Did My Spirit Seal'),
        # English - Moments
        ('Class 9', 'English', 'Moments', 18, 'The Lost Child'),
        ('Class 9', 'English', 'Moments', 19, 'The Adventures of Toto'),
        ('Class 9', 'English', 'Moments', 20, 'Iswaran the Storyteller'),
        ('Class 9', 'English', 'Moments', 21, 'In the Kingdom of Fools'),
        ('Class 9', 'English', 'Moments', 22, 'The Happy Prince'),
        ('Class 9', 'English', 'Moments', 23, 'The Last Leaf'),
        ('Class 9', 'English', 'Moments', 24, 'A House is not a Home'),
        ('Class 9', 'English', 'Moments', 25, 'The Beggar'),
        
        # Hindi - Gadya
        ('Class 9', 'Hindi', 'Gadya', 1, 'Do Bailon Ki Katha'),
        ('Class 9', 'Hindi', 'Gadya', 2, 'Kya Likhun?'),
        ('Class 9', 'Hindi', 'Gadya', 3, 'Samvadhin'),
        ('Class 9', 'Hindi', 'Gadya', 4, 'Aisi Bhi Batein Hoti Hain'),
        ('Class 9', 'Hindi', 'Gadya', 5, 'Aakhiri Chattan Tak'),
        ('Class 9', 'Hindi', 'Gadya', 6, 'Reedh Ki Haddi'),
        ('Class 9', 'Hindi', 'Gadya', 7, 'Main Aur Mera Desh'),
        # Hindi - Kavya
        ('Class 9', 'Hindi', 'Kavya', 8, 'Raidas Ke Pad'),
        ('Class 9', 'Hindi', 'Kavya', 9, 'Ram-Parshuram-Lakshman Samvad'),
        ('Class 9', 'Hindi', 'Kavya', 10, 'Bharati, Jay, Vijaykare!'),
        ('Class 9', 'Hindi', 'Kavya', 11, 'Jhansi Ki Rani'),
        ('Class 9', 'Hindi', 'Kavya', 12, 'Ghar Ki Yaad'),
        
        # Sanskrit - Shemushi
        ('Class 9', 'Sanskrit', 'Shemushi', 1, 'Bhartiwasantgeeti (भारतीवसन्तगीतिः)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 2, 'Swarnakakah (स्वर्णकाकः)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 3, 'Godohanam (गोदोहनम्)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 4, 'Suktimauktikam (सूक्तिमौक्तिकम्)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 5, 'Bhranto Balah (भ्रान्तो बालः)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 6, 'Lauhatula (लौहतुला)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 7, 'Siktasetuh (सिकतासेतुः)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 8, 'Jatayoh Shauryam (जटायोः शौर्यम्)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 9, 'Paryavaranam (पर्यावरणम्)'),
        ('Class 9', 'Sanskrit', 'Shemushi', 10, 'Vangmanahpranaswarupam (वाङ्मनःप्राणस्वरूपम्)'),
        
        # === CLASS 10 ===
        # Mathematics
        ('Class 10', 'Mathematics', '', 1, 'Real Numbers'),
        ('Class 10', 'Mathematics', '', 2, 'Polynomials'),
        ('Class 10', 'Mathematics', '', 3, 'Pair of Linear Equations in Two Variables'),
        ('Class 10', 'Mathematics', '', 4, 'Quadratic Equations'),
        ('Class 10', 'Mathematics', '', 5, 'Arithmetic Progressions'),
        ('Class 10', 'Mathematics', '', 6, 'Triangles'),
        ('Class 10', 'Mathematics', '', 7, 'Coordinate Geometry'),
        ('Class 10', 'Mathematics', '', 8, 'Introduction to Trigonometry'),
        ('Class 10', 'Mathematics', '', 9, 'Some Applications of Trigonometry'),
        ('Class 10', 'Mathematics', '', 10, 'Circles'),
        ('Class 10', 'Mathematics', '', 11, 'Areas Related to Circles'),
        ('Class 10', 'Mathematics', '', 12, 'Surface Areas and Volumes'),
        ('Class 10', 'Mathematics', '', 13, 'Statistics'),
        ('Class 10', 'Mathematics', '', 14, 'Probability'),
        
        # Science - Chemistry
        ('Class 10', 'Science', 'Chemistry', 1, 'Chemical Reactions and Equations'),
        ('Class 10', 'Science', 'Chemistry', 2, 'Acids, Bases and Salts'),
        ('Class 10', 'Science', 'Chemistry', 3, 'Metals and Non-metals'),
        ('Class 10', 'Science', 'Chemistry', 4, 'Carbon and Its Compounds'),
        # Science - Biology
        ('Class 10', 'Science', 'Biology', 5, 'Life Processes'),
        ('Class 10', 'Science', 'Biology', 6, 'Control and Coordination'),
        ('Class 10', 'Science', 'Biology', 7, 'How do Organisms Reproduce?'),
        ('Class 10', 'Science', 'Biology', 8, 'Heredity'),
        # Science - Physics
        ('Class 10', 'Science', 'Physics', 9, 'Light – Reflection and Refraction'),
        ('Class 10', 'Science', 'Physics', 10, 'The Human Eye and the Colourful World'),
        ('Class 10', 'Science', 'Physics', 11, 'Electricity'),
        ('Class 10', 'Science', 'Physics', 12, 'Magnetic Effects of Electric Current'),
        # Science - Environment
        ('Class 10', 'Science', 'Environment', 13, 'Our Environment'),
        
        # Social Science - History
        ('Class 10', 'Social Science', 'History', 1, 'The Rise of Nationalism in Europe'),
        ('Class 10', 'Social Science', 'History', 2, 'Nationalism in India'),
        ('Class 10', 'Social Science', 'History', 3, 'The Making of a Global World'),
        ('Class 10', 'Social Science', 'History', 4, 'The Age of Industrialisation'),
        ('Class 10', 'Social Science', 'History', 5, 'Print Culture and the Modern World'),
        # Social Science - Geography
        ('Class 10', 'Social Science', 'Geography', 6, 'Resources and Development'),
        ('Class 10', 'Social Science', 'Geography', 7, 'Forest and Wildlife Resources'),
        ('Class 10', 'Social Science', 'Geography', 8, 'Water Resources'),
        ('Class 10', 'Social Science', 'Geography', 9, 'Agriculture'),
        ('Class 10', 'Social Science', 'Geography', 10, 'Minerals and Energy Resources'),
        ('Class 10', 'Social Science', 'Geography', 11, 'Manufacturing Industries'),
        ('Class 10', 'Social Science', 'Geography', 12, 'Lifelines of National Economy'),
        # Social Science - Political Science
        ('Class 10', 'Social Science', 'Political Science', 13, 'Power Sharing'),
        ('Class 10', 'Social Science', 'Political Science', 14, 'Federalism'),
        ('Class 10', 'Social Science', 'Political Science', 15, 'Gender, Religion and Caste'),
        ('Class 10', 'Social Science', 'Political Science', 16, 'Political Parties'),
        ('Class 10', 'Social Science', 'Political Science', 17, 'Outcomes of Democracy'),
        # Social Science - Economics
        ('Class 10', 'Social Science', 'Economics', 18, 'Development'),
        ('Class 10', 'Social Science', 'Economics', 19, 'Sectors of the Indian Economy'),
        ('Class 10', 'Social Science', 'Economics', 20, 'Money and Credit'),
        ('Class 10', 'Social Science', 'Economics', 21, 'Globalisation and the Indian Economy'),
        ('Class 10', 'Social Science', 'Economics', 22, 'Consumer Rights'),
        
        # English - First Flight
        ('Class 10', 'English', 'First Flight', 1, 'A Letter to God'),
        ('Class 10', 'English', 'First Flight', 2, 'Nelson Mandela: Long Walk to Freedom'),
        ('Class 10', 'English', 'First Flight', 3, 'Two Stories about Flying'),
        ('Class 10', 'English', 'First Flight', 4, 'From the Diary of Anne Frank'),
        ('Class 10', 'English', 'First Flight', 5, 'Glimpses of India'),
        ('Class 10', 'English', 'First Flight', 6, 'Madam Rides the Bus'),
        ('Class 10', 'English', 'First Flight', 7, 'The Sermon at Benares'),
        ('Class 10', 'English', 'First Flight', 8, 'The Proposal'),
        # English - Poetry
        ('Class 10', 'English', 'Poetry', 9, 'Dust of Snow'),
        ('Class 10', 'English', 'Poetry', 10, 'Fire and Ice'),
        ('Class 10', 'English', 'Poetry', 11, 'A Tiger in the Zoo'),
        ('Class 10', 'English', 'Poetry', 12, 'How to Tell Wild Animals'),
        ('Class 10', 'English', 'Poetry', 13, 'The Ball Poem'),
        ('Class 10', 'English', 'Poetry', 14, 'Amanda!'),
        ('Class 10', 'English', 'Poetry', 15, 'Animals'),
        ('Class 10', 'English', 'Poetry', 16, 'The Trees'),
        ('Class 10', 'English', 'Poetry', 17, 'Fog'),
        ('Class 10', 'English', 'Poetry', 18, 'The Tale of Custard the Dragon'),
        ('Class 10', 'English', 'Poetry', 19, 'For Anne Gregory'),
        # English - Footprints Without Feet
        ('Class 10', 'English', 'Footprints Without Feet', 20, 'A Triumph of Surgery'),
        ('Class 10', 'English', 'Footprints Without Feet', 21, "The Thief's Story"),
        ('Class 10', 'English', 'Footprints Without Feet', 22, 'The Midnight Visitor'),
        ('Class 10', 'English', 'Footprints Without Feet', 23, 'A Question of Trust'),
        ('Class 10', 'English', 'Footprints Without Feet', 24, 'Footprints Without Feet'),
        ('Class 10', 'English', 'Footprints Without Feet', 25, 'The Making of a Scientist'),
        ('Class 10', 'English', 'Footprints Without Feet', 26, 'The Necklace'),
        ('Class 10', 'English', 'Footprints Without Feet', 27, 'The Hack Driver'),
        ('Class 10', 'English', 'Footprints Without Feet', 28, 'Bholi'),
        ('Class 10', 'English', 'Footprints Without Feet', 29, 'The Book that Saved the Earth'),
        
        # Hindi - Gadya
        ('Class 10', 'Hindi', 'Gadya', 1, 'Netaji Ka Chashma'),
        ('Class 10', 'Hindi', 'Gadya', 2, 'Balgobin Bhagat'),
        ('Class 10', 'Hindi', 'Gadya', 3, 'Lakhnavi Andaz'),
        ('Class 10', 'Hindi', 'Gadya', 4, 'Ek Kahan Yeh Bhi'),
        ('Class 10', 'Hindi', 'Gadya', 5, 'Noubatkhane Mein Ibadat'),
        ('Class 10', 'Hindi', 'Gadya', 6, 'Sanskriti'),
        # Hindi - Kavya
        ('Class 10', 'Hindi', 'Kavya', 7, 'Surdas Ke Pad'),
        ('Class 10', 'Hindi', 'Kavya', 8, 'Tulsidas - Ram-Lakshman-Parashuram Samvad'),
        ('Class 10', 'Hindi', 'Kavya', 9, 'Dev - Sawaiya Aur Kavit'),
        ('Class 10', 'Hindi', 'Kavya', 10, 'Jayshankar Prasad - Aatmakathya'),
        ('Class 10', 'Hindi', 'Kavya', 11, 'Suryakant Tripathi Nirala - Utsah Aur Aat Nahi Rahi Hai'),
        ('Class 10', 'Hindi', 'Kavya', 12, 'Nagarjun - Yahi Danturit Muskan Aur Fasal'),
        
        # Sanskrit - Shemushi
        ('Class 10', 'Sanskrit', 'Shemushi', 1, 'Shuchiparyavaranam (शुचिपर्यावरणम्)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 2, 'Buddhirbalavati Sada (बुद्धिर्बलवती सदा)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 3, 'Shishulalanam (शिशुलालनम्)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 4, 'Janani Tulyavatsala (जननी तुल्यवत्सला)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 5, 'Subhashitani (सुभाषितानि)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 6, 'Sauhardam Prakriteh Shobha (सौहार्दं प्रकृतेः शोभा)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 7, 'Vichitrah Sakshi (विचित्रः साक्षी)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 8, 'Suktayah (सूक्तयः)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 9, 'Bhukampavibhishika (भूकंपविभीषिका)'),
        ('Class 10', 'Sanskrit', 'Shemushi', 10, 'Anyoktayah (अन्योक्तयः)')
    ]
    
    # Seeding class_chapters
    cursor.execute("SELECT COUNT(*) FROM class_chapters")
    chapters_exist = cursor.fetchone()[0] > 0
    if not chapters_exist:
        cursor.execute("DELETE FROM class_chapters WHERE subject_name = 'Sanskrit'")
        for class_name, sub_name, sub_sec, ch_no, ch_name in class_chapters_data:
            cursor.execute('''
            SELECT id FROM class_chapters 
            WHERE class_name = ? AND subject_name = ? AND sub_section = ? AND chapter_name = ?
            ''', (class_name, sub_name, sub_sec, ch_name))
            if not cursor.fetchone():
                cursor.execute('''
                INSERT INTO class_chapters (class_name, subject_name, sub_section, chapter_no, chapter_name)
                VALUES (?, ?, ?, ?, ?)
                ''', (class_name, sub_name, sub_sec, ch_no, ch_name))
        
    # Seed default chapter videos
    default_videos = [
        ('Class 9', 'Mathematics', '', 'Number Systems', 'Introduction to Number Systems', 'https://www.youtube.com/watch?v=NybHckSEQBI', 'YouTube'),
        ('Class 9', 'Science', 'Biology', 'Cell', 'The Fundamental Unit of Life - Cell', 'https://www.youtube.com/watch?v=yjSNU6YC1s0', 'YouTube'),
        ('Class 10', 'Science', 'Chemistry', 'Chemical Reactions and Equations', 'Chemical Reactions One Shot', 'https://www.youtube.com/watch?v=T4K86v_yQNg', 'YouTube')
    ]
    for cls, sub, sec, ch_name, v_title, v_url, v_type in default_videos:
        cursor.execute('''
            SELECT id FROM class_chapters 
            WHERE class_name = ? AND subject_name = ? AND sub_section = ? AND chapter_name = ?
        ''', (cls, sub, sec, ch_name))
        row = cursor.fetchone()
        if row:
            ch_id = row['id']
            cursor.execute('''
                SELECT id FROM chapter_videos 
                WHERE chapter_id = ? AND video_url = ?
            ''', (ch_id, v_url))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO chapter_videos (chapter_id, video_title, video_url, video_type)
                    VALUES (?, ?, ?, ?)
                ''', (ch_id, v_title, v_url, v_type))

    # Seed new default quiz questions for a couple of key chapters to demo all types & difficulties
    # 1. Class 9 Mathematics - Number Systems
    cursor.execute("SELECT id FROM class_chapters WHERE class_name='Class 9' AND subject_name='Mathematics' AND chapter_name='Number Systems'")
    ch_num_sys = cursor.fetchone()
    if ch_num_sys:
        ch_id = ch_num_sys['id']
        cursor.execute("SELECT COUNT(*) FROM quiz_questions WHERE chapter_id=?", (ch_id,))
        if cursor.fetchone()[0] == 0:
            questions = [
                # Easy - MCQ
                (ch_id, 'Easy', 'MCQ', 'Which of the following is an irrational number?', 
                 json.dumps(['3.14', '22/7', '√2', '0.333...']), 2, None, None),
                # Easy - True/False
                (ch_id, 'Easy', 'True/False', 'Every rational number is a whole number.', 
                 json.dumps(['True', 'False']), 1, None, None),
                # Medium - Assertion & Reason
                (ch_id, 'Medium', 'Assertion & Reason', 
                 'Assertion (A): √2 is an irrational number.\nReason (R): The decimal expansion of √2 is non-terminating and non-recurring.', 
                 json.dumps([
                     'Both A and R are true and R is the correct explanation of A.',
                     'Both A and R are true but R is not the correct explanation of A.',
                     'A is true but R is false.',
                     'A is false but R is true.'
                 ]), 0, None, None),
                # Medium - Match the Following
                (ch_id, 'Medium', 'Match the Following', 'Match the number types with their respective examples.', 
                 json.dumps({
                     'left': ['Natural Number', 'Integer', 'Irrational Number'],
                     'right': ['-5', '√3', '7']
                 }), 0, json.dumps({'Natural Number': '7', 'Integer': '-5', 'Irrational Number': '√3'}), None),
                # Hard - Case-Based
                (ch_id, 'Hard', 'Case-Based', 'What is the rational number represented by the first mark after 1?', 
                 json.dumps(['7/6', '5/6', '8/6', '11/6']), 0, None, 
                 'A student represents rational numbers on a number line. They want to find five rational numbers between 1 and 2. They divide the segment between 1 and 2 into 6 equal parts.')
            ]
            for ch, diff, q_type, q_text, opts, corr, matches, case in questions:
                cursor.execute('''
                    INSERT INTO quiz_questions (chapter_id, difficulty, question_type, question, options, correct_index, match_answers, case_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (ch, diff, q_type, q_text, opts, corr, matches, case))

    # 2. Class 10 Science - Chemical Reactions and Equations
    cursor.execute("SELECT id FROM class_chapters WHERE class_name='Class 10' AND subject_name='Science' AND sub_section='Chemistry' AND chapter_name='Chemical Reactions and Equations'")
    ch_chem_rx = cursor.fetchone()
    if ch_chem_rx:
        ch_id = ch_chem_rx['id']
        cursor.execute("SELECT COUNT(*) FROM quiz_questions WHERE chapter_id=?", (ch_id,))
        if cursor.fetchone()[0] == 0:
            questions = [
                # Easy - MCQ
                (ch_id, 'Easy', 'MCQ', 'What is the starting substance on the left side of a chemical equation called?', 
                 json.dumps(['Product', 'Reactant', 'Catalyst', 'Solute']), 1, None, None),
                # Easy - True/False
                (ch_id, 'Easy', 'True/False', 'Rusting of iron is an endothermic reaction.', 
                 json.dumps(['True', 'False']), 1, None, None),
                # Medium - Assertion & Reason
                (ch_id, 'Medium', 'Assertion & Reason', 
                 'Assertion (A): Respiration is an exothermic reaction.\nReason (R): Energy is released in the form of heat during respiration.', 
                 json.dumps([
                     'Both A and R are true and R is the correct explanation of A.',
                     'Both A and R are true but R is not the correct explanation of A.',
                     'A is true but R is false.',
                     'A is false but R is true.'
                 ]), 0, None, None),
                # Medium - Match the Following
                (ch_id, 'Medium', 'Match the Following', 'Match the chemical reaction type with its equation.', 
                 json.dumps({
                     'left': ['Combination', 'Decomposition', 'Displacement'],
                     'right': ['Fe + CuSO4 -> FeSO4 + Cu', 'C + O2 -> CO2', '2H2O -> 2H2 + O2']
                 }), 0, json.dumps({
                     'Combination': 'C + O2 -> CO2',
                     'Decomposition': '2H2O -> 2H2 + O2',
                     'Displacement': 'Fe + CuSO4 -> FeSO4 + Cu'
                 }), None),
                # Hard - Case-Based
                (ch_id, 'Hard', 'Case-Based', 'Which gas is evolved and how can it be tested?', 
                 json.dumps([
                     'Hydrogen gas, burns with a pop sound',
                     'Oxygen gas, extinguishes a burning splinter',
                     'Carbon dioxide, turns lime water milky with popping sound',
                     'Nitrogen gas, has a rotten egg smell'
                 ]), 0, None, 
                 'A student takes 2g of lead nitrate powder in a boiling tube and heats it over a flame. In another test tube, they react granulated zinc with dilute hydrochloric acid.')
            ]
            for ch, diff, q_type, q_text, opts, corr, matches, case in questions:
                cursor.execute('''
                    INSERT INTO quiz_questions (chapter_id, difficulty, question_type, question, options, correct_index, match_answers, case_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (ch, diff, q_type, q_text, opts, corr, matches, case))

    # Seed default sample papers
    default_sample_papers = [
        ('Class 10', 'Mathematics', 'CBSE Class 10 Mathematics Standard Sample Paper (2025-26)', '/static/uploads/sample_maths_10.pdf'),
        ('Class 10', 'Science', 'CBSE Class 10 Science Practice Board Paper', '/static/uploads/sample_science_10.pdf'),
        ('Class 9', 'Mathematics', 'Class 9 Mathematics Term-1 Sample Question Paper', '/static/uploads/sample_maths_9.pdf')
    ]
    for cls, sub, title, path in default_sample_papers:
        cursor.execute('SELECT id FROM sample_papers WHERE class_name = ? AND subject_name = ? AND paper_title = ?', (cls, sub, title))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO sample_papers (class_name, subject_name, paper_title, file_path)
                VALUES (?, ?, ?, ?)
            ''', (cls, sub, title, path))

    conn.commit()
    conn.close()
    print("Database initialised and seeded successfully!")

if __name__ == '__main__':
    init_db()
