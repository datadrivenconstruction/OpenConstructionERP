// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pick a project surface, sample it along the centreline, show the long and cross sections. */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { getErrorMessage } from '@/shared/lib/api';
import { centreline, type AlignmentDesign } from '../engine/alignmentGeom';
import { crossOffsets, crossSections, longSection } from '../engine/sections';
import { sectionApi } from '../p3api';
import type { PlanConventions } from '../units';
import { CrossSections } from './CrossSections';
import { LongSection } from './LongSection';

export interface SectionPanelProps {
  projectId: string;
  design: AlignmentDesign;
  conventions: PlanConventions;
  labelEvery?: number;
  crossEvery?: number;
  halfWidth?: number;
  onHover?: (ch: number | null) => void;
}

export function SectionPanel({ projectId, design, conventions, labelEvery = 100, crossEvery = 20, halfWidth = 20, onHover }: SectionPanelProps) {
  const { t } = useTranslation();
  const surfaces = useQuery({ queryKey: ['survey-plan', 'surfaces', projectId], queryFn: () => sectionApi.surfaces(projectId), retry: false });
  const [pick, setPick] = useState('');
  const surfaceId = pick || surfaces.data?.[0]?.id || '';
  const line = useMemo(() => centreline(design, 2), [design]);
  const sample = useQuery({
    queryKey: ['survey-plan', 'sample', surfaceId, line, crossEvery, halfWidth],
    queryFn: () => sectionApi.sample(surfaceId, { polyline: line, interval: crossEvery / 4, offsets: crossOffsets(halfWidth, 2) }),
    enabled: !!surfaceId && line.length >= 2,
    retry: false,
  });
  const long = useMemo(() => longSection(sample.data?.rows ?? [], design.startCh), [sample.data, design.startCh]);
  const cross = useMemo(() => crossSections(sample.data?.rows ?? [], design.startCh, crossEvery), [sample.data, design.startCh, crossEvery]);
  const marks = design.curves.flatMap((c) => [
    { ch: c.tcCh, label: t('plan.align.tc_of', { defaultValue: 'TC {{ip}}', ip: c.ref }) },
    { ch: c.ctCh, label: t('plan.align.ct_of', { defaultValue: 'CT {{ip}}', ip: c.ref }) },
  ]);

  if (surfaces.isLoading) return null;
  if (!surfaces.data?.length) {
    return <p className="text-sm text-content-tertiary">{t('plan.section.no_surface', { defaultValue: 'Sections need a ground surface. Build one from survey points under Surfaces and volumes.' })}</p>;
  }
  return (
    <div className="space-y-3" data-testid="section-panel">
      <label className="flex items-center gap-2 text-sm">
        <span className="oe-label mb-0">{t('plan.section.surface', { defaultValue: 'Ground surface' })}</span>
        <select className="oe-select" value={surfaceId} onChange={(e) => setPick(e.target.value)}>
          {surfaces.data.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        {sample.isError && <span className="text-xs text-semantic-error">{getErrorMessage(sample.error)}</span>}
      </label>
      <LongSection points={long} conventions={conventions} labelEvery={labelEvery} marks={marks} onHover={onHover} />
      {cross.length > 0 && <CrossSections sections={cross} conventions={conventions} onStation={(ch) => onHover?.(ch)} />}
    </div>
  );
}
