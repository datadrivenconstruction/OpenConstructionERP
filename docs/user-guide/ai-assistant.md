# The AI assistant: an assistant that prepares, a person who approves

The AI assistant is a colleague you give instructions to. You tell it what needs doing in plain words, "add a task for the site team to check the formwork on level 3 by Friday", "set position 03.012 to 120 m3", "log a risk: the steel delivery is three weeks late", and it prepares the change for you. Nothing reaches your project until a person looks at the prepared change and clicks Apply. Every change it prepares, every change a person applies, rejects or undoes, is recorded with who asked, who approved and when.

## What it is for

A director or a lead manager often knows exactly what should change and simply has no time to open five screens to change it. The assistant closes that gap. It reads the project the way a colleague would, the bill of quantities, the tasks, the schedule, and turns an instruction into a ready-to-check change: the right bill, the right position, the right person, the date spelled out. You stay the one who decides. The assistant never saves anything on its own word, and it never has more rights than the person who clicks Apply.

It also answers questions. Ask for the budget of a project, the open RFIs, the tasks due this week or the positions without a rate, and it looks them up and shows the answer inline.

## Opening it

Click the round sparkle button at the bottom right of any page, or press Alt+A (Option+A on a Mac). On a wide screen the assistant opens as a panel at the side and the page moves over to make room, so nothing you were working on is covered. Drag the panel's inner edge to make it wider or narrower; the width is remembered. On a narrow screen, or when the page would get too tight, the panel opens over the page instead and closes with Escape. Press Alt+A again, or the close button, to put it away. In right-to-left languages the panel opens on the left.

The panel has two tabs. Chat is the conversation. Changes is the ledger of every change the assistant has prepared. The chip next to the tabs shows which project the assistant is working in: it follows the project you have open.

## Giving an instruction

Write the way you would brief a colleague: what, where, and any value you already know. The assistant asks when something is ambiguous, for example when a project has two bills and you did not say which one, rather than guessing. You can group several changes in one message, and they arrive together.

Today the assistant can prepare these changes:

- add a position to a bill of quantities, or change the quantity, rate, unit or description of an existing one
- create a task with an assignee, a due date and a priority
- raise an RFI
- log a risk with its probability, impact and mitigation
- add a punch list item
- set the progress of a schedule activity

The empty chat shows a few example instructions that fit the page you are on. Click one to use it as a starting point.

## Reviewing a prepared change

Each prepared change arrives as a card in the conversation. The card names the kind of change and where it lands, then lists every field it would set. For a change to an existing record the old value is shown struck through next to the new one, so you see exactly what moves. A confidence badge tells you how sure the assistant is, and Why? opens the one-line reason it gives for the change.

You then have three choices. Apply saves the change, running the same checks the platform runs when you make the change by hand: your role, your access to the project, a locked bill, a record someone else changed in the meantime. Edit lets you correct any editable field before applying, and the card remembers that a person changed it. Reject discards the change and keeps it in the ledger as rejected.

When a conversation holds several waiting changes, a bar above the message box says how many are waiting. Review scrolls to the first one; Apply all applies them one by one after you confirm the list, and reports any that could not be applied, each on its own card.

## After applying

An applied card says who applied it and when, and offers Open, which takes you to the record, and Undo. Undo restores the record as it was, but only while nobody has changed it since; if someone has, the platform refuses rather than overwrite their work. Some consequences cannot be taken back, and the card says so before you confirm: the number of an undone RFI or the code of an undone risk may be given to the next one, notifications that already went out stay sent, and a schedule activity gets its old progress back but its status is worked out again from that progress.

If applying fails, for example because the bill was locked in the meantime, the card shows the reason and a Retry button. Nothing is half-saved.

## The Changes tab

Changes is the assistant's ledger. It lists every prepared change, grouped by day, with filters for Waiting, Applied, Rejected, Undone and All, scoped to the current project or to all your projects. Each row shows who asked for the change, who approved it and at what time, and opens into the full card. Waiting rows can be applied or rejected right there, applied rows can be undone.

The same history is part of the platform's audit trail. Every applied or undone change is written to the project's activity log, marked as made through the AI assistant together with the names of the person who asked and the person who approved, so it appears in the project Timeline and in the administrator's audit log next to changes made by hand. The link at the foot of the Changes tab opens the project's full history.

## Requirements

The assistant uses the AI provider your organisation connects under Settings, AI, with your own API key. Preparing changes needs a provider that supports tool calling; with a provider that does not, the assistant still answers in plain text and tells you it cannot prepare changes. Without any key the rest of the platform works as usual and the assistant explains how to connect one.

## How it connects

The assistant works on the same records as the rest of the platform, so a position it prepares lands in the [bill of quantities](./estimating-and-boq.md) like any other, is checked by the [validation pipeline](./validation.md), and flows on into [planning and cost control](./planning-and-cost-control.md). Tasks, RFIs, risks and punch items it prepares appear in the project's lists and in [field and site operations](./field-and-site.md) exactly as if a person had entered them, with the difference that the audit trail also names the assistant.
