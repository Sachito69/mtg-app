-- Postgres/Supabase schema -- multi-user version.
--
-- Every user's data is scoped by a user_id column that points at
-- Supabase's own auth.users table (created automatically by Supabase
-- Auth -- you never create or manage that table yourself).
--
-- If you already ran an earlier version of this file against your
-- Supabase project (without user_id / friendships), don't re-run this
-- one -- run migration_add_users.sql instead, which safely adds just
-- what's missing without touching your existing data.

-- card_catalog: Scryfall's card data. Shared/reference data, the same
-- for every user -- NOT scoped by user_id. One row per unique PRINTING
-- of a card (e.g. "Lightning Bolt" has many printings across sets).

CREATE TABLE IF NOT EXISTS card_catalog (
    id            TEXT PRIMARY KEY,
    oracle_id     TEXT NOT NULL,
    name          TEXT NOT NULL,
    set_code      TEXT,
    set_name      TEXT,
    image_url     TEXT,
    colors        TEXT,
    type_line     TEXT,
    mana_cost     TEXT,
    cmc           REAL,
    legalities    TEXT,
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_card_catalog_name ON card_catalog(name);
CREATE INDEX IF NOT EXISTS idx_card_catalog_oracle_id ON card_catalog(oracle_id);
CREATE INDEX IF NOT EXISTS idx_card_catalog_set_code ON card_catalog(set_code);


-- containers: binders, boxes, and decks. Each one belongs to exactly
-- one user.

CREATE TABLE IF NOT EXISTS containers (
    id            SERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,      -- 'binder' | 'box' | 'deck'
    format        TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_containers_user_id ON containers(user_id);


-- collection_items: one user's personal collection. user_id is stored
-- directly here (not just inferred through container_id) so "Unsorted"
-- items (container_id IS NULL) are still clearly owned by someone.

CREATE TABLE IF NOT EXISTS collection_items (
    id            SERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    card_id       TEXT NOT NULL REFERENCES card_catalog(id),
    quantity      INTEGER NOT NULL DEFAULT 1,
    condition     TEXT DEFAULT 'NM',
    foil          INTEGER DEFAULT 0,
    added_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    container_id  INTEGER REFERENCES containers(id),
    is_missing    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_collection_items_card_id ON collection_items(card_id);
CREATE INDEX IF NOT EXISTS idx_collection_items_container_id ON collection_items(container_id);
CREATE INDEX IF NOT EXISTS idx_collection_items_user_id ON collection_items(user_id);


-- loans: who has borrowed a real card. Scoped by ownership of the card
-- being loaned (via collection_item_id), so no user_id column needed here.

CREATE TABLE IF NOT EXISTS loans (
    id                  SERIAL PRIMARY KEY,
    collection_item_id  INTEGER NOT NULL REFERENCES collection_items(id),
    borrower_name       TEXT NOT NULL,
    quantity_out        INTEGER NOT NULL,
    loaned_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    returned_at         TIMESTAMP
);


-- settings: per-user app preferences (key/value).

CREATE TABLE IF NOT EXISTS settings (
    user_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    key       TEXT NOT NULL,
    value     TEXT,
    PRIMARY KEY (user_id, key)
);


-- friendships: a connection request between two users. 'pending' until
-- the addressee accepts it, then 'accepted'. Deleting the row covers
-- declining, cancelling, and un-friending -- all the same operation.

CREATE TABLE IF NOT EXISTS friendships (
    id             SERIAL PRIMARY KEY,
    requester_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    addressee_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'accepted'
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (requester_id, addressee_id),
    CHECK (requester_id != addressee_id)
);

CREATE INDEX IF NOT EXISTS idx_friendships_requester ON friendships(requester_id);
CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships(addressee_id);
