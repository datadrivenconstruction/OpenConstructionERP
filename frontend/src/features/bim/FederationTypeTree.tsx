// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FederationTypeTree — Slice 2 of BIM Federations.
 *
 * Counter-intuitive design note
 * -----------------------------
 * Most BIM viewers nest the federation tree as
 * ``Federation › Model › Storey › Element``. Some BIM coordination tools invert it
 * to ``Federation › IfcClass › [all instances across all models]``. The
 * flat-by-class layout is what makes "color all mechanical ducts red
 * across 12 models" a single click instead of a 12-step traversal.
 * This component renders the flat-by-class tree; the per-model split
 * lives in the drill-down (``member_breakdown``) so the information is
 * not lost.
 *
 * Endpoint: GET /api/v1/bim-hub/federations/{federation_id}/type-tree
 */
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Box,
  ChevronDown,
  ChevronRight,
  Columns3,
  DoorOpen,
  Layers,
  PanelTop,
  Pipette,
  RectangleHorizontal,
  Settings2,
  Square,
  Wind,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { apiGet } from '@/shared/lib/api';
import { Badge } from '@/shared/ui';

/* ── Types ─────────────────────────────────────────────────────────── */

interface TypeTreeMember {
  model_id: string;
  model_name: string;
  discipline: string;
  element_count: number;
}

interface TypeTreeClass {
  ifc_class: string;
  display_name: string;
  element_count: number;
  member_breakdown: TypeTreeMember[];
  sample_properties: string[];
}

interface TypeTreeResponse {
  federation_id: string;
  total_elements: number;
  classes: TypeTreeClass[];
}

interface Props {
  federationId: string;
  onSelectClass?: (ifcClass: string, modelIds: string[]) => void;
}

/* ── Icon map ─────────────────────────────────────────────────────── */
// Lucide does not ship an icon per IfcClass — we map the most-common
// ones explicitly and fall back to ``Box`` for everything else. The
// component intentionally avoids importing the entire lucide icon set.
const ICON_BY_CLASS: Record<string, LucideIcon> = {
  IfcWall: RectangleHorizontal,
  IfcWallStandardCase: RectangleHorizontal,
  IfcSlab: Layers,
  IfcRoof: PanelTop,
  IfcDoor: DoorOpen,
  IfcWindow: Square,
  IfcColumn: Columns3,
  IfcBeam: Settings2,
  IfcDuctSegment: Wind,
  IfcPipeSegment: Pipette,
  IfcFlowSegment: Wind,
};

function iconFor(ifcClass: string): LucideIcon {
  return ICON_BY_CLASS[ifcClass] ?? Box;
}

/* ── API ──────────────────────────────────────────────────────────── */

async function fetchTypeTree(
  federationId: string,
): Promise<TypeTreeResponse> {
  return apiGet<TypeTreeResponse>(
    `/v1/bim-hub/federations/${federationId}/type-tree`,
  );
}

/* ── Component ────────────────────────────────────────────────────── */

