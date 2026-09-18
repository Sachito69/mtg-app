MTG APP - SERVICES REFACTOR

New /services layer:
  auth_service.py        Supabase client/session/authenticated DB access
  collection_service.py Shared card/container/item database lookups
  community_service.py  Friendship/community database helpers
  settings_service.py   Settings reads/writes
  deck_service.py       Deck grouping/type logic

app_core.py is now intentionally small:
  - creates Flask app
  - registers global error/context behavior
  - provides compatibility wrappers for older route code

/routes remains responsible for HTTP requests/responses.
/templates remains responsible for HTML.
/services is responsible for reusable business/database logic.

Run:
  py app.py

The AUTH_REQUIRED mismatch was also fixed: expired/missing sessions now use the
same RuntimeError("AUTH_REQUIRED") value handled by app_core.
