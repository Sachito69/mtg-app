from flask import Blueprint
from app_core import *
from services.auth_service import require_db as _sb, current_user_id as _uid
from services.collection_service import (
    card_map as _card_map,
    container_map as _container_map_service,
    get_item as _get_item_service,
)
from services.community_service import community_tables_ready as _community_tables_ready, accepted_friend as _accepted_friend

community_bp = Blueprint("community", __name__)

def _get_item(db, item_id):
    return _get_item_service(db, _uid(), item_id)

def _container_map(db):
    return _container_map_service(db, _uid())

def _profile_map(db, ids):
    ids = list({x for x in ids if x})
    if not ids:
        return {}
    rows = db.table("profiles").select("user_id,email,username").in_("user_id", ids).execute().data or []
    return {r["user_id"]: r for r in rows}

def _contact_map(db, uid, ids):
    ids = list({x for x in ids if x})
    if not ids:
        return {}
    rows = db.table("contacts").select("*").eq("user_id", uid).in_("id", ids).execute().data or []
    return {r["id"]: r for r in rows}

def _friends_of(db, user_id):
    rows = (db.table("friendships").select("*")
            .or_(f"user_a.eq.{user_id},user_b.eq.{user_id}")
            .eq("status","accepted").execute()).data or []
    return {r["user_b"] if r["user_a"] == user_id else r["user_a"] for r in rows}

@community_bp.route("/notifications")
def notifications():
    db = _sb(); uid = _uid()

    rows = (db.table("friendships").select("*")
            .or_(f"user_a.eq.{uid},user_b.eq.{uid}")
            .eq("status","pending").execute()).data or []
    incoming = [r for r in rows if r.get("requested_by") != uid]
    pm = _profile_map(db, [r.get("requested_by") for r in incoming])
    friend_requests = [{
        "id": r["id"],
        "email": pm.get(r.get("requested_by"),{}).get("email","Unknown user"),
        "username": pm.get(r.get("requested_by"),{}).get("username"),
    } for r in incoming]

    offer_rows = (db.table("card_transactions").select("*")
                  .eq("friend_id",uid).eq("status","pending")
                  .order("created_at",desc=True).execute()).data or []
    cards = _card_map(db,[r.get("card_id") for r in offer_rows if r.get("card_id")])
    owners = _profile_map(db,[r.get("owner_id") for r in offer_rows])
    card_offers = [{
        **r,
        "card_name": cards.get(r.get("card_id"),{}).get("name","Unknown card"),
        "owner_email": owners.get(r.get("owner_id"),{}).get("email","Unknown user"),
        "owner_username": owners.get(r.get("owner_id"),{}).get("username"),
    } for r in offer_rows]

    return_rows = (db.table("card_transactions").select("*")
                   .eq("owner_id",uid).eq("transaction_type","loan")
                   .eq("return_status","requested")
                   .is_("returned_at","null")
                   .order("return_requested_at",desc=True).execute()).data or []
    return_cards = _card_map(db,[r.get("card_id") for r in return_rows])
    borrowers = _profile_map(db,[r.get("current_borrower_id") or r.get("friend_id") for r in return_rows])
    return_requests = []
    for r in return_rows:
        borrower_id = r.get("current_borrower_id") or r.get("friend_id")
        p = borrowers.get(borrower_id,{})
        return_requests.append({
            **r,
            "card_name": return_cards.get(r.get("card_id"),{}).get("name","Unknown card"),
            "borrower_username": p.get("username"),
            "borrower_email": p.get("email","Unknown user"),
        })

    return render_template("notifications.html",
        friend_requests=friend_requests,
        card_offers=card_offers,
        return_requests=return_requests)

@community_bp.route("/notifications/friend/<int:friendship_id>/accept",methods=["POST"])
def notification_accept_friend(friendship_id):
    _sb().rpc("respond_to_friend_request",{"p_friendship_id":friendship_id,"p_accept":True}).execute()
    return redirect("/notifications")

@community_bp.route("/notifications/friend/<int:friendship_id>/decline",methods=["POST"])
def notification_decline_friend(friendship_id):
    _sb().rpc("respond_to_friend_request",{"p_friendship_id":friendship_id,"p_accept":False}).execute()
    return redirect("/notifications")

