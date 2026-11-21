// Design module (ERP side of the design editor link).
/**
 * The workspace canvas before the person changes anything: the newest in-play revision's real model (the one the
 * revisions and acceptance pages show), not the simplified browser preview. Labelled with the revision it is.
 */

import { useTranslation } from 'react-i18next';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import { useModelViewerData } from '@/features/bim/useModelViewerData';
import { tr } from './BriefFields';
import { upAxis, type RevisionView } from './data/revisions';
import { useIsoFrame } from './frameView';
import { useQuietViewer, VIEWER_FRAME } from './useQuietViewer';

export function TipModel({ projectId, revision, onSelect }: {
  projectId: string; revision: RevisionView & { bim_model_id: string };
  onSelect: (el: { element_key: string; ifc_class: string } | null) => void;
}) {
  const { t } = useTranslation();
  const viewer = useModelViewerData(projectId, revision.bim_model_id);
  const iso = useIsoFrame();
  useQuietViewer();
  return (
    <div ref={iso.box} data-testid="tip-model"
      className={`relative h-full min-h-[360px] overflow-hidden rounded-lg border border-border-light ${VIEWER_FRAME}`}>
      <BIMViewer key={revision.bim_model_id} modelId={revision.bim_model_id} projectId={projectId}
        modelName={`#${revision.number}`} modelMetadata={viewer.activeModel?.metadata ?? null}
        elements={viewer.elements} geometryUrl={viewer.geometryUrl} isLoading={viewer.isLoadingElements}
        glbUpAxis={upAxis(revision)} onSceneReady={iso.onSceneReady} onGeometryLoaded={iso.onGeometryLoaded}
        onSelectionChange={(_ids, els) => {
          const el = els[0];
          onSelect(el ? { element_key: el.stable_id ?? el.id, ifc_class: el.element_type ?? 'IfcBuildingElementProxy' } : null);
        }}
        className="h-full" />
      <span data-testid="tip-label" className="pointer-events-none absolute bottom-2 left-2 rounded bg-surface-primary/85 px-2 py-1 text-xs text-content-secondary">
        {tr(t, 'design.revisions.number', { number: revision.number })} · {tr(t, `design.revisions.status.${revision.status}`)}
      </span>
    </div>
  );
}
