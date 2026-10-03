"""Finance Report Extractor entry point.

Usage:
    python main.py run --input "./laporan keuangan" --limit 5
    python main.py scan --input "./laporan keuangan"
    python main.py process
    python main.py export
    python main.py status
    python main.py inspect <document>
"""
from app.cli.commands import main

if __name__ == "__main__":
    main()
