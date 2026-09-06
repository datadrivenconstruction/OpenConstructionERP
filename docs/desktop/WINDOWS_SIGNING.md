# Windows code signing for the desktop app

This guide explains how to turn on Authenticode code signing for the OpenConstructionERP Windows installers. Today the `.exe` ships unsigned, and Windows SmartScreen warns every person who runs it. The pipeline for signing is already written and already in the release workflow. Nothing in this document is active yet, because none of the credentials it needs exist. The only remaining step is a human creating one certificate and pasting five secrets and one variable into the repository settings. There is no code change to make afterwards.

This is a developer and maintainer document. If you are a user trying to install the app, read `docs/desktop/INSTALL.md` instead.

The equivalent document for the other platform is `docs/desktop/MACOS_NOTARIZATION.md`. The two are separate mechanisms with separate credentials, and turning one on does nothing for the other.

For where every published release actually stands across all four signature mechanisms, and how to check a download yourself, see `docs/desktop/RELEASE_SIGNATURE_INVENTORY.md`.

## What is unsigned today, and how you can tell

Every Windows installer this project has published is unsigned. There is no partial state and no historical exception.

The release workflow's `sign-windows` job runs on every tag, discovers that no signing secrets are set, and stops. As of the change that added this document, it says so out loud: the run page carries a warning annotation titled "Windows installers are not code signed", and the job summary carries a block headed "Windows code signing: SKIPPED". Before that change it also skipped, but it did so with a plain log line inside a green job, which nobody reads. If you look at a release and want to know whether its installers were signed, open the Desktop Release run for that tag and look for that block.

You can also check a downloaded file directly. Right-click the `.exe`, choose Properties, and look for a Digital Signatures tab. On an unsigned file there is no such tab.

## Why it matters

Windows SmartScreen inspects executables downloaded from the internet. An unsigned installer trips the "Windows protected your PC" dialog, which offers no obvious way forward: the user has to click "More info" and then "Run anyway", and most people do not. Some corporate environments block unsigned installers outright and the user never sees a choice at all.

A signed installer carries a verifiable statement of who published it. With an Extended Validation certificate SmartScreen trusts the publisher immediately. With an Organization Validation certificate the publisher builds reputation over the first weeks of downloads and the warning fades. Either way the file stops being anonymous.

Signing does not change what the app does, what it installs, or where its data lives.

## What the founder must obtain

### A code signing certificate

Buy one from a public certificate authority. GlobalSign, DigiCert, Sectigo and SSL.com all issue them. Expect identity verification of the company, which takes days rather than minutes, so start early.

Choose between Organization Validation and Extended Validation. EV costs more and grants SmartScreen reputation from the first signature. OV is cheaper and starts from zero reputation. For a product whose installers are downloaded by strangers, EV is worth the difference.

### Why the certificate cannot simply be a file

This is the part that surprises people, and it is the reason this pipeline is shaped the way it is.

Since June 2023 the CA/Browser Forum baseline requirements have required the private key of a code signing certificate to be generated and held in hardware that meets FIPS 140-2 Level 2 or Common Criteria EAL4+. Public CAs therefore no longer issue a downloadable `.pfx` file that you can hand to a build server. You get either a physical USB token posted to you, or a key generated inside a cloud HSM.

A USB token cannot be plugged into a GitHub-hosted runner, so the cloud HSM route is the one that works for CI. That is why the workflow signs through Azure Key Vault with AzureSignTool rather than with a certificate file: the private key stays inside the vault and never reaches the runner. The runner sends a hash to Azure and gets a signature back.

Any CA that supports key generation in Azure Key Vault will work. Tell the CA during ordering that the key will live in an Azure Key Vault Premium or Managed HSM, and follow their instructions for generating the certificate signing request from the vault.

### The Azure side

You need an Azure subscription, and inside it:

A Key Vault, on the Premium tier or a Managed HSM. The Standard tier is software-backed and does not satisfy the hardware requirement, so a CA will not issue against it.

The certificate imported into that vault, under a name you choose. That name is what `AZURE_KV_CERT_NAME` holds. It is the certificate's name in the vault, not the subject line of the certificate and not the file name.

An Entra ID (Azure AD) app registration with a client secret. This is the identity GitHub Actions authenticates as. Its application ID is `AZURE_KV_CLIENT_ID`, its client secret is `AZURE_KV_CLIENT_SECRET`, and the directory it lives in is `AZURE_KV_TENANT_ID`.

Permission for that app registration on the vault. Under Azure RBAC, grant it the "Key Vault Certificate User" role so it can read the certificate and the "Key Vault Crypto User" role so it can sign with the key. If the vault still uses the older access policy model instead, grant Get on certificates, and Get and Sign on keys. Signing fails with an authorisation error if either half is missing, so grant both and confirm the role assignments landed on the vault itself rather than on the resource group only.

Client secrets in Entra ID expire, at most two years out and often sooner. Put the expiry date in a calendar. When it passes, signing starts failing, which is by design: see the `WINDOWS_SIGNING_REQUIRED` variable below for how to make sure that failure is loud rather than a silent return to unsigned installers.

## The exact secrets to create, and where

Go to the repository on GitHub, then Settings, then Secrets and variables, then Actions. Everything below is created on that one page. Nothing here belongs in a file in the repository, and no value from this list should ever appear in a commit, a log, or an issue.

