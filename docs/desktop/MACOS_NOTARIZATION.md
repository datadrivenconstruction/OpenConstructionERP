# macOS notarization for the desktop app

This guide explains how to turn on Apple notarization for the OpenConstructionERP desktop app. Today the macOS build ships ad-hoc signed but not notarized, so users have to clear quarantine once by hand. Everything described here is ready to activate. The moment a real Apple Developer ID certificate and credentials exist, notarization can be switched on with a small, well-defined diff. Nothing in this document is active yet. It is the plan and the artifacts, not the live configuration.

This is a developer and maintainer document. If you are a user trying to open the app, read `docs/desktop/INSTALL.md` instead.

For where every published release actually stands across all four signature mechanisms, and how to check a download yourself, see `docs/desktop/RELEASE_SIGNATURE_INVENTORY.md`.

## Why notarization matters

When you download a `.dmg` from the web, macOS attaches a quarantine flag to it. Gatekeeper then inspects the app before it will run. An app that Apple has notarized passes that inspection silently and opens with a normal double-click. An app that is only ad-hoc signed does not, and on Apple Silicon a download with a broken or missing notarization ticket is often reported as "damaged and can't be opened" rather than the milder "unidentified developer". That is the friction we want to remove.

Right now we work around this in two ways. The release CI ad-hoc signs the sidecar and lets Tauri seal a valid ad-hoc bundle signature, which stops the "damaged" report from being the severe, unbypassable kind. Then we ask the user to run a one-time `xattr -dr com.apple.quarantine` command to strip the quarantine flag. That works, but it is a step every new user has to perform, and it looks alarming. Notarization replaces it. With a notarized and stapled build the dmg opens cleanly on a first download, no Terminal command, no Privacy and Security approval, no scary message.

Notarization does not change what the app does or where its data lives. It is purely about Apple confirming the binary is signed by a known developer and is free of known malware, so Gatekeeper trusts it.

## What the founder must obtain from Apple

Notarization needs a real Apple Developer identity. None of this can be faked or self-signed, because Apple has to recognize the certificate. The following are needed.

A paid Apple Developer Program membership. This is the annual paid membership tied to an Apple ID. A free Apple ID is not enough, because only paid members can create a Developer ID certificate.

A Developer ID Application certificate. This is the specific certificate type used for distributing apps outside the Mac App Store. Create it in the Apple Developer portal under Certificates, then export it from Keychain Access on a Mac as a `.p12` file with a password. The `.p12` holds both the certificate and its private key, which is why it carries a password and must be handled as a secret. The human-readable name of this certificate looks like `Developer ID Application: Your Company Name (TEAMID)`, and that exact string is what signing uses as the identity.

The Team ID. This is the ten-character identifier of the Apple Developer team, visible on the Membership page of the developer portal. It also appears inside the parentheses in the certificate name above.

Credentials Apple's notary service will accept, in one of two forms. The simpler form is an app-specific password together with the Apple ID email that owns the membership. Generate the app-specific password at appleid.apple.com under Sign-In and Security, App-Specific Passwords. Do not use the normal Apple ID password, it will not work for the notary service. The more robust form, better for CI because it is not tied to a personal Apple ID, is an App Store Connect API key. That gives you a `.p8` private key file, a Key ID, and an Issuer ID, all created under Users and Access, Integrations, in App Store Connect. Either form works. Pick one.

## The GitHub repository secrets to add

All of these go in the repository under Settings, Secrets and variables, Actions, as repository secrets. Nothing here belongs in a file in the repo. The signing identity string is not sensitive on its own, but it is kept as a secret so the workflow reads everything from one place and forks never inherit it.

For signing, three secrets are always needed.

`APPLE_CERTIFICATE` holds the base64 encoding of the `.p12` file. Tauri decodes this and imports it into a temporary keychain during the build.

`APPLE_CERTIFICATE_PASSWORD` is the password you set when you exported the `.p12` from Keychain Access.

`APPLE_SIGNING_IDENTITY` is the certificate's human-readable name, for example `Developer ID Application: Your Company Name (TEAMID)`. This is the identity codesign uses to sign the app.

To produce the base64 of the certificate, run this on a Mac in Terminal and copy the whole output into the `APPLE_CERTIFICATE` secret.

```
base64 -i DeveloperID_Application.p12 | pbcopy
```

That command base64-encodes the file and copies the result to the clipboard. If you prefer to see it, drop the `| pbcopy` and it prints to the screen. On Linux the equivalent is `base64 -w0 DeveloperID_Application.p12`.

For notarization itself, add one of the two credential sets, matching whichever form you obtained from Apple.

