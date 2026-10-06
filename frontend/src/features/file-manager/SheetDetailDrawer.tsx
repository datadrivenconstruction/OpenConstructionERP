// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Detail panel for one indexed drawing sheet.
 *
 * The register used to be a dead end: every row carried a `document_id` and a
 * `page_number` and nothing was clickable, so the only thing a user could do
 * after finding a drawing was read its number back off the screen. This panel
 * is the way out of the table - it names the sheet, shows the revision stack
 * the backend tracks, and links into the two places a found drawing is
 * actually used.
 *
 * Both links are deep-links that already exist, not new endpoints:
 *
 *   * Plan room takes `?doc=<document id>&page=<n>` and reads its drawing list
 *     straight off `/v1/documents/`, which is the same table `Sheet.document_id`
 *     points at, so the id needs no translation.
 *   * Takeoff takes `?doc=<document id>&source=document`, which asks the
 *     backend to find-or-create the matching takeoff document (idempotent, so
 *     re-opening reuses the row), plus `?page=<n>` to land on the sheet's own
 *     page rather than page 1.
 *
 * The fields can be corrected in place. A title block read wrongly, or not at
 * all, is the common case for a drawing set from another market, and the
 * register is only as useful as its numbers and revisions. The edit goes
 * through `PATCH /v1/documents/sheets/{id}`, gated on `documents.update`, and a
 * changed number or revision makes the backend restack the sheet, so the save
 * refetches the register and the stack instead of patching rows by hand.
 *
 * There is deliberately no drawing preview here. A sheet's rendered PNG is
 * stored as a server filesystem path and no route serves it to an authenticated
 * client - the only reader is the HMAC share-token flow, which mints a public
 * link and is the wrong shape for this. Rather than point an `<AuthImage>` at a
 * URL that 404s, the panel says plainly that the preview is not available and
 * leaves the user the two links that do work.
 */
import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { AlertTriangle, ArrowRight, FileText, History, ImageOff, Pencil, Ruler } from 'lucide-react';
import { Badge, Button, DateDisplay, SideDrawer } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { updateSheet, type SheetPatch } from './api';
import { SheetEditForm } from './SheetEditForm';
import { orderStack, revisionOrderUnclear } from './sheetStack';
import type { SheetRow } from './types';

/** Mirrors `SheetVersionHistory` from the documents module. `current` is the
 *  sheet that was asked about, NOT necessarily the newest one; `history` is
 *  every other sheet on the chain. */
interface SheetVersionHistory {
  current: SheetRow;
  history: SheetRow[];
}

export interface SheetDetailDrawerProps {
  /** The sheet to describe. `null` closes the drawer. */
  sheet: SheetRow | null;
  onClose: () => void;
  /** Called with the row the server returned after an edit, so the caller
   *  keeps showing the sheet as it now is. */
  onSheetChange?: (sheet: SheetRow) => void;
}

/** One label/value line. Renders an em dash when the field is not set, so the
 *  panel keeps the same shape whether or not the PDF carried a title block. */
function Field({ label, value }: { label: string; value: ReactNode | null }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="shrink-0 text-2xs uppercase tracking-wider text-content-tertiary">{label}</dt>
      <dd className="min-w-0 truncate text-end text-sm text-content-primary">
        {value ?? <span className="text-content-quaternary">&mdash;</span>}
      </dd>
    </div>
  );
}

