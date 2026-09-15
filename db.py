"""
Shared database connection for Supabase (Postgres).

Reads connection details from a .env file (never hardcode credentials
directly in your code -- .env stays on your machine and out of anything
you might ever share or upload).

Your .env file should look like this (see .env.example):

    SUPABASE_HOST=db.xxxxxxxxxxxx.supabase.co
    SUPABASE_PORT=5432
    SUPABASE_DBNAME=postgres
    SUPABASE_USER=postgres
    SUPABASE_PASSWORD=your-database-password
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """
    Opens a new connection to your Supabase Postgres database.
    Rows come back as dictionaries (row["column_name"]), matching how
    the app already reads data -- same pattern as sqlite3.Row before.
    """
    conn = psycopg2.connect(
        host=os.getenv("SUPABASE_HOST"),
        port=os.getenv("SUPABASE_PORT", "5432"),
        dbname=os.getenv("SUPABASE_DBNAME", "postgres"),
        user=os.getenv("SUPABASE_USER", "postgres"),
        password=os.getenv("SUPABASE_PASSWORD"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return conn
