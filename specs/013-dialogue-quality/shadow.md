# Spec 013 T034 — understanding in the shadow: new chain vs old interpreter

Run 2026-11-27 14:02 UTC · model `google_genai:gemini-3.1-flash-lite` · prompt `<!-- prompt: understander v4 -->` · 148 cases, 148 compared, 0 errors · cost €0.134

Produced by `backend/tests/eval/understanding/shadow.py`. Old = the T005 baseline run (`baseline.json`, gemini-3.6-flash on the `interpreter` role); new = Understander → validate_understanding → IntentResolver (`new_path.py`). `action` is indicative on both sides: today's policy on the mapped request, without identification or assessment; the policy reads the intent only from S4.

## Accuracy per field

| Field | Checked | Old | New | Fixed | Broke |
|---|---|---|---|---|---|
| language | 148 | 96 % | 100 % | 6 | 0 |
| answer | 148 | 66 % | 94 % | 45 | 3 |
| goals | 148 | 76 % | 89 % | 31 | 13 |
| reaction | 28 | 82 % | 89 % | 4 | 2 |
| rejections | 12 | 67 % | 50 % | 1 | 3 |
| changes | 82 | 80 % | 80 % | 8 | 8 |
| action | 148 | 28 % | 26 % | 7 | 9 |
| **all fields** | 148 | 20 % | **21 %** | 11 | 9 |
| **all fields but action** | 148 | 49 % | **72 %** | 46 | 13 |

## Latency of the understanding step (148 new calls)

old p95 4566 ms · new p95 **1824 ms** (p50 1294 ms) — criterion: new ≤ old + 20 % (G4). Wall clock with 4 calls in flight.

## Per language (all fields)

| | cases | old | new |
|---|---|---|---|
| en | 47 | 23 % | 23 % |
| es | 46 | 22 % | 26 % |
| ru | 55 | 15 % | 15 % |

## Per pending kind (all fields)

| | cases | old | new |
|---|---|---|---|
| CONFIRM_COST | 11 | 9 % | 18 % |
| CONFIRM_INTAKE | 23 | 0 % | 4 % |
| CONFIRM_VARIANTS | 10 | 40 % | 0 % |
| LIMIT | 13 | 77 % | 85 % |
| QUESTIONS | 51 | 2 % | 4 % |
| none | 40 | 32 % | 38 % |

## Broke (old right, new wrong)

