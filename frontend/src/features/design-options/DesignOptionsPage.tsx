// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DesignOptionsPage - compare competing design options for a project side by
 * side. A design option is a whole alternative, not a model: it points at the
 * model that describes it, the estimate that prices it, the programme that
 * dates it and the carbon inventory that weighs it, so a concrete frame can be
 * weighed against a steel frame on what it costs, when it finishes and what it
 * emits.
 *
 * Everything an option references is picked from what the project already
 * holds. The model comes from the federated "open from project files" dialog,
 * which lists the documents area AND the BIM hub's own store; the estimate,
 * programme and inventory come from the project's own registers. There is no
 * uploader here: the BIM hub owns CAD import, and a second one in this module
 * would leave the project holding the same drawing twice.
 *
 * The pricing flow stays explicit and human-confirmed: give an option a model,
 * generate a dry-run preview of the matched priced BOQ, review it, then apply.
 * Nothing is written to a bill of quantities without that confirmation. Linking
 * an existing estimate skips that flow entirely - the bill is already someone's
 * confirmed work, so it is totalled, not regenerated.
 *
 * Money, quantity and ratio fields arrive as Decimal-as-string from the API and
 * are parsed to numbers only for display formatting.
 */

import {
  useState,
  useEffect,
  useRef,
  useMemo,
  useCallback,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Layers,
  GitCompareArrows,
  Plus,
  Trash2,
  Sparkles,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  CalendarClock,
  Crown,
  FileStack,
  FolderOpen,
  Leaf,
  Link2,
  Download,
  RefreshCw,
  Boxes,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  ConfirmDialog,
  SkeletonTable,
  DismissibleInfo,
  ProjectFilePicker,
  WideModal,
  WideModalSection,
  WideModalField,
  PageHeader,
  InfoHint,
  type PickedProjectFile,
} from '@/shared/ui';
import { DESIGN_OPTION_SOURCE_FORMATS } from '@/shared/lib/projectFileFormats';
import type { FileKind } from '@/features/file-manager/types';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  listOptionSets,
  getOptionSet,
  createOptionSet,
  deleteOptionSet,
  createOption,
  deleteOption,
  setBaseline,
  linkBimModel,
  linkSourceDocument,
  linkOptionReferences,
  listProjectBoqs,
  listProjectCarbonInventories,
  listProjectSchedules,
  generateOption,
  getComparison,
  downloadComparisonXlsx,
  type DesignOptionSet,
  type DesignOption,
  type DesignOptionStatus,
  type DesignOptionGenerateResponse,
} from './api';
import { DesignOptionComparisonTable } from './DesignOptionComparisonTable';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { formatCurrency } from '@/shared/lib/money';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/* ── Helpers ───────────────────────────────────────────────────────────── */

const TRANSIENT_STATES: DesignOptionStatus[] = ['converting', 'boq_generating'];

function isTransient(status: DesignOptionStatus): boolean {
  return TRANSIENT_STATES.includes(status);
}

function num(v: string | number | null | undefined): number {
  if (v == null) return 0;
  const n = typeof v === 'number' ? v : parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Money, written the way its currency is written.
 *
 * This was a byte-for-byte twin of the formatter in
 * `DesignOptionComparisonTable`, down to the `toFixed(0)` in the catch, and it
 * renders the same fields of the same options - direct cost, grand total, cost
 * per area. Both pinned zero decimals against whatever currency they were
 * handed, so a euro set never showed cents and a dinar set lost a thousandth.
 *
 * Fixing one copy and leaving the other is how a defect comes back: the page
 * and the table would have disagreed about the same number, which is worse
 * than both being wrong in the same way. The shared resolver reads the digit
 * count from CLDR, and it is now the only thing either of them asks.
 */
function formatMoney(amount: string | number, currency?: string): string {
  return formatCurrency(num(amount), currency);
}

/** A whole-day count in the reader's locale. Days are never fractional here. */
function formatDays(value: string | number): string {
  return new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 0 }).format(num(value));
}

/** A non-money quantity (kgCO2e today) in the reader's locale. */
function formatQuantity(value: string | number): string {
  return new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 0 }).format(num(value));
}

const STATUS_VARIANT: Record<DesignOptionStatus, BadgeVariant> = {
  draft: 'neutral',
  model_attached: 'blue',
  converting: 'warning',
  boq_generating: 'warning',
  priced: 'success',
  failed: 'error',
};

function OptionStatusChip({ status }: { status: DesignOptionStatus }) {
  const { t } = useTranslation();
  const label: Record<DesignOptionStatus, string> = {
    draft: t('designOptions.status.draft', { defaultValue: 'Draft' }),
    model_attached: t('designOptions.status.modelAttached', { defaultValue: 'Model attached' }),
    converting: t('designOptions.status.converting', { defaultValue: 'Converting' }),
    boq_generating: t('designOptions.status.boqGenerating', { defaultValue: 'Generating' }),
    priced: t('designOptions.status.priced', { defaultValue: 'Priced' }),
    failed: t('designOptions.status.failed', { defaultValue: 'Failed' }),
  };
  return (
    <Badge variant={STATUS_VARIANT[status]} size="sm" dot>
      {label[status]}
    </Badge>
  );
}

