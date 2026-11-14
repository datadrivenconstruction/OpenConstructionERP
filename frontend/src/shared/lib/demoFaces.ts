// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The picture each showcase demo wears: the site scene of the company type it
 * plays (the Cases hub thumbs, the same ones the demo chooser shows), and a
 * building drawing when there is none. Lives in shared/lib so the app-shell
 * demo tabs can read it without pulling the lazily loaded chooser page.
 */

import { companyThumbFor } from '@/features/cases/caseFaces';
import type { HexBuildingKind } from '@/shared/ui/HexMark';

const DEMO_FACE: Record<string, { companyType: string; kind: HexBuildingKind }> = {
  'full-showcase-riyadh': { companyType: 'full_enterprise', kind: 'hospital' },
  'residential-berlin': { companyType: 'general_contractor', kind: 'residential' },
  'office-london': { companyType: 'commercial-manager', kind: 'tower' },
  'medical-us': { companyType: 'construction-manager', kind: 'hospital' },
  'condo-toronto': { companyType: 'real_estate_developer', kind: 'tower' },
};

/** Photo (or null) and fallback drawing for a demo slug; unknown slugs get a drawing only. */
export function demoFaceFor(slug: string): { src: string | null; kind: HexBuildingKind } {
  const face = DEMO_FACE[slug];
  if (!face) return { src: null, kind: 'warehouse' };
  return { src: companyThumbFor(face.companyType), kind: face.kind };
}
