# Comms Intelligence (`oe_comms_intelligence`)

A smart layer over the correspondence register. Built for a project team /
a project team to replace the RFQ/RFI comms machinery of the source workflow app
Portfolio app with native OpenConstructionERP workflows.

## What it does

- **Auto-classifies every inbound message** the moment `correspondence.created`
  fires (email via Inbound Capture, webhook, SMS, or hand-entered): quote,
  RFI response, variation notice, delay notice, instruction, claim, approval,
  delivery, or general.
- **Extracts structured facts**: prices (exact decimal strings, currency,
  context), quote numbers, register references (RFI-12, COR-005, REG-RFQ-…),
  response-requested-by dates (Australian d/m/y), commitments.
- **Suggests actions** — set status, set the response deadline, link an RFI —
  and applies them ONLY when a person confirms (partial confirmation
  supported). Confirmed extractions are filed on the correspondence row's
  metadata under `comms_intelligence`.
- **Drafts replies and chase-ups** — AI when a provider key is configured in
  Settings > AI, a visibly-skeletal fill-in template otherwise. Text only;
  nothing is ever sent from this module.
- **Dashboard** — who owes whom a response: overdue, due soon (3 days),
  awaiting; pending-review and reply-needed counts; category breakdown.

## Design rules honoured

- **AI-augmented, human-confirmed** (MODULES.md rule 4): every suggestion
  carries a confidence score; no register mutation without an explicit
  confirm from an authenticated editor.
- **Two-tier pipeline**: pure-stdlib heuristics always run (free, instant,
  no key needed); the LLM pass (`use_ai=true` on POST …/analyze) merges
  OVER the heuristic floor — facts a regex found verbatim can never be
  lost to a model miss, and a hallucinated RFI link is fenced to the
  candidate list actually offered.
- **Token budget safety**: the event-bus auto-analysis is heuristic-only.
  AI tokens are only spent on an explicit request.
- **Receipts** (RFC 36): `raw_response`, `model_name`, `prompt_version`,
  `tokens_used` and a cost estimate are stored on every analysis.

## API

Mounted at `/api/v1/comms-intelligence/`:

| Endpoint | What |
|---|---|
| `GET /analyses?project_id=&status=` | review queue |
| `POST /analyses/{correspondence_id}/analyze` | run/re-run (`{"use_ai": bool}`) |
| `POST /analyses/{analysis_id}/confirm` | apply ticked suggestions |
| `POST /analyses/{analysis_id}/dismiss` | reject |
| `GET/POST /drafts…`, `PATCH /drafts/{id}` | reply/chaser drafts |
| `GET /dashboard?project_id=` | deadline + review aggregates |

Permissions: `comms_intelligence.read` (viewer), `.analyze`, `.review`,
`.draft` (editor).

## Tests

`backend/tests/modules/comms_intelligence/` — 14 tests: heuristic
extraction (incl. d/m/y dates and the unmarked-number rule), suggestion-only
invariant, event handler isolation, partial confirm, double-review conflict,
AI-unavailable honesty, merge fencing, hostile-value clamping, template
chaser, dashboard bucket exclusivity.
