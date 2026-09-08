# IELTS Reading, Listening, Writing & Speaking Book Maker

মূল PDF থেকে passage/part, question section, প্রশ্ন, options, উত্তর ও explanation
আলাদা SQLite database-এ রাখা হয়। তারপর সেই database থেকে বইয়ের মতো নতুন PDF তৈরি হয়।
Listening বইতে transcript ও map থাকে; **audio link বা QR code থাকে না।**

## বর্তমান collection

| বিষয় | Source tests | Database | তৈরি বই |
|---|---:|---|---|
| Reading | ২৪টি — Cambridge 16–21 | `reading_books.db` | `Reading_Books/`-এ ৬টি বই |
| Listening | ১৬টি — Cambridge 18–21 | `listening_books.db` | `Listening_Books/`-এ ৪টি বই |
| Writing | ২৪টি — Cambridge 16–21 | `writing_books.db` | `Writing_Books/`-এ ৬টি বই |
| Speaking | ২৪টি — Cambridge 16–21 | `speaking_books.db` | `Speaking_Books/`-এ ৬টি বই |

প্রতিটি পূর্ণ বইতে চারটি test থাকে। Reading-এ ৭২টি passage ও ৯৬০টি প্রশ্ন;
Listening-এ ৬৪টি part, ৬৪টি transcript ও ৬৪০টি প্রশ্ন আছে।

বইয়ের বৈশিষ্ট্য: cover, clickable সূচিপত্র, page number, সুন্দর paragraph layout,
বিষয় অনুযায়ী answer blank, MCQ/matching options, table/diagram, cue card ও লেখার জায়গা।
Reading/Listening-এ source-এর উত্তর ও explanation থাকে; Writing/Speaking-এর source-এ
উত্তর নেই বলে ওই বইগুলোতে sample answer যোগ করা হয়নি।

## Setup

Project folder থেকে PowerShell-এ চালান:

```powershell
python -m pip install -r requirements.txt
```

এই workspace-এ dependencies `.packages/`-এ আছে; scriptগুলো সেই folder থাকলে ব্যবহার করে।
PDF তৈরিতে Windows-এর **Georgia ও Calibri** font ব্যবহার হয়। অন্য জায়গায় font files
থাকলে builder command-এ `--font-dir "path/to/fonts"` দিন।

## এক কমান্ডে বই তৈরি

Reading:

```powershell
python reading_pipeline.py
```

Listening:

```powershell
python listening_pipeline.py
```

Writing ও Speaking একসঙ্গে:

```powershell
python writing_speaking_pipeline.py
```

শুধু একটি বিষয়ের জন্য `--subject writing` অথবা `--subject speaking` দিন।
সব pipeline source PDF import → database → PDF build → validation চালায়।

## Database সম্পাদনার পর

Source PDF আবার import না করে database-এর পরিবর্তন থেকে বই তৈরি করুন:

```powershell
python reading_pipeline.py --from-db
python listening_pipeline.py --from-db
python writing_speaking_pipeline.py --from-db
```

সাধারণ pipeline command আবার চালালে একই test-এর database data source PDF দিয়ে
প্রতিস্থাপিত হয়। Manual database edits ধরে রাখতে `--from-db` ব্যবহার করুন।
সফল build একই নামের generated PDF প্রতিস্থাপন করে; source PDF বদলায় না।

## একটি বই বা test তৈরি

```powershell
python build_reading_books.py --book 20
python build_reading_books.py --book 20 --test 1
python build_listening_books.py --book 20
python build_listening_books.py --book 20 --test 1
python writing_speaking_pipeline.py --from-db --subject writing --book 20 --test 1
python writing_speaking_pipeline.py --from-db --subject speaking --book 20 --test 1
```

এই commandগুলো existing database পড়ে; source import করে না। `--test` দিলে
একটি test-এর আলাদা PDF তৈরি হয়, না দিলে ওই Cambridge বইয়ের সব imported test থাকে।

## আলাদা folder বা database ব্যবহার

```powershell
python reading_pipeline.py --input Reading --db reading_books.db --output Reading_Books
python listening_pipeline.py --input Listening --db listening_books.db --output Listening_Books
```

## প্রয়োজনীয় script

| Reading | Listening | কাজ |
|---|---|---|
| `reading_pipeline.py` | `listening_pipeline.py` | পুরো workflow চালানো |
| `reading_store.py` | `listening_store.py` | Database schema ও connection |
| `import_reading_pdfs.py` | `import_listening_pdfs.py` | PDF থেকে structured data import |
| `build_reading_books.py` | `build_listening_books.py` | Database থেকে বই typeset করা |
| `verify_reading_books.py` | `verify_listening_books.py` | Database ও PDF যাচাই |

`writing_speaking_pipeline.py` Writing/Speaking-এর schema, import, build ও validation
পরিচালনা করে। Shared helpers ও layout-এর জন্য মোট ১১টি script একই folder-এ রাখুন।

## অন্যান্য ফাইল ও folder

