import asyncio
from playwright.async_api import async_playwright
import os
import re
import sys
import database

def normalize_title(title):
    # Remove | Result or similar suffixes
    title = title.split('|')[0]
    # Clean whitespace and lowercase
    return re.sub(r'\s+', ' ', title).strip().lower()

def find_existing_test_number(title):
    normalized_target = normalize_title(title)
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT test_number, title FROM tests")
    rows = cursor.fetchall()
    conn.close()
    for row in rows:
        if normalize_title(row[1]) == normalized_target:
            return row[0]
    return None

async def scrape_file(browser, html_file, test_number):
    html_path = os.path.abspath(html_file)
    
    page = await browser.new_page()
    await page.goto(f"file:///{html_path}")
    
    # Extract title
    title_text = await page.title()
    print(f"\nTest Title from {html_file}: {title_text}")
    
    # Determine test number if not explicitly specified
    if test_number is None:
        existing_num = find_existing_test_number(title_text)
        if existing_num is not None:
            test_number = existing_num
            print(f"Auto-update: Found existing Test {test_number} with matching title in database. Overwriting...")
        else:
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(test_number) FROM tests")
            row = cursor.fetchone()
            max_num = row[0] if row and row[0] is not None else 0
            conn.close()
            test_number = max_num + 1
            print(f"New test detected. Assigning next available Test number: {test_number}")
    else:
        print(f"Using manually specified Test number: {test_number}")
    
    # Click modal review to load explanations
    try:
        await page.click("#show-result-modal", timeout=5000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"Review modal already loaded or click failed: {e}")
        
    # Run JS extraction
    data = await page.evaluate("""() => {
        const result = {
            passages: [],
            questions: []
        };
        
        // 1. Extract Passages (Parts 1, 2, 3)
        for (let i = 1; i <= 3; i++) {
            const partEl = document.getElementById(`part-${i}`);
            if (partEl) {
                const titleEl = partEl.querySelector('h2');
                const title = titleEl ? titleEl.textContent.trim() : `Passage ${i}`;
                const content = partEl.innerHTML.trim(); // Save HTML content for rich styling later!
                
                // Extract questions HTML for this part
                const qPartEl = document.getElementById(`part-questions-${i}`);
                const question_html = qPartEl ? qPartEl.innerHTML.trim() : '';
                
                result.passages.push({ passage_number: i, title, content, question_html });
            }
        }
        
        // 2. Extract Questions (1 to 40)
        const liElements = document.querySelectorAll('#result-modal li.answer');
        liElements.forEach(li => {
            const bTag = li.querySelector('b');
            const qNum = bTag ? parseInt(bTag.textContent.trim()) : null;
            if (!qNum) return;
            
            const bRTag = li.querySelector('.b-r');
            const answer = bRTag ? bRTag.textContent.trim() : '';
            
            // Extract explanations
            let excerpt = '';
            let explanation = '';
            let reason = '';
            
            const expDivs = li.querySelectorAll('.detailed-explanation');
            expDivs.forEach(div => {
                const text = div.textContent.trim();
                if (text.startsWith('Excerpt/Passage Explanation:')) {
                    excerpt = text.replace('Excerpt/Passage Explanation:', '').trim();
                } else if (text.startsWith('Answer Explanation:')) {
                    explanation = text.replace('Answer Explanation:', '').trim();
                } else if (text.startsWith('Reason For Correctness:')) {
                    reason = text.replace('Reason For Correctness:', '').trim();
                }
            });
            
            // Find question text, type, and passage number
            let questionText = '';
            let questionType = 'unknown';
            let passageNum = 1;
            
            // Search DOM to locate passage part and statement text
            // A. Check for multiple choice
            const mcItems = document.querySelectorAll(`.test-panel__question-sm-title`);
            mcItems.forEach(item => {
                const qp = item.querySelector('.qp-item');
                if (qp && parseInt(qp.textContent.trim()) === qNum) {
                    questionText = item.textContent.replace(qp.textContent, '').trim();
                    questionType = 'multiple_choice';
                    
                    // Trace parent passage number
                    let parent = item.parentElement;
                    while (parent) {
                        if (parent.id && parent.id.startsWith('part-questions-')) {
                            passageNum = parseInt(parent.id.replace('part-questions-', ''));
                            break;
                        }
                        parent = parent.parentElement;
                    }
                }
            });
            
            // B. Check for standard input questions
            if (!questionText) {
                const fillItems = document.querySelectorAll(`span.qp-item`);
                fillItems.forEach(item => {
                    if (parseInt(item.textContent.trim()) === qNum) {
                        questionType = 'fill_in_the_blank';
                        
                        // Trace parent passage number
                        let parent = item.parentElement;
                        while (parent) {
                            if (parent.id && parent.id.startsWith('part-questions-')) {
                                passageNum = parseInt(parent.id.replace('part-questions-', ''));
                                break;
                            }
                            parent = parent.parentElement;
                        }
                        
                        // Extract neighboring text inside the block
                        if (parent) {
                            questionText = parent.textContent.trim();
                        }
                    }
                });
            }
            
            result.questions.push({
                q_number: qNum,
                passage_number: passageNum,
                question_type: questionType,
                question_text: questionText.replace(/\\s+/g, ' ').trim(),
                correct_answer: answer,
                excerpt_explanation: excerpt,
                answer_explanation: explanation,
                reason_explanation: reason
            });
        });
        
        return result;
    }""")
    
    # Store in database
    test_id = database.insert_test(test_number, title_text)
    
    for p_data in data['passages']:
        database.insert_passage(
            test_id,
            p_data['passage_number'],
            p_data['title'],
            p_data['content'],
            p_data['question_html']
        )
        
    for q_data in data['questions']:
        database.insert_question(
            test_id,
            q_data['q_number'],
            q_data['passage_number'],
            q_data['question_type'],
            q_data['question_text'],
            q_data['correct_answer'],
            q_data['excerpt_explanation'],
            q_data['answer_explanation'],
            q_data['reason_explanation']
        )
        
    print(f"Test {test_number} successfully scraped and stored in SQLite database.")
    await page.close()

