// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Reading the input-tax split the server stores on a component and an assembly
// (issue #559). Nothing here computes tax: the figures come from the server.

import type { Assembly, AssemblyComponent, AssemblyTaxTotals } from './api';

export interface ComponentTaxSplit {
  status: string;
  rate_pct: string;
  treatment: string;
  net: string;
  tax: string;
  tax_in_cost: string;
  tax_recoverable: string;
  cost: string;
  gross_outlay: string;
}

/** The split stored on a component, or null when it is unclassified or the project does not use component tax. */
export function componentTaxSplit(component: AssemblyComponent): ComponentTaxSplit | null {
  const raw = (component.metadata as Record<string, unknown> | undefined)?.tax;
  if (!raw || typeof raw !== 'object') return null;
  const split = raw as Partial<ComponentTaxSplit>;
  return typeof split.net === 'string' && typeof split.tax === 'string' ? (split as ComponentTaxSplit) : null;
}

/** The assembly totals the server keeps in metadata, or null. */
export function assemblyTaxTotals(assembly: Pick<Assembly, 'metadata'>): AssemblyTaxTotals | null {
  const raw = assembly.metadata?.tax_totals;
  if (!raw || typeof raw !== 'object') return null;
  const totals = raw as Partial<AssemblyTaxTotals>;
  return typeof totals.net === 'string' && typeof totals.cost === 'string' ? (totals as AssemblyTaxTotals) : null;
}

/** An approved assembly keeps its prices through every tax recalculation. */
export function isAssemblyApproved(assembly: Pick<Assembly, 'metadata'>): boolean {
  const meta = assembly.metadata ?? {};
  const status = String(meta.status ?? '').toLowerCase();
  return meta.approved === true || ['approved', 'released', 'frozen'].includes(status);
}