If you went with the app-specific password, add `APPLE_ID` (the Apple ID email that owns the membership), `APPLE_PASSWORD` (the app-specific password, not the normal account password), and `APPLE_TEAM_ID` (the ten-character Team ID).

If you went with the App Store Connect API key, add `APPLE_API_ISSUER` (the Issuer ID), `APPLE_API_KEY` (the Key ID), and `APPLE_API_KEY_PATH` (the path to the `.p8` file on the runner, which the workflow must write out from a secret holding the key contents before the build runs). The API-key form is the better choice for CI because it does not depend on a single person's Apple ID.

These names are the ones Tauri's tooling reads directly. See the Tauri v2 signing documentation linked at the end. When the signing and notarization variables are both present in the build environment, Tauri signs the app with the Developer ID identity and then submits it to Apple's notary service automatically as part of `tauri build`.

## The exact minimal diff to activate notarization

Two files change. Neither change is in place yet. This section is the whole activation.

### (a) desktop/src-tauri/tauri.conf.json

Today the macOS bundle block ad-hoc signs with `"signingIdentity": "-"`, turns the hardened runtime off, and points at the entitlements file.

Before:

```json
    "macOS": {
      "minimumSystemVersion": "10.15",
      "signingIdentity": "-",
      "hardenedRuntime": false,
      "entitlements": "Entitlements.plist"
    },
```

`hardenedRuntime` is written out because Tauri's own default is `true`, not `false`. A config that says nothing about it gets the hardened runtime, and an ad-hoc signature under the hardened runtime enforces library validation with no identity that can satisfy it, so the app is refused the payload it unpacks for itself. macOS reports that refusal as a Team ID disagreement even though neither side carries a Team ID at all. Turning notarization on is what makes the hardened runtime meaningful, so the line flips back to `true` as part of the change below rather than being removed.

After:

```json
    "macOS": {
      "minimumSystemVersion": "10.15",
      "signingIdentity": "Developer ID Application: Your Company Name (TEAMID)",
      "hardenedRuntime": true,
      "entitlements": "Entitlements.plist",
      "providerShortName": "TEAMID"
    },
```

A note on `signingIdentity`. You can hardcode the Developer ID string as shown, or you can leave it reading from the environment. Tauri honours the `APPLE_SIGNING_IDENTITY` environment variable, so if that secret is set in the workflow you may keep `"signingIdentity": "-"` out of the config entirely and let the env value drive it. Hardcoding the string is the most explicit and is the recommended path for a single product. Either way, set `hardenedRuntime`, `entitlements`, and `providerShortName`. The `entitlements` path is relative to `src-tauri`, which is where `Entitlements.plist` already lives in this repo. `providerShortName` is the Team ID and disambiguates which team to notarize under when an Apple ID belongs to more than one team.

### (b) .github/workflows/desktop-release.yml

The build step that runs Tauri currently passes only the GitHub token. Notarization is enabled by adding the Apple secrets to that step's `env` block. Nothing else in the step changes.

The current step looks like this.

Before:

```yaml
      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          projectPath: desktop
          tagName: ${{ github.ref_name }}
```

After, using the app-specific password form:

```yaml
      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
          APPLE_ID: ${{ secrets.APPLE_ID }}
          APPLE_PASSWORD: ${{ secrets.APPLE_PASSWORD }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
        with:
          projectPath: desktop
          tagName: ${{ github.ref_name }}
```

If you chose the App Store Connect API key instead, swap the last three Apple variables for the API-key trio.

```yaml
          APPLE_API_ISSUER: ${{ secrets.APPLE_API_ISSUER }}
          APPLE_API_KEY: ${{ secrets.APPLE_API_KEY }}
          APPLE_API_KEY_PATH: ${{ secrets.APPLE_API_KEY_PATH }}
```

