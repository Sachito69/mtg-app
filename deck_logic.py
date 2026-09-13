"""
Deck logic: figuring out what's "real" and what's "missing" in a deck.

A "real" card is one physically filed in your Collection (unsorted), a
binder, or a box. Cards already inside OTHER decks don't count as
available -- keeping this simple, decks don't steal from each other.

A "missing" card is a placeholder: it shows in the deck (with the card's
name and image) so you can see what you still need, but it isn't backed
by a physical card anywhere.
"""


FORMAT_RULES = {
    "Standard":  {"deck_size_min": 60,  "deck_size_max": None, "max_copies": 4, "sideboard_size": 15},
    "Pioneer":   {"deck_size_min": 60,  "deck_size_max": None, "max_copies": 4, "sideboard_size": 15},
    "Modern":    {"deck_size_min": 60,  "deck_size_max": None, "max_copies": 4, "sideboard_size": 15},
    "Legacy":    {"deck_size_min": 60,  "deck_size_max": None, "max_copies": 4, "sideboard_size": 15},
    "Vintage":   {"deck_size_min": 60,  "deck_size_max": None, "max_copies": 4, "sideboard_size": 15},
    "Pauper":    {"deck_size_min": 60,  "deck_size_max": None, "max_copies": 4, "sideboard_size": 15},
    "Commander": {"deck_size_min": 100, "deck_size_max": 100,  "max_copies": 1, "sideboard_size": 0},
}

# Basic lands are exempt from copy limits in every format.
BASIC_LAND_NAMES = {
    "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
    "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
    "Snow-Covered Mountain", "Snow-Covered Forest",
}


def check_deck_legality(conn, deck_id, format_name):
    """
    Checks a deck's card counts against its format's rules: deck size
    and max copies per card (basic lands are exempt from copy limits).
    Returns None if the format has no known rules (e.g. "Casual").
    """
    rules = FORMAT_RULES.get(format_name)
    if rules is None:
        return None

    rows = conn.execute(
        """
        SELECT card_catalog.name, SUM(collection_items.quantity) as total_qty
        FROM collection_items
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE collection_items.container_id = ?
        GROUP BY card_catalog.name
        """,
        (deck_id,),
    ).fetchall()

    total_cards = sum(r["total_qty"] for r in rows)

    copy_violations = []
    for r in rows:
        if r["name"] in BASIC_LAND_NAMES:
            continue
        if r["total_qty"] > rules["max_copies"]:
            copy_violations.append({"name": r["name"], "qty": r["total_qty"], "max_allowed": rules["max_copies"]})

    if rules["deck_size_max"] is not None:
        size_ok = total_cards == rules["deck_size_max"]
        size_message = f"{total_cards} / {rules['deck_size_max']} cards (must be exactly {rules['deck_size_max']})"
    else:
        size_ok = total_cards >= rules["deck_size_min"]
        size_message = f"{total_cards} cards (minimum {rules['deck_size_min']})"

    return {
        "rules": rules,
        "total_cards": total_cards,
        "size_ok": size_ok,
        "size_message": size_message,
        "copy_violations": copy_violations,
    }


def find_real_sources(conn, card_name):
    """
    Finds every real (non-deck, non-missing) copy of a card by name,
    across your whole collection. Returns a list of rows, each with the
    collection_items id, how many are there, and which container they're in.
    """
    return conn.execute(
        """
        SELECT collection_items.id, collection_items.quantity, collection_items.card_id,
               containers.id as container_id, containers.name as container_name
        FROM collection_items
        LEFT JOIN containers ON collection_items.container_id = containers.id
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE card_catalog.name = ?
          AND collection_items.is_missing = 0
          AND (containers.kind IS NULL OR containers.kind IN ('binder', 'box'))
        ORDER BY collection_items.added_at ASC
        """,
        (card_name,),
    ).fetchall()


def total_real_available(conn, card_name):
    """Just the total count, for a quick check before showing a confirmation."""
    sources = find_real_sources(conn, card_name)
    return sum(row["quantity"] for row in sources)


