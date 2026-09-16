def community_tables_ready(db):
    try:
        db.table("profiles").select("user_id").limit(1).execute()
        db.table("friendships").select("id").limit(1).execute()
        db.table("card_transactions").select("id").limit(1).execute()
        return True
    except Exception:
        return False

def accepted_friend(db, uid, friend_id):
    a, b = sorted([uid, friend_id])
    rows = (
        db.table("friendships").select("id")
        .eq("user_a", a).eq("user_b", b).eq("status", "accepted")
        .limit(1).execute()
    ).data or []
    return bool(rows)
