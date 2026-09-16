from flask import Blueprint
from app_core import *
from services.auth_service import require_db as _sb, current_user_id as _uid
from services.collection_service import card_map as _card_map
from services.community_service import community_tables_ready as _community_tables_ready, accepted_friend as _accepted_friend

community_bp = Blueprint("community", __name__)

@community_bp.route("/notifications")
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

@community_bp.route("/notifications/friend/<int:friendship_id>/accept",methods=["POST"])
def notification_accept_friend(friendship_id):
    _sb().rpc("respond_to_friend_request",{"p_friendship_id":friendship_id,"p_accept":True}).execute(); return redirect("/notifications")

@community_bp.route("/notifications/friend/<int:friendship_id>/decline",methods=["POST"])
def notification_decline_friend(friendship_id):
    _sb().rpc("respond_to_friend_request",{"p_friendship_id":friendship_id,"p_accept":False}).execute(); return redirect("/notifications")

@community_bp.route("/notifications/offer/<int:transaction_id>/accept",methods=["POST"])
def notification_accept_offer(transaction_id):
    _sb().rpc("respond_to_card_offer",{"p_transaction_id":transaction_id,"p_accept":True}).execute(); return redirect("/notifications")

@community_bp.route("/notifications/offer/<int:transaction_id>/decline",methods=["POST"])
def notification_decline_offer(transaction_id):
    _sb().rpc("respond_to_card_offer",{"p_transaction_id":transaction_id,"p_accept":False}).execute(); return redirect("/notifications")

@community_bp.route("/community")
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

@community_bp.route("/community/add-friend", methods=["POST"])
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

@community_bp.route("/community/trade-picker/<int:item_id>/<transaction_type>")
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

@community_bp.route("/community/trade/<friend_id>/<transaction_type>")
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

@community_bp.route("/community/trade/<friend_id>/<transaction_type>/send", methods=["POST"])
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

@community_bp.route("/community/transaction", methods=["POST"])
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

@community_bp.route("/community/return/<int:transaction_id>", methods=["POST"])
def community_return(transaction_id):
    _sb().rpc("return_loaned_card", {"p_transaction_id": transaction_id}).execute()
    return redirect("/tracker")

@community_bp.route("/community/return-borrowed/<int:transaction_id>", methods=["POST"])
def community_return_borrowed(transaction_id):
    _sb().rpc("return_loaned_card", {"p_transaction_id": transaction_id}).execute()
    return redirect("/tracker")

@community_bp.route("/profile", methods=["GET", "POST"])
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

@community_bp.route("/pending-offers")
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

@community_bp.route("/pending-offers/<int:transaction_id>/delete", methods=["POST"])
def delete_pending_offer(transaction_id):
    db = _sb()
    uid = _uid()
    db.table("card_transactions").delete().eq("id", transaction_id).eq("owner_id", uid).eq("status", "pending").execute()
    return redirect("/pending-offers")

@community_bp.route("/profile/delete", methods=["POST"])
def delete_profile_account():
    if (request.form.get("confirm") or "").strip() != "DELETE":
        return redirect("/profile")
    # SECURITY DEFINER RPC deletes auth.users row and cascading app data.
    _sb().rpc("delete_my_account").execute()
    session.clear()
    return redirect("/login")
