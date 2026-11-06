# Sources revision — 2026-11-05

Owner's request (2026-11-05): many sources are blocked; replace them with new ones, with priority on Europe, China,
Kazakhstan/CIS, the Middle East, Asia and America. This revision reads robots.txt and the terms of every new site
and records the evidence in `backend/config/registry_seed_survey.yaml` (`survey: revision_2026_11_05`). It also
extends the deny-list and adds favourites in `backend/config/sources.yaml`. No application code was changed.

The hard rules still apply (constitution VIII, XII):

- No classifieds. A site with a listings section is used only on its editorial paths, and the listings path is
  deny-listed.
- robots.txt is respected per path.
- A terms clause that forbids automated access, scraping or extraction gives the verdict `tos_forbids`, and the
  clause is quoted.
- No anti-bot circumvention. A 403 or a bot wall to our UA gives `blocked_robots`.
- No JS-only scraping.

Prices outside Europe are recorded with their kinds but carry the note "Non-European market". Reports do not use
them today (spec 009 FR-009).

Method: every new domain's robots.txt was read with our UA (`AutoMindResearchBot/0.2`). Its terms or legal page was
read and searched for scraping, crawling, robot, extraction and TDM wording in the site's language. The sample URL
was fetched with our UA and returned 200 on 2026-11-05. There were 3–5 requests per site.

## 1. What was blocked (the 198 entries of the 009 survey)

The 009 survey had 111 non-candidate entries: 45 classifieds, 22 tos_forbids, 12 blocked_robots, 12 paywall,
12 js_only and 8 dead. The table below counts these entries by kind and by market.

| Kind | Blocked entries | Main blocked markets | Candidates before | New candidates (of them in Europe) |
|---|---|---|---|---|
| used_price | 60 | GB 14, ES 7, IT 5, IE 4, NL 3, FR 3 | 3 | 2 (0) |
| specs | 32 | GB 11, ES 3, CN 3, RU 2, IT 2 | 41 | 47 (28) |
| new_price | 19 | GB 8, IT 2, ES 2, CN 2 | 19 | 31 (18) |
| owner_reviews | 18 | GB 6, RU 3, NL 2, CN 2 | 21 | 11 (5) |
| measured | 18 | GB 4, ES 2, RU 2, IT 2 | 26 | 15 (9) |
| consumption_real | 15 | GB 6, RU 2 | 22 | 15 (9) |
| reliability | 14 | GB 4, US 3, RU 2, FR 2, IE 2 | 30 | 4 (3) |
| residual_value | 10 | GB 4, EU 2, FR, RU, DE, ES | 8 | 1 (0) |
| used_issues | 9 | RU 3, GB 3, SE 2 | 21 | 6 (4) |
| maintenance | 7 | GB 3, RU 2 | 16 | 5 (4) |
| phev_ev_consumption | 7 | GB 3 | 18 | 5 (3) |
| recalls | 2 | EU, CN | 12 | 4 (1) |
| warranty | 1 | GB | 6 | 0 |

What was lost, by market:

- **Used prices everywhere.** Classifieds and their aggregators make up 45 of the 60 blocked used-price entries. The
  rest are valuers behind a paywall or WAF (cap-hpi, eurotax.es, ganvam, schwacke, glass) or terms bans (largus,
  alvolante, parkers, autoweek, drive.co.uk).
- **UK.** 27 blocked entries. These are the Bauer and Hearst titles (parkers, carmagazine, fleetnews), the edge-blocked
  titles (whatcar, topgear, autocar) and the listing sites.
- **Spain.** 11 blocked entries. These are autobild.es (TDM opt-out under RDL 24/2021), coches.net, the classifieds,
  and the paywalls of ocu, eurotax and ganvam.
- **Russia.** 9 blocked entries. The terms of drom.ru and zr.ru forbid automated access, the robots.txt of autostat and
  5koleso block the paths we need, and drive2 is JS-only.
