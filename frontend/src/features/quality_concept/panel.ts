// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the page hands every tab.

import type { Catalogue, Concept } from './api';
import type { LabelContext } from './labels';

export type QcTab = 'concept' | 'certification' | 'proofs' | 'stages' | 'acceptance' | 'preservation';

export const QC_TABS: QcTab[] = ['concept', 'certification', 'proofs', 'stages', 'acceptance', 'preservation'];

export interface PanelProps {
  projectId: string;
  concept: Concept;
  /** The pinned catalogue; undefined while it loads, and names fall back to readable codes meanwhile. */
  catalogue: Catalogue | undefined;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  /** Whether the plan can be edited in the concept's current state. */
  editable: boolean;
  /** The server lets this reader change the plan at all (`concept.can.manage`). */
  manage: boolean;
  openTab: (tab: QcTab) => void;
}

/** A package reference written for a reader: its code and title when the scope knows them. */
export function packageName(concept: Pick<Concept, 'applicable_packages'>, ref: string | null | undefined): string {
  if (!ref) return '';
  const pkg = concept.applicable_packages.find((p) => p.ref === ref);
  if (!pkg) return ref;
  const parts = [pkg.code, pkg.title].filter((s) => s && s.trim());
  return parts.length > 0 ? parts.join(' ') : ref;
}
