"""
Run this once to create the database and the card_catalog table.

How to run it:
    python create_database.py

That's it -- no other commands needed. This script reads schema.sql
and uses it to build db/mtg.sqlite3.
"""

import sqlite3
import os

# Make sure the db folder exists
os.makedirs("db", exist_ok=True)

print("Connecting to database (this creates the file if it doesn't exist yet)...")
conn = sqlite3.connect("db/mtg.sqlite3")

print("Reading schema.sql...")
with open("db/schema.sql", "r") as f:
    schema = f.read()

print("Creating the card_catalog table...")
conn.executescript(schema)
conn.commit()

# --- Safe migration ---
# collection_items already existed before "containers" was invented, so we
# can't just redefine it in schema.sql -- SQLite won't retroactively add a
# column to a table that already exists. This checks whether the column is
# missing and adds it if needed, without touching any rows already there.
existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(collection_items)")]
migrated_anything = False

if "container_id" not in existing_columns:
    print("Updating collection_items to support containers (existing cards are untouched)...")
    conn.execute("ALTER TABLE collection_items ADD COLUMN container_id INTEGER REFERENCES containers(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_collection_items_container_id ON collection_items(container_id)")
    conn.commit()
    migrated_anything = True

if "is_missing" not in existing_columns:
    print("Updating collection_items to support deck placeholders ('missing' cards)...")
    conn.execute("ALTER TABLE collection_items ADD COLUMN is_missing INTEGER DEFAULT 0")
    conn.commit()
    migrated_anything = True

if not migrated_anything:
    print("collection_items already up to date, nothing to migrate.")

# The old deck_blueprint table is no longer used -- deck logic was
# redesigned to check your real collection directly instead.
had_blueprint_table = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='deck_blueprint'"
).fetchone()
if had_blueprint_table:
    print("Removing the old deck_blueprint table (replaced by the new deck logic)...")
    conn.execute("DROP TABLE deck_blueprint")
    conn.commit()

# Consolidate any duplicate collection_items rows (same exact printing,
# same container, same condition, same foil, same real/missing status) --
# these could pile up from before cards were merged automatically, and
# crowd the Card Tracker with near-identical tiles.
duplicate_groups = conn.execute(
    """
    SELECT card_id, container_id, condition, foil, is_missing, COUNT(*) as row_count, MIN(id) as keep_id
    FROM collection_items
    GROUP BY card_id, container_id, condition, foil, is_missing
    HAVING COUNT(*) > 1
    """
).fetchall()

if duplicate_groups:
    print(f"Consolidating {len(duplicate_groups)} group(s) of duplicate card entries...")
    for group in duplicate_groups:
        card_id, container_id, condition, foil, is_missing, row_count, keep_id = group
        rows = conn.execute(
            """
            SELECT id, quantity FROM collection_items
            WHERE card_id = ? AND condition = ? AND foil = ? AND is_missing = ?
              AND ((container_id IS NULL AND ? IS NULL) OR container_id = ?)
            """,
            (card_id, condition, foil, is_missing, container_id, container_id),
        ).fetchall()
        total_qty = sum(r[1] for r in rows)
        duplicate_ids = [r[0] for r in rows if r[0] != keep_id]

        conn.execute("UPDATE collection_items SET quantity = ? WHERE id = ?", (total_qty, keep_id))
        for dup_id in duplicate_ids:
            # Any loan pointing at a row we're about to remove gets moved
            # to the surviving row instead, so the loan isn't lost.
            conn.execute(
                "UPDATE loans SET collection_item_id = ? WHERE collection_item_id = ?", (keep_id, dup_id)
            )
            conn.execute("DELETE FROM collection_items WHERE id = ?", (dup_id,))
    conn.commit()

# Check it worked
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print()
print("Success! Tables in the database:", tables)

conn.close()
