-- card_catalog: Scryfall's card data, shared/reference data (not personal collection)
-- One row per unique PRINTING of a card (e.g. "Lightning Bolt" has many printings
-- across different sets — each gets its own row here).

CREATE TABLE IF NOT EXISTS card_catalog (
    id            TEXT PRIMARY KEY,   -- Scryfall's unique id for this specific printing
    oracle_id     TEXT NOT NULL,      -- Identifies the CARD itself, shared across all its printings
    name          TEXT NOT NULL,
    set_code      TEXT,
    set_name      TEXT,
    image_url     TEXT,
    colors        TEXT,               -- stored as JSON text, e.g. ["R"]
    type_line     TEXT,
    mana_cost     TEXT,
    cmc           REAL,
    legalities    TEXT,               -- stored as JSON text, e.g. {"standard":"legal",...}
    updated_at    TEXT
);

-- Indexes: these make lookups fast once we have tens of thousands of rows.
-- Without them, searching by name or filtering by set would have to scan
-- every single row, one at a time.
CREATE INDEX IF NOT EXISTS idx_card_catalog_name ON card_catalog(name);
CREATE INDEX IF NOT EXISTS idx_card_catalog_oracle_id ON card_catalog(oracle_id);
CREATE INDEX IF NOT EXISTS idx_card_catalog_set_code ON card_catalog(set_code);


-- collection_items: YOUR personal collection. This is separate from
-- card_catalog because card_catalog is just facts about the card
-- (same for everyone), while this table is "how many of this I own,
-- and in what condition."

CREATE TABLE IF NOT EXISTS collection_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id       TEXT NOT NULL,      -- matches card_catalog.id
    quantity      INTEGER NOT NULL DEFAULT 1,
    condition     TEXT DEFAULT 'NM',  -- NM = Near Mint, LP = Lightly Played, etc.
    foil          INTEGER DEFAULT 0,  -- 0 = not foil, 1 = foil
    added_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (card_id) REFERENCES card_catalog(id)
);

CREATE INDEX IF NOT EXISTS idx_collection_items_card_id ON collection_items(card_id);


-- containers: binders, boxes, and decks all use this same table, told
-- apart by "kind". Format only applies to decks (Standard, Modern, etc.)

CREATE TABLE IF NOT EXISTS containers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,      -- 'binder' | 'box' | 'deck'
    format        TEXT,               -- only used when kind = 'deck'
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);



-- loans: tracking who has borrowed a real card. This sits ON TOP of
-- collection_items -- loaning a card doesn't move it out of its binder/
-- box/deck, it just marks it as currently out with someone.
-- returned_at IS NULL means the loan is still active.

CREATE TABLE IF NOT EXISTS loans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_item_id  INTEGER NOT NULL REFERENCES collection_items(id),
    borrower_name       TEXT NOT NULL,
    quantity_out        INTEGER NOT NULL,
    loaned_at           TEXT DEFAULT CURRENT_TIMESTAMP,
    returned_at         TEXT
);
