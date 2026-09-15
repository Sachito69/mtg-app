"""
Deck logic using Supabase.

A "real" card is one physically filed in your Collection (unsorted), a
binder, or a box. Cards already inside OTHER decks don't count as
available.

A "missing" card is a placeholder in a deck that is not backed by a
physical card.
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

BASIC_LAND_NAMES = {
    "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
    "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
    "Snow-Covered Mountain", "Snow-Covered Forest",
}


def _card_name(db, card_id):
    result = (
        db.table("card_catalog")
        .select("name")
        .eq("id", card_id)
        .limit(1)
        .execute()
    )
    return result.data[0]["name"] if result.data else None


def check_deck_legality(db, user_id, deck_id, format_name):
    rules = FORMAT_RULES.get(format_name)
    if rules is None:
        return None

    result = (
        db.table("collection_items")
        .select("card_id, quantity")
        .eq("user_id", user_id)
        .eq("container_id", deck_id)
        .execute()
    )

    totals = {}
    for item in result.data or []:
        name = _card_name(db, item["card_id"])
        if name:
            totals[name] = totals.get(name, 0) + item["quantity"]

    total_cards = sum(totals.values())
    copy_violations = []

    for name, qty in totals.items():
        if name in BASIC_LAND_NAMES:
            continue
        if qty > rules["max_copies"]:
            copy_violations.append({
                "name": name,
                "qty": qty,
                "max_allowed": rules["max_copies"],
            })

    if rules["deck_size_max"] is not None:
        size_ok = total_cards == rules["deck_size_max"]
        size_message = (
            f"{total_cards} / {rules['deck_size_max']} cards "
            f"(must be exactly {rules['deck_size_max']})"
        )
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


def find_real_sources(db, user_id, card_name):
    cards = (
        db.table("card_catalog")
        .select("id")
        .eq("name", card_name)
        .execute()
    )
    card_ids = [row["id"] for row in (cards.data or [])]
    if not card_ids:
        return []

    items = (
        db.table("collection_items")
        .select("id, quantity, card_id, container_id, added_at")
        .eq("user_id", user_id)
        .eq("is_missing", False)
        .in_("card_id", card_ids)
        .order("added_at")
        .execute()
    )

    containers = (
        db.table("containers")
        .select("id, name, kind")
        .eq("user_id", user_id)
        .execute()
    )
    container_map = {row["id"]: row for row in (containers.data or [])}

    sources = []
    for item in items.data or []:
        container_id = item.get("container_id")
        container = container_map.get(container_id) if container_id is not None else None

        # Unsorted, binder and box are valid physical sources.
        if container is not None and container.get("kind") not in ("binder", "box"):
            continue

        sources.append({
            "id": item["id"],
            "quantity": item["quantity"],
            "card_id": item["card_id"],
            "container_id": container_id,
            "container_name": container.get("name") if container else None,
        })

    return sources


def total_real_available(db, user_id, card_name):
    return sum(
        row["quantity"]
        for row in find_real_sources(db, user_id, card_name)
    )


def find_decks_missing_card(db, user_id, card_name, exclude_item_id=None):
    cards = (
        db.table("card_catalog")
        .select("id")
        .eq("name", card_name)
        .execute()
    )
    card_ids = [row["id"] for row in (cards.data or [])]
    if not card_ids:
        return []

    items = (
        db.table("collection_items")
        .select("id, quantity, container_id")
        .eq("user_id", user_id)
        .eq("is_missing", True)
        .in_("card_id", card_ids)
        .execute()
    )

    decks = (
        db.table("containers")
        .select("id, name, kind")
        .eq("user_id", user_id)
        .eq("kind", "deck")
        .execute()
    )
    deck_map = {row["id"]: row for row in (decks.data or [])}

    rows = []
    for item in items.data or []:
        if exclude_item_id is not None and item["id"] == exclude_item_id:
            continue

        deck = deck_map.get(item.get("container_id"))
        if not deck:
            continue

        rows.append({
            "missing_item_id": item["id"],
            "missing_qty": item["quantity"],
            "deck_id": deck["id"],
            "deck_name": deck["name"],
        })

    return rows


def fill_missing_in_deck(db, user_id, source_item_id, missing_item_id, quantity):
    source_result = (
        db.table("collection_items")
        .select("id, quantity, card_id, is_missing")
        .eq("user_id", user_id)
        .eq("id", source_item_id)
        .limit(1)
        .execute()
    )
    missing_result = (
        db.table("collection_items")
        .select("id, quantity, container_id, card_id, is_missing")
        .eq("user_id", user_id)
        .eq("id", missing_item_id)
        .limit(1)
        .execute()
    )

    if not source_result.data or not missing_result.data:
        return 0

    source = source_result.data[0]
    missing = missing_result.data[0]

    if source.get("is_missing") or not missing.get("is_missing"):
        return 0

    take = min(quantity, source["quantity"], missing["quantity"])
    if take <= 0:
        return 0

    new_source_qty = source["quantity"] - take
    if new_source_qty <= 0:
        (
            db.table("collection_items")
            .delete()
            .eq("user_id", user_id)
            .eq("id", source_item_id)
            .execute()
        )
    else:
        (
            db.table("collection_items")
            .update({"quantity": new_source_qty})
            .eq("user_id", user_id)
            .eq("id", source_item_id)
            .execute()
        )

    new_missing_qty = missing["quantity"] - take
    if new_missing_qty <= 0:
        (
            db.table("collection_items")
            .delete()
            .eq("user_id", user_id)
            .eq("id", missing_item_id)
            .execute()
        )
    else:
        (
            db.table("collection_items")
            .update({"quantity": new_missing_qty})
            .eq("user_id", user_id)
            .eq("id", missing_item_id)
            .execute()
        )

    deck_id = missing["container_id"]

    existing = (
        db.table("collection_items")
        .select("id, quantity")
        .eq("user_id", user_id)
        .eq("container_id", deck_id)
        .eq("card_id", source["card_id"])
        .eq("is_missing", False)
        .limit(1)
        .execute()
    )

    if existing.data:
        row = existing.data[0]
        (
            db.table("collection_items")
            .update({"quantity": row["quantity"] + take})
            .eq("user_id", user_id)
            .eq("id", row["id"])
            .execute()
        )
    else:
        (
            db.table("collection_items")
            .insert({
                "user_id": user_id,
                "card_id": source["card_id"],
                "quantity": take,
                "condition": "NM",
                "foil": False,
                "container_id": deck_id,
                "is_missing": False,
            })
            .execute()
        )

    return take


def move_real_into_deck(db, user_id, card_name, deck_id, quantity_wanted):
    sources = find_real_sources(db, user_id, card_name)
    remaining = quantity_wanted

    for row in sources:
        if remaining <= 0:
            break

        take = min(row["quantity"], remaining)
        new_qty = row["quantity"] - take

        if new_qty <= 0:
            (
                db.table("collection_items")
                .delete()
                .eq("user_id", user_id)
                .eq("id", row["id"])
                .execute()
            )
        else:
            (
                db.table("collection_items")
                .update({"quantity": new_qty})
                .eq("user_id", user_id)
                .eq("id", row["id"])
                .execute()
            )

        existing = (
            db.table("collection_items")
            .select("id, quantity")
            .eq("user_id", user_id)
            .eq("container_id", deck_id)
            .eq("card_id", row["card_id"])
            .eq("is_missing", False)
            .limit(1)
            .execute()
        )

        if existing.data:
            deck_item = existing.data[0]
            (
                db.table("collection_items")
                .update({"quantity": deck_item["quantity"] + take})
                .eq("user_id", user_id)
                .eq("id", deck_item["id"])
                .execute()
            )
        else:
            (
                db.table("collection_items")
                .insert({
                    "user_id": user_id,
                    "card_id": row["card_id"],
                    "quantity": take,
                    "condition": "NM",
                    "foil": False,
                    "container_id": deck_id,
                    "is_missing": False,
                })
                .execute()
            )

        remaining -= take

    return remaining
