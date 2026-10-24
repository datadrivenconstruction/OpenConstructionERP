// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Badge slot on every sidebar row. Features register a renderer per route
 * (`registerNavItemBadge('/rfi', RfiBadge)`); with nothing registered the
 * slot renders nothing.
 */
import { useSyncExternalStore, type ComponentType } from 'react';

export type NavItemBadgeRenderer = ComponentType<{ itemId: string }>;

const registry = new Map<string, NavItemBadgeRenderer>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  listeners.forEach((l) => l());
}

/** Register a badge for one route; returns an unregister function. */
export function registerNavItemBadge(itemId: string, renderer: NavItemBadgeRenderer): () => void {
  registry.set(itemId, renderer);
  emit();
  return () => {
    if (registry.get(itemId) === renderer) {
      registry.delete(itemId);
      emit();
    }
  };
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function NavItemBadge({ itemId }: { itemId: string }) {
  useSyncExternalStore(subscribe, () => version, () => version);
  const Renderer = registry.get(itemId);
  return Renderer ? <Renderer itemId={itemId} /> : null;
}