Under the Secrets tab, use "New repository secret" five times. The names must match exactly, because the workflow reads them by name.

`AZURE_KV_URL` is the vault URL, in the form `https://yourvaultname.vault.azure.net`. Copy it from the vault's Overview page.

`AZURE_KV_CERT_NAME` is the name of the certificate inside the vault.

`AZURE_KV_CLIENT_ID` is the application (client) ID of the Entra ID app registration.

`AZURE_KV_CLIENT_SECRET` is the client secret value for that app registration. Azure shows this value once, at creation. If you did not copy it, create a new one rather than trying to recover the old one, and use a freshly rotated secret rather than one that has been pasted somewhere else.

`AZURE_KV_TENANT_ID` is the directory (tenant) ID of the Entra ID tenant.

Then switch to the Variables tab on the same page and use "New repository variable" once.

`WINDOWS_SIGNING_REQUIRED` set to `true`. This is a variable and not a secret, because it holds no confidential value and it is useful to see it plainly in the settings UI.

The variable is what stops signing from silently switching itself off later. With it set, a release where the secrets are missing or empty fails the build instead of shipping unsigned installers with a warning. That is the state you want once signing works, because the most likely future failure is not a broken certificate but an expired client secret, and an expired secret would otherwise put the pipeline straight back into the quiet skip it is in today, on a green run, indistinguishable from a healthy one.

Set the five secrets first and the variable last. Between the two the build still fails, loudly and correctly, because a half-configured vault cannot sign anything.

## What the workflow does with them

The `sign-windows` job in `.github/workflows/desktop-release.yml` begins with a preflight step that reads whether each of the five secrets is non-empty. It never reads or prints a value. There are three outcomes and they are deliberately three different colours.

None of the five set, and `WINDOWS_SIGNING_REQUIRED` is not `true`: the job annotates the run, writes a SKIPPED block into the job summary, and finishes green with unsigned installers. This is the state the project is in today.

None of the five set, and `WINDOWS_SIGNING_REQUIRED` is `true`: the job fails. The repository has declared that it signs, so shipping unsigned is a defect and not a default.

Some but not all five set: the job fails and names the missing ones. AzureSignTool needs all five, and invoking it with some of them empty produces an error about the vault rather than about the secret nobody set.

Only when all five are present does the job install .NET and AzureSignTool, download the installers from the tag's release, sign each one, verify each signature with `signtool verify /pa`, and re-upload the signed files over the unsigned ones. Every one of those steps can fail the job. In particular, a download that returns no installers is a failure rather than a quiet "nothing to sign", verification failing is a failure, and `signtool` being absent from the runner is a failure, because "nothing checked these signatures" and "these signatures are good" must not look the same from the run page.

The release is already published while this runs, since release.yml publishes it before any installer is built, so the unsigned installer is downloadable until the signed one replaces it.

One value in the workflow may need changing when the certificate arrives. The timestamp authority is currently the literal `http://timestamp.globalsign.com/tsa/r6advanced1`, on the `-tr` flag of the `azuresigntool sign` call. If the certificate comes from a CA other than GlobalSign, point that at the issuing CA's RFC 3161 timestamp server instead. A timestamp is what keeps signatures valid after the certificate expires, so do not remove the flag.

## Confirming it worked

After the first release with the secrets in place, open the Desktop Release run for that tag. The job summary should read "Windows code signing: running against Azure Key Vault" followed by a line reporting how many installers were signed and verified. If it reads SKIPPED, the secrets are not being seen.

Then download the published `.exe` and check it on a Windows machine. Right-click, Properties, Digital Signatures tab. The tab now exists, the signer name is the organisation on the certificate, and opening the entry shows a countersignature timestamp. Running the installer should no longer produce the "Windows protected your PC" dialog, immediately with an EV certificate, and after some download volume with an OV one.

From a command line, `signtool verify /pa /v installer.exe` prints the chain and reports success. `signtool` ships with the Windows SDK.

## What this does not do

It does not sign anything already published. Every release before the first signed one keeps unsigned installers, and re-signing them would mean replacing the bytes under releases that people have already downloaded and checksummed. The SHA-256 manifest attached to recent releases is computed over the assets as published, so silently swapping a file would invalidate it.

It does not affect macOS or Linux. The `.dmg` is a separate mechanism covered by `docs/desktop/MACOS_NOTARIZATION.md`, and the Linux packages are unsigned by a different convention.

It is not the same thing as the Sigstore manifest. `SHA256SUMS`, `SHA256SUMS.sig` and `SHA256SUMS.pem` on a release prove the assets are the ones our CI produced. An Authenticode signature is what Windows itself checks before running a file. A release can have either, both or neither, and they answer different questions.

## References

AzureSignTool, the tool the workflow calls: https://github.com/vcsjones/AzureSignTool

CA/Browser Forum baseline requirements for code signing, the source of the hardware key storage rule: https://cabforum.org/working-groups/code-signing/requirements/

Microsoft, SmartScreen and application reputation: https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/

Azure Key Vault certificates: https://learn.microsoft.com/en-us/azure/key-vault/certificates/

Microsoft, signtool: https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool

Questions: info@datadrivenconstruction.io. Licensed under AGPL-3.0.
