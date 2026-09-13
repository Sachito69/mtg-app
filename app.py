"""
A simple webpage that shows everything in your collection.

How to run it:
    python app.py

Then open a web browser and go to:
    http://127.0.0.1:5000

Press Ctrl+C in the terminal to stop it when you're done.
"""

from flask import Flask, render_template_string, request, redirect, jsonify
import sqlite3
from add_card import search_all_printings, fetch_card_by_id, fetch_card_by_set_number, parse_bulk_line, save_card, save_to_collection
from deck_logic import find_real_sources, total_real_available, move_real_into_deck, find_decks_missing_card, fill_missing_in_deck, check_deck_legality, FORMAT_RULES

app = Flask(__name__)

# The order deck cards are grouped in -- matches how most players sort a
# decklist. Anything not in this list (unusual card types) is grouped
# alphabetically after these.
TYPE_ORDER = ["Creature", "Planeswalker", "Instant", "Sorcery", "Artifact", "Enchantment", "Land", "Battle"]


def group_cards_by_type(cards):
    """Groups a list of card rows by their primary type (e.g. "Creature"), in a sensible order."""
    groups = {}
    for card in cards:
        primary_type = (card["type_line"] or "Other").split(" \u2014 ")[0]
        groups.setdefault(primary_type, []).append(card)

    def sort_key(type_name):
        return (TYPE_ORDER.index(type_name), "") if type_name in TYPE_ORDER else (len(TYPE_ORDER), type_name)

    ordered_names = sorted(groups.keys(), key=sort_key)
    return [{"type_name": name, "cards": groups[name], "count": len(groups[name])} for name in ordered_names]
DB_PATH = "db/mtg.sqlite3"

