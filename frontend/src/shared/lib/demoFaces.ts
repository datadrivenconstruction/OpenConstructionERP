// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The picture each showcase demo wears: the site scene of the company type it
 * plays (the Cases hub thumbs, the same ones the demo chooser shows), and a
 * building drawing when there is none. Read from the demo descriptor
 * (`DemoProfile.face`), so a new demo gets its hexagon by declaring a face.
 */

import { companyThumbFor } from '@/features/cases/caseFaces';
import type { HexBuildingKind } from '@/shared/ui/HexMark';
import { DEMO_PROFILES, type DemoFace } from './demoProfiles';

// Demos whose descriptor does not declare a face yet (the chooser carries the same pairs).
const PENDING_FACES: Record<string, DemoFace> = {
  'school-paris': { companyType: 'government-agency', kind: 'residential' },
  'office-shanghai': { companyType: 'estimator', kind: 'tower' },
};

/** Photo (or null) and fallback drawing for a demo slug; unknown slugs get a drawing only. */
export function demoFaceFor(slug: string): { src: string | null; kind: HexBuildingKind } {
  const face = DEMO_PROFILES.find((p) => p.slug === slug)?.face ?? PENDING_FACES[slug];
  if (!face) return { src: null, kind: 'warehouse' };
  return { src: companyThumbFor(face.companyType), kind: face.kind };
}
