"""
TEST-ONLY script. Generates a fake bulk-data file shaped exactly like
Scryfall's real one, so we can test import_scryfall.py without internet
access. This is NOT part of the real app -- it exists only to prove the
import logic works correctly before running it against the real download.
"""

import json
import random
import uuid

REAL_CARD_NAMES = [
    "Lightning Bolt", "Lightning Strike", "Goblin Guide", "Monastery Swiftspear",
    "Thoughtseize", "Tarmogoyf", "Snapcaster Mage", "Fatal Push", "Noble Hierarch",
    "Ragavan, Nimble Pilferer", "Serra Angel", "Shivan Dragon", "Air Elemental",
    "Counterspell", "Swords to Plowshares", "Dark Ritual", "Giant Growth",
    "Llanowar Elves", "Birds of Paradise", "Wrath of God", "Doom Blade",
    "Brainstorm", "Ponder", "Mana Leak", "Path to Exile", "Lava Spike",
    "Embercleave", "Cryptic Command", "Solitude", "Fury", "Grief",
]
SET_CODES = ["lea", "leb", "2ed", "m19", "m20", "znr", "khm", "mid", "vow", "neo"]
COLOR_OPTIONS = [["W"], ["U"], ["B"], ["R"], ["G"], ["W", "U"], []]
TYPES = ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Land"]

def make_fake_card():
    name = random.choice(REAL_CARD_NAMES)
    set_code = random.choice(SET_CODES)
    colors = random.choice(COLOR_OPTIONS)
    oracle_id = str(uuid.uuid4())
    return {
        "id": str(uuid.uuid4()),
        "oracle_id": oracle_id,
        "name": name,
        "set": set_code,
        "set_name": f"Test Set {set_code.upper()}",
        "image_uris": {"normal": f"https://cards.scryfall.io/normal/{set_code}/{oracle_id}.jpg"},
        "colors": colors,
        "type_line": random.choice(TYPES),
        "mana_cost": "{1}{R}",
        "cmc": round(random.uniform(0, 6), 1),
        "legalities": {
            "standard": random.choice(["legal", "not_legal"]),
            "modern": "legal",
            "commander": "legal",
        },
        "released_at": "2020-01-01",
    }

if __name__ == "__main__":
    count = 12000  # comfortably over the 10,000+ target
    cards = [make_fake_card() for _ in range(count)]
    with open("db/test_bulk_data.json", "w") as f:
        json.dump(cards, f)
    print(f"Generated {count} test card records into db/test_bulk_data.json")
