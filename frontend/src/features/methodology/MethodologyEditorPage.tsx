// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The methodology editor - edits one methodology's cascade (base sets,
// composites, ordered markup steps + VAT), its analytical dimensions and its
// funding sources, with a live computed preview alongside the cascade.
//
// Built-in / pack templates (project_id === null, or is_editable === false) are
// read-only platform data: PATCH / DELETE return 403, so the UI disables every
// control and offers "Duplicate to edit", which clones the methodology into an
// editable project copy and reopens the editor on it.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Coins,
  Copy,
  FileSpreadsheet,
  FileText,
  Info,
  Layers3,
  Lock,
  Save,
  Tags,
  Trash2,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TabBar, tabIds } from '@/shared/ui/TabBar';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtPercent } from '@/shared/lib/formatters';
import { methodologyApi, downloadEstimate, type MethodologyExportFormat } from './api';
import type { MarkupStep, Methodology, MethodologyUpdate } from './types';
import { CascadeSection } from './CascadeSection';
import { CascadePreview } from './CascadePreview';
import { DimensionsSection } from './DimensionsSection';
import { FundingSourcesSection } from './FundingSourcesSection';

type EditorTab = 'cascade' | 'dimensions' | 'funding';

const TAB_IDS = tabIds('methodology-editor');

/** Local editable draft of the parts of a methodology this editor changes. */
interface Draft {
  name: string;
  description: string;
  currency: string;
  decimals: number;
  baseMapping: Record<string, string[]>;
  composites: Record<string, string[]>;
  steps: MarkupStep[];
}

/**
 * Says so when the tax line on screen is not the rate the project is charged.
 *
 * The cascade below is editable, and its tax step looks like the rate in
 * force. It is not, whenever the project states a VAT rate of its own: pricing
 * substitutes the project's figure, and the exports print it, so an editor
 * showing nought can belong to a bill costed at twenty five. A methodology
 * created by hand is the case that bites, because it is seeded with a single
 * tax step at nought and that is exactly the shape the substitution replaces.
 *
 * Both the decision and the comparison come from the server, which is the same
 * code that performs the substitution. Recomputing either here would be a
 * second statement of one rule, free to drift from the engine it describes.
 */
function ProjectVatNotice({ methodology }: { methodology: Methodology }) {
  const { t } = useTranslation();
  const vat = methodology.effective_vat;

  if (!vat?.differs_from_stored || vat.source !== 'project') return null;

  // VAT rates are whole numbers far more often than not, so a blanket single
  // decimal would print "25.0 %" on most of the world's screens. The unit and
  // its placement come from the locale formatter rather than from the message,
  // which is why neither string below carries a per-cent sign of its own.
  const asPercent = (raw: string | null): string | null => {
    const n = Number(raw);
    if (raw === null || raw.trim() === '' || !Number.isFinite(n)) return null;
    return fmtPercent(n, Number.isInteger(n) ? 0 : 1);
  };

  const rate = asPercent(vat.rate);
  if (rate === null) return null;
  const stored = asPercent(vat.stored_rate);

  return (
    <div className="flex items-start gap-2 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning-strong">
      <Info size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>
        {stored === null
          ? t('methodology.vat_from_project_unreadable', {
              defaultValue:
                'This project is billed at {{rate}} VAT, which it sets itself. The tax step below does not state a rate that can be read, so the project rate is what will be charged.',
              rate,
            })
          : t('methodology.vat_from_project', {
              defaultValue:
                'This project is billed at {{rate}} VAT, which it sets itself. The tax step below stores {{stored}}, and that is not what will be charged.',
              rate,
              stored,
            })}
      </span>
    </div>
  );
}

function toDraft(m: Methodology): Draft {
  return {
    name: m.name,
    description: m.description ?? '',
    currency: m.currency ?? '',
    decimals: m.decimals ?? 2,
    baseMapping: m.base_mapping ?? {},
    composites: m.composites ?? {},
    steps: (m.cascade_steps ?? []).map((s) => ({ ...s, base: [...s.base] })),
  };
}