export function FederationTypeTree({ federationId, onSelectClass }: Props) {
  const { t } = useTranslation();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['bim-federation-type-tree', federationId],
    queryFn: () => fetchTypeTree(federationId),
    enabled: !!federationId,
  });

  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = useCallback((ifcClass: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(ifcClass)) next.delete(ifcClass);
      else next.add(ifcClass);
      return next;
    });
  }, []);

  const handleSelect = useCallback(
    (cls: TypeTreeClass) => {
      if (!onSelectClass) return;
      const ids = cls.member_breakdown.map((m) => m.model_id);
      onSelectClass(cls.ifc_class, ids);
    },
    [onSelectClass],
  );

  const totalLabel = useMemo(() => {
    if (!data) return '';
    // Manual interpolation — the i18n hook does this in production, but
    // the test mock returns ``defaultValue`` verbatim. Building the
    // string here keeps both paths honest.
    const tmpl = t('bim.federation.type_tree.total', {
      defaultValue: '{{count}} elements across {{classes}} classes',
    });
    return tmpl
      .replace('{{count}}', String(data.total_elements))
      .replace('{{classes}}', String(data.classes.length));
  }, [data, t]);

  /* ── Loading ──────────────────────────────────────────────────── */
  if (isLoading) {
    return (
      <div
        data-testid="federation-type-tree-loading"
        className="p-4 text-sm text-slate-500"
      >
        {t('bim.federation.type_tree.loading', {
          defaultValue: 'Loading element types…',
        })}
      </div>
    );
  }

  /* ── Error ────────────────────────────────────────────────────── */
  if (isError) {
    return (
      <div
        data-testid="federation-type-tree-error"
        role="alert"
        className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
      >
        {t('bim.federation.type_tree.error', {
          defaultValue: 'Failed to load element types',
        })}
        {error instanceof Error ? (
          <span className="ml-1 text-xs opacity-70">— {error.message}</span>
        ) : null}
      </div>
    );
  }

  /* ── Empty ────────────────────────────────────────────────────── */
  if (!data || data.classes.length === 0) {
    return (
      <div
        data-testid="federation-type-tree-empty"
        className="rounded border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500"
      >
        {t('bim.federation.type_tree.empty', {
          defaultValue:
            'No elements yet - add a model with imported elements to populate the type tree.',
        })}
      </div>
    );
  }

  /* ── Populated ────────────────────────────────────────────────── */
  return (
    <div data-testid="federation-type-tree" className="space-y-1">
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
        <span>{totalLabel}</span>
      </div>
      <ul className="divide-y divide-slate-100 rounded border border-slate-200">
        {data.classes.map((cls) => {
          const Icon = iconFor(cls.ifc_class);
          const isExpanded = expanded.has(cls.ifc_class);
          const tooltip =
            cls.sample_properties.length > 0
              ? `${t('bim.federation.type_tree.has_properties_label', {
                  defaultValue: 'Has properties:',
                })} ${cls.sample_properties.join(', ')}`
              : '';
          return (
            <li
              key={cls.ifc_class}
              data-testid={`federation-type-tree-row-${cls.ifc_class}`}
            >
              <div className="flex items-center gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() => toggle(cls.ifc_class)}
                  aria-label={
                    isExpanded
                      ? t('common.collapse', { defaultValue: 'Collapse' })
                      : t('common.expand', { defaultValue: 'Expand' })
                  }
                  aria-expanded={isExpanded}
                  data-testid={`federation-type-tree-toggle-${cls.ifc_class}`}
                  className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => handleSelect(cls)}
                  title={tooltip || undefined}
                  data-testid={`federation-type-tree-select-${cls.ifc_class}`}
                  className="flex flex-1 items-center gap-2 text-left text-sm text-slate-700 hover:text-slate-900"
                >
                  <Icon className="h-4 w-4 text-slate-500" aria-hidden />
                  <span className="font-medium">{cls.display_name}</span>
                  <span className="text-xs text-slate-400">
                    {cls.ifc_class}
                  </span>
                </button>
                <Badge>{cls.element_count.toLocaleString()}</Badge>
              </div>
              {isExpanded ? (
                <ul
                  data-testid={`federation-type-tree-breakdown-${cls.ifc_class}`}
                  className="space-y-1 border-t border-slate-100 bg-slate-50/50 px-3 py-2"
                >
                  {cls.member_breakdown.map((m) => (
                    <li
                      key={`${cls.ifc_class}::${m.model_id}`}
                      className="flex items-center justify-between text-xs text-slate-600"
                      data-testid={`federation-type-tree-member-${cls.ifc_class}-${m.model_id}`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-600">
                          {m.discipline}
                        </span>
                        <span className="truncate">{m.model_name}</span>
                      </div>
                      <span className="font-mono">
                        {m.element_count.toLocaleString()}
                      </span>
                    </li>
                  ))}
                  {cls.sample_properties.length > 0 ? (
                    <li className="pt-2 text-[11px] text-slate-400">
                      {/* The label is i18n'd but the property list is
                          interpolated manually — that keeps the test
                          mock (which returns ``defaultValue`` verbatim,
                          no ``{{var}}`` substitution) honest. */}
                      <span>
                        {t('bim.federation.type_tree.has_properties_label', {
                          defaultValue: 'Has properties:',
                        })}{' '}
                      </span>
                      <span>{cls.sample_properties.join(', ')}</span>
                    </li>
                  ) : null}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default FederationTypeTree;
