"""Import Writing/Speaking PDFs into SQLite, typeset books, and verify outputs."""
import argparse
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.packages'))
import pymupdf as fitz
from build_reading_books import (BookDoc, Cover, Hairline, WIDTH, Paragraph,
    Spacer, PageBreak, KeepTogether, Image, TableOfContents, ParagraphStyle,
    register_fonts, styles, markup, heading)

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS tests (
 id INTEGER PRIMARY KEY, book_number INTEGER NOT NULL, test_number INTEGER NOT NULL,
 source_file TEXT NOT NULL, source_text TEXT NOT NULL,
 UNIQUE(book_number,test_number));
CREATE TABLE IF NOT EXISTS sections (
 id INTEGER PRIMARY KEY, test_id INTEGER NOT NULL REFERENCES tests ON DELETE CASCADE,
 part_number INTEGER NOT NULL, UNIQUE(test_id,part_number));
CREATE TABLE IF NOT EXISTS questions (
 id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL REFERENCES sections ON DELETE CASCADE,
 question_number INTEGER NOT NULL, prompt TEXT NOT NULL,
 sample_answer TEXT, explanation TEXT, UNIQUE(section_id,question_number));
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL REFERENCES sections ON DELETE CASCADE,
 position INTEGER NOT NULL, source_page INTEGER NOT NULL, image BLOB NOT NULL);