/* ── Option sources ────────────────────────────────────────────────────── */

/**
 * The BIM hub keeps converted models in a store of its own, so "project files"
 * has to mean both stores here or the dialog cannot offer a model the project
 * already has. Documents are added by the picker itself and must not be
 * repeated.
 *
 * OC-07: the picker now includes ``document`` so PDF drawings can serve as
 * the design basis when no 3D model exists yet. ``dwg_drawing`` remains
 * excluded because the attach-model endpoint does not accept drawing ids.
 */
const DESIGN_OPTION_PICKER_KINDS: readonly FileKind[] = ['bim_model', 'document'];

/** One row of the sources panel: what the option points at, if anything. */
function SourceRow({
  icon,
  label,
  value,
  linked,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  linked: boolean;
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={linked ? 'text-oe-blue' : 'text-content-quaternary'}>{icon}</span>
      <span className="shrink-0 text-content-tertiary">{label}</span>
      <span
        className={`ml-auto min-w-0 truncate text-right ${
          linked ? 'font-medium text-content-primary' : 'text-content-quaternary'
        }`}
      >
        {value}
      </span>
    </div>
  );
}

/**
 * What this option is made of, and the two ways to change it.
 *
 * A design option is a whole alternative, so this panel is the option's whole
 * reach: the model, the estimate that prices it, the programme that dates it
 * and the inventory that weighs it. Every one of them is PICKED from what the
 * project already holds. There is no upload here on purpose - the BIM hub owns
 * CAD import, and a second uploader in this module would leave the project
 * holding two copies of the same drawing under two different names.
 */
