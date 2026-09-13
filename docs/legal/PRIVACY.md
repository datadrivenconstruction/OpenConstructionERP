# Privacy Policy

**Effective date:** 2026-04-18
**Last updated:** 2026-04-18

This Privacy Policy describes how OpenConstructionERP ("the Software", "we")
handles personal data when you self-host the Software or use an instance
operated by DataDrivenConstruction ("DDC", the "Operator"). It is written
to satisfy the baseline transparency obligations of the EU General Data
Protection Regulation 2016/679 ("GDPR"), the United Kingdom Data
Protection Act 2018, the California Consumer Privacy Act / CPRA, and the
Brazilian Lei Geral de Proteção de Dados (LGPD).

> **Self-hosting note.** When you deploy the Software on your own
> infrastructure, **you become the data controller** for your users, and
> DDC has no access to any data. This document is then a template you may
> adapt for your own users. The operator-specific clauses below apply only
> to the instance at `https://openconstructionerp.com` operated by DDC.

---

## 1. Data we process

| Category | Examples | Legal basis |
|---|---|---|
| Account data | email, password hash, display name, locale | Contract (GDPR 6(1)(b)) |
| Authentication data | session tokens, API keys | Contract |
| Project content | BOQ items, documents, CAD/BIM files, annotations | Contract |
| Usage telemetry (anonymised) | page timings, error reports | Legitimate interest (GDPR 6(1)(f)) |
| Support correspondence | emails, issue comments | Legitimate interest |
| AI interaction logs (if configured) | prompts and responses | Consent (GDPR 6(1)(a)) |

We do **not** collect special-category data (GDPR Art. 9), nor do we sell
personal data as defined by the CCPA.

## 2. Where data is stored

- The Software stores all content in the database you configure
  (PostgreSQL or SQLite) and the object store you configure (local disk or
  S3-compatible).
- For the DDC-operated instance, servers are located in the European
  Economic Area. The processors DDC uses to operate that instance, and the
  safeguard recorded for each, are listed in section 5.

### Outbound requests the Software makes

The Software contacts third-party services in the situations below. Some
are outside the EEA. This list describes the application's own behaviour
and is separate from the processors DDC uses to run its hosted instance.

- **AI providers.** Only where you configure one. The Software ships with
  no API key and contacts no provider until you supply one. The key is
  yours, so the account and the agreement with that provider are between
  you and them; DDC is not a party to that agreement. On a self-hosted
  install DDC operates no part of it. Section 5 lists every provider and
  its endpoint, and what the features transmit.
- **Geocoding.** When a project address is set, the address is sent to the
  public OpenStreetMap Nominatim service to resolve it to coordinates.
  Set `OE_GEOCODER_DISABLED=true` to switch this off, or
  `OE_GEOCODER_BASE_URL` to use your own Nominatim mirror.
- **Weather.** Where weather-dependent features are used, coordinates are
  sent to Open-Meteo, or to OpenWeatherMap if you configure a key.
- **Software and reference-data downloads.** Cost-base files, encoder
  model weights and vector snapshots are fetched from GitHub and Hugging
  Face. These requests carry no project content; like any HTTP request
  they disclose the requesting server's IP address to the host.

Transfers of personal data outside the EEA are governed by Chapter V of
the GDPR, whose mechanisms include the standard contractual clauses
adopted by Commission Implementing Decision (EU) 2021/914. Which
mechanism applies to a given transfer depends on the parties to it. Where
you configure a provider under your own account, DDC is not a party to
that relationship and so cannot conclude those clauses within it.

*This section replaced an earlier statement that no personal data left
the EEA except under standard contractual clauses put in place by DDC.
That did not describe how the Software works: the outbound requests above
were not covered by it, and for a provider you configure under your own
key DDC is not in a position to conclude such clauses. Operators relying
on this section should have it reviewed by their own counsel, and should
confirm which of the outbound requests above their deployment actually
makes.*

## 3. Retention

| Category | Default retention |
|---|---|
| Account data | Until account deletion |
| Project content | Until you delete it; deleted content is purged from backups within 35 days |
| Telemetry | 90 days |
| Support correspondence | 24 months |
| AI logs | 30 days unless you opt into a longer window |

