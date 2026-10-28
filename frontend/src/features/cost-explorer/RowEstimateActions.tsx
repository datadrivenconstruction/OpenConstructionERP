// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The handoff out of Cost Explorer: turn a result row into real estimate data.
// Every result row in "Find work" and "By resources" carries the fields a BOQ
// position or an assembly component needs ({cost_item_id, code, description,
// unit, rate, currency, region}), so a work found here can be pushed straight
// into an estimate without re-entry:
//
//   * "Add to BOQ"        - opens a project → BOQ picker and creates a new
//                           position, reusing the SAME full-fidelity path the
//                           Cost Database browser uses (fetch the full cost
//                           item, build the resource/variant metadata with
//                           buildBoqPositionDraft, POST the position).
//   * "Save as assembly"  - creates a one-line reusable assembly from the row
//                           and opens it, mirroring the costs → assembly flow.
//
// Money never gets JS arithmetic here: buildBoqPositionDraft owns the rate
// build-up, and the single Number(rate) coercion for the assembly component is
// the exact one the Cost Database browser uses when creating a component.

import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ListPlus, Loader2, PackagePlus, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { apiGet, apiPost, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { listBoqPickerProjects, listBoqPickerBoqs } from '@/features/norm-expansion/api';
import { buildBoqPositionDraft, type FullCostItem } from '@/features/costs/addToBoqHelpers';

/** The minimal result-row shape both Cost Explorer result lists already carry. */
export interface EstimateRow {
  cost_item_id: string;
  code: string;
  description?: string;
  unit?: string;
  /** Decimal-as-string rate from the API (may also arrive as a number). */
  rate?: string | number;
  currency?: string;
  region?: string | null;
}

const SELECT_CLS =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary ' +
  'focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30 disabled:opacity-60';

/**
 * The two estimate-handoff controls for one result row: "Add to BOQ" (opens the
 * picker dialog) and "Save as assembly" (creates + opens a one-line assembly).
 * Rendered inside each row's action stack in both result panels.
 */
export function RowEstimateActions({ row }: { row: EstimateRow }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [pickerOpen, setPickerOpen] = useState(false);

  const currency = (row.currency || '').trim().toUpperCase();
  const name = (row.description || row.code || '').trim() || row.code;
  const unit = row.unit || '';

  // Create a single-line assembly from this row (assembly + one component), then
  // open it so the estimator can add more components or apply it to a BOQ.
  // Mirrors the Cost Database browser's create-assembly flow verbatim.
  const saveAssembly = useMutation({
    mutationFn: async () => {
      const code = `ASM-${Date.now().toString(36).toUpperCase()}`;
      const assembly = await apiPost<{ id: string }>('/v1/assemblies/', {
        code,
        name,
        unit,
        category: 'General',
        currency,
      });
      await apiPost(`/v1/assemblies/${assembly.id}/components/`, {
        cost_item_id: row.cost_item_id,
        description: row.description || row.code,
        unit,
        unit_cost: Number(row.rate) || 0,
        quantity: 1,
        factor: 1.0,
      });
      return assembly.id;
    },
    onSuccess: (id) => {
      addToast({
        type: 'success',
        title: t('costExplorer.assembly.saved', { defaultValue: 'Saved as assembly' }),
        message: t('costExplorer.assembly.savedHint', {
          defaultValue: 'Opening the assembly so you can add components and apply it.',
        }),
      });
      navigate(`/assemblies/${id}`);
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('costExplorer.assembly.saveFailed', { defaultValue: 'Could not save the assembly' }),
        message: getErrorMessage(e),
      }),
  });

  return (
    <>
      <button
        type="button"
        onClick={() => setPickerOpen(true)}
        className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
      >
        <ListPlus className="h-3.5 w-3.5" /> {t('costExplorer.actions.addToBoq', { defaultValue: 'Add to BOQ' })}
      </button>
      <button
        type="button"
        onClick={() => saveAssembly.mutate()}
        disabled={saveAssembly.isPending}
        className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline disabled:opacity-60"
      >
        {saveAssembly.isPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <PackagePlus className="h-3.5 w-3.5" />
        )}{' '}
        {t('costExplorer.actions.saveAssembly', { defaultValue: 'Save as assembly' })}
      </button>
      {pickerOpen && <AddToBoqDialog row={row} onClose={() => setPickerOpen(false)} />}
    </>
  );
}

