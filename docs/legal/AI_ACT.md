# AI in OpenConstructionERP: what it does and what the deployer does

Also available in [Deutsch](AI_ACT.de.md) and [Русский](AI_ACT.ru.md).

This page states facts about the software. It is not a declaration of
conformity with Regulation (EU) 2024/1689 (the AI Act). No harmonised
standard for the AI Act has been published yet, so there is nothing a
conformity claim could rest on today, and we do not make one.

## What we count as AI

We count a feature as AI when it sends data to a language, speech or
vision model and uses what the model returns. Rule-based checks,
templates, formulas, statistics and optimisation (for example the
validation engine, cost roll-ups, scheduling and risk scoring) are not
AI in this sense, even where marketing text calls a feature smart.

## Nothing is sent until a provider is configured

The software ships with no model key and contacts no model provider on
its own. A provider is used only after a deployer or user supplies a key,
in the settings, in an environment variable or in
`~/.openestimate/config.json`. The provider is chosen by the deployer.
The privacy policy, [PRIVACY.md](PRIVACY.md) section 5, lists every
provider and the address each one is reached at.

If you need data to stay inside your own network, run a local model
(Ollama or vLLM) and select it as the provider. Text then does not leave
your infrastructure through the AI features.

Two exceptions you should know:

- Speech to text for the phone log and voice capture is always performed
  by OpenAI, whatever provider is selected, using an OpenAI key. Recorded
  audio is kept for 90 days by default (`OE_PHONELOG_AUDIO_RETENTION_DAYS`).
- Requests sent to OpenRouter carry a header that attributes the usage to
  this application. Your key, your account and OpenRouter's terms apply.

## Humans confirm, the model suggests

AI output is a proposal. In the estimate, a suggested change shows its
origin and the model's confidence and is applied only when a person
accepts it. The confidence figure is the model's own estimate, not a
measurement.

One feature works differently: the module builder. There the model writes
a specification, never Python code, a person reads every generated file
on the review step and presses Install, and the module then takes effect
immediately.

## What the deployer has to do

When you run the software for your organisation you are the deployer.
In particular you decide:

- whether to enable AI at all, and with which provider and contract;
- whether your use falls under a high-risk category of the AI Act, for
  example if you use scores produced by the software to make decisions
  about individual people (the software scores work packages, suppliers
  and organisations, not persons, but the data you enter determines what
  is actually being assessed);
- how you inform your staff and others whose data you process, including
  people whose voice is in a recorded call;
- how long you keep AI results stored with your records.

## Contact

Questions about this page: info@datadrivenconstruction.io
