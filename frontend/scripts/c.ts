import { createClient } from '@supabase/supabase-js';
const sb = createClient('https://inmsssedwdmgtnhaydmg.supabase.co','sb_publishable_VY9dJ14bTCYQVg2OK3yV3Q_zeuhiC2O');
const n = await sb.schema('nestor' as any).from('intakes').select('id, client_id, product_slug, title').eq('product_slug','pulse');
console.log('intakes', n);
const ids = (n.data||[]).map((r:any)=>r.client_id);
const pub = await sb.from('clients').select('id, name').in('id', ids);
console.log('public.clients', pub);
const nc = await sb.schema('nestor' as any).from('clients').select('id, name').in('id', ids);
console.log('nestor.clients', nc);
