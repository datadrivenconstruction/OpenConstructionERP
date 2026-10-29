// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Where the reader is in the onboarding wizard, kept in sessionStorage so a
// reload mid-way returns to the same step with the same profile and modules
// instead of the welcome screen. Session scope: a new tab starts fresh.

const KEY = 'oe_onboarding_progress';

export interface WizardProgress {
  step: number;
  visited: number[];
  companyType: string | null;
  enabledModules: string[];
}

function isProgress(v: unknown): v is WizardProgress {
  if (!v || typeof v !== 'object') return false;
  const p = v as Record<string, unknown>;
  return (
    Number.isInteger(p.step) &&
    Array.isArray(p.visited) &&
    p.visited.every((n) => Number.isInteger(n)) &&
    (p.companyType === null || typeof p.companyType === 'string') &&
    Array.isArray(p.enabledModules) &&
    p.enabledModules.every((m) => typeof m === 'string')
  );
}

/** The saved progress, or null when none, unreadable, or out of range. */
export function loadWizardProgress(stepCount: number): WizardProgress | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isProgress(parsed) || parsed.step < 0 || parsed.step >= stepCount) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveWizardProgress(progress: WizardProgress): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(progress));
  } catch {
    // Storage unavailable: a reload starts over, nothing else breaks.
  }
}

export function clearWizardProgress(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
