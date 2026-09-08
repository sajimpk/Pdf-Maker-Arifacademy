"""Typeset real books from SQLite only: python build_reading_books.py"""
from pathlib import Path
import argparse
import io
import json
import re
import sys
from xml.sax.saxutils import escape
from reading_store import ROOT, DEFAULT_DB, connect

sys.path.insert(0, str(ROOT / '.packages'))
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    PageBreak, KeepTogether, Table, TableStyle, Image, Flowable, CondPageBreak)
from reportlab.platypus.tableofcontents import TableOfContents

W, H = 595.276, 841.89
LEFT, RIGHT = 61, 55
WIDTH = W - LEFT - RIGHT
INK = colors.HexColor('#24312F')
GREEN = colors.HexColor('#294D43')
MUTED = colors.HexColor('#69736E')
GOLD = colors.HexColor('#B29864')
RULE = colors.HexColor('#C7CFCA')
PALE = colors.HexColor('#F2F5F1')


def register_fonts(font_dir=None):
    directory = Path(font_dir) if font_dir else Path('C:/Windows/Fonts')
    files = {'Book': 'georgia.ttf', 'Book-Bold': 'georgiab.ttf', 'Book-Italic': 'georgiai.ttf',
             'Book-BoldItalic': 'georgiaz.ttf', 'Sans': 'calibri.ttf', 'Sans-Bold': 'calibrib.ttf',
             'Sans-Italic': 'calibrii.ttf', 'Sans-BoldItalic': 'calibriz.ttf'}
    for name, filename in files.items():
        path = directory / filename
        if not path.exists():
            raise ValueError(f'Missing font {path}. Supply --font-dir with Georgia and Calibri font files.')
        pdfmetrics.registerFont(TTFont(name, str(path)))
    for family in ['Book', 'Sans']:
        pdfmetrics.registerFontFamily(family, normal=family, bold=family + '-Bold', italic=family + '-Italic', boldItalic=family + '-BoldItalic')


def styles():
    base = dict(fontName='Book', fontSize=10.5, leading=16, textColor=INK, spaceAfter=9,
                allowWidows=0, allowOrphans=0, splitLongWords=False)
    def style(name, **kwargs):
        return ParagraphStyle(name, **(base | kwargs))
    return {
        'body': style('body', alignment=4),
        'question': style('question', fontName='Sans', fontSize=11, leading=16, spaceAfter=7),
        'option': style('option', fontName='Sans', fontSize=10.5, leading=14.5, leftIndent=22, firstLineIndent=-15, spaceAfter=4),
        'instruction': style('instruction', fontName='Sans', fontSize=10, leading=14.5, spaceAfter=4, textColor=MUTED, keepWithNext=True),
        'title': style('title', fontSize=25, leading=31, spaceAfter=18, textColor=GREEN, keepWithNext=True),
        'section': style('section', fontName='Sans-Bold', fontSize=14, leading=19, spaceBefore=17, spaceAfter=9, keepWithNext=True),
        'subhead': style('subhead', fontName='Sans-Bold', fontSize=11, leading=15, spaceBefore=9, spaceAfter=7, keepWithNext=True),
        'eyebrow': style('eyebrow', fontName='Sans-Bold', fontSize=9, leading=13, textColor=GREEN, spaceAfter=12, keepWithNext=True),
        'small': style('small', fontName='Sans', fontSize=9, leading=13, textColor=MUTED, spaceAfter=6),
        'answer': style('answer', fontName='Sans-Bold', fontSize=10.5, leading=14.5, textColor=GREEN, spaceAfter=4),
        'explanation': style('explanation', fontSize=9.5, leading=14.5, spaceAfter=8),
    }


def markup(text):
    # Escape all database text before introducing only our own markup.
    value = escape(text)
    value = re.sub(r'\{\{(\d+)\}\}', lambda m: '<b>' + m[1] + '</b>\u00a0________________', value)
    value = re.sub(r'\s+([,.;:!?])', r'\1', value)
    return value


class Hairline(Flowable):
    def __init__(self, width=WIDTH, color=RULE):
        super().__init__()
        self.width, self.height, self.color = width, 9, color
    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(.5)
        self.canv.line(0, 5, self.width, 5)


