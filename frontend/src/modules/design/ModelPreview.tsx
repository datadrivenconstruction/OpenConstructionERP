// Design module (ERP side of the design editor link).
/**
 * Live preview beside the model panel: the brief the server would generate from (dry run) goes to the editor's
 * generator compiled to wasm, in a Web Worker; the keyed GLB is shown in the ERP viewer. Simplified geometry;
 * the revision itself is still built by the server job. No worker or no wasm: status 'off', the panel is as before.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Box } from 'lucide-react';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import { useBIMViewerStore } from '@/stores/useBIMViewerStore';
import type { BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';
import { previewBrief, type ModelValue } from './modelApi';
import { useIsoFrame } from './frameView';
import { fieldLabel } from './BriefFields';
import { VIEWER_FRAME } from './useQuietViewer';
import { countByClass, glbNodes, type GenResult, type WorkerOut } from './wasm/ddcWeb';
import wasmUrl from './wasm/ddc_web.wasm?url';
import { fmtList } from '@/shared/lib/formatters';

const DEBOUNCE_MS = 300;
const LOAD_TIMEOUT_MS = 20_000;

export type PreviewState =
  | { status: 'off' }
  | { status: 'loading' }
  | { status: 'none'; reason: string; unconfirmed?: string[] }
  | { status: 'ready'; seq: number; url: string; elements: BIMElementData[]; counts: [string, number][]; ms: number; building: boolean };

function startWorker(): Worker | null {
  if (typeof Worker === 'undefined' || typeof WebAssembly === 'undefined') return null;
  try {
    return new Worker(new URL('./wasm/preview.worker.ts', import.meta.url), { type: 'module' });
  } catch {
    return null;
  }
}

export function usePreview(projectId: string, briefVersion: number | undefined, values: Record<string, ModelValue>,
  enabled: boolean): PreviewState {
  const [state, setState] = useState<PreviewState>({ status: 'loading' });
  const [ready, setReady] = useState(false);
  const worker = useRef<Worker | null>(null);
  const waiting = useRef(new Map<number, (r: GenResult) => void>());
  const seq = useRef(0);

  useEffect(() => {
    const w = startWorker();
    if (!w) { setState({ status: 'off' }); return; }
    worker.current = w;
    const off = () => { setState({ status: 'off' }); w.terminate(); worker.current = null; };
    const timer = setTimeout(off, LOAD_TIMEOUT_MS);
    w.onmessage = (e: MessageEvent<WorkerOut>) => {
      const m = e.data;
      if (m.type === 'ready') { clearTimeout(timer); setReady(true); }
      else if (m.type === 'failed') { clearTimeout(timer); off(); }
      else { waiting.current.get(m.id)?.(m.result); waiting.current.delete(m.id); }
    };
    w.onerror = () => { clearTimeout(timer); off(); };
    w.postMessage({ type: 'init', url: new URL(wasmUrl, window.location.href).href });
    return () => { clearTimeout(timer); w.terminate(); worker.current = null; };
  }, []);

  const key = JSON.stringify(values);
  useEffect(() => {
    if (!ready || !worker.current || briefVersion === undefined) return;
    if (!enabled) { setState({ status: 'none', reason: '' }); return; }
    setState((s) => (s.status === 'ready' ? { ...s, building: true } : s));
    const timer = setTimeout(async () => {
      const id = ++seq.current;
      try {
        const { brief, problems } = await previewBrief(projectId, briefVersion, JSON.parse(key) as Record<string, ModelValue>);
        const w = worker.current;
        if (!w || id !== seq.current) return;
        if (brief == null) { setState({ status: 'none', reason: problems?.message ?? '', unconfirmed: problems?.unconfirmed }); return; }
        const result = await new Promise<GenResult>((resolve) => {
          waiting.current.set(id, resolve);
          w.postMessage({ type: 'gen', id, brief: JSON.stringify(brief) });
        });
        if (id !== seq.current) return;
        if (!result.ok) { setState({ status: 'none', reason: result.error }); return; }
        const nodes = glbNodes(result.glb);
        // A data: URL, not blob:. The ERP viewer asks for the type with HEAD first, which blob: URLs refuse
        // with a console error on every preview.
        const url = await asDataUrl(new Blob([result.glb as BlobPart], { type: 'model/gltf-binary' }));
        if (id !== seq.current) return;
        setState({
          status: 'ready', seq: id, url, ms: Math.round(result.ms), building: false, counts: countByClass(nodes),
          elements: nodes.map((n) => ({ id: n.key, stable_id: n.key, mesh_ref: n.key, name: n.key, element_type: n.ifcClass,
            discipline: 'architectural' })),
        });
      } catch (e) {
        if (id === seq.current) setState({ status: 'none', reason: e instanceof Error ? e.message : String(e) });
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [ready, projectId, briefVersion, key, enabled]);

  return state;
}

function asDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error ?? new Error('read failed'));
    r.readAsDataURL(blob);
  });
}

export function ModelPreview({ projectId, state, onSelect, tall = false }: {
  projectId: string; state: Exclude<PreviewState, { status: 'off' }>;
  /** The picked element (key and IFC class from the preview GLB), null when the pick is cleared. */
  onSelect?: (el: { element_key: string; ifc_class: string } | null) => void;
  tall?: boolean;
}) {
  const { t } = useTranslation();
  const m = (key: string, o?: Record<string, unknown>) => t(key, o) as string;
  const iso = useIsoFrame();
  // The viewer's model summary would cover the small design model on open: closed here, the person's setting
  // comes back when the preview goes.
  useEffect(() => {
    const st = useBIMViewerStore.getState();
    const was = st.summaryPanelOpen;
    st.setSummaryPanelOpen(false);
    return () => useBIMViewerStore.getState().setSummaryPanelOpen(was);
  }, []);
  return (
    <aside className={`flex min-w-0 flex-col gap-2 ${tall ? 'h-full min-h-[360px]' : ''}`} data-testid="model-preview"
      aria-label={m('design.model.preview.label')} title={tall ? m('design.model.preview.label') : undefined}>
      {!tall && <p className="text-sm font-medium text-content-primary">{m('design.model.preview.label')}</p>}
      <div ref={iso.box} className={`relative ${tall ? 'min-h-0 flex-1' : 'h-[320px]'} overflow-hidden rounded-lg border border-border-light ${VIEWER_FRAME}`}>
        {/* portal: a click shows the loaded element's own data; no /bim_hub request for a model the server lacks */}
        {state.status === 'ready' && (
          <BIMViewer key={state.seq} modelId="design-model-preview" projectId={projectId} elements={state.elements}
            geometryUrl={state.url} glbUpAxis="y" className="h-full"
            portal readOnly
            onSceneReady={iso.onSceneReady} onGeometryLoaded={iso.onGeometryLoaded}
            onElementSelect={onSelect && ((id) => {
              const el = id ? state.elements.find((e) => e.id === id) : undefined;
              onSelect(el ? { element_key: el.id, ifc_class: el.element_type ?? 'IfcBuildingElementProxy' } : null);
            })} />
        )}
        {(state.status === 'loading' || (state.status === 'ready' && state.building)) && (
          <span className="absolute left-2 top-2 rounded bg-surface-primary/80 px-2 py-1 text-xs text-content-secondary">
            {m('design.model.preview.building')}
          </span>
        )}
        {state.status === 'none' && (
          <p className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-content-tertiary"
            title={state.reason || undefined}>
            <Box size={24} aria-hidden className="text-content-quaternary" />
            {state.unconfirmed?.length ? (
              <>
                <span>{m('design.model.preview.unconfirmed', {
                  fields: fmtList(state.unconfirmed.map((p) => fieldLabel(t, p))) })}</span>
                <Link to="/design/brief" className="text-oe-blue-text underline">{m('design.model.preview.open_brief')}</Link>
              </>
            ) : m('design.model.preview.none')}
          </p>
        )}
      </div>
      {state.status === 'ready' && !tall && (
        <>
          <span className="text-xs font-medium text-content-secondary">{m('design.model.preview.counts')}</span>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-content-primary" data-testid="model-preview-counts">
            {state.counts.map(([cls, n]) => (
              <li key={cls}><span className="text-content-secondary">{cls}</span> {n}</li>
            ))}
          </ul>
          <span className="text-xs text-content-tertiary">{m('design.model.preview.took', { ms: state.ms })}</span>
        </>
      )}
    </aside>
  );
}
