// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The pack of the open demo on the hosted demo. One account there owns every
 * demo, so the install-wide pack names one country for all of them; the demo's
 * project names its own. Without an installed pack for that country nothing is
 * claimed, rather than another country's pack.
 */

import { usePartnerPack, type PartnerPackManifest } from './usePartnerPack';
import { useDemoScope } from '@/shared/lib/useDemoScope';

export interface DemoPack {
  /** A demo is open: callers show `manifest` (or nothing) instead of the install pack. */
  inDemo: boolean;
  manifest: PartnerPackManifest | null;
}

export function useDemoPack(): DemoPack {
  const scope = useDemoScope();
  const inDemo = scope.demoMode && scope.profile !== null;
  const projectId = inDemo ? (scope.project?.id ?? null) : null;
  const q = usePartnerPack(projectId);
  const fromProject = projectId !== null && q.data?.active === true && q.data.source === 'project';
  return { inDemo, manifest: fromProject ? (q.data?.manifest ?? null) : null };
}