class Cover(Flowable):
    def __init__(self, book, count, test=None, subject='Reading'):
        super().__init__()
        self.book, self.count, self.test = book, count, test
        self.subject = subject
        self.width, self.height = WIDTH, 695
    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(GREEN)
        c.rect(-LEFT, -90, W, 900, stroke=0, fill=1)
        c.setStrokeColor(GOLD)
        c.setLineWidth(.7)
        c.rect(-27, -20, WIDTH + 54, 733, stroke=1, fill=0)
        c.setFillColor(colors.HexColor('#D7DFD6'))
        c.setFont('Sans-Bold', 10)
        c.drawString(12, 659, 'A R I F   A C A D E M Y')
        c.setFillColor(colors.HexColor('#FAF7EE'))
        c.setFont('Book', 17)
        c.drawString(12, 552, 'Cambridge IELTS')
        c.setFont('Book', 104)
        c.drawString(6, 437, str(self.book))
        c.setStrokeColor(GOLD)
        c.line(12, 399, 94, 399)
        c.setFont('Book', 39)
        c.drawString(12, 337, 'Academic')
        c.drawString(12, 282, self.subject)
        c.setFillColor(colors.HexColor('#D7DFD6'))
        c.setFont('Sans', 13)
        subtitle = f'Practice Test {self.test}' if self.test else 'Four complete practice tests'
        c.drawString(12, 221, subtitle)
        c.setFont('Sans', 11)
        detail = {'Reading': 'Passages · Questions · Answers & explanations',
                  'Listening': 'Questions · Transcripts · Answers & explanations',
                  'Writing': 'Tasks · Charts · Writing practice',
                  'Speaking': 'Questions · Cue cards · Discussion'}.get(self.subject, 'Practice collection')
        c.drawString(12, 96, detail)
        c.setFont('Sans-Bold', 9)
        c.drawString(12, 41, self.subject.upper() + ' PRACTICE COLLECTION')
        c.restoreState()


class FlowArrow(Flowable):
    def __init__(self):
        super().__init__()
        self.width, self.height = WIDTH, 20
        self.keepWithNext = True
    def draw(self):
        c = self.canv
        c.setStrokeColor(GREEN)
        c.setLineWidth(.8)
        x = WIDTH / 2
        c.line(x, 18, x, 3)
        c.line(x, 3, x - 3, 7)
        c.line(x, 3, x + 3, 7)


class BookDoc(BaseDocTemplate):
    def __init__(self, path, book, subject='Reading', **kwargs):
        super().__init__(str(path), pagesize=(W, H), leftMargin=LEFT, rightMargin=RIGHT,
                         topMargin=61, bottomMargin=53, title=f'Cambridge IELTS {book} Academic {subject}',
                         author='ARIF ACADEMY', **kwargs)
        self.book = book
        self.subject = subject
        self.running = 'ACADEMIC ' + subject.upper()
        self.destination_pages = {}
        self.addPageTemplates(PageTemplate('book', [Frame(LEFT, 53, WIDTH, H - 114, leftPadding=0,
             bottomPadding=0, rightPadding=0, topPadding=0)], onPageEnd=self.draw_page))

    def beforeDocument(self):
        self.running = 'ACADEMIC ' + self.subject.upper()
        self.destination_pages = {}

    def draw_page(self, c, doc):
        if doc.page == 1:
            return
        c.saveState()
        c.setStrokeColor(RULE)
        c.setLineWidth(.45)
        c.line(LEFT, H - 40, W - RIGHT, H - 40)
        c.setFillColor(MUTED)
        c.setFont('Sans', 8)
        c.drawString(LEFT, H - 29, f'CAMBRIDGE IELTS {self.book}  /  ACADEMIC {self.subject.upper()}')
        c.drawRightString(W - RIGHT, H - 29, self.running)
        c.setFont('Sans', 8)
        c.drawString(LEFT, 29, 'ARIF ACADEMY')
        c.setFillColor(GREEN)
        c.drawRightString(W - RIGHT, 29, str(doc.page))
        c.restoreState()

    def afterFlowable(self, flowable):
        if hasattr(flowable, 'destination'):
            key, title, level = flowable.destination
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level, closed=False)
            self.destination_pages[key] = self.page
            if getattr(flowable, 'in_contents', True):
                self.notify('TOCEntry', (level, escape(title), self.page, key))
        if hasattr(flowable, 'running'):
            self.running = flowable.running


def heading(text, style, key, level=0, running=None, in_contents=True):
    p = Paragraph(markup(text), style)
    p.destination = (key, text, level)
    p.in_contents = in_contents
    if running:
        p.running = running
    return p


