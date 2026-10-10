import { typeOrder, type Card, type Entry, type Wish } from './types';
export function quantityState(quantity:number, owned:number):Pick<Entry,'missing'|'status'> {
  if(!Number.isInteger(quantity)||!Number.isInteger(owned)||quantity<1||quantity>1000||owned<0||owned>quantity) throw new Error('Owned must be between zero and deck quantity.');
  return {missing:quantity-owned,status:owned===quantity?'Owned':owned===0?'Missing':'Partial'};
}
export function buildWishlist(rows:Entry[]):Wish[] {
  const grouped=new Map<string,Wish>();
  for(const row of rows) {
    const missing=row.quantity-row.quantity_owned;if(missing<=0)continue;
    let wish=grouped.get(row.oracle_id);
    if(!wish){wish={oracle_id:row.oracle_id,card:row.card,missing:0,sources:[]};grouped.set(row.oracle_id,wish);}
    wish.missing+=missing;wish.sources.push({...row,missing});
  }
  return [...grouped.values()].sort((a,b)=>a.card.name.localeCompare(b.card.name));
}
// Ported from archived app.py group_cards_by_type: Creature before Land,
// then Planeswalker, Instant, Sorcery, Artifact, Enchantment and Battle.
export function primaryType(line:string) {return typeOrder.find(t=>line.split(' // ')[0].includes(t)) || 'Other';}
export function normalizeCard(raw:Record<string,any>):Card {
  const faces=raw.card_faces || [],front=faces[0] || raw,images=raw.image_uris || front.image_uris || {};
  return {id:raw.id,oracle_id:raw.oracle_id || raw.id,name:raw.name,image_url:images.normal || images.large || '',back_image_url:faces[1]?.image_uris?.normal || '',type_line:raw.type_line || '',mana_cost:raw.mana_cost || front.mana_cost || '',oracle_text:raw.oracle_text || faces.map((f:any)=>f.oracle_text || '').join('\n\n'),cmc:raw.cmc || 0,colors:raw.colors || front.colors || [],color_identity:raw.color_identity || [],set_code:raw.set || '',set_name:raw.set_name || '',collector_number:raw.collector_number || '',legalities:raw.legalities || {}};
}

export function availableBoards(format:import('./types').Format):import('./types').Board[] {
 return format==='commander'?['commander','main','maybeboard']:format==='casual'?['main','sideboard','maybeboard']:['main','sideboard','maybeboard'];
}
export function deckProgress(rows:Entry[]) {
 const included=rows.filter(r=>r.board!=='maybeboard');
 const quantity=included.reduce((sum,r)=>sum+r.quantity,0),owned=included.reduce((sum,r)=>sum+r.quantity_owned,0);
 return {quantity,owned,missing:quantity-owned,complete:quantity>0&&quantity===owned};
}
export interface DeckFilters {completion:string;format:string;from:string;to:string;sort:string}
export function filterDecks(decks:import('./types').Deck[],rows:Entry[],filters:DeckFilters) {
 const from=filters.from?new Date(filters.from+'T00:00:00').getTime():-Infinity;
 const to=filters.to?new Date(filters.to+'T23:59:59.999').getTime():Infinity;
 return decks.filter(deck=>{
  if(filters.format&&deck.format!==filters.format)return false;
  const complete=deckProgress(rows.filter(r=>r.deck_id===deck.id)).complete;
  if(filters.completion==='complete'&&!complete||filters.completion==='incomplete'&&complete)return false;
  const date=Date.parse(deck.created_at);
  return (!filters.from&&!filters.to)||(Number.isFinite(date)&&date>=from&&date<=to);
 }).sort((a,b)=>{
  const field=filters.sort==='updated'?'updated_at':'created_at';
  const delta=(Date.parse(b[field])||0)-(Date.parse(a[field])||0);
  return (filters.sort==='oldest'?-delta:delta)||a.name.localeCompare(b.name);
 });
}
