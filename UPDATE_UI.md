# UI update

Extract this ZIP and replace the matching files inside your existing `mtg-app` folder. Keep your other files and environment settings.

Run `npm run build`, then commit and push the changes to the branch Render deploys (main if configured that way). The existing Render Static Site settings remain: build `npm ci && npm run build`, publish directory `dist`.

No dependency installation or Supabase SQL migration is required for this update.

Changes:
- Compact card image tiles without separate card name labels.
- A `+1 owned` button below missing image tiles and beside names in the text list. Each click fills one missing copy.
- Visible sideboard sections for constructed decks, including empty sideboards.
- A commander section with an Add commander slot for Commander decks.
- Deck filters for completion, format, and creation date, plus date sorting.
- Wishlist Text/Image views, with the selected view saved on this browser.

Completion means a nonempty deck with every included copy owned. Sideboard and commander cards count; maybeboard cards do not. This is an ownership filter, not a format legality check.

Validation: production build, 13 unit tests, and browser checks passed. Browser checks used mocked remote Supabase/Scryfall responses and included phone layout, quick fill, board selection, filters, wishlist views, and existing authentication/deck editing flows.
