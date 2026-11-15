# Equipment, ledger and data-quality rules

Short reference for rules that surface as errors or warnings. Warnings never block your work; they mark what to fix before it matters.

## Optional extras

The base install covers everything except two optional packages:

- `pip install "openconstructionerp[saml]"` adds SAML single sign-on (the SAML option in Settings > Single sign-on appears once it is installed), see [SSO](../sso.md). OIDC needs nothing extra.
- `pip install "openconstructionerp[parquet]"` adds `pyarrow` for Parquet data feeds, see [data feeds](../data-feeds.md). Without it a `.parquet` feed answers with a clear message naming this extra, and Settings > Data feeds hides the Parquet URL. CSV and JSON keep working.

## Equipment

- Every equipment unit belongs to one tenant (your organisation). Other tenants never see it.
- A unit is linked to a project only through a dated rental (start and end date). There is no open-ended project assignment.
- Two rentals of the same unit that overlap in time are rejected, so a machine cannot be on two projects on the same day. Shorten or move one of the rentals.

## Budget ledger: segregation of duties

In each project, Budget ledger settings has **Segregation of duties**, on by default. While it is on, whoever requested a budget transfer or modification cannot approve it; a second person must. Switching it off needs the cost-model manage permission, is logged, and suits very small teams only.

## Warnings you may see

- **NCR closed without root cause**: closing a major non-conformance report with an empty root cause raises a warning. Fill in the root cause so the corrective action is traceable.
- **Insurance or bond without coverage amount**: a policy or bond with no coverage amount is flagged. Enter the insured sum so exposure reports are complete.
- **Estimate rate without currency**: a rate saved without a currency takes the project base currency and shows a warning. Check it, because a rate from another currency would otherwise be priced wrongly.

## Share links

A share link to a file protects the file name and details until the visitor enters the password, and also once the link has expired. An unauthorised or expired visitor sees only a neutral prompt or notice.

## US pack: lien statutes

The US pack lists lien and notice statutes per state as a reference only. Deadlines and forms change and depend on the contract, so verify them with counsel before relying on them.
