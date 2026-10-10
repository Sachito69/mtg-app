-- New isolated tables. Never drops or alters old tracker tables.
begin;
create table if not exists public.deckbuilder_decks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (length(trim(name)) between 1 and 100),
  format text not null default 'commander' check (format in ('commander','standard','pioneer','modern','legacy','vintage','pauper','casual')),
  description text not null default '' check (length(description) <= 2000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.deckbuilder_cards (
  id uuid primary key default gen_random_uuid(),
  deck_id uuid not null references public.deckbuilder_decks(id) on delete cascade,
  oracle_id uuid not null,
  printing_id uuid not null,
  card jsonb not null check (jsonb_typeof(card)='object' and card ? 'name'),
  quantity integer not null default 1 check (quantity between 1 and 1000),
  quantity_owned integer not null default 0 check (quantity_owned between 0 and quantity),
  board text not null default 'main' check (board in ('main','sideboard','commander','maybeboard')),
  version integer not null default 1,
  created_at timestamptz not null default now(),
  unique(deck_id,oracle_id,board)
);
create index if not exists deckbuilder_decks_owner_idx on public.deckbuilder_decks(user_id);
create index if not exists deckbuilder_cards_deck_idx on public.deckbuilder_cards(deck_id);
alter table public.deckbuilder_decks enable row level security;
alter table public.deckbuilder_cards enable row level security;
revoke all on public.deckbuilder_decks,public.deckbuilder_cards from anon;
grant select,insert,update,delete on public.deckbuilder_decks,public.deckbuilder_cards to authenticated;
drop policy if exists deckbuilder_decks_owner on public.deckbuilder_decks;
create policy deckbuilder_decks_owner on public.deckbuilder_decks for all to authenticated
using (user_id=(select auth.uid())) with check (user_id=(select auth.uid()));
drop policy if exists deckbuilder_cards_owner on public.deckbuilder_cards;
create policy deckbuilder_cards_owner on public.deckbuilder_cards for all to authenticated
using (exists (select 1 from public.deckbuilder_decks d where d.id=deck_id and d.user_id=(select auth.uid())))
with check (exists (select 1 from public.deckbuilder_decks d where d.id=deck_id and d.user_id=(select auth.uid())));

-- Security INVOKER: functions keep the caller's RLS restrictions.
create or replace function public.deckbuilder_add_card(p_deck_id uuid,p_oracle_id uuid,p_printing_id uuid,p_card jsonb,p_board text,p_quantity integer)
returns public.deckbuilder_cards language plpgsql security invoker set search_path = '' as $$
declare result public.deckbuilder_cards;
begin
  if p_quantity is null or p_quantity not between 1 and 1000 then raise exception 'Invalid quantity' using errcode='22023'; end if;
  if not exists(select 1 from public.deckbuilder_decks where id=p_deck_id and user_id=auth.uid()) then
    raise exception 'Deck not found' using errcode='42501';
  end if;
  insert into public.deckbuilder_cards(deck_id,oracle_id,printing_id,card,board,quantity,quantity_owned)
  values(p_deck_id,p_oracle_id,p_printing_id,p_card,p_board,p_quantity,0)
  on conflict(deck_id,oracle_id,board) do update
    set quantity=public.deckbuilder_cards.quantity+excluded.quantity,
        version=public.deckbuilder_cards.version+1
  returning * into result;
  return result;
end $$;

-- Version checking avoids silently overwriting edits from another browser.
create or replace function public.deckbuilder_edit_card(p_id uuid,p_version integer,p_operation text,p_amount integer)
returns public.deckbuilder_cards language plpgsql security invoker set search_path = '' as $$
declare item public.deckbuilder_cards;
begin
  select * into item from public.deckbuilder_cards where id=p_id for update;
  if not found then raise exception 'Card not found' using errcode='P0002'; end if;
  if item.version<>p_version or p_version is null then raise exception 'Card changed. Reload and retry.' using errcode='40001'; end if;
  if p_amount is null then raise exception 'Amount required' using errcode='22023'; end if;
  if p_operation='owned' then item.quantity_owned:=p_amount;
  elsif p_operation='quantity' then item.quantity:=p_amount;
  elsif p_operation='acquire' and p_amount>0 then item.quantity_owned:=item.quantity_owned+p_amount;
  else raise exception 'Invalid operation' using errcode='22023'; end if;
  if item.quantity not between 1 and 1000 or item.quantity_owned not between 0 and item.quantity then
    raise exception 'Owned must be between zero and deck quantity. Reduce owned before removing copies.' using errcode='22023';
  end if;
  update public.deckbuilder_cards set quantity=item.quantity,quantity_owned=item.quantity_owned,version=version+1
  where id=p_id returning * into item;
  return item;
end $$;

-- Trigger covers direct table edits too, keeping concurrency versions trustworthy.
create or replace function public.deckbuilder_touch_card() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op='UPDATE' then new.version:=old.version+1; end if;
  update public.deckbuilder_decks set updated_at=now() where id=new.deck_id;
  return new;
end $$;
drop trigger if exists deckbuilder_cards_touch on public.deckbuilder_cards;
create trigger deckbuilder_cards_touch before insert or update on public.deckbuilder_cards
for each row execute function public.deckbuilder_touch_card();
create or replace function public.deckbuilder_touch_deck() returns trigger
language plpgsql set search_path = '' as $$
begin new.updated_at:=now(); return new; end $$;
drop trigger if exists deckbuilder_decks_touch on public.deckbuilder_decks;
create trigger deckbuilder_decks_touch before update on public.deckbuilder_decks
for each row execute function public.deckbuilder_touch_deck();
revoke all on function public.deckbuilder_add_card(uuid,uuid,uuid,jsonb,text,integer) from public,anon;
revoke all on function public.deckbuilder_edit_card(uuid,integer,text,integer) from public,anon;
grant execute on function public.deckbuilder_add_card(uuid,uuid,uuid,jsonb,text,integer) to authenticated;
grant execute on function public.deckbuilder_edit_card(uuid,integer,text,integer) to authenticated;
commit;