- **China.** 6 blocked entries. The spec configurators of autohome, yiche and dongchedi are JS-only, che168 and guazi
  are classifieds, and samr.gov.cn is dead.

## 2. What was added

There are 94 new survey entries: 60 `candidate`, 19 `tos_forbids`, 8 `blocked_robots`, 4 `js_only` and
3 `classifieds`.

| Region | New candidates | New non-candidates |
|---|---|---|
| Europe (outside Spain; PL, CH, FR, GB, DK, FI, HU, IT, NL, RO, GR, PT, NO, SE, EU-wide) | 33 | 12 (+ evspecifications.com, global) |
| China | 8 | 1 |
| Kazakhstan / CIS (KZ 2, RU 2, UA 1) | 5 | 7 |
| Middle East (TR) | 2 | 4 |
| Asia (JP 4, IN 1) | 5 | 5 |
| America (US 1, CA 3, MX 2, BR 1) | 7 | 4 |

New candidates by kind (all regions / Europe):

| Kind | All regions | Europe |
|---|---|---|
| specs | 47 | 28 |
| new_price | 31 | 18 |
| measured | 15 | 9 |
| consumption_real | 15 | 9 |
| owner_reviews | 11 | 5 |
| used_issues | 6 | 4 |
| phev_ev_consumption | 5 | 3 |
| maintenance | 5 | 4 |
| reliability | 4 | 3 |
| recalls | 4 | 1 |
| used_price | 2 | 0 |
| safety | 2 | 0 |
| residual_value | 1 | 0 |

The strongest new sources:

- **autocentrum.pl**: per-model faults, owner ratings, its own 0-100 km/h and consumption measurements, and owners'
  cost diaries.
- **automobilrevue.ch**: measured tests.
- **autotitre.com**: problems by model.
- **moottori.fi**: Traficom rejection rates by model, from the magazine of the Finnish automobile club.
- **fixter.co.uk** and **theaa.com**: UK service prices and car-care guidance.
- **pcauto.com.cn/pingce** and **d1ev.com**: instrumented Chinese tests.
- **quatrorodas**: Brazilian instrumented tests.
- **open.canada.ca** and **NRCan**: recall and consumption datasets.
- **guideautoweb.com**: reliability ratings.

The table below lists every new entry. The "Why" column shows what a candidate gives, or the evidence for a block.
The full robots line, the terms clause and the sample URL of each entry are in the YAML.

