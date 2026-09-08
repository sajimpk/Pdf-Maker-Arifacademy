"""Typeset Listening books from SQLite. No audio URLs or QR codes are included."""
import argparse
import io
import json
from pathlib import Path
import re
from xml.sax.saxutils import escape
from listening_store import ROOT, DEFAULT_DB, connect
from build_reading_books import (BookDoc, Cover, Hairline, FlowArrow, register_fonts, styles, markup,
    heading, option_bank, question_section, WIDTH, INK, GREEN, MUTED, PALE, RULE,
    ParagraphStyle, Paragraph, Spacer, PageBreak, KeepTogether, CondPageBreak, Table,
    TableStyle, Image, TableOfContents)


def get_tests(db, book, test=None):
    query = 'SELECT * FROM tests WHERE book_number=?'
    args = [book]
    if test is not None:
        query += ' AND test_number=?'
        args.append(test)
    tests = []
    for row in db.execute(query + ' ORDER BY test_number', args):
        t = dict(row)
        t['parts'] = []
        for row in db.execute('SELECT * FROM parts WHERE test_id=? ORDER BY part_number', (t['id'],)):
            part = dict(row)
            transcript = db.execute('SELECT * FROM transcripts WHERE part_id=?', (part['id'],)).fetchone()
            if not transcript or not transcript['content']:
                raise ValueError('Missing transcript')
            part['transcript'] = transcript['content']
            part['sections'] = []
            for row in db.execute('SELECT * FROM sections WHERE part_id=? ORDER BY position', (part['id'],)):
                s = dict(row)
                s['instructions'] = json.loads(s['instructions_json'])
                s['nodes'] = json.loads(s['content_json'])
                s['questions'] = []
                for row in db.execute('SELECT * FROM questions WHERE section_id=? ORDER BY question_number', (s['id'],)):
                    q = dict(row)
                    q['options'] = [dict(o) for o in db.execute('SELECT * FROM options WHERE question_id=? ORDER BY position', (q['id'],))]
                    q['answer'] = db.execute('SELECT answer FROM answers WHERE question_id=?', (q['id'],)).fetchone()[0]
                    q['explanation'] = db.execute('SELECT text FROM explanations WHERE question_id=?', (q['id'],)).fetchone()[0]
                    s['questions'].append(q)
                s['options'] = [dict(o) for o in db.execute('SELECT * FROM options WHERE section_id=? AND question_id IS NULL ORDER BY position', (s['id'],))]
                s['assets'] = [dict(a) for a in db.execute('SELECT * FROM assets WHERE section_id=? ORDER BY position', (s['id'],))]
                part['sections'].append(s)
            t['parts'].append(part)
        qs = [q['question_number'] for p in t['parts'] for s in p['sections'] for q in s['questions']]
        if [p['part_number'] for p in t['parts']] != [1, 2, 3, 4] or qs != list(range(1, 41)):
            raise ValueError(f"Incomplete test {t['test_number']}")
        tests.append(t)
    if not tests:
        raise ValueError('No matching tests')
    return tests


def listening_styles():
    st = styles()
    st['cell'] = ParagraphStyle('cell', parent=st['question'], fontSize=9.5, leading=13.5, spaceAfter=0)
    st['transcript'] = ParagraphStyle('transcript', parent=st['body'], fontSize=9.5, leading=14.2, spaceAfter=7, alignment=0)
    return st


def native_table(node, st):
    rows = node['rows']
    count = len(rows[0])
    if any(len(row) != count for row in rows):
        raise ValueError('Table column count changed')
    data = [[Paragraph(markup(text).replace('________________', '_________'), st['cell']) for text in row] for row in rows]
    header_rows = 0 if any('{{' in text for text in rows[0]) else 1
    table = Table(data, colWidths=[WIDTH / count] * count, repeatRows=header_rows, hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), .45, RULE), ('BACKGROUND', (0, 0), (-1, 0), PALE),
        ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8)]))
    return table


