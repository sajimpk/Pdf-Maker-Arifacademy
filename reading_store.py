"""Structured, source-traceable SQLite storage for local IELTS Reading PDFs."""
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'reading_books.db'

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS tests (
 id INTEGER PRIMARY KEY, book_number INTEGER NOT NULL, test_number INTEGER NOT NULL,
 title TEXT NOT NULL, source_name TEXT NOT NULL, source_sha256 TEXT NOT NULL,
 imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(book_number,test_number));
CREATE TABLE IF NOT EXISTS passages (
 id INTEGER PRIMARY KEY, test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
 passage_number INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
 paragraphs_json TEXT NOT NULL, source_pages TEXT NOT NULL,
 UNIQUE(test_id,passage_number));
CREATE TABLE IF NOT EXISTS sections (
 id INTEGER PRIMARY KEY, passage_id INTEGER NOT NULL REFERENCES passages(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, first_question INTEGER NOT NULL, last_question INTEGER NOT NULL,
 question_type TEXT NOT NULL, instructions_json TEXT NOT NULL, content_json TEXT NOT NULL,
 source_pages TEXT NOT NULL, UNIQUE(passage_id,position));
CREATE TABLE IF NOT EXISTS questions (
 id INTEGER PRIMARY KEY, test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
 section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
 question_number INTEGER NOT NULL, prompt TEXT NOT NULL, group_key TEXT,
 source_pages TEXT NOT NULL, UNIQUE(test_id,question_number));
CREATE TABLE IF NOT EXISTS options (
 id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
 question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
 label TEXT NOT NULL, text TEXT NOT NULL, position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS answers (
 question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
 answer TEXT NOT NULL, source_pages TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS explanations (
 question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
 text TEXT NOT NULL, source_pages TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, mime_type TEXT NOT NULL, data BLOB NOT NULL,
 source_page INTEGER NOT NULL, width REAL NOT NULL, height REAL NOT NULL);
CREATE TABLE IF NOT EXISTS source_pages (
 test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
 page_number INTEGER NOT NULL, text TEXT NOT NULL, lines_json TEXT NOT NULL,
 PRIMARY KEY(test_id,page_number));
CREATE VIEW IF NOT EXISTS question_details AS
 SELECT t.book_number,t.test_number,p.passage_number,p.title passage_title,
 s.question_type,s.first_question,s.last_question,q.question_number,q.prompt,
 a.answer,e.text explanation,q.id question_id,s.id section_id
 FROM questions q JOIN tests t ON t.id=q.test_id
 JOIN sections s ON s.id=q.section_id JOIN passages p ON p.id=s.passage_id
 LEFT JOIN answers a ON a.question_id=q.id
 LEFT JOIN explanations e ON e.question_id=q.id;
'''


def connect(path=DEFAULT_DB, readonly=False):
    path = Path(path).resolve()
    if readonly:
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db
