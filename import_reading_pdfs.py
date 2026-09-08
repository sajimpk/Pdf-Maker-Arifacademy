"""Import Reading PDFs into reading_books.db; no network or generated answers."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from reading_store import ROOT, DEFAULT_DB, connect

sys.path.insert(0, str(ROOT / '.packages'))
import pymupdf as fitz

RANGE = re.compile(r'^Questions?\s+(\d+)\s*[-–—]\s*(\d+)$', re.I)
MARK = re.compile(r'\{\{(\d+)\}\}')


def clean(s):
    return re.sub(r'\s+', ' ', s).strip()


def json_text(value):
    return json.dumps(value, ensure_ascii=False)


def read_lines(page):
    lines = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            if not clean(''.join(s['text'] for s in line['spans'])):
                continue
            lines.append({'page': page.number + 1, 'bbox': list(line['bbox']),
                          'spans': [{'text': s['text'], 'font': s['font'], 'size': s['size'],
                                     'bbox': list(s['bbox'])} for s in line['spans']],
                          'text': ''.join(s['text'] for s in line['spans'])})
    return lines


def visual_rows(lines, first=0, last=0):
    """Join fragments on a baseline, retaining bold question numbers as tokens."""
    rows = []
    for line in sorted(lines, key=lambda x: (x['page'], x['bbox'][1], x['bbox'][0])):
        if rows and rows[-1]['page'] == line['page'] and abs(rows[-1]['y'] - line['bbox'][1]) < 4:
            rows[-1]['spans'].extend(line['spans'])
            rows[-1]['bottom'] = max(rows[-1]['bottom'], line['bbox'][3])
        else:
            rows.append({'page': line['page'], 'y': line['bbox'][1], 'bottom': line['bbox'][3],
                         'spans': list(line['spans'])})
    for row in rows:
        pieces = []
        row['spans'].sort(key=lambda x: x['bbox'][0])
        for span in row['spans']:
            value = span['text']
            num = clean(value)
            if num.isdigit() and first <= int(num) <= last and 'Bold' in span['font'] and span['size'] >= 12:
                value = '{{' + num + '}}'
            pieces.append(value)
        row['text'] = clean(' '.join(pieces))
        row['bold'] = all(('Bold' in s['font'] or 'Semibold' in s['font']) for s in row['spans'] if clean(s['text']))
    return rows


def paragraphs(rows, mode='body'):
    result = []
    previous = None
    for row in rows:
        text = row['text']
        if not text:
            continue
        kind = 'heading' if row['bold'] and not MARK.search(text) else 'paragraph'
        option = re.match(r'^([A-K]|[ivx]+)\.\s*(.*)', text)
        if option and mode == 'section':
            kind = 'option'
        new = previous is None or kind != 'paragraph' or result[-1]['kind'] != 'paragraph'
        if previous is not None:
            if row['page'] == previous['page']:
                new |= row['y'] - previous['bottom'] >= 12
            else:
                new |= bool(re.match(r'^[A-Z][.)]\s', text)) or bool(re.search(r'[.!?]$', previous['text']))
        if new:
            result.append({'kind': kind, 'text': text, 'pages': [row['page']]})
        else:
            result[-1]['text'] += ' ' + text
            result[-1]['pages'] = sorted(set(result[-1]['pages'] + [row['page']]))
        previous = row
    return result


def parse_answers(lines):
    answers = {}
    active = None
    answer_x, explanation_x = None, None
    for line in lines:
        text = clean(line['text'])
        x = line['bbox'][0]
        if text == 'Answer':
            answer_x = x
            continue
        if text == 'Explanation':
            explanation_x = x
            continue
        if text in ('Answer Key', '#'):
            continue
        if answer_x is None or explanation_x is None:
            raise ValueError('Answer-key column headers missing')
        if x < answer_x - 5 and text.isdigit():
            active = int(text)
            if active in answers:
                raise ValueError(f'Duplicate answer {active}')
            answers[active] = {'answer': [], 'explanation': [], 'pages': []}
        elif active is not None:
            key = 'answer' if x < explanation_x - 5 else 'explanation'
            answers[active][key].append(text)
            answers[active]['pages'].append(line['page'])
    for data in answers.values():
        for key in ('answer', 'explanation'):
            data[key] = clean(' '.join(data[key]))
        data['pages'] = sorted(set(data['pages']))
    if set(answers) != set(range(1, 41)):
        raise ValueError(f'Expected answers 1-40, got {sorted(answers)}')
    if any(not a['answer'] or not a['explanation'] for a in answers.values()):
        raise ValueError('An answer or source explanation is empty')
    return answers


def question_type(rows):
    intro = ' '.join(r['text'] for r in rows[:7]).lower()
    all_text = ' '.join(r['text'] for r in rows).lower()
    if 'correct heading' in intro:
        return 'matching_headings'
    if 'diagrams' in intro:
        return 'diagram_label'
    if 'choose two' in intro:
        return 'multiple_response'
    if 'choose the correct letter' in intro and 'complete' not in intro:
        return 'multiple_choice'
    if 'following statements agree' in intro or ('not given' in intro and ('yes' in intro or 'true' in intro)):
        return 'yes_no_not_given' if re.search(r'\byes\b', all_text) else 'true_false_not_given'
    if 'correct ending' in intro:
        return 'matching_endings'
    if 'contains the following information' in intro or 'which paragraph contains' in intro:
        return 'matching_information'
    if 'match each' in intro or 'list of people' in intro or 'list of researchers' in intro or 'list of experts' in intro or 'list of timber' in intro:
        return 'matching_features'
    if 'complete' in intro:
        if 'flow-chart' in intro:
            return 'flow_chart'
        if 'list of' in intro or 'list ofphrases' in intro:
            return 'summary_options'
        for word in ['table', 'notes', 'sentences', 'summary']:
            if word in intro:
                return word + '_completion'
    if 'answer the questions' in intro:
        return 'short_answer'
    raise ValueError(f'Unrecognised question type: {intro[:160]}')


def split_instruction_rows(rows, kind):
    if kind in ('multiple_choice', 'multiple_response', 'true_false_not_given', 'yes_no_not_given', 'short_answer', 'matching_information'):
        index = next((i for i, r in enumerate(rows) if MARK.search(r['text'])), len(rows))
        return rows[:index], rows[index:]
    # Instruction sentences end before the task title, option bank or first blank.
    index = 0
    instruction_start = re.compile(r'^(Complete|Choose|Write|In boxes|in boxes|The Reading Passage|Reading Passage|The passage|Look at|Match each|NB\b|Label|Answer the)', re.I)
    while index < len(rows):
        row = rows[index]
        if MARK.search(row['text']):
            break
        if instruction_start.search(row['text']):
            index += 1
            while index < len(rows) and rows[index]['page'] == row['page'] and rows[index]['y'] - row['bottom'] < 12 and not rows[index]['bold']:
                row = rows[index]
                index += 1
        else:
            break
    return rows[:index], rows[index:]


def parse_section(section, passage):
    first, last = section['first'], section['last']
    rows = visual_rows(section['lines'], first, last)
    kind = question_type(rows)
    instructions, body = split_instruction_rows(rows, kind)
    # Web matrix column labels have no content beyond the available letters.
    instructions = [r for r in instructions if not re.fullmatch(r'[A-K](?:\s+[A-K])+', r['text'])]
    body = [r for r in body if not re.fullmatch(r'[A-K](?:\s+[A-K])+', r['text'])]
    nodes = paragraphs(body, 'section')
    if kind in ('summary_completion', 'summary_options', 'notes_completion', 'sentences_completion', 'table_completion'):
        joined = []
        for node in nodes:
            previous = joined[-1] if joined else None
            join_summary = kind in ('summary_completion', 'summary_options') and previous and not re.search(r'[.!?:]$', previous['text'])
            join_blank = MARK.fullmatch(node['text']) and previous
            if previous and previous['kind'] == node['kind'] == 'paragraph' and (join_summary or join_blank):
                previous['text'] += ' ' + node['text']
                previous['pages'] = sorted(set(previous['pages'] + node['pages']))
            else:
                joined.append(node)
        nodes = joined
    questions = []
    options = []
    if kind == 'matching_headings':
        mapping = passage['heading_map']
        for num in range(first, last + 1):
            if num not in mapping:
                raise ValueError(f'No source paragraph label for heading question {num}')
            questions.append({'number': num, 'prompt': 'Paragraph ' + mapping[num], 'pages': section['pages'], 'options': []})
    elif kind in ('multiple_choice', 'multiple_response', 'true_false_not_given', 'yes_no_not_given', 'short_answer', 'matching_information', 'matching_features'):
        # Shared matching options may precede the first numbered question.
        current = None
        current_option = None
        shared = []
        for row in body:
            text = row['text']
            nums = [int(n) for n in MARK.findall(text)]
            if nums:
                if current:
                    questions.extend([{**current, 'number': n} for n in current['numbers']])
                current = {'numbers': nums, 'prompt': clean(MARK.sub('', text)), 'pages': [row['page']], 'options': []}
                current_option = None
            else:
                opt = re.match(r'^([A-K])(?:\.|\s|$)\s*(.*)', text)
                if current and opt and kind in ('multiple_choice', 'multiple_response', 'true_false_not_given', 'yes_no_not_given'):
                    current_option = {'label': opt.group(1), 'text': opt.group(2)}
                    current['options'].append(current_option)
                elif current_option is not None:
                    current_option['text'] = clean(current_option['text'] + ' ' + text)
                elif current:
                    current['prompt'] = clean(current['prompt'] + ' ' + text)
                    current['pages'] = sorted(set(current['pages'] + [row['page']]))
                else:
                    shared.append(row)
        if current:
            questions.extend([{**current, 'number': n} for n in current['numbers']])
        nodes = paragraphs(shared, 'section')
    else:
        for node in nodes:
            for num in map(int, MARK.findall(node['text'])):
                questions.append({'number': num, 'prompt': node['text'], 'pages': node['pages'], 'options': []})
    # Option banks are kept in their own relational records.
    kept = []
    for node in nodes:
        bank = kind in ('matching_headings', 'matching_features', 'matching_endings', 'summary_options')
        opt = re.match(r'^([A-K]|[ivx]+)\.\s*(.*)', node['text']) if bank else None
        plain_opt = re.match(r'^([A-K])\s+(.+)', node['text']) if kind == 'matching_features' else None
        if opt:
            pieces = re.split(r'(?:^|\s)([A-K]|[ivx]+)\.\s*', node['text'])
            options.extend({'label': pieces[i], 'text': clean(pieces[i + 1])} for i in range(1, len(pieces), 2))
        elif plain_opt:
            options.append({'label': plain_opt.group(1), 'text': plain_opt.group(2)})
        elif options and node['kind'] == 'paragraph' and not MARK.search(node['text']):
            options[-1]['text'] += ' ' + node['text']
        else:
            kept.append(node)
    found = [q['number'] for q in questions]
    unique_options = {}
    for option in options:
        if option['label'] in unique_options and unique_options[option['label']]['text'] != option['text']:
            raise ValueError(f"Conflicting option {option['label']} in section {first}-{last}")
        unique_options[option['label']] = option
    options = list(unique_options.values())
    if sorted(found) != list(range(first, last + 1)):
        raise ValueError(f'{kind} {first}-{last}: question markers {found}')
    for q in questions:
        if not q['prompt']:
            if kind == 'diagram_label':
                q['prompt'] = f"Diagram label {{{{{q['number']}}}}}"
            else:
                raise ValueError(f"Empty prompt for {q['number']}")
        if kind in ('multiple_choice', 'multiple_response') and len(q['options']) < 4:
            raise ValueError(f"Missing options for {q['number']}: {q['options']}")
    return {'kind': kind, 'instructions': paragraphs(instructions, 'section'), 'nodes': kept,
            'questions': questions, 'options': options, **section}


def parse_source(source):
    match = re.search(r'(\d+) Academic Reading Test (\d+)', source.stem)
    if not match:
        raise ValueError('Unrecognised filename')
    book, test = map(int, match.groups())
    passages = []
    answer_lines = []
    page_records = []
    mode, current, section = None, None, None
    with fitz.open(source) as doc:
        for page in doc:
            lines = read_lines(page)
            if not lines and page.get_images():
                raise ValueError(f'Page {page.number + 1} has no selectable text; OCR is required')
            page_records.append({'page': page.number + 1, 'text': page.get_text(), 'lines': lines})
            for line in lines:
                text = clean(line['text'])
                if re.match(r'^Cambridge IELTS \d+ Academic Reading Test \d+', text):
                    continue
                pm = re.fullmatch(r'PASSAGE\s+(\d+)', text)
                qm = RANGE.match(text)
                if pm:
                    current = {'number': int(pm.group(1)), 'lines': [], 'sections': [], 'heading_map': {}}
                    passages.append(current)
                    mode = 'passage'
                elif re.match(r'^PART\s+\d+\s*[—–-]\s*QUESTIONS', text):
                    mode = 'questions'
                elif qm:
                    section = {'first': int(qm.group(1)), 'last': int(qm.group(2)), 'lines': [], 'pages': [], 'assets': []}
                    current['sections'].append(section)
                    mode = 'questions'
                elif text == 'Answer Key':
                    mode = 'answers'
                elif mode == 'answers':
                    answer_lines.append(line)
                elif mode == 'passage':
                    current['lines'].append(line)
                elif mode == 'questions' and section is not None:
                    section['lines'].append(line)
                    section['pages'].append(line['page'])
            # Images are actual diagram assets, not page screenshots.
            for info in sorted(page.get_image_info(xrefs=True), key=lambda image: (image['bbox'][1], image['bbox'][0])):
                if not info['xref']:
                    raise ValueError('Inline image without xref needs manual extraction')
                candidates = [s for p in passages for s in p['sections'] if page.number + 1 in s['pages']]
                diagram = next((s for s in candidates if any('diagrams' in l['text'] for l in s['lines'])), None)
                if diagram is None:
                    raise ValueError('Image found outside a recognised diagram section')
                asset = doc.extract_image(info['xref'])
                diagram['assets'].append({'data': asset['image'], 'mime': 'image/' + asset['ext'],
                                          'page': page.number + 1, 'width': asset['width'], 'height': asset['height']})
        answers = parse_answers(answer_lines)
    if [p['number'] for p in passages] != [1, 2, 3]:
        raise ValueError('Expected exactly three passages')
    for passage in passages:
        rows = visual_rows(passage['lines'])
        title_rows = [r for r in rows[:7] if min(s['size'] for s in r['spans']) >= 14]
        if not title_rows:
            # Cambridge 19 uses the body font size for passage titles.
            if rows and len(rows[0]['text']) < 180 and not rows[0]['text'].startswith('You should spend'):
                title_rows = [rows[0]]
            else:
                raise ValueError('Passage title could not be identified by typography')
        passage['title'] = ' '.join(r['text'] for r in title_rows)
        rows = [r for r in rows if r not in title_rows]
        kept = []
        for i, row in enumerate(rows):
            if row['text'].isdigit() and row['bold'] and 1 <= int(row['text']) <= 40:
                next_row = rows[i + 1]['text'] if i + 1 < len(rows) else ''
                label = re.match(r'^([A-H])(?:[.)]|$)', next_row)
                if not label:
                    raise ValueError('Heading number has no paragraph label')
                passage['heading_map'][int(row['text'])] = label.group(1)
                continue
            kept.append(row)
        passage['paragraphs'] = paragraphs(kept)
        passage['pages'] = sorted(set(l['page'] for l in passage['lines']))
        for section in passage['sections']:
            section['pages'] = sorted(set(section['pages']))
        passage['sections'] = [parse_section(s, passage) for s in passage['sections']]
    all_questions = [q for p in passages for s in p['sections'] for q in s['questions']]
    if sorted(q['number'] for q in all_questions) != list(range(1, 41)):
        raise ValueError('Question sections do not cover 1-40 exactly once')
    return {'book': book, 'test': test, 'title': source.stem.split(' (')[0], 'passages': passages,
            'answers': answers, 'pages': page_records}


def save_test(db, source, data):
    with db:
        db.execute('DELETE FROM tests WHERE book_number=? AND test_number=?', (data['book'], data['test']))
        tid = db.execute('INSERT INTO tests(book_number,test_number,title,source_name,source_sha256) VALUES(?,?,?,?,?)',
                         (data['book'], data['test'], data['title'], source.name, hashlib.sha256(source.read_bytes()).hexdigest())).lastrowid
        for page in data['pages']:
            db.execute('INSERT INTO source_pages VALUES(?,?,?,?)', (tid, page['page'], page['text'], json_text(page['lines'])))
        for p in data['passages']:
            pid = db.execute('INSERT INTO passages(test_id,passage_number,title,content,paragraphs_json,source_pages) VALUES(?,?,?,?,?,?)',
                (tid, p['number'], p['title'], '\n\n'.join(n['text'] for n in p['paragraphs']), json_text(p['paragraphs']), json_text(p['pages']))).lastrowid
            for pos, s in enumerate(p['sections']):
                sid = db.execute('INSERT INTO sections(passage_id,position,first_question,last_question,question_type,instructions_json,content_json,source_pages) VALUES(?,?,?,?,?,?,?,?)',
                    (pid, pos, s['first'], s['last'], s['kind'], json_text(s['instructions']), json_text(s['nodes']), json_text(s['pages']))).lastrowid
                for q in s['questions']:
                    qid = db.execute('INSERT INTO questions(test_id,section_id,question_number,prompt,group_key,source_pages) VALUES(?,?,?,?,?,?)',
                        (tid, sid, q['number'], q['prompt'], ','.join(map(str, q.get('numbers', [q['number']]))), json_text(q['pages']))).lastrowid
                    a = data['answers'][q['number']]
                    db.execute('INSERT INTO answers VALUES(?,?,?)', (qid, a['answer'], json_text(a['pages'])))
                    db.execute('INSERT INTO explanations VALUES(?,?,?)', (qid, a['explanation'], json_text(a['pages'])))
                    for oi, option in enumerate(q['options']):
                        db.execute('INSERT INTO options(section_id,question_id,label,text,position) VALUES(?,?,?,?,?)', (sid, qid, option['label'], option['text'], oi))
                for oi, option in enumerate(s['options']):
                    db.execute('INSERT INTO options(section_id,question_id,label,text,position) VALUES(?,NULL,?,?,?)', (sid, option['label'], option['text'], oi))
                for ai, asset in enumerate(s['assets']):
                    db.execute('INSERT INTO assets(section_id,position,mime_type,data,source_page,width,height) VALUES(?,?,?,?,?,?,?)',
                        (sid, ai, asset['mime'], asset['data'], asset['page'], asset['width'], asset['height']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'Reading')
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
                result = {'source': source.name, 'status': 'ok', 'passages': 3,
                          'sections': sum(len(p['sections']) for p in data['passages']), 'questions': 40, 'answers': 40, 'explanations': 40}
            except Exception as exc:
                result = {'source': source.name, 'status': 'error', 'error': str(exc)}
            report.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
    args.db.with_suffix('.import.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return int(any(r['status'] != 'ok' for r in report))


if __name__ == '__main__':
    sys.exit(main())