async def extract_all():
    # Initialize the database tables
    database.init_db()
    
    html_file = "main.html"
    test_number = None
    html_files_to_process = []
    
    # 1. Parse arguments
    if len(sys.argv) == 2:
        # Single argument: check if it is a test number (integer)
        try:
            test_number = int(sys.argv[1])
            html_file = "main.html"
        except ValueError:
            print("Error: Single argument must be an integer test number.")
            return
        if not os.path.exists(html_file):
            print(f"Error: Default HTML file '{html_file}' not found.")
            return
        html_files_to_process = [(html_file, test_number)]
    elif len(sys.argv) >= 3:
        # Two arguments: html_file and test_number
        html_file = sys.argv[1]
        try:
            test_number = int(sys.argv[2])
        except ValueError:
            print("Error: Test number must be an integer.")
            return
        if not os.path.exists(html_file):
            print(f"Error: HTML file '{html_file}' not found.")
            return
        html_files_to_process = [(html_file, test_number)]
    else:
        # No arguments provided
        if os.path.exists("main.html"):
            html_file = "main.html"
            # Pass None so it auto-detects/updates based on title inside scrape_file
            html_files_to_process = [(html_file, None)]
        else:
            # Fall back to scanning for {number}.html files
            html_files = [f for f in os.listdir('.') if f.endswith('.html') and re.match(r'^\d+\.html$', f)]
            if not html_files:
                print("\nUsage for manual test add:")
                print("  python extract_to_db.py <test_number> (uses main.html)")
                print("  python extract_to_db.py <html_file> <test_number>")
                print("  Example: python extract_to_db.py 3")
                print("  Example: python extract_to_db.py C20_Reading_Test_3.html 3")
                print("\nOr name your files 1.html, 2.html, etc. to run automatic scan: ")
                print("  python extract_to_db.py")
                return
            for f in html_files:
                test_num = int(f.replace('.html', ''))
                html_files_to_process.append((f, test_num))
            
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch()
        for file_name, test_num in html_files_to_process:
            try:
                await scrape_file(browser, file_name, test_num)
            except Exception as e:
                print(f"Error scraping file {file_name}: {e}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(extract_all())
