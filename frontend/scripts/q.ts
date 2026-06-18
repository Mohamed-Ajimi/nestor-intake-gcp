import { createClient } from '@supabase/supabase-js';
const sb = createClient('https://inmsssedwdmgtnhaydmg.supabase.co','sb_publishable_VY9dJ14bTCYQVg2OK3yV3Q_zeuhiC2O',{db:{schema:'nestor'}});
const { data: t, error } = await sb.from('intake_templates').select('id, version, schema').eq('product_slug','pulse').eq('is_active',true).order('version',{ascending:false}).limit(1).single();
if (error) { console.error(error); process.exit(1); }
console.log('TEMPLATE_ID='+t.id);
console.log('VERSION='+t.version);
console.log(JSON.stringify(t.schema));