Keep `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, and `APPLE_SIGNING_IDENTITY` in both cases. The certificate signs the app, the credential set notarizes it. With the API-key form, add a small step before the build that writes the `.p8` contents from a secret to the path named in `APPLE_API_KEY_PATH`, since a file path secret needs an actual file on the runner.

These two edits are the entire activation. The macOS runner already builds the dmg; once the environment carries a real Developer ID and notarization credentials, the same build signs with hardened runtime and submits to Apple automatically.

## The sidecar and nested binaries

This is the part that is easy to miss. A Developer ID signature with hardened runtime is only valid if every executable inside the app bundle is also signed the same way, with hardened runtime enabled and a secure timestamp. Our app is not a single binary. It ships the backend as a sidecar (the `externalBin` entry `binaries/openconstructionerp-server` in `tauri.conf.json`), and that sidecar in turn carries nested Mach-O binaries, including the embedded PostgreSQL executables and the bundled converters. Apple's notary service will reject the submission if any nested binary lacks hardened runtime or a timestamp.

The good news is that Tauri signs the bundle and the binaries it knows about during `tauri build` when a signing identity is set, applying the hardened runtime options and a secure timestamp as it goes. So for the binaries Tauri places in the bundle, the existing build does the right thing once the identity is real.

The piece that needs attention is the existing CI step named "Ad-hoc sign sidecar (macOS)". Today that step ad-hoc signs the sidecar with `codesign --force --sign - --timestamp=none` precisely because we ship ad-hoc and an ad-hoc signature must not carry a timestamp. For the real Developer ID path this is wrong in two ways. The signature must use the Developer ID identity rather than `-`, and it must use a secure timestamp rather than `--timestamp=none`, and it must enable the hardened runtime with `--options runtime`. When you activate notarization, change that step so the sidecar is signed with the real identity, with `--options runtime`, and with a secure timestamp (drop `--timestamp=none` and let codesign use Apple's timestamp server, optionally with the entitlements applied via `--entitlements desktop/src-tauri/Entitlements.plist`). In practice you sign from the inside out, deepest nested binaries first, then the sidecar, so each signature seals an already-signed payload. If you would rather not pre-sign the sidecar at all on the real path, you can remove that step and let Tauri sign everything during the bundle, as long as Tauri is configured to deep-sign the externalBin, but the safe and explicit choice is to keep the step and switch it to the real identity with hardened runtime and a timestamp.

Whichever way you go, the rule to remember is simple. On the ad-hoc path, sidecar signed with `-` and no timestamp. On the Developer ID path, every binary signed with the real identity, hardened runtime on, secure timestamp on. The notary service checks all of them.

One place that rule does not apply, and it cost a release to learn. It is about the `codesign` command in CI, which signs the sidecar file on disk. It is not about `codesign_identity` in `desktop/pyinstaller.spec`, which decides how PyInstaller signs the binaries it seals inside that file, and there `-` is wrong on the ad-hoc path. PyInstaller ad-hoc signs collected binaries when no identity is named at all, and reads any identity that is named, `-` included, as a real Developer ID for which it adds `--options=runtime`. The spec spent 14.5.0 to 17.1.0 asking for `-` and shipping every archived binary ad-hoc and hardened with no entitlements, which is a process with library validation on and no identity able to pass it. Users could install the app, start it, and never get a database, because `initdb` was refused the copy of libpq unpacked beside it. That is issue #480. On the ad-hoc path the spec line stays `codesign_identity = None`; on the Developer ID path it takes the real identity and an `entitlements_file` alongside it. `backend/tests/unit/test_desktop_sidecar_hardened_adhoc.py` asserts the line, and the release workflow reads the property back out of the built artifact with `--fail-on-hardened-adhoc`.

## Verifying a notarized build

After a release build with notarization on, two checks confirm it worked. Run them against the built `.app` (the same bundle the dmg contains).

First, ask Gatekeeper to assess it.

```
spctl -a -t exec -vvv /path/to/OpenConstructionERP.app
```

On a correctly notarized build this prints `accepted` and a source line reading `source=Notarized Developer ID`. Today, before activation, this same command reports the app as rejected and unnotarized, which is expected for the ad-hoc build. The diagnostic step at the end of the release workflow already runs this command and prints the result into the build log, so the change from rejected to accepted is visible at release time.

Second, confirm the notarization ticket is stapled to the bundle so it validates offline.

```
xcrun stapler validate /path/to/OpenConstructionERP.app
```

This should report that the validate action worked and the ticket is present. Stapling attaches the notary ticket to the app itself, so Gatekeeper can confirm notarization even without a network connection. Tauri staples automatically after a successful notarization. If `stapler validate` passes and `spctl` says accepted with source Notarized Developer ID, the build is good and the dmg will open cleanly on a fresh download with no quarantine workaround.

It is also worth confirming the signature carries hardened runtime, which you can read from `codesign -dvvv /path/to/OpenConstructionERP.app` in the build log. The flags line should show `runtime` among the code-signing flags.

## References

Tauri v2 macOS code signing and notarization, including the environment variables and the `bundle.macOS` configuration keys: https://v2.tauri.app/distribute/sign/macos/

Apple, Notarizing macOS software before distribution: https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution

Apple, Customizing the notarization workflow (stapling, spctl assessment, troubleshooting): https://developer.apple.com/documentation/security/customizing-the-notarization-workflow

Apple, Hardened Runtime (entitlements and capabilities): https://developer.apple.com/documentation/security/hardened-runtime

Questions: info@datadrivenconstruction.io. Licensed under AGPL-3.0.
