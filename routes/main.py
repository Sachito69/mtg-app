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
