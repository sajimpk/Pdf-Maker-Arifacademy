import sqlite3
import os
import re

DB_PATH = "quiz_data.db"

def normalize_title(title):
    # Remove | Result or similar suffixes
    title = title.split('|')[0]
    # Clean whitespace and lowercase
    return re.sub(r'\s+', ' ', title).strip().lower()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_number INTEGER UNIQUE,
            title TEXT NOT NULL
        )
    """)
    
    # Create passages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL,
            passage_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            question_html TEXT,
            FOREIGN KEY (test_id) REFERENCES tests (id) ON DELETE CASCADE,
            UNIQUE(test_id, passage_number)
        )
    """)
    
    # Create questions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL,
            q_number INTEGER NOT NULL,
            passage_number INTEGER NOT NULL,
            q_type TEXT NOT NULL,
            question_text TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            excerpt_explanation TEXT,
            answer_explanation TEXT,
            reason_explanation TEXT,
            FOREIGN KEY (test_id) REFERENCES tests (id) ON DELETE CASCADE,
            UNIQUE(test_id, q_number)
        )
    """)
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def insert_test(test_number, title):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if a test with the same title (test name) already exists in the database
        cursor.execute("SELECT id, test_number, title FROM tests")
        rows = cursor.fetchall()
        existing_test = None
        normalized_target = normalize_title(title)
        for row in rows:
            if normalize_title(row['title']) == normalized_target:
                existing_test = row
                break
        
        if existing_test:
            test_id = existing_test['id']
            # If the user specified a new test_number, we can try to update it.
            # But we must check if that new test_number is already used by another test to avoid constraint violation.
            new_test_number = test_number
            if new_test_number != existing_test['test_number']:
                cursor.execute("SELECT id FROM tests WHERE test_number = ? AND id != ?", (new_test_number, test_id))
                if cursor.fetchone():
                    # The number is taken by another test, so keep the existing test's number to be safe
                    new_test_number = existing_test['test_number']
            
            # Update the title and test_number
            cursor.execute(
                "UPDATE tests SET title = ?, test_number = ? WHERE id = ?",
                (title, new_test_number, test_id)
            )
            # Delete old passages and questions associated with this test to avoid duplicates/orphans
            cursor.execute("DELETE FROM passages WHERE test_id = ?", (test_id,))
            cursor.execute("DELETE FROM questions WHERE test_id = ?", (test_id,))
            conn.commit()
            return test_id
        else:
            # If no test with this title exists, check if the test_number is taken
            # to avoid UNIQUE constraint violation. If taken, assign the next available number.
            cursor.execute("SELECT id FROM tests WHERE test_number = ?", (test_number,))
            if cursor.fetchone():
                cursor.execute("SELECT MAX(test_number) FROM tests")
                max_row = cursor.fetchone()
                max_num = max_row[0] if max_row and max_row[0] is not None else 0
                test_number = max_num + 1
            
            # Insert a new test record
            cursor.execute(
                "INSERT INTO tests (test_number, title) VALUES (?, ?)",
                (test_number, title)
            )
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()

def insert_passage(test_id, passage_number, title, content, question_html):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO passages (test_id, passage_number, title, content, question_html) VALUES (?, ?, ?, ?, ?)",
            (test_id, passage_number, title, content, question_html)
        )
        conn.commit()
    finally:
        conn.close()

def insert_question(test_id, q_number, passage_number, q_type, question_text, correct_answer, excerpt, answer_exp, reason):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT OR REPLACE INTO questions 
               (test_id, q_number, passage_number, q_type, question_text, correct_answer, excerpt_explanation, answer_explanation, reason_explanation) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (test_id, q_number, passage_number, q_type, question_text, correct_answer, excerpt, answer_exp, reason)
        )
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