export function SheetDetailDrawer({ sheet, onClose, onSheetChange }: SheetDetailDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = useHasPermission('documents.update');
  const [editing, setEditing] = useState(false);

  // A different sheet opens in view mode, never in the middle of another
  // sheet's edit.
  useEffect(() => {
    setEditing(false);
  }, [sheet?.id]);

  const { data: versions, isLoading: versionsLoading } = useQuery({
    queryKey: ['sheet-versions', sheet?.id],
    queryFn: () => apiGet<SheetVersionHistory>(`/v1/documents/sheets/${sheet?.id}/versions/`),
    enabled: !!sheet?.id,
  });

  const projectId = sheet?.project_id ?? '';
  const { data: disciplines = [] } = useQuery({
    queryKey: ['sheet-disciplines', projectId],
    queryFn: () =>
      apiGet<string[]>(
        `/v1/documents/sheets/disciplines/?project_id=${encodeURIComponent(projectId)}`,
      ),
    enabled: editing && !!projectId,
  });

  const saveMutation = useMutation({
    mutationFn: (patch: SheetPatch) => updateSheet(sheet?.id ?? '', patch),
    onSuccess: (updated) => {
      setEditing(false);
      onSheetChange?.(updated);
      // A changed number or revision restacks the sheet, which can retire or
      // restore other rows, so every view of the register is refetched.
      queryClient.invalidateQueries({ queryKey: ['sheets', updated.project_id] });
      queryClient.invalidateQueries({ queryKey: ['sheet-versions'] });
      queryClient.invalidateQueries({ queryKey: ['sheet-disciplines', updated.project_id] });
    },
  });

  /* The whole stack in one list, newest first, so the panel can render it as a
     single sequence instead of "this one" plus "some others". The backend hands
     back the asked-for sheet separately from the rest of the chain. */
  const chain = useMemo(() => {
    if (!versions) return [];
    return orderStack([versions.current, ...versions.history]);
  }, [versions]);

  /* What replaced this sheet. Only meaningful for a superseded row, and only
     when the chain actually holds a current one - a chain whose head was
     deleted has no answer, and inventing one would be worse than the gap. */
  const supersededBy = useMemo(() => {
    if (!sheet || sheet.is_current) return null;
    return chain.find((s) => s.is_current && s.id !== sheet.id) ?? null;
  }, [chain, sheet]);

  if (!sheet) return null;

  const sheetName = sheet.sheet_number ?? `p.${sheet.page_number}`;
  const planRoomTo = `/plan-room?doc=${encodeURIComponent(sheet.document_id)}&page=${sheet.page_number}`;
  const takeoffTo =
    `/takeoff?tab=measurements&source=document&doc=${encodeURIComponent(sheet.document_id)}` +
    `&page=${sheet.page_number}`;
  const filesTo = `/files?file=${encodeURIComponent(sheet.document_id)}`;
  const saveError = saveMutation.error
    ? saveMutation.error instanceof Error
      ? saveMutation.error.message
      : String(saveMutation.error)
    : null;

  const actionCls =
    'inline-flex items-center justify-between gap-2 rounded-lg border border-border-light px-3 py-2.5 text-sm font-medium text-content-primary transition-colors hover:border-oe-blue hover:bg-surface-secondary';

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={sheetName}
      subtitle={sheet.sheet_title ?? undefined}
      widthClass="max-w-md"
    >
      <div className="p-5">
        {/* Preview slot. Honest about why it is empty - see the file header. */}
        <div className="mb-5 flex h-32 flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-border-light bg-surface-secondary/40 text-content-tertiary">
          <ImageOff size={20} strokeWidth={1.5} />
          <p className="px-4 text-center text-2xs">
            {t('sheets.preview_unavailable', {
              defaultValue: 'No preview available for this sheet yet.',
            })}
          </p>
        </div>

        {/* Metadata, or the form that corrects it. The button is left out for
            a role the PATCH would refuse rather than offered and failed. */}
        {canEdit && !editing && (
          <div className="mb-2 flex justify-end">
            <Button
              variant="secondary"
              size="sm"
              icon={<Pencil size={13} />}
              onClick={() => {
                saveMutation.reset();
                setEditing(true);
              }}
            >
              {t('sheets.edit_action', { defaultValue: 'Edit details' })}
            </Button>
          </div>
        )}
        {editing ? (
          <SheetEditForm
            sheet={sheet}
            disciplines={disciplines}
            saving={saveMutation.isPending}
            error={saveError}
            onSubmit={(patch) => saveMutation.mutate(patch)}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <dl className="divide-y divide-border-light">
            <Field
              label={t('sheets.col_number', { defaultValue: 'Sheet #' })}
              value={sheet.sheet_number}
            />
            <Field
              label={t('sheets.col_title', { defaultValue: 'Title' })}
              value={sheet.sheet_title}
            />
            <Field
              label={t('sheets.col_discipline', { defaultValue: 'Discipline' })}
              value={sheet.discipline}
            />
            <Field
              label={t('sheets.col_revision', { defaultValue: 'Rev' })}
              value={sheet.revision}
            />
            <Field
              label={t('sheets.col_issue_date', { defaultValue: 'Issue Date' })}
              value={sheet.revision_date ? <DateDisplay value={sheet.revision_date} format="date" /> : null}
            />
            <Field
              label={t('sheets.col_scale', { defaultValue: 'Scale' })}
              value={sheet.scale}
            />
            <Field
              label={t('sheets.col_page', { defaultValue: 'Page' })}
              value={String(sheet.page_number)}
            />
          </dl>
        )}

        {/* Revision standing */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge variant={sheet.is_current ? 'success' : 'warning'} size="sm">
            {sheet.is_current
              ? t('sheets.is_current_yes', { defaultValue: 'Current revision' })
              : t('sheets.is_current_no', { defaultValue: 'Superseded' })}
          </Badge>
          {supersededBy && (
            <span className="text-xs text-content-secondary">
              {t('sheets.superseded_by', {
                defaultValue: 'Replaced by revision {{revision}}',
                revision:
                  supersededBy.revision ??
                  supersededBy.sheet_number ??
                  `p.${supersededBy.page_number}`,
              })}
            </span>
          )}
        </div>
        {revisionOrderUnclear(sheet) && (
          <div className="mt-3 flex gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning/5 px-3 py-2 text-xs text-content-secondary">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" />
            <div>
              <p className="font-medium text-content-primary">
                {t('sheets.revision_order_unclear', {
                  defaultValue: 'Revision order unclear, check',
                })}
              </p>
              <p className="mt-0.5">
                {t('sheets.revision_order_unclear_hint', {
                  defaultValue:
                    'This revision could not be ranked against the one it replaced, so the latest upload was made current. Check the revision and correct it if it is wrong.',
                })}
              </p>
            </div>
          </div>
        )}

        {/* Revision stack. Present whenever the sheet has more than itself on
            the chain - a one-entry chain says nothing a badge has not said. */}
        {(versionsLoading || chain.length > 1) && (
          <section className="mt-6">
            <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-content-primary">
              <History size={14} className="text-oe-blue" />
              {t('sheets.version_history', { defaultValue: 'Revision history' })}
            </h3>
            {versionsLoading ? (
              <p className="text-xs text-content-tertiary">
                {t('sheets.version_loading', { defaultValue: 'Loading revisions…' })}
              </p>
            ) : (
              <>
                <p className="mb-2 text-2xs text-content-tertiary">
                  {t('sheets.stack_hint', {
                    defaultValue:
                      'Newest on top. An older revision uploaded later is filed beneath the newer one and never replaces it.',
                  })}
                </p>
                <ol className="flex flex-col gap-1.5">
                  {chain.map((v) => (
                    <li
                      key={v.id}
                      className={clsx(
                        'flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-xs',
                        v.id === sheet.id
                          ? 'border-oe-blue bg-oe-blue-subtle'
                          : 'border-border-light bg-surface-secondary/40',
                      )}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <Badge variant={v.is_current ? 'success' : 'neutral'} size="sm">
                          {v.revision ??
                            t('sheets.revision_unset', { defaultValue: 'No rev' })}
                        </Badge>
                        <span className="truncate text-content-secondary">
                          {v.sheet_title ?? v.sheet_number ?? `p.${v.page_number}`}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2 text-content-tertiary">
                        {v.is_current && (
                          <span className="font-medium text-semantic-success">
                            {t('sheets.stack_current', { defaultValue: 'Current' })}
                          </span>
                        )}
                        <DateDisplay value={v.revision_date ?? v.created_at} format="relative" />
                      </span>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </section>
        )}

        {/* Where this sheet goes next */}
        <section className="mt-6">
          <h3 className="mb-2 text-xs font-semibold text-content-primary">
            {t('sheets.open_in', { defaultValue: 'Open this sheet in' })}
          </h3>
          <div className="flex flex-col gap-2">
            <Link to={planRoomTo} className={actionCls}>
              <span className="flex items-center gap-2">
                <FileText size={15} className="text-oe-blue" />
                {t('sheets.open_plan_room', { defaultValue: 'Plan room' })}
              </span>
              <ArrowRight size={14} className="text-content-tertiary" />
            </Link>
            <Link to={takeoffTo} className={actionCls}>
              <span className="flex items-center gap-2">
                <Ruler size={15} className="text-oe-blue" />
                {t('sheets.open_takeoff', { defaultValue: 'PDF takeoff, to measure it' })}
              </span>
              <ArrowRight size={14} className="text-content-tertiary" />
            </Link>
            <Link to={filesTo} className={actionCls}>
              <span className="flex items-center gap-2">
                <FileText size={15} className="text-oe-blue" />
                {t('sheets.open_source_document', { defaultValue: 'The drawing set it came from' })}
              </span>
              <ArrowRight size={14} className="text-content-tertiary" />
            </Link>
          </div>
        </section>
      </div>
    </SideDrawer>
  );
}
