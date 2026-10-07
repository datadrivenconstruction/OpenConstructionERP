#!/usr/bin/env bash
# Credentials alone cannot activate the Developer ID pipeline. Run before upload.
set -euo pipefail
{
  echo '### macOS signing status'
  echo
  echo 'The current build uses an ad-hoc signature and is not notarized.'
  echo 'Apple credentials, if present, do not activate the signing pipeline.'
  echo 'See `docs/desktop/MACOS_NOTARIZATION.md` for the activation procedure.'
} >> "${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY must be set}"
case "${MACOS_NOTARIZATION_REQUIRED:-false}" in
  true)
    echo '::error title=macOS notarization is required::MACOS_NOTARIZATION_REQUIRED is true, but the release pipeline still builds ad-hoc without notarization. Refusing to build or upload a macOS installer. Activate Developer ID signing and artifact verification first.'
    exit 1
    ;;
  false|'')
    echo '::warning title=macOS installer is not notarized::This release uses an ad-hoc signature. Gatekeeper requires the documented manual quarantine workaround. Apple notarization is not activated.'
    ;;
  *)
    echo '::error title=Invalid macOS notarization policy::MACOS_NOTARIZATION_REQUIRED must be true, false, or unset.'
    exit 1
    ;;
esac
