from flask import Blueprint
from app_core import *
from services.auth_service import require_db as _sb

settings_bp = Blueprint("settings", __name__)

@settings_bp.route("/settings/deck-view", methods=["POST"])
def save_deck_view():
    db = _sb()
    data = request.get_json(silent=True) or {}
    mode = data.get("deck_view")
    if mode not in ("text", "stacks", "grid"):
        return jsonify({"ok": False, "error": "Invalid deck view"}), 400
    set_setting(db, "preferred_deck_view", mode)
    return jsonify({"ok": True})

@settings_bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    db = _sb()
    saved = False
    if request.method == "POST":
        set_setting(
            db,
            "auto_pick_version",
            "true" if request.form.get("auto_pick_version") else "false",
        )
        preferred_deck_view = request.form.get("preferred_deck_view", "stacks")
        if preferred_deck_view not in ("text", "stacks", "grid"):
            preferred_deck_view = "stacks"
        set_setting(db, "preferred_deck_view", preferred_deck_view)
        saved = True
    auto_pick_version = get_setting(db, "auto_pick_version", "true") == "true"
    preferred_deck_view = get_setting(db, "preferred_deck_view", "stacks")
    if preferred_deck_view not in ("text", "stacks", "grid"):
        preferred_deck_view = "stacks"
    return render_template("settings.html",
        auto_pick_version=auto_pick_version,
        preferred_deck_view=preferred_deck_view,
        saved=saved,
    )