@community_bp.route("/notifications/offer/<int:transaction_id>/accept",methods=["POST"])
def notification_accept_offer(transaction_id):
    _sb().rpc("respond_to_card_offer",{"p_transaction_id":transaction_id,"p_accept":True}).execute()
    return redirect("/notifications")

@community_bp.route("/notifications/offer/<int:transaction_id>/decline",methods=["POST"])
def notification_decline_offer(transaction_id):
    _sb().rpc("respond_to_card_offer",{"p_transaction_id":transaction_id,"p_accept":False}).execute()
    return redirect("/notifications")

@community_bp.route("/notifications/return/<int:transaction_id>/accept",methods=["POST"])
def accept_return_request(transaction_id):
    _sb().rpc("respond_to_return_request",{"p_transaction_id":transaction_id,"p_accept":True}).execute()
    return redirect("/notifications")

@community_bp.route("/notifications/return/<int:transaction_id>/decline",methods=["POST"])
def decline_return_request(transaction_id):
    _sb().rpc("respond_to_return_request",{"p_transaction_id":transaction_id,"p_accept":False}).execute()
    return redirect("/notifications")

@community_bp.route("/community")
def community():
    db = _sb(); uid = _uid()
    if not _community_tables_ready(db):
        return render_template("community.html",friends=[],contacts=[],
            message="Community database tables are not installed yet.")

    friend_ids = list(_friends_of(db,uid))
    profiles = _profile_map(db,friend_ids)
    friends = [{
        "user_id": fid,
        "email": profiles.get(fid,{}).get("email","Unknown user"),
        "username": profiles.get(fid,{}).get("username")
    } for fid in friend_ids]
    friends.sort(key=lambda x:(x.get("username") or x.get("email") or "").lower())

    contacts = (db.table("contacts").select("*").eq("user_id",uid)
                .order("name").execute()).data or []
    return render_template("community.html",friends=friends,contacts=contacts,message=None)

@community_bp.route("/community/add-friend",methods=["POST"])
def community_add_friend():
    db=_sb(); uid=_uid()
    email=(request.form.get("email") or "").strip().lower()
    if not email: return redirect("/community")
    rows=db.table("profiles").select("user_id,email,username").eq("email",email).limit(1).execute().data or []
    if not rows or rows[0]["user_id"]==uid: return redirect("/community")
    other=rows[0]["user_id"]; a,b=sorted([uid,other])
    existing=db.table("friendships").select("id").eq("user_a",a).eq("user_b",b).limit(1).execute().data or []
    if not existing:
        db.table("friendships").insert({"user_a":a,"user_b":b,"requested_by":uid,"status":"pending"}).execute()
    return redirect("/community")

@community_bp.route("/community/contacts",methods=["POST"])
def add_contact():
    db=_sb(); uid=_uid()
    name=(request.form.get("name") or "").strip()
    phone=(request.form.get("phone") or "").strip() or None
    notes=(request.form.get("notes") or "").strip() or None
    if name:
        db.table("contacts").insert({"user_id":uid,"name":name,"phone":phone,"notes":notes}).execute()
    return redirect("/community")

@community_bp.route("/community/contacts/<int:contact_id>/delete",methods=["POST"])
def delete_contact(contact_id):
    db=_sb(); uid=_uid()
    db.table("contacts").delete().eq("id",contact_id).eq("user_id",uid).execute()
    return redirect("/community")

@community_bp.route("/community/trade-picker/<int:item_id>/<transaction_type>")
def community_trade_picker(item_id,transaction_type):
    db=_sb(); uid=_uid()
    if transaction_type not in ("loan","sale"): return redirect("/tracker")
    item=_get_item(db,item_id)
    if not item: return redirect("/tracker")
    card=_card_map(db,[item["card_id"]]).get(item["card_id"],{})

    # Borrowed cards may only be passed onward as a loan, never sold.
    borrowed = bool(item.get("loan_transaction_id"))
    if borrowed and transaction_type != "loan":
        return redirect("/tracker")

    friend_ids = list(_friends_of(db,uid))
    if borrowed:
        tx=(db.table("card_transactions").select("owner_id")
            .eq("id",item["loan_transaction_id"]).limit(1).execute()).data or []
        if not tx: return redirect("/tracker")
        owner_id=tx[0]["owner_id"]
        # Mutual friend = friend of current borrower AND friend of original owner.
        friend_ids=list(set(friend_ids) & _friends_of(db,owner_id))
        friend_ids=[x for x in friend_ids if x != owner_id]

    profiles=_profile_map(db,friend_ids)
    friends=[{"user_id":f,"email":profiles.get(f,{}).get("email","Unknown user"),
              "username":profiles.get(f,{}).get("username")} for f in friend_ids]

    contacts=[]
    if not borrowed:
        contacts=(db.table("contacts").select("*").eq("user_id",uid).order("name").execute()).data or []

    return render_template("trade_picker.html",friends=friends,contacts=contacts,
        transaction_type=transaction_type,item_id=item_id,
        card_name=card.get("name","Card"),borrowed=borrowed)