| Case | Message | Fields (expected / got) |
|---|---|---|
| ru-002 | давно хотел дизель | **answer** none / no<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-014 | Mercedes C-Class | **goals** [] / ['compare']<br>**action** ASK / CONFIRM_VARIANTS |
| ru-016 | не тот | **action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#2', 'VERSION')] / [] |
| ru-017 | нет, другую | **action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#2', 'VERSION')] / [] |
| ru-023 | Найди Мазда mx-30 r-ev вот https://www.mazda.es/promociones/promociones-actuales | **goals** [] / ['research_more']<br>**action** ASK / CONFIRM_VARIANTS |
| ru-024 | MAZDA MX-30 E-SKYACTIV R-EV 125 KW (170 CV) AT 2WD | **action** ASK / CONFIRM_VARIANTS<br>**changes** car#1.engine R-EV / None; car#1.gearbox automatic / None |
| ru-027 | MG ZS (suv, petrol, hybrid) | **action** ASK / CONFIRM_VARIANTS |
| ru-033 | ну дак сравни byd seal u с сеатом атека 1.5 двигателя | **changes** car#1.make BYD / None |
| ru-034 | BYD это компания Build your dream китайская представленная в европе | **goals** [] / ['ask_general']<br>**action** ASK / ANSWER_GENERAL<br>**changes** car#1.make BYD / None |
| ru-035 | я же спрашивал про расходы на обслуживание, а не про разгон | **goals** ['follow_up'] / ['research_more']<br>**action** ANSWER_FROM_CONTEXT / REPORT |
| ru-036 | спасибо, а теперь добавь Kia Sportage | **goals** ['compare'] / []<br>**action** ASK / ANSWER_GENERAL<br>**changes** add_cars ['Kia Sportage'] / [] |
| ru-045 | вперед к сравнению | **goals** [] / ['compare']<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-004 | Vivimos en Sevilla y hacemos unos 18.000 km al año. ¿BYD Seal U DM-i o SEAT Atec | **action** ASK / CONFIRM_VARIANTS<br>**changes** region Sevilla / None |
| es-005 | no es ese, quiero el diésel | **answer** no:None / option:option:car#2:20tdi-dsg<br>**action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#2', 'VERSION')] / []<br>**changes** car#2.fuel diesel / None |
| es-017 | gracias, ¿y si priorizo el consumo? | **reaction** thanks / None |
| es-020 | Ahora no | **goals** [] / ['stop']<br>**action** REPORT / CONFIRM_VARIANTS |
| es-021 | si, ese | **answer** yes:None / option:option:car#2:15tsi-dsg<br>**action** RESEARCH / CONFIRM_VARIANTS |
| es-035 | compara ya | **answer** yes:None / None:None<br>**goals** [] / ['compare']<br>**action** RESEARCH / CONFIRM_VARIANTS |
| es-036 | es el 1.5, no el 1.0 | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS<br>**reaction** correction / None<br>**changes** car#1.displacement_l 1.5 / 1.0 |
| en-006 | if I prefer status, who wins? | **goals** ['change_priorities'] / ['compare']<br>**action** ANSWER_FROM_CONTEXT / REPORT |
| en-013 | We are a family in Seville, about 18,000 km a year. BYD Seal U DM-i or SEAT Atec | **action** ASK / CONFIRM_VARIANTS<br>**changes** region Seville / None |
| en-014 | Deep research please: Skoda Octavia RS, Cupra Leon VZ and Peugeot 308 | **goals** ['compare'] / ['research_more']<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-025 | Not now | **goals** [] / ['stop']<br>**action** REPORT / CONFIRM_VARIANTS |
| en-030 | okay, that's the one | **action** RESEARCH / CONFIRM_VARIANTS |
| en-032 | nein nein, not that one | **action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#1', 'VERSION')] / [] |
| en-034 | you didn't find the R-EV, that's the electric one | **goals** [] / ['research_more']<br>**action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#1', 'ENGINE')] / [] |
| en-038 | thanks! now compare it with a Skoda Kodiaq | **goals** ['compare'] / []<br>**action** ASK / ANSWER_GENERAL<br>**changes** add_cars ['Skoda Kodiaq'] / [] |
| en-042 | used Land Rover Prado vs Volvo XC90 | **changes** add_cars ['Toyota Land Cruiser Prado', 'Volvo XC90'] / ['Land Rover Land Rover Prado', 'Volvo XC90'] |

## All failures of the new chain

