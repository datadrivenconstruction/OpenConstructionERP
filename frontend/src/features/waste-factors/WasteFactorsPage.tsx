// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Waste Factors - turn net measured quantities into gross procurement
 * quantities by applying a library of waste, lap and coverage factors per
 * material or work category (rebar laps, tile waste, concrete over-pour).
 *
 * Two areas, both working against the platform-wide factor library:
 *   1. Factor library: manage category -> multiplier entries (>= 1).
 *   2. Quick apply: paste "category quantity" lines and see the gross result.
 *
 * Quantities and factors are decimal strings end to end, never float-mathed.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Layers, Wand2, Sparkles, ArrowRight, Loader2, Package } from 'lucide-react';
import { Button, Badge, Card, CardHeader, EmptyState, ErrorState, Input, PageHeader } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { parseDecimalInput, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { getResourceStatement } from '@/features/resource-summary/api';
import {
  listFactors,
  createFactor,
  deleteFactor,
  seedDefaults,
  applyFactors,
  parseApplyInput,
  materialLinesToApplyInput,
  trimQty,
  type ApplyLineInput,
  type ApplyResponse,
} from './api';

const QK = {
  factors: ['waste-factors', 'library'] as const,
};

export function WasteFactorsPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('waste_factors.title', { defaultValue: 'Waste Factors' })}
        subtitle={t('waste_factors.subtitle', {
          defaultValue:
            'Convert net measured quantities into gross procurement quantities using a library of waste, lap and coverage factors, so purchase quantities reflect real site consumption.',
        })}
      />
      <WasteFactorsContent />
    </div>
  );
}

function WasteFactorsContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const factorsQ = useQuery({ queryKey: QK.factors, queryFn: () => listFactors() });
  const factors = useMemo(() => factorsQ.data ?? [], [factorsQ.data]);

  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  // ── Add-factor form state ──────────────────────────────────────────────
  const [newCategory, setNewCategory] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [newFactor, setNewFactor] = useState('');
  const [newNote, setNewNote] = useState('');

  const createMut = useMutation({
    mutationFn: () =>
      createFactor({
        category: newCategory.trim(),
        label: newLabel.trim(),
        factor: toDecimalPayloadString(newFactor),
        note: newNote.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QK.factors });
      setNewCategory('');
      setNewLabel('');
      setNewFactor('');
      setNewNote('');
    },
    onError,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteFactor(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QK.factors }),
    onError,
  });

  const seedMut = useMutation({
    mutationFn: () => seedDefaults(),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: QK.factors });
      addToast({
        type: 'success',
        title: t('waste_factors.seeded', { defaultValue: 'Starter factors added' }),
        message: t('waste_factors.seeded_detail', {
          defaultValue: '{{inserted}} added, {{skipped}} already present',
          inserted: res.inserted,
          skipped: res.skipped,
        }),
      });
    },
    onError,
  });

  // A stored factor must be at least 1 (a factor below 1 would drop quantity).
  const parsedFactor = parseDecimalInput(newFactor);
  const factorValid = parsedFactor !== null && parsedFactor >= 1;
  const factorTooLow = parsedFactor !== null && parsedFactor < 1;

  // ── Quick-apply panel state ────────────────────────────────────────────
  const [applyText, setApplyText] = useState('');
  const [applyResult, setApplyResult] = useState<ApplyResponse | null>(null);

  const parsedLines = useMemo(() => parseApplyInput(applyText), [applyText]);

  const applyMut = useMutation({
    mutationFn: (lines: ApplyLineInput[]) => applyFactors(lines),
    onSuccess: (res) => setApplyResult(res),
    onError,
  });

  const canApply = parsedLines.length > 0 && !applyMut.isPending;

  // Prefill the calculator from the active project's estimate: read its
  // resource statement (READ-ONLY), turn the material group's { name, quantity }
  // rows into net lines, drop them into the paste box and run the existing
  // net-to-gross flow. This only feeds the calculator - no billed quantity is
  // touched.
  const loadMaterialsMut = useMutation({
    mutationFn: () => getResourceStatement(activeProjectId as string),
    onSuccess: (statement) => {
      const materialGroup = statement.groups.find((g) => g.kind === 'material');
      const lines = materialLinesToApplyInput(materialGroup?.lines ?? []);
      if (lines.length === 0) {
        addToast({
          type: 'info',
          title: t('waste_factors.no_materials_title', { defaultValue: 'No materials to load' }),
          message: t('waste_factors.no_materials_msg', {
            defaultValue: "This project's estimate has no material quantities yet.",
          }),
        });
        return;
      }
      setApplyText(lines.map((l) => `${l.category} ${trimQty(l.net_qty)}`).join('\n'));
      applyMut.mutate(lines);
    },
    onError,
  });

  if (factorsQ.isError) {
    return (
      <ErrorState
        title={t('waste_factors.load_error', { defaultValue: 'Could not load the waste-factor library' })}
        onRetry={() => factorsQ.refetch()}
      />
    );
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      {/* ── Factor library ─────────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Layers className="h-4 w-4 text-oe-blue" aria-hidden />
              {t('waste_factors.library_title', { defaultValue: 'Factor library' })}
            </span>
          }
          subtitle={t('waste_factors.library_subtitle', {
            defaultValue: 'A multiplier per category. 1.10 means order 10 percent more than the drawn quantity.',
          })}
        />
        <div className="mt-4 space-y-4">
          {factorsQ.isLoading ? (
            <span className="inline-flex items-center gap-2 text-sm text-content-tertiary">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t('common.loading', { defaultValue: 'Loading...' })}
            </span>
          ) : factors.length === 0 ? (
            <EmptyState
              icon={<Layers className="h-5 w-5" />}
              title={t('waste_factors.no_factors', { defaultValue: 'No waste factors yet' })}
              description={t('waste_factors.no_factors_desc', {
                defaultValue: 'Add a category and its multiplier, or load a few sensible starting factors.',
              })}
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Sparkles className="h-4 w-4" />}
                  loading={seedMut.isPending}
                  onClick={() => seedMut.mutate()}
                >
                  {t('waste_factors.seed_defaults', { defaultValue: 'Load starter factors' })}
                </Button>
              }
            />
          ) : (
            <ul className="divide-y divide-border-light">
              {factors.map((f) => (
                <li key={f.id} className="flex items-center justify-between gap-3 py-1.5 text-sm">
                  <span className="min-w-0">
                    <span className="font-mono text-content-primary">{f.category}</span>
                    {f.label && <span className="ml-2 text-content-tertiary">{f.label}</span>}
                    {f.note && <div className="truncate text-xs text-content-tertiary">{f.note}</div>}
                  </span>
                  <span className="flex shrink-0 items-center gap-3">
                    <Badge variant="blue" size="sm">
                      &times;{trimQty(f.factor)}
                    </Badge>
                    <button
                      type="button"
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                      className="text-content-tertiary hover:text-semantic-error"
                      onClick={() => deleteMut.mutate(f.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}

          {/* Add-factor form */}
          <div className="grid grid-cols-2 gap-2 border-t border-border-light pt-4">
            <Input
              label={t('waste_factors.category', { defaultValue: 'Category' })}
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              placeholder="rebar"
              className="font-mono"
            />
            <Input
              label={t('waste_factors.factor', { defaultValue: 'Factor' })}
              value={newFactor}
              onChange={(e) => setNewFactor(e.target.value)}
              placeholder="1.10"
              inputMode="decimal"
              error={
                factorTooLow
                  ? t('waste_factors.factor_min', { defaultValue: 'Must be 1 or more' })
                  : undefined
              }
            />
            <div className="col-span-2">
              <Input
                label={t('waste_factors.label', { defaultValue: 'Label (optional)' })}
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder={t('waste_factors.label_ph', { defaultValue: 'Reinforcement laps and offcuts' })}
              />
            </div>
            <div className="col-span-2">
              <Input
                label={t('waste_factors.note', { defaultValue: 'Note (optional)' })}
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                placeholder={t('waste_factors.note_ph', { defaultValue: 'Basis for the allowance' })}
              />
            </div>
            <div className="col-span-2 flex items-center justify-between gap-2">
              {factors.length > 0 ? (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Sparkles className="h-4 w-4" />}
                  loading={seedMut.isPending}
                  onClick={() => seedMut.mutate()}
                >
                  {t('waste_factors.seed_defaults', { defaultValue: 'Load starter factors' })}
                </Button>
              ) : (
                <span />
              )}
              <Button
                variant="secondary"
                icon={<Plus className="h-4 w-4" />}
                disabled={newCategory.trim() === '' || !factorValid || createMut.isPending}
                loading={createMut.isPending}
                onClick={() => createMut.mutate()}
              >
                {t('waste_factors.add_factor', { defaultValue: 'Add factor' })}
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {/* ── Quick apply ────────────────────────────────────────────── */}
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Wand2 className="h-4 w-4 text-oe-blue" aria-hidden />
              {t('waste_factors.apply_title', { defaultValue: 'Net to gross' })}
            </span>
          }
          subtitle={t('waste_factors.apply_subtitle', {
            defaultValue: 'Paste "category quantity" lines. Unmatched categories pass through at a factor of 1.',
          })}
        />
        <div className="mt-4 space-y-4">
          {/* Prefill the box from the active project's estimate (read-only). */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Package className="h-4 w-4" />}
              disabled={!activeProjectId || loadMaterialsMut.isPending || applyMut.isPending}
              loading={loadMaterialsMut.isPending}
              onClick={() => loadMaterialsMut.mutate()}
            >
              {t('waste_factors.load_project_materials', {
                defaultValue: "Load this project's materials",
              })}
            </Button>
            <span className="text-xs text-content-tertiary">
              {activeProjectId
                ? t('waste_factors.load_project_hint', {
                    defaultValue: "Fills the box with this project's net material quantities, then converts.",
                  })
                : t('waste_factors.load_needs_project', {
                    defaultValue: 'Select a project to load its material quantities.',
                  })}
            </span>
          </div>

          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium text-content-primary">
              {t('waste_factors.net_lines', { defaultValue: 'Net quantities' })}
            </span>
            <textarea
              value={applyText}
              onChange={(e) => setApplyText(e.target.value)}
              rows={5}
              spellCheck={false}
              placeholder={'concrete 12.5\nrebar 340\ntiling 85'}
              className="rounded-lg border border-border bg-surface-primary px-3 py-2 font-mono text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
          </label>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              icon={<Wand2 className="h-4 w-4" />}
              disabled={!canApply}
              loading={applyMut.isPending}
              onClick={() => applyMut.mutate(parsedLines)}
            >
              {t('waste_factors.run_apply', { defaultValue: 'Convert to gross' })}
            </Button>
            <span className="text-xs text-content-tertiary">
              {t('waste_factors.line_count', { defaultValue: '{{count}} lines parsed', count: parsedLines.length })}
            </span>
          </div>

          {applyResult && <ApplyResults result={applyResult} />}
        </div>
      </Card>
    </div>
  );
}

