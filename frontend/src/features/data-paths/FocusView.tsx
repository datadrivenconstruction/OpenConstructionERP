// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One module in the middle of its data paths: the swimlane canvas on the left,
// the panel about the module on the right. Used by the drawer behind every
// module's Data paths button and by the full page. The focus, the selected
// card and a playing trace can live in the URL (`?node=&trace=&step=`), so a
// link opens the same picture.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { useModuleFocus, usePlatformMapProgressive } from './api';
import { FocusCanvas, type LayoutMode } from './FocusCanvas';
import { FocusPanel, type TraceState } from './FocusPanel';
import { moduleMeta } from './moduleMeta';
import { useReducedMotion } from './motion';
import { traceEdges } from './swimlane';

const STEP_MS = 1400;
const LAYOUT_KEY = 'oe.dataPaths.layout';

function storedLayout(): LayoutMode {
  try {
    const v = window.localStorage.getItem(LAYOUT_KEY);
    return v === 'landscape' || v === 'portrait' ? v : 'auto';
  } catch {
    return 'auto';
  }
}

export interface FocusViewProps {
  module: string;
  projectId: string | null;
  /** Only fetch while visible: the graph loads when the window opens. */
  enabled?: boolean;
  /** Keep focus, node and trace in the URL (full page). */
  deepLink?: boolean;
  technical?: boolean;
  onOpenModule?: (route: string) => void;
  onPeople?: () => void;
  canvasHeight?: number | string;
}

export function FocusView({ module, projectId, enabled = true, deepLink = false, technical = false, onOpenModule, onPeople, canvasHeight = 640 }: FocusViewProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const [search, setSearch] = useSearchParams();
  const [localFocus, setLocalFocus] = useState(module);
  useEffect(() => setLocalFocus(module), [module]);
  const focus = (deepLink && search.get('focus_node')) || localFocus;
  const [layout, setLayoutState] = useState<LayoutMode>(storedLayout);
  const [stages, setStages] = useState<Map<string, number>>(new Map());

  const initialTrace: TraceState | null = useMemo(() => {
    const id = deepLink ? search.get('trace') : null;
    return id ? { id, step: Number(search.get('step') ?? 0) || 0, playing: false } : null;
    // Read once: later changes go the other way, state to URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [trace, setTrace] = useState<TraceState | null>(initialTrace);

  const map = usePlatformMapProgressive(projectId, enabled);
  const info = useModuleFocus(focus, enabled);
  const active = useMemo(() => info.data?.traces.find((x) => x.id === trace?.id) ?? null, [info.data, trace?.id]);

  useEffect(() => {
    if (!trace?.playing || !active) return undefined;
    if (trace.step >= active.steps.length - 1) {
      setTrace({ ...trace, playing: false });
      return undefined;
    }
    const id = window.setTimeout(() => setTrace({ ...trace, step: trace.step + 1 }), reduce ? STEP_MS * 1.5 : STEP_MS);
    return () => window.clearTimeout(id);
  }, [trace, active, reduce]);

  useEffect(() => {
    if (!deepLink) return;
    const next = new URLSearchParams(search);
    if (trace) {
      next.set('trace', trace.id);
      next.set('step', String(trace.step));
    } else {
      next.delete('trace');
      next.delete('step');
    }
    if (next.toString() !== search.toString()) setSearch(next, { replace: true });
  }, [trace, deepLink, search, setSearch]);

  const setLayout = (mode: LayoutMode) => {
    setLayoutState(mode);
    try {
      window.localStorage.setItem(LAYOUT_KEY, mode);
    } catch {
      // Private mode: the choice lasts for this view only.
    }
  };

  const refocus = useCallback(
    (m: string) => {
      setTrace(null);
      if (deepLink) {
        const next = new URLSearchParams(search);
        next.set('focus_node', m);
        next.delete('trace');
        next.delete('step');
        setSearch(next, { replace: true });
      } else {
        setLocalFocus(m);
      }
    },
    [deepLink, search, setSearch],
  );

  const open = useCallback(
    (m: string) => {
      const route = moduleMeta(m).route;
      if (!route) return;
      if (onOpenModule) onOpenModule(route);
      else navigate(route);
    },
    [navigate, onOpenModule],
  );

  const traceModules = useMemo(
    () => (active && trace ? active.steps.slice(0, trace.step + 1).map((s) => s.module) : []),
    [active, trace],
  );
  const traceLinks = useMemo(() => (active && trace ? traceEdges(active.steps, trace.step) : []), [active, trace]);
  const downstream = useMemo(
    () => [...stages].filter(([, s]) => s > 0).sort((a, b) => a[1] - b[1]).map(([m]) => m),
    [stages],
  );

  if (map.isLoading || !map.data) {
    return map.isError ? (
      <p className="text-sm text-semantic-error">{t('data_paths.load_failed', { defaultValue: 'The data paths could not be loaded.' })}</p>
    ) : (
      <div className="flex h-[520px] items-center justify-center rounded-2xl bg-surface-secondary" role="status" aria-busy="true" data-testid="dp-focus-loading">
        <span className="inline-flex items-center gap-2 text-sm text-content-tertiary">
          <Loader2 size={16} className="animate-spin" aria-hidden />
          {t('data_paths.loading_map', { defaultValue: 'Drawing the data paths' })}
        </span>
      </div>
    );
  }

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]" data-testid="dp-focus-view">
      <div className="min-w-0" style={{ height: canvasHeight }}>
        <FocusCanvas
          focus={focus}
          modules={map.data.modules}
          edges={map.data.edges}
          info={info.data}
          projectId={projectId}
          technical={technical}
          layout={layout}
          onLayout={setLayout}
          traceLinks={traceLinks}
          traceModules={traceModules}
          onRefocus={refocus}
          onOpen={open}
          onRole={onPeople ? () => onPeople() : undefined}
          onWindow={setStages}
        />
      </div>
      <FocusPanel
        focus={focus}
        info={info.data}
        modules={map.data.modules}
        edges={map.data.edges}
        technical={technical}
        projectId={projectId}
        downstream={downstream}
        trace={trace}
        onTrace={setTrace}
        onOpen={open}
        onRefocus={refocus}
        onPeople={onPeople}
      />
    </div>
  );
}