| Domain | Country | Kinds | Verdict | Why |
|---|---|---|---|---|
| autocentrum.pl | PL | reliability, used_issues, owner_reviews, measured, consumption_real, maintenance, specs | candidate | Per-model fault reports (usterki), owner ratings (oceny, e.g. RAV4 4.2 from 719 ratings), own instrumented measurements (nasze-pomiary: 0-100 km/h and fuel use), techn… |
| automobilrevue.ch | CH | measured, specs, new_price | candidate | Swiss weekly (since 1906) with road tests, measured values and CHF list prices. |
| autotitre.com | FR | reliability, used_issues, owner_reviews, specs | candidate | Per-model problem reports, owner opinions and reliability notes by generation. |
| theaa.com | GB | specs, maintenance, owner_reviews | candidate | AA (UK automobile club) car reviews and car-care / servicing guidance. |
| fixter.co.uk | GB | maintenance | candidate | Fixed service / MOT / repair prices per make and model (UK). |
| autobutler.dk | DK | maintenance | candidate | Workshop price comparisons per job and make (service, brakes, rust protection) in Denmark. |
| electrifying.com | GB | phev_ev_consumption, specs, new_price, owner_reviews | candidate | EV/PHEV reviews with real-world range and efficiency, long-term reports, UK prices. |
| carsized.com | EU | specs | candidate | Exterior/interior dimensions and boot volume, side-by-side size comparison. |
| moottori.fi | FI | reliability, used_issues, measured | candidate | Magazine of Autoliitto (Finnish automobile club): Traficom inspection rejection rates by model and age, road tests. |
| totalcar.hu | HU | measured, specs, consumption_real | candidate | Hungary's largest car magazine: tests with measured consumption and performance. |
| vezess.hu | HU | measured, specs, consumption_real, new_price | candidate | New-car tests with consumption and Hungarian prices. |
| bevolt.com | FR | phev_ev_consumption, measured, specs | candidate | EV/hybrid tests with measured consumption and range (automobile-propre.com now redirects here). |
| sportauto.fr | FR | measured, specs | candidate | Performance-car tests with timed acceleration and track data. |
| autojournal.fr | FR | specs, consumption_real, new_price | candidate | Road tests with French prices and test consumption. |
| leblogauto.com | FR | specs, consumption_real | candidate | Independent French road tests. |
| autonews.fr | FR | specs, new_price | candidate | French news and first drives with prices. |
| rappel.conso.gouv.fr | FR | recalls | candidate | Official French product-recall register (RappelConso), vehicles included. |
| automoto.it | IT | new_price, specs | candidate | Italian new-car price list with versions and technical data. |
| motorbox.com | IT | specs, consumption_real, new_price | candidate | Italian tests ('prova tecnica, consumi e prezzi'). |
| infomotori.com | IT | new_price, specs | candidate | Italian news with official price lists (listino) per model. |
| autozine.nl | NL | specs, new_price | candidate | Dutch model pages with versions, technical data and list prices. |
| motofakty.pl | PL | specs, consumption_real, new_price | candidate | Polish tests with consumption and PLN prices. |
| automarket.ro | RO | new_price, specs | candidate | Romanian new-car catalogue with versions, prices and technical data. |
| promotor.ro | RO | specs, consumption_real | candidate | Romanian news and tests. |
| autotriti.gr | GR | new_price, specs | candidate | Greek new-car price lists (times) by make and model. |
| 4troxoi.gr | GR | specs, new_price | candidate | Greek road tests with prices and data. |
| carzine.gr | GR | new_price, specs | candidate | Greek news with model prices. |
| motor24.pt | PT | specs, consumption_real, new_price | candidate | Portuguese road tests (ensaios). |
| aquelamaquina.pt | PT | specs, new_price | candidate | Portuguese new-model news and drives with prices. |
| elbil.no | NO | phev_ev_consumption, measured, specs | candidate | Norwegian EV Association: EV model pages, range and winter tests. |
| bilnorge.no | NO | specs, new_price | candidate | Norwegian trade news with model prices and data. |
| bilmagasinet.dk | DK | specs, measured, new_price | candidate | Danish magazine with model pages and tests. |
| carup.se | SE | owner_reviews, used_issues | candidate | Swedish car news incl. owner cases and recalls/defects. |
| www.pcauto.com.cn | CN | measured, specs, consumption_real | candidate | PCauto tests with instrumented acceleration, braking and consumption (complements price.pcauto.com.cn). |
| d1ev.com | CN | measured, phev_ev_consumption | candidate | First Electric (第一电动): NEV tests and range/consumption measurements. |
| 16888.com | CN | new_price, specs | candidate | Chinese dealer price quotes and spec sheets per series (e.g. 8.60–16.49万). |
| chexun.com | CN | specs, new_price | candidate | Chexun (车讯网) news, launches and prices. |
| c-ncap.org.cn | CN | safety | candidate | C-NCAP (CATARC) crash-test and C-ICAP assisted-driving ratings for Chinese-market cars. |
| carnewschina.com | CN | specs, new_price | candidate | English-language Chinese-market launches with specs (CLTC range, dimensions) and CNY prices. |
| cnevpost.com | CN | specs, new_price, phev_ev_consumption | candidate | English-language Chinese NEV news: specs, CLTC range, prices and sales data. |
| www.autohome.com.cn | CN | measured, specs | candidate | Autohome editorial tests (instrumented 'actual measurement' pieces); the JS spec configurator stays js_only. |
| akab.kz | KZ | new_price, used_price | candidate | Association of Kazakhstan Auto Business: monthly statistics of new and used car prices and sales. |
| tengrinews.kz | KZ | new_price, owner_reviews, specs | candidate | TengriAuto: Kazakh-market reviews and new-car price round-ups in tenge. |
| autostat.ru | RU | residual_value, used_price | candidate | Autostat analytics articles on the Russian market, residual values and used prices. |
| avtovzglyad.ru | RU | used_issues, maintenance, new_price | candidate | Russian consumer motoring site: used-car advice, maintenance tips and price news. |
| autocentre.ua | UA | specs, owner_reviews, consumption_real | candidate | Ukrainian magazine Autocentre: test drives with consumption and specs. |
| otomobilgazetesi.com | TR | specs, new_price | candidate | Turkish motoring news and drives with TL prices. |
| arabalar.com.tr | TR | specs, new_price | candidate | Turkish model catalogue with versions, specs and price lists. |
| kakaku.com | JP | owner_reviews, consumption_real, specs | candidate | Kakaku.com car section: owner reviews with ratings and owner-reported fuel economy. |
| car.motor-fan.jp | JP | specs, measured | candidate | Motor-Fan (San-ei) catalogue with full specs per grade; tests on motor-fan.jp. |
| jaf.or.jp | JP | measured, safety | candidate | JAF (Japan Automobile Federation) user tests: braking on snow/ice, crash and equipment experiments with named cars. |
| renrakuda.mlit.go.jp | JP | recalls, used_issues | candidate | MLIT (Japanese ministry) recall notifications and owner defect reports. |
| carwale.com | IN | specs, new_price, owner_reviews | candidate | Indian model pages with versions, ex-showroom prices, expert and long-term reviews. |
| carbuzz.com | US | specs, new_price, owner_reviews | candidate | US model pages with trims, specs, MSRP and reviews. |
| guideautoweb.com | CA | specs, new_price, reliability, owner_reviews | candidate | Guide de l'auto (Quebec): specs, CAD prices, reliability ratings and owner reviews. |
| open.canada.ca | CA | recalls, specs, consumption_real | candidate | Government of Canada open data: Transport Canada vehicle recalls and NRCan fuel consumption ratings (CSV). |
| natural-resources.canada.ca | CA | specs, consumption_real | candidate | NRCan fuel consumption ratings per model year, make, model and powertrain (L/100 km, CO2). |
| quatrorodas.abril.com.br | BR | measured, consumption_real, specs | candidate | Quatro Rodas instrumented tests (0-100 km/h, braking, measured consumption). |
| autocosmos.com.mx | MX | specs, new_price | candidate | Mexican catalogue of current models with versions and MXN prices. |
| gob.mx | MX | recalls | candidate | Profeco (Mexican consumer agency) vehicle recall notices. |
| autogids.be | BE | specs, new_price, measured | tos_forbids | 'Elke extractie of hergebruik van het geheel of een substantieel deel van de gegevens ... uit deze databanken, is onderworpen aan het voorafgaand schriftelijk akkoord … |
| moniteurautomobile.be | BE | specs, new_price, measured | tos_forbids | 'Le stockage d'une quelconque information et/ou élément du Site Web dans une base de données (électronique) n'est pas autorisé' (https://www.moniteurautomobile.be/cond… |
| autokult.pl | PL | specs, measured | tos_forbids | WP reserves '... web crawlers, oprogramowania, narzędzia, roboty ... web scraping, text and data mining, harvesting, screen scraping' — use requires prior consent (htt… |
| autorevue.cz | CZ | specs, measured | tos_forbids | 'Uživatelé nejsou oprávněni ... narušovat jejich provoz (zejména zasíláním ... automaticky generovaných přístupů na Internetové stránky nebo do Aplikací)' (https://www… |
| auto.cz | CZ | specs, measured, new_price | tos_forbids | footer links the CNC terms https://www.cncenter.cz/podminky-uzivani that forbid 'automaticky generovaných přístupů' |
| turbo.fr | FR | specs, new_price | tos_forbids | 'DIGITAL PRISMA PLAYERS s'oppose, sauf autorisation express, à toute extraction (notamment moissonnage et/ou fouille de textes et de données) ... par tout logiciel et/… |
| tuulilasi.fi | FI | measured, owner_reviews | tos_forbids | 'Et saa käyttää automaattisia järjestelmiä (kuten "robot-", "spider-" "scraper-" ja "offline reader-" ohjelmistot) tietojen keräämiseksi' (https://www.a-lehdet.fi/arti… |
| evspecifications.com | global | specs, phev_ev_consumption | tos_forbids | 'The use of automated systems or software to extract data from EVSpecifications.com for commercial or personal purposes (scraping) is strictly prohibited' (https://www… |
| autoflotte.de | DE | residual_value, used_price | tos_forbids | 'Unzulässig ist es auch, Inhalte der Websites ... systematisch auszulesen (Web-Crawling)' + TDM reservation § 44b UrhG (https://www.autoflotte.de/agb) |
| autohaus.de | DE | residual_value, used_price | tos_forbids | 'Unzulässig ist es auch, Inhalte der Websites ... systematisch auszulesen (Web-Crawling)' (https://www.autohaus.de/agb) |
| kfz-betrieb.vogel.de | DE | residual_value, maintenance | tos_forbids | 'Die Vogel Communications Group ... behält sich eine Nutzung seiner Inhalte für kommerzielles Text und Data Mining im Sinne von § 44b UrhG ausdrücklich vor' (https://w… |
| fairgarage.com | DE | maintenance | tos_forbids | 'Nutzer dürfen keine Mechanismen, Software oder sonstige Scripts ... verwenden, ... insbesondere solche, die es ermöglichen, automatisierte Seitenaufrufe ... zu generi… |
| auto.mail.ru | RU | specs, measured, owner_reviews | tos_forbids | 'Запрещено использование автоматизированных скриптов (программ, ботов, краулеров) для сбора информации и (или) взаимодействия с Сервисами Mail без согласия' (https://h… |
| lada.kz | KZ | new_price | tos_forbids | 'Без письменного согласия Правообладателя также не допускаются: автоматическое извлечение Материалов с Ресурса программными средствами (парсинг, скрейпинг)' (https://w… |
| icar.co.il | IL | specs, new_price | tos_forbids | 'אין להפעיל ... תוכנות מסוג Crawlers, Robots וכדומה, לשם חיפוש, סריקה, העתקה או אחזור אוטומטי של תכנים מתוך האתר' (https://www.icar.co.il/terms/) |
| autocarindia.com | IN | measured, specs | tos_forbids | 'You shall not: (i) engage in spidering, "screen scraping," "database scraping," ... or any other automatic means of obtaining ... information from or through the Web … |
| overdrive.in | IN | measured, specs | tos_forbids | '(iii) scrape, crawl, mine or extract data from the site ... without express written permission of Overdrive' (https://www.overdrive.in/terms-and-conditions/) |
| cardekho.com | IN | specs, new_price, used_price | tos_forbids | '... access or copy any Content ... through manual and/or automated means including but not limited to page scraping, data mining, data gathering, indexing, using soft… |
| autoesporte.globo.com | BR | measured, specs, new_price | tos_forbids | 'Nos Produtos Digitais é proibida a utilização, de aplicativos spider, ou de mineração de dados ... que atue de modo automatizado' (https://autoesporte.globo.com/termo… |
| vroomly.com | FR | maintenance | blocked_robots | disallowed (User-agent * Disallow /) |
| wwwapps.tc.gc.ca | CA | recalls | blocked_robots | disallowed (User-agent * Disallow /) |
| data.gov.il | IL | specs, recalls | blocked_robots | robots allows / (Disallow /api/) but every page returns HTTP 403 to our UA |
| yallamotor.com | AE | specs, new_price | blocked_robots | robots allowed for /new-cars/ but pages and terms return HTTP 403 (bot wall) |
| motory.com | SA | specs, new_price | blocked_robots | robots has no rules for * but pages return HTTP 403 (bot wall) |
| team-bhp.com | IN | owner_reviews, used_issues, reliability | blocked_robots | robots allow the forum, but pages return HTTP 403 (bot wall) |
| carview.yahoo.co.jp | JP | owner_reviews, specs | blocked_robots | robots.txt returns HTTP 403 |
| cars.usnews.com | US | owner_reviews, maintenance, reliability | blocked_robots | robots.txt allows car pages, but pages give no response to our UA (connection dropped) |
| motor.ru | RU | measured, specs | js_only | Every page redirects to a JS auth controller (/api/unity-id-sdk/…). |
| quto.ru | RU | specs | js_only | Every page redirects to a JS auth controller (/api/unity-id-sdk/…). |
| db.auto.sohu.com | CN | specs, new_price | js_only | The config page HTML has the model name only; the spec table is loaded by JS (Nuxt). |
| veiculos.fipe.org.br | BR | used_price | js_only | JS single-page app behind a 403 to our UA; FIPE publishes no static per-model pages. |
| kolesa.kz | KZ | used_price, new_price | classifieds | Classifieds marketplace — never used (constitution VIII). |
| mycar.kz | KZ | used_price | classifieds | Classifieds marketplace — never used. |
| drom.kz | KZ | used_price | classifieds | Classifieds and robots-blocked. |

## 3. Re-checks of the 009 tos_forbids and blocked_robots entries

**tos_forbids (22 entries, 20 domains): no verdict changes.** The terms pages were fetched again on 2026-11-05. The
forbidding clause is still present on:

- alvolante.it ("Sono vietate sia l'estrazione che il reimpiego…")
- auto-data.net
- autobild.es (RDL 24/2021 art. 67.3 opt-out)
- carmagazine.co.uk and fleetnews.co.uk (Bauer: "The use of any automated system or software to extract Content…")
- clickmechanic.com
- drive.co.uk
- drom.ru (§6 reprint rules)
- largus.fr ("s'oppose à toutes opérations de moissonnage et de fouille")
- ncts.ie
- pistonheads.com
- spritmonitor.de
- tekniikanmaailma.fi
- zapmap.com
- zr.ru (§5.3.9)

Four domains could not be re-read and keep their verdict:

- autoweek.nl and autovisie.nl: their terms pages answer 403 (DPG Media WAF).
- speakev.com: its terms page answers with a 202 challenge.
- greencarguide.co.uk: no connection.

coches.net is classifieds anyway.

**blocked_robots (12): no verdict changes.** They were re-tested with our exact UA:

- autocar.co.uk: robots.txt and pages give 202 with an empty body (WAF challenge).
- topgear.com and whatcar.com: 403.
- it.motor1.com: robots.txt 200, but /reviews/ gives 403.
- quattroruote.it: /listino/ gives 403.
- schwacke.de: redirects to a J.D. Power page that gives 403.
- check-mot.service.gov.uk: 403.
- diariomotor.com: /catalogo/ is still disallowed.
- 5koleso.ru: /catalogue/ is still disallowed.
- autostat.ru: only `/residualvalue/$` is allowed; its subpages are disallowed. The /news/ articles are allowed and are
  now a separate candidate.
- carfueldata.vehicle-certification-agency.gov.uk: `Disallow: /`.

autocar.co.uk and topgear.com are favourites in sources.yaml, but they never serve our UA. The owner may want to
drop them from the favourites. This revision did not drop them because it does not change existing favourites.

**Data fix.** The 009 file had `country: false` and `lang: false` for the five Norwegian entries (finn.no, ofv.no,
motor.no, naf.no, vegvesen.no). YAML reads an unquoted `NO` as a boolean, so the seed gave these entries the market
ANY. They are now quoted as `'NO'` and `'no'`.

## 4. sources.yaml changes

**Deny-list (+66 entries).** The deny-list matches a substring of host + path, so each entry is a full domain or a
domain/path:

- **Survey classifieds that were not yet deny-listed (23):** avito.ru, bilbasen.dk, bytbil.com, carsireland.ie,
  cazoo.co.uk, che168.com, cinch.co.uk, dba.dk, donedeal.ie, encar.com, finn.no, gaspedaal.nl, guazi.com, gumtree.com,
  kvd.se, marktplaats.nl, motors.co.uk, nettiauto.com, olx.pt, standvirtual.com, subito.it, carsensor.net,
  goo-net.com.
- **New classifieds (19):** kolesa.kz, mycar.kz, drom.kz, auto.ria.com, av.by, avtoelon.uz, myauto.ge, otomoto.pl,
  sauto.cz, tipcars.com, hasznaltauto.hu, autovit.ro, car.gr/classifieds, sahibinden.com, arabam.com, dubizzle.com,
  yad2.co.il, webmotors.com.br, icarros.com.br.
- **Listings sections of usable sites (6):** automoto.it/auto-usate, theaa.com/used-cars, kakaku.com/kuruma/used,
  carwale.com/used, yallamotor.com/used-cars, bevolt.com/fr-fr/automobile/occasions.
- **Terms forbid automated access (18):** autogids.be, moniteurautomobile.be, autokult.pl, autorevue.cz, turbo.fr,
  tuulilasi.fi, evspecifications.com, autoflotte.de, kfz-betrieb.vogel.de, fairgarage.com, vroomly.com (robots
  `Disallow: /`), auto.mail.ru, lada.kz, icar.co.il, autocarindia.com, `overdrive.in/` (with the slash so that it does
  not match overdrive.info), cardekho.com, autoesporte.globo.com.

Some domains are left out of the deny-list on purpose because the substring would over-match:

| Left out | Would also match |
|---|---|
| cars.com | iseecars.com, a favourite |
| auto.ru | skoda-auto.ru |
| auto.cz | skoda-auto.cz |
| cars.ie | other *cars.ie domains |
| autohaus.de | dealer domains |

The registry still blocks these through their survey entries.

A script checked the result (`denycheck`). No deny entry matches a candidate, favourite, official or manufacturer
domain, or any candidate sample URL. The deny-list has no duplicates.

**Favourites (+11).** All were added with `tos_checked: 2026-11-05` and `reader: null`. They are European sources whose
robots.txt allows the model pages for our UA and whose terms have no automated-access clause. Sites outside ES/EN/DE
get `markets: [ANY]` and only market-neutral areas (no prices).

| Domain | Areas | Market | Priority |
|---|---|---|---|
| autocentrum.pl | reliability, used_issues, measured, reviews, maintenance | ANY | 2 |
| autotitre.com | reliability, used_issues, reviews | ANY | 3 |
| moottori.fi | reliability, used_issues | ANY | 3 |
| automobilrevue.ch (INSTRUMENTED_TEST) | measured, reviews | DE | 2 |
| totalcar.hu (INSTRUMENTED_TEST) | measured, reviews | ANY | 3 |
| elbil.no | specs, measured | ANY | 3 |
| bevolt.com | specs, measured, reviews | ANY | 3 |
| fixter.co.uk | maintenance | EN | 2 |
| theaa.com | maintenance, reviews | EN | 2 |
| electrifying.com | specs, reviews | EN | 3 |
| carsized.com (SPEC_DATABASE) | specs | ANY | 3 |

The task allowed favourite markets FR/IT/PT/NL, but `config.MARKETS` accepts only ES/EN/DE/ANY, and changing it would
change application code. French, Italian, Portuguese and Dutch sites therefore stay registry candidates. sportauto.fr
and autojournal.fr were not promoted because of the Reworld database-right clause.

Validation passed:

- `reference(load_all())` loads without error.
- `pytest tests/unit -k "config or source or registry"`: 40 passed.
- The full unit suite: 890 passed.
- `seed_rules.from_survey` and `from_favourite` accept every new entry.

## 5. Gaps that remain

- **Used prices in Spain and across Europe.** No European used-price source that allows robots was found. The
  remaining ones are classifieds, their aggregators, or paywalled or WAF-protected valuers: largus, eurotax, schwacke,
  cap-hpi, quattroruote, parkers. dat.de and the ADAC remain the only open guides. autocentrum.pl's "ceny aut
  używanych" table is computed from its own ads and was excluded. Outside Europe there are akab.kz (KZ market
  statistics), autostat.ru news and FIPE (JS-only).
- **Residual value.** No new European source. autoflotte.de, autohaus.de and kfz-betrieb.vogel.de publish DAT and
  Schwacke residual-value rankings, but their terms forbid crawling or TDM. autovista24, adac.de and dat.de remain.
- **Reliability.** The new sources are autocentrum.pl (PL), autotitre.com (FR) and moottori.fi (Traficom inspections).
  The Swedish Bilprovningen and Finnish A-Katsastus reports have no model-level pages (the PDFs found are not per
  model).
- **Maintenance costs.** fixter.co.uk (GBP), theaa.com and autobutler.dk (DKK) were added. There is still no Spanish or
  German open price guide: fairgarage forbids automated access and vroomly blocks robots.
- **UK.** whatcar, topgear, autocar, parkers and the Bauer titles stay closed to our UA. The AA, Fixter and
  Electrifying help.
- **China specs.** The configurators (autohome, yiche, dongchedi, db.auto.sohu) are JS-only. 16888.com, carnewschina
  and cnevpost give specs and prices in static HTML.
- **Middle East.** Coverage is thin: two Turkish candidates. yallamotor, motory and data.gov.il answer 403 to our UA,
  and icar.co.il forbids crawlers.
- **Thin new entries.** Some candidates are news sites with low data density: autonews.fr, promotor.ro, carup.se,
  bilnorge.no, carzine.gr, chexun.com. The registry's scoring will show whether they earn their place.

## 6. Suggestions (datasets to ingest)

- **Traficom (FI), RDW (NL), Statens vegvesen (NO), KBA (DE), DVSA MOT API (GB):** model-level inspection and failure
  data are open, and several are already candidates. A small ingestion job would give reliability by model and age
  without scraping.
- **open.canada.ca:** the Transport Canada Vehicle Recalls Database (CSV) and the NRCan Fuel Consumption Ratings (CSV,
  one file per model year). Both use the Open Government Licence. Download the files instead of using the robots-
  disallowed wwwapps.tc.gc.ca search.
- **RappelConso (FR):** read the fiche pages. The data.economie.gouv.fr API and dataset exports are robots-disallowed,
  so ask the operator for a bulk export if needed.
- **NHTSA complaints/recalls API and fueleconomy.gov (already candidates):** these could be ingested in bulk as the
  baseline for used_issues and consumption.
- **Licensing:** ask the operators of autoflotte/autohaus (TECVIA), Vogel and Reworld for a licence if residual-value
  rankings and French instrumented tests are worth it. Their terms reserve TDM, so licensing is the only clean route.
- **Favourite markets:** extend `config.MARKETS` with FR/IT/PT/NL. This is an application change that this revision
  did not make. Then bevolt.com, autotitre.com, automoto.it (/listino/), motorbox.com, autozine.nl and motor24.pt
  could become per-market favourites, including prices from European markets.