# A simple HTML template. {{ }} are placeholders Flask fills in with real data.
PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Card Tracker</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; }
        h1 { font-family: Georgia, serif; }
        table { width: 100%; border-collapse: collapse; margin-top: 16px; }
        th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #5c4c3a; }
        th { color: #c9b28a; font-weight: normal; font-size: 13px; }
        img { height: 70px; border-radius: 4px; }
        .empty { color: #c9b28a; font-style: italic; margin-top: 20px; }
        .filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 14px 0; }
        .filter-bar select { padding: 5px 8px; border-radius: 4px; border: 1px solid #5c4c3a; background: #2f2419; color: #f0e6d2; font-size: 12.5px; }
        .filter-bar a { color: #e6c766; font-size: 12.5px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px; margin-top: 18px; }
        .card-tile { background: #2f2419; border: 1px solid #5c4c3a; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }
        .card-tile img { width: 100%; height: auto; border-radius: 0; display: block; }
        .card-tile .no-image { height: 180px; display: flex; align-items: center; justify-content: center; color: #5c4c3a; font-size: 12px; background: #1c140f; }
        .card-body { padding: 10px 12px 12px; flex: 1; display: flex; flex-direction: column; gap: 3px; }
        .card-body .name { font-family: Georgia, serif; font-weight: bold; font-size: 14px; }
        .card-body .meta { font-size: 11.5px; color: #c9b28a; }
        .card-body .qty-row { margin-top: 6px; font-size: 12px; display: flex; justify-content: space-between; align-items: center; }
        .foil-tag { color: #e6c766; font-size: 10.5px; }
        .location-tag { font-size: 11px; color: #8ab8c9; margin-top: 4px; }
        .loan-tag { font-size: 11px; color: #e6c766; margin-top: 2px; }
        .card-actions { margin-top: 8px; display: flex; gap: 8px; font-size: 12px; flex-wrap: wrap; align-items: center; }
        .card-actions form { display: inline; }
        .card-actions button { background: none; border: none; color: #c0392b; cursor: pointer; text-decoration: underline; padding: 0; font-size: inherit; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Card Tracker</h1>
    <p><a href="/add" style="color:#e6c766;">+ Add a card to your collection</a></p>
    <form method="GET" class="filter-bar">
        <select name="color" onchange="this.form.submit()">
            <option value="all" {% if color_filter == 'all' %}selected{% endif %}>All colors</option>
            <option value="W" {% if color_filter == 'W' %}selected{% endif %}>White</option>
            <option value="U" {% if color_filter == 'U' %}selected{% endif %}>Blue</option>
            <option value="B" {% if color_filter == 'B' %}selected{% endif %}>Black</option>
            <option value="R" {% if color_filter == 'R' %}selected{% endif %}>Red</option>
            <option value="G" {% if color_filter == 'G' %}selected{% endif %}>Green</option>
            <option value="C" {% if color_filter == 'C' %}selected{% endif %}>Colorless</option>
            <option value="M" {% if color_filter == 'M' %}selected{% endif %}>Multicolor</option>
        </select>
        <select name="ptype" onchange="this.form.submit()">
            <option value="all" {% if type_filter == 'all' %}selected{% endif %}>All types</option>
            {% for t in primary_types %}
            <option value="{{ t }}" {% if type_filter == t %}selected{% endif %}>{{ t }}</option>
            {% endfor %}
        </select>
        <select name="cmc" onchange="this.form.submit()">
            <option value="all" {% if cmc_filter == 'all' %}selected{% endif %}>Any mana value</option>
            {% for v in ['0','1','2','3','4','5','6','7+'] %}
            <option value="{{ v }}" {% if cmc_filter == v %}selected{% endif %}>{{ v }}</option>
            {% endfor %}
        </select>
        {% if color_filter != 'all' or type_filter != 'all' or cmc_filter != 'all' %}
        <a href="/tracker">Clear filters</a>
        {% endif %}
    </form>
    {% if cards %}
    <div class="grid">
        {% for card in cards %}
        <div class="card-tile">
            {% if card['image_url'] %}
            <img src="{{ card['image_url'] }}">
            {% else %}
            <div class="no-image">No image</div>
            {% endif %}
            <div class="card-body">
                <div class="name">{{ card['name'] }}</div>
                <div class="meta">{{ card['set_name'] }} &middot; {{ card['type_line'] }}</div>
                <div class="qty-row">
                    <span>{{ card['quantity'] }}x &middot; {{ card['condition'] }}</span>
                    {% if card['foil'] %}<span class="foil-tag">FOIL</span>{% endif %}
                </div>
                <div class="location-tag">
                    {% if card['location_name'] %}In: {{ card['location_name'] }} ({{ card['location_kind'] }}){% else %}Unsorted{% endif %}
                </div>
                {% if loans_by_item.get(card['id']) %}
                <div class="loan-tag">
                    {% for l in loans_by_item.get(card['id']) %}Loaned {{ l['quantity_out'] }}x to {{ l['borrower_name'] }}{% if not loop.last %}, {% endif %}{% endfor %}
                </div>
                {% endif %}
                <div class="card-actions">
                    <a href="/edit/{{ card['id'] }}" style="color:#e6c766;">Edit</a>
                    <a href="/loan/{{ card['id'] }}" style="color:#8ab8c9;">Loan out</a>
                    <form method="POST" action="/delete/{{ card['id'] }}"
                          onsubmit="return confirm('Remove this card from your collection?');">
                        <button type="submit">Delete</button>
                    </form>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p class="empty">Your collection is empty so far. Click "+ Add a card" above to get started!</p>
    {% endif %}
</body>
</html>
"""


@app.route("/tracker")
def show_collection():
    color_filter = request.args.get("color", "all")
    type_filter = request.args.get("ptype", "all")
    cmc_filter = request.args.get("cmc", "all")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name, like a dictionary

    query = """
        SELECT
            collection_items.id,
            card_catalog.name,
            card_catalog.set_name,
            card_catalog.type_line,
            card_catalog.image_url,
            card_catalog.colors,
            card_catalog.cmc,
            collection_items.quantity,
            collection_items.condition,
            collection_items.foil,
            containers.name as location_name,
            containers.kind as location_kind
        FROM collection_items
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        LEFT JOIN containers ON collection_items.container_id = containers.id
        WHERE (collection_items.is_missing = 0 OR collection_items.is_missing IS NULL)
    """
    params = []

    if color_filter == "C":
        query += " AND card_catalog.colors = '[]'"
    elif color_filter == "M":
        query += " AND card_catalog.colors LIKE '%,%'"  # more than one color listed = multicolor
    elif color_filter != "all":
        query += " AND card_catalog.colors LIKE ?"
        params.append(f'%"{color_filter}"%')

    if type_filter != "all":
        query += " AND card_catalog.type_line LIKE ?"
        params.append(f"{type_filter}%")

    if cmc_filter == "7+":
        query += " AND card_catalog.cmc >= 7"
    elif cmc_filter != "all":
        query += " AND card_catalog.cmc = ?"
        params.append(int(cmc_filter))

    query += " ORDER BY card_catalog.name"
    rows = conn.execute(query, params).fetchall()

    # Build the list of types actually present, for the filter dropdown
    all_type_rows = conn.execute(
        """
        SELECT DISTINCT card_catalog.type_line
        FROM collection_items
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE collection_items.is_missing = 0 OR collection_items.is_missing IS NULL
        """
    ).fetchall()
    primary_types = sorted(set(row["type_line"].split(" \u2014 ")[0] for row in all_type_rows if row["type_line"]))

    # Figure out which of these cards currently have an active loan against them
    active_loans = conn.execute(
        "SELECT collection_item_id, borrower_name, quantity_out FROM loans WHERE returned_at IS NULL"
    ).fetchall()
    loans_by_item = {}
    for loan in active_loans:
        loans_by_item.setdefault(loan["collection_item_id"], []).append(loan)

    conn.close()
    return render_template_string(
        PAGE_TEMPLATE, cards=rows, loans_by_item=loans_by_item, primary_types=primary_types,
        color_filter=color_filter, type_filter=type_filter, cmc_filter=cmc_filter,
    )


EDIT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Edit {{ item['name'] }}</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 400px; }
        h1 { font-family: Georgia, serif; font-size: 22px; }
        label { display: block; margin-top: 14px; font-size: 13px; color: #c9b28a; }
        input, select { width: 100%; padding: 6px; margin-top: 4px; border-radius: 4px; border: 1px solid #5c4c3a; }
        button { margin-top: 20px; padding: 8px 16px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; }
        a { color: #e6c766; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Edit: {{ item['name'] }}</h1>
    <form method="POST">
        <label>Quantity
            <input type="number" name="quantity" value="{{ item['quantity'] }}" min="0" required>
        </label>
        <label>Condition
            <select name="condition">
                {% for c in ['NM', 'LP', 'MP', 'HP', 'DMG'] %}
                <option value="{{ c }}" {% if item['condition'] == c %}selected{% endif %}>{{ c }}</option>
                {% endfor %}
            </select>
        </label>
        <label>
            <input type="checkbox" name="foil" style="width:auto;" {% if item['foil'] %}checked{% endif %}>
            Foil
        </label>
        <label>Container
            <select name="container_id">
                <option value="">Unsorted</option>
                {% for c in containers %}
                <option value="{{ c['id'] }}" {% if item['container_id'] == c['id'] %}selected{% endif %}>{{ c['name'] }} ({{ c['kind'] }})</option>
                {% endfor %}
            </select>
        </label>
        <button type="submit">Save changes</button>
    </form>
    <p style="margin-top:10px;"><a href="/edit/{{ item['id'] }}/version">Change version / printing</a></p>
    <p><a href="/tracker">&larr; Back to card tracker</a></p>
</body>
</html>
"""


@app.route("/edit/<int:item_id>", methods=["GET", "POST"])
def edit_item(item_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if request.method == "POST":
        quantity = int(request.form["quantity"])
        condition = request.form["condition"]
        foil = 1 if request.form.get("foil") else 0
        container_id = request.form.get("container_id") or None
        conn.execute(
            "UPDATE collection_items SET quantity = ?, condition = ?, foil = ?, container_id = ? WHERE id = ?",
            (quantity, condition, foil, container_id, item_id),
        )
        conn.commit()
        conn.close()
        return redirect("/tracker")

    item = conn.execute(
        """
        SELECT collection_items.id, collection_items.quantity, collection_items.condition,
               collection_items.foil, collection_items.container_id, card_catalog.name
        FROM collection_items
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE collection_items.id = ?
        """,
        (item_id,),
    ).fetchone()
    containers = conn.execute("SELECT id, name, kind FROM containers ORDER BY name").fetchall()
    conn.close()

    if item is None:
        return "That collection item doesn't exist.", 404

    return render_template_string(EDIT_TEMPLATE, item=item, containers=containers)


@app.route("/delete/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM collection_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return redirect("/tracker")


@app.route("/item/<int:item_id>/increment", methods=["POST"])
def increment_item(item_id):
    next_url = request.form.get("next") or "/tracker"
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE collection_items SET quantity = quantity + 1 WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(next_url)


@app.route("/item/<int:item_id>/decrement", methods=["POST"])
def decrement_item(item_id):
    next_url = request.form.get("next") or "/tracker"
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT quantity FROM collection_items WHERE id = ?", (item_id,)).fetchone()
    if row:
        if row[0] <= 1:
            conn.execute("DELETE FROM collection_items WHERE id = ?", (item_id,))
        else:
            conn.execute("UPDATE collection_items SET quantity = quantity - 1 WHERE id = ?", (item_id,))
        conn.commit()
    conn.close()
    return redirect(next_url)


SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Add a card</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 400px; }
        h1 { font-family: Georgia, serif; font-size: 22px; }
        input { width: 100%; padding: 8px; margin-top: 8px; border-radius: 4px; border: 1px solid #5c4c3a; }
        button { margin-top: 14px; padding: 8px 16px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; }
        a { color: #e6c766; }
        .error { color: #c0392b; margin-top: 10px; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Add a card</h1>
    <form method="POST" action="/add">
        <input type="hidden" name="container_id" value="{{ container_id or '' }}">
        <label>Card name<br>
            <input type="text" name="card_name" placeholder="e.g. Lightning Bolt" required autofocus>
        </label>
        <button type="submit">Find printings</button>
    </form>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p style="margin-top:14px;"><a href="/bulk-add">Bulk add a list of cards instead &rarr;</a></p>
    <p><a href="/tracker">&larr; Back to card tracker</a></p>
</body>
</html>
"""

PRINTINGS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Choose a printing</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; }
        h1 { font-family: Georgia, serif; font-size: 22px; }
        .printing { display: flex; gap: 14px; align-items: center; border-bottom: 1px solid #5c4c3a; padding: 12px 0; }
        .printing img { height: 90px; border-radius: 4px; }
        .printing-info { flex: 1; }
        .printing-info b { font-family: Georgia, serif; }
        form.inline { display: flex; gap: 8px; align-items: center; margin-top: 6px; }
        form.inline input, form.inline select { padding: 4px; border-radius: 4px; border: 1px solid #5c4c3a; }
        form.inline input[type=number] { width: 55px; }
        button { padding: 6px 12px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; }
        a { color: #e6c766; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Printings of "{{ card_name }}"</h1>
    {% if printings %}
        {% for p in printings %}
        <div class="printing">
            {% if p['image_uris'] %}<img src="{{ p['image_uris']['small'] }}">{% endif %}
            <div class="printing-info">
                <div><b>{{ p['set_name'] }}</b> ({{ p['set'] }}) &mdash; {{ p['released_at'] }}</div>
                <form class="inline" method="POST" action="/add/confirm">
                    <input type="hidden" name="scryfall_id" value="{{ p['id'] }}">
                    <input type="hidden" name="container_id" value="{{ container_id or '' }}">
                    Qty <input type="number" name="quantity" value="1" min="1">
                    <select name="condition">
                        {% for c in ['NM', 'LP', 'MP', 'HP', 'DMG'] %}
                        <option value="{{ c }}">{{ c }}</option>
                        {% endfor %}
                    </select>
                    <label><input type="checkbox" name="foil" style="width:auto;"> Foil</label>
                    <button type="submit">Add this version</button>
                </form>
            </div>
        </div>
        {% endfor %}
    {% else %}
        <p>No printings found.</p>
    {% endif %}
    <p><a href="/add">&larr; Search a different card</a></p>
</body>
</html>
"""


@app.route("/add", methods=["GET", "POST"])
def add_card_page():
    if request.method == "GET":
        return render_template_string(SEARCH_TEMPLATE, error=None, container_id=request.args.get("container_id"))

    card_name = request.form["card_name"]
    container_id = request.form.get("container_id") or None
    try:
        printings = search_all_printings(card_name)
    except Exception:
        return render_template_string(
            SEARCH_TEMPLATE,
            error=f'Could not find a card named "{card_name}". Check the spelling and try again.',
            container_id=container_id,
        )

    if not printings:
        return render_template_string(
            SEARCH_TEMPLATE,
            error=f'Could not find a card named "{card_name}". Check the spelling and try again.',
            container_id=container_id,
        )

    return render_template_string(
        PRINTINGS_TEMPLATE, card_name=card_name, printings=printings, container_id=container_id
    )


CONTAINERS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>My Collection</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 520px; }
        h1 { font-family: Georgia, serif; font-size: 22px; }
        h2 { font-family: Georgia, serif; font-size: 16px; margin-top: 28px; }
        .item { display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #5c4c3a; padding: 10px 0; }
        .item a { color: #f0e6d2; text-decoration: none; font-weight: bold; }
        .item a:hover { text-decoration: underline; }
        .item-info { flex: 1; }
        .kind-tag { color: #c9b28a; font-size: 12px; display: block; }
        .options-menu { position: relative; flex-shrink: 0; }
        .options-menu summary { list-style: none; cursor: pointer; padding: 4px 10px; color: #c9b28a; font-size: 18px; border-radius: 4px; }
        .options-menu summary::-webkit-details-marker { display: none; }
        .options-menu summary:hover { background: #3a2e22; }
        .options-menu[open] summary { background: #3a2e22; }
        .options-dropdown { position: absolute; right: 0; top: 100%; background: #2f2419; border: 1px solid #5c4c3a; border-radius: 6px; z-index: 10; min-width: 120px; overflow: hidden; }
        .options-dropdown form { display: block; }
        .options-dropdown button { width: 100%; text-align: left; padding: 8px 12px; background: none; border: none; color: #f0e6d2; cursor: pointer; font-size: 13px; }
        .options-dropdown button:hover { background: #3a2e22; }
        .options-dropdown button.danger { color: #e07a5f; }
        input, select { width: 100%; padding: 6px; margin-top: 4px; border-radius: 4px; border: 1px solid #5c4c3a; }
        label { display: block; margin-top: 10px; font-size: 13px; color: #c9b28a; }
        button { margin-top: 14px; padding: 8px 16px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; }
        a.back { color: #e6c766; }

        /* distinct icon per container type */
        .icon { flex-shrink: 0; width: 34px; height: 30px; position: relative; }
        .icon-deck .cb { position: absolute; width: 18px; height: 25px; border-radius: 3px; border: 1px solid #7a6a4d; bottom: 0; }
        .icon-deck .cb:nth-child(1) { background: #8a2f2f; left: 4px; transform: rotate(-10deg); }
        .icon-deck .cb:nth-child(2) { background: #7a2828; left: 8px; transform: rotate(2deg); }
        .icon-deck .cb:nth-child(3) { background: #6a2020; left: 12px; transform: rotate(12deg); }
        .icon-binder { background: linear-gradient(135deg, #6b7690, #4a5468); border-radius: 2px 5px 5px 2px; height: 30px; width: 24px; margin-left: 5px; }
        .icon-binder::before { content: ''; position: absolute; left: -4px; top: 5px; width: 6px; height: 6px; background: #d8d0bc; border-radius: 50%; box-shadow: 0 8px 0 #d8d0bc, 0 16px 0 #d8d0bc; }
        .icon-box { background: linear-gradient(135deg, #a9805a, #7a5738); border-radius: 2px; height: 22px; width: 32px; margin-top: 8px; }
        .icon-box::before { content: ''; position: absolute; top: -6px; left: -1px; width: 34px; height: 7px; background: #c39868; border-radius: 2px; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>My Collection</h1>

    {% if containers %}
    {% for c in containers %}
    <div class="item">
        <div class="icon icon-{{ c['kind'] }}">
            {% if c['kind'] == 'deck' %}<div class="cb"></div><div class="cb"></div><div class="cb"></div>{% endif %}
        </div>
        <div class="item-info">
            <a href="/containers/{{ c['id'] }}">{{ c['name'] }}</a>
            <span class="kind-tag">{{ c['kind'] }}{% if c['format'] %} &middot; {{ c['format'] }}{% endif %} &mdash; {{ c['card_count'] }} cards</span>
        </div>
        <details class="options-menu">
            <summary>&#8942;</summary>
            <div class="options-dropdown">
                <form method="POST" action="/containers/{{ c['id'] }}/duplicate">
                    <button type="submit">Duplicate</button>
                </form>
                <form method="POST" action="/containers/{{ c['id'] }}/delete"
                      onsubmit="return confirm('Delete \'{{ c['name'] }}\'? Real cards inside will move to Unsorted, not be deleted.');">
                    <button type="submit" class="danger">Delete</button>
                </form>
            </div>
        </details>
    </div>
    {% endfor %}
    {% else %}
    <p style="color:#c9b28a; font-style:italic;">You haven't made any binders, boxes, or decks yet.</p>
    {% endif %}

    <h2>Create a new one</h2>
    <form method="POST" action="/">
        <label>Name
            <input type="text" name="name" placeholder="e.g. Modern Staples" required>
        </label>
        <label>Type
            <select name="kind" id="kind-select" onchange="document.getElementById('format-field').style.display = this.value === 'deck' ? 'block' : 'none';">
                <option value="binder">Binder</option>
                <option value="box">Box</option>
                <option value="deck">Deck</option>
            </select>
        </label>
        <label id="format-field" style="display:none;">Format (decks only)
            <select name="format">
                {% for f in formats %}
                <option value="{{ f }}">{{ f }}</option>
                {% endfor %}
                <option value="Casual">Casual / Other</option>
            </select>
        </label>
        <button type="submit">Create</button>
    </form>
</body>
</html>
"""

CONTAINER_DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ container['name'] }}</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; }
        h1 { font-family: Georgia, serif; }
        .kind-tag { color: #c9b28a; font-size: 13px; }
        table { width: 100%; border-collapse: collapse; margin-top: 16px; }
        th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #5c4c3a; }
        th { color: #c9b28a; font-weight: normal; font-size: 13px; }
        img { height: 70px; border-radius: 4px; }
        a { color: #e6c766; }
        .empty { color: #c9b28a; font-style: italic; margin-top: 20px; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>{{ container['name'] }} <span class="kind-tag">({{ container['kind'] }}{% if container['format'] %} &middot; {{ container['format'] }}{% endif %})</span></h1>
    {% if cards %}
    <table>
        <tr><th>Image</th><th>Name</th><th>Set</th><th>Qty</th><th>Condition</th></tr>
        {% for card in cards %}
        <tr>
            <td>{% if card['image_url'] %}<img src="{{ card['image_url'] }}">{% endif %}</td>
            <td>{{ card['name'] }}</td>
            <td>{{ card['set_name'] }}</td>
            <td>{{ card['quantity'] }}</td>
            <td>{{ card['condition'] }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p class="empty">Nothing filed here yet. Edit a card in your collection and assign it to this container.</p>
    {% endif %}
    <p style="margin-top:20px;"><a href="/">&larr; Back to containers</a></p>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def containers_page():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if request.method == "POST":
        name = request.form["name"]
        kind = request.form["kind"]
        format_ = request.form.get("format") or None
        conn.execute(
            "INSERT INTO containers (name, kind, format) VALUES (?, ?, ?)",
            (name, kind, format_ if kind == "deck" else None),
        )
        conn.commit()
        conn.close()
        return redirect("/")

    containers = conn.execute(
        """
        SELECT containers.*, COUNT(collection_items.id) as card_count
        FROM containers
        LEFT JOIN collection_items ON collection_items.container_id = containers.id
        GROUP BY containers.id
        ORDER BY containers.name
        """
    ).fetchall()
    conn.close()
    return render_template_string(CONTAINERS_TEMPLATE, containers=containers, formats=list(FORMAT_RULES.keys()))


@app.route("/containers/<int:container_id>/delete", methods=["POST"])
def delete_container(container_id):
    conn = sqlite3.connect(DB_PATH)
    # Missing placeholders aren't real cards -- just remove them.
    conn.execute("DELETE FROM collection_items WHERE container_id = ? AND is_missing = 1", (container_id,))
    # Real cards move to Unsorted instead of being deleted -- deleting a
    # binder/box/deck shouldn't destroy cards you actually own.
    conn.execute("UPDATE collection_items SET container_id = NULL WHERE container_id = ?", (container_id,))
    conn.execute("DELETE FROM containers WHERE id = ?", (container_id,))
    conn.commit()
    conn.close()
    return redirect("/")


@app.route("/containers/<int:container_id>/duplicate", methods=["POST"])
def duplicate_container(container_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    original = conn.execute("SELECT * FROM containers WHERE id = ?", (container_id,)).fetchone()
    if original is None:
        conn.close()
        return redirect("/")

    new_name = f"{original['name']} (copy)"
    cursor = conn.execute(
        "INSERT INTO containers (name, kind, format) VALUES (?, ?, ?)",
        (new_name, original["kind"], original["format"]),
    )
    new_container_id = cursor.lastrowid

    if original["kind"] == "deck":
        # Cloning a deck copies its card LIST as a fresh want-list, not as
        # claimed ownership -- duplicating a deck shouldn't make it look
        # like you suddenly own twice as many real cards.
        cards = conn.execute(
            "SELECT card_id, quantity FROM collection_items WHERE container_id = ?", (container_id,)
        ).fetchall()
        for card in cards:
            conn.execute(
                "INSERT INTO collection_items (card_id, quantity, condition, foil, container_id, is_missing) "
                "VALUES (?, ?, 'NM', 0, ?, 1)",
                (card["card_id"], card["quantity"], new_container_id),
            )
        conn.commit()
    # Binders and boxes duplicate as an empty container -- physically
    # duplicating real cards doesn't make sense, since you don't suddenly
    # own two of everything just because you copied the folder.

    conn.close()
    return redirect("/")


@app.route("/containers/<int:container_id>")
def container_detail(container_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    container = conn.execute("SELECT * FROM containers WHERE id = ?", (container_id,)).fetchone()
    if container is None:
        conn.close()
        return "That container doesn't exist.", 404

    if container["kind"] == "deck":
        cards = conn.execute(
            """
            SELECT collection_items.id as item_id,
                   card_catalog.name, card_catalog.set_name, card_catalog.image_url, card_catalog.type_line,
                   collection_items.quantity, collection_items.condition, collection_items.is_missing
            FROM collection_items
            JOIN card_catalog ON collection_items.card_id = card_catalog.id
            WHERE collection_items.container_id = ?
            ORDER BY collection_items.is_missing ASC, card_catalog.name
            """,
            (container_id,),
        ).fetchall()
        legality = check_deck_legality(conn, container_id, container["format"])
        conn.close()
        grouped_cards = group_cards_by_type(cards)
        return render_template_string(
            DECK_DETAIL_TEMPLATE, container=container, grouped_cards=grouped_cards, legality=legality
        )

    cards = conn.execute(
        """
        SELECT card_catalog.name, card_catalog.set_name, card_catalog.image_url,
               collection_items.quantity, collection_items.condition
        FROM collection_items
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE collection_items.container_id = ?
        ORDER BY card_catalog.name
        """,
        (container_id,),
    ).fetchall()
    conn.close()
    return render_template_string(CONTAINER_DETAIL_TEMPLATE, container=container, cards=cards)


DECK_DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ container['name'] }}</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 700px; }
        h1 { font-family: Georgia, serif; }
        .kind-tag { color: #c9b28a; font-size: 13px; }
        table { width: 100%; border-collapse: collapse; margin-top: 16px; }
        th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #5c4c3a; }
        th { color: #c9b28a; font-weight: normal; font-size: 12.5px; }
        img { height: 60px; border-radius: 4px; }
        a { color: #e6c766; }
        .empty { color: #c9b28a; font-style: italic; }
        .missing-tag { color: #e07a5f; font-size: 11px; border: 1px solid #e07a5f; border-radius: 8px; padding: 1px 7px; }
        .deck-search-bar { display: flex; gap: 8px; margin-top: 12px; }
        .deck-search-bar input[type=text] { flex: 1; padding: 7px 10px; border-radius: 4px; border: 1px solid #5c4c3a; background: #2f2419; color: #f0e6d2; }
        .deck-search-bar button { padding: 7px 14px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; }
        .legality-box { border: 1px solid #5c4c3a; border-radius: 6px; padding: 12px 14px; margin-top: 16px; font-size: 13px; }
        .legality-box h3 { font-family: Georgia, serif; font-size: 14px; margin: 0 0 6px; }
        .legal-ok { color: #8ab88a; }
        .legal-bad { color: #e07a5f; }
        .legality-box ul { margin: 6px 0 0; padding-left: 18px; }
        .sideboard-note { color: #c9b28a; font-size: 12px; margin-top: 8px; }
        .view-switcher { margin-top: 16px; font-size: 13px; color: #c9b28a; }
        .view-switcher select { padding: 5px 8px; border-radius: 4px; border: 1px solid #5c4c3a; background: #2f2419; color: #f0e6d2; font-size: 12.5px; margin-left: 6px; }

        .type-heading { font-family: Georgia, serif; font-size: 14.5px; color: #e6c766; margin: 22px 0 6px; border-bottom: 1px solid #5c4c3a; padding-bottom: 4px; }
        .type-heading:first-of-type { margin-top: 16px; }

        .fan { display: flex; flex-direction: column; width: 260px; margin-bottom: 10px; }
        .fan-card { position: relative; margin-top: -327px; }
        .fan-card:first-child { margin-top: 0; }
        .fan-card img { width: 260px; height: auto; border-radius: 10px; display: block; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
        .fan-card.stack-missing img { opacity: 0.55; }
        .fan-missing-tag { position: absolute; top: 6px; right: 6px; }

        .qty-badge { position: absolute; top: 8px; left: 8px; background: rgba(0,0,0,0.8); color: #fff; font-size: 13px; font-weight: bold; padding: 2px 9px; border-radius: 12px; }
        .card-options { position: absolute; top: 4px; right: 4px; z-index: 5; }
        .card-options summary { list-style: none; cursor: pointer; background: rgba(0,0,0,0.8); color: #fff; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 15px; }
        .card-options summary::-webkit-details-marker { display: none; }
        .card-options .options-dropdown { position: absolute; top: 28px; right: 0; background: #2f2419; border: 1px solid #5c4c3a; border-radius: 6px; min-width: 130px; z-index: 20; overflow: hidden; }
        .card-options .options-dropdown a, .card-options .options-dropdown button {
            display: block; width: 100%; text-align: left; padding: 8px 12px; background: none; border: none;
            color: #f0e6d2; text-decoration: none; cursor: pointer; font-size: 12.5px; box-sizing: border-box;
        }
        .card-options .options-dropdown a:hover, .card-options .options-dropdown button:hover { background: #3a2e22; }
        .text-options-cell { position: relative; width: 30px; }
        .text-options-cell .card-options { position: static; }
        .text-options-cell .options-dropdown { top: 26px; right: 0; }
        .stack-thumb { position: relative; flex-shrink: 0; }
        .stack-thumb img { height: 160px; border-radius: 6px; display: block; }

        .grid-wrap { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px; margin-top: 14px; }
        .grid-cell.stack-missing { opacity: 0.6; }
        .grid-cell .stack-thumb img { height: auto; width: 100%; border-radius: 8px; }
        .grid-name { font-size: 12px; text-align: center; margin-top: 5px; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>{{ container['name'] }} <span class="kind-tag">(deck{% if container['format'] %} &middot; {{ container['format'] }}{% endif %})</span></h1>
    <form class="deck-search-bar" method="POST" action="/add">
        <input type="hidden" name="container_id" value="{{ container['id'] }}">
        <input type="text" name="card_name" placeholder="Search a card to add to this deck..." required>
        <button type="submit">Search</button>
    </form>

    {% if legality %}
    <div class="legality-box">
        <h3>{{ container['format'] }} legality</h3>
        <div class="{{ 'legal-ok' if legality['size_ok'] else 'legal-bad' }}">
            Deck size: {{ legality['size_message'] }}
        </div>
        {% if legality['copy_violations'] %}
        <div class="legal-bad">
            Too many copies:
            <ul>
                {% for v in legality['copy_violations'] %}
                <li>{{ v['name'] }}: {{ v['qty'] }}x (max {{ v['max_allowed'] }})</li>
                {% endfor %}
            </ul>
        </div>
        {% else %}
        <div class="legal-ok">No copy-limit violations</div>
        {% endif %}
        {% if legality['rules']['sideboard_size'] > 0 %}
        <div class="sideboard-note">Sideboard allowed: up to {{ legality['rules']['sideboard_size'] }} cards (not tracked separately yet -- this only checks your main deck list above).</div>
        {% endif %}
    </div>
    {% endif %}


    {% macro card_options(item_id) %}
    <details class="options-menu card-options">
        <summary>&#8942;</summary>
        <div class="options-dropdown">
            <a href="/edit/{{ item_id }}/version">Change version</a>
            <form method="POST" action="/item/{{ item_id }}/increment">
                <input type="hidden" name="next" value="/containers/{{ container['id'] }}">
                <button type="submit">+1 copy</button>
            </form>
            <form method="POST" action="/item/{{ item_id }}/decrement">
                <input type="hidden" name="next" value="/containers/{{ container['id'] }}">
                <button type="submit">-1 copy</button>
            </form>
        </div>
    </details>
    {% endmacro %}

    {% if grouped_cards %}
    <div class="view-switcher">
        <label>Show as:
            <select id="view-mode" onchange="setDeckView(this.value)">
                <option value="text">Text (qty, name, set)</option>
                <option value="stacks">Visual stacks</option>
                <option value="grid">Visual grid</option>
            </select>
        </label>
    </div>

    <div id="view-text">
        {% for group in grouped_cards %}
        <h4 class="type-heading">{{ group['type_name'] }} ({{ group['count'] }})</h4>
        <table>
            <tr><th>Name</th><th>Set</th><th>Qty</th><th></th><th></th></tr>
            {% for card in group['cards'] %}
            <tr>
                <td>{{ card['name'] }}</td>
                <td>{{ card['set_name'] }}</td>
                <td>{{ card['quantity'] }}</td>
                <td>{% if card['is_missing'] %}<span class="missing-tag">MISSING</span>{% endif %}</td>
                <td class="text-options-cell">{{ card_options(card['item_id']) }}</td>
            </tr>
            {% endfor %}
        </table>
        {% endfor %}
    </div>

    <div id="view-stacks" style="display:none;">
        {% for group in grouped_cards %}
        <h4 class="type-heading">{{ group['type_name'] }} ({{ group['count'] }})</h4>
        <div class="fan">
            {% for card in group['cards'] %}
            <div class="fan-card {% if card['is_missing'] %}stack-missing{% endif %}" title="{{ card['name'] }}">
                {% if card['image_url'] %}<img src="{{ card['image_url'] }}">{% endif %}
                <span class="qty-badge">{{ card['quantity'] }}</span>
                {{ card_options(card['item_id']) }}
                {% if card['is_missing'] %}<span class="missing-tag fan-missing-tag">MISSING</span>{% endif %}
            </div>
            {% endfor %}
        </div>
        {% endfor %}
    </div>

    <div id="view-grid" style="display:none;">
        {% for group in grouped_cards %}
        <h4 class="type-heading">{{ group['type_name'] }} ({{ group['count'] }})</h4>
        <div class="grid-wrap">
            {% for card in group['cards'] %}
            <div class="grid-cell {% if card['is_missing'] %}stack-missing{% endif %}">
                <div class="stack-thumb">
                    {% if card['image_url'] %}<img src="{{ card['image_url'] }}">{% endif %}
                    <span class="qty-badge">{{ card['quantity'] }}</span>
                    {{ card_options(card['item_id']) }}
                </div>
                <div class="grid-name">{{ card['name'] }}</div>
            </div>
            {% endfor %}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p class="empty">Nothing in this deck yet. Add a card above to get started.</p>
    {% endif %}

    <p style="margin-top:20px;"><a href="/">&larr; Back to containers</a></p>

<script>
function setDeckView(mode) {
    document.getElementById('view-text').style.display = (mode === 'text') ? 'block' : 'none';
    document.getElementById('view-stacks').style.display = (mode === 'stacks') ? 'block' : 'none';
    document.getElementById('view-grid').style.display = (mode === 'grid') ? 'block' : 'none';
}
</script>
</body>
</html>
"""

MOVE_OR_MISSING_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>You already own this</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 440px; }
        h1 { font-family: Georgia, serif; font-size: 19px; }
        li { margin-bottom: 4px; }
        button { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; margin-top: 16px; margin-right: 8px; font-size: 13px; }
        .move-btn { background: #8ab88a; color: #1c140f; }
        .missing-btn { background: #4a3c2c; color: #f0e6d2; }
    </style>
</head>
<body>
    <h1>You already have {{ available }}x {{ card_name }}</h1>
    <p>Found in:</p>
    <ul>
        {% for s in sources %}
        <li>{{ s['quantity'] }}x in {{ s['container_name'] or 'your Collection (unsorted)' }}</li>
        {% endfor %}
    </ul>
    <p>Move real copies into this deck, or add a placeholder instead and leave your real copies where they are?</p>
    <form method="POST" action="/add/confirm/move" style="display:inline;">
        <input type="hidden" name="scryfall_id" value="{{ scryfall_id }}">
        <input type="hidden" name="quantity" value="{{ quantity }}">
        <input type="hidden" name="condition" value="{{ condition }}">
        <input type="hidden" name="foil" value="{{ foil }}">
        <input type="hidden" name="container_id" value="{{ container_id }}">
        <button class="move-btn" type="submit">Move {{ available if available < quantity else quantity }} real cop{{ 'y' if quantity == 1 else 'ies' }} in</button>
    </form>
    <form method="POST" action="/add/confirm/missing" style="display:inline;">
        <input type="hidden" name="scryfall_id" value="{{ scryfall_id }}">
        <input type="hidden" name="quantity" value="{{ quantity }}">
        <input type="hidden" name="condition" value="{{ condition }}">
        <input type="hidden" name="foil" value="{{ foil }}">
        <input type="hidden" name="container_id" value="{{ container_id }}">
        <button class="missing-btn" type="submit">Add as missing instead</button>
    </form>
</body>
</html>
"""


@app.route("/add/confirm", methods=["POST"])
def add_card_confirm():
    scryfall_id = request.form["scryfall_id"]
    quantity = int(request.form["quantity"])
    condition = request.form["condition"]
    foil = 1 if request.form.get("foil") else 0
    container_id = request.form.get("container_id") or None

    card = fetch_card_by_id(scryfall_id)
    save_card(card)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    target_kind = None
    if container_id:
        target = conn.execute("SELECT kind FROM containers WHERE id = ?", (container_id,)).fetchone()
        target_kind = target["kind"] if target else None

    if target_kind != "deck":
        # Not going into a deck -- just a normal, real add (collection/binder/box).
        new_item_id = save_to_collection(card["id"], quantity, condition, foil, container_id=container_id, is_missing=0)

        # Check: does any deck have this card marked MISSING? If so, offer to fill it.
        matches = find_decks_missing_card(conn, card["name"])
        conn.close()
        fallback_url = f"/containers/{container_id}" if container_id else "/tracker"

        if matches:
            fill_options = []
            for m in matches:
                fillable = min(quantity, m["missing_qty"])
                fill_options.append({
                    "deck_id": m["deck_id"],
                    "deck_name": m["deck_name"],
                    "missing_item_id": m["missing_item_id"],
                    "missing_qty": m["missing_qty"],
                    "fillable": fillable,
                })
            return render_template_string(
                FILL_MISSING_TEMPLATE,
                card_name=card["name"],
                quantity=quantity,
                source_item_id=new_item_id,
                fill_options=fill_options,
                fallback_url=fallback_url,
            )

        return redirect(fallback_url)

    # Going into a deck: check if real copies exist elsewhere first.
    available = total_real_available(conn, card["name"])
    if available <= 0:
        conn.execute(
            "INSERT INTO collection_items (card_id, quantity, condition, foil, container_id, is_missing) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (card["id"], quantity, condition, foil, container_id),
        )
        conn.commit()
        conn.close()
        return redirect(f"/containers/{container_id}")

    sources = find_real_sources(conn, card["name"])
    conn.close()
    return render_template_string(
        MOVE_OR_MISSING_TEMPLATE,
        card_name=card["name"],
        available=available,
        sources=sources,
        scryfall_id=scryfall_id,
        quantity=quantity,
        condition=condition,
        foil=foil,
        container_id=container_id,
    )


@app.route("/add/confirm/move", methods=["POST"])
def add_card_confirm_move():
    scryfall_id = request.form["scryfall_id"]
    quantity = int(request.form["quantity"])
    condition = request.form["condition"]
    foil = 1 if request.form.get("foil") else 0
    container_id = request.form["container_id"]

    card = fetch_card_by_id(scryfall_id)
    save_card(card)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    leftover = move_real_into_deck(conn, card["name"], container_id, quantity)
    if leftover > 0:
        conn.execute(
            "INSERT INTO collection_items (card_id, quantity, condition, foil, container_id, is_missing) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (card["id"], leftover, condition, foil, container_id),
        )
        conn.commit()
    conn.close()
    return redirect(f"/containers/{container_id}")


@app.route("/add/confirm/missing", methods=["POST"])
def add_card_confirm_missing():
    scryfall_id = request.form["scryfall_id"]
    quantity = int(request.form["quantity"])
    condition = request.form["condition"]
    foil = 1 if request.form.get("foil") else 0
    container_id = request.form["container_id"]

    card = fetch_card_by_id(scryfall_id)
    save_card(card)

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO collection_items (card_id, quantity, condition, foil, container_id, is_missing) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (card["id"], quantity, condition, foil, container_id),
    )
    conn.commit()
    conn.close()
    return redirect(f"/containers/{container_id}")


LOAN_FORM_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Loan out {{ item['name'] }}</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 400px; }
        h1 { font-family: Georgia, serif; font-size: 20px; }
        label { display: block; margin-top: 14px; font-size: 13px; color: #c9b28a; }
        input { width: 100%; padding: 6px; margin-top: 4px; border-radius: 4px; border: 1px solid #5c4c3a; }
        button { margin-top: 20px; padding: 8px 16px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; }
        a { color: #e6c766; }
        .avail { color: #c9b28a; font-size: 13px; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Loan out: {{ item['name'] }}</h1>
    <p class="avail">{{ available }} available to loan out of {{ item['quantity'] }} total (the rest is already loaned).</p>
    {% if available > 0 %}
    <form method="POST">
        <label>Borrower's name
            <input type="text" name="borrower_name" required autofocus>
        </label>
        <label>Quantity
            <input type="number" name="quantity_out" value="1" min="1" max="{{ available }}" required>
        </label>
        <button type="submit">Mark as loaned</button>
    </form>
    {% else %}
    <p style="color:#e07a5f;">All copies of this card are already loaned out.</p>
    {% endif %}
    <p style="margin-top:16px;"><a href="/tracker">&larr; Back to card tracker</a></p>
</body>
</html>
"""

LOANS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Loans</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 600px; }
        h1 { font-family: Georgia, serif; }
        table { width: 100%; border-collapse: collapse; margin-top: 16px; }
        th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #5c4c3a; }
        th { color: #c9b28a; font-weight: normal; font-size: 12.5px; }
        button { padding: 5px 10px; background: #4a3c2c; color: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .empty { color: #c9b28a; font-style: italic; margin-top: 16px; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Loans</h1>
    {% if loans %}
    <table>
        <tr><th>Card</th><th>Qty</th><th>Borrower</th><th>Since</th><th></th></tr>
        {% for l in loans %}
        <tr>
            <td>{{ l['card_name'] }}</td>
            <td>{{ l['quantity_out'] }}</td>
            <td>{{ l['borrower_name'] }}</td>
            <td>{{ l['loaned_at'] }}</td>
            <td>
                <form method="POST" action="/loans/{{ l['id'] }}/return">
                    <button type="submit">Mark returned</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p class="empty">Nothing currently loaned out.</p>
    {% endif %}
</body>
</html>
"""


@app.route("/loan/<int:item_id>", methods=["GET", "POST"])
def loan_item(item_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    item = conn.execute(
        """
        SELECT collection_items.id, collection_items.quantity, card_catalog.name
        FROM collection_items
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE collection_items.id = ?
        """,
        (item_id,),
    ).fetchone()
    if item is None:
        conn.close()
        return "That card doesn't exist.", 404

    already_loaned = conn.execute(
        "SELECT COALESCE(SUM(quantity_out), 0) FROM loans WHERE collection_item_id = ? AND returned_at IS NULL",
        (item_id,),
    ).fetchone()[0]
    available = item["quantity"] - already_loaned

    if request.method == "POST":
        borrower_name = request.form["borrower_name"]
        quantity_out = min(int(request.form["quantity_out"]), available)  # never loan more than available
        if quantity_out > 0:
            conn.execute(
                "INSERT INTO loans (collection_item_id, borrower_name, quantity_out) VALUES (?, ?, ?)",
                (item_id, borrower_name, quantity_out),
            )
            conn.commit()
        conn.close()
        return redirect("/tracker")

    conn.close()
    return render_template_string(LOAN_FORM_TEMPLATE, item=item, available=available)


@app.route("/loans")
def loans_page():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    active = conn.execute(
        """
        SELECT loans.id, loans.borrower_name, loans.quantity_out, loans.loaned_at,
               card_catalog.name as card_name
        FROM loans
        JOIN collection_items ON loans.collection_item_id = collection_items.id
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE loans.returned_at IS NULL
        ORDER BY loans.loaned_at DESC
        """
    ).fetchall()
    conn.close()
    return render_template_string(LOANS_TEMPLATE, loans=active)


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
def return_loan(loan_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE loans SET returned_at = CURRENT_TIMESTAMP WHERE id = ?", (loan_id,))
    conn.commit()
    conn.close()
    return redirect("/loans")


BULK_ADD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Bulk add cards</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 560px; }
        h1 { font-family: Georgia, serif; font-size: 22px; }
        label { display: block; margin-top: 14px; font-size: 13px; color: #c9b28a; }
        textarea, select { width: 100%; padding: 8px; margin-top: 4px; border-radius: 4px; border: 1px solid #5c4c3a;
                            background: #2f2419; color: #f0e6d2; font-family: monospace; font-size: 13px; }
        textarea { height: 160px; }
        button { margin-top: 14px; padding: 8px 16px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; }
        button:disabled { opacity: 0.5; cursor: default; }
        a { color: #e6c766; }
        .hint { font-size: 12px; color: #c9b28a; margin-top: 6px; }
        #progress { font-size: 13px; color: #c9b28a; margin-top: 16px; }
        .result { padding: 6px 0; border-bottom: 1px solid #5c4c3a; font-size: 13px; }
        .result.ok { color: #8ab88a; }
        .result.fail { color: #e07a5f; }
        .result .line { color: #c9b28a; font-family: monospace; font-size: 11.5px; display: block; }
        .fill-note { color: #e6c766; font-size: 12px; margin-top: 4px; }
        .fill-note button { margin-top: 4px; padding: 4px 10px; font-size: 11.5px; background: #8ab88a; color: #1c140f; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Bulk add cards</h1>
    <form id="bulk-form">
        <label>Paste your list, one card per line
            <textarea name="card_list" id="card_list" placeholder="1 Reckless Impulse (PLST) VOW-174&#10;1 Skullclamp (MSC) 210&#10;1 Sol Ring (MSC) 213" required></textarea>
        </label>
        <p class="hint">Format: quantity, card name, set code in parentheses, collector number -- exactly like the example above. Each card is looked up by its EXACT printing, so the set code and number matter.</p>
        <label>Add all of these to
            <select name="container_id" id="container_id">
                <option value="">Unsorted (Collection)</option>
                {% for c in containers %}
                <option value="{{ c['id'] }}">{{ c['name'] }} ({{ c['kind'] }})</option>
                {% endfor %}
            </select>
        </label>
        <button type="submit" id="submit-btn">Add all</button>
    </form>

    <div id="progress"></div>
    <div id="results"></div>

    <p style="margin-top:16px;"><a href="/tracker">&larr; Back to card tracker</a></p>

<script>
document.getElementById('bulk-form').addEventListener('submit', async function(event) {
    event.preventDefault();

    const textarea = document.getElementById('card_list');
    const containerId = document.getElementById('container_id').value;
    const lines = textarea.value.split('\\n').map(l => l.trim()).filter(l => l.length > 0);

    const progressDiv = document.getElementById('progress');
    const resultsDiv = document.getElementById('results');
    const submitBtn = document.getElementById('submit-btn');
    resultsDiv.innerHTML = '';
    submitBtn.disabled = true;

    for (let i = 0; i < lines.length; i++) {
        progressDiv.textContent = 'Adding ' + (i + 1) + ' of ' + lines.length + '...';

        let result;
        try {
            const response = await fetch('/bulk-add/line', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({line: lines[i], container_id: containerId})
            });
            result = await response.json();
        } catch (err) {
            result = {ok: false, line: lines[i], message: 'Something went wrong talking to the server.'};
        }

        const row = document.createElement('div');
        row.className = 'result ' + (result.ok ? 'ok' : 'fail');

        const msgDiv = document.createElement('div');
        msgDiv.textContent = result.message;
        row.appendChild(msgDiv);

        const lineSpan = document.createElement('span');
        lineSpan.className = 'line';
        lineSpan.textContent = result.line;
        row.appendChild(lineSpan);

        if (result.fill_options && result.fill_options.length > 0) {
            result.fill_options.forEach(function(opt) {
                const fillDiv = document.createElement('div');
                fillDiv.className = 'fill-note';
                fillDiv.textContent = 'This fills a MISSING slot in "' + opt.deck_name + '" (needs ' + opt.missing_qty + ' more). ';

                const fillBtn = document.createElement('button');
                fillBtn.type = 'button';
                fillBtn.textContent = 'Fill it';
                fillBtn.addEventListener('click', async function() {
                    fillBtn.disabled = true;
                    fillBtn.textContent = 'Filling...';
                    const fillResp = await fetch('/fill-missing/ajax', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            source_item_id: opt.source_item_id,
                            missing_item_id: opt.missing_item_id,
                            quantity: opt.fillable
                        })
                    });
                    fillBtn.textContent = 'Filled!';
                });
                fillDiv.appendChild(fillBtn);
                row.appendChild(fillDiv);
            });
        }

        resultsDiv.appendChild(row);
    }

    progressDiv.textContent = 'Done -- ' + lines.length + ' line' + (lines.length === 1 ? '' : 's') + ' processed.';
    submitBtn.disabled = false;
});
</script>
</body>
</html>
"""

VERSION_PICKER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Change version</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; }
        h1 { font-family: Georgia, serif; font-size: 22px; }
        .printing { display: flex; gap: 14px; align-items: center; border-bottom: 1px solid #5c4c3a; padding: 12px 0; }
        .printing img { height: 90px; border-radius: 4px; }
        .printing-info { flex: 1; }
        .printing-info b { font-family: Georgia, serif; }
        button { padding: 6px 12px; background: #f0e6d2; border: none; border-radius: 4px; cursor: pointer; margin-top: 6px; }
        a { color: #e6c766; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>Change version: {{ item['name'] }}</h1>
    {% if printings %}
        {% for p in printings %}
        <div class="printing">
            {% if p['image_uris'] %}<img src="{{ p['image_uris']['small'] }}">{% endif %}
            <div class="printing-info">
                <div><b>{{ p['set_name'] }}</b> ({{ p['set'] }}) &mdash; {{ p['released_at'] }}</div>
                <form method="POST" action="/edit/{{ item['id'] }}/version/confirm">
                    <input type="hidden" name="scryfall_id" value="{{ p['id'] }}">
                    <button type="submit">Use this printing</button>
                </form>
            </div>
        </div>
        {% endfor %}
    {% else %}
        <p>No printings found.</p>
    {% endif %}
    <p style="margin-top:16px;"><a href="/edit/{{ item['id'] }}">&larr; Cancel</a></p>
</body>
</html>
"""


@app.route("/bulk-add")
def bulk_add_page():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    containers = conn.execute("SELECT id, name, kind FROM containers ORDER BY name").fetchall()
    conn.close()
    return render_template_string(BULK_ADD_TEMPLATE, containers=containers)


@app.route("/bulk-add/line", methods=["POST"])
def bulk_add_line():
    data = request.get_json()
    line = data.get("line", "")
    container_id = data.get("container_id") or None

    parsed = parse_bulk_line(line)
    if not parsed:
        return jsonify({
            "ok": False, "line": line,
            "message": "Couldn't read this line -- expected format: 1 Card Name (SET) 123",
        })

    try:
        card = fetch_card_by_set_number(parsed["set_code"], parsed["collector_number"])
    except Exception:
        return jsonify({
            "ok": False, "line": line,
            "message": f"Couldn't find a card in set \"{parsed['set_code']}\" #{parsed['collector_number']}",
        })

    save_card(card)
    new_item_id = save_to_collection(
        card["id"], parsed["quantity"], "NM", False, container_id=container_id, is_missing=0
    )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    matches = find_decks_missing_card(conn, card["name"])
    conn.close()

    fill_options = [
        {
            "deck_id": m["deck_id"],
            "deck_name": m["deck_name"],
            "missing_item_id": m["missing_item_id"],
            "missing_qty": m["missing_qty"],
            "fillable": min(parsed["quantity"], m["missing_qty"]),
            "source_item_id": new_item_id,
        }
        for m in matches
    ]

    return jsonify({
        "ok": True, "line": line,
        "message": f"Added {parsed['quantity']}x {card['name']} ({card.get('set_name')})",
        "fill_options": fill_options,
    })


@app.route("/fill-missing/ajax", methods=["POST"])
def fill_missing_ajax():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    moved = fill_missing_in_deck(
        conn, int(data["source_item_id"]), int(data["missing_item_id"]), int(data["quantity"])
    )
    conn.close()
    return jsonify({"moved": moved})


@app.route("/edit/<int:item_id>/version")
def change_version_page(item_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    item = conn.execute(
        """
        SELECT collection_items.id, card_catalog.name
        FROM collection_items
        JOIN card_catalog ON collection_items.card_id = card_catalog.id
        WHERE collection_items.id = ?
        """,
        (item_id,),
    ).fetchone()
    conn.close()

    if item is None:
        return "That card doesn't exist.", 404

    printings = search_all_printings(item["name"])
    return render_template_string(VERSION_PICKER_TEMPLATE, item=item, printings=printings)


@app.route("/edit/<int:item_id>/version/confirm", methods=["POST"])
def change_version_confirm(item_id):
    scryfall_id = request.form["scryfall_id"]
    card = fetch_card_by_id(scryfall_id)
    save_card(card)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE collection_items SET card_id = ? WHERE id = ?", (card["id"], item_id))
    conn.commit()
    conn.close()
    return redirect(f"/edit/{item_id}")


FILL_MISSING_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Fill a missing card?</title>
    <style>
        body { font-family: sans-serif; background: #241b15; color: #f0e6d2; padding: 24px; max-width: 460px; }
        h1 { font-family: Georgia, serif; font-size: 19px; }
        .match { border-bottom: 1px solid #5c4c3a; padding: 12px 0; }
        .match b { font-family: Georgia, serif; }
        form.inline { display: flex; gap: 8px; align-items: center; margin-top: 6px; }
        form.inline input { width: 55px; padding: 5px; border-radius: 4px; border: 1px solid #5c4c3a; }
        button { padding: 6px 12px; background: #8ab88a; color: #1c140f; border: none; border-radius: 4px; cursor: pointer; }
        a { color: #e6c766; }
    </style>
</head>
<body>
<div style="margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #5c4c3a;font-size:13px;"><a href="/" style="color:#e6c766;text-decoration:none;margin-right:14px;">Containers</a><a href="/tracker" style="color:#e6c766;text-decoration:none;margin-right:14px;">Card Tracker</a><a href="/loans" style="color:#e6c766;text-decoration:none;">Loans</a></div>
    <h1>You added {{ quantity }}x {{ card_name }}</h1>
    <p>This card is marked MISSING in:</p>
    {% for opt in fill_options %}
    <div class="match">
        <b>{{ opt['deck_name'] }}</b> needs {{ opt['missing_qty'] }} more
        <form class="inline" method="POST" action="/fill-missing">
            <input type="hidden" name="source_item_id" value="{{ source_item_id }}">
            <input type="hidden" name="missing_item_id" value="{{ opt['missing_item_id'] }}">
            <input type="hidden" name="fallback_url" value="{{ fallback_url }}">
            <input type="number" name="quantity" value="{{ opt['fillable'] }}" min="1" max="{{ opt['fillable'] }}">
            <button type="submit">Fill this deck</button>
        </form>
    </div>
    {% endfor %}
    <p style="margin-top:16px;"><a href="{{ fallback_url }}">Skip -- just keep it in my collection</a></p>
</body>
</html>
"""


@app.route("/fill-missing", methods=["POST"])
def fill_missing():
    source_item_id = int(request.form["source_item_id"])
    missing_item_id = int(request.form["missing_item_id"])
    quantity = int(request.form["quantity"])
    fallback_url = request.form.get("fallback_url") or "/tracker"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    fill_missing_in_deck(conn, source_item_id, missing_item_id, quantity)
    conn.close()

    return redirect(fallback_url)


if __name__ == "__main__":
    app.run(debug=True)
