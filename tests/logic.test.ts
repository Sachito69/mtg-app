import {describe,it,expect} from 'vitest';
import {quantityState,buildWishlist,primaryType,normalizeCard} from '../src/logic';
import type {Entry} from '../src/types';
describe('deck progress without inventory',()=>{
 it('4 requested / 3 owned = 1 missing',()=>expect(quantityState(4,3)).toEqual({missing:1,status:'Partial'}));
 it('zero owned is missing; fully owned is complete',()=>{expect(quantityState(4,0).status).toBe('Missing');expect(quantityState(4,4).status).toBe('Owned');});
 it.each([[0,0],[4,5],[4,-1],[4,1.5],[1001,0]])('rejects invalid %i/%i',(q,o)=>expect(()=>quantityState(q,o)).toThrow());
 it('sums shortages and retains distinct deck sources',()=>{
 const card={name:'Bolt'};
 const rows=[{id:'a',oracle_id:'bolt',card,quantity:4,quantity_owned:3},{id:'b',oracle_id:'bolt',card,quantity:4,quantity_owned:2},{id:'c',oracle_id:'ring',card:{name:'Ring'},quantity:1,quantity_owned:1}] as Entry[];
 const wish=buildWishlist(rows);expect(wish).toHaveLength(1);expect(wish[0].missing).toBe(3);expect(wish[0].sources.map(s=>s.id)).toEqual(['a','b']);
 });
 it('ports old mixed-type priority and groups only front faces',()=>{expect(primaryType('Artifact Creature — Golem')).toBe('Creature');expect(primaryType('Artifact Land')).toBe('Land');expect(primaryType('Instant // Creature — Human')).toBe('Instant');});
 it('handles separate front/back images',()=>{const c=normalizeCard({id:'a',oracle_id:'b',name:'Front // Back',card_faces:[{image_uris:{normal:'https://cards.scryfall.io/front.jpg'},mana_cost:'{U}'},{image_uris:{normal:'https://cards.scryfall.io/back.jpg'}}]});expect(c.image_url).toContain('front.jpg');expect(c.back_image_url).toContain('back.jpg');expect(c.mana_cost).toBe('{U}');});
});
