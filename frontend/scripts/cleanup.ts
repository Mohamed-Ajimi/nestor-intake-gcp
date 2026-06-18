import { createClient } from '@supabase/supabase-js';
const sb = createClient('https://inmsssedwdmgtnhaydmg.supabase.co','sb_publishable_VY9dJ14bTCYQVg2OK3yV3Q_zeuhiC2O',{db:{schema:'nestor'}});
const oldId = 'b9ba4f75-5c1e-4165-8a4c-d3c9a6cc4f2b';
await sb.from('intake_answers').delete().eq('intake_id', oldId);
const { error } = await sb.from('intakes').delete().eq('id', oldId);
console.log('cleanup', error || 'ok');