'''


def tokens(text):
    return re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold())


def parse_source(path, subject):
    match = re.search(r'IELTS (\d+) Academic ' + subject + r' Test (\d+)', path.name)
    if not match:
        raise ValueError(f'Unrecognised source name: {path.name}')
    sections, current, question, all_text = [], None, None, []
    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc):
            all_text.append(page.get_text())
            for block in page.get_text('dict')['blocks']:
                if block['type'] == 1:
                    if current is None:
                        raise ValueError('Image before first part')
                    # A page-clipped chart can repeat the same full embedded image.
                    if not any(data == block['image'] for _, data in current['assets']):
                        current['assets'].append((page_index + 1, block['image']))
                    continue
                for line in block.get('lines', []):
                    text = ' '.join(''.join(s['text'] for s in line['spans']).split())
                    if not text or text.startswith('Cambridge IELTS '):
                        continue
                    part = re.fullmatch(r'Part (\d+)', text)
                    q = re.fullmatch(r'Question (\d+)', text)
                    if part:
                        current = {'number': int(part[1]), 'questions': [], 'assets': []}
                        sections.append(current)
                        question = None
                        if subject == 'Writing':
                            question = {'number': int(part[1]), 'lines': []}
                            current['questions'].append(question)
                    elif q and current is not None:
                        question = {'number': int(q[1]), 'lines': []}
                        current['questions'].append(question)
                    elif question is not None:
                        question['lines'].append(text)
                    else:
                        raise ValueError(f'Unassigned source text: {text}')
    expected = [1, 2] if subject == 'Writing' else [1, 2, 3]
    if [s['number'] for s in sections] != expected:
        raise ValueError('Unexpected part sequence')
    numbers = [q['number'] for s in sections for q in s['questions']]
    if numbers != list(range(1, (2 if subject == 'Writing' else 11) + 1)):
        raise ValueError('Incomplete question sequence')
    if any(not q['lines'] for s in sections for q in s['questions']):
        raise ValueError('Empty question')
    return int(match[1]), int(match[2]), '\n'.join(all_text), sections


def import_sources(db, directory, subject):
    files = sorted(directory.glob('*.pdf'))
    if not files:
        raise ValueError(f'No PDF sources in {directory}')
    report = []
    for path in files:
        book, test, raw, sections = parse_source(path, subject)
        with db:
            db.execute('DELETE FROM tests WHERE book_number=? AND test_number=?', (book, test))
            tid = db.execute('INSERT INTO tests(book_number,test_number,source_file,source_text) VALUES(?,?,?,?)',
                             (book, test, path.name, raw)).lastrowid
            for section in sections:
                sid = db.execute('INSERT INTO sections(test_id,part_number) VALUES(?,?)',
                                 (tid, section['number'])).lastrowid
                for q in section['questions']:
                    db.execute('INSERT INTO questions(section_id,question_number,prompt) VALUES(?,?,?)',
                               (sid, q['number'], '\n'.join(q['lines'])))
                for index, (page, data) in enumerate(section['assets']):
                    db.execute('INSERT INTO assets(section_id,position,source_page,image) VALUES(?,?,?,?)',
                               (sid, index, page, data))
        report.append({'file': path.name, 'book': book, 'test': test, 'sections': len(sections),
                       'questions': sum(len(s['questions']) for s in sections),
                       'assets': sum(len(s['assets']) for s in sections)})
    return report


def load_tests(db, book, test=None):
    rows = db.execute('SELECT * FROM tests WHERE book_number=? AND (? IS NULL OR test_number=?) ORDER BY test_number',
                      (book, test, test)).fetchall()
    tests = []
    for row in rows:
        item = dict(row)
        item['sections'] = []
        for section in db.execute('SELECT * FROM sections WHERE test_id=? ORDER BY part_number', (row['id'],)):
            section = dict(section)
            section['questions'] = [dict(q) for q in db.execute('SELECT * FROM questions WHERE section_id=? ORDER BY question_number', (section['id'],))]
            section['assets'] = [dict(a) for a in db.execute('SELECT * FROM assets WHERE section_id=? ORDER BY position', (section['id'],))]
            item['sections'].append(section)
        tests.append(item)
    if not tests:
        raise ValueError('No matching tests')
    return tests


def story_for(tests, book, subject, st):
    story = [Cover(book, len(tests), tests[0]['test_number'] if len(tests) == 1 else None, subject),
             PageBreak(), Paragraph('Contents', st['title'])]
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle('toc0', fontName='Sans-Bold', fontSize=11, leading=16, spaceBefore=9),
                       ParagraphStyle('toc1', fontName='Sans', fontSize=10, leading=14, leftIndent=15, spaceBefore=3)]
    story.extend([toc, Spacer(1, 24), Paragraph(
        'Practice questions reproduced from the supplied source PDFs. Charts and cue cards are retained. '
        'The source files do not contain sample answers or explanations.', st['small'])])
    for test in tests:
        tn = test['test_number']
        story.extend([PageBreak(), heading(f'Test {tn}', st['title'], f'test-{tn}', running=f'TEST {tn}'), Hairline()])
        for index, section in enumerate(test['sections']):
            pn = section['part_number']
            if index:
                story.append(PageBreak())
            label = f'Task {pn}' if subject == 'Writing' else f'Part {pn}'
            story.append(heading(label, st['section'], f'test-{tn}-part-{pn}', 1))
            for q in section['questions']:
                prompt = q['prompt']
                if subject == 'Speaking' and pn == 2:
                    lines = prompt.splitlines()
                    split = next((i for i, line in enumerate(lines) if line.lower().startswith('you should say')), 1)
                    story.extend([Paragraph('CUE CARD', st['eyebrow']),
                                  Paragraph(markup(' '.join(lines[:split])), st['subhead'])])
                    cue = []
                    for line in lines[split:]:
                        if cue and not re.match(r'^(You should say|what|when|where|who|how|why|and explain)\b', line, re.I):
                            cue[-1] += ' ' + line
                        else:
                            cue.append(line)
                    story.extend(Paragraph(markup(line), st['question']) for line in cue)
                    story.extend([Spacer(1, 22), Paragraph('Your notes', st['subhead'])])
                    story.extend(Hairline() for _ in range(12))
                else:
                    text = markup(' '.join(prompt.splitlines()))
                    if subject == 'Speaking':
                        text = f'<b>{q["question_number"]}.</b>  ' + text
                    story.append(Paragraph(text, st['question']))
                    story.append(Spacer(1, 14))
                if q['sample_answer']:
                    story.extend([Paragraph('Sample answer', st['subhead']), Paragraph(markup(q['sample_answer']), st['body'])])
                if q['explanation']:
                    story.extend([Paragraph('Explanation', st['subhead']), Paragraph(markup(q['explanation']), st['body'])])
            images = [Image(io.BytesIO(asset['image'])) for asset in section['assets']]
            if images:
                # Keep related chart images together at a readable common width.
                width = min(WIDTH, 520 / sum(img.imageHeight / img.imageWidth for img in images))
                for img in images:
                    img.drawWidth, img.drawHeight = width, width * img.imageHeight / img.imageWidth
                story.append(KeepTogether([Spacer(1, 8), *images]))
            if subject == 'Writing':
                story.extend([PageBreak(), Paragraph(f'Test {tn} / Task {pn} · Writing space', st['section'])])
                for _ in range(27):
                    story.extend([Hairline(), Spacer(1, 12)])
    return story


def verify(db, tests, target):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Database integrity check failed')
    with fitz.open(target) as doc:
        output = tokens(' '.join(p.get_text() for p in doc))
        cursor = 0
        for test in tests:
            # Compare complete prompt word order against the archived source text.
            source = tokens(re.sub(r'Cambridge IELTS \d+ Academic \w+ Test \d+|Part \d+|Question \d+', '', test['source_text']))
            prompts = tokens(' '.join(q['prompt'] for s in test['sections'] for q in s['questions']))
            if source != prompts:
                raise ValueError(f'Source text differs from stored prompts: {test["source_file"]}')
            for s in test['sections']:
                for q in s['questions']:
                    wanted = tokens(q['prompt'])
                    for start in range(cursor, len(output) - len(wanted) + 1):
                        if output[start:start + len(wanted)] == wanted:
                            cursor = start + len(wanted)
                            break
                    else:
                        raise ValueError(f'Output missing prompt {q["question_number"]}')
        assets = sum(len(s['assets']) for t in tests for s in t['sections'])
        if sum(len(p.get_image_info()) for p in doc) < assets:
            raise ValueError('Missing chart images')
        for page in doc:
            if not page.get_text().strip():
                raise ValueError('Blank page')
            if any(link.get('uri') for link in page.get_links()):
                raise ValueError('Unexpected external link')
            for word in page.get_text('words'):
                if word[0] < 0 or word[1] < 0 or word[2] > page.rect.width + 1 or word[3] > page.rect.height + 1:
                    raise ValueError('Text outside page')
        if len(doc.get_toc()) < sum(1 + len(t['sections']) for t in tests):
            raise ValueError('Missing PDF bookmarks')
        return {'file': target.name, 'pages': len(doc), 'tests': len(tests), 'assets': assets, 'validation': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject', choices=['writing', 'speaking', 'both'], default='both')
    parser.add_argument('--from-db', action='store_true', help='Preserve database edits; skip source import')
    parser.add_argument('--book', type=int)
    parser.add_argument('--test', type=int)
    parser.add_argument('--font-dir', type=Path)
    args = parser.parse_args()
    if args.test and not args.book:
        parser.error('--test requires --book')
    register_fonts(args.font_dir)
    for subject in (['Writing', 'Speaking'] if args.subject == 'both' else [args.subject.title()]):
        path = ROOT / f'{subject.lower()}_books.db'
        if args.from_db and not path.exists():
            raise FileNotFoundError(path)
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            if not args.from_db:
                imported = import_sources(db, ROOT / subject, subject)
                path.with_suffix('.import.json').write_text(json.dumps(imported, indent=2), encoding='utf-8')
            output = ROOT / f'{subject}_Books'
            output.mkdir(exist_ok=True)
            books = [args.book] if args.book else [r[0] for r in db.execute('SELECT DISTINCT book_number FROM tests ORDER BY book_number')]
            results = []
            for book in books:
                tests = load_tests(db, book, args.test)
                suffix = f'Test {args.test}' if args.test else 'Practice Book'
                target = output / f'Cambridge IELTS {book} Academic {subject} {suffix}.pdf'
                temp = target.with_suffix('.tmp.pdf')
                try:
                    doc = BookDoc(temp, book, subject=subject)
                    doc.multiBuild(story_for(tests, book, subject, styles()))
                    result = verify(db, tests, temp)
                    temp.replace(target)
                    result['file'] = target.name
                    result['destinations'] = doc.destination_pages
                    results.append(result)
                    print(json.dumps(result), flush=True)
                finally:
                    temp.unlink(missing_ok=True)
            prefix = f'test-{args.book}-{args.test}-' if args.test else ''
            for report in ['generation_report.json', 'validation_report.json']:
                (output / (prefix + report)).write_text(json.dumps(results, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
