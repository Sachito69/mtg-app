"""
A simple webpage that shows everything in your collection.

How to run it:
    python app.py

Then open a web browser and go to:
    http://127.0.0.1:5000

Press Ctrl+C in the terminal to stop it when you're done.
"""

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    jsonify,
    session,
    url_for,
)
import re
import os

from add_card import search_all_printings, fetch_card_by_id, fetch_card_by_name, fetch_card_by_set_number, parse_bulk_line, save_card, save_to_collection, autocomplete_card_name
from deck_logic import find_real_sources, total_real_available, move_real_into_deck, find_decks_missing_card, fill_missing_in_deck, check_deck_legality, FORMAT_RULES
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

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


def _sb():
    """Authenticated Supabase client for the current logged-in user."""
    client = get_user_supabase()
    if client is None:
        raise RuntimeError("You must be logged in.")
    return client


def _uid():
    user_id = session.get("user_id")
    if not user_id:
        raise RuntimeError("You must be logged in.")
    return user_id


def _card_map(db, card_ids):
    """Return {card_id: card_catalog row} for the supplied ids."""
    ids = list(dict.fromkeys([x for x in card_ids if x]))
    if not ids:
        return {}
    result = db.table("card_catalog").select("*").in_("id", ids).execute()
    return {row["id"]: row for row in (result.data or [])}


def _container_map(db):
    result = (
        db.table("containers")
        .select("*")
        .eq("user_id", _uid())
        .execute()
    )
    return {row["id"]: row for row in (result.data or [])}


