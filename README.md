# IELTS Reading Test PDF Generator

A database-backed PDF generator system that extracts passages, questions, correct answers, and explanations from local HTML files into an SQLite database, and renders them into beautiful, book-style PDFs using a clean print template.

## Features

- **SQLite Database Integration**: Saves all extracted test content in plain text / structured HTML in an SQLite database (`quiz_data.db`).
- **Flexible Test Mapping**: Supports automatically scanning numbered HTML files, or mapping any custom HTML file to any test number in the database manually.
- **Premium Book Vibe Styling**: Formats reading passages with justified alignment, clean spacing, and modern typography.
- **Clean Printed Questions**: Hides scorecard summaries, mobile card border frames, question number squares, and browser radio selector circles to present a clean, print-ready exam sheet.
- **Consolidated Answer Key**: Gathers correct answers and detailed explanations into a clean, structured table at the end of the PDF, beginning on a new page.
- **Duplicate Prevention & Compact Layout**: Renders content efficiently to keep pages compact and organized (typically ~23 pages per test booklet).
- **All-PDFs Generation**: Generates PDF booklets for all tests stored in the database in a single command.

---

## File Structure

- **`database.py`**: Creates the SQLite tables (`tests`, `passages`, `questions`) and provides insert/query helper functions.
- **`extract_to_db.py`**: Scrapes HTML files in the directory and writes the structured data to `quiz_data.db`. Supports automatic scanning and custom manual arguments.
- **`generate_from_db.py`**: Queries the database, builds the book-style HTML template, and renders it to a PDF using Playwright. Supports single-test generation and all-tests generation.
- **`requirements.txt`**: Lists Python dependencies for this project.

---

## Installation & Setup

1. **Set up a Virtual Environment**:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

3. **Install Playwright Browsers**:
   ```powershell
   playwright install
   ```

---

## How to Run

### Step 1: Scrape HTML to Database

You can add tests to the database in the following ways:

#### Option A: main.html Clipboard Workflow (Recommended)
Paste any new test's review HTML source code directly into `main.html` in the project root directory. Then run:
```powershell
python extract_to_db.py
```
* **Auto-Update:** If the test title in `main.html` matches a test already in the database, the script will automatically overwrite and update that existing test.
* **Auto-Increment:** If it is a new test title, the script will automatically assign the next available test number (e.g., Test 3 if Tests 1 and 2 already exist) and insert it.

#### Option B: Manual Override using main.html
To force the contents of `main.html` to be saved under a specific test number (even if it's a new title or you want to overwrite a different test ID), specify the test number:
```powershell
python extract_to_db.py <test_number>
```
*Example:*
```powershell
python extract_to_db.py 2
```

#### Option C: Custom HTML Files & Backward Compatibility
To parse a custom HTML file and map it to a specific test number, run:
```powershell
python extract_to_db.py <html_file> <test_number>
```
*Example:*
```powershell
python extract_to_db.py C20_Reading_Test_3.html 3
```

#### Option D: Automatic Batch Scan of Numbered Files
If you have multiple numbered HTML files (e.g., `1.html`, `2.html`, etc.) and no `main.html` is present, running the script without arguments:
```powershell
python extract_to_db.py
```
scans all files matching `{number}.html` and inserts them as `Test {number}`.

---

### Step 2: Generate PDF from Database

#### Option A: Generate a Single PDF Booklet
To generate a book-style PDF booklet for a specific test number (e.g., Test 1) from the database:
```powershell
python generate_from_db.py 1
```
This generates the file: `Cambridge IELTS 21 Academic Reading Test 1.pdf`.

#### Option B: Generate All PDF Booklets at Once
To compile and generate booklets for all tests stored in the database at the same time:
```powershell
python generate_from_db.py all
```
This will loop through all test records in the SQLite database and output their respective PDF files.
