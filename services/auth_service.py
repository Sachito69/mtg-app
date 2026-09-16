import os
from flask import session
from dotenv import load_dotenv
from supabase import create_client
from supabase_auth.errors import AuthApiError

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set.")

def create_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# Kept for auth routes that currently use the shared client.
supabase = create_supabase_client()

def get_user_supabase():
    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")
    if not access_token or not refresh_token:
        return None

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    try:
        auth_response = client.auth.set_session(access_token, refresh_token)
        auth_session = getattr(auth_response, "session", None)

        # Supabase refresh tokens rotate. Always save the newest pair.
        if auth_session:
            if getattr(auth_session, "access_token", None):
                session["access_token"] = auth_session.access_token
            if getattr(auth_session, "refresh_token", None):
                session["refresh_token"] = auth_session.refresh_token
            user = getattr(auth_session, "user", None)
            if user:
                if getattr(user, "id", None):
                    session["user_id"] = user.id
                if getattr(user, "email", None):
                    session["email"] = user.email
        return client

    except AuthApiError:
        # Stale/revoked refresh token: log out cleanly instead of Render 500.
        session.clear()
        return None
    except Exception:
        session.clear()
        return None

def require_db():
    client = get_user_supabase()
    if client is None:
        raise RuntimeError("AUTH_REQUIRED")
    return client

def current_user_id():
    user_id = session.get("user_id")
    if not user_id:
        raise RuntimeError("AUTH_REQUIRED")
    return user_id
