// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Snags block — rendered per-Handover inside PropertyDevPage's
 * HandoversTab. Owns the full snag clickflow:
 *
 *   - Lazy-load snags on expand (avoids fan-out on huge handover lists).
 *   - Add snag modal (category, severity, description, location, cost).
 *   - Status transitions: open → in_progress → fixed / wont_fix.
 *   - Photo upload (validated server-side via magic bytes).
 *   - Promote snag → warranty claim (idempotent backend; UI hides the
 *     button when prerequisites aren't met to never advertise a 4xx).
 *   - Cross-link to auto-bridged punchlist item (the property_dev
 *     event subscriber writes ``linked_punch_item_id`` when the
 *     punchlist module is loaded).
 *   - Delete with confirm.
 *
 * Extracted into its own file because PropertyDevPage.tsx was already
 * ~4700 lines and the snag flow is self-contained.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Trash2,
  Camera,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  ArrowRightCircle,
  Loader2,
} from 'lucide-react';

import { Button, Badge, ConfirmDialog } from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';

import {
  listSnags,
  createSnag,
  updateSnag,
  deleteSnag,
  fixSnag,
  wontFixSnag,
  uploadSnagPhoto,
  createWarrantyClaimFromSnag,
  type Buyer,
  type Handover,
  type SnagCategory,
  type SnagSeverity,
  type SnagStatus,
} from './api';

// English fallbacks for the computed `propdev.snag.status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const SNAG_STATUS_LABELS: Record<string, string> = {
  open: 'Open', in_progress: 'In progress', fixed: 'Fixed', wont_fix: 'Will not fix'
};


const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const SNAG_STATUS_VARIANT: Record<
  SnagStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  open: 'warning',
  in_progress: 'blue',
  fixed: 'success',
  wont_fix: 'neutral',
};

const SNAG_SEVERITY_VARIANT: Record<
  SnagSeverity,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  cosmetic: 'neutral',
  minor: 'neutral',
  major: 'warning',
  safety: 'error',
};

