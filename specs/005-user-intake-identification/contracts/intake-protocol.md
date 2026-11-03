# Contract: Intake Protocol Additions (005)

These additions extend protocol v2 (specs 002–004) and remove nothing. Older clients show an unknown `confirm_request` kind as text plus option buttons, so they still work.

## Server → client

### confirm_request, kind "intake" (the confirmation card, FR-019–FR-021)

```jsonc
{
  "type": "confirm_request", "kind": "intake", "action": "CONFIRM_INTAKE", "request_id": "…",
  "text": "Проверьте, что я понял, и подтвердите — после этого начну исследование.",   // conversation language
  "options": [ { "id": "yes", "label": "Да, исследовать" }, { "id": "stop", "label": "Пока не надо" } ],
  "estimate": { "eur": 0.42, "cars": 2, "areas": ["specs", "reliability", "maintenance", "price"], "depth": "STANDARD" },
  "card": {
    "cars": [
      { "key": "car#1", "display_name": "BYD Seal U DM-i",
        "items": [
          { "field": "model", "value": "Seal U", "basis": "STATED", "evidence": "BYD Seal U допустим" },
          { "field": "engine", "value": "1.5 PHEV 218 CV", "basis": "LOOKED_UP",
            "source": { "name": "byd.com/es", "url": "https://www.byd.com/es/…", "retrieved_at": "…" },
            "options": ["Seal U EV (eléctrico)"] },
          { "field": "condition", "value": "новый", "basis": "ASSUMED" },
          { "field": "price_eur", "value": "€35 990", "basis": "LOOKED_UP", "source": { … } }
        ] },
      { "key": "car#2", "display_name": "SEAT Ateca 1.5 TSI 150 CV DSG",
        "items": [
          { "field": "engine", "value": "1.5 TSI 150 CV", "basis": "STATED", "evidence": "1.5 двигатель",
            "changed": true, "before": "1.0 TSI 110 CV" } ] }
    ],
    "profile": [
      { "field": "usage", "value": "семья; город и трасса", "basis": "INFERRED", "evidence": "семейной… по городу и за" },
      { "field": "annual_km", "value": "12 000–24 000 км/год", "basis": "STATED", "evidence": "1-2 тыс км в месяц" },
      { "field": "region", "value": "юг Испании (жаркий климат)", "basis": "INFERRED", "evidence": "на юге испании" }
    ]
  }
}
```

`card` is optional for other kinds. Each `basis` is one of `STATED`, `INFERRED`, `LOOKED_UP` or `ASSUMED`. When the basis is LOOKED_UP, `source` is required. When the basis is INFERRED, `evidence` is required. Each `options` entry is shown as a chip.

### assistant_message during the intake (questions, proposals)

There is no new block type. Questions keep using the `quick_replies` block, now with concrete options:

```jsonc
{ "type": "quick_replies", "question": "MODEL",
  "items": [ { "label": "BYD Seal U DM-i (PHEV, SUV)", "text": "BYD Seal U DM-i", "suggested": false },
             { "label": "BYD Atto 3 (eléctrico, SUV)", "text": "BYD Atto 3", "suggested": true,
               "reason": "семейный SUV, дешевле в обслуживании" },
             { "label": "Выбери сам", "text": "Выбери сам" } ] }
```

Constraints:
- `items` is never empty. A question without options has no `quick_replies` block.
- `suggested: true` marks a model the user did not name. The UI shows it as a suggestion.

A correction shows a notice in the conversation language: `{ "type": "notice", "level": "info", "text": "SEAT Ateca 1.0 TSI 110 CV → 1.5 TSI 150 CV DSG" }`.

## Client → server

```jsonc
{ "type": "intake_edit", "request_id": "…", "car_key": "car#2", "field": "engine", "value": "1.5 TSI 150 CV" }
{ "type": "intake_edit", "request_id": "…", "car_key": null, "field": "annual_km", "value": "20000" }
{ "type": "confirm", "request_id": "…", "choice": "yes" }          // existing message: the card's yes
```

- `intake_edit` is applied by code, with no model call. The server answers with a new `confirm_request` of kind "intake", and the edited items carry `changed: true`.
- Free text while the card is shown keeps working: it is a `confirm` with `choice: "text"`, as today, and is interpreted as a correction.

## Invariants (checked in graph tests and goldens)

1. No `assistant_message` repeats the previous question text for the same car and item.
2. While an intake step is pending, no `assistant_message` comes from the `general` role.
3. Every text in an intake message is in `assistant_message.language`.
4. `research_jobs` are created only after `confirm(choice: "yes")` on a `kind: "intake"` card, or on a CONFIRM_VARIANTS card in chats started before 005.
