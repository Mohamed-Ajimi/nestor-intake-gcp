import { createClient } from '@supabase/supabase-js';
const sb = createClient('https://inmsssedwdmgtnhaydmg.supabase.co','sb_publishable_VY9dJ14bTCYQVg2OK3yV3Q_zeuhiC2O',{db:{schema:'nestor'}});
const r = await (sb as any).schema('public').from('clients').select('id, name').in('id', ['a9a5075c-5135-4e0b-82ba-cc3a4656d55e']);
console.log(r);
