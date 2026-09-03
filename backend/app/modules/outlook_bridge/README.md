# Outlook Bridge (`oe_outlook_bridge`)

The **outbound** email engine for the correspondence register: register
emails go out as properly-formatted Outlook drafts or an editable `.eml`.
Ported from the source workflow app's email engine.

Reading a mailbox (inbound capture) is deliberately **not** part of this
build - the register is fed by replies filed by hand instead, so nothing
here connects to, sweeps, or reads an inbox.

## Outbound - three ways to the same email

ONE payload builder (`service.build_email_payload`) stands behind all
three, so the preview is byte-for-byte what gets sent:

| Path | Endpoint | When |
|---|---|---|
| **Preview** | `POST /preview/{correspondence_id}` | always - renders in-app, no side effects |
| **Outlook draft (COM)** | `POST /draft/{correspondence_id}` | backend on the user's own Windows box |
| **.eml download** | `POST /eml/{correspondence_id}` | **self-hosted server + browser** - Outlook opens the file as an editable unsent draft |

Send is never automated. The COM path preserves the user's saved Outlook
signature (`GetInspector` before the body edit); the `.eml` path cannot
(Outlook does not inject signatures into an opened .eml).

### The livery
`outbound.build_register_email_html` reproduces the planner engine's
design system: grey page, one centred white card, 4px orange bar, navy
hero with orange micro-caps eyebrow, navy2 project sub-bar with a 3px
orange left border, 2px-navy-ruled section heads, zebra details, tiny
slate footer. **Outlook renders with the Word engine**, so the markup is
table-based with `bgcolor` attributes, `nowrap="nowrap"` attributes and
`&nbsp;` spacing - never CSS margins, flex or `white-space`.

### The plain-text part
Every generated message is multipart: the livery above **and** a real
`text/plain` alternative built from the same structured content by
`outbound.build_register_email_text`. It used to be a single stub line
("This message requires an HTML-capable mail client"), so any recipient,
gateway or filter that preferred plain text was sent a request
containing no request. Payloads that arrive as HTML and nothing else
fall back to `app.core.email.textify.html_to_text` - block tags become
line breaks, table cells join with " | ", entities are decoded - never
back to the stub.

### The money rail
`INTERNAL_LABELS` (estimated value, cost, sell, margin, cost impact,
budget) are stripped **inside both builders** (HTML and text), so no
caller can leak an internal figure by skipping a step.

### Standing CC
`OE_OUTLOOK_CC` (empty by default) is copied on every register email when
set - the loop that brings replies back to a monitored address. The
organisation supplies the address; none is baked into the code.

## Configuration

| Env var | Default | What |
|---|---|---|
| `OE_OUTLOOK_CC` | (empty) | standing CC on register emails, comma-separated |

## Server deployment note

COM automation needs desktop Outlook on the machine running the backend.
On a self-hosted server reached through a browser the outbound path is the
**.eml download** - it works from any browser on any OS, no COM required.
