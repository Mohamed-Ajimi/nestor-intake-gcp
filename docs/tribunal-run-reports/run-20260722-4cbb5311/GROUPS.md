# Groups & Claims Inventory — run 4cbb5311

One row per group-skeptic PASS (176 total; 163 single-claim + 13 multi-claim). Verdicts are the values the group-skeptic LLM emitted. Rows flagged **BUG:recon-as-str** had their reconciliation returned as a JSON string, so `_parse_group_verdict` crashed with `'str' object has no attribute 'get'` and the pipeline DISCARDED all of that group's verdicts (24 rows).

| # | Subject/entity | Property/attribute | #claims | web (search/fetch) | Claims & emitted verdicts |
|---|---|---|---|---|---|
| 1 | competitive fuel tracking | toepassingsgebied | 1 | 3s/1f | `refute` Competitive fuel tracking is van toepassing in alle EU-landen met prijstransparantie. |
| 2 | PriceCast | acquisition | 1 | 2s/0f | `support` De PriceCast module van a2i Systems is in 2024 geacquireerd door Dow Jones/OPIS. |
| 3 | luxemburg | uniforme_prijs | 1 | 2s/1f | `insufficient` Alle stations in Luxemburg hanteren dezelfde prijs. |
| 4 | ai-prijzen | winstverbetering | 1 | 3s/0f **BUG:recon-as-str -> verdicts DISCARDED** | `refute` De algehele winstverbetering door AI-prijzen is 10–20% van de totale winstgevendheid. |
| 5 | manual labeling | labor_cost | 1 | 3s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` De arbeidskost voor het handmatig vervangen van prijskaartjes bedraagt $32.760 per jaar, gebaseerd op een uurl |
| 6 | brandstofprijzen nederland | regulering | 1 | 2s/3f | `support` De Nederlandse markt kent vrije prijsvorming voor brandstof. |
| 7 | nederlandse brandstofmarkt | belemmeringen | 1 | 3s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `support` De Nederlandse brandstofmarkt wordt ontmoedigd door extreem hoge brandstofbelastingen en strenge milieu-compli |
| 8 | complexe ESL-varianten | pricing | 1 | 2s/0f | `support` Complexe ESL-varianten kunnen $50 of meer kosten. |
| 9 | brandstofprijzen belgië oostenrijk | prijsdaling_restrictie | 1 | 3s/2f | `refute` In België en Oostenrijk mogen brandstofprijzen alleen dalen ten opzichte van de maximumprijs. |
| 10 | ESL | implementation_cost | 1 | 2s/2f | `insufficient` Een complete end-to-end ESL-implementatie voor een groter, conventioneel filiaal kost circa $120.000. |
| 11 | API-feeds | compliance_requirement | 1 | 4s/2f | `insufficient` API-feeds zijn noodzakelijke compliance-voorwaarden voor dynamic pricing. |
| 12 | lukoil implementatiemodel fase 3 | omvang | 1 | 3s/0f | `insufficient` Fase 3 omvat de ontwikkeling van asymmetrische en zeer voorspellende AI-modellen voor de Duitse markt. |
| 13 | Kalibrate | data_privacy | 1 | 2s/2f | `support` Kalibrate-modellen worden strikt getraind op afgeschermde data van de licentienemer om onafhankelijkheid te bo |
| 14 | dynamic pricing | suitability | 2 | 3s/2f | `insufficient` Investering in dynamic pricing is inadequaat voor volledig onbemande pompen.<br>`support` Investering in dynamic pricing is inadequaat voor extreem rurale monopolie-locaties. |
| 15 | germany | regulatory_changes | 1 | 2s/2f | `support` Het Duitse regelgevingskader is in april 2026 drastisch gewijzigd. |
| 16 | dynamic pricing | adoption | 3 | 5s/1f | `insufficient` Toonaangevende retailers zoals OK Benzin, team energie, TotalEnergies, Shell, Preem, Lekkerland en onafhankeli<br>`insufficient` De adoptie van dynamische beprijzing is versneld door gespecialiseerde oplossingen zoals EdgePetrol (Groot-Bri<br>`refute` De adoptie van dynamic pricing in de Europese brandstofretail was initieel het domein van grote multinationale |
| 17 | eu fuel retail | market_size | 1 | 2s/2f | `support` De marktomvang van de EU fuel retail bedroeg €324,2 miljard in 2026. |
| 18 | Kalibrate en EdgePetrol | impact | 1 | 4s/0f | `insufficient` Consumentenrechtadvocaten in Californië bepleiten dat Kalibrate en EdgePetrol systemen lokale benzineprijzen t |
| 19 | OK Benzin | product_scope | 1 | 4s/2f | `insufficient` OK Benzin past dynamic pricing toe op Euro 95, Diesel en convenience-artikelen. |
| 20 | Bellinger | product_scope | 1 | 5s/1f | `insufficient` Bellinger past dynamic pricing uitsluitend toe op brandstof. |
| 21 | lukoil | verkoop_internationale_operaties | 1 | 2s/2f | `refute` LUKOIL verkocht zijn internationale operaties aan Gunvor Group na nieuwe Amerikaanse sancties. |
| 22 | brandstofprijzen belgië oostenrijk | prijsstijging_frequentie | 1 | 3s/1f | `refute` In België en Oostenrijk mogen brandstofprijzen slechts één keer per dag stijgen. |
| 23 | algoritmische stilzwijgende coördinatie | margin_impact | 1 | 3s/1f | `insufficient` De grootste margesprongen komen voort uit Algoritmische stilzwijgende coördinatie (tacit collusion). |
| 24 | lukoil benelux | overname | 1 | 2s/2f **BUG:recon-as-str -> verdicts DISCARDED** | `support` LUKOIL BeNeLux werd eind januari 2026 overgenomen door Carlyle (VS), waarbij de naam intact bleef. |
| 25 | lukoil implementatiemodel fase 2 | hardware_behoefte | 1 | 3s/0f | `insufficient` Er is nagenoeg geen front-end luifel-hardware nodig in Fase 2, zolang luifels reeds digitaal aangestuurd worde |
| 26 | PCI DSS | definition | 1 | 2s/1f | `support` PCI DSS-compliance is een internationale, verplichte veiligheidsnorm gericht op het beschermen van betalingsge |
| 27 | lukoil implementatiemodel fase 2 | tijdlijn | 1 | 3s/0f | `insufficient` Fase 2 van het LUKOIL implementatiemodel is de Brandstof Algoritme Pilot in de BeNeLux (Q1-Q2 2027), binnen ge |
| 28 | BDI | definition | 1 | 1s/0f | `refute` BDI staat voor Belief-Desire-Intention en is een neuraal logica-model voor software-agenten. |
| 29 | OK Benzin | pricing_frequency | 2 | 4s/1f | `insufficient` OK Benzin past prijzen meerdere malen per dag aan de pomp aan, reagerend op ochtend- en middagpatronen.<br>`insufficient` OK Benzin past prijzen realtime aan in de shop. |
| 30 | Preem / ST1 | data_inputs | 1 | 3s/1f | `insufficient` Preem / ST1's data-inputs omvatten vraagverschuivingen ten opzichte van lokale concurrentie in dunbevolktere g |
| 31 | brandstofprijzen duitsland | wekelijks_patroon | 2 | 3s/3f | `refute` De brandstofprijzen in Duitsland zijn het laagst op zondag.<br>`refute` De brandstofprijzen in Duitsland zijn het hoogst op donderdag. |
| 32 | lukoil implementatiemodel fase 1 | installatietijd | 1 | 3s/0f | `insufficient` De roll-out van hardware-installatie duurt gemiddeld 1 dag per station. |
| 33 | a2i Systems | architecture | 1 | 3s/2f | `insufficient` Geavanceerde engines (zoals a2i oplossingen) opereren op een specifieke BDI-architectuur. |
| 34 | Preem / ST1 | technology_use | 1 | 2s/2f | `support` Preem / ST1 in Scandinavië gebruikt Kalibrate AI software. |
| 35 | brandstofprijzen luxemburg | maximumprijs | 1 | 3s/4f | `insufficient` In Luxemburg lag de maximumprijs in 2025 op €1.473 per liter voor Euro 95. |
| 36 | individueel station | margin_impact | 1 | 4s/0f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Een individueel station kan gemiddeld 1 tot 2 pence per liter (ppl) aan marge vasthouden door niet blindelings |
| 37 | stilzwijgende coördinatie | margin_impact | 2 | 2s/2f | `refute` In Duitse en Deense lokale gebieden met meerdere stations die dit AI-model gebruiken, leidt stilzwijgende coör<br>`insufficient` De algemene margeverbetering door stilzwijgende coördinatie is 28% tot 38%. |
| 38 | lukoil implementatiemodel fase 2 | omvang | 1 | 3s/0f | `insufficient` Fase 2 omvat de selectie van een SaaS provider zoals EdgePetrol, a2i of Kalibrate. |
| 39 | nederlandse brandstofmarkt | software_operatie | 1 | 4s/2f | `insufficient` De afwezigheid van federale plafonds in Nederland stelt software in staat om volledig bi-directioneel, opwaart |
| 40 | european fuel retail market | state | 1 | 2s/2f | `support` De Europese brandstofretailmarkt bevindt zich in een kritische transitiefase. |
| 41 | brandstofprijzen belgië oostenrijk | prijsstijging_tijd | 1 | 3s/2f **BUG:recon-as-str -> verdicts DISCARDED** | `refute` In België en Oostenrijk vindt de prijsstijging meestal plaats om 11.00 uur 's ochtends. |
| 42 | lukoil implementatiemodel fase 1 | omvang | 1 | 3s/1f | `insufficient` Fase 1 omvat de implementatie van het hardware-pakket (Electronic Shelf Labels van $5-$20) in de convenience s |
| 43 | shop | manual_labeling_time | 1 | 2s/1f | `refute` Een middelgrote shop met circa 10.000 SKU's besteedt wekelijks zo'n 40 uur aan het handmatig vervangen van pap |
| 44 | Preem / ST1 | product_scope | 1 | 4s/1f | `support` Preem / ST1 past dynamic pricing toe op brandstof. |
| 45 | dynamic pricing | accessibility | 1 | 2s/2f | `support` Dynamic pricing is toegankelijk geworden door de proliferatie van gespecialiseerde Software-as-a-Service (SaaS |
| 46 | germany | esl_adoption | 1 | 2s/1f | `support` In Duitsland zien we een versnelde adoptie van Electronic Shelf Labels (ESL) voor shopproducten. |
| 47 | lukoil implementatiemodel fase 1 | prioriteit | 1 | 4s/0f | `insufficient` De prioriteit van Fase 1 is snel en meetbaar rendement ter grootte van ~$45.000 besparing per jaar, per filiaa |
| 48 | EdgePetrol | data_model | 1 | 2s/0f | `support` Het datamodel van EdgePetrol past FIFO (First-In-First-Out) toe om de 'live weighted & blended margin' accuraa |
| 49 | brandstofprijzen belgië | formule | 1 | 2s/1f | `support` De Belgische formule voor maximumprijzen is opgebouwd uit internationale raffinageprijzen (Rotterdam), accijnz |
| 50 | brandstofprijzen belgië luxemburg | dynamic_pricing | 1 | 3s/1f | `support` Binnen de maximumprijs 'ceiling' in België en Luxemburg is neerwaartse dynamic pricing (dynamisch discounting) |
| 51 | manual labeling | material_cost | 1 | 4s/1f | `insufficient` Er zijn circa $5.000 aan inkt- en papierkosten voor prijskaartjes per jaar. |
| 52 | dg energie | publicatie_maximumprijs | 1 | 2s/1f | `support` De DG Energie publiceert dagelijks de officiële maximumprijs in België. |
| 53 | intraday fuel pricing | toepassingsgebied | 1 | 5s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Intraday fuel pricing is van toepassing in Duitsland (vóór 2026), het VK en Scandinavië. |
| 54 | Shell | product_scope | 1 | 3s/2f | `refute` Shell's AI-optimalisatie is exclusief voor brandstof. |
| 55 | brandstofprijzen belgië oostenrijk | prijsstijging_restrictie | 1 | 2s/1f | `insufficient` In België en Oostenrijk mogen brandstofprijzen niet stijgen boven de maximumprijs. |
| 56 | brandstofprijzen europa | frequentie_wijziging | 1 | 2s/1f | `support` De brandstofprijzen in Europa kunnen meerdere keren per dag veranderen. |
| 57 | algoritmische prijssoftware | objective | 1 | 3s/2f | `insufficient` Algoritmische prijssoftware heeft als primaire doelstelling het balanceren van volume en marge, en het creëren |
| 58 | lukoil implementatiemodel fase 3 | infrastructuur | 1 | 2s/1f | `support` De technologische infrastructuur voor Fase 3 omvat directe en wettelijk vereiste data(API)-koppelingen met de  |
| 59 | store automation | operational_efficiency | 1 | 3s/2f | `support` Winkelautomatisering via Electronic Shelf Labels (ESL) levert een directe operationele tijdsbesparing op van c |
| 60 | luxemburg | regulatoir_risico_uniforme_prijs | 1 | 2s/3f | `support` In Luxemburg is er een kritisch regulatoir risico door een uniforme prijs voor alle stations en een vaste maxi |
| 61 | lukoil duitsland | concurrentievoordeel | 1 | 5s/0f | `insufficient` LUKOIL kan met haar geprepareerde AI direct de vruchten plukken van de verlaagde mededingingsdruk op prijzensl |
| 62 | lukoil belgië luxemburg | prijslimiet | 1 | 2s/3f | `support` LUKOIL mag de wettelijke maximumprijs in België en Luxemburg op geen enkel moment van de dag overschrijden. |
| 63 | Lekkerland | data_inputs | 1 | 4s/1f | `insufficient` Lekkerland's data-inputs omvatten analyse van prijsgevoeligheid versus gemaksgevoeligheid. |
| 64 | Preem / ST1 | pricing_frequency | 1 | 2s/2f | `insufficient` Preem / ST1's frequentie van prijsaanpassingen is algoritmisch bepaald per fluctuatie. |
| 65 | Lekkerland | product_focus | 1 | 3s/0f | `support` Lekkerland focust op hogere marge 'food-to-go' en convenience producten. |
| 66 | lukoil benelux | overname_reden | 1 | 2s/0f | `support` De Carlyle-acquisitie vond plaats na de dreiging van Amerikaanse sancties tegen het Russische moederbedrijf. |
| 67 | TotalEnergies | technology_use | 1 | 5s/1f | `insufficient` TotalEnergies gebruikt eigen in-house AI platformen gecombineerd met modules van marktleider Kalibrate. |
| 68 | lukoil benelux | status_rapport | 1 | 4s/1f | `refute` Dit rapport behandelt LUKOIL BeNeLux als een zelfstandige going concern onder Carlyle-eigendom. |
| 69 | EdgePetrol | data_integration | 1 | 2s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `support` EdgePetrol integreert direct met POS (Point of Sale), ATG's (Automatic Tank Gauges) en leest real-time de CMA- |
| 70 | API | definition | 1 | 2s/0f | `refute` API staat voor Application Programming Interface, een digitale softwarebrug die wetgevende servers direct, rea |
| 71 | brandstofprijzen duitsland | prijsverhoging_restrictie | 1 | 2s/0f | `refute` Het AI-systeem mag na 12:00 uur de prijs absoluut niet meer verhogen in Duitsland. |
| 72 | fuel measures package 2026 | onderdeel | 1 | 2s/1f | `support` Deze Duitse regulering is onderdeel van het "Fuel Measures Package 2026". |
| 73 | lukoil implementatiemodel fase 1 | infrastructuur | 1 | 5s/0f **BUG:recon-as-str -> verdicts DISCARDED** | `support` De technologische infrastructuur voor Fase 1 omvat POS-integratie (back-end SaaS, kosten $150-$400/maand), ins |
| 74 | PriceCast | availability | 1 | 3s/1f | `support` De PriceCast module is actief op meer dan 12.500 locaties wereldwijd. |
| 75 | Kalibrate | data_ownership | 1 | 2s/2f | `support` Kalibrate benadrukt dat elke retailer 100% eigenaarschap behoudt over hun macro- en micro-datastrategieën. |
| 76 | onbemande pompen | consumer_behavior | 1 | 3s/1f | `refute` Bij onbemande pompen reageren automobilisten strikt elastisch op brandstofprijs als er geen winkel in de nabij |
| 77 | team energie | pricing_frequency | 1 | 5s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` team energie (HEM) past prijzen realtime en geautomatiseerd aan op basis van dagdeel-regels. |
| 78 | gateways | pricing | 1 | 2s/0f | `insufficient` Gateways voor datacommunicatie naar de ESL-bordjes kosten circa $200 tot $600 per stuk. |
| 79 | lukoil implementatiemodel fase 1 | exclusiecriterium | 1 | 3s/0f | `insufficient` Exclusie-criterium voor Fase 1: sla onbemande of piepkleine rurale shops over. |
| 80 | lukoil implementatiemodel fase 2 | roi | 1 | 4s/1f | `insufficient` De verwachte ROI voor Fase 2 is een historisch bewezen realisatie van 0,8 tot maximaal 2-3 cent per liter nett |
| 81 | brandstofprijzen belgië oostenrijk | prijsdaling_frequentie | 1 | 2s/2f | `support` In België en Oostenrijk kunnen brandstofprijzen gedurende de dag onbeperkt dalen. |
| 82 | Kraftstoffanpassungsgesetz (KPAnG) | margin_impact | 1 | 2s/2f | `support` De gemiddelde marges in Duitsland stegen op korte termijn direct met 5 tot 6 cent per liter na de invoering va |
| 83 | dynamic pricing | margin_impact | 1 | 5s/0f | `insufficient` De pilot van *team energie* (HEM) wees uit dat marges aanzienlijk groeien door na 22:00 uur een 'night-time ma |
| 84 | TotalEnergies | pricing_strategy | 1 | 2s/2f **BUG:recon-as-str -> verdicts DISCARDED** | `support` TotalEnergies optimaliseert prijzen dynamisch, afhankelijk van lokale wetgeving. |
| 85 | ESL-software | backend_license_cost | 1 | 2s/3f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Een eenmalige backend-licentie voor ESL-software ligt tussen de $3.000 en $8.000. |
| 86 | Bellinger | technology_use | 1 | 5s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Bellinger (onafhankelijk JET dealer, VK) gebruikt EdgePetrol, de marktleider in het VK met 30 van de top 50 on |
| 87 | OK Benzin | data_inputs | 1 | 3s/2f | `insufficient` OK Benzin's algoritmes zijn getraind op historische afzet, loyaliteitsdata en directe prijzen van nabije concu |
| 88 | ESL | error_reduction_impact | 1 | 3s/1f | `insufficient` ESL-implementatie leidt tot een directe structurele eliminatie van foutgerelateerde derving, geschat op $8.000 |
| 89 | belgië | regulatoir_risico_maximumprijs | 1 | 2s/2f | `support` In België is er een kritisch regulatoir risico door een dagelijkse maximumprijs via een overheidsformule. |
| 90 | Duitse brandstofmarkt | market_condition | 1 | 2s/2f | `refute` De Duitse brandstofmarkt kende sinds de oprichting van de federale database *Markttransparenzstelle für Krafts |
| 91 | intraday fuel pricing | definitie | 1 | 3s/1f | `support` Intraday fuel pricing omvat meerdere prijswijzigingen per dag op pompprijzen. |
| 92 | rurale monopolie-locaties | pricing_strategy | 1 | 4s/3f | `insufficient` Op rurale monopolie-locaties functioneren lokaal gepositioneerde maximumprijzen reeds optimaal zonder software |
| 93 | EdgePetrol | technology_use | 1 | 4s/3f **BUG:recon-as-str -> verdicts DISCARDED** | `support` Bedrijven zoals EdgePetrol opereren via veilige SD-WAN verbindingen. |
| 94 | lukoil implementatiemodel fase 3 | tijdlijn | 1 | 4s/0f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Fase 3 van het LUKOIL implementatiemodel is de voorbereiding op de Germany Entry (Vóór Q2 2027), gericht op co |
| 95 | brandstofprijzen duitsland | regulering | 1 | 2s/1f | `refute` In Duitsland is er geen wettelijke regulering van de brandstofprijzen. |
| 96 | basic monochrome ESL-labels | pricing | 1 | 2s/0f | `support` Zeer basic monochrome ESL-labels zijn verkrijgbaar vanaf $5. |
| 97 | brandstofprijzen duitsland | frequentie_wijziging | 1 | 2s/2f | `refute` In Duitsland kunnen brandstofprijzen tot 8 keer per dag veranderen. |
| 98 | fuel sales | purpose | 1 | 3s/0f | `insufficient` De verkoop van brandstof fungeert als een marginaal 'loss leader'-mechanisme om klanten de winkel in te lokken |
| 99 | ESL-software | saas_fee | 1 | 2s/2f | `support` SaaS-fee kosten voor ESL-software variëren tussen $150 en $400 per winkel, per maand. |
| 100 | team energie | data_inputs | 1 | 6s/1f | `insufficient` team energie (HEM) gebruikt tijdstip (avonduren t.o.v. supermarktopeningen), actuele weersomstandigheden en fy |
| 101 | rapport | onderzoeksscope | 1 | 2s/0f | `insufficient` De onderzoeksscope omvat de BeNeLux (kern), Duitsland (expansiecontext) en selectieve Europese precedenten. |
| 102 | team energie | technology_use | 1 | 2s/2f **BUG:recon-as-str -> verdicts DISCARDED** | `support` team energie (HEM) in Duitsland gebruikt Panasonic en Delfi ESL, verbonden met Huth kassa- en ERP-systemen. |
| 103 | ai-driven dynamic pricing | capability | 1 | 2s/2f | `refute` AI-gedreven dynamic pricing op brandstof mitigeert prijsoorlogen. |
| 104 | lukoil benelux | overname_start | 1 | 2s/1f | `support` De saga van de overname van LUKOIL BeNeLux begon in oktober 2025 met nieuwe Amerikaanse sancties tegen Rusland |
| 105 | lukoil implementatiemodel fase 2 | prioriteit | 1 | 4s/0f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` De prioriteit van Fase 2 is optimalisatie van discounting onder wettelijke plafonds in België/Luxemburg, en vo |
| 106 | Kraftstoffanpassungsgesetz (KPAnG) | effective_date | 1 | 2s/2f | `support` Op 1 april 2026 is de *Kraftstoffanpassungsgesetz (KPAnG)* in Duitsland in werking getreden. |
| 107 | store automation | investment_cost | 1 | 3s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` De investering voor winkelautomatisering bedraagt eenmalig circa $120.000 voor een middelgroot filiaal. |
| 108 | lukoil implementatiemodel fase 1 | roi | 1 | 4s/0f | `insufficient` De verwachte ROI voor Fase 1 is een terugverdientijd na 2,6 jaar door bespaarde uren, plus verhoogde brutowins |
| 109 | Shell | data_inputs | 1 | 5s/0f | `insufficient` Shell's data-inputs omvatten verkeersstromen, macro-economische trends en inkoopprijsfluctuaties. |
| 110 | Shell | pricing_frequency | 1 | 4s/2f | `insufficient` Shell past prijzen realtime of in gedefinieerde batches aan, aangestuurd via gecentraliseerde Cloud- of iPad-a |
| 111 | fuel algorithms | capability | 1 | 2s/1f | `support` Brandstofalgoritmes gebruiken realtime POS-data en weers-/concurrentie-inputs voor continue aanpassingen. |
| 112 | ESL | pos_integration_cost | 1 | 2s/3f | `support` De POS-integratie voor ESL vereist eenmalig circa $2.000 tot soms wel $15.000. |
| 113 | belgium and luxembourg | fuel_pricing_regulation | 2 | 2s/2f | `support` België en Luxemburg hanteren een strikte wettelijke overheidscap, waardoor alleen geoptimaliseerde discounting<br>`support` In België en Luxemburg dicteert een stringente overheidscap de maximale brandstofprijzen. |
| 114 | store automation | payback_period | 1 | 4s/0f | `insufficient` De terugverdientijd voor winkelautomatisering is ongeveer 2,6 jaar. |
| 115 | Shell | capability | 1 | 3s/1f | `insufficient` Shell gebruikt 'PriceLens' voor visuele concurrentie-tracking. |
| 116 | LUKOIL BeNeLux | profitability | 1 | 4s/1f | `insufficient` De schaalbaarheid van prijsinnovaties in het shop-model en de brandstofverkoop is een fundamentele pijler voor |
| 117 | lukoil implementatiemodel fase 2 | infrastructuur | 1 | 4s/0f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` De technologische infrastructuur voor Fase 2 omvat de implementatie van gesloten SD-WAN / Mako VPN's om kassa' |
| 118 | ESL | labor_savings_impact | 1 | 2s/3f | `insufficient` ESL-implementatie leidt tot arbeidsbesparingen van 30 tot 35 manuren per week ($32.760 jaarlijks). |
| 119 | Kraftstoffanpassungsgesetz (KPAnG) | pricing_rules | 2 | 2s/3f | `support` Tankstations in Duitsland mogen hun brandstofprijzen slechts één keer per dag verhogen, op exact 12:00 uur 's <br>`support` Prijsverlagingen in Duitsland blijven te allen tijde, onbeperkt toegestaan gedurende de rest van de dag. |
| 120 | TotalEnergies | product_scope | 1 | 3s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` TotalEnergies past dynamic pricing toe op brandstoffen, convenience store-assortiment en EV-laadinfrastructuur |
| 121 | Edgeworth Price Cycles | impact | 1 | 4s/2f | `insufficient` De 'Edgeworth Price Cycles' dwongen automatische algoritmes om prijzen tot wel 20 keer per dag met micro-cente |
| 122 | EdgePetrol | capability | 3 | 2s/1f | `support` EdgePetrol optimaliseert specifiek op 'live weighted & blended margin'.<br>`support` Het EdgePetrol algoritme berekent de daadwerkelijke netto-marge door creditcardkosten direct van de winst af t<br>`support` EdgePetrol biedt een live continue weergave van marges voor de filiaalmanager. |
| 123 | duitse regelgeving | predictief_model | 1 | 3s/1f | `refute` De Duitse regelgeving eist een zwaar predictief model dat berekent hoe hoog de eenmalige initiële pieksprong o |
| 124 | ESL | training_cost | 1 | 3s/1f | `refute` Voor omschakeling naar ESL dient men rekening te houden met circa 10 tot 20 betaalde trainingsuren per persone |
| 125 | algoritmes | capability | 1 | 2s/0f | `support` Algoritmes houden prijzen hoog en stabiel zonder illegale menselijke communicatie bij stilzwijgende coördinati |
| 126 | algoritmische stilzwijgende coördinatie | definition | 1 | 2s/3f | `refute` Algoritmische stilzwijgende coördinatie is een niet-gereguleerde, spontane marktsituatie waarbij onafhankelijk |
| 127 | rapport | onderzoeksperiode | 1 | 1s/0f | `insufficient` De onderzochte periode voor dit rapport was 2023–2026. |
| 128 | dynamic pricing | operational_impact | 1 | 4s/1f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Dynamic pricing in België en Luxemburg vertaalt zich operationeel naar dynamisch discounting onder de wettelij |
| 129 | marktmarges duitsland | stijging | 1 | 2s/2f | `support` Marktmarges in Duitsland zijn dankzij KPAnG direct gestegen. |
| 130 | bundeskartellamt | toezicht | 1 | 2s/0f | `support` De Duitse mededingingsautoriteit, het Bundeskartellamt, heeft de brandstofprijzen in de gaten gehouden. |
| 131 | gateway | range | 1 | 4s/0f | `insufficient` Elke gateway heeft een bereik van circa 15 meter. |
| 132 | SD-WAN | definition | 1 | 2s/0f | `refute` SD-WAN is een virtuele netwerkarchitectuur waarbij centraal beheer via de cloud de dataversleuteling en router |
| 133 | electronic shelf labels | capability | 1 | 3s/0f | `support` In de shop (FMCG) maken IoT-gedreven Electronic Shelf Labels (ESL) asymmetrische margestrategieën gedurende de |
| 134 | Kraftstoffanpassungsgesetz (KPAnG) | penalties | 1 | 2s/0f | `support` Overtredingen van de KPAnG kunnen resulteren in bestuursrechtelijke boetes tot 100.000 euro. |
| 135 | ai optimization | margin_improvement | 1 | 2s/1f | `support` AI-optimalisatie van brandstofmarges levert verbeteringen op van 9% tot 38% (0,8 tot 3,2 cent per liter). |
| 136 | scandinavian market | dynamic_pricing_adoption | 1 | 3s/3f | `insufficient` De Scandinavische markt, met OK Benzin en Preem, was een vroege pionier in dynamic pricing om marge-erosie te  |
| 137 | brandstofprijzen duitsland | dagelijks_patroon | 7 | 2s/2f | `support` De brandstofprijzen in Duitsland zijn het hoogst in de ochtend en dalen gedurende de dag.<br>`support` De brandstofprijzen in Duitsland zijn het laagst tussen 18.00 en 22.00 uur.<br>`support` De brandstofprijzen in Duitsland stijgen 's nachts.<br>`support` De brandstofprijzen in Duitsland zijn het hoogst in de ochtend.<br>`support` De brandstofprijzen in Duitsland zijn het laagst in de avond.<br>`support` De brandstofprijzen in Duitsland zijn het hoogst tussen 5.00 en 8.00 uur.<br>`support` De brandstofprijzen in Duitsland zijn het hoogst tussen 5.00 en 8.0 |
| 138 | SD-WAN | compliance_requirement | 1 | 2s/2f | `refute` SD-WAN is strikt noodzakelijk om te voldoen aan PCI DSS-compliance. |
| 139 | lukoil implementatiemodel fase 3 | prioriteit | 1 | 4s/0f | `insufficient` De prioriteit van Fase 3 is de aanpassing van de in Fase 2 geconfigureerde pricing engine aan de unieke KPAnG- |
| 140 | bundeskartellamt | conclusie_prijsafspraken | 1 | 2s/2f | `insufficient` Het Bundeskartellamt heeft geconcludeerd dat er geen sprake is van prijsafspraken tussen de grote oliemaatscha |
| 141 | grotere ESL-modellen | pricing | 1 | 2s/2f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Grotere 7.5-inch ESL-modellen of freezer-varianten kosten $12 tot $25 per stuk. |
| 142 | rapport | publicatiedatum | 1 | 1s/0f | `insufficient` De datum van het rapport is juli 2026. |
| 143 | store automation | capability | 1 | 2s/2f | `support` Winkelautomatisering via ESL faciliteert flexibele margestrategieën in de avonduren. |
| 144 | europese retailers | adoptie_dynamic_pricing | 1 | 3s/2f | `support` 61% van de Europese retailers heeft enige vorm van dynamic pricing geadopteerd, voornamelijk rule-based en nie |
| 145 | team energie | product_focus | 1 | 2s/1f | `refute` team energie (HEM) focust volledig op FMCG (Fast-Moving Consumer Goods). |
| 146 | Kalibrate | impact | 1 | 4s/2f | `insufficient` Kalibrate claimt gemiddelde volumestijgingen van 0,1% bij hun optimalisatie op 1.250 netwerken. |
| 147 | duitse brandstofmarkt | coördinatie | 1 | 5s/3f | `insufficient` De stilzwijgende coördinatie is groter geworden in Duitsland nu niemand nog willekeurig prijzen kan stuwen ged |
| 148 | dynamische brandstofprijzen | margevoordeel | 2 | 4s/2f | `insufficient` Het potentiële margevoordeel van dynamische brandstofprijzen is €0,02–€0,04 per liter netto voordeel per gallo<br>`insufficient` Het potentiële margevoordeel van dynamische brandstofprijzen is $50.000–$100.000 per station per jaar (VS-benc |
| 149 | OK Benzin | technology_use | 1 | 5s/2f | `insufficient` OK Benzin in Denemarken gebruikt a2i Systems (PriceCast) en Delfi ESL. |
| 150 | static pricing models | effectiveness | 1 | 3s/2f | `support` Traditionele, statische prijsmodellen zijn niet langer toereikend door volatiliteit in inkoopprijzen, aangesch |
| 151 | eu fuel retail | market_growth | 1 | 2s/2f | `insufficient` De marktgroei van de EU fuel retail is +2,6% jaar-op-jaar. |
| 152 | LUKOIL BeNeLux | operational_necessity | 1 | 5s/2f | `insufficient` De integratie van dynamic pricing technologieën is een operationele noodzaak geworden voor LUKOIL BeNeLux. |
| 153 | duitsland | regulatoir_risico_prijsverhoging | 1 | 2s/0f | `support` In Duitsland is een kritisch regulatoir risico dat prijsverhogingen maximaal 1 keer per dag (om 12:00 uur) zij |
| 154 | Shell | technology_use | 1 | 5s/1f | `insufficient` Shell gebruikt algoritmische prijssoftware met diepe integraties van Kalibrate Location Intelligence & Pricing |
| 155 | research report | scope | 1 | 3s/0f | `refute` Dit onderzoeksrapport biedt een kwantitatieve analyse van de huidige staat van dynamic pricing binnen de Europ |
| 156 | BDI | capability | 1 | 3s/0f | `support` BDI-architectuur acteert proactief en streeft zelfstandig lange termijn volumebalans na. |
| 157 | kleine e-ink labels | pricing | 1 | 2s/0f | `refute` Standaard kleine e-ink labels (2.13 inch) kosten $8 tot $12 per stuk. |
| 158 | Lekkerland | pricing_model | 1 | 2s/3f | `support` Lekkerland (Frischwerk-concept, Duitsland) gebruikt een eigen dynamisch prijsmodel op de shopvloer, niet verbo |
| 159 | lukoil implementatiemodel fase 1 | tijdlijn | 2 | 4s/0f | `insufficient` Fase 1 van het LUKOIL implementatiemodel is winkelautomatisering (Q3-Q4 2026), gericht op efficiëntie.<br>`insufficient` De tijdlijn voor Fase 1 omvat pilots op 5 bemande snelweg/stedelijke locaties met veel SKU's gedurende 1 maand |
| 160 | TotalEnergies | data_inputs | 1 | 5s/0f | `insufficient` TotalEnergies' systemen scannen naar micro-marktevaluaties, lokale vraagelasticiteit en de posities van naburi |
| 161 | LUKOIL | recommended_path | 3 | 5s/0f | `insufficient` Het aanbevolen pad voor LUKOIL is drieledig: starten met ESL in laag-risico shop-omgevingen in Q3 2026.<br>`insufficient` Het aanbevolen pad voor LUKOIL omvat algoritmische pilot-sturing onder de vaste prijsplafonds van de BeNeLux.<br>`insufficient` Het aanbevolen pad voor LUKOIL heeft als einddoel een voor de 12:00-uur-regulatie geoptimaliseerd model ten be |
| 162 | brandstofprijzen belgië oostenrijk | regulering | 1 | 3s/2f | `insufficient` In België en Oostenrijk zijn de brandstofprijzen wettelijk gereguleerd. |
| 163 | dynamische prijzen europa | adoptie | 1 | 4s/1f | `refute` Dynamische prijzen worden gebruikt door 90% van de tankstations in Europa. |
| 164 | fuel retailers | net_margins | 1 | 2s/2f | `insufficient` Nettomarges op brandstof voor retailers wereldwijd liggen in reguliere marktomstandigheden op slechts circa 2  |
| 165 | ai-driven dynamic pricing | margin_improvement | 1 | 3s/2f | `support` Implementatie van AI-gedreven dynamic pricing op brandstof leidt tot bewezen margeverbeteringen van 9% tot 38% |
| 166 | competitive fuel tracking | definitie | 1 | 3s/0f | `support` Competitive fuel tracking omvat real-time reactie op concurrentieprijzen via transparantiesystemen. |
| 167 | distributors | profit_margins | 1 | 2s/1f | `support` Distributeurs draaien op slechts 3 tot 4 dollarcent per gallon winst. |
| 168 | bundeskartellamt | conclusie_marktpositie | 1 | 4s/2f | `refute` Het Bundeskartellamt heeft geconcludeerd dat er geen sprake is van misbruik van een dominante marktpositie. |
| 169 | EdgePetrol | impact | 1 | 4s/2f | `insufficient` Software zoals EdgePetrol toont bij zijn Britse klanten (waaronder Bellinger) een algemene winsttoename van 18 |
| 170 | LUKOIL BeNeLux | strategic_horizon | 1 | 4s/1f | `insufficient` LUKOIL BeNeLux heeft een strategische horizon gericht op een mogelijke marktbetreding in Duitsland in 2027. |
| 171 | fuel margins | vulnerability | 1 | 4s/0f | `support` Een kleine neerwaartse correctie van de concurrent vernietigt onmiddellijk de minimale brandstofmarges. |
| 172 | germany | fuel_pricing_regulation | 3 | 3s/1f | `support` Duitsland heeft per april 2026 de KPAnG geactiveerd, die maximaal één prijsstijging per dag stipt om 12:00 uur<br>`support` Prijsverhogingen voor brandstof in Duitsland zijn wettelijk beperkt tot maximaal één keer per dag (om 12:00 uu<br>`insufficient` De Duitse regelgeving dwingt traditionele hoogfrequente prijsalgoritmes tot nieuwe, asymmetrische optimalisati |
| 173 | store automation | cost_savings | 1 | 3s/1f | `insufficient` Winkelautomatisering leidt tot $45.760 aan bespaarde manuren en foutreductie per jaar. |
| 174 | brandstofprijzen belgië luxemburg | regulering | 1 | 2s/2f | `insufficient` België en Luxemburg berekenen elke werkdag een officiële, wettelijke maximumprijs voor brandstof. |
| 175 | Lekkerland | pricing_frequency | 1 | 4s/3f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` Lekkerland past prijzen aan in vaste tijdsvensters, hoofdzakelijk 's avonds en 's nachts. |
| 176 | ai-prijzen | winstverbetering_bron | 1 | 2s/2f **BUG:recon-as-str -> verdicts DISCARDED** | `insufficient` De winstverbetering van 10-20% is het resultaat van gecombineerde brandstof- en winkel-AI-implementaties. |