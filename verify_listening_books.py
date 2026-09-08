"""Validate Listening data, table/option coverage and PDFs with no audio URLs."""
import argparse
from pathlib import Path
import json
import re
from listening_store import ROOT, DEFAULT_DB, connect
from verify_reading_books import words, fitz


def task_content(db, t):
    texts = []
    for p in db.execute('SELECT * FROM parts WHERE test_id=?', (t['id'],)):
        for s in db.execute('SELECT * FROM sections WHERE part_id=?', (p['id'],)):
            for key in ['instructions_json', 'content_json']:
                for n in json.loads(s[key]):
                    texts.append(' '.join(cell for row in n['rows'] for cell in row) if n['kind'] == 'table' else n['text'])
            texts.extend(r[0] + ' ' + r[1] for r in db.execute('SELECT label,text FROM options WHERE section_id=?', (s['id'],)))
            if s['question_type'] in ('multiple_choice', 'multiple_response'):
                texts.extend(r[0] for r in db.execute('SELECT prompt FROM questions WHERE section_id=?', (s['id'],)))
    return ' '.join(texts)


def validate(db, output):
    errors = []
    totals = {t: db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in
        ['tests', 'parts', 'sections', 'questions', 'answers', 'explanations', 'transcripts', 'assets']}
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        errors.append('SQLite integrity failure')
    if 'audio_url' in [r[1] for r in db.execute('PRAGMA table_info(parts)')]:
        errors.append('Audio URL column remains')
    tests = db.execute('SELECT * FROM tests ORDER BY book_number,test_number').fetchall()
    contents = {}
    for t in tests:
        label = f"C{t['book_number']} Test {t['test_number']}"
        qs = db.execute('SELECT * FROM question_details WHERE book_number=? AND test_number=? ORDER BY question_number', (t['book_number'], t['test_number'])).fetchall()
        if [q['question_number'] for q in qs] != list(range(1, 41)):
            errors.append(label + ': question coverage')
        for q in qs:
            if not all(q[k] for k in ['prompt', 'answer', 'explanation']):
                errors.append(label + ': empty question record')
            if q['question_type'] in ('matching_features', 'map_label'):
                if re.findall(r'\{\{(\d+)\}\}', q['prompt']) != [str(q['question_number'])]:
                    errors.append(label + f": combined question labels at {q['question_number']}")
            if q['question_type'] in ('multiple_choice', 'multiple_response'):
                opts = db.execute('SELECT label,text FROM options WHERE question_id=? ORDER BY position', (q['question_id'],)).fetchall()
                expected = list('ABCDE') if q['question_type'] == 'multiple_response' else list('ABC')
                if [o['label'] for o in opts] != expected or any(not o['text'] for o in opts):
                    errors.append(label + f": choices missing for {q['question_number']}")
        raw_tasks, raw_transcripts = [], {n: [] for n in range(1, 5)}
        state, pn = 'questions', 0
        for page in db.execute('SELECT * FROM source_pages WHERE test_id=? ORDER BY page_number', (t['id'],)):
            if re.search(r'https?://|\.mp3', page['text'], re.I):
                errors.append(label + ': audio URL remains in stored source text')
            for line in json.loads(page['lines_json']):
                text = line['text'].strip()
                if text == 'Transcripts':
                    state = 'transcript'
                elif text == 'Answer Key':
                    state = 'answers'
                elif state == 'questions':
                    raw_tasks.append(text)
                elif state == 'transcript':
                    match = re.fullmatch(r'Part\s+(\d+)', text)
                    if match:
                        pn = int(match[1])
                    else:
                        raw_transcripts[pn].append(text)
        tasks = task_content(db, t)
        missing = set(words(' '.join(raw_tasks))) - set(words(tasks)) - {'part', 'questions', 'question', 'drag'} - set('abcdefghijk')
        if missing:
            errors.append(label + ': missing task vocabulary: ' + str(sorted(missing)))
        all_text = [tasks]
        for p in db.execute('SELECT * FROM parts WHERE test_id=? ORDER BY part_number', (t['id'],)):
            transcript = db.execute('SELECT content FROM transcripts WHERE part_id=?', (p['id'],)).fetchone()
            if not transcript or words(' '.join(raw_transcripts[p['part_number']])) != words(transcript[0]):
                errors.append(label + f": transcript words/order differ, Part {p['part_number']}")
            else:
                all_text.append(transcript[0])
            for s in db.execute('SELECT * FROM sections WHERE part_id=?', (p['id'],)):
                if s['question_type'] == 'map_label' and not db.execute('SELECT id FROM assets WHERE section_id=?', (s['id'],)).fetchone():
                    errors.append(label + ': map missing')
                if s['question_type'] == 'matching_features':
                    opts = db.execute('SELECT label,text FROM options WHERE section_id=? AND question_id IS NULL ORDER BY position', (s['id'],)).fetchall()
                    if len(opts) < 3 or len({o['label'] for o in opts}) != len(opts) or any(not o['text'] for o in opts):
                        errors.append(label + ': matching options malformed')
        all_text.extend(q['answer'] + ' ' + q['explanation'] for q in qs)
        contents.setdefault(t['book_number'], []).extend(all_text)
    reports = []
    for book, chunks in contents.items():
        file = output / f'Cambridge IELTS {book} Academic Listening Practice Book.pdf'
        if not file.exists():
            errors.append('Missing book: ' + file.name)
            continue
        with fitz.open(file) as pdf:
            all_text = ' '.join(p.get_text() for p in pdf)
            if re.search(r'https?://|\.mp3|audio link|QR code', all_text, re.I):
                errors.append(file.name + ': audio reference in output')
            if any(l.get('uri') for p in pdf for l in p.get_links()):
                errors.append(file.name + ': external link in output')
            missing = set(words(' '.join(chunks))) - set(words(all_text))
            if missing:
                errors.append(file.name + ': missing rendered vocabulary: ' + str(sorted(missing)))
            if len(pdf.get_toc()) < 30 or 'Placeholder for table of contents' in all_text:
                errors.append(file.name + ': contents not complete')
            for index, page in enumerate(pdf):
                if index == 0:
                    continue
                if not page.get_text(clip=fitz.Rect(50, 48, 550, 792)).strip():
                    errors.append(file.name + f': blank page {index + 1}')
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        x0, y0, x1, y1 = line['bbox']
                        if x0 < 45 or x1 > 550 or y0 < 14 or y1 > 827:
                            errors.append(file.name + f': text outside margins, page {index + 1}')
            reports.append({'file': file.name, 'pages': len(pdf), 'bookmarks': len(pdf.get_toc()), 'external_links': 0})
    return {'totals': totals, 'books': reports, 'errors': errors, 'status': 'failed' if errors else 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=ROOT / 'Listening_Books')
    args = parser.parse_args()
    with connect(args.db, readonly=True) as db:
        report = validate(db, args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'validation_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return int(bool(report['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
