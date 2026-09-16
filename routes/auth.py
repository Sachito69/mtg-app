from flask import Blueprint
from app_core import *

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        try:
            response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })

            session["access_token"] = response.session.access_token
            session["refresh_token"] = response.session.refresh_token
            session["user_id"] = response.user.id
            session["email"] = response.user.email

            return redirect("/")

        except Exception as e:
            return render_template("login.html",
                error=str(e)
            )

    return render_template("login.html",
        error=None
    )

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        try:
            response = supabase.auth.sign_up({
                "username": username,
                "email": email,
                "password": password,
            })

            if response.session:
                session["access_token"] = response.session.access_token
                session["refresh_token"] = response.session.refresh_token
                session["user_id"] = response.user.id
                session["email"] = response.user.email

                return redirect("/")

            return render_template("signup.html",
                error=None,
                message="Account created. Check your email to confirm your account, then log in."
            )

        except Exception as e:

            return render_template("signup.html",
                error=str(e),
                message=None
            )

    return render_template("signup.html",
        error=None,
        message=None
    )

@auth_bp.route("/logout")
def logout():

    try:
        supabase.auth.sign_out()
    except Exception:
        pass

    session.clear()

    return redirect("/login")
