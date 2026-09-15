"""
Run this once to create your tables in Supabase (Postgres).

How to run it:
    python create_database_postgres.py

Before running this:
1. Copy .env.example to a new file named ".env" in this same folder.
2. Fill in your real Supabase connection details (from your Supabase
   dashboard: Project Settings -> Database).
3. Run:  pip install psycopg2-binary python-dotenv
   (you likely already have python-dotenv from earlier)

This is safe to run more than once -- it only creates tables that
don't already exist, it never deletes anything.
"""

from db import get_connection

print("Connecting to your Supabase database...")
conn = get_connection()
cur = conn.cursor()
print("Connected!")

print("Reading db/schema_postgres.sql...")
with open("db/schema_postgres.sql", "r") as f:
    schema = f.read()

print("Creating tables...")
cur.execute(schema)
conn.commit()

# Check it worked
cur.execute(
    """
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
    """
)
tables = [row["table_name"] for row in cur.fetchall()]
print()
print("Success! Tables in your Supabase database:", tables)

cur.close()
conn.close()
