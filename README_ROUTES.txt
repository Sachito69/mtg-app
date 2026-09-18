MTG APP - ROUTES REFACTOR

The original embedded HTML was already moved to /templates.
This stage also separates Flask routes into Blueprints.

Generated route modules:
  routes/auth.py
  routes/collection.py
  routes/community.py
  routes/main.py
  routes/settings.py
  routes/tracker.py

Shared helpers, Supabase setup, and utility functions are in:
  app_core.py

The new app.py only creates/registers the route modules and starts Flask.

Keep your existing:
  add_card.py
  deck_logic.py
  .env
  requirements.txt
  static/style.css

Run:
  py app.py

IMPORTANT:
This refactor preserves the existing route bodies instead of rewriting their
business logic. That makes it substantially safer than changing route behavior
and project structure at the same time.
