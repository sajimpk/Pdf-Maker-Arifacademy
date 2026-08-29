import asyncio
from playwright.async_api import async_playwright
import os
import sys
import sqlite3

# Ensure test number or 'all' is provided
if len(sys.argv) < 2:
    print("Usage: python generate_from_db.py <test_number | all>")
    sys.exit(1)

target_arg = sys.argv[1]
DB_PATH = "quiz_data.db"

def get_all_test_numbers():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file '{DB_PATH}' not found. Run extract_to_db.py first.")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT test_number FROM tests ORDER BY test_number ASC")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_test_data(test_num):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file '{DB_PATH}' not found. Run extract_to_db.py first.")
        sys.exit(1)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Fetch test
    cursor.execute("SELECT * FROM tests WHERE test_number = ?", (test_num,))
    test = cursor.fetchone()
    if not test:
        print(f"Error: Test {test_num} not found in database.")
        conn.close()
        sys.exit(1)
        
    test_id = test['id']
    test_title = test['title']
    
    # 2. Fetch passages
    cursor.execute("SELECT * FROM passages WHERE test_id = ? ORDER BY passage_number ASC", (test_id,))
    passages = [dict(row) for row in cursor.fetchall()]
    
    # 3. Fetch questions
    cursor.execute("SELECT * FROM questions WHERE test_id = ? ORDER BY q_number ASC", (test_id,))
    questions = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return test_title, passages, questions

def inject_missing_instructions(html_content):
    if not html_content:
        return html_content
    
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    
    wraps = soup.find_all(class_='aa-select-matrix-wrap')
    for wrap in wraps:
        options = wrap.get('data-aa-options', '').lower()
        if not options:
            continue
        
        # Check if already has instruction box to avoid duplicates
        if wrap.find(class_='ielts-instruction-box'):
            continue
            
        instruction_html = ""
        if 'true|false|not given' in options:
            instruction_html = """
            <div class="ielts-instruction-box">
                <div class="ielts-instruction-row">
                    <div class="ielts-instruction-key">TRUE</div>
                    <div class="ielts-instruction-val">if the statement agrees with the information</div>
                </div>
                <div class="ielts-instruction-row">
                    <div class="ielts-instruction-key">FALSE</div>
                    <div class="ielts-instruction-val">if the statement contradicts the information</div>
                </div>
                <div class="ielts-instruction-row">
                    <div class="ielts-instruction-key">NOT GIVEN</div>
                    <div class="ielts-instruction-val">if there is no information on this</div>
                </div>
            </div>
            """
        elif 'yes|no|not given' in options:
            instruction_html = """
            <div class="ielts-instruction-box">
                <div class="ielts-instruction-row">
                    <div class="ielts-instruction-key">YES</div>
                    <div class="ielts-instruction-val">if the statement agrees with the claims of the writer</div>
                </div>
                <div class="ielts-instruction-row">
                    <div class="ielts-instruction-key">NO</div>
                    <div class="ielts-instruction-val">if the statement contradicts the claims of the writer</div>
                </div>
                <div class="ielts-instruction-row">
                    <div class="ielts-instruction-key">NOT GIVEN</div>
                    <div class="ielts-instruction-val">if it is impossible to say what the writer thinks about this</div>
                </div>
            </div>
            """
            
        if instruction_html:
            instruction_soup = BeautifulSoup(instruction_html, 'html.parser')
            # Insert right before the table
            table = wrap.find('table')
            if table:
                table.insert_before(instruction_soup)
            else:
                wrap.insert(0, instruction_soup)
                
    return str(soup)