def section_story(s, st):
    kind = s['question_type']
    if kind in ('multiple_choice', 'multiple_response'):
        return question_section(s, st)
    rule = Hairline()
    rule.keepWithNext = True
    gap = Spacer(1, 8)
    gap.keepWithNext = True
    story = [CondPageBreak(650 if kind == 'flow_chart' else 140), Paragraph(f"Questions {s['first_question']}–{s['last_question']}", st['section']), rule]
    story.extend(Paragraph(markup(n['text']), st['instruction']) for n in s['instructions'])
    story.append(gap)
    if kind == 'map_label':
        if not s['assets']:
            raise ValueError('Map section is missing its image')
        for node in s['nodes']:
            if not re.search(r'\{\{\d+\}\}', node.get('text', '')):
                story.append(Paragraph(markup(node['text']), st['subhead']))
        for asset in s['assets']:
            scale = min((WIDTH - 12) / asset['width'], 315 / asset['height'])
            picture = Image(io.BytesIO(asset['data']), width=asset['width'] * scale, height=asset['height'] * scale)
            picture.hAlign = 'CENTER'
            story.extend([picture, Spacer(1, 12)])
        for q in s['questions']:
            text = re.sub(r'\{\{\d+\}\}', '', q['prompt']).strip(' •')
            story.append(Paragraph(f'<b>{q["question_number"]}</b>  {markup(text)}  __________', st['question']))
        return story
    if kind == 'matching_features':
        unnumbered = [n for n in s['nodes'] if not re.search(r'\{\{\d+\}\}', n.get('text', ''))]
        if unnumbered:
            story.append(Paragraph(markup(unnumbered[0]['text']), st['subhead']))
        story.extend(option_bank(s['options'], st))
        for n in unnumbered[1:]:
            story.append(Paragraph(markup(n['text']), st['subhead'] if n['kind'] == 'heading' else st['question']))
        for q in s['questions']:
            text = re.sub(r'\{\{\d+\}\}', '', q['prompt']).strip(' •')
            story.append(KeepTogether([Paragraph(f'<b>{q["question_number"]}</b>  {markup(text)}', st['question']),
                Paragraph('Answer: ____________________', st['small'])]))
        return story
    if kind == 'flow_chart':
        steps, current = [], []
        for n in s['nodes']:
            text = n['text']
            if n['kind'] == 'heading' and not current and not steps:
                story.append(Paragraph(markup(text), st['subhead']))
                continue
            pieces = re.split(r'[↓⭣⬇]', text)
            for i, piece in enumerate(pieces):
                if i and current:
                    steps.append(' '.join(current))
                    current = []
                if piece.strip():
                    current.append(piece.strip())
        if current:
            steps.append(' '.join(current))
        for i, text in enumerate(steps):
            if i:
                story.append(FlowArrow())
            box = Table([[Paragraph(markup(text), st['question'])]], colWidths=[WIDTH - 32], hAlign='CENTER')
            box.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PALE), ('BOX', (0, 0), (-1, -1), .5, RULE),
                ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
            story.append(box)
        story.extend([Spacer(1, 12)] + option_bank(s['options'], st))
        return story
    for node in s['nodes']:
        if node['kind'] == 'table':
            story.extend([native_table(node, st), Spacer(1, 12)])
        else:
            story.append(Paragraph(markup(node['text']), st['subhead'] if node['kind'] == 'heading' else st['question']))
    return story


