# Spec 013 T005 — understanding baseline (today's interpreter)

Run 2026-11-27 09:47 UTC · model `google_genai:gemini-3.6-flash` · prompt `<!-- prompt: interpreter v5 (R4; spec 005 R1, R4, R5; spec 0` · 148 cases, 148 scored, 0 errors · cost €1.145

Produced by `backend/tests/eval/understanding/runner.py`. How the old path is run and what it cannot run (identification and assessment: no catalogue in the fixtures; car facts from the fixture's resolution) is in `old_path.py`; the scoring rules in `scoring.py`. Old labels → new fields by understanding-spec §4.

## Accuracy per field

Ceiling = the same harness with an interpreter that returns the expected labels (`oracle.py`): what the old schema and this harness can score at best. The gap between the two columns is the model's; the gap between the ceiling and 100 % is the old schema's (no `stop`, no answer kinds for typed confirmations, no ANSWER_AND_REASK) or the harness's (no identification / assessment, so `action` is indicative only).

| Field | Checked | Correct | Accuracy | Ceiling |
|---|---|---|---|---|
| language | 148 | 142 | 96 % | 98 % |
| answer | 148 | 97 | 66 % | 72 % |
| goals | 148 | 113 | 76 % | 86 % |
| reaction | 28 | 23 | 82 % | 100 % |
| rejections | 12 | 8 | 67 % | 8 % |
| changes | 82 | 66 | 80 % | 30 % |
| action | 148 | 41 | 28 % | 28 % |
| **all fields of the case** | 148 | 29 | **20 %** | 17 % |

## Latency of the understanding step (old interpreter, 130 model calls)

p50 2129 ms · p95 **4567 ms** · max 5687 ms — the reference for the +20 % criterion (G4). Wall clock with 4 calls in flight.

## Per language

| | cases | all ok | language | answer | goals | reaction | rejections | changes | action |
|---|---|---|---|---|---|---|---|---|---|
| en | 47 | 23 % | 100 % | 77 % | 85 % | 100 % | 33 % | 77 % | 34 % |
| es | 46 | 22 % | 98 % | 67 % | 65 % | 86 % | 67 % | 82 % | 30 % |
| ru | 55 | 15 % | 91 % | 55 % | 78 % | 67 % | 83 % | 82 % | 20 % |

## Per pending kind

| | cases | all ok | language | answer | goals | reaction | rejections | changes | action |
|---|---|---|---|---|---|---|---|---|---|
| CONFIRM_COST | 11 | 9 % | 100 % | 100 % | 82 % | – | – | 100 % | 18 % |
| CONFIRM_INTAKE | 23 | 0 % | 100 % | 70 % | 83 % | 100 % | 100 % | 91 % | 0 % |
| CONFIRM_VARIANTS | 10 | 40 % | 100 % | 40 % | 80 % | 100 % | 67 % | 100 % | 40 % |
| LIMIT | 13 | 77 % | 100 % | 85 % | 92 % | – | – | – | 85 % |
| QUESTIONS | 51 | 2 % | 90 % | 29 % | 61 % | 62 % | 75 % | 85 % | 4 % |
| none | 40 | 32 % | 98 % | 100 % | 85 % | 100 % | 0 % | 71 % | 55 % |

## Per category

| | cases | all ok | language | answer | goals | reaction | rejections | changes | action |
|---|---|---|---|---|---|---|---|---|---|
| button_text | 7 | 14 % | 86 % | 57 % | 86 % | – | – | 50 % | 43 % |
| choose_for_me | 12 | 0 % | 75 % | 75 % | 100 % | – | – | – | 0 % |
| complaint | 10 | 30 % | 100 % | 30 % | 30 % | 80 % | 67 % | 100 % | 30 % |
| diesel_engine_closed | 1 | 0 % | 100 % | 100 % | 100 % | – | – | 100 % | 0 % |
| diesel_engine_open | 1 | 0 % | 100 % | 0 % | 100 % | – | – | 100 % | 0 % |
| golden | 16 | 6 % | 100 % | 75 % | 75 % | 67 % | 100 % | 53 % | 25 % |
| interpreter_patch | 46 | 24 % | 96 % | 76 % | 85 % | 100 % | 100 % | 70 % | 43 % |
| language_hysteresis | 6 | 17 % | 50 % | 50 % | 83 % | 50 % | – | 100 % | 33 % |
| lookalike_choose | 4 | 0 % | 100 % | 25 % | 50 % | – | – | 67 % | 0 % |
| lookalike_no | 6 | 0 % | 100 % | 50 % | 50 % | 100 % | – | 100 % | 0 % |
| lookalike_yes | 8 | 0 % | 100 % | 100 % | 62 % | 100 % | – | 100 % | 12 % |
| no_pending | 40 | 32 % | 98 % | 100 % | 85 % | 100 % | 0 % | 71 % | 55 % |
| pending_confirm_cost | 11 | 9 % | 100 % | 100 % | 82 % | – | – | 100 % | 18 % |
| pending_confirm_intake | 23 | 0 % | 100 % | 70 % | 83 % | 100 % | 100 % | 91 % | 0 % |
| pending_confirm_variants | 10 | 40 % | 100 % | 40 % | 80 % | 100 % | 67 % | 100 % | 40 % |
| pending_limit | 13 | 77 % | 100 % | 85 % | 92 % | – | – | – | 85 % |
| pending_questions | 51 | 2 % | 90 % | 29 % | 61 % | 62 % | 75 % | 85 % | 4 % |
| phrases_word | 68 | 21 % | 96 % | 74 % | 84 % | 100 % | 67 % | 89 % | 22 % |
| plain_no | 10 | 40 % | 100 % | 90 % | 100 % | – | – | 100 % | 40 % |
| plain_yes | 20 | 45 % | 100 % | 95 % | 95 % | – | – | – | 45 % |
| preprod_miss | 7 | 0 % | 71 % | 0 % | 57 % | 60 % | 50 % | 100 % | 0 % |
| problem_table | 6 | 0 % | 100 % | 17 % | 67 % | – | – | 67 % | 0 % |
| question_during_question | 12 | 0 % | 100 % | 50 % | 42 % | – | – | 67 % | 0 % |
| rejection | 12 | 17 % | 92 % | 25 % | 83 % | 71 % | 73 % | 100 % | 17 % |
| spec1 | 11 | 0 % | 100 % | 27 % | 55 % | 50 % | – | 78 % | 0 % |
| stop | 7 | 0 % | 100 % | 0 % | 0 % | 33 % | 67 % | 100 % | 0 % |
| two_intents | 12 | 8 % | 100 % | 33 % | 67 % | 60 % | 67 % | 83 % | 8 % |

## Failures

| Case | Message | Fields (expected / got) |
|---|---|---|
| ru-001 | да, но дизель | **answer** yes:None / None:None<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-002 | давно хотел дизель | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-003 | дайте подумать | **action** ANSWER_AND_REASK / ANSWER_GENERAL |
| ru-004 | все равно хочу дизель | **answer** value:None / choose_for_me:None<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-005 | все равно хочу дизель | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-006 | давай сравним с BMW | **answer** none / value<br>**goals** ['compare'] / []<br>**action** ASK / SELECT_CANDIDATES<br>**changes** add_cars ['BMW'] / [] |
| ru-007 | а что такое DSG? | **answer** none / value<br>**goals** ['ask_general'] / []<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| ru-008 | да, и добавь Hyundai | **answer** yes:None / None:None<br>**action** ASK / SELECT_CANDIDATES<br>**changes** add_cars ['Hyundai'] / [] |
| ru-009 | переформулируйте | **answer** none / value<br>**goals** [] / ['follow_up']<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS<br>**reaction** rephrase / None |
| ru-010 | ты не нашел мерседес класс C | **answer** none / value<br>**action** ASK / CONFIRM_VARIANTS |
| ru-011 | ты полный кретин. ты не нашел  мерседес класс C. отменяй поиск . пошел в жопу | **answer** none / value<br>**goals** ['stop'] / []<br>**action** ANSWER_FROM_CONTEXT / CONFIRM_VARIANTS<br>**reaction** complaint / correction |
| ru-012 | ты не нашел мерседес класс C. отменяй поиск. пошел в жопу | **answer** none / value<br>**goals** ['stop'] / []<br>**action** ANSWER_FROM_CONTEXT / CONFIRM_VARIANTS<br>**reaction** complaint / correction |
| ru-013 | ты полный кретин. ты не нашел мерседес класс C. отменяй поиск . пошел в жопу | **answer** none / value<br>**goals** ['stop'] / ['critique']<br>**action** ANSWER_FROM_CONTEXT / ASK<br>**rejections** [] / [('car#1', 'MODEL')] |
| ru-014 | Mercedes C-Class | **language** ru / en<br>**answer** none / value<br>**action** ASK / CONFIRM_VARIANTS |
| ru-015 | отменяй поиск | **answer** none / no<br>**goals** ['stop'] / []<br>**action** ANSWER_FROM_CONTEXT / CONFIRM_VARIANTS |
| ru-018 | нет | **action** ASK / CONFIRM_VARIANTS |
| ru-019 | да | **action** RESEARCH / CONFIRM_VARIANTS |
| ru-020 | Очень плохо! Ты ничего не нашел | **answer** none / value<br>**goals** [] / ['critique']<br>**action** ASK / CONFIRM_VARIANTS |
| ru-021 | Очень плохо! Ты ничего не нашел | **answer** none / value<br>**goals** [] / ['critique']<br>**action** ASK / CONFIRM_VARIANTS |
| ru-022 | Это роторная мазда mx-30 r-ev | **answer** none / value<br>**action** ASK / CONFIRM_VARIANTS<br>**reaction** correction / None |
| ru-023 | Найди Мазда mx-30 r-ev вот https://www.mazda.es/promociones/promociones-actuales | **answer** none / value<br>**action** ASK / CONFIRM_VARIANTS |
| ru-024 | MAZDA MX-30 E-SKYACTIV R-EV 125 KW (170 CV) AT 2WD | **language** ru / en<br>**answer** none / value<br>**action** ASK / CONFIRM_VARIANTS |
| ru-025 | А вот если я хочу мазду mx-30 r-ev как альтернативу hyundai i10. Вот страница: h | **action** ASK / CONFIRM_VARIANTS |
| ru-026 | я выбираю между Clase C Berlina мерседесом и Маздой CX-60 | **action** ASK / CONFIRM_VARIANTS |
| ru-028 | hybrid 155 | **action** REPORT / CONFIRM_VARIANTS |
| ru-031 | Find the missing data: all | **language** ru / en |
| ru-032 | Мне 20, могу купить б/у BMW 320d M Sport или Golf R-Line 4Motion — сравни на дра | **action** ASK / ANSWER_GENERAL<br>**changes** add_cars ['BMW 3 Series', 'Volkswagen Golf'] / []; persona PERFORMANCE / UNKNOWN; age 20 / None; usage True / [] |
| ru-033 | ну дак сравни byd seal u с сеатом атека 1.5 двигателя | **answer** option:q:car#1:MAKE_LINEUP:0 / value:None<br>**goals** ['compare'] / []<br>**action** ASK / CONFIRM_VARIANTS |
| ru-034 | BYD это компания Build your dream китайская представленная в европе | **answer** none / value |
| ru-036 | спасибо, а теперь добавь Kia Sportage | **action** ASK / CONFIRM_VARIANTS |
| ru-037 | найди мне подходящую kia для замены моего ленд круер прадо 150 возрастом 15 лет | **changes** add_cars ['Toyota Land Cruiser Prado'] / []; replaced_car Toyota Land Cruiser Prado / [] |
| ru-038 | б/у | **answer** option:q:-:BUDGET_INTENT:1 / value:None<br>**action** SELECT_CANDIDATES / ANSWER_GENERAL |
| ru-039 | автомат | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS<br>**changes** car#1.gearbox automatic / None |
| ru-040 | выбери сам, любой | **language** ru / en<br>**answer** choose_for_me:None / option:None<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-041 | любая версия, мне всё равно | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-042 | возьми любую, на твой выбор | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-043 | любое исполнение — на ваш выбор, неважно | **language** ru / en<br>**answer** choose_for_me:None / option:None<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-044 | выбери ты, не важно какой | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-045 | вперед к сравнению | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| ru-046 | поехали, вперёд | **action** RESEARCH / CONFIRM_COST |
| ru-047 | давай, запускай | **action** RESEARCH / CONFIRM_COST |
| ru-048 | нет, дорого | **action** REPORT / CONFIRM_COST |
| ru-051 | достаточно, ответь по тому, что уже собрано | **answer** no:None / yes:None<br>**action** REPORT / RESEARCH |
| ru-052 | ок, сравнивай | **answer** yes:None / None:None<br>**goals** [] / ['compare']<br>**action** RESEARCH / CONFIRM_VARIANTS |
| ru-053 | стоп, а у Prado какой расход? | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| ru-054 | да ладно, а сколько стоит обслуживание Sportage? | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| ru-055 | 1.6 гибрид, и добавь ещё Toyota RAV4 | **answer** option:q:car#1:ENGINE:0 / value:None<br>**goals** ['compare'] / []<br>**action** ASK / CONFIRM_VARIANTS<br>**changes** add_cars ['Toyota RAV4'] / [] |
| es-001 | para mi familia | **goals** [] / ['compare']<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-003 | busco un Kia Sportage para sustituir mi Qashqai de 2012 | **action** ASK / CONFIRM_VARIANTS<br>**changes** add_cars ['Kia Sportage', 'Nissan Qashqai'] / ['Kia Sportage'] |
| es-004 | Vivimos en Sevilla y hacemos unos 18.000 km al año. ¿BYD Seal U DM-i o SEAT Atec | **action** ASK / CONFIRM_VARIANTS |
| es-005 | no es ese, quiero el diésel | **answer** no:None / None:None<br>**action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#2', 'VERSION')] / [] |
| es-006 | otro, ese no | **answer** no:None / None:None<br>**action** ASK / CONFIRM_VARIANTS |
| es-007 | no encontraste el Clase C, me has puesto el Clase E | **answer** no:None / None:None<br>**action** ASK / CONFIRM_VARIANTS |
| es-008 | para, cancela la búsqueda | **answer** none / value<br>**goals** ['stop'] / []<br>**action** ANSWER_FROM_CONTEXT / CONFIRM_VARIANTS |
| es-009 | olvídalo, cancela todo | **answer** none / value<br>**goals** ['stop'] / []<br>**action** ANSWER_FROM_CONTEXT / CONFIRM_VARIANTS |
| es-010 | fatal, no has encontrado nada | **answer** none / value<br>**goals** [] / ['critique']<br>**action** ASK / CONFIRM_VARIANTS |
| es-012 | si es diésel mejor | **goals** [] / ['change_priorities']<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-013 | ¿vale la pena un híbrido enchufable si no puedo cargar en casa? | **goals** ['ask_general'] / ['follow_up']<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| es-014 | ¿sigue siendo fiable el motor 1.5 TSI? | **action** ANSWER_AND_REASK / RESEARCH |
| es-015 | no sé cuál, ¿cuál gasta menos? | **answer** none / value<br>**goals** ['follow_up'] / ['change_priorities']<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| es-016 | sí, y añade un Toyota RAV4 | **answer** yes:None / None:None<br>**action** ASK / CONFIRM_VARIANTS |
| es-018 | sí | **action** RESEARCH / CONFIRM_VARIANTS |
| es-019 | vale | **action** RESEARCH / CONFIRM_VARIANTS |
| es-020 | Ahora no | **answer** option:stop / no:None<br>**action** REPORT / CONFIRM_VARIANTS |
| es-022 | el del diésel, el 2.0 TDI | **answer** option:option:car#2:20tdi-dsg / None:None<br>**goals** [] / ['compare']<br>**action** RESEARCH / CONFIRM_VARIANTS |
| es-024 | no, es demasiado caro | **action** REPORT / RESEARCH |
| es-025 | ¿cuánto tarda la investigación? | **goals** ['ask_general'] / ['follow_up']<br>**action** ANSWER_AND_REASK / RESEARCH |
| es-030 | Seguir investigando | **answer** option:continue / None:None<br>**goals** [] / ['research_more'] |
| es-031 | Automático | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-032 | me da igual, elige tu | **language** es / en<br>**answer** choose_for_me:None / option:None<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-033 | cualquiera vale | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-034 | elige tú el motor | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| es-035 | compara ya | **action** RESEARCH / CONFIRM_VARIANTS |
| es-036 | es el 1.5, no el 1.0 | **answer** option:q:car#1:ENGINE:1 / value:None<br>**action** CONFIRM_INTAKE / CONFIRM_VARIANTS<br>**changes** car#1.displacement_l 1.5 / 1.0 |
| es-037 | de segunda mano | **action** ASK / CONFIRM_VARIANTS<br>**changes** car#1.condition USED / UNKNOWN; car#2.condition USED / UNKNOWN |
| es-038 | tengo dos hijos y un perro | **goals** [] / ['compare'] |
| es-039 | mi presupuesto es de 30.000 €, nuevo | **goals** [] / ['compare']<br>**action** ASK / CONFIRM_VARIANTS |
| es-040 | lo quiero para unos 10 años | **goals** [] / ['compare'] |
| es-041 | Toyota Corolla o Nissan Qashqai, y que tenga un color bonito | **action** ASK / CONFIRM_VARIANTS |
| es-042 | somos cinco y llevamos mucho equipaje en vacaciones | **goals** [] / ['change_priorities']<br>**action** REPORT / ANSWER_FROM_CONTEXT<br>**changes** passengers 5 / None |
| es-043 | quiero el acabado R-Line | **answer** none / value<br>**action** ASK / CONFIRM_VARIANTS |
| es-045 | unos 1.500 km al mes | **goals** [] / ['compare'] |
| es-046 | ¿puedes reformularlo? no lo entiendo | **answer** none / value<br>**goals** [] / ['follow_up']<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS<br>**reaction** rephrase / None |
| en-001 | answer me about fuel | **answer** none / value<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| en-002 | do you have any... | **answer** none / choose_for_me<br>**goals** ['follow_up'] / []<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| en-003 | I don't want to spend too much, but I don't want rubbish either. A brand-new Dac | **action** ASK / ANSWER_GENERAL<br>**changes** add_cars ['Dacia Bigster', 'Toyota Land Cruiser Prado'] / []; persona BUYER / UNKNOWN; priorities True / [] |
| en-004 | about 10 years old, the 150 | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-005 | but i asked about used 10 yrs old LC prado 150 not new | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-007 | the same, but I'm a car engineer | **changes** persona EXPERT / UNKNOWN |
| en-008 | no, I meant the old one, the 150 | **action** CONFIRM_INTAKE / ASK |
| en-010 | used, about 5 years | **answer** option:condition:USED / value:None<br>**action** ASK / CONFIRM_VARIANTS |
| en-011 | I want a Hyundai instead of my 2014 Golf, something for the family | **action** SELECT_CANDIDATES / ASK<br>**changes** add_cars ['Volkswagen Golf'] / ['Hyundai', 'Ford']; replaced_car Volkswagen Golf / []; usage True / [] |
| en-012 | and for a smart buyer? | **changes** persona BUYER / UNKNOWN |
| en-013 | We are a family in Seville, about 18,000 km a year. BYD Seal U DM-i or SEAT Atec | **changes** add_cars ['BYD Seal U', 'SEAT Ateca'] / ['BYD', 'SEAT'] |
| en-014 | Deep research please: Skoda Octavia RS, Cupra Leon VZ and Peugeot 308 | **action** CONFIRM_INTAKE / ASK<br>**changes** add_cars ['Skoda Octavia', 'Cupra Leon', 'Peugeot 308'] / ['Skoda', 'Cupra', 'Peugeot'] |
| en-015 | proceed | **action** RESEARCH / CONFIRM_COST |
| en-016 | sure, run it | **action** RESEARCH / CONFIRM_COST |
| en-017 | too expensive, skip it | **action** REPORT / CONFIRM_COST |
| en-018 | running costs matter most to me | **goals** [] / ['change_priorities'] |
| en-019 | go ahead | **action** RESEARCH / CONFIRM_COST |
| en-024 | yes | **action** RESEARCH / CONFIRM_VARIANTS |
| en-025 | Not now | **answer** option:stop / no:None<br>**action** REPORT / CONFIRM_VARIANTS |
| en-026 | no | **action** ASK / CONFIRM_VARIANTS |
| en-027 | ok so how much is the plug-in to run per month? | **action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| en-028 | yes, but make it AWD | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-029 | no idea what DSG means | **answer** none / value<br>**goals** ['ask_general'] / []<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |
| en-031 | the second one | **answer** option:option:car#1:mk75-20tdi / None:None<br>**goals** [] / ['compare']<br>**action** RESEARCH / CONFIRM_VARIANTS |
| en-032 | nein nein, not that one | **answer** no:None / None:None<br>**action** ASK / CONFIRM_VARIANTS |
| en-033 | wrong generation, it's a Golf 7 from 2015, not a 7.5 | **answer** no:None / None:None<br>**action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#1', 'GENERATION')] / [] |
| en-034 | you didn't find the R-EV, that's the electric one | **action** ASK / CONFIRM_VARIANTS<br>**rejections** [('car#1', 'ENGINE')] / [('car#1', 'VERSION')] |
| en-035 | stop, cancel the search | **answer** none / value<br>**goals** ['stop'] / []<br>**action** ANSWER_FROM_CONTEXT / CONFIRM_VARIANTS |
| en-037 | terrible, you found nothing | **answer** none / value<br>**goals** [] / ['critique']<br>**action** ASK / CONFIRM_VARIANTS |
| en-038 | thanks! now compare it with a Skoda Kodiaq | **action** ASK / CONFIRM_VARIANTS |
| en-039 | whatever, doesn't matter, you choose | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-040 | I don't care, choose for me | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-041 | any is fine, dont care | **action** CONFIRM_INTAKE / CONFIRM_VARIANTS |
| en-043 | Tesla Model 3 or BMW 320d, no more than €150 a month to run it | **action** ASK / CONFIRM_VARIANTS |
| en-044 | who wins a drag race in the wet with two passengers? I bet the Golf | **goals** [] / ['compare'] |
| en-045 | the purple one | **answer** none / value<br>**action** ANSWER_AND_REASK / CONFIRM_VARIANTS |

## Errors

