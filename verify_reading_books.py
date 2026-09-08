"""Validate the database relationships, content coverage and final book PDFs."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import unicodedata
from reading_store import ROOT, DEFAULT_DB, connect
sys.path.insert(0, str(ROOT / '.packages'))
import pymupdf as fitz


def words(text):
    return re.findall(r'[^\W\d_]+', unicodedata.normalize('NFC', text).casefold())


def database_content(db, test):
    chunks = [test['title']]
    for passage in db.execute('SELECT * FROM passages WHERE test_id=?', (test['id'],)):
        chunks.extend([passage['title'], passage['content']])
        for section in db.execute('SELECT * FROM sections WHERE passage_id=?', (passage['id'],)):
            for field in ('instructions_json', 'content_json'):
                chunks.extend(n['text'] for n in json.loads(section[field]))
            chunks.extend(r[0] + ' ' + r[1] for r in db.execute('SELECT label,text FROM options WHERE section_id=?', (section['id'],)))
            # Discrete questions live in question records; summaries live in shared section text.
            if section['question_type'] in ('multiple_choice', 'multiple_response', 'true_false_not_given', 'yes_no_not_given', 'short_answer', 'matching_features', 'matching_information', 'matching_headings'):
                seen = set()
                for q in db.execute('SELECT * FROM questions WHERE section_id=?', (section['id'],)):
                    if q['group_key'] not in seen:
                        chunks.append(q['prompt'])
                        seen.add(q['group_key'])
    chunks.extend(r[0] + ' ' + r[1] for r in db.execute('SELECT a.answer,e.text FROM questions q JOIN answers a ON a.question_id=q.id JOIN explanations e ON e.question_id=q.id WHERE q.test_id=?', (test['id'],)))
    return ' '.join(chunks)


def validate(db, folder):
    errors = []
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        errors.append('SQLite integrity / foreign key failure')
    tests = db.execute('SELECT * FROM tests ORDER BY book_number,test_number').fetchall()
    totals = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
              for table in ['tests', 'passages', 'sections', 'questions', 'answers', 'explanations', 'assets']}
    book_results = []
    for t in tests:
        identity = f"C{t['book_number']} Test {t['test_number']}"
        details = db.execute('SELECT * FROM question_details WHERE book_number=? AND test_number=? ORDER BY question_number', (t['book_number'], t['test_number'])).fetchall()
        if [q['question_number'] for q in details] != list(range(1, 41)):
            errors.append(identity + ': question numbers incomplete')
        for q in details:
            if not q['prompt'] or not q['answer'] or not q['explanation']:
                errors.append(identity + f": empty record {q['question_number']}")
            if q['question_type'] in ('multiple_choice', 'multiple_response'):
                opts = db.execute('SELECT label,text FROM options WHERE question_id=? ORDER BY position', (q['question_id'],)).fetchall()
                expected = list('ABCDE') if q['question_type'] == 'multiple_response' else list('ABCD')
                if [o['label'] for o in opts] != expected or any(not o['text'] for o in opts):
                    errors.append(identity + f": incomplete choices {q['question_number']}")
        source_text = ' '.join(r[0] for r in db.execute('SELECT text FROM source_pages WHERE test_id=? ORDER BY page_number', (t['id'],)))
        content = database_content(db, t)
        allowed = {'part', 'passage', 'questions', 'question', 'answer', 'key', 'explanation'}
        missing = set(words(source_text)) - set(words(content)) - allowed
        if missing:
            errors.append(identity + ': source words absent from structured records: ' + str(sorted(missing)))
        for p in db.execute('SELECT * FROM passages WHERE test_id=?', (t['id'],)):
            if p['title'].startswith('You should') or len(p['content'].split()) < 300:
                errors.append(identity + ': malformed passage title/content')
            for s in db.execute('SELECT * FROM sections WHERE passage_id=?', (p['id'],)):
                opts = db.execute('SELECT label,text FROM options WHERE section_id=? AND question_id IS NULL ORDER BY position', (s['id'],)).fetchall()
                if s['question_type'] in ('matching_headings', 'summary_options', 'matching_features', 'matching_endings'):
                    if len(opts) < 3 or any(not o['text'] for o in opts) or len({o['label'] for o in opts}) != len(opts):
                        errors.append(identity + f": incomplete shared options, section {s['first_question']}")
    for book in sorted({t['book_number'] for t in tests}):
        file = folder / f'Cambridge IELTS {book} Academic Reading Practice Book.pdf'
        if not file.exists():
            errors.append(f'Missing output: {file.name}')
            continue
        with fitz.open(file) as pdf:
            text = ' '.join(p.get_text() for p in pdf)
            pdf_words = set(words(text))
            toc = pdf.get_toc()
            if len(toc) < 22 or 'Placeholder for table of contents' in text:
                errors.append(file.name + ': missing contents/bookmarks')
            for t in (t for t in tests if t['book_number'] == book):
                missing = set(words(database_content(db, t))) - pdf_words
                # Per-question browser choice controls are intentionally replaced by answer lines.
                missing -= {'a', 'b', 'c'}
                if missing:
                    errors.append(file.name + f": missing rendered words Test {t['test_number']}: {sorted(missing)}")
            for index, page in enumerate(pdf):
                if index == 0:
                    continue
                body = page.get_text(clip=fitz.Rect(50, 48, 550, 792))
                if not body.strip():
                    errors.append(file.name + f': blank page {index + 1}')
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        x0, y0, x1, y1 = line['bbox']
                        if x0 < 45 or x1 > 550 or y0 < 14 or y1 > 827:
                            errors.append(file.name + f': text outside margins page {index + 1}')
                            break
            book_results.append({'file': file.name, 'pages': len(pdf), 'bookmarks': len(toc)})
    return {'totals': totals, 'books': book_results, 'errors': errors, 'status': 'passed' if not errors else 'failed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=ROOT / 'Reading_Books')
    args = parser.parse_args()
    with connect(args.db, readonly=True) as db:
        result = validate(db, args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'validation_report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return int(bool(result['errors']))


if __name__ == '__main__':
    sys.exit(main())