@community_bp.route("/community/transfer-loan/<int:item_id>/<friend_id>",methods=["POST"])
def transfer_borrowed_loan(item_id,friend_id):
    db=_sb(); uid=_uid()
    item=_get_item(db,item_id)
    if not item or not item.get("loan_transaction_id"): return redirect("/tracker")
    db.rpc("transfer_borrowed_loan",{
        "p_transaction_id":item["loan_transaction_id"],
        "p_new_borrower_id":friend_id
    }).execute()
    return redirect("/tracker")

@community_bp.route("/community/trade/<friend_id>/<transaction_type>")
def community_trade(friend_id,transaction_type):
    db=_sb(); uid=_uid(); transaction_type=transaction_type.lower()
    if transaction_type not in ("loan","sale") or not _accepted_friend(db,uid,friend_id):
        return redirect("/community")
    profile=(db.table("profiles").select("user_id,email,username")
             .eq("user_id",friend_id).limit(1).execute()).data or []
    if not profile: return redirect("/community")
    item_rows=(db.table("collection_items").select("*").eq("user_id",uid)
               .eq("is_missing",False).is_("loaned_from_user_id","null")
               .gt("quantity",0).execute()).data or []
    cards=_card_map(db,[r.get("card_id") for r in item_rows]); containers=_container_map(db)
    items=[]
    for row in item_rows:
        card=cards.get(row.get("card_id"),{}); container=containers.get(row.get("container_id"))
        items.append({"id":row["id"],"quantity":row["quantity"],
            "card_name":card.get("name","Unknown card"),"image_url":card.get("image_url"),
            "container_name":container.get("name") if container else "Unsorted"})
    items.sort(key=lambda x:x["card_name"].lower())
    return render_template("community_trade.html",friend=profile[0],items=items,
        transaction_type=transaction_type,selected_item_id=request.args.get("item",type=int))

@community_bp.route("/community/trade/<friend_id>/<transaction_type>/send",methods=["POST"])
def community_trade_send(friend_id,transaction_type):
    db=_sb(); uid=_uid(); transaction_type=transaction_type.lower()
    if transaction_type not in ("loan","sale") or not _accepted_friend(db,uid,friend_id):
        return redirect("/community")
    item_ids=request.form.getlist("item_id"); quantities=request.form.getlist("quantity")
    if not item_ids or len(item_ids)!=len(quantities): return redirect("/community")
    price_raw=(request.form.get("price") or "").strip()
    total_price=float(price_raw) if price_raw else None
    for index,(iid,qraw) in enumerate(zip(item_ids,quantities)):
        try: item_id=int(iid); qty=max(1,int(qraw))
        except ValueError: continue
        item=_get_item(db,item_id)
        if not item or item.get("loan_transaction_id") or int(item.get("quantity") or 0)<qty: continue
        db.table("card_transactions").insert({
            "owner_id":uid,"friend_id":friend_id,"current_borrower_id":friend_id,
            "card_id":item["card_id"],"source_item_id":item_id,
            "transaction_type":transaction_type,"quantity":qty,
            "price":total_price if transaction_type=="sale" and index==0 else (0 if transaction_type=="sale" and total_price is not None else None),
            "status":"pending"
        }).execute()
    return redirect("/community")

