# Windows code signing for the desktop app

This guide explains how to turn on Authenticode code signing for the OpenConstructionERP Windows installers. Today the `.exe` ships unsigned, and Windows SmartScreen warns every person who runs it. The pipeline for signing is already written and already in the release workflow. Nothing in this document is active yet, because none of the credentials it needs exist. The only remaining step is a human opening an Artifact Signing account and pasting six secrets and one variable into the repository settings. There is no code change to make afterwards.

This is a developer and maintainer document. If you are a user trying to install the app, read `docs/desktop/INSTALL.md` instead.

The equivalent document for the other platform is `docs/desktop/MACOS_NOTARIZATION.md`. The two are separate mechanisms with separate credentials, and turning one on does nothing for the other.

For where every published release actually stands across all four signature mechanisms, and how to check a download yourself, see `docs/desktop/RELEASE_SIGNATURE_INVENTORY.md`.

## Smart App Control, and why the installer signature is not enough

Windows 11 Smart App Control checks every executable file as the loader maps it, not only the file that was downloaded, and it offers no per-app exception. A file runs when Microsoft's cloud reputation service knows it, or when it carries a valid signature that chains to a CA in the Microsoft Trusted Root Program. Everything else is blocked. Smart App Control starts in an evaluation mode after a clean Windows install and later switches itself on, which is how a tester can run the app once and find it blocked on later starts with nothing changed on our side.

The desktop sidecar is a PyInstaller onefile build that unpacks about 490 `.exe`, `.dll` and `.pyd` files at every start and runs them from `%LOCALAPPDATA%\OpenConstructionERP\extract`. Measured on a 17.x install, 409 of those 492 files carried no signature: every PostgreSQL program (`postgres.exe`, `initdb.exe`, `pg_ctl.exe` and the rest), and most of the native modules of scipy, scikit-learn, pandas, pyarrow and numpy. The launcher, the sidecar and the uninstaller were unsigned too. Signing only the installer would leave every one of them blocked.

So the release workflow signs from the inside out, in three places, all skipped unless the Artifact Signing secrets below are set:

1. In `build-sidecar`, before PyInstaller runs, `scripts/sign_windows_binaries.py` signs every unsigned PE file in the Python environment the sidecar is built from. Files that already carry their publisher's signature (the Python Software Foundation, Microsoft, Intel) keep it. This has to happen before packing, because the onefile archive seals its members and no later pass can reach them.
2. Right after PyInstaller, the onefile `openconstructionerp-server.exe` itself is signed, and the existing sidecar checks then run the signed file.
3. In `build-tauri`, the bundled converters are signed, and Tauri receives `bundle.windows.signCommand` through `--config`, so it signs the launcher, its copy of the sidecar, the NSIS plugins, the uninstaller and the installer.

`scripts/setup_windows_signing.py` decides whether any of this runs. With no secrets it writes a notice and changes nothing. With some but not all it fails the run and names the missing ones. It signs only when the run releases a version tag, so a branch build is never signed.

### Artifact Signing secrets

Azure Artifact Signing (formerly Trusted Signing) issues short-lived certificates under a Microsoft root and costs 9.99 USD a month on the Basic tier (5,000 signatures a month, then 0.005 USD each). A release uses one signature per unsigned file it signs: every unsigned PE file in the sidecar's build environment plus the launcher, the sidecar, the converters, the NSIS plugins, the uninstaller and the installer, which is several hundred. The signing steps print the exact count, so read the first signed run before relying on the quota. Public Trust is open to organisations in the EU, and to individual developers only in the US and Canada, so the account has to be opened in the company's name. Identity validation takes from one to twenty business days. Reputation for SmartScreen still builds over time, as with any certificate, but Smart App Control accepts the signature from the first release.

Create these six repository secrets under Settings, Secrets and variables, Actions:

`ARTIFACT_SIGNING_ENDPOINT` is the regional endpoint of the account, for example `https://weu.codesigning.azure.net` for West Europe. It must match the region the account and the certificate profile were created in.

`ARTIFACT_SIGNING_ACCOUNT` is the Artifact Signing account name.

`ARTIFACT_SIGNING_PROFILE` is the certificate profile name (Public Trust).