| Case | Message | Fields (expected / got) |
|---|---|---|
| ru-001 | да, но дизель | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-002 | давно хотел дизель | **answer** none / no<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-003 | дайте подумать | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| ru-004 | все равно хочу дизель | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-005 | все равно хочу дизель | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-007 | а что такое DSG? | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| ru-009 | переформулируйте | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| ru-010 | ты не нашел мерседес класс C | **action** ASK / CONFIRM_VARIANTS |
| ru-011 | ты полный кретин. ты не нашел  мерседес класс C. отменяй поиск . пошел в жопу | **action** ANSWER_FROM_CONTEXT / ANSWER_GENERAL |
| ru-012 | ты не нашел мерседес класс C. отменяй поиск. пошел в жопу | **action** ANSWER_FROM_CONTEXT / ANSWER_GENERAL |
| ru-013 | ты полный кретин. ты не нашел мерседес класс C. отменяй поиск . пошел в жопу | **action** ANSWER_FROM_CONTEXT / ANSWER_GENERAL |
| ru-014 | Mercedes C-Class | **goals** [] / ['compare']<br>**action** ASK / CONFIRM_VARIANTS |
| ru-015 | отменяй поиск | **action** ANSWER_FROM_CONTEXT / ANSWER_GENERAL |
| ru-016 | не тот | **action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#2', 'VERSION')] / [] |
| ru-017 | нет, другую | **action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#2', 'VERSION')] / [] |
| ru-018 | нет | **action** ASK / CONFIRM_VARIANTS |
| ru-019 | да | **action** RESEARCH / CONFIRM_VARIANTS |
| ru-020 | Очень плохо! Ты ничего не нашел | **action** ASK / CONFIRM_VARIANTS |
| ru-021 | Очень плохо! Ты ничего не нашел | **action** ASK / CONFIRM_VARIANTS |
| ru-022 | Это роторная мазда mx-30 r-ev | **action** ASK / CONFIRM_VARIANTS<br>**reaction** correction / None |
| ru-023 | Найди Мазда mx-30 r-ev вот https://www.mazda.es/promociones/promociones-actuales | **goals** [] / ['research_more']<br>**action** ASK / CONFIRM_VARIANTS |
| ru-024 | MAZDA MX-30 E-SKYACTIV R-EV 125 KW (170 CV) AT 2WD | **action** ASK / CONFIRM_VARIANTS<br>**changes** car#1.engine R-EV / None; car#1.gearbox automatic / None |
| ru-025 | А вот если я хочу мазду mx-30 r-ev как альтернативу hyundai i10. Вот страница: h | **action** ASK / CONFIRM_VARIANTS |
| ru-026 | я выбираю между Clase C Berlina мерседесом и Маздой CX-60 | **action** ASK / CONFIRM_VARIANTS |
| ru-027 | MG ZS (suv, petrol, hybrid) | **action** ASK / CONFIRM_VARIANTS |
| ru-028 | hybrid 155 | **action** REPORT / CONFIRM_VARIANTS |
| ru-032 | Мне 20, могу купить б/у BMW 320d M Sport или Golf R-Line 4Motion — сравни на дра | **changes** persona PERFORMANCE / UNKNOWN |
| ru-033 | ну дак сравни byd seal u с сеатом атека 1.5 двигателя | **changes** car#1.make BYD / None |
| ru-034 | BYD это компания Build your dream китайская представленная в европе | **goals** [] / ['ask_general']<br>**action** ASK / ANSWER_GENERAL<br>**changes** car#1.make BYD / None |
| ru-035 | я же спрашивал про расходы на обслуживание, а не про разгон | **goals** ['follow_up'] / ['research_more']<br>**action** ANSWER_FROM_CONTEXT / REPORT |
| ru-036 | спасибо, а теперь добавь Kia Sportage | **goals** ['compare'] / []<br>**action** ASK / ANSWER_GENERAL<br>**changes** add_cars ['Kia Sportage'] / [] |
| ru-037 | найди мне подходящую kia для замены моего ленд круер прадо 150 возрастом 15 лет | **changes** add_cars ['Toyota Land Cruiser Prado'] / []; replaced_car Toyota Land Cruiser Prado / [] |
| ru-038 | б/у | **action** SELECT_CANDIDATES / ANSWER_GENERAL |
| ru-039 | автомат | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-040 | выбери сам, любой | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-041 | любая версия, мне всё равно | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-042 | возьми любую, на твой выбор | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-043 | любое исполнение — на ваш выбор, неважно | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-044 | выбери ты, не важно какой | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-045 | вперед к сравнению | **goals** [] / ['compare']<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-046 | поехали, вперёд | **action** RESEARCH / CONFIRM_COST |
| ru-047 | давай, запускай | **action** RESEARCH / CONFIRM_COST |
| ru-048 | нет, дорого | **action** REPORT / CONFIRM_COST |
| ru-052 | ок, сравнивай | **goals** [] / ['compare']<br>**action** RESEARCH / CONFIRM_VARIANTS |
| ru-053 | стоп, а у Prado какой расход? | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| ru-054 | да ладно, а сколько стоит обслуживание Sportage? | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| ru-055 | 1.6 гибрид, и добавь ещё Toyota RAV4 | **action** ASK / CONFIRM_VARIANTS |
| es-001 | para mi familia | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-003 | busco un Kia Sportage para sustituir mi Qashqai de 2012 | **action** ASK / CONFIRM_VARIANTS<br>**changes** add_cars ['Kia Sportage', 'Nissan Qashqai'] / ['Kia Sportage'] |
| es-004 | Vivimos en Sevilla y hacemos unos 18.000 km al año. ¿BYD Seal U DM-i o SEAT Atec | **action** ASK / CONFIRM_VARIANTS<br>**changes** region Sevilla / None |
| es-005 | no es ese, quiero el diésel | **answer** no:None / option:option:car#2:20tdi-dsg<br>**action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#2', 'VERSION')] / []<br>**changes** car#2.fuel diesel / None |
| es-006 | otro, ese no | **action** ASK / CONFIRM_VARIANTS |
| es-007 | no encontraste el Clase C, me has puesto el Clase E | **answer** no:None / None:None<br>**action** ASK / CONFIRM_VARIANTS |
| es-008 | para, cancela la búsqueda | **action** ANSWER_FROM_CONTEXT / ANSWER_GENERAL |
| es-009 | olvídalo, cancela todo | **action** ANSWER_FROM_CONTEXT / ANSWER_GENERAL |
| es-010 | fatal, no has encontrado nada | **goals** [] / ['critique']<br>**action** ASK / CONFIRM_VARIANTS |
| es-012 | si es diésel mejor | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-013 | ¿vale la pena un híbrido enchufable si no puedo cargar en casa? | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| es-014 | ¿sigue siendo fiable el motor 1.5 TSI? | **action** ANSWER_AND_REASK / RESEARCH |
| es-015 | no sé cuál, ¿cuál gasta menos? | **answer** none / choose_for_me<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| es-016 | sí, y añade un Toyota RAV4 | **action** ASK / CONFIRM_VARIANTS |
| es-017 | gracias, ¿y si priorizo el consumo? | **reaction** thanks / None |
| es-018 | sí | **action** RESEARCH / CONFIRM_VARIANTS |
| es-019 | vale | **action** RESEARCH / CONFIRM_VARIANTS |
| es-020 | Ahora no | **goals** [] / ['stop']<br>**action** REPORT / CONFIRM_VARIANTS |
| es-021 | si, ese | **answer** yes:None / option:option:car#2:15tsi-dsg<br>**action** RESEARCH / CONFIRM_VARIANTS |
| es-022 | el del diésel, el 2.0 TDI | **action** RESEARCH / CONFIRM_VARIANTS |
| es-024 | no, es demasiado caro | **action** REPORT / RESEARCH |
| es-025 | ¿cuánto tarda la investigación? | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| es-030 | Seguir investigando | **goals** [] / ['research_more'] |
| es-031 | Automático | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-032 | me da igual, elige tu | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-033 | cualquiera vale | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-034 | elige tú el motor | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-035 | compara ya | **answer** yes:None / None:None<br>**goals** [] / ['compare']<br>**action** RESEARCH / CONFIRM_VARIANTS |
| es-036 | es el 1.5, no el 1.0 | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS<br>**reaction** correction / None<br>**changes** car#1.displacement_l 1.5 / 1.0 |
| es-039 | mi presupuesto es de 30.000 €, nuevo | **action** ASK / CONFIRM_VARIANTS |
| es-041 | Toyota Corolla o Nissan Qashqai, y que tenga un color bonito | **action** ASK / CONFIRM_VARIANTS |
| es-042 | somos cinco y llevamos mucho equipaje en vacaciones | **changes** passengers 5 / None |
| es-043 | quiero el acabado R-Line | **answer** none / value<br>**action** ASK / CONFIRM_VARIANTS |
| es-046 | ¿puedes reformularlo? no lo entiendo | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| en-001 | answer me about fuel | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| en-002 | do you have any... | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| en-003 | I don't want to spend too much, but I don't want rubbish either. A brand-new Dac | **action** ASK / ANSWER_GENERAL<br>**changes** add_cars ['Dacia Bigster', 'Toyota Land Cruiser Prado'] / []; persona BUYER / UNKNOWN; priorities True / [] |
| en-004 | about 10 years old, the 150 | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-005 | but i asked about used 10 yrs old LC prado 150 not new | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-006 | if I prefer status, who wins? | **goals** ['change_priorities'] / ['compare']<br>**action** ANSWER_FROM_CONTEXT / REPORT |
| en-008 | no, I meant the old one, the 150 | **action** CONFIRM_INTAKE / ASK |
| en-010 | used, about 5 years | **action** ASK / CONFIRM_VARIANTS |
| en-011 | I want a Hyundai instead of my 2014 Golf, something for the family | **action** SELECT_CANDIDATES / ASK<br>**changes** add_cars ['Volkswagen Golf'] / ['Hyundai', 'Ford']; replaced_car Volkswagen Golf / []; usage True / [] |
| en-013 | We are a family in Seville, about 18,000 km a year. BYD Seal U DM-i or SEAT Atec | **action** ASK / CONFIRM_VARIANTS<br>**changes** region Seville / None |
| en-014 | Deep research please: Skoda Octavia RS, Cupra Leon VZ and Peugeot 308 | **goals** ['compare'] / ['research_more']<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-015 | proceed | **action** RESEARCH / CONFIRM_COST |
| en-016 | sure, run it | **action** RESEARCH / CONFIRM_COST |
| en-017 | too expensive, skip it | **action** REPORT / CONFIRM_COST |
| en-019 | go ahead | **action** RESEARCH / CONFIRM_COST |
| en-024 | yes | **action** RESEARCH / CONFIRM_VARIANTS |
| en-025 | Not now | **goals** [] / ['stop']<br>**action** REPORT / CONFIRM_VARIANTS |
| en-026 | no | **action** ASK / CONFIRM_VARIANTS |
| en-027 | ok so how much is the plug-in to run per month? | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| en-028 | yes, but make it AWD | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-029 | no idea what DSG means | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| en-030 | okay, that's the one | **action** RESEARCH / CONFIRM_VARIANTS |
| en-031 | the second one | **action** RESEARCH / CONFIRM_VARIANTS |
| en-032 | nein nein, not that one | **action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#1', 'VERSION')] / [] |
| en-033 | wrong generation, it's a Golf 7 from 2015, not a 7.5 | **answer** no:None / None:None<br>**action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#1', 'GENERATION')] / [] |
| en-034 | you didn't find the R-EV, that's the electric one | **goals** [] / ['research_more']<br>**action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#1', 'ENGINE')] / [] |
| en-035 | stop, cancel the search | **action** ANSWER_FROM_CONTEXT / ANSWER_GENERAL |
| en-037 | terrible, you found nothing | **action** ASK / CONFIRM_VARIANTS |
| en-038 | thanks! now compare it with a Skoda Kodiaq | **goals** ['compare'] / []<br>**action** ASK / ANSWER_GENERAL<br>**changes** add_cars ['Skoda Kodiaq'] / [] |
| en-039 | whatever, doesn't matter, you choose | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-040 | I don't care, choose for me | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-041 | any is fine, dont care | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-042 | used Land Rover Prado vs Volvo XC90 | **changes** add_cars ['Toyota Land Cruiser Prado', 'Volvo XC90'] / ['Land Rover Land Rover Prado', 'Volvo XC90'] |
| en-043 | Tesla Model 3 or BMW 320d, no more than €150 a month to run it | **action** ASK / CONFIRM_VARIANTS |
| en-044 | who wins a drag race in the wet with two passengers? I bet the Golf | **goals** [] / ['compare'] |
| en-045 | the purple one | **answer** none / value<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |

## Errors

