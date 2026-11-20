// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * /survey/plan: the project's plan on the full canvas. Survey points and
 * control are editable for writers (moves and codes go to the edit history),
 * linework follows the code library, the sketch layer holds drawn shapes.
 * `?focus=<feature id>` opens on one feature.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Breadcrumb, EmptyState, ErrorState, Skeleton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useSurveyAccess } from '@/features/survey/useSurveyAccess';
import { planApi, planKeys, type PlanPointOut } from './api';
import PlanCanvas from './PlanCanvas';
import { layer } from './planLayers';
import type { PlanFeature, PlanLayerSpec } from './types';

const CONTROL_KINDS = new Set(['control', 'benchmark']);

/** A served point as a canvas feature; the id doubles as the edit-history entity id. */
export function pointFeature(p: PlanPointOut): PlanFeature {
  const control = CONTROL_KINDS.has(p.kind);
  return {
    id: `point:${p.id}`,
    layer: control ? 'control' : 'points',
    geometry: { type: 'Point', coordinates: p.z == null ? [p.e, p.n] : [p.e, p.n, p.z] },
    properties: { label: p.point_id, code: p.code, kind: p.kind, source_line: p.source_line },
    entityType: 'point',
    entityId: p.id,
    rev: p.rev,
  };
}

export default function PlanEditorPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const { canWrite } = useSurveyAccess();
  const [params] = useSearchParams();
  const enabled = !!projectId;
  const points = useQuery({ queryKey: planKeys.points(projectId ?? ''), queryFn: () => planApi.points(projectId!), enabled });
  const sketch = useQuery({ queryKey: planKeys.sketch(projectId ?? ''), queryFn: () => planApi.sketch(projectId!), enabled });
  const title = t('plan.page.title', { defaultValue: 'Plan editor' });

  const layers = useMemo((): PlanLayerSpec[] => {
    const feats = (points.data?.items ?? []).map(pointFeature);
    return [
      layer('control', feats.filter((f) => f.layer === 'control'), { editable: true }),
      layer('points', feats.filter((f) => f.layer === 'points'), { editable: true }),
      layer('sketch', sketch.data?.features ?? [], { editable: true }),
    ];
  }, [points.data, sketch.data]);

  const focus = params.get('focus') ?? params.get('id') ?? undefined;

  let body;
  if (!projectId) {
    body = <EmptyState title={t('plan.page.no_project', { defaultValue: 'Open a project to see its plan.' })} />;
  } else if (points.isLoading || sketch.isLoading) {
    body = <Skeleton className="h-[calc(100vh-11rem)]" />;
  } else if (points.error || sketch.error) {
    body = (
      <ErrorState
        title={t('plan.page.error', { defaultValue: 'The plan could not be loaded.' })}
        onRetry={() => {
          void points.refetch();
          void sketch.refetch();
        }}
      />
    );
  } else {
    body = (
      <PlanCanvas
        projectId={projectId}
        layers={layers}
        editable={canWrite}
        focusFeatureId={focus}
        heightClass="h-[calc(100vh-11rem)] min-h-[28rem]"
        testId="plan-editor"
        empty={{
          title: t('plan.page.empty', { defaultValue: 'No points yet. Import a points file, or start drawing on the sketch layer.' }),
          action: (
            <Link to="/survey/points" className="text-sm font-medium text-oe-blue-text hover:underline">
              {t('plan.page.import', { defaultValue: 'Import points' })}
            </Link>
          ),
        }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="plan-editor-page">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }), to: '/survey' }, { label: title }]} />
      <PageHeader srTitle={title} />
      {body}
    </div>
  );
}