## 4. Your rights

Under GDPR / UK DPA / LGPD you may:

- Access the personal data we hold about you (Art. 15)
- Rectify inaccurate data (Art. 16)
- Request erasure (Art. 17)
- Restrict or object to processing (Art. 18 / 21)
- Obtain your data in a portable format (Art. 20)
- Withdraw consent at any time

Under CCPA / CPRA you may additionally:

- Know what categories of personal information are collected
- Opt out of sale or sharing (we do not sell)
- Request deletion
- Not be discriminated against for exercising these rights

To exercise any right, email **info@datadrivenconstruction.io**. We
respond within 30 days (GDPR) or 45 days (CCPA).

## 5. Third-party processors

The DDC-operated instance uses these processors (self-hosted deployments
may use different providers):

- Infrastructure: Hetzner Online GmbH (EEA)
- Email delivery: Amazon SES (SCC in place)
- Error reporting: Sentry (optional)

### AI providers

**Only those you enable**, with API keys you supply. None is contacted
until you save a key, and the Software ships with no key for any of them.
Your prompts, and any document text, image or recording the feature sends,
pass through the provider you selected, under that provider's own privacy
policy and terms rather than this one.

The full list the Software can talk to, with the endpoint each one uses.
The endpoint is the host the Software sends the request to; where the
provider then stores or processes that content, and for how long, is
stated in the provider's own policy and not here. Listing a provider is
not a recommendation and does not mean DDC has assessed its privacy
practices, its security, or its suitability for your data.

| Provider | Endpoint |
|---|---|
| Anthropic Claude | `api.anthropic.com` |
| OpenAI | `api.openai.com` |
| Google Gemini | `generativelanguage.googleapis.com` |
| OpenRouter | `openrouter.ai` |
| Mistral AI | `api.mistral.ai` |
| Groq | `api.groq.com` |
| DeepSeek | `api.deepseek.com` |
| Together AI | `api.together.xyz` |
| Fireworks AI | `api.fireworks.ai` |
| Perplexity | `api.perplexity.ai` |
| Cohere | `api.cohere.com` |
| AI21 Labs | `api.ai21.com` |
| xAI Grok | `api.x.ai` |
| Zhipu AI (GLM) | `open.bigmodel.cn` |
| Baidu (ERNIE Bot) | `qianfan.baidubce.com` |
| Yandex GPT | `llm.api.cloud.yandex.net` |
| Sber GigaChat | `gigachat.devices.sberbank.ru` |
| Kimi (Moonshot AI) | `api.moonshot.cn` |

Two further options run on infrastructure you provide, at an address you
enter yourself, so nothing leaves your network through them: Ollama
(Local) and vLLM (Local).

Speech-to-text is a separate call: recordings captured by the phone log
and voice-capture features are transcribed by OpenAI at
`api.openai.com`, using your OpenAI key, and are not sent anywhere else.
A recording may contain the voice of someone other than you, so consider
whether you have a basis to record and transmit it before you upload one.

## 6. Security

- Passwords hashed with bcrypt
- Transport over HTTPS / TLS 1.2+
- Database encryption-at-rest (recommended for self-hosters)
- Role-based access control with least-privilege defaults
- Security issues: see [SECURITY.md](SECURITY.md)

## 7. Cookies

See [COOKIES.md](COOKIES.md) for the cookie inventory.

## 8. Children

The Software is intended for professional use. We do not knowingly
process personal data of children under 16 (or under 13 in the US).

## 9. Changes

Material changes to this policy are announced via the release notes and,
for registered users on the DDC-operated instance, via email at least 30
days before taking effect.

## 10. Contact

- **Data controller (DDC instance):** DataDrivenConstruction, Artem Boiko
- **Email:** info@datadrivenconstruction.io
- **Supervisory authority:** the data-protection authority in your EU
  member state; for users in the UK, the Information Commissioner's
  Office (ICO).

---

*This policy provides a baseline and is not a substitute for legal
advice. Before relying on it for a production deployment with
third-party users, have it reviewed by a qualified privacy lawyer in
the jurisdictions where you offer the service.*
