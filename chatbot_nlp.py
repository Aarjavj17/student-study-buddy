import re
import math
import collections
import sqlite3

# Standard English stopwords
STOPWORDS = {
    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 
    'him', 'his', 'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 
    'they', 'them', 'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 
    'this', 'that', 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 
    'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'a', 'an', 
    'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 'while', 'of', 'at', 
    'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during', 
    'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 
    'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 
    'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 
    'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 'should', 'now',
    'explain', 'tell', 'show', 'give', 'find', 'chapter', 'subject', 'class', 'syllabus', 
    'buddy', 'learn', 'please'
}

class LocalTFIDF:
    def __init__(self):
        self.stopwords = STOPWORDS
        self.documents = []
        self.doc_tokens = []
        self.vocab = set()
        self.idf = {}
        
    def preprocess(self, text):
        if not text:
            return []
        text = text.lower()
        # Remove punctuation, keep alphanumeric & Devanagari characters
        text = re.sub(r'[^a-z0-9\s\u0900-\u097F]', ' ', text)
        tokens = text.split()
        return [t for t in tokens if t not in self.stopwords and len(t) > 1]
        
    def fit(self, documents):
        self.documents = documents
        self.doc_tokens = [self.preprocess(doc) for doc in documents]
        
        self.vocab = set()
        for tokens in self.doc_tokens:
            self.vocab.update(tokens)
            
        total_docs = len(documents)
        self.idf = {}
        for token in self.vocab:
            containing_docs = sum(1 for tokens in self.doc_tokens if token in tokens)
            self.idf[token] = math.log((1 + total_docs) / (1 + containing_docs)) + 1.0
            
    def compute_tf(self, tokens):
        counts = collections.Counter(tokens)
        tf = {}
        for t, count in counts.items():
            tf[t] = count / len(tokens) if tokens else 0
        return tf
        
    def get_vector(self, tokens):
        tf = self.compute_tf(tokens)
        vector = {}
        for t in tokens:
            if t in self.idf:
                vector[t] = tf[t] * self.idf[t]
        return vector
        
    def cosine_similarity(self, vec1, vec2):
        intersection = set(vec1.keys()) & set(vec2.keys())
        numerator = sum(vec1[x] * vec2[x] for x in intersection)
        
        sum1 = sum(val**2 for val in vec1.values())
        sum2 = sum(val**2 for val in vec2.values())
        
        denominator = math.sqrt(sum1) * math.sqrt(sum2)
        if not denominator:
            return 0.0
        return numerator / denominator

    def score(self, query):
        query_tokens = self.preprocess(query)
        if not query_tokens:
            return []
            
        query_vector = self.get_vector(query_tokens)
        if not query_vector:
            return []
            
        results = []
        for i, doc in enumerate(self.documents):
            doc_vector = self.get_vector(self.doc_tokens[i])
            sim = self.cosine_similarity(query_vector, doc_vector)
            results.append((sim, i))
            
        return sorted(results, key=lambda x: x[0], reverse=True)


def get_general_intent_reply(message):
    """
    Checks if a query is a general intent and returns a corresponding reply.
    """
    msg_lower = message.lower()
    
    # Greetings
    if any(x in msg_lower for x in ['hello', 'hi', 'hey', 'sup', 'how are you', 'buddy', 'greetings', 'hola']):
        return ("Hello! I'm **Buddy**, your personal AI study companion. 👋\n\n"
                "I can explain chapter concepts, summarize syllabus details, suggest study tips, or test your memory! "
                "Ask me something like **'Explain Number Systems'** or **'Give me a study tip'**.")
                
    # Jokes
    elif any(x in msg_lower for x in ['joke', 'funny', 'laugh', 'humor', 'entertain']):
        import random
        jokes = [
            "Why did the student eat their math homework? Because the teacher said it was a piece of cake! 🍰",
            "Why did the two ones get married? Because they were 1-derful together! 💍",
            "Why can't you trust atoms? Because they make up everything! ⚛️",
            "What did the triangle say to the circle? 'You're pointless!' 📐",
            "Why was the math book sad? It had too many problems. 😢"
        ]
        return f"Haha, here's an educational joke for you:\n\n{random.choice(jokes)}"
        
    # Study Tips / Advice
    elif any(x in msg_lower for x in ['tip', 'study', 'advice', 'learn', 'focus', 'pomodoro', 'technique']):
        import random
        tips = [
            "⏱️ **Pomodoro Technique**: Study focused for 25 minutes, then take a 5-minute break. After 4 cycles, take a longer 15-minute break. This prevents mental fatigue!",
            "🧠 **Active Recall**: Don't just reread textbook paragraphs. Close the book, write down everything you remember, and highlight what you missed.",
            "🧸 **Feynman Technique**: Try explaining a concept in simple terms to a friend (or even a toy). If you hit a blank spot, review that part of the chapter.",
            "📅 **Spaced Repetition**: Review your notes after 1 day, then 3 days, then a week. This moves the details into your long-term memory!"
        ]
        return f"Here is a great study tip to boost your focus:\n\n{random.choice(tips)}"
        
    # Motivation
    elif any(x in msg_lower for x in ['motivation', 'tired', 'bored', 'lazy', 'hard', 'give up', 'depressed', 'stress']):
        import random
        quotes = [
            "🌟 *\"Don't study to react, study to understand. The knowledge you build today will open doors tomorrow.\"*",
            "💪 *\"Mistakes are proof that you are trying. Every wrong answer in the Quiz Arena is a step closer to understanding.\"*",
            "🚀 *\"You don't have to be perfect. You just have to be 1% better than yesterday. Let's do a single 5-minute study block together!\"*"
        ]
        return f"Hang in there! You've got this. Here is a little boost of motivation:\n\n{random.choice(quotes)}"
        
    # Help / Commands
    elif any(x in msg_lower for x in ['help', 'features', 'what can you do', 'guide', 'commands']):
        return ("Here are some things you can ask me:\n\n"
                "- **Syllabus Queries**: Ask *'Explain Chemical Reactions'* or *'Sanskrit Chapter 1'*.\n"
                "- **Study Tips**: Ask *'How do I focus?'* or *'Give me study advice'*.\n"
                "- **Quick Breaks**: Ask *'Tell me a joke'*.\n"
                "- **Review Material**: Ask *'Show notes'* or *'Do you have sample papers?'*.")
                
    return None


