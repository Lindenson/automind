# Contract: WebSocket feedback messages

Client → server on `ws://…/ws/chat/{id}` (existing socket).

## bad_source (new)
```json
{"type": "bad_source", "message_id": "<assistant message id>", "url": "https://…", "car_id": "car#1"?, "attribute": "power_kw"?, "area": "specs"?, "text": "optional note"?}
```
Server: validates the chat owner (existing socket auth), stores a `feedback` row (`kind=bad_source`), a `truth_signal` (`verdict=wrong`, weight 1, blame `source`) on the capability `(domain(url), area, market of the evidence)` when resolvable, patches the turn outcome (`signals.bad_source += 1`, class `wrong_data`). Replies:
```json
{"type": "feedback_ack", "kind": "bad_source", "url": "https://…"}
```
Unknown or deny-listed URL → ack with `"ignored": true`. Max 20 per chat per hour (silently ignored above).

## rating (existing, extended behaviour)
Unchanged message. Also writes `feedback(kind=rating)` and patches the outcome score of the message's turn.

## challenge (existing, extended behaviour)
Unchanged message and `challenge_result`. Also writes `feedback(kind=wrong_value, outcome)`, fills `value_challenges.turn_id/claim_id`, writes truth signals per claim (CONFIRMED → right; CORRECTED/REMOVED → wrong with blame from the excerpt check), patches the outcome.

## Frontend
- `SourceItem` (components/badges.tsx) shows a small "bad source" action on accepted sources; after ack it shows "noted".
- `lib/protocol.ts`: `BadSourceOut`, `FeedbackAckSchema` (zod).
