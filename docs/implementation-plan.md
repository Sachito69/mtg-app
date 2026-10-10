# Static Supabase Deck Builder Implementation Plan

Goal: build the approved deck/wishlist flow without Flask, using app.py only as reference.
Architecture: React renders all pages, Supabase JS owns sessions/data, RLS/RPC own access control and arithmetic. Scryfall is fetched directly with a per-client throttle and bounded cache. Vite generates dist for Render Static Site.
Spec: design.md. Execution: inline, authorized by the user.

1. src/types.ts and src/logic.ts: port old type-priority behavior, normalize multi-face cards, derive partial state, aggregate wishlist by Oracle identity. Tests pin 4/3 = 1 missing, invalid quantities, mixed types and double faces.
2. src/api.ts and sql/setup.sql: direct Supabase Auth/client, paginated owner-scoped reads, new isolated tables/RLS, atomic add and version-checked edit RPCs. Temporary PostgreSQL tests check bounds, stale writes, cross-user access and anon denial.
3. src/main.tsx and src/style.css: auth, deck CRUD, search/filter, board selection, desktop drag/mobile tap, three stack/list views, wishlist with per-source acquisition, quantity editor and export. Test rendered flows with mocked Supabase/Scryfall endpoints using the actual browser SDK.
4. package.json, render.yaml, .env.example, README.md: static build and setup instructions. Check TypeScript/build, unit tests, SQL, browser flows and mobile overflow. Package replacement source only with lockfile and no generated node_modules/dist or credentials.
