// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Action registry behind the command palette, the keyboard shortcuts and the
 * assistant's "run this for me" suggestions.
 *
 * Modules contribute actions the same way they contribute routes: through
 * `ModuleManifest.actions`, or at runtime with `registerActions(source, defs)`.
 * Nothing in here knows a module by name.
 */
import { useSyncExternalStore } from 'react';
import type { LucideIcon } from 'lucide-react';

export type ActionGroup = 'create' | 'import' | 'navigate' | 'project' | 'view' | 'ai';

/** What an action may use when it runs. Built by the palette / shortcut layer. */
export interface ActionContext {
  navigate: (to: string) => void;
  /** Project the action targets: the one picked in the palette, else the active one. */
  projectId: string | null;
  projectName: string;
  /** Make `projectId` the active project before a project-scoped page opens. */
  setActiveProject: (id: string, name: string) => void;
}

export interface PaletteAction {
  /** Stable id, `[a-z0-9._/:-]`, e.g. `boq.new` or `nav./finance`. Shortcuts and the AI refer to it. */
  id: string;
  titleKey: string;
  defaultTitle: string;
  /** i18n key of a comma-separated synonym list in the UI language. */
  keywordsKey?: string;
  defaultKeywords?: string;
  group: ActionGroup;
  icon?: LucideIcon;
  /** `project`: runs against a project, offered as "<project> > <title>". */
  scope?: 'global' | 'project';
  /** Hidden while this module is switched off. */
  moduleKey?: string;
  /** Shortcut out of the box; the user can rebind or clear it. See shortcuts.ts. */
  defaultShortcut?: string;
  /** Plain navigation. `:projectId` is replaced for project-scoped actions. */
  path?: string;
  /** Custom behaviour; when absent the action navigates to `path`. */
  run?: (ctx: ActionContext) => void;
  /** Ranking tie-break, higher first. */
  priority?: number;
}

const ACTION_ID = /^[a-z0-9][a-z0-9._/:-]{0,63}$/;

const sources = new Map<string, PaletteAction[]>();
let snapshot: PaletteAction[] = [];
const listeners = new Set<() => void>();

function rebuild(): void {
  const byId = new Map<string, PaletteAction>();
  for (const defs of sources.values()) {
    for (const def of defs) {
      // First registration wins, so a module cannot silently replace a core action.
      if (!byId.has(def.id)) byId.set(def.id, def);
    }
  }
  snapshot = [...byId.values()];
  listeners.forEach((l) => l());
}

/**
 * Register (or replace) the actions of one source, e.g. `core` or a module id.
 * Returns an unregister function. Ids that do not fit the id pattern are
 * refused loudly in development and dropped.
 */
export function registerActions(source: string, defs: readonly PaletteAction[]): () => void {
  const valid = defs.filter((d) => {
    const ok = ACTION_ID.test(d.id);
    if (!ok && import.meta.env?.DEV) console.warn(`[actions] invalid action id "${d.id}" from ${source}`);
    return ok;
  });
  sources.set(source, valid);
  rebuild();
  return () => {
    if (sources.get(source) === valid) {
      sources.delete(source);
      rebuild();
    }
  };
}

export function listActions(): readonly PaletteAction[] {
  return snapshot;
}

export function getAction(id: string): PaletteAction | undefined {
  return snapshot.find((a) => a.id === id);
}

export function subscribeActions(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useActions(): readonly PaletteAction[] {
  return useSyncExternalStore(subscribeActions, listActions, listActions);
}

/** Run an action. Project-scoped actions without a project open the project list instead. */
export function runAction(action: PaletteAction, ctx: ActionContext): void {
  if (action.scope === 'project') {
    if (!ctx.projectId) {
      ctx.navigate('/projects');
      return;
    }
    ctx.setActiveProject(ctx.projectId, ctx.projectName);
  }
  if (action.run) {
    action.run(ctx);
    return;
  }
  if (action.path) {
    ctx.navigate(action.path.replace(':projectId', encodeURIComponent(ctx.projectId ?? '')));
  }
}

/** Test hook: forget every registration. */
export function __resetActionsForTests(): void {
  sources.clear();
  rebuild();
}
