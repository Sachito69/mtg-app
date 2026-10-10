# Decksmith — Supabase + Render deck builder

**React + TypeScript + Vite + Supabase + Scryfall. Render Static Site. No Flask or Python.** Your old app.py was used as the reference for card grouping and the deck/card behavior; it is not part of the new runtime.

Included: login, signup, forgot/reset password; deck create/edit/delete; name search and color/type/mana value/format filters; four boards; List, Condensed Stack and Split Stack; requested/owned quantity editing; automatic wishlist with per-deck Mark owned; desktop drag-to-add/mobile tap-to-add; text export.

## 1. Replace the frontend files

Back up your current project first. Extract this ZIP into the project folder containing package.json. This is the complete replacement frontend, not a patch against the unseen current React source. Its entry point is src/main.tsx. Old inventory/community files are no longer imported and may be kept in your backup. Keep your actual .env values out of the ZIP/source control.

No app.py, requirements.txt, gunicorn command or Python web service is needed. If you currently have a Render **Static Site**, keep that service type. If your old deployment is a Python **Web Service**, create a Static Site for this frontend.

## 2. Supabase SQL

Open your existing Supabase project → SQL Editor and run **sql/setup.sql** in full.

It creates two isolated tables:

- `deckbuilder_decks`: decks belonging to the signed-in user.
- `deckbuilder_cards`: card snapshots, board, requested quantity and quantity_owned progress counter.

RLS restricts all deck/card access to the owner. Atomic RPCs combine duplicate additions, enforce quantity limits, and reject stale edits from another window. Running the setup again is safe for this schema version. Existing tracker tables are left intact.

**Old collection/deck rows are not automatically imported.** This app starts with empty decks. Do not delete old tables yet if you want a later import. No physical-inventory reconciliation survives in this model.

A card requested 4 times with quantity_owned=3 shows **Partial** and contributes **1** missing copy to the wishlist. Adding another copy increases requested quantity only; the new copy is missing. Wishlist sources remain separate by deck/board. Marking one copy owned in one deck never automatically completes another deck. Counters are manual deck progress, not a collection ledger.

## 3. Run locally

Install **Node.js 22 or newer**. In the project folder:

```sh
npm ci
```

Copy .env.example to .env.local. Set:

```dotenv
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_PUBLISHABLE_OR_ANON_KEY
```

Use a **publishable key** (sb_publishable_...) or legacy **anon** key. A browser app must never contain a service_role or secret key. `VITE_SUPABASE_PUBLISHABLE_KEY` is also supported as an alias, so existing modern Supabase environment names can be retained.

```sh
npm run dev
```

Open the localhost URL printed in the terminal (usually http://localhost:5173). Supabase is the only database. The only device storage is the SDK's auth session and your view preference; edits require internet.

## 4. Render Static Site settings

Connect the repository/project folder that contains this package.json.

| Setting | Value |
|---|---|
| Service type | Static Site |
| Build command | `npm ci && npm run build` |
| Publish directory | `dist` |
| Node version | `22.16.0` or a supported newer 22+ version |
| Environment | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` |

Add this rewrite in Render → Redirects/Rewrites:

| Source | Destination | Action |
|---|---|---|
| `/*` | `/index.html` | Rewrite |

The rewrite lets the password-reset URL serve the app. `render.yaml` includes these settings if you use a Render Blueprint. Change environment variables **before building**; Vite embeds the public configuration in the bundle. Rebuild after changing them. If you see “One small setup step”, the configuration was missing or unsafe during the build.

## 5. Signup and password reset

Supabase → Authentication → URL Configuration:

- Site URL: your actual Render site URL.
- Allowed redirect URLs:
  - `https://YOUR-SITE.onrender.com/`
  - `https://YOUR-SITE.onrender.com/reset-password`
  - `http://localhost:5173/`
  - `http://localhost:5173/reset-password`

Use the exact origin/port if you run locally at 127.0.0.1 or another port. Keep email/password login enabled. With email confirmation enabled, signup prompts the user to confirm their email before logging in. Reset sends an email link, opens the new-password form and returns to the deck list after saving.

Existing Supabase users keep their accounts. This app supplies username metadata at signup but does not depend on a profiles table. A broken **legacy auth.users/profile trigger** can still block signup: inspect Auth logs if Supabase reports a database error, and fix that specific trigger rather than removing other apps' triggers indiscriminately.

## Views and actions

- **List:** one row per unique card/board with name, type, set, quantity, owned and missing counts. Missing entries use red text.
- **Condensed Stack:** one tile per unique card, overlapping different cards in its type group, with ×quantity and owned count. Incomplete entries are tinted red with lower image opacity.
- **Split Stack:** one tile per copy. Owned copies look normal; only missing copies are red/translucent. Clicking a copy can mark one owned/missing. Copies are interchangeable, not individually identified inventory objects.
- Click a card to edit quantities or remove it. Requested copies must be 1–1000; owned must be 0–requested. Reduce owned first if shrinking a deck entry below its current owned count.
- Search results can be dragged into the deck on desktop; use Add card on mobile. Pick main/commander/sideboard/maybeboard before adding. Search returns Scryfall's first page (up to 175 results); narrow filters when indicated.
- Identical Oracle IDs in the same board combine quantities; their first selected printing remains. Different boards keep independent counters. Multiple commanders can be entered on the commander board.
- The deck header includes main/commander/sideboard; maybeboard entries are excluded from its total but included in the wishlist.
- View preference is saved on the device per user. Data access is protected by RLS; no backend or admin key is used.
- If a connection fails during a save, reload before retrying: a request may already have reached Supabase. Stale-version edits are rejected and the app reloads the latest data.

## Limits and verification

This is the first working web version. It has no frames, inventory, friends, loans/sales, manual wishlist, automatic legacy import, import parser, full deck-legality engine, offline editing or APK package. Format filtering uses Scryfall's legality metadata; card totals are planning indicators, not a legality verdict. An Android wrapper can be added later without putting Flask back into the architecture.

Verified locally: TypeScript/production build, quantity/wishlist/card-normalization unit tests, temporary PostgreSQL tests for constraints/RLS/RPCs, and desktop/mobile browser flows against mocked Supabase/Scryfall endpoints using the actual Supabase SDK. **Your live Supabase project, email delivery and Render deployment still require the setup above and a live account test.**

```sh
npm test
npm run build
```

References: [Supabase React quickstart](https://supabase.com/docs/guides/getting-started/quickstarts/reactjs), [Render Static Sites](https://render.com/docs/static-sites), [Render rewrites](https://render.com/docs/redirects-rewrites), [Scryfall API](https://scryfall.com/docs/api).