def get_tests(db, book, test=None):
    query = 'SELECT * FROM tests WHERE book_number=?'
    params = [book]
    if test is not None:
        query += ' AND test_number=?'
        params.append(test)
    tests = []
    for record in db.execute(query + ' ORDER BY test_number', params):
        t = dict(record)
        t['passages'] = []
        for record in db.execute('SELECT * FROM passages WHERE test_id=? ORDER BY passage_number', (t['id'],)):
            p = dict(record)
            p['sections'] = []
            for record in db.execute('SELECT * FROM sections WHERE passage_id=? ORDER BY position', (p['id'],)):
                s = dict(record)
                s['instructions'] = json.loads(s['instructions_json'])
                s['nodes'] = json.loads(s['content_json'])
                s['questions'] = [dict(r) for r in db.execute('SELECT * FROM questions WHERE section_id=? ORDER BY question_number', (s['id'],))]
                for q in s['questions']:
                    q['options'] = [dict(r) for r in db.execute('SELECT * FROM options WHERE question_id=? ORDER BY position', (q['id'],))]
                    q['answer'] = db.execute('SELECT answer FROM answers WHERE question_id=?', (q['id'],)).fetchone()[0]
                    q['explanation'] = db.execute('SELECT text FROM explanations WHERE question_id=?', (q['id'],)).fetchone()[0]
                s['options'] = [dict(r) for r in db.execute('SELECT * FROM options WHERE section_id=? AND question_id IS NULL ORDER BY position', (s['id'],))]
                s['assets'] = [dict(r) for r in db.execute('SELECT * FROM assets WHERE section_id=? ORDER BY position', (s['id'],))]
                p['sections'].append(s)
            t['passages'].append(p)
        tests.append(t)
    if not tests:
        raise ValueError('No matching tests in the database')
    for t in tests:
        qs = [q for p in t['passages'] for s in p['sections'] for q in s['questions']]
        if len(t['passages']) != 3 or [q['question_number'] for q in qs] != list(range(1, 41)):
            raise ValueError(f"Test {t['test_number']} is incomplete")
    return tests


def option_bank(options, st):
    if not options:
        return []
    rows = [[Paragraph('<b>' + escape(o['label']) + '</b>', st['question']),
             Paragraph(markup(o['text']), st['question'])] for o in options]
    table = Table(rows, colWidths=[29, WIDTH - 51], hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PALE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('LEFTPADDING', (0, 0), (-1, -1), 10)]))
    return [table, Spacer(1, 10)]