export function MethodologyEditorPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { methodologyId } = useParams<{ methodologyId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [tab, setTab] = useState<EditorTab>('cascade');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const methodologyQ = useQuery({
    queryKey: ['methodology', 'detail', methodologyId, activeProjectId],
    queryFn: () => methodologyApi.get(methodologyId!, activeProjectId!),
    enabled: !!methodologyId && !!activeProjectId,
  });

  const methodology = methodologyQ.data;

  // A built-in / pack template, or any non-editable / non-project-owned row, is
  // read-only (the backend enforces this with 403 on PATCH/DELETE).
  const readOnly =
    !!methodology && (!methodology.is_editable || methodology.is_builtin || methodology.project_id === null);

  // Seed the draft when the methodology id changes (first load, or switching to
  // a different methodology) - NOT on every refetch. The query is staleTime'd
  // (30s) and refetches on window focus, returning a new object reference each
  // time; depending on the whole object here would re-seed and silently clobber
  // the user's unsaved cascade edits. Keying on the id preserves the draft
  // across background refetches; the save path re-seeds explicitly in onSuccess.
  useEffect(() => {
    if (methodology) setDraft(toDraft(methodology));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [methodology?.id]);

  const dirty = useMemo(() => {
    if (!methodology || !draft) return false;
    const base = toDraft(methodology);
    return JSON.stringify(base) !== JSON.stringify(draft);
  }, [methodology, draft]);

  const saveMut = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error('no draft');
      const payload: MethodologyUpdate = {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        currency: draft.currency.trim(),
        decimals: draft.decimals,
        base_mapping: draft.baseMapping,
        composites: draft.composites,
        cascade_steps: draft.steps,
      };
      return methodologyApi.update(methodologyId!, activeProjectId!, payload);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(
        ['methodology', 'detail', methodologyId, activeProjectId],
        updated,
      );
      queryClient.invalidateQueries({ queryKey: ['methodology', 'list', activeProjectId] });
      setDraft(toDraft(updated));
      addToast({
        type: 'success',
        title: t('methodology.editor.saved', { defaultValue: 'Methodology saved' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const duplicateMut = useMutation({
    mutationFn: () => {
      if (!methodology) throw new Error('no methodology');
      return methodologyApi.create({
        project_id: activeProjectId!,
        name: t('methodology.editor.copy_name', {
          defaultValue: '{{name}} (copy)',
          name: methodology.name,
        }),
        description: methodology.description,
        country_code: methodology.country_code,
        industry: methodology.industry,
        currency: methodology.currency,
        decimals: methodology.decimals,
        hierarchy_levels: methodology.hierarchy_levels,
        dimension_scheme: methodology.dimension_scheme,
        column_preset: methodology.column_preset,
        base_mapping: methodology.base_mapping,
        composites: methodology.composites,
        cascade_steps: methodology.cascade_steps,
        vat_rate: methodology.vat_rate,
      });
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['methodology', 'list', activeProjectId] });
      addToast({
        type: 'success',
        title: t('methodology.editor.duplicated', { defaultValue: 'Editable copy created' }),
      });
      navigate(`/methodologies/${created.id}`);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMut = useMutation({
    mutationFn: () => methodologyApi.remove(methodologyId!, activeProjectId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['methodology', 'list', activeProjectId] });
      addToast({
        type: 'success',
        title: t('methodology.editor.deleted', { defaultValue: 'Methodology deleted' }),
      });
      navigate('/methodologies');
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // Export the computed estimate as a client-facing Excel / PDF document. The
  // server recomputes from the LAST SAVED methodology, so a dirty draft warns
  // the user the export reflects their saved version, not the unsaved edits.
  const exportMut = useMutation({
    mutationFn: (format: MethodologyExportFormat) =>
      downloadEstimate(methodologyId!, activeProjectId!, format),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('methodology.editor.exported', { defaultValue: 'Estimate exported' }),
      }),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  // react-query types `variables` as the mutation arg (MethodologyExportFormat)
  // while a request is in flight, so this drives the per-button spinner.
  const exportingFormat = exportMut.isPending ? exportMut.variables : undefined;

  const handleExport = (format: MethodologyExportFormat) => {
    if (dirty) {
      addToast({
        type: 'info',
        title: t('methodology.editor.export_dirty', {
          defaultValue: 'Exporting the last saved version. Save your edits to include them.',
        }),
      });
    }
    exportMut.mutate(format);
  };

  // ── No project / loading / error / not found ─────────────────────────
  if (!activeProjectId) {
    return (
      <div className="space-y-5 animate-fade-in">
        <EmptyState
          icon={<Layers3 size={22} />}
          title={t('methodology.no_project.title', { defaultValue: 'Select a project first' })}
          action={{
            label: t('methodology.no_project.action', { defaultValue: 'Go to projects' }),
            onClick: () => navigate('/projects'),
          }}
        />
      </div>
    );
  }

  if (methodologyQ.isLoading || !draft) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Skeleton height={20} width={200} />
        <Skeleton height={40} className="w-full" />
        <Skeleton height={300} className="w-full" />
      </div>
    );
  }

  if (methodologyQ.isError || !methodology) {
    return (
      <div className="space-y-5 animate-fade-in">
        <ErrorState
          title={t('methodology.editor.load_error', { defaultValue: 'Could not load this methodology.' })}
          hint={t('methodology.editor.load_error_hint', {
            defaultValue: 'It may have been deleted, or belong to another project.',
          })}
          onRetry={() => methodologyQ.refetch()}
        />
        <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={() => navigate('/methodologies')}>
          {t('methodology.editor.back', { defaultValue: 'Back to methodologies' })}
        </Button>
      </div>
    );
  }

  const updateDraft = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  const tabs = [
    {
      id: 'cascade' as const,
      label: t('methodology.editor.tab_cascade', { defaultValue: 'Markup cascade' }),
      icon: <Layers3 size={14} />,
    },
    {
      id: 'dimensions' as const,
      label: t('methodology.editor.tab_dimensions', { defaultValue: 'Dimensions' }),
      icon: <Tags size={14} />,
    },
    {
      id: 'funding' as const,
      label: t('methodology.editor.tab_funding', { defaultValue: 'Funding' }),
      icon: <Coins size={14} />,
    },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          {
            label: t('methodology.title', { defaultValue: 'Estimating methodologies' }),
            to: '/methodologies',
          },
          { label: methodology.name },
        ]}
      />

      <PageHeader
        srTitle={methodology.name}
        subtitle={
          methodology.description ||
          t('methodology.editor.subtitle', {
            defaultValue: 'Edit the markup cascade, analytical dimensions and funding sources.',
          })
        }
        actions={
          <div className="flex items-center gap-2">
            {/* Export the computed estimate as a client-facing document. Always
                available (a built-in template's estimate is exportable too). */}
            <Button
              variant="ghost"
              size="sm"
              icon={<FileSpreadsheet size={14} />}
              loading={exportingFormat === 'excel'}
              disabled={exportMut.isPending}
              onClick={() => handleExport('excel')}
            >
              {t('methodology.editor.export_excel', { defaultValue: 'Excel' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              icon={<FileText size={14} />}
              loading={exportingFormat === 'pdf'}
              disabled={exportMut.isPending}
              onClick={() => handleExport('pdf')}
            >
              {t('methodology.editor.export_pdf', { defaultValue: 'PDF' })}
            </Button>
            {readOnly ? (
              <Button
                variant="primary"
                size="sm"
                icon={<Copy size={14} />}
                loading={duplicateMut.isPending}
                onClick={() => duplicateMut.mutate()}
              >
                {t('methodology.editor.duplicate', { defaultValue: 'Duplicate to edit' })}
              </Button>
            ) : (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={14} />}
                  onClick={() => setConfirmDelete(true)}
                >
                  {t('common.delete', { defaultValue: 'Delete' })}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Save size={14} />}
                  disabled={!dirty}
                  loading={saveMut.isPending}
                  onClick={() => saveMut.mutate()}
                >
                  {dirty
                    ? t('methodology.editor.save', { defaultValue: 'Save changes' })
                    : t('methodology.editor.saved_label', { defaultValue: 'Saved' })}
                </Button>
              </>
            )}
          </div>
        }
      />

      {/* ── Read-only banner ────────────────────────────────────────────── */}
      {readOnly && (
        <div className="flex items-start gap-2.5 rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-4 py-3">
          <Lock size={16} className="mt-0.5 shrink-0 text-oe-blue" />
          <div className="min-w-0 text-sm">
            <p className="font-medium text-content-primary">
              {t('methodology.editor.readonly_title', {
                defaultValue: 'This is a built-in template (read-only)',
              })}
            </p>
            <p className="mt-0.5 text-content-secondary">
              {t('methodology.editor.readonly_body', {
                defaultValue:
                  'Built-in templates are shared platform references and cannot be changed. Duplicate it to make an editable copy for this project.',
              })}
            </p>
          </div>
        </div>
      )}

      {/* ── Identity card ───────────────────────────────────────────────── */}
      <Card padding="lg">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="lg:col-span-2">
            <Input
              label={t('methodology.editor.name', { defaultValue: 'Name' })}
              value={draft.name}
              disabled={readOnly}
              onChange={(e) => updateDraft({ name: e.target.value })}
              maxLength={255}
            />
          </div>
          <Input
            label={t('methodology.editor.currency', { defaultValue: 'Currency' })}
            value={draft.currency}
            disabled={readOnly}
            onChange={(e) => updateDraft({ currency: e.target.value.toUpperCase() })}
            placeholder={t('methodology.editor.currency_placeholder', { defaultValue: 'e.g. EUR' })}
            maxLength={8}
          />
          <Input
            label={t('methodology.editor.decimals', { defaultValue: 'Decimals' })}
            type="number"
            min={0}
            max={8}
            value={String(draft.decimals)}
            disabled={readOnly}
            onChange={(e) => updateDraft({ decimals: Math.max(0, Math.min(8, Number(e.target.value) || 0)) })}
          />
          <div className="sm:col-span-2 lg:col-span-4">
            <Input
              label={t('methodology.editor.description', { defaultValue: 'Description' })}
              value={draft.description}
              disabled={readOnly}
              onChange={(e) => updateDraft({ description: e.target.value })}
              placeholder={t('methodology.editor.description_placeholder', {
                defaultValue: 'What this methodology is for',
              })}
              maxLength={5000}
            />
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {methodology.country_code && (
            <Badge variant="neutral" size="sm">{methodology.country_code}</Badge>
          )}
          {methodology.industry && (
            <Badge variant="neutral" size="sm">{methodology.industry}</Badge>
          )}
          <Badge variant="neutral" size="sm">
            <span className="font-mono">{methodology.slug}</span>
          </Badge>
        </div>
      </Card>

      {/* ── Tabs ────────────────────────────────────────────────────────── */}
      <TabBar
        tabs={tabs}
        activeId={tab}
        onChange={setTab}
        ariaLabel={t('methodology.editor.tabs_label', { defaultValue: 'Methodology sections' })}
        idPrefix="methodology-editor"
        variant="underline"
      />

      <div role="tabpanel" id={TAB_IDS.panelId(tab)} aria-labelledby={TAB_IDS.tabId(tab)}>
        {tab === 'cascade' && (
          <div className="space-y-4">
            <ProjectVatNotice methodology={methodology} />
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
              <CascadeSection
                readOnly={readOnly}
                baseMapping={draft.baseMapping}
                composites={draft.composites}
                steps={draft.steps}
                onChangeBaseMapping={(baseMapping) => updateDraft({ baseMapping })}
                onChangeComposites={(composites) => updateDraft({ composites })}
                onChangeSteps={(steps) => updateDraft({ steps })}
              />
              <div className="xl:sticky xl:top-4 self-start">
                <Card padding="lg">
                  <h3 className="text-sm font-semibold text-content-primary">
                    {t('methodology.preview.title', { defaultValue: 'Live preview' })}
                  </h3>
                  <p className="mt-0.5 text-xs text-content-secondary">
                    {t('methodology.preview.subtitle', {
                      defaultValue: 'How the current cascade marks up a sample of direct costs.',
                    })}
                  </p>
                  <div className="mt-3">
                    <CascadePreview
                      projectId={activeProjectId}
                      methodologySlug={methodology.slug}
                      baseMapping={draft.baseMapping}
                      composites={draft.composites}
                      steps={draft.steps}
                      decimals={draft.decimals}
                      currency={draft.currency}
                      dirty={dirty}
                    />
                  </div>
                </Card>
              </div>
            </div>
          </div>
        )}

        {tab === 'dimensions' && (
          <DimensionsSection
            projectId={activeProjectId}
            methodologySlug={methodology.slug}
            readOnly={readOnly}
          />
        )}

        {tab === 'funding' && (
          <FundingSourcesSection projectId={activeProjectId} readOnly={readOnly} />
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false);
          deleteMut.mutate();
        }}
        title={t('methodology.editor.delete_title', { defaultValue: 'Delete this methodology?' })}
        message={t('methodology.editor.delete_message', {
          defaultValue:
            'This removes the methodology and its dimensions from the project. If it was the active methodology, the project falls back to the International default. This cannot be undone.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        variant="danger"
      />
    </div>
  );
}
