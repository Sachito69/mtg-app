"""
Imports Scryfall's bulk card data into the local card_catalog table.

Run this with:  python3 import_scryfall.py

What it does, in order:
  1. Asks Scryfall "where is your latest bulk data file?"
  2. Downloads that file (it's large — a few hundred MB — so this can take a while)
  3. Reads through the file and inserts every card into card_catalog, in batches
     (batches are much faster than inserting one row at a time)

NOTE: step 1 and 2 require internet access. If you're running this somewhere
without internet, see import_from_file() below, which does step 3 only and
works on any local JSON file that matches Scryfall's format.
"""

import json
import sqlite3
import time
import urllib.request

DB_PATH = "db/mtg.sqlite3"
BULK_DATA_LIST_URL = "https://api.scryfall.com/bulk-data"
BATCH_SIZE = 500

# Scryfall asks that requests identify what app is calling them, and
# rejects requests that don't. This header is what fixes that.
REQUEST_HEADERS = {
    "User-Agent": "MTGCollectionApp/1.0",
    "Accept": "application/json",
}


def get_bulk_download_url(kind="default_cards"):
    """
    Ask Scryfall's API which file to download.
    'default_cards' = one entry per unique printing (what we want).
    Scryfall also updates this URL periodically, so we always ask fresh
    rather than hardcoding a link.
    """
    request = urllib.request.Request(BULK_DATA_LIST_URL, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        listing = json.loads(response.read())
    for entry in listing["data"]:
        if entry["type"] == kind:
            return entry["download_uri"], entry["size"]
    raise ValueError(f"Could not find bulk data of type '{kind}'")


def download_bulk_file(url, dest_path="db/scryfall_bulk.json"):
    """Downloads the bulk file to disk. Requires internet access."""
    print(f"Downloading {url} ...")
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        with open(dest_path, "wb") as out_file:
            # Read and save in chunks rather than all at once --
            # the file is a few hundred MB, so this is kinder to memory.
            while True:
                chunk = response.read(1024 * 1024)  # 1 MB at a time
                if not chunk:
                    break
                out_file.write(chunk)
    print(f"Saved to {dest_path}")
    return dest_path


def _card_to_row(card):
    """Pulls out just the fields our card_catalog table cares about."""
    return (
        card.get("id"),
        card.get("oracle_id"),
        card.get("name"),
        card.get("set"),
        card.get("set_name"),
        (card.get("image_uris") or {}).get("normal"),
        json.dumps(card.get("colors") or []),
        card.get("type_line"),
        card.get("mana_cost"),
        card.get("cmc"),
        json.dumps(card.get("legalities") or {}),
        card.get("released_at"),
    )


def import_from_file(json_path, db_path=DB_PATH, batch_size=BATCH_SIZE):
    """
    Reads a Scryfall-format JSON file (a list of card objects) and loads it
    into card_catalog, inserting in batches for speed.
    This part needs no internet — it just needs the JSON file to exist.
    """
    print(f"Reading {json_path} ...")
    with open(json_path, "r", encoding="utf-8") as f:
        cards = json.load(f)
    print(f"Found {len(cards)} cards to import.")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    insert_sql = """
        INSERT OR REPLACE INTO card_catalog
            (id, oracle_id, name, set_code, set_name, image_url,
             colors, type_line, mana_cost, cmc, legalities, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    start = time.time()
    batch = []
    inserted = 0
    for card in cards:
        batch.append(_card_to_row(card))
        if len(batch) >= batch_size:
            cur.executemany(insert_sql, batch)
            inserted += len(batch)
            batch = []
            print(f"  ...{inserted} cards imported so far")
    if batch:
        cur.executemany(insert_sql, batch)
        inserted += len(batch)

    conn.commit()
    elapsed = time.time() - start
    print(f"Done. Imported {inserted} cards in {elapsed:.2f} seconds.")

    conn.close()
    return inserted


def main():
    """Full real run: download from Scryfall, then import. Needs internet."""
    url, size = get_bulk_download_url("default_cards")
    print(f"Latest bulk file is {size / 1_000_000:.1f} MB")
    path = download_bulk_file(url)
    import_from_file(path)


if __name__ == "__main__":
    main()
