import sqlite3
from database import get_db_connection

def view_students():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Count total students
        cursor.execute("SELECT COUNT(*) as count FROM users")
        total_users = cursor.fetchone()['count']
        
        print("=" * 60)
        print(f"DATABASE SUMMARY: {total_users} student(s) registered.")
        print("=" * 60)
        
        if total_users > 0:
            # Query all user details
            cursor.execute("SELECT id, username, xp, level, streak, total_hours FROM users")
            users = cursor.fetchall()
            
            print(f"{'ID':<5} | {'Username':<15} | {'Level':<6} | {'XP':<6} | {'Streak':<7} | {'Hours Studied':<12}")
            print("-" * 60)
            for user in users:
                print(f"{user['id']:<5} | {user['username']:<15} | {user['level']:<6} | {user['xp']:<6} | {user['streak']:<7} | {round(user['total_hours'], 2):<12}")
        else:
            print("No student accounts have been created yet.")
        print("=" * 60)
        
        conn.close()
    except Exception as e:
        print(f"Error accessing database: {e}")

if __name__ == '__main__':
    view_students()
