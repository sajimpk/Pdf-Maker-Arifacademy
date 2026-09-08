# PDF → Database → Reading books

এই workflow সরাসরি `Reading` ফোল্ডারের PDF থেকে structured SQLite database তৈরি করে।
তারপর শুধু সেই database পড়ে নতুন করে বই typeset করে। পুরোনো PDF পৃষ্ঠা বসানো হয় না।
Diagram দুটি আসল image asset হিসেবে database-এ রাখা হয়।

## এক কমান্ডে

```powershell
python -m pip install pymupdf reportlab
python reading_pipeline.py
```

এই workspace-এ প্রয়োজনীয় packages ইতিমধ্যে `.packages`-এ আছে। Windows-এর Georgia
ও Calibri font দিয়ে বই তৈরি হয়। অন্য কম্পিউটারে এই font files না থাকলে
`build_reading_books.py --font-dir <folder>` দিন।

ফলাফল:

- `reading_books.db`: ২৪ test, ৭২ passage, ২০৩ section, ৯৬০ question, answer ও explanation।
- `Reading_Books/`: Cambridge 16–21-এর ছয়টি বই; প্রতিটিতে চারটি test।
- `reading_books.import.json`: প্রতিটি PDF import-এর ফলাফল।
- `Reading_Books/generation_report.json`: page count এবং contents destinations।
- `Reading_Books/validation_report.json`: database এবং PDF validation।

বইয়ে cover, clickable contents, passage typography, MCQ options, matching lists,
numbered answer blanks, diagrams, flow-chart, answer sheets, running headers,
page numbers এবং শেষে answer explanations আছে।

## আলাদা ধাপে চালানো

```powershell
python import_reading_pdfs.py
python build_reading_books.py
python verify_reading_books.py
```

শুধু একটি test:

```powershell
python build_reading_books.py --book 20 --test 1
```

ডেটাবেসে সম্পাদনা করার পর PDF আবার তৈরি করতে, source re-import বাদ দিন:

```powershell
python reading_pipeline.py --from-db
```

`build_reading_books.py` source PDFs পড়ে না; database ও font files থাকলেই চলে।
একই book/test আবার import করলে একটি transaction-এ সেই test-এর আগের data বদলায়,
duplicate তৈরি করে না। Parsing ব্যর্থ হলে আগের test অক্ষত থাকে এবং command ব্যর্থ হয়।
Re-import করলে সেই test-এর database edits প্রতিস্থাপিত হবে। অন্য test বদলায় না।
আগে import করা test-এর PDF পরে input folder থেকে সরালেও database থেকে তা মোছে না।
একটি পুরো নতুন collection-এর জন্য আলাদা `--db` path ব্যবহার করুন।
একই নামে generated PDF থাকলে নতুন সফল build সেটি প্রতিস্থাপন করে।

## Database structure

| Table | কী থাকে |
|---|---|
| `tests` | Cambridge book/test number, filename, SHA-256, import time |
| `passages` | Title, complete text, paragraph metadata, source pages |
| `sections` | Passage link, question range/type, instructions, shared task text |
| `questions` | Individual number, prompt/context, multi-answer group, source pages |
| `options` | Shared option bank অথবা question-specific choices |
| `answers` | Source-এর correct answer, question-এর সঙ্গে যুক্ত |
| `explanations` | Source-এর explanation, question-এর সঙ্গে যুক্ত |
| `assets` | Diagram image bytes ও source page |
| `source_pages` | Audit-এর জন্য PDF-এর raw text ও text coordinates |
| `question_details` | Passage, question, answer, explanation একসঙ্গে দেখার SQL view |

উদাহরণ:

```sql
SELECT passage_number, question_type, question_number, prompt, answer, explanation
FROM question_details
WHERE book_number = 20 AND test_number = 1
ORDER BY question_number;
```

বইয়ের passage সম্পাদনা করতে `passages.title` ও `passages.content` বদলান। Paragraph
আলাদা থাকে double newline দিয়ে। Discrete question-এর জন্য `questions.prompt` এবং
`options.text` ব্যবহৃত হয়। Summary/notes-এর shared text থাকে `sections.content_json`-এ;
`{{24}}` মানে question 24-এর answer blank। এই shared task-এর individual prompt হলো
import-এর সময় পাওয়া context snapshot; বই বানানোর সময় shared text-ই authoritative।
Instructions থাকে `instructions_json`-এ। Answer ও explanation সংশ্লিষ্ট table থেকে পড়ে।

## যাচাই ও সীমা

Validator SQLite integrity, foreign keys, প্রতি test-এর 1–40 question coverage,
MCQ/shared option completeness, source-to-database vocabulary coverage, database-to-PDF
vocabulary coverage, bookmarks, blank pages ও text margins পরীক্ষা করে। Vocabulary
coverage হলো missing-word check; এটি একই শব্দের order বা অর্থ সঠিক হওয়ার পূর্ণ প্রমাণ নয়।
প্রতিনিধিত্বমূলক cover, contents, passage, matching, diagram, flow-chart ও answer পৃষ্ঠা
ছবিতে দেখে পরীক্ষা করা হয়েছে।

এটি এই folder-এর selectable-text PDF format-এর জন্য তৈরি importer; scanned PDFs-এর
OCR করে না। উৎসের spelling বা factual error নিজে থেকে সংশোধন করে না, এবং নতুন answer
বা explanation বানায় না। উৎসে থাকা একই option bank-এর exact duplicate একবার রাখা হয়।
Source PDFs এবং আগের `quiz_data.db` বদলায় না।