/**
 * Project → BOQ picker that creates a new BOQ position from a Cost Explorer row.
 *
 * The picker lists reuse the app's existing endpoints via the norm-expansion
 * helpers (GET /v1/projects/, GET /v1/boq/boqs/?project_id=). On confirm it
 * replicates the Cost Database browser's add-to-BOQ path exactly: fetch the full
 * cost item (so the position inherits every resource + the variant catalog),
 * build the metadata + unit_rate with buildBoqPositionDraft (all Decimal-string
 * coercion lives there), number the position after the current max ordinal, and
 * POST it with source 'cost_database'.
 */
function AddToBoqDialog({ row, onClose }: { row: EstimateRow; onClose: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [projectId, setProjectId] = useState('');
  const [boqId, setBoqId] = useState('');

  const projectsQuery = useQuery({
    queryKey: ['cost-explorer', 'boq-projects'],
    queryFn: listBoqPickerProjects,
  });
  const boqsQuery = useQuery({
    queryKey: ['cost-explorer', 'boq-boqs', projectId],
    queryFn: () => listBoqPickerBoqs(projectId),
    enabled: projectId !== '',
  });

  // Land the picker ready to use: auto-select the first project / BOQ. The
  // estimator can still switch either before confirming.
  useEffect(() => {
    const list = projectsQuery.data;
    if (list && list.length > 0 && projectId === '') setProjectId(list[0]!.id);
  }, [projectsQuery.data, projectId]);
  useEffect(() => {
    const list = boqsQuery.data;
    if (list && list.length > 0 && boqId === '') setBoqId(list[0]!.id);
  }, [boqsQuery.data, boqId]);

  // Close on Escape (the backdrop click closes too).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const addMut = useMutation({
    mutationFn: async () => {
      if (boqId === '') throw new Error('No BOQ selected');

      // Fetch the FULL cost item so the position inherits ALL resources + the
      // variant catalog (the Cost Explorer rows, like the /costs list, are
      // trimmed). Fall back to a minimal item on a transient fetch failure so
      // the add still succeeds at degraded fidelity rather than aborting.
      let full: FullCostItem;
      try {
        full = await apiGet<FullCostItem>(`/v1/costs/${encodeURIComponent(row.cost_item_id)}`);
      } catch {
        full = {
          id: row.cost_item_id,
          code: row.code,
          description: row.description || row.code,
          unit: row.unit || '',
          rate: Number(row.rate) || 0,
          currency: row.currency || '',
          region: row.region ?? null,
          classification: {},
          components: [],
          metadata_: {},
          source: 'cost_database',
        };
      }

      const itemCurrency = (full.currency || row.currency || '').trim().toUpperCase();
      const { unitRate, metadata } = buildBoqPositionDraft(full, itemCurrency, {
        labor: t('costExplorer.addToBoq.labor', { defaultValue: 'Labor' }),
        material: t('costExplorer.addToBoq.material', { defaultValue: 'Material' }),
        equipment: t('costExplorer.addToBoq.equipment', { defaultValue: 'Equipment' }),
      });

      // Number the new position after the current max ordinal (mirror the Cost
      // Database browser). A fetch failure just starts at 1.
      let nextOrdinal = 1;
      try {
        const boqData = await apiGet<{ positions?: Array<{ ordinal: string }> }>(
          `/v1/boq/boqs/${encodeURIComponent(boqId)}`,
        );
        let maxNum = 0;
        for (const p of boqData.positions ?? []) {
          for (const part of p.ordinal.split('.')) {
            const n = parseInt(part, 10);
            if (!Number.isNaN(n) && n > maxNum) maxNum = n;
          }
        }
        nextOrdinal = maxNum + 1;
      } catch {
        // start at 1
      }
      const section = String(Math.floor((nextOrdinal - 1) / 999) + 1).padStart(2, '0');
      const pos = String(((nextOrdinal - 1) % 999) + 1).padStart(3, '0');
      const ordinal = `${section}.${pos}`;

      await apiPost(`/v1/boq/boqs/${encodeURIComponent(boqId)}/positions/`, {
        boq_id: boqId,
        ordinal,
        description: full.description,
        unit: full.unit,
        quantity: 1,
        unit_rate: unitRate,
        classification: full.classification || {},
        parent_id: undefined,
        cost_item_id: row.cost_item_id,
        source: 'cost_database',
        metadata,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('costExplorer.addToBoq.added', { defaultValue: 'Added to the BOQ' }),
        message: t('costExplorer.addToBoq.addedHint', {
          defaultValue: 'A new position was created with the rate from this base.',
        }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('costExplorer.addToBoq.failed', { defaultValue: 'Could not add to the BOQ' }),
        message: getErrorMessage(e),
      }),
  });

  const projects = projectsQuery.data ?? [];
  const boqs = boqsQuery.data ?? [];
  // Both fall back to an empty array, which a failed request is indistinguishable
  // from. Gate the "nothing here" copy on the query having actually succeeded so
  // a backend outage is never reported to the estimator as an empty account.
  const noProjects =
    !projectsQuery.isLoading && !projectsQuery.isError && projects.length === 0;
  const noBoqs =
    projectId !== '' && !boqsQuery.isLoading && !boqsQuery.isError && boqs.length === 0;
  const canAdd = boqId !== '' && !addMut.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 animate-fade-in"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="ce-add-boq-title"
        className="w-full max-w-md overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border-light px-5 py-4">
          <div className="min-w-0">
            <h2 id="ce-add-boq-title" className="text-sm font-semibold text-content-primary">
              {t('costExplorer.addToBoq.title', { defaultValue: 'Add to a BOQ' })}
            </h2>
            <p className="mt-0.5 truncate text-xs text-content-tertiary">
              {row.code}
              {row.description ? ` · ${row.description}` : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="shrink-0 rounded p-1 text-content-tertiary hover:bg-surface-secondary"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <div>
            <label
              htmlFor="ce-add-boq-project"
              className="mb-1 block text-xs font-medium text-content-secondary"
            >
              {t('costExplorer.addToBoq.project', { defaultValue: 'Project' })}
            </label>
            <select
              id="ce-add-boq-project"
              className={SELECT_CLS}
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                setBoqId('');
              }}
            >
              <option value="">
                {projectsQuery.isLoading
                  ? t('common.loading', { defaultValue: 'Loading...' })
                  : t('costExplorer.addToBoq.chooseProject', { defaultValue: 'Choose a project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="ce-add-boq-boq"
              className="mb-1 block text-xs font-medium text-content-secondary"
            >
              {t('costExplorer.addToBoq.boq', { defaultValue: 'BOQ' })}
            </label>
            <select
              id="ce-add-boq-boq"
              className={SELECT_CLS}
              value={boqId}
              onChange={(e) => setBoqId(e.target.value)}
              disabled={projectId === ''}
            >
              <option value="">
                {boqsQuery.isLoading
                  ? t('common.loading', { defaultValue: 'Loading...' })
                  : t('costExplorer.addToBoq.chooseBoq', { defaultValue: 'Choose a BOQ...' })}
              </option>
              {boqs.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>

          {noProjects && (
            <p className="text-xs text-content-tertiary">
              {t('costExplorer.addToBoq.noProjects', {
                defaultValue: 'No projects yet. Create a project first, then add a BOQ to it.',
              })}
            </p>
          )}
          {noBoqs && (
            <p className="text-xs text-content-tertiary">
              {t('costExplorer.addToBoq.noBoqs', {
                defaultValue: 'This project has no BOQ yet. Open the BOQ module to create one.',
              })}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border-light px-5 py-3">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="sm" disabled={!canAdd} onClick={() => addMut.mutate()}>
            {addMut.isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <ListPlus className="mr-1.5 h-3.5 w-3.5" />
            )}
            {addMut.isPending
              ? t('costExplorer.addToBoq.adding', { defaultValue: 'Adding...' })
              : t('costExplorer.addToBoq.add', { defaultValue: 'Add position' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
