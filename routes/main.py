from flask import Blueprint
from app_core import *
from services.auth_service import require_db as _sb, current_user_id as _uid

main_bp = Blueprint("main", __name__)

@main_bp.route("/", methods=["GET", "POST"])
def containers_page():
    if "user_id" not in session:
        return redirect("/login")
    db = _sb()
    uid = _uid()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        kind = (request.form.get("kind") or "box").lower()
        format_ = request.form.get("format") or None
        folder_id = request.form.get("folder_id") or None
        if name and kind in ("deck", "binder", "box"):
            db.table("containers").insert({
                "user_id": uid,
                "name": name,
                "kind": kind,
                "format": format_ if kind == "deck" else None,
                "folder_id": int(folder_id) if folder_id else None,
            }).execute()
        return redirect("/")

    rows = db.table("containers").select("*").eq("user_id", uid).order("name").execute().data or []
    items = db.table("collection_items").select("container_id,quantity,is_missing").eq("user_id", uid).execute().data or []
    folders = db.table("desktop_folders").select("*").eq("user_id", uid).order("name").execute().data or []

    counts = {}
    for item in items:
        cid = item.get("container_id")
        if cid is not None and not item.get("is_missing"):
            counts[cid] = counts.get(cid, 0) + (item.get("quantity") or 0)

    containers = []
    for row in rows:
        c = dict(row)
        c["card_count"] = counts.get(c["id"], 0)
        containers.append(c)

    return render_template(
        "collection_desktop.html",
        containers=containers,
        folders=folders,
        formats=list(FORMAT_RULES.keys()),
    )

@main_bp.route("/desktop/container/<int:container_id>")
def desktop_container(container_id):
    db = _sb()
    uid = _uid()
    container = get_container(db, uid, container_id)
    if not container:
        return jsonify({"ok": False, "error": "Container not found"}), 404
    rows = (db.table("collection_items").select("*").eq("user_id", uid)
            .eq("container_id", container_id).execute()).data or []
    cards = card_map(db, [r.get("card_id") for r in rows])
    out = []
    for r in rows:
        c = cards.get(r.get("card_id"), {})
        out.append({
            "item_id": r["id"], "card_id": r.get("card_id"),
            "name": c.get("name", "Unknown card"),
            "type_line": c.get("type_line") or "Card",
            "image_url": c.get("image_url"),
            "colors": c.get("colors") or [],
            "quantity": r.get("quantity") or 0,
            "condition": r.get("condition"),
            "foil": bool(r.get("foil")),
            "is_missing": bool(r.get("is_missing")),
            "loan_transaction_id": r.get("loan_transaction_id"),
        })
    return jsonify({"ok": True, "container": container, "cards": out})

@main_bp.route("/desktop/folder", methods=["POST"])
def desktop_create_folder():
    db = _sb()
    uid = _uid()
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Folder name is required."}), 400
    made = db.table("desktop_folders").insert({"user_id": uid, "name": name}).execute().data or []
    return jsonify({"ok": True, "folder": made[0] if made else None})

@main_bp.route("/desktop/folder/<int:folder_id>", methods=["GET"])
def desktop_folder(folder_id):
    db = _sb()
    uid = _uid()
    folder = (db.table("desktop_folders").select("*").eq("user_id", uid)
              .eq("id", folder_id).limit(1).execute()).data or []
    if not folder:
        return jsonify({"ok": False, "error": "Folder not found."}), 404
    rows = (db.table("containers").select("*").eq("user_id", uid)
            .eq("folder_id", folder_id).order("name").execute()).data or []
    items = db.table("collection_items").select("container_id,quantity,is_missing").eq("user_id", uid).execute().data or []
    counts = {}
    for item in items:
        cid = item.get("container_id")
        if cid is not None and not item.get("is_missing"):
            counts[cid] = counts.get(cid, 0) + (item.get("quantity") or 0)
    containers = []
    for row in rows:
        c = dict(row)
        c["card_count"] = counts.get(c["id"], 0)
        containers.append(c)
    return jsonify({"ok": True, "folder": folder[0], "containers": containers})

@main_bp.route("/desktop/folder/<int:folder_id>/delete", methods=["POST"])
def desktop_delete_folder(folder_id):
    db = _sb()
    uid = _uid()
    db.table("containers").update({"folder_id": None}).eq("user_id", uid).eq("folder_id", folder_id).execute()
    db.table("desktop_folders").delete().eq("user_id", uid).eq("id", folder_id).execute()
    return jsonify({"ok": True})

@main_bp.route("/desktop/container-folder", methods=["POST"])
def desktop_container_folder():
    db = _sb()
    uid = _uid()
    data = request.get_json(silent=True) or {}
    try:
        container_id = int(data.get("container_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid container."}), 400
    folder_id = data.get("folder_id")
    if folder_id in ("", None):
        folder_id = None
    else:
        try:
            folder_id = int(folder_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Invalid folder."}), 400

    container = get_container(db, uid, container_id)
    if not container:
        return jsonify({"ok": False, "error": "Container not found."}), 404
    if folder_id is not None:
        folder = (db.table("desktop_folders").select("id").eq("user_id", uid)
                  .eq("id", folder_id).limit(1).execute()).data or []
        if not folder:
            return jsonify({"ok": False, "error": "Folder not found."}), 404
    db.table("containers").update({"folder_id": folder_id}).eq("user_id", uid).eq("id", container_id).execute()
    return jsonify({"ok": True})

@main_bp.route("/desktop/move", methods=["POST"])
def desktop_move():
    db = _sb()
    uid = _uid()
    data = request.get_json(silent=True) or {}
    try:
        item_id = int(data.get("item_id"))
        target_id = int(data.get("target_container_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid card or container"}), 400

    item = get_item(db, uid, item_id)
    target = get_container(db, uid, target_id)
    if not item or not target:
        return jsonify({"ok": False, "error": "Card or container not found"}), 404
    if item.get("loan_transaction_id"):
        return jsonify({"ok": False, "error": "Borrowed cards cannot be moved between your containers."}), 400

    # For normal collection movement, the desktop is now the main interface.
    # Deck moves still use the deck manager so missing/legality sourcing is preserved.
    if target.get("kind") == "deck":
        return jsonify({"ok": False, "error": "Open the deck window and use Deck Manager to add/commit cards."}), 400

    db.table("collection_items").update({"container_id": target_id}).eq("user_id", uid).eq("id", item_id).execute()
    return jsonify({"ok": True})

@main_bp.route("/loan/<int:item_id>", methods=["GET", "POST"])
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

@main_bp.route("/loans")
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

@main_bp.route("/loans/<int:loan_id>/return", methods=["POST"])
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

@main_bp.route("/fill-missing/ajax", methods=["POST"])
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

@main_bp.route("/fill-missing", methods=["POST"])
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
