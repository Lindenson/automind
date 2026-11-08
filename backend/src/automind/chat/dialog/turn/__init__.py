"""A chat turn's life, apart from the logic of the dialog (code-shape "States, not words").

Flow: `runner.ChatRunner` (one task per chat) → `entry.route` (what a message does: start, answer the open
question, replace it, busy) → `execution.TurnExecution.run` (budget → RUNNING → graph → question | answer, or an
early `endings` reply, cancel, failure) → `replies.TurnReplies` (store, events) → `outcome.OutcomeRecorder`.
Every status write goes through `journal.TurnJournal.move`, checked against `chat.domain.turn.TRANSITIONS`.

Modules:
- `context` — `TurnContext`: what every graph node receives (ports, ids, budget, events);
- `entry` — `Entry`, `route(open_turn, preset_kind)`: the pure decision table of the runner;
- `endings` — `Ending`, `ending_for(error)`: limit, timeout, loop, provider down → a plain answer;
- `journal` — `LiveTurn`, `TurnJournal`: status writes through the lifecycle table;
- `execution` — `TurnExecution`: one run of the graph to the turn's end;
- `replies` — `TurnResult`, `TurnReplies`: the answer (DONE) or the question (WAITING);
- `outcome` — `OutcomeRecorder`, `FeedbackKind`: the outcome row, metrics, feedback on the previous answer.
"""

__all__: list[str] = []
