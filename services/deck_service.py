TYPE_ORDER = ["Creature", "Planeswalker", "Instant", "Sorcery", "Artifact", "Enchantment", "Land", "Battle"]

def group_cards_by_type(cards):
    groups = {}
    priority = ("Creature", "Land", "Planeswalker", "Instant", "Sorcery",
                "Artifact", "Enchantment", "Battle")
    for card in cards:
        type_line = card.get("type_line") or ""
        primary_type = next((t for t in priority if t in type_line), "Other")
        groups.setdefault(primary_type, []).append(card)

    order = list(priority)
    def sort_key(type_name):
        return (order.index(type_name), "") if type_name in order else (len(order), type_name)

    return [
        {
            "type_name": name,
            "cards": groups[name],
            "count": sum(card.get("quantity", 0) for card in groups[name]),
        }
        for name in sorted(groups.keys(), key=sort_key)
    ]
