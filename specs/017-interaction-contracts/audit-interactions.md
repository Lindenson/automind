# Audit: every user interaction and its tests (2026-11-28)

Paths under `backend/` unless stated; `tests/graph/X:name` = a test in that file. "E2E" below means a full turn through
the runner (`run_turn` / `resume`); only `test_feedback.py` drives the socket class `ChatSocket`.

## Routing

- Socket messages: `src/automind/delivery/web/ws.py:67-91`; client shapes `frontend/src/lib/protocol.ts:1094-1160`;
  senders `frontend/src/store/chat.ts:416-560`.
- `PresetKind` (`chat/domain/turn.py:62-72`): research_more, car_edit, rescore, report_saved, pick; car_edit, rescore
  and report_saved are stored with the hidden role `edit`.
- Entry (`chat/dialog/turn/entry.py:37-46`): no open turn → new turn; a running turn → busy; an open question → typed
  text and "find it" answer it, car_edit cancels it and starts a turn, rescore / report_saved are refused.
- Open question kinds (`chat/domain/understanding/open_question.py:25-32`): QUESTIONS, CONFIRM_VARIANTS,
  CONFIRM_COST, CONFIRM_INTAKE, LIMIT. Confirmations: `chat/dialog/graph.py:53-68`, pause `nodes/confirm.py:190`,
  button ids `chat/domain/intake/card_choice.py:51`.

## Inventory

| Interaction | Sent as | Handled at | Unit | E2E | Frontend |
|---|---|---|---|---|---|
| Typed message | `user_message{text}` | `ws.py:76-81` → `runner.py:59` | `test_typed_words_never_confirm.py` | many (`test_runner.py`, `test_intake_card.py`, `test_corrections.py`) | `quickWins.test.tsx` |
| Chip (`pick`) | `user_message{text, option_id}` | `ws.py:80,263` → `interpretation/service.py:81` | `test_pick_preset.py`, `test_service.py` (2), `test_option_ids.py`, `test_open_question.py` | **none** (`test_version_question.py` sends the chip as text) | `quickReplies.test.tsx` |
| Choose for me | chip `choose` or words | `service.py:119`, `card_choice.py:37` | `test_service.py`, `test_identification.py`, `test_version_ladder.py` | typed only | — |
| Intake card yes / not now | `confirm{yes|stop}` | `confirm.py:408,433` | `test_typed_words_never_confirm.py` | yes only; **"stop" none** | — |
| Intake card field edit | `intake_edit{car_key, field, value}` | `ws.py:88,252` → `confirm.py:392` | `test_intake_card_profile.py` | engine only | render only |
| Variants confirm / option / remove / skip | `confirm{choice}` | `confirm.py:197` | `test_confirm_variants_cost.py` | confirm, remove; **option, skip none** | — |
| Cost run / skip | `confirm{run|skip}` | `confirm.py:263` | `test_apply_cost_*` | skip; **run none** | — |
| Feasibility choices | `confirm{choice}` | `nodes/feasibility.py:50` | `test_pending.py` | `test_feasibility_flow.py` (2) | — |
| Limit continue / stop | `confirm` or words | `nodes/research.py:117` | `test_limit_pause.py` | `test_limit_pause.py` (3) | — |
| Change generation / engine / gearbox / trim / not_this_car / remove | `car_edit` | `ws.py:82,269` → `service.py` → `car_view.py edit_delta` | `test_service.py` (remove, unknown car, not_this_car ×3 since PR #163) | **engine only** | `carEdit.test.tsx` |
| Find it (panel, suggestions) | `find{focus_cars, areas}` | `ws.py:95` → `service.py:88` | several | `test_find_it.py`, `test_research_flow.py` | render only |
| Find it (verdict card) | typed `user_message` (`Verdict.tsx:123`) | interpreter | — | **none** | render only |
| Panel PATCH (persona, profile, budget, …) | `PATCH /api/v1/chats/{id}/case` | `rest.py:217,364`; rescore worker `:328` | `test_case_patch.py` (6) | `test_rescore.py`, `test_rescore_queue.py`, `test_weights_recompute.py`, `test_three_profiles.py` | **none** |
| Weights slider / reset | PATCH `{weights}` / `{reset_weights}` | `rest.py:394-400` | `test_case_patch.py`, `test_weights.py` | **none** | **none** |
| Report from saved data | system (`runner.py:153`) | `policy/rules/limits.py:37` | `test_entry_and_endings.py` | `test_robustness.py` | — |
| Stop / cancel | `cancel` | `ws.py:90` → `runner.py:83` | `test_turn_lifecycle.py` | `test_cancel_and_resume.py`, `test_runner.py` | `store/chat.test.ts` |
| Error retry / continue | typed `user_message` | interpreter | — | **none** | `auditFollowUp.test.tsx` |
| Rating | `rating` | `ws.py:126` | — | `test_feedback.py` (socket) | `quickWins.test.tsx` |
| Bad source | `bad_source` | `ws.py:167` | `test_outcome.py` | `test_feedback.py` (socket) | `badSource.test.tsx` |
| Challenge | `challenge` | `ws.py:110` | `test_gold_services.py` | `test_challenge.py`, `test_feedback.py` | `carEdit.test.tsx` |
| Reconnect | `hello{last_seq}` | `ws.py:69,199` | — | `test_limit_pause.py` | `auditFollowUp.test.tsx` |
| Delete chat | `POST /api/v1/chats/delete` | `rest.py:126` | — | `test_delete_chat.py` | `lib/chats.test.ts` |
| Language picker | client only, never sent | — | — | — | `i18n.test.ts` |

## Gaps

1. No socket-level test for `user_message`, `confirm`, `intake_edit`, `car_edit`, `find`, `cancel`;
   `ws.py _resume_payload` / `_car_edit_preset` untested.
2. Chip `option_id`: no full-turn test; `runner.py:72` resumes an open question with `{"choice": "text"}` and drops
   the id.
3. Change: only engine has a full turn.
4. Untested answers: variants `option:` and skip; cost "run"; card "not now"; `edit_field` other than engine.
5. Weights slider / reset: no e2e; CasePanel / `patchCase` no frontend test.
6. "Find it" on the verdict card is free text, untested.
7. The frontend never sends `language`; the server reads it.
8. Frontend tests never check the `confirm`, `intake_edit` or `find` payloads.
9. 007 contract says PATCH during a turn → 409; the code queues it.
10. What an action must keep is written for FR-035–FR-039 (010), T012/T013 (013), FR-014 (007) and in docstrings only.