async def render_single_pdf(test_num):
    test_title, passages, questions = get_test_data(test_num)
    
    # Parse book number and test number from title if possible (e.g. "C20 Reading Test 2" -> book 20, test 2)
    import re
    book_match = re.search(r'C(\d+)', test_title, re.IGNORECASE)
    test_match = re.search(r'Test\s*(\d+)', test_title, re.IGNORECASE)
    
    if test_match:
        display_test_num = test_match.group(1)
    else:
        display_test_num = str(test_num)

    if book_match:
        book_num = book_match.group(1)
        pdf_name = os.path.abspath(f"Cambridge IELTS {book_num} Academic Reading Test {display_test_num}.pdf")
    else:
        # Fallback to standard cleaning
        clean_title = test_title.split('|')[0].strip()
        pdf_name = os.path.abspath(f"{clean_title}.pdf")
    
    # 1. Build Cover Page HTML
    if book_match:
        cover_title = f"Cambridge IELTS {book_num}"
        cover_subtitle = f"Academic Reading Test {display_test_num}"
    else:
        cover_title = "IELTS Academic Reading Test"
        cover_subtitle = f"Practice Test {display_test_num}"
        
    cover_html = f"""
    <div class="cover-page">
        <div class="cover-header">ARIF ACADEMY</div>
        <h1 class="cover-title">{cover_title}</h1>
        <h2 class="cover-subtitle">{cover_subtitle}</h2>
        
        <div class="divider"></div>
        
        <div class="info-boxes">
            <div class="info-box">
                <span class="info-icon">📄</span>
                <span class="info-text"><strong>3</strong> Reading<br>Passages</span>
            </div>
            <div class="info-box">
                <span class="info-icon">❓</span>
                <span class="info-text"><strong>40</strong> Questions</span>
            </div>
            <div class="info-box">
                <span class="info-icon">⏱</span>
                <span class="info-text"><strong>60</strong> Minutes</span>
            </div>
        </div>
        
        <div class="candidate-info">
            <div class="info-row">
                <span class="info-label">Candidate name:</span>
                <div class="info-line"></div>
            </div>
            <div class="info-row">
                <span class="info-label">Test date:</span>
                <div class="info-line"></div>
            </div>
        </div>
    </div>
    <div class="page-break"></div>
    """
    
    # 2. Build Instructions Page HTML
    instructions_html = """
    <div class="instructions-page">
        <h1 class="page-title">Test Instructions</h1>
        
        <div class="instructions-container">
            <div class="general-rules">
                <h2 class="rules-heading">General Rules</h2>
                <ul class="rules-list">
                    <li>
                        <span class="arrow">➔</span>
                        <span>The test contains three reading passages and 40 questions.</span>
                    </li>
                    <li>
                        <span class="arrow">➔</span>
                        <span>Allow approximately 20 minutes for each passage.</span>
                    </li>
                    <li>
                        <span class="arrow">➔</span>
                        <span>Read every instruction carefully before answering.</span>
                    </li>
                    <li>
                        <span class="arrow">➔</span>
                        <span>Write answers in the spaces provided.</span>
                    </li>
                    <li>
                        <span class="arrow">➔</span>
                        <span>Check spelling and word limits for completion tasks.</span>
                    </li>
                    <li>
                        <span class="arrow">➔</span>
                        <span>Transfer and review all answers before the time ends.</span>
                    </li>
                </ul>
            </div>
            
            <div class="time-plan">
                <h2 class="plan-heading">Time Plan</h2>
                
                <div class="plan-item">
                    <div class="plan-number">01</div>
                    <div class="plan-details">
                        <span class="plan-title">Passage 1</span>
                        <span class="plan-sub">Questions 1–13 — 20 minutes</span>
                    </div>
                </div>
                
                <div class="plan-item">
                    <div class="plan-number">02</div>
                    <div class="plan-details">
                        <span class="plan-title">Passage 2</span>
                        <span class="plan-sub">Questions 14–26 — 20 minutes</span>
                    </div>
                </div>
                
                <div class="plan-item">
                    <div class="plan-number">03</div>
                    <div class="plan-details">
                        <span class="plan-title">Passage 3</span>
                        <span class="plan-sub">Questions 27–40 — 20 minutes</span>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="warning-box">
            <span class="warning-icon">⚠</span>
            <span class="warning-text">Do not turn over until you are told to begin. Manage your time carefully — 20 minutes per passage is recommended.</span>
        </div>
    </div>
    <div class="page-break"></div>
    """
    
    # 3. Build Passages & Questions HTML
    import re
    passages_html = ""
    for idx, p in enumerate(passages):
        p_num = p['passage_number']
        q_range = "1–13" if p_num == 1 else ("14–26" if p_num == 2 else "27–40")
        
        p_content = p['content']
        # Find first <p> tag and remove it if it contains instructions to prevent duplication
        first_p_match = re.search(r'<p>(.*?)</p>', p_content, re.DOTALL)
        if first_p_match and ('spend' in first_p_match.group(1).lower() or 'questions' in first_p_match.group(1).lower()):
            p_content = p_content.replace(first_p_match.group(0), "", 1)
            
        title_header = ""
        if "h2" not in p_content.lower():
            title_header = f"<h2>{p['title']}</h2>"
            
        q_html = inject_missing_instructions(p['question_html'])
        passages_html += f"""
        <div id="part-{p_num}" class="test-contents">
            <div class="passage-tag">PASSAGE {p_num}</div>
            {title_header}
            
            <div class="passage-instructions-box">
                <span class="instructions-icon">🗏</span>
                <span class="instructions-text">You should spend about 20 minutes on Questions {q_range}, which are based on Reading Passage {p_num} below.</span>
            </div>
            
            {p_content}
        </div>
        <div id="part-questions-{p_num}" class="test-panel">
            <div class="questions-tag">PART {p_num} — QUESTIONS</div>
            {q_html}
        </div>
        """
        if idx < len(passages) - 1:
            passages_html += '<div class="page-break"></div>\n'
        
    # 4. Build Explanations HTML table
    explanations_html = """
    <div class="print-only-explanations-section">
        <div class="answer-key-tag">ANSWER KEY</div>
        <h2 class="explanations-title">Answer Key & Explanations</h2>
        
        <table class="explanations-table">
            <thead>
                <tr>
                    <th style="width: 8%; text-align: center;">#</th>
                    <th style="width: 22%">Correct Answer</th>
                    <th style="width: 70%">Explanation</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for q in questions:
        exp_text = ""
        if q['excerpt_explanation']:
            exp_text += f"<p style='margin: 0 0 6px 0; font-family: \"Lora\", serif;'><strong>Excerpt/Passage Explanation:</strong> {q['excerpt_explanation']}</p>"
        if q['answer_explanation']:
            exp_text += f"<p style='margin: 0 0 6px 0; font-family: \"Lora\", serif;'><strong>Answer Explanation:</strong> {q['answer_explanation']}</p>"
        if q['reason_explanation']:
            exp_text += f"<p style='margin: 0 0 6px 0; font-family: \"Lora\", serif;'><strong>Reason For Correctness:</strong> {q['reason_explanation']}</p>"
            
        if not exp_text:
            exp_text = "<p style='margin: 0; font-family: \"Lora\", serif;'>No explanation available.</p>"
            
        explanations_html += f"""
        <tr>
            <td style="font-weight: bold; text-align: center; border: 1px solid #bdc3c7; padding: 10px; font-family: 'Lora', serif;">{q['q_number']}</td>
            <td style="font-weight: bold; color: #2d6a4f; border: 1px solid #bdc3c7; padding: 10px; font-family: 'Lora', serif;">{q['correct_answer']}</td>
            <td style="border: 1px solid #bdc3c7; padding: 10px; font-size: 13px; line-height: 1.5; font-family: 'Lora', serif;">{exp_text}</td>
        </tr>
        """
        
    explanations_html += """
            </tbody>
        </table>
    </div>
    """
    
    # 5. Assemble full intermediate HTML
    full_html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{test_title}</title>
        <style>
            body {{
                background: white;
            }}
        </style>
    </head>
    <body class="modal-open">
        <div id="result-modal">
            <div class="modal-content">
                {cover_html}
                {instructions_html}
                {passages_html}
                {explanations_html}
            </div>
        </div>
    </body>
    </html>
    """
    
    temp_html_path = os.path.abspath(f"temp_print_{test_num}.html")
    with open(temp_html_path, "w", encoding="utf-8") as f:
        f.write(full_html)
        
    # 6. Render PDF using Playwright
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        print("Loading intermediate HTML in browser...")
        await page.goto(f"file:///{temp_html_path}")
        await page.wait_for_timeout(1000)
        
        # Inject print CSS for a beautiful "book vibe"
        print("Injecting book-style CSS...")
        css_content = """
        @import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,700;1,400;1,700&family=Playfair+Display:ital,wght@0,600;0,700;1,600;1,700&family=Montserrat:wght@400;500;700&display=swap');

        /* Hide interface elements, scorecards, headers, footers, and scrollbars */
        body > .dialog-off-canvas-main-canvas,
        .container.page, 
        #result-frame, 
        .reading-footer, 
        .nicescroll-rails,
        .modal-header,
        .modal-footer,
        #show-result-modal,
        .btn-show-re,
        .close-rf,
        .realtest-header,
        /* Hide raw source matrix paragraphs to avoid duplicate questions */
        .aa-matrix-source-hidden,
        p.aa-matrix-source-hidden,
        /* Hide Bootstrap-select and standard browser dropdown containers */
        .bootstrap-select,
        .dropdown-menu,
        .dropdown-toggle,
        .btn-group.bootstrap-select {
            display: none !important;
        }

        /* Hide inline detailed explanations next to questions */
        .sl-item.explanation {
            display: none !important;
        }

        /* Hide inline answers lists (review answers) on the question page */
        .test-panel__item > ul,
        .test-panel li.answer,
        .test-panel .answer,
        .test-panel .locate-explain,
        .test-panel .detailed-explanation {
            display: none !important;
        }

        /* Reset html/body to flow naturally and use premium book typography */
        html, body {
            height: auto !important;
            overflow: visible !important;
            position: static !important;
            background: white !important;
            font-family: 'Lora', 'Georgia', serif !important;
            color: #2c3e50 !important;
            font-size: 13px !important; /* Smaller base font size */
            line-height: 1.5 !important; /* Tighter print line height */
        }

        /* Force review modal container to print cleanly */
        #result-modal {
            position: static !important;
            display: block !important;
            height: auto !important;
            width: auto !important;
            overflow: visible !important;
            background: white !important;
            opacity: 1 !important;
        }
        .modal-dialog,
        .modal-content {
            display: block !important;
            position: static !important;
            height: auto !important;
            width: auto !important;
            overflow: visible !important;
        }
        
        #result-modal .dialog-off-canvas-main-canvas,
        #result-modal .page.take-test,
        #result-modal .take-test__body,
        #result-modal .region-content,
        #result-modal article,
        #result-modal #highlighter-contents,
        #result-modal .take-test__board {
            position: static !important;
            display: block !important;
            height: auto !important;
            width: auto !important;
            overflow: visible !important;
            background: white !important;
        }

        /* Stack split columns vertically inside modal */
        #result-modal .take-test__split-item {
            width: 100% !important;
            max-width: 100% !important;
            position: static !important;
            display: block !important;
            height: auto !important;
            overflow: visible !important;
            float: none !important;
            padding: 0 !important;
            margin: 0 !important;
        }

        /* Show test content and question panels only inside modal */
        #result-modal .test-contents {
            display: block !important;
            position: static !important;
            height: auto !important;
            overflow: visible !important;
            visibility: visible !important;
            outline: none !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        #result-modal .test-panel {
            display: block !important;
            position: static !important;
            height: auto !important;
            overflow: visible !important;
            visibility: visible !important;
            outline: none !important;
            padding: 0 !important;
            margin: 40px 0 0 0 !important;
        }

        /* --- Page Breaks --- */
        .page-break {
            page-break-before: always !important;
        }
        h2, h3, .questions-tag, .passage-tag, .answer-key-tag, .test-panel__header, .test-panel__question {
            break-after: avoid !important;
            page-break-after: avoid !important;
        }

        /* --- Cover Page Styling (Page 1) --- */
        .cover-page {
            text-align: center !important;
            padding-top: 1.5cm !important;
            height: 25cm !important;
            box-sizing: border-box !important;
            background: #ffffff !important;
            font-family: 'Montserrat', sans-serif !important;
        }
        .cover-header {
            font-size: 14px !important;
            font-weight: 700 !important;
            letter-spacing: 2px !important;
            color: #7f8c8d !important;
            text-transform: uppercase !important;
            margin-bottom: 2cm !important;
        }
        .cover-title {
            font-family: 'Playfair Display', serif !important;
            font-size: 38px !important;
            color: #2e5bff !important;
            margin-bottom: 20px !important;
            font-weight: 700 !important;
        }
        .cover-subtitle {
            font-family: 'Playfair Display', serif !important;
            font-size: 42px !important;
            color: #2e5bff !important;
            margin-bottom: 2.5cm !important;
            font-weight: 700;
        }
        .cover-page .divider {
            height: 2px !important;
            background-color: #bdc3c7 !important;
            width: 80% !important;
            margin: 0 auto 1.5cm auto !important;
        }
        .info-boxes {
            display: flex !important;
            justify-content: center !important;
            gap: 2px !important;
            margin-bottom: 3.5cm !important;
            width: 80% !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }
        .info-box {
            flex: 1 !important;
            background-color: #2d6a4f !important; /* Green background */
            color: white !important;
            padding: 15px 10px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 10px !important;
            font-size: 14px !important;
            box-sizing: border-box !important;
        }
        .info-icon {
            font-size: 20px !important;
        }
        .info-text {
            text-align: left !important;
            line-height: 1.3 !important;
        }
        .candidate-info {
            width: 60% !important;
            margin: 0 auto !important;
            text-align: left !important;
            font-size: 15px !important;
            color: #34495e !important;
        }
        .info-row {
            display: flex !important;
            align-items: flex-end !important;
            margin-bottom: 25px !important;
        }
        .info-label {
            font-weight: 700 !important;
            margin-right: 15px !important;
            width: 140px !important;
        }
        .info-line {
            flex-grow: 1 !important;
            border-bottom: 1px solid #7f8c8d !important;
            height: 18px !important;
        }

        /* --- Instructions Page Styling (Page 2) --- */
        .instructions-page {
            padding-top: 1cm !important;
            height: 25cm !important;
            box-sizing: border-box !important;
            font-family: 'Montserrat', sans-serif !important;
        }
        .page-title {
            font-family: 'Playfair Display', serif !important;
            font-size: 36px !important;
            color: #2e5bff !important;
            margin-bottom: 30px !important;
            border-bottom: 2px solid #bdc3c7 !important;
            padding-bottom: 10px !important;
            font-weight: 700 !important;
        }
        .instructions-container {
            display: flex !important;
            justify-content: space-between !important;
            gap: 40px !important;
            margin-bottom: 2cm !important;
        }
        .general-rules {
            flex: 1.2 !important;
        }
        .rules-heading, .plan-heading {
            font-size: 18px !important;
            font-weight: 700 !important;
            color: #e74c3c !important; /* Red Heading */
            margin-bottom: 20px !important;
        }
        .rules-list {
            list-style: none !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        .rules-list li {
            display: flex !important;
            align-items: flex-start !important;
            gap: 15px !important;
            margin-bottom: 20px !important;
            font-size: 14px !important;
            line-height: 1.5 !important;
            color: #34495e !important;
        }
        .rules-list li .arrow {
            color: #2d6a4f !important;
            font-weight: bold !important;
            font-size: 16px !important;
        }
        .time-plan {
            flex: 0.8 !important;
            background-color: #2d6a4f !important; /* Green background */
            color: white !important;
            padding: 25px !important;
        }
        .time-plan .plan-heading {
            color: white !important;
            border-bottom: 1px solid #52b788 !important;
            padding-bottom: 10px !important;
            margin-top: 0 !important;
        }
        .plan-item {
            display: flex !important;
            align-items: center !important;
            gap: 20px !important;
            margin-bottom: 25px !important;
            border-bottom: 1px solid rgba(255,255,255,0.2) !important;
            padding-bottom: 15px !important;
        }
        .plan-item:last-child {
            border-bottom: none !important;
            padding-bottom: 0 !important;
            margin-bottom: 0 !important;
        }
        .plan-number {
            font-size: 24px !important;
            font-weight: 700 !important;
            color: #52b788 !important;
        }
        .plan-details {
            display: flex !important;
            flex-direction: column !important;
        }
        .plan-title {
            font-size: 15px !important;
            font-weight: 700 !important;
        }
        .plan-sub {
            font-size: 12px !important;
            opacity: 0.9 !important;
            margin-top: 4px !important;
        }
        .warning-box {
            background-color: #fef9c3 !important; /* Yellow warning box */
            border: 1px solid #fef08a !important;
            border-left: 5px solid #eab308 !important;
            padding: 20px !important;
            display: flex !important;
            gap: 15px !important;
            align-items: center !important;
            font-size: 13px !important;
            color: #713f12 !important;
            line-height: 1.5 !important;
        }
        .warning-icon {
            font-size: 20px !important;
            color: #eab308 !important;
        }

        /* --- Passage Page Styling --- */
        .passage-tag, .questions-tag, .answer-key-tag {
            background-color: #e74c3c !important; /* Red Tag */
            color: white !important;
            font-family: 'Montserrat', sans-serif !important;
            font-size: 10px !important;
            font-weight: 700 !important;
            padding: 4px 10px !important;
            display: inline-block !important;
            margin-bottom: 15px !important;
            text-transform: uppercase !important;
            letter-spacing: 1px !important;
        }
        .test-contents h2 {
            font-family: 'Playfair Display', serif !important;
            font-size: 32px !important;
            font-weight: 700 !important;
            color: #2e5bff !important; /* Premium Blue */
            margin-top: 0 !important;
            margin-bottom: 20px !important;
        }
        .passage-instructions-box {
            background-color: #e8eaf6 !important; /* Soft Purple/Blue alert box */
            border-left: 4px solid #3f51b5 !important;
            padding: 15px !important;
            display: flex !important;
            gap: 15px !important;
            align-items: center !important;
            font-size: 14px !important;
            color: #1a237e !important;
            margin-bottom: 25px !important;
            font-family: 'Montserrat', sans-serif !important;
        }
        .instructions-icon {
            font-size: 18px !important;
        }
        .test-contents,
        .test-contents__paragragh,
        .test-contents p {
            text-align: justify !important;
            text-justify: inter-word !important;
        }
        .test-contents p {
            text-indent: 0 !important; /* No paragraph indents (gaps) */
            margin: 0 0 16px 0 !important; /* Spacing between paragraphs */
            font-family: 'Lora', serif !important;
            font-size: 13px !important; /* Smaller passage font size */
            color: #2c3e50 !important;
        }

        /* Allow page breaks inside question blocks to fit content naturally and avoid gaps */
        .test-panel__item {
            page-break-inside: auto !important;
            break-inside: auto !important;
            margin-bottom: 30px !important;
        }

        /* Premium styling for question layout tables (e.g. notes, flow-charts) */
        .test-panel table:not(.aa-select-matrix) {
            border-collapse: collapse !important;
            border: 1.5px solid #2c3e50 !important; /* Premium dark slate border */
            margin: 20px 0 !important;
            width: 100% !important;
            page-break-inside: auto !important;
            break-inside: auto !important;
        }
        .test-panel table:not(.aa-select-matrix) td {
            padding: 20px 25px !important; /* Generous padding so text does not touch borders */
            border: none !important;
        }

        /* --- Questions Panel Book Styling --- */
        .questions-tag {
            background-color: #2e5bff !important; /* Blue tag for questions */
        }
        .test-panel h3 {
            font-family: 'Playfair Display', serif !important;
            font-size: 24px !important;
            font-weight: 700 !important;
            color: #2e5bff !important;
            margin-top: 0 !important;
            margin-bottom: 20px !important;
            border-bottom: 1px solid #bdc3c7 !important;
            padding-bottom: 8px !important;
        }
        .test-panel p {
            margin: 0 0 8px 0 !important;
            font-family: 'Lora', serif !important;
            font-size: 13px !important; /* Smaller question font size */
        }

        /* Multiple Choice clean vertical print styling */
        .test-panel__question-sm-group {
            display: block !important;
            margin-top: 15px !important;
            margin-bottom: 20px !important;
            border: none !important;
            background: transparent !important;
            padding: 0 !important;
        }
        .test-panel__question-sm-group > div,
        .test-panel__question-sm-title,
        .test-panel__answer {
            display: block !important;
            width: 100% !important;
            border: none !important;
            background: transparent !important;
            padding: 0 !important;
            margin: 0 !important;
            box-shadow: none !important;
            float: none !important;
        }
        .test-panel__question-sm-title {
            font-weight: bold !important;
            color: #2c3e50 !important;
            margin-bottom: 10px !important;
            font-size: 13px !important;
        }
        .test-panel__answer {
            margin-left: 20px !important; /* Indent choices below the question */
        }
        .test-panel__answer-item {
            margin-bottom: 6px !important;
            font-size: 12px !important;
            display: flex !important;
            align-items: flex-start !important;
        }

        /* Clean badges for MCQ options */
        .qp-item,
        .test-panel__answer-option {
            border: none !important;
            background: transparent !important;
            padding: 0 !important;
            margin-right: 8px !important;
            font-weight: 700 !important;
            color: #1a1a1a !important;
            width: auto !important;
            height: auto !important;
            display: inline-block !important;
            line-height: inherit !important;
        }
        .test-panel__answer-option.-is-correct {
            color: #2d6a4f !important;
        }
        .test-panel__answer-option.-wrong {
            color: #e74c3c !important;
        }
        
        /* Hide radio/checkbox circles */
        input[type="radio"],
        input[type="checkbox"] {
            display: none !important;
        }
        .iot-radio, .iot-checkbox {
            display: inline-block !important;
            margin-left: 4px !important;
            cursor: default !important;
            color: #2c3e50 !important;
        }

        /* Style the True/False/Not Given Matrix Table to look like clean book lines */
        .aa-select-matrix-wrap {
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            padding: 0 !important;
            margin: 0 0 25px 0 !important;
        }
        
        .aa-select-matrix,
        .aa-select-matrix tbody,
        .aa-select-matrix tr,
        .aa-select-matrix-question {
            display: block !important;
            width: 100% !important;
            border: none !important;
            background: transparent !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        
        /* Individual question rows in the matrix */
        .aa-select-matrix tr {
            margin-bottom: 20px !important;
            padding-bottom: 12px !important;
            border-bottom: 1px dashed #e0e0e0 !important; /* Soft separation */
        }
        
        /* Question cell */
        .aa-select-matrix-question {
            font-size: 15px !important;
            line-height: 1.6 !important;
            color: #1a1a1a !important;
            font-family: 'Lora', serif !important;
        }
        
        /* Question numbers in matrix */
        .aa-select-matrix-qnum {
            display: inline-block !important;
            font-weight: 700 !important;
            margin-right: 8px !important;
            border: none !important; /* Remove square border */
            background: transparent !important;
            padding: 0 !important;
            color: #1a1a1a !important;
            width: auto !important;
            height: auto !important;
            line-height: inherit !important;
        }
        
        /* Hide matrix headers and choice radio cells */
        .aa-select-matrix thead,
        .aa-select-matrix-choice {
            display: none !important;
        }

        /* Standard blank underlines */
        input[type="text"],
        input[type="number"],
        input[type="email"],
        select,
        textarea {
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            outline: none !important;
            padding: 0 4px !important;
            margin: 0 !important;
            appearance: none !important;
            -webkit-appearance: none !important;
            -moz-appearance: none !important;
            font-size: inherit !important;
            font-family: 'Lora', serif !important;
            font-style: italic !important;
            color: #2c3e50 !important;
            font-weight: 700 !important;
            width: 90px !important; /* Fixed width to prevent huge gaps */
            min-width: 90px !important;
            max-width: 90px !important;
            display: inline-block !important;
            border-bottom: 1.5px solid #2c3e50 !important;
            text-align: center !important;
            height: auto !important;
        }
        .question__input,
        .test-panel__input-answer,
        .iot-question__fill-blank,
        .form-control {
            border: none !important;
            border-bottom: 1.5px dashed #7f8c8d !important;
            background: transparent !important;
            box-shadow: none !important;
            border-radius: 0 !important;
            display: inline-block !important;
            text-align: center !important;
            padding: 0 4px !important;
            height: auto !important;
            min-width: 50px !important;
        }

        /* Custom dropdown blank placeholder underline styles */
        .aa-dd-blank {
            border-bottom: 1.5px dashed #7f8c8d !important;
            display: inline-block !important;
            width: 90px !important; /* Fixed width matching select elements */
            min-width: 90px !important;
            max-width: 90px !important;
            height: 15px !important;
            vertical-align: middle !important;
            margin: 0 5px !important;
        }

        /* --- Answer Key Table Styling --- */
        .answer-key-tag {
            background-color: #2d6a4f !important; /* Green tag for Answer Key */
        }
        .explanations-title {
            font-family: 'Playfair Display', serif !important;
            font-size: 36px !important;
            color: #2d6a4f !important;
            margin-bottom: 30px !important;
            border-bottom: 2px solid #bdc3c7 !important;
            padding-bottom: 10px !important;
            font-weight: 700 !important;
        }
        .explanations-table {
            width: 100% !important;
            border-collapse: collapse !important;
            margin-top: 20px !important;
            margin-bottom: 40px !important;
            font-family: 'Lora', serif !important;
        }
        .explanations-table th {
            background-color: #2d6a4f !important; /* Solid dark green header */
            color: white !important;
            font-family: 'Montserrat', sans-serif !important;
            font-weight: bold !important;
            border: 1px solid #2d6a4f !important;
            padding: 12px !important;
            text-align: left !important;
            font-size: 14px !important;
        }
        .explanations-table td {
            border: 1px solid #cccccc !important;
            padding: 12px !important;
            font-size: 11.5px !important; /* Smaller explanations table text */
            line-height: 1.5 !important;
            color: #2c3e50 !important;
        }
        .explanations-table tr:nth-child(even) {
            background-color: #f4f9f4 !important;
        }
        .green-alert {
            background-color: #d1fae5 !important; /* Green alert box */
            border: 1px solid #a7f3d0 !important;
            border-left: 5px solid #10b981 !important;
            color: #065f46 !important;
        }
        .green-alert .warning-icon {
            color: #10b981 !important;
        }

        /* IELTS Instruction Box Styling */
        .ielts-instruction-box {
            border: 1px solid #7f8c8d !important;
            padding: 10px 15px !important;
            margin: 15px 0 20px 0 !important;
            font-family: 'Lora', serif !important;
            font-size: 12.5px !important;
            background-color: #ffffff !important;
        }
        .ielts-instruction-row {
            display: flex !important;
            margin-bottom: 6px !important;
        }
        .ielts-instruction-row:last-child {
            margin-bottom: 0 !important;
        }
        .ielts-instruction-key {
            width: 110px !important;
            font-weight: bold !important;
            flex-shrink: 0 !important;
        }
        .ielts-instruction-val {
            flex-grow: 1 !important;
        }

        .print-only-explanations-section {
            margin-top: 50px !important;
            page-break-inside: auto !important;
            break-inside: auto !important;
        }
        """
        await page.add_style_tag(content=css_content)
        
        # Save to PDF using Playwright native footer template
        print(f"Generating PDF: {pdf_name}...")
        footer_template = """
        <div style="font-size: 9px; font-family: Arial, sans-serif; width: 100%; display: flex; justify-content: space-between; padding: 0 2.0cm; box-sizing: border-box; color: #7f8c8d;">
            <span>ARIF ACADEMY</span>
            <span class="pageNumber"></span>
        </div>
        """
        
        await page.pdf(
            path=pdf_name,
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<div style='height: 0px;'></div>",
            footer_template=footer_template,
            margin={"top": "1.0cm", "bottom": "1.2cm", "left": "2.0cm", "right": "2.0cm"}
        )
        print("PDF generated successfully.")
        await browser.close()
        
    # Clean up temp file
    if os.path.exists(temp_html_path):
        os.remove(temp_html_path)

async def render_pdf():
    if target_arg.lower() == 'all':
        test_numbers = get_all_test_numbers()
        if not test_numbers:
            print("No tests found in database.")
            return
        print(f"Found {len(test_numbers)} tests in database: {test_numbers}")
        for test_num in test_numbers:
            print(f"\n--- Processing Test {test_num} ---")
            try:
                await render_single_pdf(test_num)
            except Exception as e:
                print(f"Error generating PDF for Test {test_num}: {e}")
    else:
        try:
            test_num = int(target_arg)
        except ValueError:
            print("Error: Argument must be an integer test number or 'all'.")
            sys.exit(1)
        await render_single_pdf(test_num)

if __name__ == "__main__":
    asyncio.run(render_pdf())