@community_bp.route("/community/custom/<int:contact_id>/<transaction_type>")
def custom_trade(contact_id,transaction_type):
    db=_sb(); uid=_uid()
    if transaction_type not in ("loan","sale"): return redirect("/community")
    contact=(db.table("contacts").select("*").eq("id",contact_id).eq("user_id",uid).limit(1).execute()).data or []
    if not contact: return redirect("/community")
    item_rows=(db.table("collection_items").select("*").eq("user_id",uid)
               .eq("is_missing",False).is_("loaned_from_user_id","null")
               .gt("quantity",0).execute()).data or []
    cards=_card_map(db,[r.get("card_id") for r in item_rows]); containers=_container_map(db)
    items=[]
    for row in item_rows:
        card=cards.get(row.get("card_id"),{}); c=containers.get(row.get("container_id"))
        items.append({"id":row["id"],"quantity":row["quantity"],"card_name":card.get("name","Unknown card"),
                      "image_url":card.get("image_url"),"container_name":c.get("name") if c else "Unsorted"})
    pseudo={"user_id":f"contact-{contact_id}","email":contact[0]["name"],"username":None}
    return render_template("community_trade.html",friend=pseudo,items=items,
        transaction_type=transaction_type,selected_item_id=request.args.get("item",type=int),
        custom_contact=contact[0])

@community_bp.route("/community/custom/<int:contact_id>/<transaction_type>/send",methods=["POST"])
def custom_trade_send(contact_id,transaction_type):
    db=_sb(); uid=_uid()
    if transaction_type not in ("loan","sale"): return redirect("/community")
    contact=(db.table("contacts").select("*").eq("id",contact_id).eq("user_id",uid).limit(1).execute()).data or []
    if not contact: return redirect("/community")
    item_ids=request.form.getlist("item_id"); quantities=request.form.getlist("quantity")
    price_raw=(request.form.get("price") or "").strip()
    total_price=float(price_raw) if price_raw else None
    for index,(iid,qraw) in enumerate(zip(item_ids,quantities)):
        try: item_id=int(iid); qty=max(1,int(qraw))
        except ValueError: continue
        item=_get_item(db,item_id)
        if not item or item.get("loan_transaction_id") or int(item.get("quantity") or 0)<qty: continue
        db.rpc("create_nonuser_transaction",{
            "p_contact_id":contact_id,"p_source_item_id":item_id,
            "p_transaction_type":transaction_type,"p_quantity":qty,
            "p_price": total_price if transaction_type=="sale" and index==0 else (0 if transaction_type=="sale" and total_price is not None else None)
        }).execute()
    return redirect("/tracker")

@community_bp.route("/community/return-borrowed/<int:transaction_id>",methods=["POST"])
def community_return_borrowed(transaction_id):
    _sb().rpc("request_loan_return",{"p_transaction_id":transaction_id}).execute()
    return redirect("/tracker")

@community_bp.route("/community/return/<int:transaction_id>",methods=["POST"])
def community_return(transaction_id):
    # Kept for old links: a registered borrower now creates a return request.
    _sb().rpc("request_loan_return",{"p_transaction_id":transaction_id}).execute()
    return redirect("/tracker")

@community_bp.route("/community/nonuser-return/<int:transaction_id>",methods=["POST"])
def nonuser_return(transaction_id):
    _sb().rpc("confirm_nonuser_return",{"p_transaction_id":transaction_id}).execute()
    return redirect("/tracker")

@community_bp.route("/profile",methods=["GET","POST"])
def profile_page():
    db=_sb(); uid=_uid(); message=None; success=False
    if request.method=="POST":
        username=(request.form.get("username") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,24}",username):
            message="Username must be 3–24 characters using only letters, numbers, or underscores."
        else:
            try:
                db.table("profiles").update({"username":username}).eq("user_id",uid).execute()
                message="Username saved."; success=True
            except Exception:
                message="That username is already taken."
    rows=db.table("profiles").select("username").eq("user_id",uid).limit(1).execute().data or []
    return render_template("profile.html",username=rows[0].get("username") if rows else None,
                           message=message,success=success)

