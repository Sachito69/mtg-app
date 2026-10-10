export const formats = ['commander','standard','pioneer','modern','legacy','vintage','pauper','casual'] as const;
export const boards = ['main','commander','sideboard','maybeboard'] as const;
export const typeOrder = ['Creature','Land','Planeswalker','Instant','Sorcery','Artifact','Enchantment','Battle','Other'] as const;
export type Format=typeof formats[number];
export type Board=typeof boards[number];
export type View='list'|'condensed'|'split';
export interface Card { id:string; oracle_id:string; name:string; image_url:string; back_image_url:string; type_line:string; mana_cost:string; oracle_text:string; cmc:number; colors:string[]; color_identity:string[]; set_code:string; set_name:string; collector_number:string; legalities:Record<string,string> }
export interface Deck { id:string; user_id:string; name:string; format:Format; description:string; created_at:string; updated_at:string }
export interface Entry { id:string; deck_id:string; oracle_id:string; printing_id:string; card:Card; quantity:number; quantity_owned:number; board:Board; version:number; missing:number; status:'Missing'|'Partial'|'Owned' }
export interface Wish { oracle_id:string; card:Card; missing:number; sources:Entry[] }
export interface Data { decks:Deck[]; cards:Entry[]; wishlist:Wish[] }
export const emptyData:Data={decks:[],cards:[],wishlist:[]};