def question_section(s, st):
    story = []
    a, b = s['first_question'], s['last_question']
    label = f'Question {a}' if a == b else f'Questions {a}–{b}'
    rule = Hairline()
    rule.keepWithNext = True
    story.extend([CondPageBreak(135), Paragraph(label, st['section']), rule])
    for node in s['instructions']:
        story.append(Paragraph(markup(node['text']), st['instruction']))
    kind = s['question_type']
    if kind in ('true_false_not_given', 'yes_no_not_given'):
        intro = ' '.join(n['text'] for n in s['instructions']).lower()
        if 'if the statement' not in intro:
            vals = [('TRUE', 'agrees with the information'), ('FALSE', 'contradicts the information'), ('NOT GIVEN', 'there is no information on this')]
            if kind == 'yes_no_not_given':
                vals = [('YES', 'agrees with the writer’s claims'), ('NO', 'contradicts the writer’s claims'), ('NOT GIVEN', 'the writer’s view is not stated')]
            for word, meaning in vals:
                story.append(Paragraph(f'<b>{word}</b> — {meaning}', st['instruction']))
    gap = Spacer(1, 7)
    gap.keepWithNext = True
    story.append(gap)
    if kind == 'diagram_label':
        for asset in s['assets']:
            scale = min((WIDTH - 22) / asset['width'], 215 / asset['height'])
            picture = Image(io.BytesIO(asset['data']), width=asset['width'] * scale, height=asset['height'] * scale)
            picture.hAlign = 'CENTER'
            story.extend([picture, Spacer(1, 12)])
        rows = [[Paragraph(f'<b>{q["question_number"]}</b>  ________________________', st['question']) for q in s['questions'][i:i + 2]] for i in range(0, len(s['questions']), 2)]
        story.append(KeepTogether([Table(rows, colWidths=[WIDTH / 2] * 2, hAlign='LEFT')]))
        return story
    # Shared text, titles, notes and summaries are reflowed from database nodes.
    if kind == 'table_completion':
        table_rows = []
        for n in s['nodes']:
            table_rows.append([Paragraph(markup(n['text']), st['subhead'] if n['kind'] == 'heading' else st['question'])])
        table = Table(table_rows, colWidths=[WIDTH], hAlign='LEFT')
        table.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), .6, RULE), ('LINEBELOW', (0, 0), (-1, -1), .35, RULE),
            ('BACKGROUND', (0, 0), (-1, 0), PALE), ('LEFTPADDING', (0, 0), (-1, -1), 13),
            ('RIGHTPADDING', (0, 0), (-1, -1), 13), ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9)]))
        story.append(table)
    elif kind == 'flow_chart':
        step_seen = False
        for n in s['nodes']:
            text = n['text'].replace('↓', '').strip()
            if not text:
                continue
            if n['kind'] == 'heading':
                story.append(Paragraph(markup(text), st['subhead']))
            else:
                if step_seen:
                    story.append(FlowArrow())
                step_seen = True
                box = Table([[Paragraph(markup(text), st['question'])]], colWidths=[WIDTH - 36], hAlign='CENTER')
                box.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), .6, RULE), ('BACKGROUND', (0, 0), (-1, -1), PALE),
                    ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
                story.extend([box, Spacer(1, 9)])
    else:
        for node in s['nodes']:
            style = st['subhead'] if node['kind'] == 'heading' else st['question']
            story.append(Paragraph(markup(node['text']), style))
    story.extend(option_bank(s['options'], st))
    discrete = kind in ('multiple_choice', 'multiple_response', 'true_false_not_given', 'yes_no_not_given',
                        'short_answer', 'matching_information', 'matching_features', 'matching_headings')
    seen = set()
    if discrete:
        for q in s['questions']:
            group = q['group_key']
            if group in seen:
                continue
            seen.add(group)
            number = group.replace(',', ' & ')
            part = [Paragraph(f'<b>{number}</b>\u00a0\u00a0 {markup(q["prompt"])}', st['question'])]
            if kind in ('multiple_choice', 'multiple_response'):
                for o in q['options']:
                    part.append(Paragraph(f'<b>{escape(o["label"])}</b>\u00a0\u00a0 {markup(o["text"])}', st['option']))
            else:
                part.append(Paragraph('Answer: ____________________', st['small']))
            part.append(Spacer(1, 7))
            story.append(KeepTogether(part))
    return story


