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
    render_template,
    request,
    redirect,
    jsonify,
    session,
    url_for,
)
# Templates were moved to /templates so app.py only contains Python logic.
# Keep CSS in /static/style.css. Existing add_card.py and deck_logic.py stay unchanged.
import re
import os

from add_card import search_all_printings, fetch_card_by_id, fetch_card_by_name, fetch_card_by_set_number, parse_bulk_line, save_card, save_to_collection, autocomplete_card_name
from deck_logic import find_real_sources, total_real_available, move_real_into_deck, find_decks_missing_card, fill_missing_in_deck, check_deck_legality, FORMAT_RULES
from dotenv import load_dotenv
from supabase import create_client
from supabase_auth.errors import AuthApiError

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
    """Put every deck card into exactly one simple card-type group."""
    groups = {}

    # Priority intentionally handles mixed types:
    # Artifact Creature -> Creature
    # Legendary Creature -> Creature
    # Artifact Land -> Land
    priority = (
        "Creature",
        "Land",
        "Planeswalker",
        "Instant",
        "Sorcery",
        "Artifact",
        "Enchantment",
        "Battle",
    )

    for card in cards:
        type_line = card.get("type_line") or ""
        primary_type = next((card_type for card_type in priority if card_type in type_line), "Other")
        groups.setdefault(primary_type, []).append(card)

    order = list(priority)

    def sort_key(type_name):
        return (order.index(type_name), "") if type_name in order else (len(order), type_name)

    ordered_names = sorted(groups.keys(), key=sort_key)
    return [
        {
            "type_name": name,
            "cards": groups[name],
            "count": sum(card.get("quantity", 0) for card in groups[name]),
        }
        for name in ordered_names
    ]


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

