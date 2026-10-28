// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - auto-discovery registry.
//
// New cases are added by DROPPING a file into ./data/<slug>.playbook.ts that
// default-exports a Playbook. There is NO central list to edit, so several
// authors can add cases in parallel without merge conflicts. Vite's
// import.meta.glob collects them at build time; the list is sorted by `order`
// (then id) so ordering is deterministic.

import type { Playbook } from './types';

/** Eagerly import every `*.playbook.ts` data file in ./data. */
const modules = import.meta.glob<PlaybookModule>('./data/*.playbook.ts', {
  eager: true,
});

/** A data file may default-export the Playbook, or use a named `playbook`
 *  export. The default export is the documented convention; the named export
 *  is accepted as a fallback so a stray `export const playbook` still loads. */
interface PlaybookModule {
  default?: Playbook;
  playbook?: Playbook;
}

/**
 * All discovered playbooks, sorted by `order` ascending (ties broken by id).
 * Files that export nothing usable are skipped rather than crashing the list.
 */
export const PLAYBOOKS: Playbook[] = Object.values(modules)
  .map((mod) => mod.default ?? mod.playbook)
  .filter((pb): pb is Playbook => Boolean(pb && Array.isArray(pb.steps)))
  .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));

/** Look up a single playbook by id (`undefined` when not found). */
export function getPlaybook(id: string | undefined): Playbook | undefined {
  if (!id) return undefined;
  return PLAYBOOKS.find((pb) => pb.id === id);
}