`ARTIFACT_SIGNING_TENANT_ID`, `ARTIFACT_SIGNING_CLIENT_ID` and `ARTIFACT_SIGNING_CLIENT_SECRET` identify an Entra ID app registration that holds the "Artifact Signing Certificate Profile Signer" role on the profile. The workflow passes them to the signing library as `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET`, the names the Azure SDK reads, so the secret never appears on a command line.

The timestamp authority is `http://timestamp.acs.microsoft.com`. Do not remove it: the certificates are valid for three days, and the timestamp is what keeps a signature valid after that.

To check a release, install it on a test machine and run, in PowerShell, `Get-ChildItem "$env:LOCALAPPDATA\OpenConstructionERP\extract" -Recurse -Include *.exe,*.dll,*.pyd | Get-AuthenticodeSignature | Group-Object Status`. Every file should report `Valid`.

After the build, the `sign-windows` job (named "Verify Windows installer signatures") does not sign anything. It downloads the published installer and runs `signtool verify /pa` on it. Right after PyInstaller, the sidecar step also opens the onefile archive and verifies every PE member inside it, so a signature lost during packing fails the run instead of shipping.

An earlier second path, which re-signed only the published installer through Azure Key Vault and AzureSignTool, has been removed. It could not satisfy Smart App Control on its own, and managed cloud signing was chosen instead.

## What is unsigned today, and how you can tell

Every Windows installer this project has published so far is unsigned. Until the six secrets exist, the verification job annotates the run with "The Windows installer is not code signed" and writes a block headed "WINDOWS INSTALLERS ON THIS RELEASE ARE NOT CODE SIGNED" into the job summary.

You can also check a downloaded file directly. Right-click the `.exe`, choose Properties, and look for a Digital Signatures tab. On an unsigned file there is no such tab.

## Why it matters

Windows SmartScreen inspects executables downloaded from the internet. An unsigned installer trips the "Windows protected your PC" dialog, and Smart App Control blocks it outright. A signed installer carries a verifiable statement of who published it, and SmartScreen names the publisher while reputation builds.

Signing does not change what the app does, what it installs, or where its data lives.

## The repository variable

After the six secrets, create one repository variable under Settings, Secrets and variables, Actions, Variables: `WINDOWS_SIGNING_REQUIRED` set to `true`.

With it set, a release where the secrets are missing or empty fails instead of shipping unsigned installers with a warning. The most likely future failure is an expired client secret, and without the variable that would put the pipeline back into a quiet skip on a green run. Set the secrets first and the variable last.

## What the verification job does

The job begins with a preflight that reads only whether each of the six `ARTIFACT_SIGNING_*` secrets is non-empty.

None set, and `WINDOWS_SIGNING_REQUIRED` is not `true`: the job annotates the run, writes the unsigned block into the summary, and finishes green.

None set, and `WINDOWS_SIGNING_REQUIRED` is `true`: the job fails.

Some but not all set: the job fails and names the missing ones.

All six set: the job downloads the `.exe` from the release and verifies it with `signtool verify /pa`. A download with no installer, a missing `signtool` and a failed verification each fail the job.

## Confirming it worked

After the first release with the secrets in place, open the Desktop Release run for that tag. The verification job summary reports how many installers were verified. Then install the release on a Windows machine and run the PowerShell check above over the extraction folder; every file should report `Valid`. `signtool verify /pa /v installer.exe` prints the chain of the installer itself.

## What this does not do

It does not sign anything already published. Re-signing old releases would replace bytes people have already downloaded and checksummed, and invalidate the SHA-256 manifest attached to them.

It does not affect macOS or Linux. The `.dmg` is covered by `docs/desktop/MACOS_NOTARIZATION.md`.

It is not the same thing as the Sigstore manifest. `SHA256SUMS`, `SHA256SUMS.sig` and `SHA256SUMS.pem` prove the assets are the ones our CI produced. An Authenticode signature is what Windows itself checks before running a file.

## References

Azure Artifact Signing: https://learn.microsoft.com/en-us/azure/artifact-signing/

Microsoft, SmartScreen and application reputation: https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/

Microsoft, SmartScreen reputation for Windows app developers, the source for EV no longer bypassing SmartScreen and for Smart App Control checking every executable: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation

Microsoft, signtool: https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool

Questions: info@datadrivenconstruction.io. Licensed under AGPL-3.0.
