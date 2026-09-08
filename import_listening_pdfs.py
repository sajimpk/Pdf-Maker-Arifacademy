"""Import local Listening PDFs into a source-traceable, structured database."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from listening_store import ROOT, DEFAULT_DB, connect
from import_reading_pdfs import fitz, read_lines, visual_rows, paragraphs, parse_answers, clean, json_text, MARK, RANGE


def identify(rows):
    intro = ' '.join(r['text'] for r in rows[:5]).lower()
    if intro.startswith('choose two'):
        return 'multiple_response'
    if intro.startswith('choose the correct letter'):
        return 'multiple_choice'
    if intro.startswith('label the map'):
        return 'map_label'
    if intro.startswith(('what ', 'which ', 'where ')):
        return 'matching_features'
    if intro.startswith('complete'):
        for word in ('notes', 'table', 'form', 'flowchart', 'flow-chart'):
            if word in intro:
                return 'flow_chart' if 'flow' in word else word + '_completion'
    raise ValueError('Unrecognised task: ' + intro[:140])


def task_paragraphs(rows):
    """Keep separate numbered note entries apart even when source lines are tight."""
    result, batch = [], []
    for row in rows:
        prior_mark = any(MARK.search(r['text']) for r in batch)
        boundary = (MARK.match(row['text']) and prior_mark) or re.match(r'^(?:[•–]\s|must\b)', row['text']) or row['bold']
        if boundary and batch:
            result.extend(paragraphs(batch, 'section'))
            batch = []
        batch.append(row)
    result.extend(paragraphs(batch, 'section'))
    return result


def extract_table_rows(section, tables):
    """Read cells independently so parallel columns never become one sentence."""
    extracted, used = [], set()
    for table in tables:
        for row in table['rows']:
            cells = row['cells']
            real = [c for c in cells if c]
            if len(real) < 2:
                continue  # Ignore full-page frames and web UI containers.
            cell_texts, cell_ids = [], set()
            for cell in cells:
                chosen = []
                if cell:
                    for i, line in enumerate(section['lines']):
                        if line['page'] != table['page']:
                            continue
                        x0, y0, x1, y1 = line['bbox']
                        if cell[0] - 1 <= (x0 + x1) / 2 <= cell[2] + 1 and cell[1] - 1 <= (y0 + y1) / 2 <= cell[3] + 1:
                            chosen.append(line)
                            cell_ids.add(i)
                cell_texts.append(' '.join(r['text'] for r in visual_rows(chosen, section['first'], section['last'])))
            if sum(bool(s) for s in cell_texts) >= 2:
                extracted.append({'cells': cell_texts, 'page': table['page'], 'y': min(c[1] for c in real)})
                used.update(cell_ids)
    return extracted, used


def parse_section(section, tables):
    rows = visual_rows(section['lines'], section['first'], section['last'])
    kind = identify(rows)
    # Matching tasks can put their option bank either before or after the questions.
    index = 1
    while index < len(rows):
        r, prev = rows[index], rows[index - 1]
        if MARK.search(r['text']):
            break
        instruction = re.match(r'^(Write|Choose|Drag|NB\b)', r['text'], re.I)
        continuation = r['page'] == prev['page'] and r['y'] - prev['bottom'] < 12 and not MARK.search(r['text']) and not r['bold']
        if instruction or (continuation and not re.match(r'^[A-K][.)]', r['text'])):
            index += 1
        else:
            break
    intro, body = rows[:index], rows[index:]
    # Explicit web-only drag instructions become print instructions.
    instructions = paragraphs(intro, 'section')
    for node in instructions:
        node['text'] = node['text'].replace('Drag the correct letter', 'Write the correct letter')
    body = [r for r in body if not re.fullmatch(r'[A-K](?:\s+[A-K])+', r['text'])]
    questions, options = [], []
    nodes = []
    if kind in ('multiple_choice', 'multiple_response'):
        current, option = None, None
        for row in body:
            text = row['text']
            numbers = list(map(int, MARK.findall(text)))
            if numbers:
                if current:
                    questions.extend(dict(current, number=n) for n in current['numbers'])
                current = {'numbers': numbers, 'prompt': clean(MARK.sub('', text)), 'pages': [row['page']], 'options': []}
                option = None
            else:
                match = re.match(r'^([A-E])(?:[.)]|\s|$)\s*(.*)', text)
                if match and current:
                    option = {'label': match[1], 'text': match[2]}
                    current['options'].append(option)
                elif option is not None:
                    option['text'] = clean(option['text'] + ' ' + text)
                elif current:
                    current['prompt'] += ' ' + text
                else:
                    nodes.append({'kind': 'heading' if row['bold'] else 'paragraph', 'text': text, 'pages': [row['page']]})
        if current:
            questions.extend(dict(current, number=n) for n in current['numbers'])
        for q in questions:
            expected = list('ABCDE') if kind == 'multiple_response' else list('ABC')
            if [o['label'] for o in q['options']] != expected or any(not o['text'] for o in q['options']):
                raise ValueError(f"Incomplete options for question {q['number']}")
    else:
        table_rows, used = extract_table_rows(section, tables) if 'completion' in kind else ([], set())
        if used:
            remaining = [l for i, l in enumerate(section['lines']) if i not in used]
            first_y = (table_rows[0]['page'], table_rows[0]['y'])
            # Exclude instruction lines and keep shared titles outside the table.
            body_keys = {(r['page'], r['y']) for r in body}
            remaining_rows = [r for r in visual_rows(remaining, section['first'], section['last']) if (r['page'], r['y']) in body_keys]
            before = [r for r in remaining_rows if (r['page'], r['y']) < first_y]
            after = [r for r in remaining_rows if (r['page'], r['y']) >= first_y]
            nodes = paragraphs(before, 'section')
            nodes.append({'kind': 'table', 'rows': [r['cells'] for r in table_rows], 'pages': sorted({r['page'] for r in table_rows})})
            nodes.extend(paragraphs(after, 'section'))
        else:
            nodes = task_paragraphs(body) if kind in ('notes_completion', 'form_completion') else paragraphs(body, 'section')
        kept = []
        # Same-baseline option banks may contain several labels in one row.
        for node in nodes:
            text = node.get('text', '')
            if kind in ('matching_features', 'flow_chart') and re.match(r'^([A-K])[.)]\s*', text):
                pieces = re.split(r'(?:^|\s)([A-K])[.)]\s*', text)
                options.extend({'label': pieces[i], 'text': clean(pieces[i + 1])} for i in range(1, len(pieces), 2))
            elif kind in ('matching_features', 'flow_chart') and options and not MARK.search(text) and node['kind'] == 'paragraph' and not text.startswith('•'):
                options[-1]['text'] += ' ' + text
            else:
                kept.append(node)
        nodes = kept
        # Question numbers ending a line may be placed on a separate source baseline.
        joined = []
        for node in nodes:
            if joined and node.get('text') and MARK.fullmatch(node['text']) and joined[-1]['kind'] == 'paragraph' and not MARK.search(joined[-1]['text']):
                joined[-1]['text'] += ' ' + node['text']
                joined[-1]['pages'] = sorted(set(joined[-1]['pages'] + node['pages']))
            else:
                joined.append(node)
        nodes = joined
        for node in nodes:
            texts = [' | '.join(row) for row in node['rows']] if node['kind'] == 'table' else [node['text']]
            if kind == 'map_label':
                texts = [piece for text in texts for piece in re.findall(r'\{\{\d+\}\}.*?(?=\{\{\d+\}\}|$)', text)]
            elif kind == 'matching_features':
                texts = [piece for text in texts for piece in re.findall(r'.*?\{\{\d+\}\}', text)]
            for text in texts:
                for n in map(int, MARK.findall(text)):
                    questions.append({'number': n, 'prompt': text.strip(), 'pages': node['pages'], 'options': []})
        if kind == 'matching_features':
            if len(options) < 3 or any(not o['text'] for o in options):
                raise ValueError(f"No complete option bank for {section['first']}-{section['last']}")
    found = sorted(q['number'] for q in questions)
    if found != list(range(section['first'], section['last'] + 1)):
        raise ValueError(f"{kind} {section['first']}-{section['last']}: found question numbers {found}")
    return {**section, 'kind': kind, 'instructions': instructions, 'nodes': nodes, 'questions': questions, 'options': options}


def transcript_segments(lines):
    rows = visual_rows(lines)
    result = []
    previous = None
    for row in rows:
        text = row['text']
        speaker = re.match(r'^([A-Z][A-Z .’\'-]{1,25})(?::\s*|\s+)(?=[A-Za-z])', text)
        divider = bool(re.fullmatch(r'[-–—_ ]{3,}', text))
        gap = previous and row['page'] == previous['page'] and row['y'] - previous['bottom'] >= 10
        if not result or speaker or divider or gap or result[-1]['kind'] == 'divider':
            result.append({'kind': 'divider' if divider else 'speech' if speaker else 'paragraph',
                           'text': text, 'speaker': speaker[1].strip(' :') if speaker else '', 'pages': [row['page']]})
        else:
            result[-1]['text'] += ' ' + text
            result[-1]['pages'] = sorted(set(result[-1]['pages'] + [row['page']]))
        previous = row
    return result


def parse_source(source):
    match = re.search(r'(\d+) Academic Listening Test (\d+)', source.stem)
    if not match:
        raise ValueError('Unrecognised filename')
    book, test = map(int, match.groups())
    parts, page_records, answers, tables = [], [], [], []
    mode, part, section, transcript_part = None, None, None, None
    with fitz.open(source) as doc:
        for page in doc:
            lines = read_lines(page)
            retained_lines = []
            if mode not in ('transcripts', 'answers'):
                for table in page.find_tables().tables:
                    tables.append({'page': page.number + 1, 'rows': [{'cells': row.cells} for row in table.rows]})
            for line in lines:
                text = clean(line['text'])
                pm = re.fullmatch(r'PART\s+(\d+)\s*[—–-]\s*QUESTIONS', text)
                qm = RANGE.match(text)
                if re.match(r'^Cambridge IELTS \d+ Academic Listening Test', text):
                    continue
                if pm:
                    part = {'number': int(pm[1]), 'sections': [], 'transcript_lines': [], 'pages': []}
                    parts.append(part)
                    mode = 'audio'
                elif text == 'Transcripts':
                    mode = 'transcripts'
                elif text == 'Answer Key':
                    mode = 'answers'
                elif mode == 'transcripts':
                    tm = re.fullmatch(r'Part\s+(\d+)', text)
                    if tm:
                        transcript_part = parts[int(tm[1]) - 1]
                    elif transcript_part is not None:
                        transcript_part['transcript_lines'].append(line)
                elif mode == 'answers':
                    answers.append(line)
                elif qm:
                    section = {'first': int(qm[1]), 'last': int(qm[2]), 'lines': [], 'pages': [], 'assets': []}
                    part['sections'].append(section)
                    mode = 'questions'
                elif mode == 'audio':
                    continue
                elif mode == 'questions':
                    section['lines'].append(line)
                    section['pages'].append(line['page'])
                    part['pages'].append(line['page'])
                retained_lines.append(line)
            page_records.append({'page': page.number + 1, 'text': '\n'.join(l['text'] for l in retained_lines), 'lines': retained_lines})
            for image in sorted(page.get_image_info(xrefs=True), key=lambda v: (v['bbox'][1], v['bbox'][0])):
                candidates = [s for p in parts for s in p['sections'] if page.number + 1 in s['pages']]
                owner = next((s for s in candidates if any('map below' in l['text'].lower() for l in s['lines'])), None)
                if owner is None:
                    raise ValueError('Unassigned image on page ' + str(page.number + 1))
                data = doc.extract_image(image['xref'])
                owner['assets'].append({'data': data['image'], 'mime': 'image/' + data['ext'], 'page': page.number + 1,
                                        'width': data['width'], 'height': data['height']})
    if [p['number'] for p in parts] != [1, 2, 3, 4]:
        raise ValueError('Expected four Listening parts')
    for part in parts:
        part['sections'] = [parse_section(s, tables) for s in part['sections']]
        part['pages'] = sorted(set(part['pages']))
        for s in part['sections']:
            s['pages'] = sorted(set(s['pages']))
        numbers = sorted(q['number'] for s in part['sections'] for q in s['questions'])
        if numbers != list(range((part['number'] - 1) * 10 + 1, part['number'] * 10 + 1)):
            raise ValueError('Part does not have its ten questions')
        headings = [n['text'] for s in part['sections'] for n in s['nodes'] if n['kind'] == 'heading']
        part['title'] = headings[0] if headings else f'Part {part["number"]}'
        part['segments'] = transcript_segments(part['transcript_lines'])
        if sum(len(n['text'].split()) for n in part['segments']) < 100:
            raise ValueError('Missing or incomplete transcript')
    return {'book': book, 'test': test, 'title': source.stem.split(' (')[0], 'parts': parts,
            'answers': parse_answers(answers), 'pages': page_records}


def save_test(db, source, data):
    with db:
        db.execute('DELETE FROM tests WHERE book_number=? AND test_number=?', (data['book'], data['test']))
        tid = db.execute('INSERT INTO tests(book_number,test_number,title,source_name,source_sha256) VALUES(?,?,?,?,?)',
            (data['book'], data['test'], data['title'], source.name, hashlib.sha256(source.read_bytes()).hexdigest())).lastrowid
        for page in data['pages']:
            db.execute('INSERT INTO source_pages VALUES(?,?,?,?)', (tid, page['page'], page['text'], json_text(page['lines'])))
        for p in data['parts']:
            pid = db.execute('INSERT INTO parts(test_id,part_number,title,source_pages) VALUES(?,?,?,?)',
                (tid, p['number'], p['title'], json_text(p['pages']))).lastrowid
            db.execute('INSERT INTO transcripts VALUES(?,?,?,?)', (pid, '\n\n'.join(n['text'] for n in p['segments']),
                json_text(p['segments']), json_text(sorted({l['page'] for l in p['transcript_lines']}))))
            for pos, s in enumerate(p['sections']):
                sid = db.execute('INSERT INTO sections(part_id,position,first_question,last_question,question_type,instructions_json,content_json,source_pages) VALUES(?,?,?,?,?,?,?,?)',
                    (pid, pos, s['first'], s['last'], s['kind'], json_text(s['instructions']), json_text(s['nodes']), json_text(s['pages']))).lastrowid
                for q in s['questions']:
                    qid = db.execute('INSERT INTO questions(test_id,section_id,question_number,prompt,group_key,source_pages) VALUES(?,?,?,?,?,?)',
                        (tid, sid, q['number'], q['prompt'], ','.join(map(str, q.get('numbers', [q['number']]))), json_text(q['pages']))).lastrowid
                    answer = data['answers'][q['number']]
                    db.execute('INSERT INTO answers VALUES(?,?,?)', (qid, answer['answer'], json_text(answer['pages'])))
                    db.execute('INSERT INTO explanations VALUES(?,?,?)', (qid, answer['explanation'], json_text(answer['pages'])))
                    for oi, opt in enumerate(q['options']):
                        db.execute('INSERT INTO options(section_id,question_id,label,text,position) VALUES(?,?,?,?,?)', (sid, qid, opt['label'], opt['text'], oi))
                for oi, opt in enumerate(s['options']):
                    db.execute('INSERT INTO options(section_id,question_id,label,text,position) VALUES(?,NULL,?,?,?)', (sid, opt['label'], opt['text'], oi))
                for ai, asset in enumerate(s['assets']):
                    db.execute('INSERT INTO assets(section_id,position,mime_type,data,source_page,width,height) VALUES(?,?,?,?,?,?,?)',
                        (sid, ai, asset['mime'], asset['data'], asset['page'], asset['width'], asset['height']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'Listening')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--pattern', default='*.pdf')
    args = parser.parse_args()
    files = sorted(args.input.glob(args.pattern))
    if not files:
        parser.error('No matching PDF files')
    report = []
    with connect(args.db) as db:
        for source in files:
            try:
                data = parse_source(source)
                save_test(db, source, data)
                result = {'source': source.name, 'status': 'ok', 'parts': 4, 'questions': 40, 'transcripts': 4}
            except Exception as exc:
                result = {'source': source.name, 'status': 'error', 'error': str(exc)}
            report.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
    args.db.with_suffix('.import.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return int(any(r['status'] != 'ok' for r in report))


if __name__ == '__main__':
    sys.exit(main())
