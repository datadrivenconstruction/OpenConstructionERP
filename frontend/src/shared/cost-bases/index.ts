/**
 * Public surface for the shared cost-bases toolkit (multi-base scope,
 * comparison and region helpers).
 *
 * Barrel ownership: this file is edited only by W3-1. Sibling shared files in
 * this folder are imported by their consumers via relative path during the
 * wave, so the build never depends on this barrel re-exporting them. The app
 * shell mounts the keystone tray through `@/shared/cost-bases`, so it is
 * exported here. Additional shared exports (BaseScopeSelect, CrossBaseCompare,
 * region helpers, formatters) are appended to this barrel as their files land.
 */

export { LoadedBasesTray } from './LoadedBasesTray';