def build_story(tests, book, st):
    single = tests[0]['test_number'] if len(tests) == 1 else None
    story = [Cover(book, len(tests), single), PageBreak()]
    story.append(heading('Contents', st['title'], 'contents', in_contents=False))
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle('toc0', fontName='Sans-Bold', fontSize=11, leading=18, spaceBefore=10, textColor=GREEN),
                       ParagraphStyle('toc1', fontName='Sans', fontSize=10, leading=16, leftIndent=14, textColor=INK)]
    toc.dotsMinLevel = 0
    story.extend([toc, PageBreak(), heading('Before you begin', st['title'], 'instructions', in_contents=False)])
    story.append(Paragraph('A complete Reading test takes 60 minutes. Each test has three passages and 40 questions. Work through the test before turning to the answers at the back of this book.', st['body']))
    for title, text in [
        ('Plan your time', 'Allow approximately 20 minutes for each passage. Keep enough time to check your answers within the 60-minute limit.'),
        ('Follow the task instructions', 'Check the word limit for each completion task. For matching and multiple-choice tasks, write the requested letter or number.'),
        ('Record your answers', 'Use the spaces alongside the questions or the answer sheet after each test. Check spelling carefully.'),
        ('Review your work', 'After finishing a test, use the answer key and the source explanations to review the passage evidence for each answer.')]:
        story.extend([Paragraph(title, st['section']), Paragraph(text, st['body'])])
    story.append(Spacer(1, 24))
    story.append(Paragraph('This practice edition is typeset by Arif Academy from the supplied Reading material. Passage wording and answer explanations follow that material.', st['small']))
    for t in tests:
        tn = t['test_number']
        story.extend([PageBreak(), heading(f'Test {tn}', st['title'], f'test-{tn}', running=f'TEST {tn}')])
        story.append(Paragraph('60 MINUTES  /  3 PASSAGES  /  40 QUESTIONS', st['eyebrow']))
        for pi, p in enumerate(t['passages']):
            pn = p['passage_number']
            if pi:
                story.append(PageBreak())
            story.append(Paragraph(f'READING PASSAGE {pn}', st['eyebrow']))
            story.append(heading(p['title'], st['title'], f'test-{tn}-passage-{pn}', 1))
            paras = p['content'].split('\n\n')
            source_instruction = paras and paras[0].startswith('You should spend')
            if source_instruction:
                instruction = paras.pop(0)
            else:
                first = p['sections'][0]['first_question']
                last = p['sections'][-1]['last_question']
                instruction = f'You should spend about 20 minutes on Questions {first}–{last}, which are based on Reading Passage {pn} below.'
            story.extend([Paragraph(markup(instruction), st['instruction']), Hairline(), Spacer(1, 10)])
            i = 0
            while i < len(paras):
                text = paras[i]
                if re.fullmatch(r'[A-H][.)]?', text) and i + 1 < len(paras):
                    text += '  ' + paras[i + 1]
                    i += 1
                value = markup(text)
                value = re.sub(r'^([A-H][.)]?)\s+', lambda m: '<b>' + m[1] + '</b>\u00a0\u00a0 ', value)
                story.append(Paragraph(value, st['body']))
                i += 1
            story.extend([PageBreak(), Paragraph(f'TEST {tn}  /  PASSAGE {pn}', st['eyebrow']),
                          Paragraph('Questions', st['title'])])
            for s in p['sections']:
                story.extend(question_section(s, st))
        story.extend([PageBreak(), Paragraph(f'Test {tn} · Answer sheet', st['title']),
                      Paragraph('Candidate name: __________________________________     Date: __________________', st['small']), Spacer(1, 15)])
        answer_rows = [[Paragraph(f'<b>{n}</b>   __________________________________', st['question']),
                        Paragraph(f'<b>{n + 20}</b>   __________________________________', st['question'])] for n in range(1, 21)]
        sheet = Table(answer_rows, colWidths=[WIDTH / 2] * 2)
        sheet.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        story.append(sheet)
    story.extend([PageBreak(), heading('Answers & explanations', st['title'], 'answers', running='ANSWERS & EXPLANATIONS')])
    story.append(Paragraph('Check your answers after completing each test. Explanations below reproduce the supporting text provided in the source material.', st['body']))
    for ti, t in enumerate(tests):
        tn = t['test_number']
        if ti:
            story.append(PageBreak())
        story.append(heading(f'Test {tn} · Answer key', st['section'], f'answers-{tn}', 1))
        for p in t['passages']:
            story.extend([CondPageBreak(110), Paragraph(f'Passage {p["passage_number"]} · {p["title"]}', st['subhead'])])
            qs = [q for s in p['sections'] for q in s['questions']]
            for q in qs:
                story.append(KeepTogether([
                    Paragraph(f'{q["question_number"]}\u00a0\u00a0 {markup(q["answer"])}', st['answer']),
                    Paragraph(markup(q['explanation']), st['explanation']), Hairline()]))
    return story


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=ROOT / 'Reading_Books')
    parser.add_argument('--book', type=int)
    parser.add_argument('--test', type=int)
    parser.add_argument('--font-dir', type=Path)
    args = parser.parse_args()
    if args.test and not args.book:
        parser.error('--test requires --book')
    register_fonts(args.font_dir)
    st = styles()
    args.output.mkdir(parents=True, exist_ok=True)
    report = []
    with connect(args.db, readonly=True) as db:
        books = [args.book] if args.book else [r[0] for r in db.execute('SELECT DISTINCT book_number FROM tests ORDER BY book_number')]
        for book in books:
            tests = get_tests(db, book, args.test)
            suffix = f' Test {args.test}' if args.test else ' Practice Book'
            target = args.output / f'Cambridge IELTS {book} Academic Reading{suffix}.pdf'
            temp = target.with_suffix('.tmp.pdf')
            try:
                doc = BookDoc(temp, book)
                doc.multiBuild(build_story(tests, book, st))
                temp.replace(target)
                record = {'file': target.name, 'book': book, 'tests': len(tests), 'pages': doc.page,
                          'questions': len(tests) * 40, 'destinations': doc.destination_pages}
                report.append(record)
                print(json.dumps(record), flush=True)
            finally:
                temp.unlink(missing_ok=True)
    name = 'generation_report.json' if args.test is None else f'test-{args.book}-{args.test}-report.json'
    (args.output / name).write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