function OptionSources({
  option,
  projectId,
  onChanged,
}: {
  option: DesignOption;
  projectId: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [pickingFileId, setPickingFileId] = useState<string | null>(null);

  // Named so the panel can show WHICH estimate is linked rather than an id.
  // Shared cache key with the link modal, so opening one does not refetch for
  // the other.
  const boqsQuery = useQuery({
    queryKey: ['design-options', 'linkable-boqs', projectId],
    queryFn: () => listProjectBoqs(projectId),
    enabled: Boolean(projectId) && Boolean(option.boq_id),
    staleTime: 30_000,
  });
  const linkedBoqName = useMemo(
    () => (boqsQuery.data ?? []).find((b) => b.id === option.boq_id)?.name ?? '',
    [boqsQuery.data, option.boq_id],
  );

  const attach = useMutation({
    mutationFn: (file: PickedProjectFile) =>
      // The row's own store decides which reference it becomes. A model is
      // already converted; a document still has to go through the BIM hub.
      file.kind === 'bim_model'
        ? linkBimModel(option.id, file.id)
        : linkSourceDocument(option.id, file.id),
    onSuccess: () => {
      setShowFilePicker(false);
      onChanged();
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
    onSettled: () => setPickingFileId(null),
  });

  // Says WHETHER a model is there, not how big it is. The element count already
  // has two homes on this screen (the ready-to-price line below and the
  // comparison table), and a third would be the only one forced to carry a
  // counted plural into 29 languages for no new information.
  const modelValue = option.bim_model_id
    ? t('designOptions.source.modelLinked', { defaultValue: 'Linked' })
    : option.source_document_id
      ? t('designOptions.source.awaitingConversion', { defaultValue: 'Awaiting conversion' })
      : t('designOptions.source.notSet', { defaultValue: 'Not set' });

  return (
    <div className="space-y-2.5 rounded-lg border border-border-light bg-surface-secondary/30 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
        {t('designOptions.source.title', { defaultValue: 'What this option is made of' })}
      </p>

      <SourceRow
        icon={<Boxes size={13} />}
        label={t('designOptions.source.model', { defaultValue: 'Model' })}
        value={modelValue}
        linked={Boolean(option.bim_model_id || option.source_document_id)}
      />
      <SourceRow
        icon={<FileStack size={13} />}
        label={t('designOptions.source.estimate', { defaultValue: 'Estimate' })}
        value={
          option.boq_id
            ? linkedBoqName ||
              (option.boq_source === 'linked'
                ? t('designOptions.source.linkedEstimate', { defaultValue: 'Linked estimate' })
                : t('designOptions.source.generatedEstimate', { defaultValue: 'Generated here' }))
            : t('designOptions.source.notSet', { defaultValue: 'Not set' })
        }
        linked={Boolean(option.boq_id)}
      />
      <SourceRow
        icon={<CalendarClock size={13} />}
        label={t('designOptions.source.programme', { defaultValue: 'Programme' })}
        value={
          option.schedule_id
            ? t('designOptions.source.programmeValue', {
                defaultValue: '{{days}} days, ends {{date}}',
                days: formatDays(option.duration_days),
                date: option.finish_date || '-',
              })
            : t('designOptions.source.notSet', { defaultValue: 'Not set' })
        }
        linked={Boolean(option.schedule_id)}
      />
      <SourceRow
        icon={<Leaf size={13} />}
        label={t('designOptions.source.carbon', { defaultValue: 'Carbon' })}
        value={
          option.carbon_inventory_id
            ? t('designOptions.source.carbonValue', {
                defaultValue: '{{amount}} kgCO2e',
                amount: formatQuantity(option.embodied_carbon_kg),
              })
            : t('designOptions.source.notSet', { defaultValue: 'Not set' })
        }
        linked={Boolean(option.carbon_inventory_id)}
      />

      <div className="flex flex-wrap gap-2 pt-1">
        <Button
          variant="secondary"
          size="sm"
          icon={<FolderOpen size={13} />}
          onClick={() => setShowFilePicker(true)}
          disabled={!projectId}
        >
          {t('project_files.open_from_project', { defaultValue: 'Open from project files' })}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={<Link2 size={13} />}
          onClick={() => setShowLinkModal(true)}
          disabled={!projectId}
        >
          {t('designOptions.source.linkProjectData', { defaultValue: 'Link project data' })}
        </Button>
      </div>

      {/* Says where a new model comes from, rather than growing a second
          uploader beside the one the BIM hub already owns. */}
      <p className="text-[11px] leading-relaxed text-content-quaternary">
        {t('designOptions.source.importHint', {
          defaultValue: 'A model that is not in the project yet is imported in the BIM hub.',
        })}{' '}
        <Link to="/bim" className="font-medium text-oe-blue hover:underline">
          {t('designOptions.source.goToBim', { defaultValue: 'Go to BIM hub' })}
        </Link>
      </p>

      <ProjectFilePicker
        open={showFilePicker}
        onClose={() => setShowFilePicker(false)}
        projectId={projectId}
        accepted={DESIGN_OPTION_SOURCE_FORMATS}
        moduleKinds={DESIGN_OPTION_PICKER_KINDS}
        title={t('designOptions.source.pickModelTitle', { defaultValue: 'Choose a model for this option' })}
        busyId={pickingFileId}
        onPick={(file) => {
          setPickingFileId(file.id);
          attach.mutate(file);
        }}
      />

      {showLinkModal && (
        <LinkProjectDataModal
          option={option}
          projectId={projectId}
          onClose={() => setShowLinkModal(false)}
          onLinked={onChanged}
        />
      )}
    </div>
  );
}

/**
 * Pick the estimate, programme and carbon inventory this option stands for.
 *
 * These are records, not files, so they are not the file picker's business:
 * each list is the project's own register, read straight from the module that
 * owns it. "Not linked" is a real choice in every list, because an option that
 * should stop claiming a programme has to be able to say so.
 */
function LinkProjectDataModal({
  option,
  projectId,
  onClose,
  onLinked,
}: {
  option: DesignOption;
  projectId: string;
  onClose: () => void;
  onLinked: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [boqId, setBoqId] = useState(option.boq_id ?? '');
  const [scheduleId, setScheduleId] = useState(option.schedule_id ?? '');
  const [inventoryId, setInventoryId] = useState(option.carbon_inventory_id ?? '');

  const boqsQuery = useQuery({
    queryKey: ['design-options', 'linkable-boqs', projectId],
    queryFn: () => listProjectBoqs(projectId),
    staleTime: 30_000,
  });
  const schedulesQuery = useQuery({
    queryKey: ['design-options', 'linkable-schedules', projectId],
    queryFn: () => listProjectSchedules(projectId),
    staleTime: 30_000,
  });
  const inventoriesQuery = useQuery({
    queryKey: ['design-options', 'linkable-inventories', projectId],
    queryFn: () => listProjectCarbonInventories(projectId),
    staleTime: 30_000,
  });

  const save = useMutation({
    mutationFn: () =>
      // All three references go every time, including the ones the user left
      // alone. The figures an option carries are read at link time, so a
      // schedule that has since slipped or a bill that has been re-rated only
      // catches up when its reference is sent again - saving the same three
      // selections is how you refresh them. Sending only what moved would make
      // an unchanged select unrefreshable short of unlinking it first.
      linkOptionReferences(option.id, {
        boq_id: boqId || null,
        schedule_id: scheduleId || null,
        carbon_inventory_id: inventoryId || null,
      }),
    onSuccess: () => {
      onLinked();
      onClose();
      addToast({
        type: 'success',
        title: t('designOptions.toast.linked', { defaultValue: 'Option updated' }),
      });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const selectCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
  const notLinked = t('designOptions.source.notLinked', { defaultValue: 'Not linked' });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('designOptions.source.linkProjectData', { defaultValue: 'Link project data' })}
      subtitle={t('designOptions.source.linkSubtitle', {
        defaultValue:
          'Point this option at what the project already holds. Linking an estimate prices the option straight away, with no model needed.',
      })}
      size="md"
      busy={save.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('designOptions.source.estimate', { defaultValue: 'Estimate' })}
          hint={t('designOptions.source.estimateHint', {
            defaultValue: 'Any bill of quantities in this project, including one built by hand.',
          })}
        >
          <select className={selectCls} value={boqId} onChange={(e) => setBoqId(e.target.value)}>
            <option value="">{notLinked}</option>
            {(boqsQuery.data ?? []).map((boq) => (
              <option key={boq.id} value={boq.id}>
                {boq.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('designOptions.source.programme', { defaultValue: 'Programme' })}
          hint={t('designOptions.source.programmeHint', {
            defaultValue: 'The duration and finish date come from the schedule activities.',
          })}
        >
          <select className={selectCls} value={scheduleId} onChange={(e) => setScheduleId(e.target.value)}>
            <option value="">{notLinked}</option>
            {(schedulesQuery.data ?? []).map((schedule) => (
              <option key={schedule.id} value={schedule.id}>
                {schedule.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('designOptions.source.carbon', { defaultValue: 'Carbon' })}
          hint={t('designOptions.source.carbonHint', {
            defaultValue: 'Embodied carbon A1-A5, the part a choice of scheme actually commits.',
          })}
        >
          <select className={selectCls} value={inventoryId} onChange={(e) => setInventoryId(e.target.value)}>
            <option value="">{notLinked}</option>
            {(inventoriesQuery.data ?? []).map((inventory) => (
              <option key={inventory.id} value={inventory.id}>
                {inventory.name}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Generate dry-run preview ──────────────────────────────────────────── */

function PreviewStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="text-base font-semibold tabular-nums text-content-primary">{value}</p>
    </div>
  );
}

function GeneratePreviewModal({
  option,
  onApplied,
  onClose,
}: {
  option: DesignOption;
  onApplied: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const started = useRef(false);
  const [preview, setPreview] = useState<DesignOptionGenerateResponse | null>(null);

  const dryRun = useMutation({
    mutationFn: () => generateOption(option.id, true),
    onSuccess: (res) => setPreview(res),
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  const apply = useMutation({
    mutationFn: () => generateOption(option.id, false),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('designOptions.toast.generated', {
          defaultValue: 'Priced BOQ generated for this option',
        }),
      });
      onApplied();
      onClose();
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  // Run the preview exactly once when the modal opens. The ref guard keeps
  // React StrictMode's double-mount from firing two preview requests.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    dryRun.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('designOptions.previewTitle', { defaultValue: 'Generate priced estimate' })}
      subtitle={t('designOptions.previewSubtitle', {
        defaultValue:
          'Preview the matched, priced bill of quantities before it is written to this option. Nothing is applied until you confirm.',
      })}
      size="lg"
      busy={apply.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={apply.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            icon={<Sparkles size={14} />}
            loading={apply.isPending}
            disabled={!preview || dryRun.isPending}
            onClick={() => apply.mutate()}
          >
            {t('designOptions.applyGenerate', { defaultValue: 'Apply and price' })}
          </Button>
        </>
      }
    >
      {dryRun.isPending ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-content-secondary">
          <Loader2 size={18} className="animate-spin text-oe-blue" />
          {t('designOptions.previewLoading', {
            defaultValue: 'Matching model elements to cost items...',
          })}
        </div>
      ) : preview ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <PreviewStat
              label={t('designOptions.elements', { defaultValue: 'Elements' })}
              value={preview.element_count}
            />
            <PreviewStat
              label={t('designOptions.matched', { defaultValue: 'Matched' })}
              value={preview.groups_confirmed}
            />
            <PreviewStat
              label={t('designOptions.unmatched', { defaultValue: 'Unmatched' })}
              value={Math.max(0, preview.groups_total - preview.groups_confirmed)}
            />
            <PreviewStat
              label={t('designOptions.positions', { defaultValue: 'Positions' })}
              value={preview.position_count}
            />
          </div>

          <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-content-secondary">
                {t('designOptions.estDirectCost', { defaultValue: 'Estimated direct cost' })}
              </span>
              <span className="text-lg font-semibold tabular-nums text-content-primary">
                {formatMoney(preview.direct_cost, preview.currency)}
              </span>
            </div>
            {num(preview.grand_total) > 0 && (
              <div className="mt-1 flex items-center justify-between">
                <span className="text-sm text-content-secondary">
                  {t('designOptions.estGrandTotal', { defaultValue: 'Estimated grand total' })}
                </span>
                <span className="text-sm font-medium tabular-nums text-content-primary">
                  {formatMoney(preview.grand_total, preview.currency)}
                </span>
              </div>
            )}
          </div>

          {preview.groups_total - preview.groups_confirmed > 0 && (
            <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
              <span>
                {t('designOptions.unmatchedNote', {
                  defaultValue:
                    '{{count}} element(s) could not be matched to a cost item and are left unpriced. You can refine them in the option BOQ after applying.',
                  count: Math.max(0, preview.groups_total - preview.groups_confirmed),
                })}
              </span>
            </div>
          )}

          {preview.warnings.length > 0 && (
            <ul className="space-y-1 text-xs text-content-secondary">
              {preview.warnings.map((w, i) => (
                <li key={i} className="flex gap-1.5">
                  <span aria-hidden="true">-</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          )}

          <p className="text-xs text-content-tertiary">
            {t('designOptions.humanConfirmNote', {
              defaultValue:
                'These matches are AI-assisted suggestions. Review the numbers above, then apply to write the priced BOQ for this option.',
            })}
          </p>
        </div>
      ) : (
        <div className="py-10 text-center text-sm text-content-tertiary">
          {t('designOptions.previewFailed', {
            defaultValue: 'Could not build a preview. Please close and try again.',
          })}
        </div>
      )}
    </WideModal>
  );
}

/* ── Option card ───────────────────────────────────────────────────────── */

function OptionCard({
  option,
  baselineOptionId,
  onChanged,
}: {
  option: DesignOption;
  baselineOptionId: string | null;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [showPreview, setShowPreview] = useState(false);

  const isBaseline = option.id === baselineOptionId;
  const isPriced = option.status === 'priced';

  const baselineMutation = useMutation({
    mutationFn: () => setBaseline(option.set_id, option.id),
    onSuccess: onChanged,
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteOption(option.id),
    onSuccess: onChanged,
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  return (
    <Card padding="none" className={isBaseline ? 'ring-2 ring-oe-blue/40 border-oe-blue/40' : ''}>
      <div className="flex flex-col gap-3 p-4">
        {/* Header */}
        <div className="flex items-start gap-2">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
            <Boxes size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <h3 className="truncate text-sm font-semibold text-content-primary">{option.name}</h3>
              {isBaseline && (
                <Crown size={13} className="shrink-0 text-oe-blue" aria-label={t('designOptions.baseline', { defaultValue: 'Baseline' })} />
              )}
            </div>
            <div className="mt-1">
              <OptionStatusChip status={option.status} />
            </div>
          </div>
          <button
            type="button"
            aria-label={t('designOptions.removeOption', { defaultValue: 'Remove option' })}
            title={t('designOptions.removeOption', { defaultValue: 'Remove option' })}
            className="shrink-0 rounded-md p-1.5 text-content-tertiary transition-colors hover:bg-semantic-error-bg/40 hover:text-semantic-error disabled:opacity-50"
            disabled={removeMutation.isPending}
            onClick={async () => {
              const ok = await confirm({
                title: t('designOptions.removeOption', { defaultValue: 'Remove option' }),
                message: t('designOptions.removeOptionConfirm', {
                  defaultValue: 'Remove "{{name}}" and its generated BOQ from this comparison?',
                  name: option.name,
                }),
                variant: 'warning',
              });
              if (ok) removeMutation.mutate();
            }}
          >
            <Trash2 size={15} />
          </button>
        </div>

        {/* What the option references. Always shown, never only in the empty
            state: an option that is already priced still has to be able to
            gain a programme or swap the estimate behind it. */}
        <OptionSources option={option} projectId={option.project_id} onChanged={onChanged} />

        {/* Body by status */}
        {option.status === 'converting' && (
          <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-4 text-sm text-content-secondary">
            <Loader2 size={16} className="animate-spin text-oe-blue" />
            {t('designOptions.convertingBody', { defaultValue: 'Converting the model...' })}
          </div>
        )}

        {option.status === 'boq_generating' && (
          <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-4 text-sm text-content-secondary">
            <Loader2 size={16} className="animate-spin text-oe-blue" />
            {t('designOptions.generatingBody', { defaultValue: 'Generating the priced estimate...' })}
          </div>
        )}

        {option.status === 'model_attached' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/30 px-3 py-2 text-xs text-content-secondary">
              <CheckCircle2 size={14} className="text-semantic-success" />
              {t('designOptions.modelReady', {
                defaultValue: '{{count}} element(s) ready to price.',
                count: option.element_count,
              })}
            </div>
            {/* Attaching a model to an option already priced from a linked bill
                is an ordinary thing to do, and it puts the card back in this
                state. Generating from here would write matched positions into
                a bill this module does not own, which the server refuses, so
                the card withholds the action and says why. */}
            {option.boq_source === 'linked' ? (
              <p className="text-[11px] leading-relaxed text-content-tertiary">
                {t('designOptions.pricedFromLinkedEstimate', {
                  defaultValue:
                    'Priced from an estimate the project already held. Edit it in the bill editor and the figures follow.',
                })}
              </p>
            ) : (
              <Button
                variant="primary"
                size="sm"
                icon={<Sparkles size={14} />}
                className="w-full"
                onClick={() => setShowPreview(true)}
              >
                {t('designOptions.generate', { defaultValue: 'Generate estimate' })}
              </Button>
            )}
          </div>
        )}

        {option.status === 'failed' && (
          <div className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/30 px-3 py-2 text-xs text-semantic-error">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span>{option.error || t('designOptions.failedGeneric', { defaultValue: 'Processing failed.' })}</span>
          </div>
        )}

        {isPriced && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-border-light bg-surface-secondary/30 px-3 py-2">
                <p className="text-xs text-content-tertiary">
                  {t('designOptions.grandTotal', { defaultValue: 'Grand total' })}
                </p>
                <p className="text-base font-semibold tabular-nums text-content-primary">
                  {formatMoney(option.grand_total, option.currency)}
                </p>
              </div>
              <div className="rounded-lg border border-border-light bg-surface-secondary/30 px-3 py-2">
                <p className="text-xs text-content-tertiary">
                  {t('designOptions.costPerM2', { defaultValue: 'Cost per m2' })}
                </p>
                <p className="text-base font-semibold tabular-nums text-content-primary">
                  {num(option.cost_per_m2) > 0 ? formatMoney(option.cost_per_m2, option.currency) : '-'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs text-content-tertiary">
              <span className="inline-flex items-center gap-1">
                <Boxes size={12} /> {option.element_count}
              </span>
              <span className="inline-flex items-center gap-1">
                <FileStack size={12} /> {option.position_count}
              </span>
            </div>
            {/* Regenerating writes into the option's bill. When that bill was
                linked from the project it belongs to whoever built it, so the
                action is withheld rather than offered and then refused - and
                the card says why instead of leaving a gap. */}
            {option.boq_source === 'linked' ? (
              <p className="text-[11px] leading-relaxed text-content-tertiary">
                {t('designOptions.pricedFromLinkedEstimate', {
                  defaultValue:
                    'Priced from an estimate the project already held. Edit it in the bill editor and the figures follow.',
                })}
              </p>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw size={13} />}
                disabled={!option.bim_model_id}
                onClick={() => setShowPreview(true)}
              >
                {t('designOptions.regenerate', { defaultValue: 'Regenerate' })}
              </Button>
            )}
          </div>
        )}

        {/* Baseline selector */}
        <div className="mt-1 border-t border-border-light pt-3">
          {isBaseline ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-oe-blue-text">
              <Crown size={13} /> {t('designOptions.isBaseline', { defaultValue: 'Comparison baseline' })}
            </span>
          ) : (
            <button
              type="button"
              disabled={baselineMutation.isPending}
              onClick={() => baselineMutation.mutate()}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-content-secondary transition-colors hover:text-oe-blue disabled:opacity-50"
            >
              <Crown size={13} /> {t('designOptions.setBaseline', { defaultValue: 'Set as baseline' })}
            </button>
          )}
        </div>
      </div>

      {showPreview && (
        <GeneratePreviewModal
          option={option}
          onApplied={onChanged}
          onClose={() => setShowPreview(false)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}

/* ── Create set / add option modals ────────────────────────────────────── */

function CreateSetModal({
  projectId,
  onClose,
  onCreated,
}: {
  projectId: string;
  onClose: () => void;
  onCreated: (set: DesignOptionSet) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');

  const create = useMutation({
    mutationFn: () => createOptionSet({ project_id: projectId, name: name.trim() }),
    onSuccess: (set) => {
      onCreated(set);
      onClose();
      addToast({ type: 'success', title: t('designOptions.toast.setCreated', { defaultValue: 'Option set created' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('designOptions.newSet', { defaultValue: 'New option set' })}
      subtitle={t('designOptions.newSetSubtitle', {
        defaultValue: 'Group the design options you want to weigh against each other.',
      })}
      size="md"
      busy={create.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim()}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            {t('designOptions.createSet', { defaultValue: 'Create set' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField label={t('designOptions.setName', { defaultValue: 'Set name' })} required>
          <input
            type="text"
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && name.trim()) create.mutate();
            }}
            placeholder={t('designOptions.setNamePlaceholder', {
              defaultValue: 'e.g. Superstructure - frame options',
            })}
            className={fieldCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function AddOptionModal({
  setId,
  onClose,
  onCreated,
}: {
  setId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');

  const create = useMutation({
    mutationFn: () => createOption(setId, { name: name.trim() }),
    onSuccess: () => {
      onCreated();
      onClose();
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('designOptions.newOption', { defaultValue: 'Add option' })}
      size="md"
      busy={create.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim()}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            {t('designOptions.addOption', { defaultValue: 'Add option' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField label={t('designOptions.optionName', { defaultValue: 'Option name' })} required>
          <input
            type="text"
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && name.trim()) create.mutate();
            }}
            placeholder={t('designOptions.optionNamePlaceholder', {
              defaultValue: 'e.g. Reinforced concrete frame',
            })}
            className={fieldCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Selected-set detail ───────────────────────────────────────────────── */

function OptionSetDetail({ setId }: { setId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showAddOption, setShowAddOption] = useState(false);

  const setQuery = useQuery({
    queryKey: ['design-options', 'set', setId],
    queryFn: () => getOptionSet(setId),
    // Poll while any option is converting or generating, so the cards advance
    // from "Converting" to "Priced" without a manual refresh.
    refetchInterval: (query) => {
      const data = query.state.data as DesignOptionSet | undefined;
      const opts = data?.options ?? [];
      return opts.some((o) => isTransient(o.status)) ? 4000 : false;
    },
  });

  const set = setQuery.data;
  const options = useMemo(
    () => [...(set?.options ?? [])].sort((a, b) => a.sort_order - b.sort_order),
    [set],
  );
  const pricedCount = options.filter((o) => o.status === 'priced').length;
  const canCompare = pricedCount >= 2;

  const comparisonQuery = useQuery({
    queryKey: ['design-options', 'comparison', setId],
    queryFn: () => getComparison(setId),
    enabled: canCompare,
  });

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['design-options', 'set', setId] });
    queryClient.invalidateQueries({ queryKey: ['design-options', 'comparison', setId] });
  }, [queryClient, setId]);

  const handleExport = useCallback(async () => {
    if (!set) return;
    const safe = set.name.replace(/[^a-z0-9_-]+/gi, '_') || 'design-options';
    try {
      await downloadComparisonXlsx(setId, `${safe}-comparison.xlsx`);
    } catch (error) {
      addToast({
        type: 'error',
        title: t('designOptions.exportFailed', { defaultValue: 'Export failed' }),
        message: error instanceof Error ? error.message : undefined,
      });
    }
  }, [set, setId, addToast, t]);

  if (setQuery.isLoading) {
    return <SkeletonTable rows={3} columns={3} />;
  }
  if (setQuery.isError || !set) {
    return (
      <Card className="py-10">
        <EmptyState
          icon={<AlertTriangle size={26} strokeWidth={1.5} />}
          title={t('common.error', { defaultValue: 'Error' })}
          description={t('designOptions.setLoadError', {
            defaultValue: 'Could not load this option set. Please try again.',
          })}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* Options grid */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('designOptions.options', { defaultValue: 'Options' })}
          </h2>
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setShowAddOption(true)}
          >
            {t('designOptions.addOption', { defaultValue: 'Add option' })}
          </Button>
        </div>

        {options.length === 0 ? (
          <EmptyState
            icon={<Layers size={26} strokeWidth={1.5} />}
            title={t('designOptions.noOptions', { defaultValue: 'No options yet' })}
            description={t('designOptions.noOptionsDesc', {
              defaultValue:
                'Add two or more options, then point each one at the model, estimate, programme or carbon inventory the project already holds.',
            })}
            action={{
              label: t('designOptions.addOption', { defaultValue: 'Add option' }),
              onClick: () => setShowAddOption(true),
            }}
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {options.map((option) => (
              <OptionCard
                key={option.id}
                option={option}
                baselineOptionId={set.baseline_option_id}
                onChanged={invalidate}
              />
            ))}
          </div>
        )}
      </div>

      {/* Comparison */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <GitCompareArrows size={16} className="text-oe-blue" />
            {t('designOptions.comparison', { defaultValue: 'Comparison' })}
            <InfoHint
              text={t('designOptions.comparisonHelp', {
                defaultValue:
                  'Every option is priced into its own bill of quantities and rebased to the set currency, then compared against the baseline on total cost, by-trade quantities and completeness.',
              })}
            />
          </h2>
          {canCompare && (
            <Button variant="ghost" size="sm" icon={<Download size={14} />} onClick={handleExport}>
              {t('designOptions.exportXlsx', { defaultValue: 'Export' })}
            </Button>
          )}
        </div>

        {!canCompare ? (
          <EmptyState
            icon={<GitCompareArrows size={26} strokeWidth={1.5} />}
            title={t('designOptions.compareGateTitle', { defaultValue: 'Price two options to compare' })}
            description={t('designOptions.compareGateDesc', {
              defaultValue:
                'Attach a model or PDF drawing to at least two options and generate their priced estimates. The side-by-side comparison appears here.',
            })}
          />
        ) : comparisonQuery.isLoading ? (
          <SkeletonTable rows={4} columns={Math.max(2, pricedCount)} />
        ) : comparisonQuery.isError || !comparisonQuery.data ? (
          <Card className="py-10">
            <EmptyState
              icon={<AlertTriangle size={26} strokeWidth={1.5} />}
              title={t('common.error', { defaultValue: 'Error' })}
              description={t('designOptions.comparisonLoadError', {
                defaultValue: 'Could not load the comparison. Please try again.',
              })}
            />
          </Card>
        ) : (
          <DesignOptionComparisonTable comparison={comparisonQuery.data} />
        )}
      </div>

      {showAddOption && (
        <AddOptionModal
          setId={setId}
          onClose={() => setShowAddOption(false)}
          onCreated={invalidate}
        />
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────── */

export function DesignOptionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { confirm, ...confirmProps } = useConfirm();
  const addToast = useToastStore((s) => s.addToast);
  const { activeProjectId } = useProjectContextStore();
  const projectId = activeProjectId ?? '';

  const [selectedSetId, setSelectedSetId] = useState('');
  const [showCreateSet, setShowCreateSet] = useState(false);

  const setsQuery = useQuery({
    queryKey: ['design-options', 'sets', projectId],
    queryFn: () => listOptionSets(projectId),
    enabled: !!projectId,
  });
  const sets = setsQuery.data ?? [];

  // Keep a valid selection: default to the first set, and drop a stale id if
  // the selected set was deleted elsewhere.
  useEffect(() => {
    if (sets.length === 0) {
      if (selectedSetId) setSelectedSetId('');
      return;
    }
    if (!selectedSetId || !sets.some((s) => s.id === selectedSetId)) {
      setSelectedSetId(sets[0]!.id);
    }
  }, [sets, selectedSetId]);

  const deleteSetMutation = useMutation({
    mutationFn: (setId: string) => deleteOptionSet(setId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['design-options', 'sets', projectId] });
      addToast({ type: 'success', title: t('designOptions.toast.setDeleted', { defaultValue: 'Option set deleted' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const handleSetCreated = useCallback(
    (set: DesignOptionSet) => {
      queryClient.invalidateQueries({ queryKey: ['design-options', 'sets', projectId] });
      setSelectedSetId(set.id);
    },
    [queryClient, projectId],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('designOptions.title', { defaultValue: 'Design Options' }) }]} />

      <PageHeader
        srTitle={t('designOptions.title', { defaultValue: 'Design Options' })}
        subtitle={t('designOptions.subtitle', {
          defaultValue: 'Compare competing design options for the project on cost, quantity and completeness',
        })}
        actions={
          <span
            title={
              !projectId
                ? t('designOptions.selectProjectFirst', { defaultValue: 'Select a project first' })
                : undefined
            }
          >
            <Button
              variant="primary"
              icon={<Plus size={16} />}
              disabled={!projectId}
              onClick={() => setShowCreateSet(true)}
            >
              {t('designOptions.newSet', { defaultValue: 'New option set' })}
            </Button>
          </span>
        }
      />

      <DismissibleInfo
        storageKey="design-options"
        title={t('designOptions.introTitle', {
          defaultValue: 'Weigh design options side by side',
        })}
        links={[
          { label: t('nav.bim', { defaultValue: 'BIM' }), onClick: () => navigate('/bim') },
          { label: t('nav.boq', { defaultValue: 'BOQ' }), onClick: () => navigate('/boq') },
        ]}
      >
        {t('designOptions.introBody', {
          defaultValue:
            'Create a set, add each design option, and attach its model. Every option is converted and priced into its own bill of quantities, so you can compare a concrete frame against a steel frame (or any A/B choice) on total cost, by-trade quantities and completeness. Pick a baseline and the others are measured against it.',
        })}
      </DismissibleInfo>

      {/* No project selected */}
      {!projectId && (
        <RequiresProject
          emptyHint={t('designOptions.selectProjectDesc', {
            defaultValue: 'Select a project to start comparing design options.',
          })}
        >
          {null}
        </RequiresProject>
      )}

      {/* Sets loading */}
      {projectId && setsQuery.isLoading && <SkeletonTable rows={2} columns={3} />}

      {/* Sets error */}
      {projectId && setsQuery.isError && (
        <Card className="py-10">
          <EmptyState
            icon={<AlertTriangle size={26} strokeWidth={1.5} />}
            title={t('common.error', { defaultValue: 'Error' })}
            description={t('designOptions.setsLoadError', {
              defaultValue: 'Could not load option sets. Please try again.',
            })}
          />
        </Card>
      )}

      {/* No sets */}
      {projectId && !setsQuery.isLoading && !setsQuery.isError && sets.length === 0 && (
        <EmptyState
          icon={<Layers size={28} strokeWidth={1.5} />}
          title={t('designOptions.noSets', { defaultValue: 'No option sets yet' })}
          description={t('designOptions.noSetsDesc', {
            defaultValue: 'Create an option set to compare competing design options for this project.',
          })}
          action={{
            label: t('designOptions.newSet', { defaultValue: 'New option set' }),
            onClick: () => setShowCreateSet(true),
          }}
        />
      )}

      {/* Set picker + detail */}
      {projectId && sets.length > 0 && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            {sets.map((s) => {
              const active = s.id === selectedSetId;
              return (
                <div key={s.id} className="flex items-center">
                  <button
                    type="button"
                    onClick={() => setSelectedSetId(s.id)}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
                      active
                        ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                        : 'border-border bg-surface-primary text-content-secondary hover:border-content-tertiary'
                    }`}
                  >
                    <Layers size={13} />
                    {s.name}
                  </button>
                  {active && (
                    <button
                      type="button"
                      aria-label={t('designOptions.deleteSet', { defaultValue: 'Delete set' })}
                      title={t('designOptions.deleteSet', { defaultValue: 'Delete set' })}
                      className="ml-1 rounded-md p-1 text-content-tertiary transition-colors hover:bg-semantic-error-bg/40 hover:text-semantic-error disabled:opacity-50"
                      disabled={deleteSetMutation.isPending}
                      onClick={async () => {
                        const ok = await confirm({
                          title: t('designOptions.deleteSet', { defaultValue: 'Delete set' }),
                          message: t('designOptions.deleteSetConfirm', {
                            defaultValue: 'Delete "{{name}}" and every option in it? This cannot be undone.',
                            name: s.name,
                          }),
                          variant: 'danger',
                        });
                        if (ok) deleteSetMutation.mutate(s.id);
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {selectedSetId && <OptionSetDetail setId={selectedSetId} />}
        </div>
      )}

      {showCreateSet && projectId && (
        <CreateSetModal
          projectId={projectId}
          onClose={() => setShowCreateSet(false)}
          onCreated={handleSetCreated}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

export default DesignOptionsPage;
