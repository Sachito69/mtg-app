from flask import Blueprint
from app_core import *
from services.auth_service import require_db as _sb, current_user_id as _uid
from services.collection_service import card_map as _card_map

tracker_bp = Blueprint("tracker", __name__)

@tracker_bp.route("/tracker")
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
