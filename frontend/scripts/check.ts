import { createClient } from '@supabase/supabase-js';
const sb = createClient('https://inmsssedwdmgtnhaydmg.supabase.co','sb_publishable_VY9dJ14bTCYQVg2OK3yV3Q_zeuhiC2O',{db:{schema:'nestor'}});
const { data } = await sb.from('intakes').select('id, title, status, created_at, client_intake_token').eq('client_id','bf4b90c4-16b9-4cca-92ba-a83ac13fbed8').order('created_at',{ascending:false});
console.log(data);
const { data: a } = await sb.from('intake_answers').select('intake_id, field_key').in('intake_id', (data||[]).map((d:any)=>d.id));
console.log('answers count by intake:', a?.reduce((acc:any,r:any)=>{acc[r.intake_id]=(acc[r.intake_id]||0)+1;return acc;},{}));
