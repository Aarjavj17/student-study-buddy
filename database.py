import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

def get_db_connection():
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
        total_hours REAL DEFAULT 0.0
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
        topic_id TEXT NOT NULL,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
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
        topic_id TEXT NOT NULL,
        question TEXT NOT NULL,
        options TEXT NOT NULL, -- JSON string list
        correct_index INTEGER NOT NULL
    )
    ''')
    
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
        
    # Seed Quiz Questions
    quiz_questions_data = [
        # Maths - Algebra
        ('maths_algebra', 'What is the value of x in 2x + 5 = 15?', ['2', '5', '10', '15'], 1),
        ('maths_algebra', 'What is the coefficient of x in the expression 5x^2 - 3x + 7?', ['5', '-3', '3', '7'], 1),
        ('maths_algebra', 'Simplify: 3(x + 2) - 4', ['3x + 2', '3x - 2', '3x + 6', '3x + 10'], 0),
        ('maths_algebra', 'If y = 3x - 4 and x = 2, what is y?', ['2', '4', '-4', '10'], 0),
        ('maths_algebra', 'Which of the following is a linear equation?', ['x^2 + 2 = 0', 'y = 3x - 1', 'xy = 4', 'y = 1/x'], 1),
        
        # Science - Gravity
        ('science_gravity', 'What is the value of acceleration due to gravity on Earth\'s surface?', ['9.8 m/s²', '1.6 m/s²', '10.8 m/s²', '9.8 cm/s²'], 0),
        ('science_gravity', 'Who formulated the Universal Law of Gravitation?', ['Albert Einstein', 'Isaac Newton', 'Galileo Galilei', 'Nikola Tesla'], 1),
        ('science_gravity', 'If the mass of an object is doubled, what happens to its gravitational pull (keeping distance same)?', ['Halved', 'Doubled', 'Remains same', 'Quadrupled'], 1),
        ('science_gravity', 'What is the approximate gravity on the Moon compared to Earth?', ['Same', '6 times more', '1/6th of Earth', '1/10th of Earth'], 2),
        ('science_gravity', 'Gravity is a repulsive force.', ['True', 'False'], 1),
        
        # Science - Chemical Reactions
        ('science_reactions', 'What is the reaction called when two or more substances combine to form a single substance?', ['Decomposition', 'Combination/Synthesis', 'Displacement', 'Combustion'], 1),
        ('science_reactions', 'In a chemical equation, what do we call the starting substances on the left side?', ['Products', 'Reactants', 'Catalysts', 'Solutes'], 1),
        ('science_reactions', 'What is the gas produced when a active metal reacts with dilute acid?', ['Oxygen', 'Carbon Dioxide', 'Hydrogen', 'Nitrogen'], 2),
        ('science_reactions', 'A reaction that releases heat energy into the surroundings is:', ['Endothermic', 'Exothermic', 'Reversible', 'Decomposition'], 1),
        ('science_reactions', 'Rusting of iron is which type of reaction?', ['Fast physical change', 'Slow chemical reaction/oxidation', 'Displacement', 'Reversible change'], 1)
    ]
    
    # Clear existing questions to avoid duplicates and re-seed clean values
    cursor.execute('DELETE FROM quiz_questions')
    for q_topic, q_text, q_opts, q_correct in quiz_questions_data:
        cursor.execute('''
        INSERT INTO quiz_questions (topic_id, question, options, correct_index)
        VALUES (?, ?, ?, ?)
        ''', (q_topic, q_text, json.dumps(q_opts), q_correct))
        
    conn.commit()
    conn.close()
    print("Database initialised and seeded successfully!")

if __name__ == '__main__':
    init_db()