export function SnagsBlock({
  handover,
  buyer,
  plotId,
}: {
  handover: Handover;
  buyer: Buyer | undefined;
  plotId: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [expanded, setExpanded] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const { confirm, ...confirmProps } = useConfirm();

  const snagsQ = useQuery({
    queryKey: ['propdev', 'snags', handover.id],
    queryFn: () => listSnags({ handover_id: handover.id }),
    enabled: expanded,
    staleTime: 30_000,
  });
  const snags = snagsQ.data ?? [];

  const promoteMu = useMutation({
    mutationFn: (snagId: string) => createWarrantyClaimFromSnag(snagId),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.snag.promoted_warranty', {
          defaultValue: 'Warranty claim filed from snag',
        }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'warranty'] });
      qc.invalidateQueries({ queryKey: ['propdev', 'snags', handover.id] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const fixMu = useMutation({
    mutationFn: (id: string) => fixSnag(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'snags', handover.id] });
      qc.invalidateQueries({ queryKey: ['propdev', 'dashboard'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const wontFixMu = useMutation({
    mutationFn: (id: string) => wontFixSnag(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'snags', handover.id] });
      qc.invalidateQueries({ queryKey: ['propdev', 'dashboard'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const updateMu = useMutation({
    mutationFn: ({ id, status }: { id: string; status: SnagStatus }) =>
      updateSnag(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'snags', handover.id] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMu = useMutation({
    mutationFn: (id: string) => deleteSnag(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'snags', handover.id] });
      qc.invalidateQueries({ queryKey: ['propdev', 'dashboard'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const openCount = snags.filter(
    (s) => s.status === 'open' || s.status === 'in_progress',
  ).length;

  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded"
          aria-expanded={expanded}
          data-testid={`snags-toggle-${handover.id}`}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <AlertTriangle size={12} />
          {t('propdev.snags_label', { defaultValue: 'Snags' })}
          {expanded && snagsQ.isLoading ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            <span className="text-content-tertiary">
              ({expanded ? snags.length : handover.snag_count_at_handover || 0}
              {expanded && openCount > 0 ? ` · ${openCount} open` : ''})
            </span>
          )}
        </button>
        <Button
          size="sm"
          variant="ghost"
          icon={<Plus size={12} />}
          onClick={() => {
            setExpanded(true);
            setAddOpen(true);
          }}
          data-testid={`add-snag-${handover.id}`}
        >
          {t('propdev.add_snag', { defaultValue: 'Add snag' })}
        </Button>
      </div>
      {expanded && (
        <>
          {snagsQ.isLoading ? (
            <p className="mt-2 text-xs text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </p>
          ) : snags.length === 0 ? (
            <p className="mt-2 text-xs text-content-tertiary italic">
              {t('propdev.no_snags', {
                defaultValue: 'No snags logged for this handover yet.',
              })}
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {snags.map((s) => (
                <li
                  key={s.id}
                  className="rounded-md border border-border-light bg-surface-secondary/40 px-3 py-2 text-xs"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={SNAG_STATUS_VARIANT[s.status]} dot>
                      {t(`propdev.snag.status_${s.status}`, {
                        defaultValue: SNAG_STATUS_LABELS[s.status] ?? s.status,
                      })}
                    </Badge>
                    <Badge variant={SNAG_SEVERITY_VARIANT[s.severity]}>
                      {t(`propdev.snag.severity_${s.severity}`, {
                        defaultValue: s.severity,
                      })}
                    </Badge>
                    <span className="text-content-tertiary text-[10px]">
                      {t(`propdev.snag.category_${s.category}`, {
                        defaultValue: s.category,
                      })}
                    </span>
                    {s.location_in_plot && (
                      <span className="text-content-tertiary">
                        · {s.location_in_plot}
                      </span>
                    )}
                    {s.photos && s.photos.length > 0 && (
                      <span className="inline-flex items-center gap-0.5 text-content-tertiary">
                        <Camera size={10} />
                        {s.photos.length}
                      </span>
                    )}
                    {s.linked_punch_item_id && (
                      <Link
                        to={`/punchlist?item=${s.linked_punch_item_id}`}
                        className="inline-flex items-center gap-0.5 text-oe-blue hover:underline"
                      >
                        <ArrowRightCircle size={10} />
                        {t('propdev.snag.punch_linked', {
                          defaultValue: 'Punchlist',
                        })}
                      </Link>
                    )}
                  </div>
                  <p className="mt-1 text-content-primary">{s.description}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {s.status === 'open' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          updateMu.mutate({ id: s.id, status: 'in_progress' })
                        }
                        disabled={updateMu.isPending}
                      >
                        {t('propdev.snag.start', {
                          defaultValue: 'Start work',
                        })}
                      </Button>
                    )}
                    {(s.status === 'open' || s.status === 'in_progress') && (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => fixMu.mutate(s.id)}
                          disabled={fixMu.isPending}
                        >
                          {t('propdev.snag.mark_fixed', {
                            defaultValue: 'Mark fixed',
                          })}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => wontFixMu.mutate(s.id)}
                          disabled={wontFixMu.isPending}
                        >
                          {t('propdev.snag.wont_fix', {
                            defaultValue: "Won't fix",
                          })}
                        </Button>
                      </>
                    )}
                    {/* Promote to warranty — only meaningful once handover
                        is complete AND snag has a buyer link. Backend
                        enforces; hide here so UI never advertises 4xx. */}
                    {handover.completed_at && s.buyer_id && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<ShieldAlert size={11} />}
                        onClick={() => promoteMu.mutate(s.id)}
                        disabled={promoteMu.isPending}
                        title={t('propdev.snag.promote_help', {
                          defaultValue:
                            'File a warranty claim from this snag (idempotent)',
                        })}
                      >
                        {t('propdev.snag.promote_warranty', {
                          defaultValue: 'File warranty claim',
                        })}
                      </Button>
                    )}
                    <SnagPhotoButton snagId={s.id} handoverId={handover.id} />
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        const ok = await confirm({
                          title: t('propdev.snag.confirm_delete_title', {
                            defaultValue: 'Delete snag?',
                          }),
                          message: t('propdev.snag.confirm_delete', {
                            defaultValue: 'Delete this snag?',
                          }),
                          confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                          variant: 'danger',
                        });
                        if (!ok) return;
                        deleteMu.mutate(s.id);
                      }}
                      disabled={deleteMu.isPending}
                    >
                      <Trash2 size={11} />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {addOpen && (
        <CreateSnagModal
          handoverId={handover.id}
          buyerId={buyer?.id ?? null}
          plotId={plotId}
          costCurrency={buyer?.currency || null}
          onClose={() => setAddOpen(false)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

function SnagPhotoButton({
  snagId,
  handoverId,
}: {
  snagId: string;
  handoverId: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const inputId = `snag-photo-${snagId}`;
  const uploadMu = useMutation({
    mutationFn: (file: File) => uploadSnagPhoto(snagId, file),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.snag.photo_uploaded', {
          defaultValue: 'Photo uploaded',
        }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'snags', handoverId] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  return (
    <>
      <input
        id={inputId}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) {
            uploadMu.mutate(f);
            e.target.value = ''; // allow re-pick of same file
          }
        }}
      />
      <Button
        size="sm"
        variant="ghost"
        icon={
          uploadMu.isPending ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            <Camera size={11} />
          )
        }
        onClick={() => document.getElementById(inputId)?.click()}
        disabled={uploadMu.isPending}
      >
        {t('propdev.snag.add_photo', { defaultValue: 'Photo' })}
      </Button>
    </>
  );
}

function CreateSnagModal({
  handoverId,
  buyerId,
  plotId,
  costCurrency,
  onClose,
}: {
  handoverId: string;
  buyerId: string | null;
  plotId: string;
  /**
   * ISO currency the cost-impact estimate is denominated in. The Snag
   * model stores cost_impact as a bare Decimal in the buyer's /
   * development's base currency, so we surface the code on the input
   * label rather than letting the figure float currency-less.
   */
  costCurrency: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<{
    category: SnagCategory;
    severity: SnagSeverity;
    description: string;
    location_in_plot: string;
    cost_impact: string;
  }>({
    category: 'general',
    severity: 'minor',
    description: '',
    location_in_plot: '',
    cost_impact: '0',
  });
  const mu = useMutation({
    mutationFn: () =>
      createSnag({
        handover_id: handoverId,
        buyer_id: buyerId ?? null,
        category: form.category,
        severity: form.severity,
        description: form.description,
        location_in_plot: form.location_in_plot || undefined,
        cost_impact: form.cost_impact.trim() || undefined,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.snag.created', { defaultValue: 'Snag logged' }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'snags', handoverId] });
      qc.invalidateQueries({ queryKey: ['propdev', 'dashboard'] });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots', plotId] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const canSubmit = form.description.trim().length > 0 && !mu.isPending;
  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.snag.new', { defaultValue: 'Log new snag' })}
      size="md"
      busy={mu.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mu.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => mu.mutate()}
            disabled={!canSubmit}
            loading={mu.isPending}
            icon={<Plus size={14} />}
          >
            {t('propdev.snag.log', { defaultValue: 'Log snag' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.category', { defaultValue: 'Category' })}
        >
          <select
            value={form.category}
            onChange={(e) =>
              setForm({ ...form, category: e.target.value as SnagCategory })
            }
            className={inputCls}
          >
            <option value="cosmetic">{t('propdev.snag.category_cosmetic', { defaultValue: 'Cosmetic' })}</option>
            <option value="functional">{t('propdev.snag.category_functional', { defaultValue: 'Functional' })}</option>
            <option value="structural">{t('propdev.snag.category_structural', { defaultValue: 'Structural' })}</option>
            <option value="mechanical">{t('propdev.snag.category_mechanical', { defaultValue: 'Mechanical' })}</option>
            <option value="electrical">{t('propdev.snag.category_electrical', { defaultValue: 'Electrical' })}</option>
            <option value="plumbing">{t('propdev.snag.category_plumbing', { defaultValue: 'Plumbing' })}</option>
            <option value="finishing">{t('propdev.snag.category_finishing', { defaultValue: 'Finishing' })}</option>
            <option value="exterior">{t('propdev.snag.category_exterior', { defaultValue: 'Exterior' })}</option>
            <option value="general">{t('propdev.snag.category_general', { defaultValue: 'General' })}</option>
            <option value="safety">{t('propdev.snag.category_safety', { defaultValue: 'Safety' })}</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.severity', { defaultValue: 'Severity' })}
        >
          <select
            value={form.severity}
            onChange={(e) =>
              setForm({ ...form, severity: e.target.value as SnagSeverity })
            }
            className={inputCls}
          >
            <option value="cosmetic">{t('propdev.snag.severity_cosmetic', { defaultValue: 'Cosmetic' })}</option>
            <option value="minor">{t('propdev.snag.severity_minor', { defaultValue: 'Minor' })}</option>
            <option value="major">{t('propdev.snag.severity_major', { defaultValue: 'Major' })}</option>
            <option value="safety">{t('propdev.snag.severity_safety', { defaultValue: 'Safety' })}</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.snag.location', {
            defaultValue: 'Location in plot',
          })}
          span={2}
        >
          <input
            value={form.location_in_plot}
            onChange={(e) =>
              setForm({ ...form, location_in_plot: e.target.value })
            }
            className={inputCls}
            placeholder={t('propdev.snag.location_ph', {
              defaultValue: 'e.g. Master bedroom - east wall',
            })}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.description', { defaultValue: 'Description' })}
          required
          span={2}
        >
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className={inputCls}
            rows={3}
            placeholder={t('propdev.snag.describe', {
              defaultValue:
                'Defect description - what is wrong, observed symptoms, urgency…',
            })}
          />
        </WideModalField>
        <WideModalField
          label={
            costCurrency
              ? t('propdev.snag.cost_impact_ccy', {
                  defaultValue: 'Cost impact (estimate, {{ccy}})',
                  ccy: costCurrency,
                })
              : t('propdev.snag.cost_impact', {
                  defaultValue: 'Cost impact (estimate)',
                })
          }
        >
          <input
            type="number"
            min={0}
            step="0.01"
            value={form.cost_impact}
            onChange={(e) => setForm({ ...form, cost_impact: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
      {!buyerId && (
        <div className="mx-5 mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {t('propdev.snag.no_buyer_warn', {
            defaultValue:
              'No buyer is linked to this plot - the snag will be unattributed and cannot be promoted to a warranty claim until a buyer is assigned.',
          })}
        </div>
      )}
    </WideModal>
  );
}