function ApplyResults({ result }: { result: ApplyResponse }) {
  const { t } = useTranslation();
  if (result.lines.length === 0) {
    return (
      <p className="text-sm text-content-tertiary">
        {t('waste_factors.no_result', { defaultValue: 'No lines to convert.' })}
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border-light">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
            <th className="px-3 py-2 font-medium">{t('waste_factors.col_category', { defaultValue: 'Category' })}</th>
            <th className="px-3 py-2 text-right font-medium">{t('waste_factors.col_net', { defaultValue: 'Net' })}</th>
            <th className="px-3 py-2 text-right font-medium">
              {t('waste_factors.col_factor', { defaultValue: 'Factor' })}
            </th>
            <th className="px-3 py-2 text-right font-medium">
              {t('waste_factors.col_gross', { defaultValue: 'Gross' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {result.lines.map((r, i) => (
            <tr key={i} className="border-b border-border-light last:border-0">
              <td className="px-3 py-2">
                <span className="font-mono text-content-secondary">{r.category}</span>
                {!r.matched && (
                  <Badge variant="warning" size="sm" className="ml-2">
                    {t('waste_factors.unmatched', { defaultValue: 'no factor' })}
                  </Badge>
                )}
              </td>
              <td className="px-3 py-2 text-right font-mono text-content-secondary">{trimQty(r.net_qty)}</td>
              <td className="px-3 py-2 text-right font-mono text-content-tertiary">
                <span className="inline-flex items-center justify-end gap-1">
                  &times;{trimQty(r.factor)}
                  <ArrowRight className="h-3 w-3 text-content-tertiary" aria-hidden />
                </span>
              </td>
              <td className="px-3 py-2 text-right font-mono font-semibold text-content-primary">
                {trimQty(r.gross_qty)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
