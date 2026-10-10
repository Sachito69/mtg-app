# Verification — October 10, 2026

- Production build passed with a mock Supabase URL/publishable key: TypeScript plus Vite 6.4.4. Real configuration must be set in Render before rebuilding.
- Ten unit tests passed under Vitest 5.0.3: quantity bounds, zero/partial/complete statuses, cross-deck wishlist aggregation, mixed card types and double-faced images.
- SQL was executed twice in temporary PostgreSQL (PGlite), with Supabase's auth.users/auth.uid interfaces represented locally. Verified default-missing additions, duplicate increments, partial counters, invalid bounds, stale versions, cross-user RLS visibility, forbidden inserts/edits/ownership transfer, deck deletion cascade and anonymous access denial.
- Browser flows passed in Chromium using the actual Supabase JS SDK and mocked Supabase/Scryfall endpoints: signup confirmation, forgot/reset password, login, create/open/delete deck, all three views, 4 requested/3 owned split rendering, per-deck wishlist filling, duplicate addition missing by default, quantity editing and preserved search results.
- Desktop and 390px mobile screenshots inspected; mobile deck/wishlist pages had no document-level horizontal overflow.

These checks do not validate the user's live Supabase migrations/profile triggers, actual email delivery, Render account configuration or Android packaging. No live project was modified and no deployment was performed.