def search_syllabus_context(query, db_path):
    """
    Connects to the sqlite DB, index chapters, notes, and videos, 
    and finds the best context matching the query using TF-IDF.
    """
    try:
        from database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Fetch all chapters
        cursor.execute("SELECT id, class_name, subject_name, sub_section, chapter_no, chapter_name FROM class_chapters")
        chapters = [dict(row) for row in cursor.fetchall()]
        
        if not chapters:
            conn.close()
            return None
            
        # 2. Fetch all notes
        cursor.execute("SELECT topic_id, content FROM notes")
        notes = {row['topic_id']: row['content'] for row in cursor.fetchall()}
        
        # 3. Fetch chapter videos
        cursor.execute("SELECT chapter_id, video_title, video_url FROM chapter_videos")
        videos = {}
        for row in cursor.fetchall():
            videos.setdefault(row['chapter_id'], []).append({
                'title': row['video_title'],
                'url': row['video_url']
            })
            
        # 4. Fetch resources count/list
        cursor.execute("SELECT chapter_id, resource_type, file_path, resource_title FROM chapter_resources")
        resources = {}
        for row in cursor.fetchall():
            resources.setdefault(row['chapter_id'], []).append({
                'type': row['resource_type'],
                'path': row['file_path'],
                'title': row['resource_title']
            })
            
        conn.close()
        
        # Build document strings to index
        documents = []
        doc_metadata = []
        for ch in chapters:
            ch_id = ch['id']
            ch_notes = notes.get(str(ch_id), '')
            ch_vids = ", ".join([v['title'] for v in videos.get(ch_id, [])])
            ch_res = ", ".join([r['title'] or r['type'] for r in resources.get(ch_id, [])])
            
            doc_str = (
                f"Class: {ch['class_name']}. "
                f"Subject: {ch['subject_name']}. "
                f"Chapter {ch['chapter_no']}: {ch['chapter_name']}. "
                f"Section: {ch['sub_section']}. "
                f"Notes: {ch_notes}. "
                f"Videos: {ch_vids}. "
                f"Resources: {ch_res}."
            )
            documents.append(doc_str)
            doc_metadata.append({
                'chapter': ch,
                'notes': ch_notes,
                'videos': videos.get(ch_id, []),
                'resources': resources.get(ch_id, [])
            })
            
        # Fit TF-IDF model
        engine = LocalTFIDF()
        engine.fit(documents)
        
        scores = engine.score(query)
        if scores and scores[0][0] > 0.12:  # Threshold for relevance
            best_match = doc_metadata[scores[0][1]]
            best_match['score'] = scores[0][0]
            return best_match
            
    except Exception as e:
        print(f"Chatbot NLP error searching context: {e}")
        
    return None


def generate_local_nlp_response(matched_context):
    """
    Generates a beautifully formatted educational reply based on the local retrieved context.
    """
    ch = matched_context['chapter']
    notes = matched_context['notes']
    videos = matched_context['videos']
    resources = matched_context['resources']
    
    section_prefix = f" ({ch['sub_section']})" if ch['sub_section'] else ""
    
    reply = f"I found some information from your syllabus! 📚\n\n"
    reply += f"### 📘 {ch['class_name']} - {ch['subject_name']}{section_prefix}\n"
    reply += f"**Chapter {ch['chapter_no']}: {ch['chapter_name']}**\n\n"
    
    if notes:
        reply += f"#### 📝 Your Study Notes:\n"
        # Truncate notes if they are too long
        if len(notes) > 300:
            reply += f"_{notes[:300]}..._ *(Read full notes in the Learn Hub)*\n\n"
        else:
            reply += f"_{notes}_\n\n"
    else:
        reply += f"#### 📝 Study Notes:\n_No notes have been written for this chapter yet. You can start summarizing this topic in the Learn Hub!_\n\n"
        
    if videos:
        reply += f"#### 🎥 Video References:\n"
        for vid in videos:
            reply += f"- [{vid['title']}]({vid['url']})\n"
        reply += "\n"
        
    if resources:
        reply += f"#### 📁 Available PDFs/Resources:\n"
        for res in resources:
            title = res['title'] or res['type'].replace('_', ' ').title()
            reply += f"- **{title}**\n"
        reply += "\n"
        
    reply += f"Would you like to head over to **Learn Hub** to review this topic, or go to **Quiz Arena** to test your knowledge? 🚀"
    
    return reply