@app.errorhandler(RuntimeError)
def handle_runtime_error(error):
    if str(error) == "AUTH_REQUIRED":
        session.clear()
        return redirect("/login")
    raise error



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

    # Active outgoing loans are rendered as separate tracker tiles.
    sent_loans = (
        db.table("card_transactions")
        .select("id,card_id,friend_id,quantity,loan_condition,loan_foil")
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
            "lent_to": [],
        })

    # Add one separate tile per active outgoing loan. These are not
    # collection_items, so they cannot be edited, sold, loaned again, or placed
    # in a deck while they are physically with another user.
    lent_cards = _card_map(db, [loan.get("card_id") for loan in sent_loans])
    for loan in sent_loans:
        card = lent_cards.get(loan.get("card_id"))
        if not card:
            continue

        name = card.get("name") or ""
        type_line = card.get("type_line") or ""
        colors = card.get("colors") or []
        cmc = card.get("cmc")

        if search_query and search_query.lower() not in name.lower():
            continue
        if color_filters:
            matches = any(
                (f == "C" and not colors)
                or (f == "M" and len(colors) > 1)
                or (f in ("W","U","B","R","G") and f in colors)
                for f in color_filters
            )
            if not matches:
                continue
        if type_filter != "all" and type_filter not in type_line:
            continue
        if cmc_filter != "all" and (cmc is None or float(cmc) != int(cmc_filter)):
            continue

        borrower = borrower_profiles.get(loan.get("friend_id"), {})
        rows.append({
            "id": None,
            "name": name,
            "set_name": card.get("set_name"),
            "type_line": type_line,
            "image_url": card.get("image_url"),
            "colors": colors,
            "cmc": cmc,
            "quantity": loan.get("quantity") or 1,
            "condition": loan.get("loan_condition") or "NM",
            "foil": bool(loan.get("loan_foil")),
            "location_name": None,
            "location_kind": None,
            "loaned_from_user_id": None,
            "loaned_from_email": None,
            "loan_transaction_id": None,
            "is_lent_out": True,
            "lent_transaction_id": loan.get("id"),
            "lent_to": [{
                "transaction_id": loan.get("id"),
                "quantity": loan.get("quantity") or 1,
                "username": borrower.get("username"),
                "email": borrower.get("email", "another user"),
            }],
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

    return render_template("tracker.html",
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
    return render_template("edit_item.html", item=item, containers=container_result.data or []
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
        return render_template("search.html", error=None, container_id=request.args.get("container_id"))

    card_name = request.form["card_name"]
    container_id = request.form.get("container_id") or None
    force_picker = request.form.get("force_picker") == "1"

    db = _sb()
    auto_pick = get_setting(db, "auto_pick_version", "true") == "true"

    if auto_pick and not force_picker:
        try:
            card = fetch_card_by_name(card_name)
        except Exception:
            return render_template("search.html",
                error=f'Could not find a card named "{card_name}". Check the spelling and try again.',
                container_id=container_id,
            )
        return render_template("quick_add.html", card=card, card_name=card_name, container_id=container_id)

    try:
        printings = search_all_printings(card_name)
    except Exception:
        return render_template("search.html",
            error=f'Could not find a card named "{card_name}". Check the spelling and try again.',
            container_id=container_id,
        )

    if not printings:
        return render_template("search.html",
            error=f'Could not find a card named "{card_name}". Check the spelling and try again.',
            container_id=container_id,
        )

    return render_template("printings.html", card_name=card_name, printings=printings, container_id=container_id
    )





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
        .select("container_id,quantity")
        .eq("user_id", uid)
        .execute()
    )
    counts = {}
    for item in item_result.data or []:
        cid = item.get("container_id")
        if cid is not None:
            counts[cid] = counts.get(cid, 0) + (item.get("quantity") or 0)

    for container in containers:
        container["card_count"] = counts.get(container["id"], 0)

    return render_template("collection.html",
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

        return render_template("deck_detail.html",
            container=container,
            grouped_cards=group_cards_by_type(cards),
            legality=legality,
            missing_text=missing_text,
            deck_view=get_setting(db, "preferred_deck_view", "stacks"),
        )

    cards.sort(key=lambda row: (row["name"] or "").lower())
    return render_template("container_detail.html", container=container, cards=cards
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
            return render_template("fill_missing.html",
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
    return render_template("move_or_missing.html",
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

    return render_template("loan_form.html", item=item, available=available
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
    return render_template("loans.html", loans=active)


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
    return render_template("bulk_add.html", containers=containers, preselect_container_id=preselect_container_id
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
    return render_template("version_picker.html", item=item, printings=printings)


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


@app.route("/settings/deck-view", methods=["POST"])
def save_deck_view():
    db = _sb()
    data = request.get_json(silent=True) or {}
    mode = data.get("deck_view")
    if mode not in ("text", "stacks", "grid"):
        return jsonify({"ok": False, "error": "Invalid deck view"}), 400
    set_setting(db, "preferred_deck_view", mode)
    return jsonify({"ok": True})



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
        preferred_deck_view = request.form.get("preferred_deck_view", "stacks")
        if preferred_deck_view not in ("text", "stacks", "grid"):
            preferred_deck_view = "stacks"
        set_setting(db, "preferred_deck_view", preferred_deck_view)
        saved = True
    auto_pick_version = get_setting(db, "auto_pick_version", "true") == "true"
    preferred_deck_view = get_setting(db, "preferred_deck_view", "stacks")
    if preferred_deck_view not in ("text", "stacks", "grid"):
        preferred_deck_view = "stacks"
    return render_template("settings.html",
        auto_pick_version=auto_pick_version,
        preferred_deck_view=preferred_deck_view,
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
    return render_template("notifications.html",friend_requests=friend_requests,offers=offers)

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
        return render_template("community.html", friends=[],
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

    return render_template("community.html", friends=friends, message=None)


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





def _accepted_friend(db, uid, friend_id):
    a, b = sorted([uid, friend_id])
    rows = (
        db.table("friendships").select("id")
        .eq("user_a", a).eq("user_b", b).eq("status", "accepted")
        .limit(1).execute()
    ).data or []
    return bool(rows)





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
    return render_template("trade_picker.html", friends=friends, transaction_type=transaction_type,
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
        .is_("loaned_from_user_id", "null")
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

    return render_template("community_trade.html",
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
    return render_template("profile.html", username=username, message=message, success=success)


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
    return render_template("pending_offers.html", offers=offers)


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
            return render_template("login.html",
                error=str(e)
            )

    return render_template("login.html",
        error=None
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        try:
            response = supabase.auth.sign_up({
                "username": username,
                "email": email,
                "password": password,
            })

            if response.session:
                session["access_token"] = response.session.access_token
                session["refresh_token"] = response.session.refresh_token
                session["user_id"] = response.user.id
                session["email"] = response.user.email

                return redirect("/")

            return render_template("signup.html",
                error=None,
                message="Account created. Check your email to confirm your account, then log in."
            )

        except Exception as e:

            return render_template("signup.html",
                error=str(e),
                message=None
            )

    return render_template("signup.html",
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
    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")
    if not access_token or not refresh_token:
        return None

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    try:
        auth_response = client.auth.set_session(access_token, refresh_token)
        auth_session = getattr(auth_response, "session", None)

        # Supabase refresh tokens rotate. Always save the newest pair.
        if auth_session:
            if getattr(auth_session, "access_token", None):
                session["access_token"] = auth_session.access_token
            if getattr(auth_session, "refresh_token", None):
                session["refresh_token"] = auth_session.refresh_token
            user = getattr(auth_session, "user", None)
            if user:
                if getattr(user, "id", None):
                    session["user_id"] = user.id
                if getattr(user, "email", None):
                    session["email"] = user.email
        return client

    except AuthApiError:
        # Stale/revoked refresh token: log out cleanly instead of Render 500.
        session.clear()
        return None
    except Exception:
        session.clear()
        return None


if __name__ == "__main__":
    app.run(debug=True)
