# Extend, do not fork

The point of the module system is that you change behaviour by adding code at
defined extension points, not by editing core files. A fork drifts from upstream
and turns every platform release into a merge conflict. A module upgrades
cleanly because it only touches the surfaces the core promises to keep stable.

This page covers the three ways to change behaviour without editing core: react
to events, transform data with filters, and run side effects with actions. All
three live in your own module's files, which the loader auto-imports.

## Pick the right tool

| You want to | Use | Where it lives | On failure |
| --- | --- | --- | --- |
| Do something after an event happened | Event subscriber | `events.py` | logged, other handlers still run |
| Change a value as it passes a named point | Filter hook | `hooks.py` | raises and stops the chain |
| Run a side effect at a named point | Action hook | `hooks.py` | logged and swallowed |
| Add a check to the validation engine | Validation rule | `validators.py` | isolated per rule |
| Add new API, tables or screens | A new module | your package | module fails to load in isolation |

The loader imports `events.py`, `hooks.py` and `validators.py` for their
import-time side effects, so registering a handler is just defining it in the
right file. Nothing else wires them.

## React to events

An event says "this happened". Subscribing lets your module respond without the
producing module knowing you exist. Handlers receive an `Event` with `name`,
`data`, `id`, `timestamp` and `source_module`.

In your module's `events.py`:

```python
from app.core.events import event_bus, Event


@event_bus.on("oe_site_log.item.created")
async def notify_on_new_entry(event: Event) -> None:
    entry_id = event.data["id"]
    # send a notification, update a cache, kick off enrichment, etc.
    ...
```

Good to know:

- Names are dot-notation, `{module}.{entity}.{action}`. Subscribe to exactly the
  name the producer publishes. The tutorial module publishes
  `oe_site_log.item.created`, which is a guaranteed-real target to try.
- Handlers can be `async def` or plain `def`. A sync handler runs in a thread so
  it never blocks the event loop.
- A failing subscriber is caught and logged, and the other subscribers still
  run. One handler cannot break another, or the producer.
- `@event_bus.on("*")` subscribes to every event, which is handy for audit or
  logging modules.

To discover what is currently wired, call `event_bus.list_handlers()`.

## Transform data with filter hooks

A filter says "let modules shape this value before I use it". Core calls
`apply_filters(name, value, ...)` at a point it chooses to expose, and your
filter receives the value, returns a new one, and passes it along the chain in
priority order.

In your module's `hooks.py`:

```python
from app.core.hooks import hooks


@hooks.filter("boq.position.before_save", priority=10)
async def stamp_default_unit(position: dict) -> dict:
    position.setdefault("unit", "m2")
    return position
```

Points to keep in mind:

- Lower `priority` runs earlier. Chain output feeds the next handler.
- A filter error propagates. Because a filter sits on a data path, a failure
  raises rather than silently corrupting the value, so keep filters total and
  fast, and return the value you received when you have nothing to change.
- A filter only fires where core actually calls
  `await hooks.apply_filters("boq.position.before_save", position)`. The hook
  name is a contract the core offers at that spot, not a way to intercept any
  function. `hooks.list_filters()` shows the registered filters.

## Run side effects with action hooks

An action says "modules may do something extra here", and it never changes the
value or the outcome of the operation it hangs off.

```python
from app.core.hooks import hooks


@hooks.action("boq.export.completed")
async def archive_export(boq_id: str) -> None:
    ...
```

Core fires it with `await hooks.do_actions("boq.export.completed", boq_id=boq_id)`.
Action errors are logged and swallowed, so a failing action cannot break the
export it observes. Use an action when you want to add behaviour at a core step
but must not be able to affect it. Use a filter when you must change the data.
`hooks.list_actions()` lists the registered actions.

## Emit your own extension points

Extension is a two-way street. When you build a module, publish events at the
moments other modules would care about, and expose hooks where you want them to
be able to customise you. The tutorial's `service.create_item` already does the
first:

```python
from app.core.events import event_bus

event_bus.publish_detached(
    "oe_site_log.item.created",
    {"id": str(item.id), "project_id": str(item.project_id)},
    source_module="oe_site_log",
)
```

Use `publish_detached` from a request path that still holds a database session,
so the request can commit before subscribers open their own sessions. Use
`await event_bus.publish(...)` when you want the `EventResult` back, for example
in a test. Where you want callers to shape your data or observe your steps, call
`hooks.apply_filters(...)` and `hooks.do_actions(...)` at those points and
document the names.

## Add checks instead of editing the checker

To change what the platform considers valid, register a validation rule rather
than editing the engine. The loader auto-imports `validators.py`, and
[the tutorial](./first-module-in-10-minutes.md) shows the full pattern. The
short version:

```python
from app.core.validation.engine import rule_registry
# ... define a ValidationRule subclass ...
rule_registry.register(MyRule(), ["my_set", "boq_quality"])
```

Registering into an existing set such as `boq_quality` extends a built-in check
with your rule, again without touching core. Pick a set your rule really answers
for. A set nothing implements is reported as unsupported and drawn on the
dashboard as a check that did not run, and a single rule registered into it
turns that honest gap into a check that ran and found nothing.

## The payoff

Everything above lives in your module. When the next platform release lands, you
pull it and your module keeps working, because you never edited a file the
release also changed. You can confirm your wiring survived an upgrade by
introspecting the live system:

- `event_bus.list_handlers()` for event subscriptions.
- `hooks.list_filters()` and `hooks.list_actions()` for hooks.
- `rule_registry.list_rules()` for validation rules.
- `GET /api/v1/modules/` for the module and its route and dependency status.

If you ever feel you must edit a core file to achieve something, that is a signal
to ask for a new event or hook at that point rather than to fork. An added
extension point helps every builder and stays in the upstream release. A fork
helps no one and has to be re-paid every release.
