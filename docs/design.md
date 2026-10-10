# Decksmith design — final clarified scope

The old Flask app.py is a reference implementation only. The user clarified “don't use the flask just use supabase and render from app.py”. This build uses React + TypeScript + Vite, Supabase Auth/Postgres/RLS, Scryfall search and Render Static Site hosting. No Python, Flask, SQLite, native backend or Tauri build is included.

Login/signup/forgot password → deck list/add deck → deck page with search/filter → newly added cards start missing → List / Condensed Stack / Split Stack → wishlist across decks with per-deck Mark owned controls. Requested quantity and manual quantity_owned counter define missing = requested - owned. This is not a physical collection model. Repeated cards merge within the same Oracle identity and board; adding copies never marks them owned.

New deckbuilder_decks/cards tables leave existing tables intact. RLS enforces ownership. Atomic RPCs support duplicate additions and version-checked edits. No automatic import of old inventory is performed. A normalized Scryfall snapshot lives on each deck entry. Type-grouping priority is ported from the archived app.py. Search is a simple name/filter control with inline results, not a separate finder window. Cards render as safe React text; image URLs are restricted to cards.scryfall.io.

Condensed stacks overlap unique card tiles vertically within type groups, with ×quantity and owned counts. Split stacks overlap one tile per copy, tinting only missing copies. Views persist on the current device per user. Mobile uses add buttons and card dialogs. Desktop also supports dragging search results onto the deck.

Exclude frames, community, loans/sales, physical inventory, offline editing, manual wishlist and native APK packaging. The frontend remains suitable for a later mobile wrapper; Android packaging and password reset app-links are not part of this deliverable.
