def get_setting(db, user_id, key, default=None):
    result = (
        db.table("settings").select("value")
        .eq("user_id", user_id).eq("key", key)
        .limit(1).execute()
    )
    return result.data[0]["value"] if result.data else default

def set_setting(db, user_id, key, value):
    (
        db.table("settings")
        .upsert({"user_id": user_id, "key": key, "value": value},
                on_conflict="user_id,key")
        .execute()
    )
