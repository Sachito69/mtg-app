"""
Diagnostic only -- checks whether your .env file is being found and
read correctly, without trying to connect to anything.

Run: python check_env.py
"""

import os
from dotenv import load_dotenv, find_dotenv

path = find_dotenv(usecwd=True)
print("Looking for a .env file...")
if path:
    print(f"Found it at: {path}")
else:
    print("Could NOT find a .env file in this folder (or any parent folder).")
    print("Make sure a file named exactly '.env' (not '.env.txt' or '.env.example') exists here.")

load_dotenv()

print()
print("Values currently loaded:")
print("  SUPABASE_HOST     =", repr(os.getenv("SUPABASE_HOST")))
print("  SUPABASE_PORT     =", repr(os.getenv("SUPABASE_PORT")))
print("  SUPABASE_DBNAME   =", repr(os.getenv("SUPABASE_DBNAME")))
print("  SUPABASE_USER     =", repr(os.getenv("SUPABASE_USER")))
print("  SUPABASE_PASSWORD =", "*** (set)" if os.getenv("SUPABASE_PASSWORD") else repr(None))

print()
print("Raw bytes of the .env file (first 200 bytes), to catch empty files or odd encodings:")
if path:
    with open(path, "rb") as f:
        raw = f.read(200)
    print(repr(raw))
    if len(raw) == 0:
        print(">>> The file is EMPTY. Open it and paste your real values in.")
    elif raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        print(">>> This file was saved in UTF-16 (common with Notepad's default 'Save As' encoding).")
        print(">>> Re-save it choosing 'UTF-8' as the encoding, not 'Unicode' or 'ANSI'.")