def _get_container(db, container_id):
    result = (
        db.table("containers")
        .select("*")
        .eq("user_id", _uid())
        .eq("id", container_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _get_item(db, item_id):
    result = (
        db.table("collection_items")
        .select("*")
        .eq("user_id", _uid())
        .eq("id", item_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_setting(db, key, default=None):
    result = (
        db.table("settings")
        .select("value")
        .eq("user_id", _uid())
        .eq("key", key)
        .limit(1)
        .execute()
    )
    return result.data[0]["value"] if result.data else default


def set_setting(db, key, value):
    (
        db.table("settings")
        .upsert(
            {"user_id": _uid(), "key": key, "value": value},
            on_conflict="user_id,key",
        )
        .execute()
    )


# A simple HTML template. {{ }} are placeholders Flask fills in with real data.
PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Card Tracker</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
    <div class="tracker-heading">
        <h1>Card Tracker</h1>
        <button type="button" class="primary tracker-add-btn"
                onclick="document.getElementById('add-card-modal').showModal()">+ Add Card</button>
    </div>
    <form method="GET" class="tracker-toolbar" id="tracker-filter-form">
        <div class="tracker-search-wrap">
            <input type="search" name="q" value="{{ search_query }}" placeholder="Search your cards...">
            <button type="submit" class="secondary">Search</button>
        </div>
        <button type="button" class="secondary filter-popup-button"
                onclick="document.getElementById('tracker-filter-modal').showModal()">
            Filters{% if active_filter_count %} ({{ active_filter_count }}){% endif %}
        </button>

        <dialog id="tracker-filter-modal" class="deck-modal tracker-filter-modal">
            <div class="filter-modal-heading">
                <h2>Filter Cards</h2>
                <button type="button" class="dialog-close"
                        onclick="document.getElementById('tracker-filter-modal').close()">&times;</button>
            </div>

            <fieldset class="color-filter-fieldset">
                <legend>Color</legend>
                <div class="color-check-grid">
                    {% for code, label in [('W','White'),('U','Blue'),('B','Black'),('R','Red'),('G','Green'),('C','Colorless'),('M','Multicolor')] %}
                    <label class="check-option">
                        <input type="checkbox" name="color" value="{{ code }}" {% if code in color_filters %}checked{% endif %}>
                        <span>{{ label }}</span>
                    </label>
                    {% endfor %}
                </div>
            </fieldset>

            <label>Card type
                <select name="ptype">
                    <option value="all">All types</option>
                    {% for t in primary_types %}
                    <option value="{{ t }}" {% if type_filter == t %}selected{% endif %}>{{ t }}</option>
                    {% endfor %}
                </select>
            </label>

            <label>Mana value
                <input type="number" name="cmc" min="0" step="1"
                       value="{{ cmc_filter if cmc_filter != 'all' else '' }}"
                       placeholder="Any">
            </label>

            <div class="modal-actions">
                <a href="/tracker{% if search_query %}?q={{ search_query|urlencode }}{% endif %}" class="button-link secondary">Clear filters</a>
                <button type="submit" class="primary">Apply Filters</button>
            </div>
        </dialog>
    </form>
    {% if cards %}
    <div class="grid">
        {% for card in cards %}
        <div class="card-tile tracker-card-tile">
            <details class="card-options tracker-card-options">
                <summary title="Card options">&#8942;</summary>
                <div class="options-dropdown">
                    {% if card['loan_transaction_id'] %}
                    <form method="POST" action="/community/return-borrowed/{{ card['loan_transaction_id'] }}"
                          onsubmit="return confirm('Return this card to {{ card['loaned_from_email'] }}?');">
                        <button type="submit">Return to lender</button>
                    </form>
                    {% else %}
                    <a href="/edit/{{ card['id'] }}">Edit</a>
                    <a href="/community/trade-picker/{{ card['id'] }}/loan">Loan</a>
                    <a href="/community/trade-picker/{{ card['id'] }}/sale">Sell</a>
                    <form method="POST" action="/delete/{{ card['id'] }}"
                          onsubmit="return confirm('Remove this card from your collection?');">
                        <button type="submit" class="danger">Delete</button>
                    </form>
                    {% endif %}
                </div>
            </details>
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
                {% if card['lent_to'] %}
                    {% for loan in card['lent_to'] %}
                    <div class="lent-tag">Lent {{ loan.quantity }}x to @{{ loan.username or loan.email }}</div>
                    {% endfor %}
                {% else %}
                <div class="location-tag">
                    {% if card['location_name'] %}In: {{ card['location_name'] }} ({{ card['location_kind'] }}){% else %}Unsorted{% endif %}
                </div>
                {% endif %}
                {% if card['loan_transaction_id'] %}
                <div class="borrowed-tag">Loaned from {{ card['loaned_from_email'] }}</div>
                {% endif %}
                {% if loans_by_item.get(card['id']) %}
                <div class="loan-tag">
                    {% for l in loans_by_item.get(card['id']) %}Loaned {{ l['quantity_out'] }}x to {{ l['borrower_name'] }}{% if not loop.last %}, {% endif %}{% endfor %}
                </div>
                {% endif %}

            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p class="empty">Your collection is empty so far. Click "+ Add Card" above to get started!</p>
    {% endif %}

    <dialog id="add-card-modal" class="deck-modal add-card-modal">
        <form method="POST" action="/add">
            <h2>Add a Card</h2>
            <p class="modal-hint">Search for a Magic card by name.</p>
            <input type="hidden" name="container_id" value="">
            <label>Card name
                <div class="autocomplete-wrap">
                    <input type="text" name="card_name" id="tracker-card-name-input"
                           placeholder="e.g. Lightning Bolt" required autocomplete="off">
                    <div id="tracker-suggestions-box" class="suggestions-list"></div>
                </div>
            </label>
            <div class="modal-actions">
                <button type="button" class="secondary"
                        onclick="document.getElementById('add-card-modal').close()">Cancel</button>
                <button type="submit" class="primary">Find Card</button>
            </div>
        </form>
    </dialog>

<script>
const addCardModal = document.getElementById('add-card-modal');
const trackerCardInput = document.getElementById('tracker-card-name-input');
const trackerSuggestions = document.getElementById('tracker-suggestions-box');
let trackerAutocompleteTimer = null;

addCardModal.addEventListener('click', function(event) {
    if (event.target === addCardModal) addCardModal.close();
});

trackerCardInput.addEventListener('input', function() {
    clearTimeout(trackerAutocompleteTimer);
    const q = this.value.trim();
    if (q.length < 2) {
        trackerSuggestions.innerHTML = '';
        trackerSuggestions.style.display = 'none';
        return;
    }
    trackerAutocompleteTimer = setTimeout(async function() {
        try {
            const response = await fetch('/autocomplete?q=' + encodeURIComponent(q));
            const names = await response.json();
            trackerSuggestions.innerHTML = '';
            names.forEach(function(name) {
                const row = document.createElement('div');
                row.className = 'suggestion-item';
                row.textContent = name;
                row.addEventListener('click', function() {
                    trackerCardInput.value = name;
                    trackerSuggestions.innerHTML = '';
                    trackerSuggestions.style.display = 'none';
                });
                trackerSuggestions.appendChild(row);
            });
            trackerSuggestions.style.display = names.length ? 'block' : 'none';
        } catch (e) {
            trackerSuggestions.style.display = 'none';
        }
    }, 180);
});
</script>
</body>
</html>
"""


DECK_DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ container['name'] }}</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
    <h1>{{ container['name'] }} <span class="kind-tag">(deck{% if container['format'] %} &middot; {{ container['format'] }}{% endif %})</span></h1>
    <form class="deck-search-bar" method="POST" action="/add">
        <input type="hidden" name="container_id" value="{{ container['id'] }}">
        <div class="autocomplete-wrap" style="flex:1;">
            <input type="text" name="card_name" id="deck-card-name-input" placeholder="Search a card to add to this deck..." required autocomplete="off">
            <div id="deck-suggestions-box" class="suggestions-list"></div>
        </div>
        <button type="submit">Search</button>
    </form>
    <p class="deck-bulk-links">
        <button type="button" class="link-btn" onclick="document.getElementById('bulk-add-modal').showModal()">Bulk add cards to this deck</button>
        &middot;
        <button type="button" class="link-btn" onclick="document.getElementById('bulk-edit-modal').showModal()">Bulk edit missing cards</button>
    </p>

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

    <dialog id="bulk-add-modal" class="deck-modal">
        <h3>Bulk add cards to "{{ container['name'] }}"</h3>
        <p class="modal-hint">Format: quantity, card name, set code in parentheses, collector number. One per line.</p>
        <textarea id="bulk-add-textarea" placeholder="1 Reckless Impulse (PLST) VOW-174&#10;1 Skullclamp (MSC) 210&#10;1 Sol Ring (MSC) 213"></textarea>
        <div id="bulk-add-progress" class="modal-progress"></div>
        <div id="bulk-add-results" class="modal-results"></div>
        <div class="modal-actions">
            <button type="button" onclick="document.getElementById('bulk-add-modal').close()">Close</button>
            <button type="button" class="primary" id="bulk-add-submit" onclick="runBulkAdd()">Add all</button>
        </div>
    </dialog>

    <dialog id="bulk-edit-modal" class="deck-modal">
        <h3>Bulk edit missing cards: "{{ container['name'] }}"</h3>
        <p class="modal-hint">This only edits this deck's MISSING (wishlist) cards -- real cards you already own here are never touched. Edit a quantity, delete a line to remove that card, or add "qty Card Name" for something new.</p>
        <textarea id="bulk-edit-textarea">{{ missing_text }}</textarea>
        <div id="bulk-edit-results" class="modal-results"></div>
        <div class="modal-actions">
            <button type="button" onclick="document.getElementById('bulk-edit-modal').close()">Close</button>
            <button type="button" class="primary" id="bulk-edit-submit" onclick="runBulkEdit()">Apply changes</button>
        </div>
    </dialog>

<script>
async function runBulkAdd() {
    const textarea = document.getElementById('bulk-add-textarea');
    const lines = textarea.value.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
    const progressDiv = document.getElementById('bulk-add-progress');
    const resultsDiv = document.getElementById('bulk-add-results');
    const submitBtn = document.getElementById('bulk-add-submit');
    resultsDiv.innerHTML = '';
    submitBtn.disabled = true;

    for (let i = 0; i < lines.length; i++) {
        progressDiv.textContent = 'Adding ' + (i + 1) + ' of ' + lines.length + '...';
        let result;
        try {
            const resp = await fetch('/bulk-add/line', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({line: lines[i], container_id: '{{ container["id"] }}'})
            });
            result = await resp.json();
        } catch (err) {
            result = {ok: false, line: lines[i], message: 'Something went wrong talking to the server.'};
        }
        const row = document.createElement('div');
        row.className = 'modal-result-row ' + (result.ok ? 'ok' : 'fail');
        row.textContent = result.message;
        resultsDiv.appendChild(row);
    }
    progressDiv.textContent = 'Done -- reopen this window or refresh the page to see the updated deck.';
    submitBtn.disabled = false;
}

async function runBulkEdit() {
    const textarea = document.getElementById('bulk-edit-textarea');
    const resultsDiv = document.getElementById('bulk-edit-results');
    const submitBtn = document.getElementById('bulk-edit-submit');
    resultsDiv.innerHTML = '';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Applying...';

    try {
        const resp = await fetch('/containers/{{ container["id"] }}/bulk-edit/apply', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({card_list: textarea.value})
        });
        const data = await resp.json();
        data.results.forEach(function(r) {
            const row = document.createElement('div');
            row.className = 'modal-result-row ' + (r.ok ? 'ok' : 'fail');
            row.textContent = r.message;
            resultsDiv.appendChild(row);
        });
        if (data.results.length === 0) {
            const row = document.createElement('div');
            row.className = 'modal-result-row ok';
            row.textContent = 'No changes.';
            resultsDiv.appendChild(row);
        }
    } catch (err) {
        resultsDiv.textContent = 'Something went wrong talking to the server.';
    }
    submitBtn.disabled = false;
    submitBtn.textContent = 'Apply changes';
}
</script>

<script>
function setDeckView(mode) {
    document.getElementById('view-text').style.display = (mode === 'text') ? 'block' : 'none';
    document.getElementById('view-stacks').style.display = (mode === 'stacks') ? 'block' : 'none';
    document.getElementById('view-grid').style.display = (mode === 'grid') ? 'block' : 'none';
}

(function() {
    const input = document.getElementById('deck-card-name-input');
    const box = document.getElementById('deck-suggestions-box');
    let debounceTimer;
    input.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        const q = input.value.trim();
        if (q.length < 2) { box.innerHTML = ''; return; }
        debounceTimer = setTimeout(async function() {
            try {
                const resp = await fetch('/card-suggestions?q=' + encodeURIComponent(q));
                const names = await resp.json();
                box.innerHTML = '';
                names.forEach(function(name) {
                    const item = document.createElement('div');
                    item.className = 'suggestion-item';
                    item.textContent = name;
                    item.addEventListener('click', function() {
                        input.value = name;
                        box.innerHTML = '';
                    });
                    box.appendChild(item);
                });
            } catch (err) { box.innerHTML = ''; }
        }, 200);
    });
    document.addEventListener('click', function(e) {
        if (e.target !== input) box.innerHTML = '';
    });
})();
</script>
</body>
</html>
"""

EDIT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Edit {{ item['name'] }}</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
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

MOVE_OR_MISSING_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>You already own this</title>
    <link rel="stylesheet" href="/static/style.css">
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

PRINTINGS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Choose a printing</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
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

QUICK_ADD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Add {{ card['name'] }}</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
    <h1>Add this card</h1>
    <div class="quick-card">
        {% if card.get('image_uris') %}<img src="{{ card['image_uris']['normal'] }}">{% endif %}
        <div class="quick-info">
            <b>{{ card['name'] }}</b>
            <div>{{ card.get('set_name') }} ({{ card.get('set') }})</div>
            <div>{{ card.get('type_line') }}</div>
        </div>
    </div>
    <form class="details" method="POST" action="/add/confirm">
        <input type="hidden" name="scryfall_id" value="{{ card['id'] }}">
        <input type="hidden" name="container_id" value="{{ container_id or '' }}">
        <label>Quantity
            <input type="number" name="quantity" value="1" min="1">
        </label>
        <label>Condition
            <select name="condition">
                {% for c in ['NM', 'LP', 'MP', 'HP', 'DMG'] %}
                <option value="{{ c }}">{{ c }}</option>
                {% endfor %}
            </select>
        </label>
        <label><input type="checkbox" name="foil" style="width:auto;"> Foil</label>
        <button type="submit">Add this printing</button>
    </form>
    <p class="browse-note">
        <form method="POST" action="/add" style="display:inline;">
            <input type="hidden" name="card_name" value="{{ card_name }}">
            <input type="hidden" name="container_id" value="{{ container_id or '' }}">
            <input type="hidden" name="force_picker" value="1">
            <a href="#" onclick="this.closest('form').submit(); return false;">Not the right printing? Browse all versions instead &rarr;</a>
        </form>
    </p>
</body>
</html>
"""

SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Add a card</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
    <h1>Add a card</h1>
    <form method="POST" action="/add">
        <input type="hidden" name="container_id" value="{{ container_id or '' }}">
        <label>Card name<br>
            <div class="autocomplete-wrap">
                <input type="text" name="card_name" id="card-name-input" placeholder="e.g. Lightning Bolt" required autofocus autocomplete="off">
                <div id="suggestions-box" class="suggestions-list"></div>
            </div>
        </label>
        <button type="submit">Find printings</button>
    </form>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p style="margin-top:14px;"><a href="/bulk-add">Bulk add a list of cards instead &rarr;</a></p>
    <p><a href="/tracker">&larr; Back to card tracker</a></p>

<script>
(function() {
    const input = document.getElementById('card-name-input');
    const box = document.getElementById('suggestions-box');
    let debounceTimer;
    input.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        const q = input.value.trim();
        if (q.length < 2) { box.innerHTML = ''; return; }
        debounceTimer = setTimeout(async function() {
            try {
                const resp = await fetch('/card-suggestions?q=' + encodeURIComponent(q));
                const names = await resp.json();
                box.innerHTML = '';
                names.forEach(function(name) {
                    const item = document.createElement('div');
                    item.className = 'suggestion-item';
                    item.textContent = name;
                    item.addEventListener('click', function() {
                        input.value = name;
                        box.innerHTML = '';
                    });
                    box.appendChild(item);
                });
            } catch (err) { box.innerHTML = ''; }
        }, 200);
    });
    document.addEventListener('click', function(e) {
        if (e.target !== input) box.innerHTML = '';
    });
})();
</script>
</body>
</html>
"""

SETTINGS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Settings</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
    <h1>Settings</h1>
    <form method="POST">
        <div class="setting-row">
            <label>
                <input type="checkbox" name="auto_pick_version" {% if auto_pick_version %}checked{% endif %}>
                <div>
                    <div class="setting-title">Automatically pick a printing when searching</div>
                    <div class="setting-desc">When you add a card by name, skip straight to the default/most recent printing instead of showing every printing to choose from. You can still browse all printings from that screen if the auto-picked one isn't right. Turn this off to always see the full printing picker.</div>
                </div>
            </label>
        </div>
        <button type="submit">Save</button>
    </form>
    {% if saved %}<p class="saved-note">Saved.</p>{% endif %}
</body>
</html>
"""

@app.route("/tracker")
def show_collection():
    search_query = (request.args.get("q") or "").strip()
    color_filters = [c for c in request.args.getlist("color") if c in ("W","U","B","R","G","C","M")]
    type_filter = request.args.get("ptype", "all")
    cmc_raw = (request.args.get("cmc") or "").strip()
    cmc_filter = cmc_raw if cmc_raw.isdigit() else "all"

    db = _sb()
    uid = _uid()

    item_result = (
        db.table("collection_items")
        .select("*")
        .eq("user_id", uid)
        .eq("is_missing", False)
        .execute()
    )
    items = item_result.data or []
    cards = _card_map(db, [item["card_id"] for item in items])
    containers = _container_map(db)

    lender_ids = list({
        item.get("loaned_from_user_id")
        for item in items if item.get("loaned_from_user_id")
    })
    lender_profiles = {}
    if lender_ids:
        lender_profiles = {
            p["user_id"]: p
            for p in db.table("profiles").select("user_id,email,username").in_("user_id", lender_ids).execute().data or []
        }

    # Active loans sent by this user. These keep the lender's original card
    # in their tracker, but label it with the borrower instead of "Unsorted".
    sent_loans = (
        db.table("card_transactions")
        .select("id,source_item_id,friend_id,quantity")
        .eq("owner_id", uid)
        .eq("transaction_type", "loan")
        .eq("status", "accepted")
        .is_("returned_at", "null")
        .execute()
    ).data or []
    borrower_ids = list({loan.get("friend_id") for loan in sent_loans if loan.get("friend_id")})
    borrower_profiles = {}
    if borrower_ids:
        borrower_profiles = {
            p["user_id"]: p
            for p in db.table("profiles").select("user_id,email,username").in_("user_id", borrower_ids).execute().data or []
        }
    loans_sent_by_item = {}
    for loan in sent_loans:
        loans_sent_by_item.setdefault(loan.get("source_item_id"), []).append(loan)

    rows = []
    primary_types_set = set()

    # Build type choices from the whole collection before applying filters.
    for item in items:
        card = cards.get(item["card_id"])
        if card:
            type_line = card.get("type_line") or ""
            if type_line:
                for main_type in ("Creature","Planeswalker","Instant","Sorcery","Artifact","Enchantment","Land","Battle"):
                    if main_type in type_line:
                        primary_types_set.add(main_type)

    for item in items:
        card = cards.get(item["card_id"])
        if not card:
            continue

        name = card.get("name") or ""
        type_line = card.get("type_line") or ""
        colors = card.get("colors") or []
        cmc = card.get("cmc")

        if search_query and search_query.lower() not in name.lower():
            continue

        if color_filters:
            color_match = False
            for color_filter in color_filters:
                if color_filter == "C" and not colors:
                    color_match = True
                elif color_filter == "M" and len(colors) > 1:
                    color_match = True
                elif color_filter in ("W","U","B","R","G") and color_filter in colors:
                    color_match = True
            if not color_match:
                continue

        if type_filter != "all" and type_filter not in type_line:
            continue

        if cmc_filter != "all":
            if cmc is None or float(cmc) != int(cmc_filter):
                continue

        container = containers.get(item.get("container_id"))
        lender_id = item.get("loaned_from_user_id")
        rows.append({
            "id": item["id"],
            "name": name,
            "set_name": card.get("set_name"),
            "type_line": type_line,
            "image_url": card.get("image_url"),
            "colors": colors,
            "cmc": cmc,
            "quantity": item["quantity"],
            "condition": item["condition"],
            "foil": item["foil"],
            "location_name": container.get("name") if container else None,
            "location_kind": container.get("kind") if container else None,
            "loaned_from_user_id": lender_id,
            "loaned_from_email": lender_profiles.get(lender_id, {}).get("email", "another user") if lender_id else None,
            "loan_transaction_id": item.get("loan_transaction_id"),
            "lent_to": [
                {
                    "transaction_id": loan.get("id"),
                    "quantity": loan.get("quantity"),
                    "username": borrower_profiles.get(loan.get("friend_id"), {}).get("username"),
                    "email": borrower_profiles.get(loan.get("friend_id"), {}).get("email", "another user"),
                }
                for loan in loans_sent_by_item.get(item["id"], [])
            ],
        })

    rows.sort(key=lambda row: (row.get("name") or "").lower())
    primary_types = sorted(primary_types_set)

    loan_result = (
        db.table("loans")
        .select("collection_item_id, borrower_name, quantity_out")
        .eq("user_id", uid)
        .is_("returned_at", "null")
        .execute()
    )
    loans_by_item = {}
    for loan in loan_result.data or []:
        loans_by_item.setdefault(loan["collection_item_id"], []).append(loan)

    return render_template_string(
        PAGE_TEMPLATE,
        cards=rows,
        loans_by_item=loans_by_item,
        primary_types=primary_types,
        search_query=search_query,
        color_filters=color_filters,
        type_filter=type_filter,
        cmc_filter=cmc_filter,
        active_filter_count=len(color_filters) + (1 if type_filter != "all" else 0) + (1 if cmc_filter != "all" else 0),
    )


@app.route("/edit/<int:item_id>", methods=["GET", "POST"])
def edit_item(item_id):
    db = _sb()
    uid = _uid()

    if request.method == "POST":
        quantity = int(request.form["quantity"])
        condition = request.form["condition"]
        foil = bool(request.form.get("foil"))
        container_id = request.form.get("container_id") or None

        if quantity <= 0:
            (
                db.table("collection_items")
                .delete()
                .eq("user_id", uid)
                .eq("id", item_id)
                .execute()
            )
        else:
            (
                db.table("collection_items")
                .update({
                    "quantity": quantity,
                    "condition": condition,
                    "foil": foil,
                    "container_id": container_id,
                })
                .eq("user_id", uid)
                .eq("id", item_id)
                .execute()
            )
        return redirect("/tracker")

    item_row = _get_item(db, item_id)
    if item_row is None:
        return "That collection item doesn't exist.", 404

    card = _card_map(db, [item_row["card_id"]]).get(item_row["card_id"])
    if card is None:
        return "That card doesn't exist.", 404

    item = dict(item_row)
    item["name"] = card["name"]

    container_result = (
        db.table("containers")
        .select("id, name, kind")
        .eq("user_id", uid)
        .order("name")
        .execute()
    )
    return render_template_string(
        EDIT_TEMPLATE, item=item, containers=container_result.data or []
    )


@app.route("/delete/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    db = _sb()
    (
        db.table("collection_items")
        .delete()
        .eq("user_id", _uid())
        .eq("id", item_id)
        .execute()
    )
    return redirect("/tracker")


@app.route("/item/<int:item_id>/increment", methods=["POST"])
def increment_item(item_id):
    next_url = request.form.get("next") or "/tracker"
    db = _sb()
    item = _get_item(db, item_id)
    if item:
        (
            db.table("collection_items")
            .update({"quantity": item["quantity"] + 1})
            .eq("user_id", _uid())
            .eq("id", item_id)
            .execute()
        )
    return redirect(next_url)


@app.route("/item/<int:item_id>/decrement", methods=["POST"])
def decrement_item(item_id):
    next_url = request.form.get("next") or "/tracker"
    db = _sb()
    item = _get_item(db, item_id)
    if item:
        if item["quantity"] <= 1:
            (
                db.table("collection_items")
                .delete()
                .eq("user_id", _uid())
                .eq("id", item_id)
                .execute()
            )
        else:
            (
                db.table("collection_items")
                .update({"quantity": item["quantity"] - 1})
                .eq("user_id", _uid())
                .eq("id", item_id)
                .execute()
            )
    return redirect(next_url)


@app.route("/card-suggestions")
def card_suggestions():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    try:
        names = autocomplete_card_name(query)
    except Exception:
        names = []
    return jsonify(names)


@app.route("/add", methods=["GET", "POST"])
def add_card_page():
    if request.method == "GET":
        return render_template_string(SEARCH_TEMPLATE, error=None, container_id=request.args.get("container_id"))

    card_name = request.form["card_name"]
    container_id = request.form.get("container_id") or None
    force_picker = request.form.get("force_picker") == "1"

    db = _sb()
    auto_pick = get_setting(db, "auto_pick_version", "true") == "true"

    if auto_pick and not force_picker:
        try:
            card = fetch_card_by_name(card_name)
        except Exception:
            return render_template_string(
                SEARCH_TEMPLATE,
                error=f'Could not find a card named "{card_name}". Check the spelling and try again.',
                container_id=container_id,
            )
        return render_template_string(QUICK_ADD_TEMPLATE, card=card, card_name=card_name, container_id=container_id)

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
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>

<div class="collection-heading">
    <div>
        <h1>My Collection</h1>
        <p class="hint">Organize your cards into decks, binders, and boxes.</p>
    </div>
    <button type="button" class="primary collection-add-btn"
            onclick="document.getElementById('create-container-modal').showModal()">+ Add</button>
</div>

<div class="collection-kind-filter">
    <a href="/" class="{% if not active_kind %}active{% endif %}">All</a>
    <a href="/?kind=deck" class="{% if active_kind == 'deck' %}active{% endif %}">Decks</a>
    <a href="/?kind=binder" class="{% if active_kind == 'binder' %}active{% endif %}">Binders</a>
    <a href="/?kind=box" class="{% if active_kind == 'box' %}active{% endif %}">Boxes</a>
</div>

{% if containers %}
<div class="collection-list">
{% for c in containers %}
<div class="item">
    <div class="icon icon-{{ c['kind'] }}">
        {% if c['kind'] == 'deck' %}<div class="cb"></div><div class="cb"></div><div class="cb"></div>{% endif %}
    </div>
    <div class="item-info">
        <a href="/containers/{{ c['id'] }}">{{ c['name'] }}</a>
        <span class="kind-tag">{{ c['kind']|title }}{% if c['format'] %} &middot; {{ c['format'] }}{% endif %} &mdash; {{ c['card_count'] }} cards</span>
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
</div>
{% else %}
<p class="empty">
{% if active_kind %}
You don't have any {{ active_kind }}s yet.
{% else %}
You haven't made any binders, boxes, or decks yet.
{% endif %}
</p>
{% endif %}

<dialog id="create-container-modal" class="deck-modal collection-create-modal">
    <form method="POST" action="/">
        <h2>Add to Collection</h2>
        <p class="modal-hint">Create a deck, binder, or storage box.</p>

        <label>Name
            <input type="text" name="name" placeholder="e.g. Modern Staples" required>
        </label>

        <label>Type
            <select name="kind" id="kind-select"
                    onchange="document.getElementById('format-field').style.display = this.value === 'deck' ? 'block' : 'none';">
                <option value="deck">Deck</option>
                <option value="binder">Binder</option>
                <option value="box">Box</option>
            </select>
        </label>

        <label id="format-field">Format (decks only)
            <select name="format">
                {% for f in formats %}
                <option value="{{ f }}">{{ f }}</option>
                {% endfor %}
                <option value="Casual">Casual / Other</option>
            </select>
        </label>

        <div class="modal-actions">
            <button type="button" class="secondary"
                    onclick="document.getElementById('create-container-modal').close()">Cancel</button>
            <button type="submit" class="primary">Create</button>
        </div>
    </form>
</dialog>

<script>
const createModal = document.getElementById('create-container-modal');
createModal.addEventListener('click', function (event) {
    if (event.target === createModal) createModal.close();
});
</script>
</body>
</html>
"""

CONTAINER_DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ container['name'] }}</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
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
    if "user_id" not in session:
        return redirect("/login")

    db = _sb()
    uid = _uid()

    if request.method == "POST":
        name = request.form["name"]
        kind = request.form["kind"]
        format_ = request.form.get("format") or None
        (
            db.table("containers")
            .insert({
                "user_id": uid,
                "name": name,
                "kind": kind,
                "format": format_ if kind == "deck" else None,
            })
            .execute()
        )
        return redirect("/")

    container_result = (
        db.table("containers")
        .select("*")
        .eq("user_id", uid)
        .order("name")
        .execute()
    )
    containers = [dict(row) for row in (container_result.data or [])]

    active_kind = (request.args.get("kind") or "").strip().lower()
    if active_kind not in ("deck", "binder", "box"):
        active_kind = ""
    if active_kind:
        containers = [c for c in containers if c.get("kind") == active_kind]

    item_result = (
        db.table("collection_items")
        .select("container_id")
        .eq("user_id", uid)
        .execute()
    )
    counts = {}
    for item in item_result.data or []:
        cid = item.get("container_id")
        if cid is not None:
            counts[cid] = counts.get(cid, 0) + 1

    for container in containers:
        container["card_count"] = counts.get(container["id"], 0)

    return render_template_string(
        CONTAINERS_TEMPLATE,
        containers=containers,
        formats=list(FORMAT_RULES.keys()),
        active_kind=active_kind,
    )


@app.route("/containers/<int:container_id>/delete", methods=["POST"])
def delete_container(container_id):
    db = _sb()
    uid = _uid()

    (
        db.table("collection_items")
        .delete()
        .eq("user_id", uid)
        .eq("container_id", container_id)
        .eq("is_missing", True)
        .execute()
    )
    (
        db.table("collection_items")
        .update({"container_id": None})
        .eq("user_id", uid)
        .eq("container_id", container_id)
        .execute()
    )
    (
        db.table("containers")
        .delete()
        .eq("user_id", uid)
        .eq("id", container_id)
        .execute()
    )
    return redirect("/")


@app.route("/containers/<int:container_id>/duplicate", methods=["POST"])
def duplicate_container(container_id):
    db = _sb()
    uid = _uid()
    original = _get_container(db, container_id)
    if original is None:
        return redirect("/")

    created = (
        db.table("containers")
        .insert({
            "user_id": uid,
            "name": f"{original['name']} (copy)",
            "kind": original["kind"],
            "format": original.get("format"),
        })
        .execute()
    )
    if not created.data:
        return redirect("/")

    new_container_id = created.data[0]["id"]

    if original["kind"] == "deck":
        card_result = (
            db.table("collection_items")
            .select("card_id, quantity")
            .eq("user_id", uid)
            .eq("container_id", container_id)
            .execute()
        )
        for card in card_result.data or []:
            save_to_collection(
                db, uid, card["card_id"], card["quantity"], "NM", False,
                container_id=new_container_id, is_missing=True
            )

    return redirect("/")


@app.route("/containers/<int:container_id>")
def container_detail(container_id):
    db = _sb()
    uid = _uid()
    container = _get_container(db, container_id)
    if container is None:
        return "That container doesn't exist.", 404

    item_result = (
        db.table("collection_items")
        .select("*")
        .eq("user_id", uid)
        .eq("container_id", container_id)
        .execute()
    )
    items = item_result.data or []
    cards_by_id = _card_map(db, [item["card_id"] for item in items])

    cards = []
    for item in items:
        card = cards_by_id.get(item["card_id"])
        if not card:
            continue
        cards.append({
            "item_id": item["id"],
            "name": card.get("name"),
            "set_name": card.get("set_name"),
            "image_url": card.get("image_url"),
            "type_line": card.get("type_line"),
            "quantity": item["quantity"],
            "condition": item["condition"],
            "is_missing": item["is_missing"],
        })

    if container["kind"] == "deck":
        cards.sort(key=lambda row: (bool(row["is_missing"]), (row["name"] or "").lower()))
        legality = check_deck_legality(db, uid, container_id, container.get("format"))

        missing_totals = {}
        for row in cards:
            if row["is_missing"]:
                missing_totals[row["name"]] = missing_totals.get(row["name"], 0) + row["quantity"]
        missing_text = "\n".join(
            f"{qty} {name}" for name, qty in sorted(missing_totals.items())
        )

        return render_template_string(
            DECK_DETAIL_TEMPLATE,
            container=container,
            grouped_cards=group_cards_by_type(cards),
            legality=legality,
            missing_text=missing_text,
        )

    cards.sort(key=lambda row: (row["name"] or "").lower())
    return render_template_string(
        CONTAINER_DETAIL_TEMPLATE, container=container, cards=cards
    )


@app.route("/add/confirm", methods=["POST"])
def add_card_confirm():
    scryfall_id = request.form["scryfall_id"]
    quantity = int(request.form["quantity"])
    condition = request.form["condition"]
    foil = bool(request.form.get("foil"))
    container_id = request.form.get("container_id") or None

    card = fetch_card_by_id(scryfall_id)
    db = _sb()
    uid = _uid()
    save_card(db, card)

    target_kind = None
    if container_id:
        target = _get_container(db, int(container_id))
        target_kind = target["kind"] if target else None

    if target_kind != "deck":
        new_item_id = save_to_collection(
            db, uid, card["id"], quantity, condition, foil,
            container_id=container_id, is_missing=False
        )
        matches = find_decks_missing_card(db, uid, card["name"])
        fallback_url = f"/containers/{container_id}" if container_id else "/tracker"

        if matches:
            fill_options = []
            for m in matches:
                fill_options.append({
                    "deck_id": m["deck_id"],
                    "deck_name": m["deck_name"],
                    "missing_item_id": m["missing_item_id"],
                    "missing_qty": m["missing_qty"],
                    "fillable": min(quantity, m["missing_qty"]),
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

    available = total_real_available(db, uid, card["name"])
    if available <= 0:
        save_to_collection(
            db, uid, card["id"], quantity, condition, foil,
            container_id=container_id, is_missing=True
        )
        return redirect(f"/containers/{container_id}")

    sources = find_real_sources(db, uid, card["name"])
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
    foil = bool(request.form.get("foil"))
    container_id = request.form["container_id"]

    card = fetch_card_by_id(scryfall_id)
    db = _sb()
    uid = _uid()
    save_card(db, card)

    leftover = move_real_into_deck(db, uid, card["name"], container_id, quantity)
    if leftover > 0:
        save_to_collection(
            db, uid, card["id"], leftover, condition, foil,
            container_id=container_id, is_missing=True
        )
    return redirect(f"/containers/{container_id}")


@app.route("/add/confirm/missing", methods=["POST"])
def add_card_confirm_missing():
    scryfall_id = request.form["scryfall_id"]
    quantity = int(request.form["quantity"])
    condition = request.form["condition"]
    foil = bool(request.form.get("foil"))
    container_id = request.form["container_id"]

    card = fetch_card_by_id(scryfall_id)
    db = _sb()
    uid = _uid()
    save_card(db, card)
    save_to_collection(
        db, uid, card["id"], quantity, condition, foil,
        container_id=container_id, is_missing=True
    )
    return redirect(f"/containers/{container_id}")


LOAN_FORM_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Loan out {{ item['name'] }}</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
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
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
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
    db = _sb()
    uid = _uid()
    item_row = _get_item(db, item_id)
    if item_row is None:
        return "That card doesn't exist.", 404

    card = _card_map(db, [item_row["card_id"]]).get(item_row["card_id"])
    if card is None:
        return "That card doesn't exist.", 404

    item = {
        "id": item_row["id"],
        "quantity": item_row["quantity"],
        "name": card["name"],
    }

    loan_result = (
        db.table("loans")
        .select("quantity_out")
        .eq("user_id", uid)
        .eq("collection_item_id", item_id)
        .is_("returned_at", "null")
        .execute()
    )
    already_loaned = sum(row["quantity_out"] for row in (loan_result.data or []))
    available = item["quantity"] - already_loaned

    if request.method == "POST":
        borrower_name = request.form["borrower_name"]
        quantity_out = min(int(request.form["quantity_out"]), available)
        if quantity_out > 0:
            (
                db.table("loans")
                .insert({
                    "user_id": uid,
                    "collection_item_id": item_id,
                    "borrower_name": borrower_name,
                    "quantity_out": quantity_out,
                })
                .execute()
            )
        return redirect("/tracker")

    return render_template_string(
        LOAN_FORM_TEMPLATE, item=item, available=available
    )


@app.route("/loans")
def loans_page():
    db = _sb()
    loan_result = (
        db.table("loans")
        .select("*")
        .eq("user_id", _uid())
        .is_("returned_at", "null")
        .order("loaned_at", desc=True)
        .execute()
    )
    loans = loan_result.data or []
    item_ids = [row["collection_item_id"] for row in loans]
    items = {}
    if item_ids:
        item_result = (
            db.table("collection_items")
            .select("id, card_id")
            .eq("user_id", _uid())
            .in_("id", item_ids)
            .execute()
        )
        items = {row["id"]: row for row in (item_result.data or [])}
    cards = _card_map(db, [row["card_id"] for row in items.values()])
    active = []
    for loan in loans:
        row = dict(loan)
        item = items.get(loan["collection_item_id"])
        card = cards.get(item["card_id"]) if item else None
        row["card_name"] = card["name"] if card else "Unknown card"
        active.append(row)
    return render_template_string(LOANS_TEMPLATE, loans=active)


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
def return_loan(loan_id):
    from datetime import datetime, timezone
    db = _sb()
    (
        db.table("loans")
        .update({"returned_at": datetime.now(timezone.utc).isoformat()})
        .eq("user_id", _uid())
        .eq("id", loan_id)
        .execute()
    )
    return redirect("/loans")


BULK_ADD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Bulk add cards</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
    <h1>Bulk add cards</h1>
    <form id="bulk-form">
        <label>Paste your list, one card per line
            <textarea name="card_list" id="card_list" placeholder="1 Reckless Impulse (PLST) VOW-174&#10;1 Skullclamp (MSC) 210&#10;1 Sol Ring (MSC) 213" required></textarea>
        </label>
        <p class="hint">Format: quantity, card name, set code in parentheses, collector number -- exactly like the example above. Each card is looked up by its EXACT printing, so the set code and number matter.</p>
        {% if preselect_container_id %}
        <p class="hint" style="color:#8ab88a;">Adding to a specific deck/binder/box (selected below) -- change it if that's not right.</p>
        {% endif %}
        <label>Add all of these to
            <select name="container_id" id="container_id">
                <option value="" {% if not preselect_container_id %}selected{% endif %}>Unsorted (Collection)</option>
                {% for c in containers %}
                <option value="{{ c['id'] }}" {% if preselect_container_id and preselect_container_id|string == c['id']|string %}selected{% endif %}>{{ c['name'] }} ({{ c['kind'] }})</option>
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
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
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
    db = _sb()
    result = (
        db.table("containers")
        .select("id, name, kind")
        .eq("user_id", _uid())
        .order("name")
        .execute()
    )
    containers = result.data or []
    preselect_container_id = request.args.get("container_id")
    return render_template_string(
        BULK_ADD_TEMPLATE, containers=containers, preselect_container_id=preselect_container_id
    )


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

    user_supabase = get_user_supabase()

    save_card(user_supabase, card)
    new_item_id = save_to_collection(
        user_supabase, session["user_id"], card["id"], parsed["quantity"], "NM", False,
        container_id=container_id, is_missing=False
    )

    matches = find_decks_missing_card(user_supabase, session["user_id"], card["name"])

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
    db = _sb()
    moved = fill_missing_in_deck(
        db, _uid(),
        int(data["source_item_id"]),
        int(data["missing_item_id"]),
        int(data["quantity"]),
    )
    return jsonify({"moved": moved})


@app.route("/edit/<int:item_id>/version")
def change_version_page(item_id):
    db = _sb()
    item_row = _get_item(db, item_id)
    if item_row is None:
        return "That card doesn't exist.", 404
    card = _card_map(db, [item_row["card_id"]]).get(item_row["card_id"])
    if card is None:
        return "That card doesn't exist.", 404
    item = {"id": item_id, "name": card["name"]}
    printings = search_all_printings(item["name"])
    return render_template_string(VERSION_PICKER_TEMPLATE, item=item, printings=printings)


@app.route("/edit/<int:item_id>/version/confirm", methods=["POST"])
def change_version_confirm(item_id):
    db = _sb()
    scryfall_id = request.form["scryfall_id"]
    card = fetch_card_by_id(scryfall_id)
    save_card(db, card)
    (
        db.table("collection_items")
        .update({"card_id": card["id"]})
        .eq("user_id", _uid())
        .eq("id", item_id)
        .execute()
    )
    return redirect(f"/edit/{item_id}")


FILL_MISSING_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Fill a missing card?</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email", "User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>
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

    db = _sb()
    fill_missing_in_deck(
        db, _uid(), source_item_id, missing_item_id, quantity
    )
    return redirect(fallback_url)


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    db = _sb()
    saved = False
    if request.method == "POST":
        set_setting(
            db,
            "auto_pick_version",
            "true" if request.form.get("auto_pick_version") else "false",
        )
        saved = True
    auto_pick_version = get_setting(db, "auto_pick_version", "true") == "true"
    return render_template_string(
        SETTINGS_TEMPLATE,
        auto_pick_version=auto_pick_version,
        saved=saved,
    )


@app.route("/containers/<int:container_id>/bulk-edit/apply", methods=["POST"])
def bulk_edit_apply(container_id):
    data = request.get_json() or {}
    submitted_text = data.get("card_list", "")
    db = _sb()
    uid = _uid()

    container = _get_container(db, container_id)
    if container is None or container["kind"] != "deck":
        return jsonify({"results": [{"ok": False, "message": "That deck doesn't exist."}]})

    missing_result = (
        db.table("collection_items")
        .select("id, card_id, quantity")
        .eq("user_id", uid)
        .eq("container_id", container_id)
        .eq("is_missing", True)
        .execute()
    )
    missing_items = missing_result.data or []
    cards = _card_map(db, [row["card_id"] for row in missing_items])

    current_by_name = {}
    item_ids_by_name = {}
    for row in missing_items:
        card = cards.get(row["card_id"])
        if not card:
            continue
        name = card["name"]
        current_by_name[name] = current_by_name.get(name, 0) + row["quantity"]
        item_ids_by_name.setdefault(name, []).append(row["id"])

    lines = [line.strip() for line in submitted_text.splitlines() if line.strip()]
    new_wants = {}
    results = []

    for line in lines:
        match = BULK_EDIT_LINE_PATTERN.match(line)
        if not match:
            results.append({
                "ok": False,
                "message": f'Skipped "{line}" -- expected format: qty Card Name',
            })
            continue
        qty, name = match.groups()
        new_wants[name] = int(qty)

    for name in current_by_name:
        if name not in new_wants:
            for item_id in item_ids_by_name.get(name, []):
                (
                    db.table("collection_items")
                    .delete()
                    .eq("user_id", uid)
                    .eq("id", item_id)
                    .execute()
                )
            results.append({"ok": True, "message": f"Removed {name} from the wishlist"})

    for name, qty in new_wants.items():
        if name in current_by_name:
            if qty != current_by_name[name]:
                ids = item_ids_by_name.get(name, [])
                if ids:
                    (
                        db.table("collection_items")
                        .update({"quantity": qty})
                        .eq("user_id", uid)
                        .eq("id", ids[0])
                        .execute()
                    )
                    for extra_id in ids[1:]:
                        (
                            db.table("collection_items")
                            .delete()
                            .eq("user_id", uid)
                            .eq("id", extra_id)
                            .execute()
                        )
                results.append({"ok": True, "message": f"Updated {name} to {qty}x"})
        else:
            try:
                card = fetch_card_by_name(name)
            except Exception:
                card = None
            if card is None:
                results.append({
                    "ok": False,
                    "message": f'Could not find a card named "{name}" -- skipped',
                })
                continue

            save_card(db, card)
            save_to_collection(
                db, uid, card["id"], qty, "NM", False,
                container_id=container_id, is_missing=True
            )
            results.append({
                "ok": True,
                "message": f"Added {name} ({qty}x) as missing",
            })

    return jsonify({"results": results})



@app.context_processor
def inject_profile_context():
    if not session.get("user_id") or not session.get("access_token"):
        return {
            "notification_count": 0,
            "pending_offer_count": 0,
            "current_username": None,
        }
    try:
        db = get_user_supabase()
        uid = session["user_id"]

        fr = (
            db.table("friendships").select("id,requested_by")
            .or_(f"user_a.eq.{uid},user_b.eq.{uid}")
            .eq("status", "pending").execute()
        ).data or []
        friend_count = sum(1 for row in fr if row.get("requested_by") != uid)

        incoming = (
            db.table("card_transactions").select("id")
            .eq("friend_id", uid).eq("status", "pending").execute()
        ).data or []

        outgoing = (
            db.table("card_transactions").select("id")
            .eq("owner_id", uid).eq("status", "pending").execute()
        ).data or []

        profile_rows = (
            db.table("profiles").select("username")
            .eq("user_id", uid).limit(1).execute()
        ).data or []
        username = profile_rows[0].get("username") if profile_rows else None

        return {
            "notification_count": friend_count + len(incoming),
            "pending_offer_count": len(outgoing),
            "current_username": username,
        }
    except Exception:
        return {
            "notification_count": 0,
            "pending_offer_count": 0,
            "current_username": None,
        }

@app.route("/notifications")
def notifications():
    db=_sb(); uid=_uid()
    rows=db.table("friendships").select("*").or_(f"user_a.eq.{uid},user_b.eq.{uid}").eq("status","pending").execute().data or []
    incoming=[r for r in rows if r.get("requested_by") != uid]
    ids=[r.get("requested_by") for r in incoming if r.get("requested_by")]
    pm={}
    if ids: pm={p["user_id"]:p for p in db.table("profiles").select("user_id,email,username").in_("user_id",list(set(ids))).execute().data or []}
    friend_requests=[{"id":r["id"],"email":pm.get(r.get("requested_by"),{}).get("email","Unknown user")} for r in incoming]
    offer_rows=db.table("card_transactions").select("*").eq("friend_id",uid).eq("status","pending").order("created_at",desc=True).execute().data or []
    cards=_card_map(db,[r.get("card_id") for r in offer_rows if r.get("card_id")]); owner_ids=[r.get("owner_id") for r in offer_rows if r.get("owner_id")]; owners={}
    if owner_ids: owners={p["user_id"]:p for p in db.table("profiles").select("user_id,email,username").in_("user_id",list(set(owner_ids))).execute().data or []}
    offers=[{**r,"card_name":cards.get(r.get("card_id"),{}).get("name","Unknown card"),"owner_email":owners.get(r.get("owner_id"),{}).get("email","Unknown user")} for r in offer_rows]
    return render_template_string(NOTIFICATIONS_HTML,friend_requests=friend_requests,offers=offers)

@app.route("/notifications/friend/<int:friendship_id>/accept",methods=["POST"])
def notification_accept_friend(friendship_id):
    _sb().rpc("respond_to_friend_request",{"p_friendship_id":friendship_id,"p_accept":True}).execute(); return redirect("/notifications")
@app.route("/notifications/friend/<int:friendship_id>/decline",methods=["POST"])
def notification_decline_friend(friendship_id):
    _sb().rpc("respond_to_friend_request",{"p_friendship_id":friendship_id,"p_accept":False}).execute(); return redirect("/notifications")
@app.route("/notifications/offer/<int:transaction_id>/accept",methods=["POST"])
def notification_accept_offer(transaction_id):
    _sb().rpc("respond_to_card_offer",{"p_transaction_id":transaction_id,"p_accept":True}).execute(); return redirect("/notifications")
@app.route("/notifications/offer/<int:transaction_id>/decline",methods=["POST"])
def notification_decline_offer(transaction_id):
    _sb().rpc("respond_to_card_offer",{"p_transaction_id":transaction_id,"p_accept":False}).execute(); return redirect("/notifications")

COMMUNITY_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Community</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email","User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>

<div class="community-header">
<h1>Community</h1>
<p>Add friends, then loan or sell cards directly to them.</p>
</div>

{% if message %}<div class="alert">{{ message }}</div>{% endif %}

<div class="community-friends-layout">
<section class="community-card add-friend-card">
<h2>Add a friend</h2>
<form method="post" action="/community/add-friend">
<label>Friend's email</label>
<input type="email" name="email" placeholder="friend@example.com" required>
<button type="submit">Send friend request</button>
</form>
<p class="hint">Your friend must already have an account. They can accept the request from Notifications.</p>
</section>

<section class="community-card friends-wide">
<h2>Your friends</h2>
{% if friends %}
{% for f in friends %}
<div class="friend-action-row">
<div class="friend-identity">
<strong>@{{ f.username or "user" }}</strong>
<div class="muted">{{ f.email }}</div>
</div>
<div class="friend-card-actions">
<a class="button-link secondary" href="/community/trade/{{ f.user_id }}/loan">Loan</a>
<a class="button-link primary" href="/community/trade/{{ f.user_id }}/sale">Sell</a>
</div>
</div>
{% endfor %}
{% else %}
<p class="empty">You haven't added any friends yet.</p>
{% endif %}
</section>
</div>
</body>
</html>
"""

def _community_tables_ready(db):
    """Return True when the community migration has been run."""
    try:
        db.table("profiles").select("user_id").limit(1).execute()
        db.table("friendships").select("id").limit(1).execute()
        db.table("card_transactions").select("id").limit(1).execute()
        return True
    except Exception:
        return False

@app.route("/community")
def community():
    db = _sb()
    uid = _uid()
    if not _community_tables_ready(db):
        return render_template_string(
            COMMUNITY_HTML, friends=[],
            message="Community database tables are not installed yet. Run the community SQL migration in Supabase first."
        )

    friendship_rows = (
        db.table("friendships").select("*")
        .or_(f"user_a.eq.{uid},user_b.eq.{uid}").eq("status", "accepted")
        .execute()
    ).data or []

    friend_ids = []
    for row in friendship_rows:
        other = row["user_b"] if row["user_a"] == uid else row["user_a"]
        friend_ids.append(other)

    profiles = {}
    if friend_ids:
        profiles = {
            p["user_id"]: p
            for p in db.table("profiles").select("user_id,email,username").in_("user_id", list(set(friend_ids))).execute().data or []
        }

    friends = [
        {"user_id": fid, "email": profiles.get(fid, {}).get("email", "Unknown user"), "username": profiles.get(fid, {}).get("username")}
        for fid in friend_ids
    ]
    friends.sort(key=lambda x: x["email"].lower())

    return render_template_string(COMMUNITY_HTML, friends=friends, message=None)


@app.route("/community/add-friend", methods=["POST"])
def community_add_friend():
    db = _sb(); uid = _uid()
    email = (request.form.get("email") or "").strip().lower()
    if not email: return redirect("/community")
    rows = db.table("profiles").select("user_id,email,username").eq("email", email).limit(1).execute().data or []
    if not rows or rows[0]["user_id"] == uid: return redirect("/community")
    other = rows[0]["user_id"]; a, b = sorted([uid, other])
    existing = db.table("friendships").select("id,status").eq("user_a",a).eq("user_b",b).limit(1).execute().data or []
    if existing: return redirect("/community")
    db.table("friendships").insert({"user_a":a,"user_b":b,"requested_by":uid,"status":"pending"}).execute()
    return redirect("/community")



COMMUNITY_TRADE_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ transaction_type|title }} Cards</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a>
<a href="/tracker">Card Tracker</a>
<a href="/community">Community</a>
<details class="profile-menu">
<summary>Profile ▾{% if notification_count %} <span class="notification-dot">{{ notification_count }}</span>{% endif %}</summary>
<div class="profile-dropdown">
<div class="muted">Signed in as</div>
<div class="profile-username">@{{ current_username or "user" }}</div>
<div class="profile-email">{{ session.get("email","User") }}</div>
<a href="/notifications">Notifications{% if notification_count %} <span class="notification-badge">{{ notification_count }}</span>{% endif %}</a>
<a href="/profile">Profile</a>
<a href="/pending-offers">Pending Loans / Sales{% if pending_offer_count %} <span class="notification-badge">{{ pending_offer_count }}</span>{% endif %}</a>
<a href="/settings">Settings</a>
<a class="logout-link" href="/logout">Log out</a>
</div>
</details>
</div>

<div class="trade-page-header">
<div>
<a href="/community" class="back-link">&larr; Community</a>
<h1>{{ transaction_type|title }} cards to {{ friend.email }}</h1>
<p class="hint">Choose cards from your collection on the left. Your {{ transaction_type }} cart is on the right.</p>
</div>
</div>

<form method="post" action="/community/trade/{{ friend.user_id }}/{{ transaction_type }}/send" id="trade-form">
<div class="trade-split">
<section class="trade-collection">
<div class="trade-pane-heading">
<h2>Your Collection</h2>
<input type="search" id="trade-search" placeholder="Search cards...">
</div>

{% if items %}
<div class="trade-card-grid" id="trade-card-grid">
{% for item in items %}
<div class="trade-card" data-name="{{ item.card_name|lower }}">
{% if item.image_url %}
<img src="{{ item.image_url }}" alt="{{ item.card_name }}">
{% else %}
<div class="no-image">No image</div>
{% endif %}
<div class="trade-card-body">
<strong>{{ item.card_name }}</strong>
<div class="muted">{{ item.quantity }} available{% if item.container_name %} · {{ item.container_name }}{% endif %}</div>
<button type="button" class="secondary add-to-trade"
        data-id="{{ item.id }}"
        data-name="{{ item.card_name }}"
        data-image="{{ item.image_url or '' }}"
        data-max="{{ item.quantity }}" data-selected="{% if selected_item_id == item.id %}1{% else %}0{% endif %}">+ Add</button>
</div>
</div>
{% endfor %}
</div>
{% else %}
<p class="empty">No available cards in your collection.</p>
{% endif %}
</section>

<aside class="trade-cart">
<div class="trade-pane-heading">
<h2>{{ transaction_type|title }} Cart</h2>
<span class="pill" id="cart-count">0 cards</span>
</div>
<div id="trade-cart-items">
<p class="empty" id="empty-cart">Choose cards from your collection.</p>
</div>

{% if transaction_type == "sale" %}
<label class="trade-price-label">Total sale price
<input type="number" name="price" min="0" step="0.01" placeholder="0.00">
</label>
{% endif %}

<div id="trade-hidden-inputs"></div>
<button type="submit" class="primary trade-send-button" id="send-trade" disabled>
Send {{ transaction_type|title }} Offer
</button>
</aside>
</div>
</form>

<script>
const cart = new Map();
const cartBox = document.getElementById('trade-cart-items');
const hiddenBox = document.getElementById('trade-hidden-inputs');
const countBadge = document.getElementById('cart-count');
const sendButton = document.getElementById('send-trade');

function renderCart() {
    cartBox.innerHTML = '';
    hiddenBox.innerHTML = '';
    let total = 0;

    if (cart.size === 0) {
        cartBox.innerHTML = '<p class="empty">Choose cards from your collection.</p>';
    }

    cart.forEach((item, id) => {
        total += item.qty;
        const row = document.createElement('div');
        row.className = 'trade-cart-row';
        row.innerHTML = `
            ${item.image ? `<img src="${item.image}" alt="">` : ''}
            <div class="trade-cart-info">
                <strong>${item.name}</strong>
                <div class="cart-qty-controls">
                    <button type="button" data-action="minus" data-id="${id}">−</button>
                    <span>${item.qty}</span>
                    <button type="button" data-action="plus" data-id="${id}">+</button>
                    <button type="button" class="cart-remove" data-action="remove" data-id="${id}">Remove</button>
                </div>
            </div>`;
        cartBox.appendChild(row);

        const idInput = document.createElement('input');
        idInput.type = 'hidden';
        idInput.name = 'item_id';
        idInput.value = id;
        hiddenBox.appendChild(idInput);

        const qtyInput = document.createElement('input');
        qtyInput.type = 'hidden';
        qtyInput.name = 'quantity';
        qtyInput.value = item.qty;
        hiddenBox.appendChild(qtyInput);
    });

    countBadge.textContent = total + (total === 1 ? ' card' : ' cards');
    sendButton.disabled = cart.size === 0;
}

document.querySelectorAll('.add-to-trade').forEach(button => {
    button.addEventListener('click', () => {
        const id = button.dataset.id;
        if (!cart.has(id)) {
            cart.set(id, {
                name: button.dataset.name,
                image: button.dataset.image,
                max: Number(button.dataset.max),
                qty: 1
            });
        } else {
            const item = cart.get(id);
            if (item.qty < item.max) item.qty++;
        }
        renderCart();
    });
});

document.querySelectorAll('.add-to-trade[data-selected="1"]').forEach(button => {
    const id = button.dataset.id;
    if (!cart.has(id)) {
        cart.set(id, {
            name: button.dataset.name,
            image: button.dataset.image,
            max: Number(button.dataset.max),
            qty: 1
        });
    }
});
renderCart();

cartBox.addEventListener('click', event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const id = button.dataset.id;
    const item = cart.get(id);
    if (!item) return;

    if (button.dataset.action === 'plus' && item.qty < item.max) item.qty++;
    if (button.dataset.action === 'minus') {
        item.qty--;
        if (item.qty <= 0) cart.delete(id);
    }
    if (button.dataset.action === 'remove') cart.delete(id);
    renderCart();
});

document.getElementById('trade-search').addEventListener('input', function() {
    const q = this.value.trim().toLowerCase();
    document.querySelectorAll('.trade-card').forEach(card => {
        card.style.display = card.dataset.name.includes(q) ? '' : 'none';
    });
});
</script>
</body>
</html>
"""


def _accepted_friend(db, uid, friend_id):
    a, b = sorted([uid, friend_id])
    rows = (
        db.table("friendships").select("id")
        .eq("user_a", a).eq("user_b", b).eq("status", "accepted")
        .limit(1).execute()
    ).data or []
    return bool(rows)



TRADE_PICKER_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Choose Friend</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="nav-bar">
<a href="/">Collection</a><a href="/tracker">Card Tracker</a><a href="/community">Community</a>
</div>
<a href="/tracker" class="back-link">&larr; Card Tracker</a>
<h1>Who do you want to {{ transaction_type }} this card to?</h1>
<p class="hint">{{ card_name }}</p>
<div class="community-card">
{% for friend in friends %}
<div class="friend-action-row">
<div><strong>@{{ friend.username or "user" }}</strong><div class="muted">{{ friend.email }}</div></div>
<a class="button-link primary" href="/community/trade/{{ friend.user_id }}/{{ transaction_type }}?item={{ item_id }}">Choose</a>
</div>
{% else %}
<p class="empty">Add a friend in Community first.</p>
{% endfor %}
</div>
</body>
</html>
"""


@app.route("/community/trade-picker/<int:item_id>/<transaction_type>")
def community_trade_picker(item_id, transaction_type):
    db = _sb()
    uid = _uid()
    if transaction_type not in ("loan", "sale"):
        return redirect("/tracker")
    item = _get_item(db, item_id)
    if not item or item.get("loan_transaction_id"):
        return redirect("/tracker")
    card = _card_map(db, [item["card_id"]]).get(item["card_id"], {})

    friendship_rows = (
        db.table("friendships").select("*")
        .or_(f"user_a.eq.{uid},user_b.eq.{uid}").eq("status", "accepted").execute()
    ).data or []
    friend_ids = [r["user_b"] if r["user_a"] == uid else r["user_a"] for r in friendship_rows]
    profiles = {}
    if friend_ids:
        profiles = {
            p["user_id"]: p
            for p in db.table("profiles").select("user_id,email,username").in_("user_id", friend_ids).execute().data or []
        }
    friends = [{"user_id": f, "email": profiles.get(f, {}).get("email", "Unknown user"), "username": profiles.get(f, {}).get("username")} for f in friend_ids]
    return render_template_string(
        TRADE_PICKER_HTML, friends=friends, transaction_type=transaction_type,
        item_id=item_id, card_name=card.get("name", "Card")
    )


@app.route("/community/trade/<friend_id>/<transaction_type>")
def community_trade(friend_id, transaction_type):
    db = _sb()
    uid = _uid()
    transaction_type = transaction_type.lower()
    if transaction_type not in ("loan", "sale") or not _accepted_friend(db, uid, friend_id):
        return redirect("/community")

    profile_rows = (
        db.table("profiles").select("user_id,email,username")
        .eq("user_id", friend_id).limit(1).execute()
    ).data or []
    if not profile_rows:
        return redirect("/community")
    friend = profile_rows[0]

    item_rows = (
        db.table("collection_items").select("*")
        .eq("user_id", uid).eq("is_missing", False)
        .gt("quantity", 0).execute()
    ).data or []

    cards = _card_map(db, [r.get("card_id") for r in item_rows])
    containers = _container_map(db)
    items = []
    for row in item_rows:
        card = cards.get(row.get("card_id"), {})
        container = containers.get(row.get("container_id")) if row.get("container_id") else None
        items.append({
            "id": row["id"],
            "quantity": row["quantity"],
            "card_name": card.get("name", "Unknown card"),
            "image_url": card.get("image_url"),
            "container_name": container.get("name") if container else "Unsorted",
        })
    items.sort(key=lambda x: x["card_name"].lower())

    return render_template_string(
        COMMUNITY_TRADE_HTML,
        friend=friend,
        items=items,
        transaction_type=transaction_type,
        selected_item_id=request.args.get("item", type=int),
    )


@app.route("/community/trade/<friend_id>/<transaction_type>/send", methods=["POST"])
def community_trade_send(friend_id, transaction_type):
    db = _sb()
    uid = _uid()
    transaction_type = transaction_type.lower()
    if transaction_type not in ("loan", "sale") or not _accepted_friend(db, uid, friend_id):
        return redirect("/community")

    item_ids = request.form.getlist("item_id")
    quantities = request.form.getlist("quantity")
    if not item_ids or len(item_ids) != len(quantities):
        return redirect(f"/community/trade/{friend_id}/{transaction_type}")

    price_raw = (request.form.get("price") or "").strip()
    total_price = float(price_raw) if price_raw else None

    # Each selected card becomes its own pending offer so the existing
    # notification accept/decline system continues to work.
    for index, (item_id_raw, qty_raw) in enumerate(zip(item_ids, quantities)):
        try:
            item_id = int(item_id_raw)
            qty = max(1, int(qty_raw))
        except ValueError:
            continue

        item = _get_item(db, item_id)
        if not item or int(item.get("quantity") or 0) < qty:
            continue

        card_price = None
        if transaction_type == "sale" and total_price is not None:
            # Store the total price on the first card; the notification still
            # represents the grouped cart as individual card offers.
            card_price = total_price if index == 0 else 0

        db.table("card_transactions").insert({
            "owner_id": uid,
            "friend_id": friend_id,
            "card_id": item["card_id"],
            "source_item_id": item_id,
            "transaction_type": transaction_type,
            "quantity": qty,
            "price": card_price,
            "status": "pending",
        }).execute()

    return redirect("/community")


@app.route("/community/transaction", methods=["POST"])
def community_transaction():
    db = _sb(); uid = _uid()
    item_id=int(request.form["item_id"]); friend_id=request.form["friend_id"]
    tx_type=request.form.get("transaction_type","loan"); qty=max(1,int(request.form.get("quantity",1)))
    price_raw=(request.form.get("price") or "").strip(); price=float(price_raw) if price_raw else None
    item=_get_item(db,item_id)
    if not item or int(item.get("quantity") or 0) < qty: return redirect("/community")
    a,b=sorted([uid,friend_id])
    friendship=db.table("friendships").select("id").eq("user_a",a).eq("user_b",b).eq("status","accepted").limit(1).execute().data or []
    if not friendship: return redirect("/community")
    db.table("card_transactions").insert({"owner_id":uid,"friend_id":friend_id,"card_id":item["card_id"],"source_item_id":item_id,"transaction_type":tx_type,"quantity":qty,"price":price if tx_type=="sale" else None,"status":"pending"}).execute()
    return redirect("/community")


@app.route("/community/return/<int:transaction_id>", methods=["POST"])
def community_return(transaction_id):
    _sb().rpc("return_loaned_card", {"p_transaction_id": transaction_id}).execute()
    return redirect("/tracker")


@app.route("/community/return-borrowed/<int:transaction_id>", methods=["POST"])
def community_return_borrowed(transaction_id):
    _sb().rpc("return_loaned_card", {"p_transaction_id": transaction_id}).execute()
    return redirect("/tracker")



PROFILE_HTML = """
<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Profile</title><link rel="stylesheet" href="/static/style.css"></head>
<body>
<div class="nav-bar"><a href="/">Collection</a><a href="/tracker">Card Tracker</a><a href="/community">Community</a></div>
<h1>Profile</h1>
<section class="panel profile-page-card">
<form method="post" action="/profile">
<label>Username
<input type="text" name="username" minlength="3" maxlength="24" value="{{ username or '' }}" placeholder="Choose a username" required>
</label>
<p class="hint">3–24 characters. Letters, numbers and underscores only.</p>
<button type="submit" class="primary">Save Username</button>
</form>
{% if message %}<div class="alert {{ 'success' if success else 'error' }}">{{ message }}</div>{% endif %}
</section>

<section class="panel danger-zone">
<h2>Delete Account</h2>
<p class="hint">This permanently deletes your account and app data. This cannot be undone.</p>
<form method="post" action="/profile/delete" onsubmit="return confirm('Permanently delete your account? This cannot be undone.');">
<input type="text" name="confirm" placeholder="Type DELETE to confirm" required>
<button type="submit" class="danger">Delete Account</button>
</form>
</section>
</body>
</html>
"""

PENDING_OFFERS_HTML = """
<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Pending Loans / Sales</title><link rel="stylesheet" href="/static/style.css"></head>
<body>
<div class="nav-bar"><a href="/">Collection</a><a href="/tracker">Card Tracker</a><a href="/community">Community</a></div>
<a href="/profile" class="back-link">&larr; Profile</a>
<h1>Pending Loans / Sales</h1>
<p class="hint">Offers you sent that have not been accepted or declined yet.</p>
<section class="panel">
{% for offer in offers %}
<div class="pending-offer-row">
<div>
<strong>{{ offer.card_name }}</strong>
<div class="muted">{{ offer.transaction_type|title }} · {{ offer.quantity }}x → @{{ offer.friend_username or offer.friend_email }}</div>
{% if offer.transaction_type == 'sale' and offer.price is not none %}
<div class="muted">Price: ₱{{ '%.2f'|format(offer.price) }}</div>
{% endif %}
</div>
<form method="post" action="/pending-offers/{{ offer.id }}/delete"
      onsubmit="return confirm('Delete this pending offer?');">
<button type="submit" class="danger">Delete</button>
</form>
</div>
{% else %}
<p class="empty">You have no pending loan or sale offers.</p>
{% endfor %}
</section>
</body>
</html>
"""


@app.route("/profile", methods=["GET", "POST"])
def profile_page():
    db = _sb()
    uid = _uid()
    message = None
    success = False

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,24}", username):
            message = "Username must be 3–24 characters using only letters, numbers, or underscores."
        else:
            try:
                db.table("profiles").update({"username": username}).eq("user_id", uid).execute()
                message = "Username saved."
                success = True
            except Exception:
                message = "That username is already taken."

    rows = db.table("profiles").select("username").eq("user_id", uid).limit(1).execute().data or []
    username = rows[0].get("username") if rows else None
    return render_template_string(PROFILE_HTML, username=username, message=message, success=success)


@app.route("/pending-offers")
def pending_offers_page():
    db = _sb()
    uid = _uid()
    rows = (
        db.table("card_transactions").select("*")
        .eq("owner_id", uid).eq("status", "pending")
        .order("created_at", desc=True).execute()
    ).data or []
    cards = _card_map(db, [r.get("card_id") for r in rows])
    friend_ids = list({r.get("friend_id") for r in rows if r.get("friend_id")})
    profiles = {}
    if friend_ids:
        profiles = {
            p["user_id"]: p
            for p in db.table("profiles").select("user_id,email,username").in_("user_id", friend_ids).execute().data or []
        }
    offers = []
    for row in rows:
        friend = profiles.get(row.get("friend_id"), {})
        offers.append({
            **row,
            "card_name": cards.get(row.get("card_id"), {}).get("name", "Unknown card"),
            "friend_email": friend.get("email", "another user"),
            "friend_username": friend.get("username"),
        })
    return render_template_string(PENDING_OFFERS_HTML, offers=offers)


@app.route("/pending-offers/<int:transaction_id>/delete", methods=["POST"])
def delete_pending_offer(transaction_id):
    db = _sb()
    uid = _uid()
    db.table("card_transactions").delete().eq("id", transaction_id).eq("owner_id", uid).eq("status", "pending").execute()
    return redirect("/pending-offers")


@app.route("/profile/delete", methods=["POST"])
def delete_profile_account():
    if (request.form.get("confirm") or "").strip() != "DELETE":
        return redirect("/profile")
    # SECURITY DEFINER RPC deletes auth.users row and cascading app data.
    _sb().rpc("delete_my_account").execute()
    session.clear()
    return redirect("/login")


LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MTG Collection - Login</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="auth-page">
<div class="auth-shell">
<div class="auth-brand">
<div class="auth-mark">MTG</div>
<h1>MTG Collection Tracker</h1>
<p>Your cards, decks, binders, and boxes in one place.</p>
</div>
<div class="auth-card">
<h2>Welcome back</h2>
{% if error %}<div class="alert error">{{ error }}</div>{% endif %}
<form method="POST">
<label for="email">Email</label>
<input id="email" type="email" name="email" placeholder="you@example.com" autocomplete="email" required>
<label for="password">Password</label>
<input id="password" type="password" name="password" placeholder="Enter your password" autocomplete="current-password" required>
<button type="submit">Log in</button>
</form>
<p class="auth-footer">Don't have an account? <a href="/signup">Create account</a></p>
</div>
</div>
</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        try:
            response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })

            session["access_token"] = response.session.access_token
            session["refresh_token"] = response.session.refresh_token
            session["user_id"] = response.user.id
            session["email"] = response.user.email

            return redirect("/")

        except Exception as e:
            return render_template_string(
                LOGIN_HTML,
                error=str(e)
            )

    return render_template_string(
        LOGIN_HTML,
        error=None
    )

SIGNUP_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MTG Collection - Sign Up</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="auth-page">
<div class="auth-shell">
<div class="auth-brand">
<div class="auth-mark">MTG</div>
<h1>Build your collection</h1>
<p>Create an account to start tracking your cards.</p>
</div>
<div class="auth-card">
<h2>Create account</h2>
{% if error %}<div class="alert error">{{ error }}</div>{% endif %}
{% if message %}<div class="alert success">{{ message }}</div>{% endif %}
<form method="POST">
<label for="email">Email</label>
<input id="email" type="email" name="email" placeholder="you@example.com" autocomplete="email" required>
<label for="password">Password</label>
<input id="password" type="password" name="password" minlength="6" placeholder="At least 6 characters" autocomplete="new-password" required>
<button type="submit">Create account</button>
</form>
<p class="auth-footer">Already have an account? <a href="/login">Log in</a></p>
</div>
</div>
</body>
</html>
"""

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        try:
            response = supabase.auth.sign_up({
                "email": email,
                "password": password,
            })

            if response.session:
                session["access_token"] = response.session.access_token
                session["refresh_token"] = response.session.refresh_token
                session["user_id"] = response.user.id
                session["email"] = response.user.email

                return redirect("/")

            return render_template_string(
                SIGNUP_HTML,
                error=None,
                message="Account created. Check your email to confirm your account, then log in."
            )

        except Exception as e:

            return render_template_string(
                SIGNUP_HTML,
                error=str(e),
                message=None
            )

    return render_template_string(
        SIGNUP_HTML,
        error=None,
        message=None
    )

@app.route("/logout")
def logout():

    try:
        supabase.auth.sign_out()
    except Exception:
        pass

    session.clear()

    return redirect("/login")

def get_user_supabase():
    if "access_token" not in session:
        return None

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    client.auth.set_session(
        session["access_token"],
        session["refresh_token"]
    )

    return client

if __name__ == "__main__":
    app.run(debug=True)