def build_story(tests, book, st):
    single = tests[0]['test_number'] if len(tests) == 1 else None
    story = [Cover(book, len(tests), single, subject='Listening'), PageBreak(),
             heading('Contents', st['title'], 'contents', in_contents=False)]
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle('toc0', fontName='Sans-Bold', fontSize=10.5, leading=15, spaceBefore=6, textColor=GREEN),
                       ParagraphStyle('toc1', fontName='Sans', fontSize=9.5, leading=13, leftIndent=14, textColor=INK)]
    toc.dotsMinLevel = 0
    story.extend([toc, PageBreak(), heading('Before you begin', st['title'], 'instructions', in_contents=False)])
    story.append(Paragraph('Each practice test contains four Listening parts and 40 questions. Use this booklet alongside the corresponding recording for your test.', st['body']))
    for title, text in [
        ('Read ahead', 'Read the instructions and questions for each part before listening. Pay attention to word limits, names, dates and numbers.'),
        ('Record your answers', 'Write in the spaces provided or use the answer sheet after each test. For matching and map tasks, write the requested letter.'),
        ('Review after the test', 'Check the answer key after completing all four parts. Read the explanations, then use the transcript to revisit anything you missed.')]:
        story.extend([Paragraph(title, st['section']), Paragraph(text, st['body'])])
    story.extend([Spacer(1, 25), Paragraph('Typeset by Arif Academy from the supplied Listening material. Question wording, answers and transcripts follow the source documents.', st['small'])])
    for t in tests:
        tn = t['test_number']
        story.extend([PageBreak(), heading(f'Test {tn}', st['title'], f'test-{tn}', running=f'TEST {tn}'),
                      Paragraph('4 PARTS  /  40 QUESTIONS', st['eyebrow'])])
        for index, part in enumerate(t['parts']):
            pn = part['part_number']
            if index:
                story.append(PageBreak())
            label = f'Part {pn}'
            story.append(heading(label, st['title'], f'test-{tn}-part-{pn}', 1))
            for s in part['sections']:
                story.extend(section_story(s, st))
        story.extend([PageBreak(), Paragraph(f'Test {tn} · Answer sheet', st['title']),
            Paragraph('Candidate name: __________________________________     Date: __________________', st['small']), Spacer(1, 15)])
        rows = [[Paragraph(f'<b>{n}</b>   __________________________________', st['question']),
                 Paragraph(f'<b>{n + 20}</b>   __________________________________', st['question'])] for n in range(1, 21)]
        sheet = Table(rows, colWidths=[WIDTH / 2] * 2)
        sheet.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        story.append(sheet)
    story.extend([PageBreak(), heading('Answers & explanations', st['title'], 'answers', running='ANSWERS & EXPLANATIONS'),
        Paragraph('Check these answers after completing each test. Explanations reproduce the supporting text supplied with the source material.', st['body'])])
    for index, t in enumerate(tests):
        tn = t['test_number']
        if index:
            story.append(PageBreak())
        story.append(heading(f'Test {tn} · Answer key', st['section'], f'answers-{tn}', 1))
        for part in t['parts']:
            story.extend([CondPageBreak(110), Paragraph(f'Part {part["part_number"]}', st['subhead'])])
            for s in part['sections']:
                for q in s['questions']:
                    story.append(KeepTogether([Paragraph(f'{q["question_number"]}  {markup(q["answer"])}', st['answer']),
                        Paragraph(markup(q['explanation']), st['explanation']), Hairline()]))
    story.extend([PageBreak(), heading('Transcripts', st['title'], 'transcripts', running='TRANSCRIPTS'),
        Paragraph('Use these transcripts to review the conversations and talks after completing the questions.', st['body'])])
    for index, t in enumerate(tests):
        tn = t['test_number']
        if index:
            story.append(PageBreak())
        story.append(heading(f'Test {tn} · Transcript', st['section'], f'transcript-{tn}', 1))
        for part in t['parts']:
            pn = part['part_number']
            story.extend([CondPageBreak(110), heading(f'Part {pn}', st['subhead'], f'transcript-{tn}-{pn}', 2, in_contents=False)])
            for text in part['transcript'].split('\n\n'):
                if re.fullmatch(r'[-–—_ ]{3,}', text):
                    story.extend([Spacer(1, 3), Hairline(), Spacer(1, 3)])
                else:
                    formatted = markup(text)
                    formatted = re.sub(r'^([A-Z][A-Z .’\'-]{1,25}:?)\s*(?=[A-Z][a-z]|I\b)', r'<b>\1</b> ', formatted)
                    story.append(Paragraph(formatted, st['transcript']))
    return story


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=ROOT / 'Listening_Books')
    parser.add_argument('--book', type=int)
    parser.add_argument('--test', type=int)
    parser.add_argument('--font-dir', type=Path)
    args = parser.parse_args()
    if args.test and not args.book:
        parser.error('--test requires --book')
    register_fonts(args.font_dir)
    st = listening_styles()
    args.output.mkdir(parents=True, exist_ok=True)
    report = []
    with connect(args.db, readonly=True) as db:
        books = [args.book] if args.book else [r[0] for r in db.execute('SELECT DISTINCT book_number FROM tests ORDER BY book_number')]
        for book in books:
            tests = get_tests(db, book, args.test)
            suffix = f' Test {args.test}' if args.test else ' Practice Book'
            target = args.output / f'Cambridge IELTS {book} Academic Listening{suffix}.pdf'
            temp = target.with_suffix('.tmp.pdf')
            try:
                doc = BookDoc(temp, book, subject='Listening')
                doc.multiBuild(build_story(tests, book, st))
                temp.replace(target)
                result = {'file': target.name, 'book': book, 'tests': len(tests), 'pages': doc.page,
                          'questions': len(tests) * 40, 'destinations': doc.destination_pages}
                report.append(result)
                print(json.dumps(result), flush=True)
            finally:
                temp.unlink(missing_ok=True)
    filename = 'generation_report.json' if args.test is None else f'test-{args.book}-{args.test}-report.json'
    (args.output / filename).write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