| Files / folders | Purpose |
|---|---|
| `Reading/`, `Listening/` | Pipeline source PDFs |
| `Speaking/`, `Writing/` | Writing/Speaking source PDFs |
| `Reading_Books/`, `Listening_Books/` | Final books, samples and validation reports |
| `reading_books.db`, `listening_books.db` | Structured databases |
| `Writing_Books/`, `Speaking_Books/` | Writing/Speaking books and reports |
| `writing_books.db`, `speaking_books.db` | Writing/Speaking structured databases |
| `*.import.json` | Per-file import reports |
| `.packages/`, `env/` | Dependencies and local environment |
| `archive/` | Original reference PDFs and legacy HTML source |

## Git-এ কী থাকবে

`.gitignore` source ও generated PDF, চার বিষয়ের generated output folder, database,
import report, Python cache, local environment ও temporary file বাদ দেয়।
Scripts, Markdown documentation ও `requirements.txt` Git-এ রাখা যাবে।
নতুন clone-এ source PDF-গুলো নিজে `Reading/`, `Listening/`, `Writing/`, `Speaking/`
folder-এ রাখতে হবে; তারপর setup ও pipeline command চালান।

আগে থেকে tracked file শুধু `.gitignore` যোগ করলে untrack হয় না।

## Validation ও reports

```powershell
python verify_reading_books.py
python verify_listening_books.py
```

- `reading_books.import.json` / `listening_books.import.json`: প্রতিটি source import-এর ফল।
- Output folder-এর `generation_report.json`: তৈরি বই, page count ও সূচিপত্রের destinations।
- Output folder-এর `validation_report.json`: validation-এর ফল ও পাওয়া errors।

Validation database integrity, প্রশ্নের coverage, options, লেখা সংরক্ষণ ও PDF margin
পরীক্ষা করে। Listening-এর ক্ষেত্রে transcript-এর শব্দ/ক্রম এবং external link না থাকাও
পরীক্ষা করে। এটি source material-এর factual correctness যাচাই করে না।

## সীমা ও বিস্তারিত নির্দেশনা

Importer এই collection-এর selectable-text PDF format-এর জন্য তৈরি। Scanned PDF-এর
OCR করে না এবং নিজে থেকে নতুন answer, explanation বা transcript বানায় না।

Database structure ও কোন field সম্পাদনা করতে হবে:
[Reading নির্দেশনা](READING_BOOKS.md) / [Listening নির্দেশনা](LISTENING_BOOKS.md)।

## Writing ও Speaking

Reading/Listening-এর একই cover, font, clickable সূচিপত্র ও page numbering ব্যবহার হয়।
Cambridge 16–21-এর ২৪টি করে test থেকে `Writing_Books/` ও `Speaking_Books/`-এ
৬টি করে বই তৈরি হয়। Writing-এ ৪৮টি task, ২৪টি chart image ও লেখার জায়গা;
Speaking-এ ৭২টি part, ২৬৪টি প্রশ্ন, cue card ও notes-এর জায়গা আছে।
Source PDF-এ sample answer/explanation নেই, তাই বানানো উত্তর যোগ করা হয়নি।

```powershell
python writing_speaking_pipeline.py
python writing_speaking_pipeline.py --subject writing
python writing_speaking_pipeline.py --subject speaking
python writing_speaking_pipeline.py --from-db
python writing_speaking_pipeline.py --from-db --subject writing --book 20 --test 1
python writing_speaking_pipeline.py --from-db --subject speaking --book 20 --test 1
```

নতুন প্রয়োজনীয় script শুধু `writing_speaking_pipeline.py`; এটি shared layout-এর জন্য
`build_reading_books.py` ব্যবহার করে। `--font-dir`-ও সমর্থিত। মোট ১১টি script রাখুন।

`writing_books.db` ও `speaking_books.db`-এর tables: `tests`, `sections`, `questions`,
`assets`। `questions.prompt`-এ প্রশ্ন, `sample_answer` ও `explanation`-এ ঐচ্ছিক
উত্তর/ব্যাখ্যা; শেষের দুই field শুরুতে NULL থাকে। `assets.image`-এ chart bytes থাকে।
তাই `--from-db` দিয়ে বই বানাতে source PDF লাগে না। উত্তর/ব্যাখ্যা যোগ করলে
সেগুলো সংশ্লিষ্ট প্রশ্নের নিচে ছাপা হবে। Prompt-এর শব্দ/ক্রম archived source-এর সঙ্গে
মেলানো হয়; prompt বদলালে validation ব্যর্থ হবে। সাধারণ command source আবার import
করে database edits প্রতিস্থাপন করে; edits রাখতে `--from-db` ব্যবহার করুন।

প্রতিবার database integrity, source থেকে prompt-এর শব্দক্রম, PDF-এ সম্পূর্ণ prompt,
chart image count, bookmarks, blank page, page boundary ও external link পরীক্ষা হয়।
Image count chart-এর visual accuracy প্রমাণ করে না; factual correctness যাচাই হয় না।
Output folder-এ `generation_report.json` ও `validation_report.json`, root-এ
`writing_books.import.json` ও `speaking_books.import.json` থাকে।
