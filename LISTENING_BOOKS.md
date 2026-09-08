# Listening PDF → database → books

```powershell
python listening_pipeline.py
```

`Listening` ফোল্ডারের ১৬টি PDF থেকে `listening_books.db` তৈরি হয়। তারপর database থেকেই
`Listening_Books`-এ Cambridge 18–21-এর চারটি বই তৈরি হয়, প্রতিটিতে চারটি test।

বইতে cover, clickable contents, চারটি Listening part, MCQ, matching, map, multi-column
table, answer sheet, answer explanations এবং সম্পূর্ণ transcript থাকে। **Audio link বা
QR code নেই।** Source-এর audio notice ও URL database import-এর সময় বাদ দেওয়া হয়।
মূল source PDF এবং diagnostics অপরিবর্তিত থাকে।

## Commands

প্রয়োজন হলে dependency install:

```powershell
python -m pip install pymupdf reportlab
```

এই workspace-এ `.packages` ইতিমধ্যে প্রস্তুত। Reading-এর মতোই Windows-এর Georgia ও
Calibri font ব্যবহৃত হয়। অন্য font location হলে builder-এ `--font-dir` দিন।

```powershell
python import_listening_pdfs.py
python build_listening_books.py
python verify_listening_books.py
```

একটি test-এর নমুনা:

```powershell
python build_listening_books.py --book 20 --test 1
```

Database edit-এর পরে source PDF re-import না করে বই বানাতে:

```powershell
python listening_pipeline.py --from-db
```

Re-import একই book/test-এর record transaction-এ প্রতিস্থাপন করে; duplicate তৈরি করে না।
সে test-এ করা manual database edits re-import করলে বদলে যাবে। Parsing ব্যর্থ হলে আগের
test-এর data অক্ষত থাকে। PDF সফলভাবে তৈরি হলে আগের একই নামের generated PDF বদলায়।
Input folder থেকে PDF সরালে আগে import করা database record নিজে থেকে মোছে না।

## Database

| Table | Content |
|---|---|
| `tests` | Book/test number, source filename ও SHA-256 |
| `parts` | চারটি Listening part |
| `sections` | Question range/type, instructions ও shared task content |
| `questions` | Individual number, prompt/context ও answer group |
| `options` | MCQ choices ও matching option banks |
| `answers` | Source-এর correct answers |
| `explanations` | Source-এর explanation text |
| `transcripts` | প্রতি part-এর transcript ও paragraph/speaker metadata |
| `assets` | চারটি source map-এর image bytes |
| `source_pages` | Audio notice বাদে source text ও coordinates |
| `question_details` | Part, question, answer ও explanation-এর joined view |

```sql
SELECT part_number, question_type, question_number, prompt, answer, explanation
FROM question_details
WHERE book_number = 20 AND test_number = 1
ORDER BY question_number;
```

Discrete questions-এর জন্য `questions.prompt`, choices-এর জন্য `options.text`, answer ও
explanation সংশ্লিষ্ট table-এ সম্পাদনা করুন। Note/form/table-এর canonical text থাকে
`sections.content_json`-এ; `{{7}}` মানে question 7-এর answer blank। Table node-এ `rows`
একটি two-dimensional cell array; column ও row-এর সম্পর্ক বজায় রেখে সম্পাদনা করুন।
Individual completion question-এর prompt হলো import-time context snapshot।
Transcript-এর authoritative text হলো `transcripts.content`; double newline দিয়ে
speaker turn/paragraph আলাদা থাকে। Builder source PDF পড়ে না।

## Verification

`Listening_Books/validation_report.json`-এ SQLite integrity, 1–40 question coverage,
MCQ/matching options, map assets, source-to-database task vocabulary coverage,
transcript-এর শব্দ ও ক্রম, PDF vocabulary coverage, text margins, bookmarks এবং audio
URL/external links না থাকার ফল থাকে। Vocabulary check সম্পূর্ণ semantic correctness-এর
প্রমাণ নয়; গুরুত্বপূর্ণ table/map ও অন্যান্য পৃষ্ঠা ছবিতেও পর্যালোচনা করা হয়েছে।

Importer এই selectable-text source format-এর জন্য তৈরি। Scanned PDF-এর OCR করে না,
উৎসের ভুল বানান নিজে থেকে সংশোধন করে না, নতুন explanation বা transcript বানায় না।
Recording download বা audio verification করে না।
