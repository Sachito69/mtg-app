import {createClient} from '@supabase/supabase-js';
import {buildWishlist,quantityState,normalizeCard} from './logic';
import {type Board,type Card,type Data,type Deck,type Entry,type Format} from './types';
const url=import.meta.env.VITE_SUPABASE_URL || '';
const key=import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY || '';
function publicKey(value:string) {
 if(value.startsWith('sb_secret_'))return false;
 if(value.split('.').length===3){try{return JSON.parse(atob(value.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).role==='anon';}catch{return false;}}
 return value.startsWith('sb_publishable_');
}
export const configurationError=!url || !key?'Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY, then rebuild.':!publicKey(key)?'Use a Supabase publishable or anon key. Never a secret/service-role key.':'';
export const supabase=!configurationError?createClient(url,key):null;
export function check(error:any):void {
 if(!error)return;
 const messages:Record<string,string>={'40001':'This card changed in another window. Reload and retry.','23514':'Owned copies cannot exceed deck quantity. Reduce owned before reducing requested copies.','22023':error.message,'42501':'You cannot access this deck. Check the setup SQL if it is yours.','P0002':'Card not found.'};
 const e=new Error(messages[error.code] || error.message || 'Unable to save. Check your connection.') as Error & {code?:string}; e.code=error.code;throw e;
}
export async function loadData(userId:string):Promise<Data> {
 if(!supabase)throw new Error(configurationError);
 const decks:Deck[]=[],cards:Entry[]=[];
 for(let offset=0;;offset+=1000){
  const {data,error}=await supabase.from('deckbuilder_decks').select('*').eq('user_id',userId).order('created_at',{ascending:false}).order('id').range(offset,offset+999);check(error);
  decks.push(...(data || []) as Deck[]);if((data || []).length<1000)break;
 }
 for(let offset=0;;offset+=1000){
  const {data,error}=await supabase.from('deckbuilder_cards').select('*,deck:deckbuilder_decks!inner(user_id)').eq('deck.user_id',userId).order('created_at').order('id').range(offset,offset+999);check(error);
  cards.push(...(data || []).map(r=>({...r,...quantityState(r.quantity,r.quantity_owned)}) as Entry));if((data || []).length<1000)break;
 }
 return {decks,cards,wishlist:buildWishlist(cards)};
}
export async function saveDeck(userId:string,fields:{name:string;format:Format;description:string},id?:string):Promise<Deck> {
 if(!supabase)throw new Error(configurationError);
 const name=fields.name.trim();if(!name || name.length>100)throw new Error('Deck name must contain 1–100 characters.');
 const query=id?supabase.from('deckbuilder_decks').update({...fields,name}).eq('id',id).eq('user_id',userId):supabase.from('deckbuilder_decks').insert({...fields,name,user_id:userId});
 const {data,error}=await query.select().single();check(error);return data as Deck;
}
export async function deleteDeck(id:string,userId:string) {const {data,error}=await supabase!.from('deckbuilder_decks').delete().eq('id',id).eq('user_id',userId).select('id');check(error);if(!data?.length)throw new Error('Deck not found.');}
export async function addCard(deckId:string,card:Card,board:Board) {const {error}=await supabase!.rpc('deckbuilder_add_card',{p_deck_id:deckId,p_oracle_id:card.oracle_id,p_printing_id:card.id,p_card:card,p_board:board,p_quantity:1});check(error);}
export async function editCard(row:Entry,operation:'quantity'|'owned'|'acquire',amount:number) {
 if(!Number.isInteger(amount))throw new Error('Enter a whole number.');
 if(operation==='quantity')quantityState(amount,row.quantity_owned);
 else quantityState(row.quantity,operation==='acquire'?row.quantity_owned+amount:amount);
 const {error}=await supabase!.rpc('deckbuilder_edit_card',{p_id:row.id,p_version:row.version,p_operation:operation,p_amount:amount});check(error);
}
export async function deleteCard(id:string) {const {data,error}=await supabase!.from('deckbuilder_cards').delete().eq('id',id).select('id');check(error);if(!data?.length)throw new Error('Card not found.');}
export interface Filters {color:string;type:string;mv:string;format:string}
const cache=new Map<string,{cards:Card[];hasMore:boolean}>();let queue=Promise.resolve(),last=0;
export async function searchCards(q:string,filters:Filters) {
 const parts=q.trim()?['('+q.trim()+')']:[];
 if(filters.color)parts.push('c:'+filters.color.toLowerCase());if(filters.type)parts.push('t:'+filters.type.toLowerCase());if(filters.mv!=='')parts.push('mv='+filters.mv);if(filters.format)parts.push('f:'+filters.format);
 const query=parts.join(' ');if(!query)return {cards:[],hasMore:false};
 if(cache.has(query))return cache.get(query)!;
 const previous=queue;let release:()=>void=()=>{};queue=new Promise<void>(resolve=>release=resolve);await previous;
 try {
  await new Promise(r=>setTimeout(r,Math.max(0,110-(performance.now()-last))));last=performance.now();
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
  let response:Response;try{response=await fetch('https://api.scryfall.com/cards/search?'+new URLSearchParams({q:query,unique:'cards',order:'name'}),{headers:{Accept:'application/json'},signal:controller.signal});}finally{clearTimeout(timeout);}
  if(response.status===404)return {cards:[],hasMore:false};if(!response.ok)throw new Error('Card search is unavailable or the query is invalid. Please try again.');
  const raw=await response.json();const result={cards:raw.data.map(normalizeCard) as Card[],hasMore:!!raw.has_more};if(cache.size>=100)cache.delete(cache.keys().next().value!);cache.set(query,result);return result;
 } finally {release();}
}