def find_decks_missing_card(conn, card_name, exclude_item_id=None):
    """
    Finds every deck that currently has a MISSING placeholder for this
    card (by name), and how much of it is still missing.
    """
    rows = conn.execute(
        """
        SELECT collection_items.id as missing_item_id, collection_items.quantity as missing_qty,
               containers.id as deck_id, containers.name as deck_name
        FROM collection_items
        JOIN containers ON collection_items.container_id = containers.id
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE collection_items.is_missing = 1 AND containers.kind = 'deck' AND card_catalog.name = ?
        """,
        (card_name,),
    ).fetchall()
    if exclude_item_id is not None:
        rows = [r for r in rows if r["missing_item_id"] != exclude_item_id]
    return rows


def fill_missing_in_deck(conn, source_item_id, missing_item_id, quantity):
    """
    Moves `quantity` real copies from source_item_id (wherever it
    currently sits -- collection/binder/box) into the deck that owns
    missing_item_id, shrinking or removing that missing placeholder to match.
    Returns how many copies were actually moved.
    """
    source = conn.execute(
        "SELECT quantity, card_id FROM collection_items WHERE id = ?", (source_item_id,)
    ).fetchone()
    missing = conn.execute(
        "SELECT quantity, container_id, card_id FROM collection_items WHERE id = ?", (missing_item_id,)
    ).fetchone()
    if source is None or missing is None:
        return 0

    take = min(quantity, source["quantity"], missing["quantity"])
    if take <= 0:
        return 0

    new_source_qty = source["quantity"] - take
    if new_source_qty <= 0:
        conn.execute("DELETE FROM collection_items WHERE id = ?", (source_item_id,))
    else:
        conn.execute("UPDATE collection_items SET quantity = ? WHERE id = ?", (new_source_qty, source_item_id))

    new_missing_qty = missing["quantity"] - take
    if new_missing_qty <= 0:
        conn.execute("DELETE FROM collection_items WHERE id = ?", (missing_item_id,))
    else:
        conn.execute("UPDATE collection_items SET quantity = ? WHERE id = ?", (new_missing_qty, missing_item_id))

    deck_id = missing["container_id"]
    existing_real = conn.execute(
        "SELECT id, quantity FROM collection_items WHERE container_id = ? AND card_id = ? AND is_missing = 0",
        (deck_id, source["card_id"]),
    ).fetchone()
    if existing_real:
        conn.execute(
            "UPDATE collection_items SET quantity = ? WHERE id = ?",
            (existing_real["quantity"] + take, existing_real["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO collection_items (card_id, quantity, condition, foil, container_id, is_missing) "
            "VALUES (?, ?, 'NM', 0, ?, 0)",
            (source["card_id"], take, deck_id),
        )

    conn.commit()
    return take


def move_real_into_deck(conn, card_name, deck_id, quantity_wanted):
    """
    Moves up to quantity_wanted real copies of a card into the deck,
    pulling from binders/boxes/unsorted collection (oldest first).
    Whatever can't be covered by real copies is left for the caller to
    add as a "missing" placeholder.
    """
    sources = find_real_sources(conn, card_name)
    remaining = quantity_wanted

    for row in sources:
        if remaining <= 0:
            break
        take = min(row["quantity"], remaining)
        new_qty = row["quantity"] - take

        if new_qty <= 0:
            conn.execute("DELETE FROM collection_items WHERE id = ?", (row["id"],))
        else:
            conn.execute("UPDATE collection_items SET quantity = ? WHERE id = ?", (new_qty, row["id"]))

        existing_in_deck = conn.execute(
            "SELECT id, quantity FROM collection_items WHERE container_id = ? AND card_id = ? AND is_missing = 0",
            (deck_id, row["card_id"]),
        ).fetchone()
        if existing_in_deck:
            conn.execute(
                "UPDATE collection_items SET quantity = ? WHERE id = ?",
                (existing_in_deck["quantity"] + take, existing_in_deck["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO collection_items (card_id, quantity, condition, foil, container_id, is_missing) "
                "VALUES (?, ?, 'NM', 0, ?, 0)",
                (row["card_id"], take, deck_id),
            )
        remaining -= take

    conn.commit()
    return remaining  # whatever's left uncovered by real copies
