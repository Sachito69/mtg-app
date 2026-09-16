def card_map(db, card_ids):
    ids = list(dict.fromkeys([x for x in card_ids if x]))
    if not ids:
        return {}
    result = db.table("card_catalog").select("*").in_("id", ids).execute()
    return {row["id"]: row for row in (result.data or [])}

def container_map(db, user_id):
    result = db.table("containers").select("*").eq("user_id", user_id).execute()
    return {row["id"]: row for row in (result.data or [])}

def get_container(db, user_id, container_id):
    result = (
        db.table("containers").select("*")
        .eq("user_id", user_id).eq("id", container_id)
        .limit(1).execute()
    )
    return result.data[0] if result.data else None

def get_item(db, user_id, item_id):
    result = (
        db.table("collection_items").select("*")
        .eq("user_id", user_id).eq("id", item_id)
        .limit(1).execute()
    )
    return result.data[0] if result.data else None
