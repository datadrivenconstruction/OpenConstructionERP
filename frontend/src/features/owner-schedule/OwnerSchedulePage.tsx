// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Owner bid schedule: bring the owner's pay-item file into this estimate, review
 * addenda as a diff and send the priced file back. The file format is a profile
 * the user confirms; nothing is written before the preview is accepted.
 */
import { useState, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Download, FileUp } from 'lucide-react';
import { Badge, Breadcrumb, Button, EmptyState, SkeletonTable } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  detectProfiles,
  exportSchedule,
  previewAddendum,
  previewSchedule,
  useApplyAddendum,
  useImportSchedule,
  useProfiles,
  useScheduleStatus,
  type AddendumPreview,
  type DetectCandidate,
  type Preview,
} from './api';
import { bestCandidate, countByKind, hasBlockingIssue, pricedPercent } from './logic';
import { PageHeader } from '@/shared/ui/PageHeader';

function ImportPanel({ boqId }: { boqId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const profiles = useProfiles();
  const importer = useImportSchedule(boqId);
  const [file, setFile] = useState<File | null>(null);
  const [candidates, setCandidates] = useState<DetectCandidate[]>([]);
  const [profileKey, setProfileKey] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);

  const fail = (e: unknown) => addToast({ type: 'error', title: t('owner_schedule.failed', { defaultValue: 'Could not read the file' }), message: getErrorMessage(e) });

  const choose = async (profile: string, f: File) => {
    setProfileKey(profile);
    setBusy(true);
    try {
      setPreview(await previewSchedule(f, profile));
    } catch (e) {
      setPreview(null);
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (ev: ChangeEvent<HTMLInputElement>) => {
    const f = ev.target.files?.[0] ?? null;
    ev.target.value = '';
    setFile(f);
    setPreview(null);
    setCandidates([]);
    if (!f) return;
    setBusy(true);
    try {
      const found = await detectProfiles(f);
      setCandidates(found);
      const best = bestCandidate(found);
      if (best) await choose(best.profile_key, f);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const doImport = () => {
    if (!file || !profileKey) return;
    importer.mutate(
      { file, profileKey },
      {
        onSuccess: (r) =>
          addToast({
            type: 'success',
            title: t('owner_schedule.imported', {
              defaultValue: '{{created}} positions created, {{linked}} linked',
              created: r.created_positions,
              linked: r.linked_positions,
            }),
          }),
        onError: fail,
      },
    );
  };

  return (
    <div className="space-y-4" data-testid="owner-schedule-import">
      <p className="text-sm text-content-secondary">
        {t('owner_schedule.import_hint', {
          defaultValue: 'Pick the owner\'s bid schedule (CSV or spreadsheet). Item numbers, texts and units stay as the owner wrote them.',
        })}
      </p>
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border-light px-3 py-2 text-sm hover:bg-surface-secondary">
        <FileUp size={15} />
        {file ? file.name : t('owner_schedule.choose_file', { defaultValue: 'Choose file' })}
        <input type="file" accept=".csv,.xlsx,.xlsm,.xml" className="sr-only" onChange={onFile} data-testid="owner-schedule-file" />
      </label>

      {file && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="owner-schedule-profile" className="text-sm text-content-secondary">
            {t('owner_schedule.profile', { defaultValue: 'Format' })}
          </label>
          <select
            id="owner-schedule-profile"
            value={profileKey}
            onChange={(e) => file && choose(e.target.value, file)}
            className="rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
          >
            <option value="" disabled>{t('owner_schedule.profile_pick', { defaultValue: 'Select a format' })}</option>
            {(profiles.data ?? []).map((p) => (
              <option key={p.key} value={p.key}>{p.name}</option>
            ))}
          </select>
          {candidates.length > 0 && !bestCandidate(candidates) && (
            <Badge variant="warning">{t('owner_schedule.no_match', { defaultValue: 'No format matched, choose one' })}</Badge>
          )}
        </div>
      )}

      {busy && <SkeletonTable rows={4} />}

      {preview && !busy && (
        <div className="space-y-3">
          <div className="text-sm">
            {t('owner_schedule.preview_count', { defaultValue: '{{count}} pay items found', count: preview.item_count })}
          </div>
          {preview.issues.length > 0 && (
            <ul className="space-y-1 text-sm" data-testid="owner-schedule-issues">
              {preview.issues.map((i, n) => (
                <li key={n} className="flex items-center gap-2">
                  <Badge variant={i.severity === 'error' ? 'error' : 'warning'}>
                    {t(`owner_schedule.issue.${i.code}`, { defaultValue: i.code })}
                  </Badge>
                  {i.item_no && <span>{i.item_no}</span>}
                  {i.row != null && <span className="text-content-tertiary">{t('owner_schedule.row', { defaultValue: 'row {{n}}', n: i.row })}</span>}
                </li>
              ))}
            </ul>
          )}
          <div className="max-h-72 overflow-auto rounded-lg border border-border-light">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-secondary text-left">
                <tr>
                  <th className="px-2 py-1.5">{t('owner_schedule.col_item', { defaultValue: 'Item' })}</th>
                  <th className="px-2 py-1.5">{t('owner_schedule.col_description', { defaultValue: 'Description' })}</th>
                  <th className="px-2 py-1.5">{t('owner_schedule.col_unit', { defaultValue: 'Unit' })}</th>
                  <th className="px-2 py-1.5 text-right">{t('owner_schedule.col_quantity', { defaultValue: 'Quantity' })}</th>
                </tr>
              </thead>
              <tbody>
                {preview.lines.map((l) => (
                  <tr key={l.row} className={l.is_section ? 'bg-surface-secondary font-medium' : ''}>
                    <td className="px-2 py-1">{l.item_no}</td>
                    <td className="px-2 py-1">{l.description}</td>
                    <td className="px-2 py-1">{l.unit}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{l.quantity ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Button
            variant="primary"
            onClick={doImport}
            loading={importer.isPending}
            disabled={hasBlockingIssue(preview.issues) || preview.item_count === 0}
            data-testid="owner-schedule-import-go"
          >
            {t('owner_schedule.import', { defaultValue: 'Import into this estimate' })}
          </Button>
        </div>
      )}
    </div>
  );
}

function AddendumPanel({ boqId }: { boqId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const apply = useApplyAddendum(boqId);
  const [file, setFile] = useState<File | null>(null);
  const [diff, setDiff] = useState<AddendumPreview | null>(null);

  const onFile = async (ev: ChangeEvent<HTMLInputElement>) => {
    const f = ev.target.files?.[0] ?? null;
    ev.target.value = '';
    setFile(f);
    setDiff(null);
    if (!f) return;
    try {
      setDiff(await previewAddendum(boqId, f));
    } catch (e) {
      addToast({ type: 'error', title: t('owner_schedule.failed', { defaultValue: 'Could not read the file' }), message: getErrorMessage(e) });
    }
  };

  const counts = diff ? countByKind(diff.changes) : null;
  return (
    <div className="space-y-3" data-testid="owner-schedule-addendum">
      <p className="text-sm text-content-secondary">
        {t('owner_schedule.addendum_hint', { defaultValue: 'Load the revised schedule to see what the owner added, removed or changed before it touches the estimate.' })}
      </p>
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border-light px-3 py-2 text-sm hover:bg-surface-secondary">
        <FileUp size={15} />
        {t('owner_schedule.addendum_choose', { defaultValue: 'Choose revised file' })}
        <input type="file" accept=".csv,.xlsx,.xlsm" className="sr-only" onChange={onFile} />
      </label>
      {diff && counts && (
        <>
          <div className="flex flex-wrap gap-2 text-sm">
            <Badge variant="success">{t('owner_schedule.diff_added', { defaultValue: '{{n}} added', n: counts.added })}</Badge>
            <Badge variant="error">{t('owner_schedule.diff_removed', { defaultValue: '{{n}} removed', n: counts.removed })}</Badge>
            <Badge variant="warning">{t('owner_schedule.diff_quantity', { defaultValue: '{{n}} quantity changed', n: counts.quantity_changed })}</Badge>
            <Badge variant="neutral">{t('owner_schedule.diff_changed', { defaultValue: '{{n}} text or unit changed', n: counts.changed })}</Badge>
          </div>
          {diff.changes.length === 0 ? (
            <p className="text-sm text-content-secondary">{t('owner_schedule.diff_none', { defaultValue: 'No differences from the schedule on file.' })}</p>
          ) : (
            <Button
              variant="primary"
              loading={apply.isPending}
              onClick={() =>
                file &&
                apply.mutate(
                  { file, itemNos: null },
                  {
                    onSuccess: (r) => {
                      setDiff(null);
                      setFile(null);
                      addToast({ type: 'success', title: t('owner_schedule.addendum_applied', { defaultValue: 'Revision {{rev}} applied', rev: r.revision }) });
                    },
                    onError: (e) => addToast({ type: 'error', title: t('owner_schedule.failed', { defaultValue: 'Could not read the file' }), message: getErrorMessage(e) }),
                  },
                )
              }
            >
              {t('owner_schedule.addendum_apply', { defaultValue: 'Apply all changes' })}
            </Button>
          )}
        </>
      )}
    </div>
  );
}

export function OwnerSchedulePage() {
  const { t } = useTranslation();
  const { boqId = '' } = useParams<{ boqId: string }>();
  const addToast = useToastStore((s) => s.addToast);
  const status = useScheduleStatus(boqId);
  const sched = status.data;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('boq.title', { defaultValue: 'Bill of Quantities' }), to: `/boq/${boqId}` },
          { label: t('owner_schedule.title', { defaultValue: 'Owner bid schedule' }) },
        ]}
      />
      <PageHeader srTitle={t('owner_schedule.title', { defaultValue: 'Owner bid schedule' })} />

      {status.isLoading && <SkeletonTable rows={5} />}
      {status.isError && (
        <EmptyState title={t('owner_schedule.load_failed', { defaultValue: 'Could not load the schedule' })} description={getErrorMessage(status.error)} />
      )}

      {status.isSuccess && !sched && <ImportPanel boqId={boqId} />}

      {sched && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-content-secondary">
              {sched.file_name} · {sched.profile_name} · {t('owner_schedule.revision', { defaultValue: 'revision {{n}}', n: sched.revision })}
            </div>
            <Button
              variant="secondary"
              icon={<Download size={14} />}
              onClick={() =>
                exportSchedule(boqId).catch((e) =>
                  addToast({ type: 'error', title: t('owner_schedule.export_failed', { defaultValue: 'Export failed' }), message: getErrorMessage(e) }),
                )
              }
              data-testid="owner-schedule-export"
            >
              {t('owner_schedule.export', { defaultValue: 'Export priced file' })}
            </Button>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border-light p-3">
              <div className="text-xs text-content-tertiary">{t('owner_schedule.priced', { defaultValue: 'Priced items' })}</div>
              <div className="text-lg font-semibold tabular-nums">{sched.priced_count} / {sched.item_count}</div>
              <progress className="mt-1 h-1.5 w-full" max={100} value={pricedPercent(sched.priced_count, sched.item_count)} />
            </div>
            <div className="rounded-lg border border-border-light p-3">
              <div className="text-xs text-content-tertiary">{t('owner_schedule.total', { defaultValue: 'Total' })}</div>
              <div className="text-lg font-semibold tabular-nums">{sched.total}</div>
            </div>
            <div className="rounded-lg border border-border-light p-3">
              <div className="text-xs text-content-tertiary">{t('owner_schedule.alternates_total', { defaultValue: 'Alternates' })}</div>
              <div className="text-lg font-semibold tabular-nums">{sched.alternates_total}</div>
            </div>
          </div>

          {sched.findings.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold">{t('owner_schedule.findings', { defaultValue: 'Checks before you submit' })}</h2>
              <ul className="space-y-1 text-sm" data-testid="owner-schedule-findings">
                {sched.findings.map((f, n) => (
                  <li key={n} className="flex items-center gap-2">
                    <Badge variant={f.severity === 'error' ? 'error' : 'warning'}>
                      {t(`owner_schedule.rule.${f.rule_id.replace('owner_schedule.', '')}`, { defaultValue: f.rule_id })}
                    </Badge>
                    {f.item_no && <span className="font-medium">{f.item_no}</span>}
                    <span className="text-content-secondary">{f.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="max-h-96 overflow-auto rounded-lg border border-border-light">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-secondary text-left">
                <tr>
                  <th className="px-2 py-1.5">{t('owner_schedule.col_item', { defaultValue: 'Item' })}</th>
                  <th className="px-2 py-1.5">{t('owner_schedule.col_description', { defaultValue: 'Description' })}</th>
                  <th className="px-2 py-1.5">{t('owner_schedule.col_unit', { defaultValue: 'Unit' })}</th>
                  <th className="px-2 py-1.5 text-right">{t('owner_schedule.col_quantity', { defaultValue: 'Quantity' })}</th>
                  <th className="px-2 py-1.5 text-right">{t('owner_schedule.col_unit_price', { defaultValue: 'Unit price' })}</th>
                  <th className="px-2 py-1.5 text-right">{t('owner_schedule.col_amount', { defaultValue: 'Amount' })}</th>
                </tr>
              </thead>
              <tbody>
                {sched.items.map((it) => (
                  <tr key={it.id} className={it.is_section ? 'bg-surface-secondary font-medium' : it.removed ? 'opacity-50 line-through' : ''}>
                    <td className="px-2 py-1">{it.item_no}</td>
                    <td className="px-2 py-1">{it.description}</td>
                    <td className="px-2 py-1">{it.unit}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{it.quantity ?? ''}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{it.unit_price ?? ''}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{it.amount ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <section>
            <h2 className="mb-2 text-sm font-semibold">{t('owner_schedule.addendum', { defaultValue: 'Addendum' })}</h2>
            <AddendumPanel boqId={boqId} />
          </section>
          <Link className="text-sm text-oe-blue hover:underline" to={`/boq/${boqId}`}>
            {t('owner_schedule.back', { defaultValue: 'Back to the estimate' })}
          </Link>
        </div>
      )}
    </div>
  );
}
