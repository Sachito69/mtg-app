from flask import Blueprint
from app_core import *
from services.auth_service import require_db as _sb, current_user_id as _uid
from services.collection_service import (
    card_map as _card_map,
    container_map as _container_map_service,
    get_container as _get_container_service,
    get_item as _get_item_service,
)

collection_bp = Blueprint("collection", __name__)

def _container_map(db):
    return _container_map_service(db, _uid())

def _get_container(db, container_id):
    return _get_container_service(db, _uid(), container_id)

def _get_item(db, item_id):
    return _get_item_service(db, _uid(), item_id)


@collection_bp.route("/edit/<int:item_id>", methods=["GET", "POST"])
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

@collection_bp.route("/delete/<int:item_id>", methods=["POST"])
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

@collection_bp.route("/item/<int:item_id>/increment", methods=["POST"])
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

@collection_bp.route("/item/<int:item_id>/decrement", methods=["POST"])
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

@collection_bp.route("/card-suggestions")
def card_suggestions():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    try:
        names = autocomplete_card_name(query)
    except Exception:
        names = []
    return jsonify(names)

@collection_bp.route("/add", methods=["GET", "POST"])
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

@collection_bp.route("/containers/<int:container_id>/delete", methods=["POST"])
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

@collection_bp.route("/containers/<int:container_id>/duplicate", methods=["POST"])
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

@collection_bp.route("/containers/<int:container_id>")
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

@collection_bp.route("/add/confirm", methods=["POST"])
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

@collection_bp.route("/add/confirm/move", methods=["POST"])
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

@collection_bp.route("/add/confirm/missing", methods=["POST"])
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

@collection_bp.route("/bulk-add")
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

@collection_bp.route("/bulk-add/line", methods=["POST"])
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

@collection_bp.route("/edit/<int:item_id>/version")
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

@collection_bp.route("/edit/<int:item_id>/version/confirm", methods=["POST"])
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

@collection_bp.route("/containers/<int:container_id>/bulk-edit/apply", methods=["POST"])
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
