import { createClient } from '@supabase/supabase-js';

const URL = 'https://inmsssedwdmgtnhaydmg.supabase.co';
const KEY = 'sb_publishable_VY9dJ14bTCYQVg2OK3yV3Q_zeuhiC2O';

const sbPub = createClient(URL, KEY);
const sbNestor = createClient(URL, KEY, { db: { schema: 'nestor' } });

// 1. Demo client
const clientName = 'DEMO — Acme Robotics NV';
let clientId: string;
const { data: existing } = await sbPub.from('clients').select('id').eq('name', clientName).maybeSingle();
if (existing) {
  clientId = (existing as any).id;
  console.log('Reusing demo client', clientId);
} else {
  const { data, error } = await sbPub
    .from('clients')
    .insert({
      name: clientName,
      country: 'BE',
      website: 'https://demo-acme-robotics.example',
      industry: 'Industrial automation',
    })
    .select('id')
    .single();
  if (error) throw error;
  clientId = (data as any).id;
  console.log('Created demo client', clientId);
}

// 2. Active Pulse template
const { data: template, error: tErr } = await sbNestor
  .from('intake_templates')
  .select('id')
  .eq('product_slug', 'pulse')
  .eq('is_active', true)
  .order('version', { ascending: false })
  .limit(1)
  .single();
if (tErr || !template) throw new Error('No template');

// 3. Demo answers
const answers = {
  client_name: 'Acme Robotics NV',
  project_name: 'EU-expansie 2026 — DACH-verkenning',
  contact_name: 'Sophie Vandenberghe',
  contact_email: 'sophie@demo-acme-robotics.example',
  contact_phone: '+32 475 12 34 56',
  company_intro:
    'Acme Robotics ontwerpt en bouwt cobots voor mid-market maakbedrijven in de Benelux. We zijn 12 jaar oud, 84 medewerkers, hoofdkantoor in Gent en een tweede vestiging in Eindhoven. Onze klanten zijn typisch familiale maakbedrijven met 50-500 medewerkers die een eerste stap zetten in automatisatie. We staan vandaag bekend om onze laagdrempelige onboarding en sterke after-sales — minder om technologische voorsprong.',
  decision_or_goal:
    'We moeten beslissen of we in 2026 actief Duitsland (DACH) aanvallen met een eigen sales-team, of eerst de Nederlandse markt verdiepen. Beslissing valt eind Q1 2026.',
  questions: [
    { text: 'Hoe groot is de bestelbaar-adresseerbare cobot-markt voor mid-market maakbedrijven in DACH versus NL voor 2026-2028?', kind: 'decision' },
    { text: 'Welke 3-5 spelers domineren de DACH mid-market en wat is hun positionering versus de onze?', kind: 'exploration' },
    { text: 'Welk go-to-market model (direct sales / system integrators / hybrid) presteert het best in DACH voor onze prijsklasse?', kind: 'decision' },
  ],
  audience_description:
    'Familiale maakbedrijven, 50-500 medewerkers, jaaromzet €10-150M, met een interne operations- of plant manager als initiator en de CEO/eigenaar als beslisser. Sectoren: metaalverwerking, kunststof, voeding, farma-verpakking. Typische trigger: tekort aan operatoren + nieuwe productielijn.',
  competitors_list: ['Universal Robots', 'Doosan Robotics', 'Techman Robot', 'ABB GoFa', 'Franka Emika'],
  stakeholders_list: [
    { name: 'Tom Janssens', role: 'CEO & mede-oprichter', expectation: 'Heldere go/no-go op DACH met onderbouwde investeringscase.' },
    { name: 'Sophie Vandenberghe', role: 'COO', expectation: 'Realistisch beeld van operationele complexiteit van DACH-uitrol.' },
    { name: 'Marc De Wit', role: 'VP Sales', expectation: 'Inzicht in welk sales-model werkt en welke partners we nodig hebben.' },
  ],
  sensitivities_text:
    'Tom (CEO) is intern al voorstander van DACH — hij heeft daar zijn netwerk. De board wil eerst harde cijfers voor er groen licht komt. Niemand durft te challengen dat NL "afgevinkt" is, terwijl onze marktaandeel daar nog onder 4% ligt.',
  deadline: '2026-03-15',
  geo_scope: 'DACH (DE, AT, CH) en Nederland — vergelijkend',
  time_horizon: '24 maanden (2026-2027)',
  out_of_scope: 'Frankrijk, UK, Zuid-Europa. Geen technologische roadmap-analyse — focus op markt en GTM.',
  output_size: 'standard',
  output_form: 'notion',
  success_definition:
    'De board kan eind Q1 2026 een go/no-go beslissing nemen op DACH met heldere onderbouwing. Bij een go: we weten welk sales-model en welke 2-3 prioritaire sub-regio\'s. Bij een no-go: we hebben een concreet alternatief plan voor NL-verdieping.',
  materials_note: 'Geen extra materiaal voor deze demo-intake.',
};

// 4. Insert intake (status=draft = Concept)
const token = crypto.randomUUID().replace(/-/g, '').slice(0, 16);
const { data: intake, error: iErr } = await sbNestor
  .from('intakes')
  .insert({
    client_id: clientId,
    product_slug: 'pulse',
    template_id: (template as any).id,
    status: 'draft',
    title: 'DEMO — EU-expansie 2026 — DACH-verkenning',
    client_intake_token: token,
  })
  .select('id, client_intake_token, title, status')
  .single();

if (iErr) throw iErr;

// 5. Insert answers as rows in intake_answers
const intakeId = (intake as any).id;
const rows = Object.entries(answers).map(([field_key, value]) => ({
  intake_id: intakeId,
  field_key,
  value,
}));
const { error: aErr } = await sbNestor.from('intake_answers').upsert(rows, { onConflict: 'intake_id,field_key' });
if (aErr) throw aErr;
console.log(`Inserted ${rows.length} answer rows`);

console.log('\n✅ Demo intake aangemaakt');
console.log('  intake id   :', (intake as any).id);
console.log('  status      :', (intake as any).status);
console.log('  title       :', (intake as any).title);
console.log('  client link :', `/intake/${(intake as any).client_intake_token}`);
console.log('  admin link  :', `/admin/intakes/${(intake as any).id}`);
