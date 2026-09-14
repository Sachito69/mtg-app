"""
Looks up ONE card by name from Scryfall and saves it into card_catalog.

How to run it:
    python add_card.py "Lightning Bolt"

This is how cards will get added going forward: instead of downloading
Scryfall's entire database up front, we fetch and cache just the cards
you actually own or add, the moment you add them.
"""

import json
import re
import sqlite3
import sys
import urllib.request
import urllib.parse

DB_PATH = "db/mtg.sqlite3"

# Matches lines like: "1 Reckless Impulse (PLST) VOW-174"
#                       qty   name              set   number
BULK_LINE_PATTERN = re.compile(r"^\s*(\d+)\s+(.+?)\s+\(([A-Za-z0-9]+)\)\s+(\S+)\s*$")


def parse_bulk_line(line):
    """
    Parses one line of a bulk card list. Returns a dict with quantity,
    name, set_code, collector_number -- or None if the line doesn't
    match the expected format.
    """
    match = BULK_LINE_PATTERN.match(line)
    if not match:
        return None
    quantity, name, set_code, collector_number = match.groups()
    return {
        "quantity": int(quantity),
        "name": name,
        "set_code": set_code,
        "collector_number": collector_number,
    }

# Scryfall asks that requests identify themselves, or it rejects them.
REQUEST_HEADERS = {
    "User-Agent": "MTGCollectionApp/1.0",
    "Accept": "application/json",
}


def autocomplete_card_name(query):
    """Asks Scryfall for card name suggestions matching a partial name."""
    q = urllib.parse.urlencode({"q": query})
    url = f"https://api.scryfall.com/cards/autocomplete?{q}"
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        result = json.loads(response.read())
    return result.get("data", [])


def fetch_card_by_set_number(set_code, collector_number):
    """
    Gets one card's full data using its set code and collector number --
    the most precise way to identify an exact printing (used for bulk
    importing a list like "1 Sol Ring (MSC) 213").
    """
    url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def fetch_card_by_id(scryfall_id):
    """Gets one card's full data using its exact Scryfall id (no ambiguity)."""
    url = f"https://api.scryfall.com/cards/{scryfall_id}"
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def search_all_printings(name):
    """
    Finds every printing (every set/edition) of a card, by exact name.
    Returns a list of card entries, newest first.
    """
    query = urllib.parse.urlencode({
        "q": f'!"{name}"',
        "unique": "prints",
        "order": "released",
        "dir": "desc",
    })
    url = f"https://api.scryfall.com/cards/search?{query}"
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        result = json.loads(response.read())
    return result.get("data", [])


def fetch_card_by_name(name, set_code=None):
    """
    Asks Scryfall for one card, by (fuzzy) name.
    If set_code is given (e.g. "m11", "lea"), only that specific printing
    is returned -- otherwise Scryfall picks its default printing (usually
    the most recent one).
    """
    params = {"fuzzy": name}
    if set_code:
        params["set"] = set_code
    query = urllib.parse.urlencode(params)
    url = f"https://api.scryfall.com/cards/named?{query}"
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def get_colors(card):
    """
    Most cards list colors directly. Double-faced cards (two-sided cards)
    keep colors on each face instead -- this handles both cases so we
    don't crash on those.
    """
    if card.get("colors") is not None:
        return card["colors"]
    faces = card.get("card_faces")
    if faces:
        return faces[0].get("colors", [])
    return []


def save_card(card):
    """Inserts (or updates, if already saved) this card into card_catalog."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT OR REPLACE INTO card_catalog
            (id, oracle_id, name, set_code, set_name, image_url,
             colors, type_line, mana_cost, cmc, legalities, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card.get("id"),
            card.get("oracle_id"),
            card.get("name"),
            card.get("set"),
            card.get("set_name"),
            (card.get("image_uris") or {}).get("normal"),
            json.dumps(get_colors(card)),
            card.get("type_line"),
            card.get("mana_cost"),
            card.get("cmc"),
            json.dumps(card.get("legalities") or {}),
            card.get("released_at"),
        ),
    )
    conn.commit()
    conn.close()


def save_to_collection(card_id, quantity, condition, foil, container_id=None, is_missing=0):
    """
    Adds this card to your collection. If an identical entry already
    exists -- same exact printing, same container, same condition, same
    foil status, same real/missing status -- its quantity is increased
    instead of creating a duplicate row. Returns the row's id either way.
    """
    conn = sqlite3.connect(DB_PATH)
    foil_value = 1 if foil else 0

    existing = conn.execute(
        """
        SELECT id, quantity FROM collection_items
        WHERE card_id = ? AND condition = ? AND foil = ? AND is_missing = ?
          AND ((container_id IS NULL AND ? IS NULL) OR container_id = ?)
        """,
        (card_id, condition, foil_value, is_missing, container_id, container_id),
    ).fetchone()

    if existing:
        item_id, current_qty = existing
        conn.execute(
            "UPDATE collection_items SET quantity = ? WHERE id = ?", (current_qty + quantity, item_id)
        )
        conn.commit()
        conn.close()
        return item_id

    cursor = conn.execute(
        """
        INSERT INTO collection_items (card_id, quantity, condition, foil, container_id, is_missing)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (card_id, quantity, condition, foil_value, container_id, is_missing),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def ask_collection_details():
    """Asks the simple questions needed to log your copy of the card."""
    quantity_input = input("How many copies do you have? [default 1]: ").strip()
    quantity = int(quantity_input) if quantity_input else 1

    condition = input("Condition (NM/LP/MP/HP/DMG) [default NM]: ").strip().upper()
    if condition not in ("NM", "LP", "MP", "HP", "DMG"):
        condition = "NM"

    foil_input = input("Is it foil? (y/n) [default n]: ").strip().lower()
    foil = foil_input == "y"

    return quantity, condition, foil


def main():
    if len(sys.argv) < 2:
        print('Usage: python add_card.py "Card Name" [set_code]')
        print('Example: python add_card.py "Lightning Bolt" m11')
        return

    name = sys.argv[1]
    set_code = sys.argv[2] if len(sys.argv) > 2 else None

    if set_code:
        print(f"Looking up '{name}' from set '{set_code}' on Scryfall...")
    else:
        print(f"Looking up '{name}' on Scryfall (default printing)...")

    card = fetch_card_by_name(name, set_code)
    print(f"Found: {card['name']} ({card.get('set_name')})")

    save_card(card)
    print(f"Saved '{card['name']}' to the card catalog.")

    print()
    print("Now let's add it to your collection:")
    quantity, condition, foil = ask_collection_details()
    save_to_collection(card["id"], quantity, condition, foil)
    print()
    print(f"Added {quantity}x {card['name']} ({condition}{', foil' if foil else ''}) to your collection.")


if __name__ == "__main__":
    main()
