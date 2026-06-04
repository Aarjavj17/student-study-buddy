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
    
    # Check if schema upgrade is needed for class_resources
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='class_resources'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(class_resources)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'book_pdf_url' not in columns or 'formula_sheet_url' not in columns:
            cursor.execute("DROP TABLE class_resources")
            conn.commit()

    # 8. Class Resources Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS class_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_name TEXT NOT NULL,
        subject_name TEXT NOT NULL,
        chapter_no INTEGER NOT NULL,
        chapter_name TEXT NOT NULL,
        ncert_url TEXT DEFAULT '',
        notes_url TEXT DEFAULT '',
        exemplar_url TEXT DEFAULT '',
        book_pdf_url TEXT DEFAULT '',
        formula_sheet_url TEXT DEFAULT ''
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
        
    # Check if obsolete table class_resources exists, drop it
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='class_resources'")
    if cursor.fetchone():
        cursor.execute("DROP TABLE class_resources")
        conn.commit()

    # Create new class_chapters and chapter_resources tables
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

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chapter_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        resource_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        FOREIGN KEY(chapter_id) REFERENCES class_chapters(id) ON DELETE CASCADE,
        UNIQUE(chapter_id, resource_type)
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
        ('Class 10', 'Hindi', 'Kavya', 12, 'Nagarjun - Yahi Danturit Muskan Aur Fasal')
    ]
    
    # Seeding class_chapters
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

    conn.commit()
    conn.close()
    print("Database initialised and seeded successfully!")

if __name__ == '__main__':
    init_db()
