// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Per-module state for the Insights panel: whether it is open and the list of
 * charts the user has built for this module. Both persist to localStorage under
 * an `oce.insights.<moduleId>` namespace so a user's charts and their open/hide
 * preference survive reloads. The page owns this hook and passes the pieces to
 * both the header toggle and the panel, so a single source of truth drives them.
 */
import { useCallback, useEffect, useState } from 'react';
import type { InsightDef } from './types';

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function persist(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / quota - the panel still works for the session. */
  }
}

export interface ModuleInsightsState {
  open: boolean;
  setOpen: (v: boolean) => void;
  toggle: () => void;
  custom: InsightDef[];
  addCustom: (def: InsightDef) => void;
  updateCustom: (def: InsightDef) => void;
  removeCustom: (id: string) => void;
}

export function useModuleInsights(
  moduleId: string,
  opts?: { defaultOpen?: boolean },
): ModuleInsightsState {
  const defaultOpen = opts?.defaultOpen ?? true;
  const openKey = `oce.insights.${moduleId}.open`;
  const customKey = `oce.insights.${moduleId}.custom`;

  const [open, setOpenState] = useState<boolean>(() => read<boolean>(openKey, defaultOpen));
  const [custom, setCustom] = useState<InsightDef[]>(() => read<InsightDef[]>(customKey, []));

  useEffect(() => persist(openKey, open), [openKey, open]);
  useEffect(() => persist(customKey, custom), [customKey, custom]);

  const setOpen = useCallback((v: boolean) => setOpenState(v), []);
  const toggle = useCallback(() => setOpenState((v) => !v), []);
  const addCustom = useCallback((def: InsightDef) => setCustom((l) => [...l, def]), []);
  const updateCustom = useCallback(
    (def: InsightDef) => setCustom((l) => l.map((d) => (d.id === def.id ? def : d))),
    [],
  );
  const removeCustom = useCallback((id: string) => setCustom((l) => l.filter((d) => d.id !== id)), []);

  return { open, setOpen, toggle, custom, addCustom, updateCustom, removeCustom };
}

/** Stable id for a user-built chart, safe across browsers. */
export function newInsightId(): string {
  try {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  } catch {
    /* fall through */
  }
  return `ins_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}
