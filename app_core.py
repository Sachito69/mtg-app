import os
from flask import Flask, render_template, request, redirect, jsonify, session, url_for

from add_card import (
    search_all_printings, fetch_card_by_id, fetch_card_by_name,
    fetch_card_by_set_number, parse_bulk_line, save_card,
    save_to_collection, autocomplete_card_name,
)
from deck_logic import (
    find_real_sources, total_real_available, move_real_into_deck,
    find_decks_missing_card, fill_missing_in_deck, check_deck_legality,
    FORMAT_RULES,
)

from services.auth_service import (
    supabase, get_user_supabase, require_db, current_user_id,
)
from services.collection_service import (
    card_map, container_map, get_container, get_item,
)
from services.settings_service import (
    get_setting as service_get_setting,
    set_setting as service_set_setting,
)
from services.community_service import community_tables_ready, accepted_friend
from services.deck_service import TYPE_ORDER, group_cards_by_type

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# Compatibility wrappers for the existing Blueprint route files.
# New code should import services directly instead of adding more helpers here.
def _sb():
    return require_db()

def _uid():
    return current_user_id()

def _card_map(db, card_ids):
    return card_map(db, card_ids)

def _container_map(db):
    return container_map(db, _uid())

def _get_container(db, container_id):
    return get_container(db, _uid(), container_id)

def _get_item(db, item_id):
    return get_item(db, _uid(), item_id)

def get_setting(db, key, default=None):
    return service_get_setting(db, _uid(), key, default)

def set_setting(db, key, value):
    return service_set_setting(db, _uid(), key, value)

def _community_tables_ready(db):
    return community_tables_ready(db)

def _accepted_friend(db, uid, friend_id):
    return accepted_friend(db, uid, friend_id)

@app.errorhandler(RuntimeError)
def handle_runtime_error(error):
    if str(error) == "AUTH_REQUIRED":
        session.clear()
        return redirect("/login")
    raise error

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
        if db is None:
            return {
                "notification_count": 0,
                "pending_offer_count": 0,
                "current_username": None,
            }

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