@community_bp.route("/pending-offers")
def pending_offers_page():
    db=_sb(); uid=_uid()
    rows=(db.table("card_transactions").select("*").eq("owner_id",uid).eq("status","pending")
          .order("created_at",desc=True).execute()).data or []
    cards=_card_map(db,[r.get("card_id") for r in rows]); profiles=_profile_map(db,[r.get("friend_id") for r in rows])
    offers=[]
    for r in rows:
        p=profiles.get(r.get("friend_id"),{})
        offers.append({**r,"card_name":cards.get(r.get("card_id"),{}).get("name","Unknown card"),
                       "friend_email":p.get("email","another user"),"friend_username":p.get("username")})
    return render_template("pending_offers.html",offers=offers)

@community_bp.route("/pending-offers/<int:transaction_id>/delete",methods=["POST"])
def delete_pending_offer(transaction_id):
    db=_sb(); uid=_uid()
    db.table("card_transactions").delete().eq("id",transaction_id).eq("owner_id",uid).eq("status","pending").execute()
    return redirect("/pending-offers")

@community_bp.route("/profile/delete",methods=["POST"])
def delete_profile_account():
    if (request.form.get("confirm") or "").strip()!="DELETE": return redirect("/profile")
    _sb().rpc("delete_my_account").execute(); session.clear(); return redirect("/login")

@community_bp.route("/history")
def history():
    db=_sb(); uid=_uid(); events=[]
    added=(db.table("collection_items").select("id,card_id,quantity,added_at,loaned_from_user_id")
           .eq("user_id",uid).eq("is_missing",False).is_("loaned_from_user_id","null").execute()).data or []
    tx=(db.table("card_transactions").select("*").eq("owner_id",uid).execute()).data or []
    transfers=(db.table("loan_transfers").select("*").eq("owner_id",uid).execute()).data or []
    cards=_card_map(db,[r.get("card_id") for r in added+tx])
    profiles=_profile_map(db,[r.get("current_borrower_id") or r.get("friend_id") for r in tx] +
                             [r.get("from_user_id") for r in transfers]+[r.get("to_user_id") for r in transfers])
    contacts=_contact_map(db,uid,[r.get("contact_id") for r in tx])
    for r in added:
        events.append({"label":"Added","kind":"added","card_name":cards.get(r.get("card_id"),{}).get("name","Unknown card"),
                       "quantity":r.get("quantity") or 0,"person":None,"price":None,"timestamp":r.get("added_at")})
    for r in tx:
        if r.get("status")!="accepted": continue
        p=profiles.get(r.get("current_borrower_id") or r.get("friend_id"),{})
        c=contacts.get(r.get("contact_id"),{})
        person=c.get("name") or p.get("username") or p.get("email") or "Unknown"
        if r.get("transaction_type")=="loan":
            events.append({"label":"Lent","kind":"lent","card_name":cards.get(r.get("card_id"),{}).get("name","Unknown card"),
                           "quantity":r.get("quantity") or 0,"person":person,"price":None,"timestamp":r.get("created_at")})
            if r.get("return_requested_at") and not r.get("returned_at"):
                events.append({"label":"Return requested","kind":"return_requested","card_name":cards.get(r.get("card_id"),{}).get("name","Unknown card"),
                               "quantity":r.get("quantity") or 0,"person":person,"price":None,"timestamp":r.get("return_requested_at")})
            if r.get("returned_at"):
                events.append({"label":"Returned","kind":"returned","card_name":cards.get(r.get("card_id"),{}).get("name","Unknown card"),
                               "quantity":r.get("quantity") or 0,"person":person,"price":None,"timestamp":r.get("returned_at")})
        elif r.get("transaction_type")=="sale":
            events.append({"label":"Sold","kind":"sold","card_name":cards.get(r.get("card_id"),{}).get("name","Unknown card"),
                           "quantity":r.get("quantity") or 0,"person":person,"price":r.get("price"),"timestamp":r.get("created_at")})
    for tr in transfers:
        fp=profiles.get(tr.get("from_user_id"),{}); tp=profiles.get(tr.get("to_user_id"),{})
        events.append({"label":"Transferred","kind":"transferred",
            "card_name":cards.get(tr.get("card_id"),{}).get("name","Unknown card"),
            "quantity":tr.get("quantity") or 0,
            "person":f"@{fp.get('username') or fp.get('email','user')} → @{tp.get('username') or tp.get('email','user')}",
            "price":None,"timestamp":tr.get("created_at")})
    events.sort(key=lambda e:e.get("timestamp") or "",reverse=True)
    return render_template("history.html",events=events)
