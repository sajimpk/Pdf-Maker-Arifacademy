"""One command: PDF -> structured SQLite -> typeset books -> validation."""
import argparse
from pathlib import Path
import subprocess
import sys
from reading_store import ROOT, DEFAULT_DB


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'Reading')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=ROOT / 'Reading_Books')
    parser.add_argument('--from-db', action='store_true', help='Keep database edits; skip PDF re-import')
    args = parser.parse_args()
    if not args.from_db:
        subprocess.run([sys.executable, str(ROOT / 'import_reading_pdfs.py'), '--input', str(args.input), '--db', str(args.db)], check=True)
    subprocess.run([sys.executable, str(ROOT / 'build_reading_books.py'), '--db', str(args.db), '--output', str(args.output)], check=True)
    subprocess.run([sys.executable, str(ROOT / 'verify_reading_books.py'), '--db', str(args.db), '--output', str(args.output)], check=True)
    print(f'Complete. Database: {args.db}\nBooks: {args.output}')


if __name__ == '__main__':
    main()
