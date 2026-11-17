// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One seal: fingerprint strip, the opening in progress, and tabs for the sealed
 * contents, its openings, receipt and files, and the audit trail.
 */

import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Copy, Download, Lock, ShieldCheck } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  DateDisplay,
  EmptyState,
  ErrorState,
  KpiBand,
  MoneyDisplay,
  PageHeader,
  SkeletonTable,
  TabBar,
} from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { archiveApi, shortHash, type Opening, type SealDetail, type SealedPosition } from './api';
import { fmtDecimal, fmtRate, fmtStepPercent } from './format';
import { AuditTimeline } from './AuditTimeline';
import { OpeningModal } from './OpeningModal';
import { OpeningsTable } from './OpeningsTable';
import { PricingDrawer } from './PricingDrawer';
import { SealModal } from './SealModal';
import { receiptVariant, useArchiveTerm } from './labels';

type Tab = 'contents' | 'openings' | 'receipt' | 'audit';

export function SealPage() {
  const { t } = useTranslation();
  const { sealId = '' } = useParams<{ sealId: string }>();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('contents');
  const [openingModal, setOpeningModal] = useState(false);
  const [supersede, setSupersede] = useState(false);
  const seal = useQuery({ queryKey: ['estimate-archive', 'seal', sealId], queryFn: () => archiveApi.seal(sealId) });
  const openings = useQuery({
    queryKey: ['estimate-archive', 'openings', 'seal', sealId],
    queryFn: () => archiveApi.openings({ sealId }),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['estimate-archive'] });
  const verify = useMutation({ mutationFn: () => archiveApi.verify(sealId), onSuccess: refresh });
  const term = useArchiveTerm(seal.data?.policy.profile);

  if (seal.isLoading) return <SkeletonTable rows={6} />;
  if (seal.isError || !seal.data) {
    return (
      <ErrorState
        title={t('estimate_archive.load_error', { defaultValue: 'Sealed estimates could not be loaded' })}
        hint={getErrorMessage(seal.error)}
        onRetry={() => void seal.refetch()}
      />
    );
  }
  const s = seal.data;
  const live = (openings.data ?? []).find((o) => o.status === 'requested' || o.status === 'open');
  const superseded = s.status === 'superseded';

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.estimate_archive', { defaultValue: 'Sealed estimates' }), to: '/estimate-archive' },
          { label: s.label },
        ]}
      />
      <PageHeader
        srTitle={s.label}
        subtitle={[term, s.contract_label, t(`estimate_archive.basis.${s.basis_kind}`, { defaultValue: s.basis_kind })]
          .filter(Boolean)
          .join(' · ')}
        actions={
          superseded ? null : (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" icon={<ShieldCheck size={14} />} onClick={() => verify.mutate()} loading={verify.isPending}>
                {t('estimate_archive.verify', { defaultValue: 'Verify fingerprint' })}
              </Button>
              <Button variant="secondary" icon={<Download size={14} />} onClick={() => void archiveApi.downloadPackage(s.id)}>
                {t('estimate_archive.download_package', { defaultValue: 'Download deposit package' })}
              </Button>
              <Button variant="ghost" onClick={() => setSupersede(true)}>
                {t('estimate_archive.supersede', { defaultValue: 'Supersede' })}
              </Button>
              {!live && (
                <Button variant="primary" onClick={() => setOpeningModal(true)}>
                  {t('estimate_archive.request_opening', { defaultValue: 'Request opening' })}
                </Button>
              )}
            </div>
          )
        }
      />
      {superseded && s.superseded_by && (
        <div role="status" className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3 text-sm">
          {t('estimate_archive.superseded_by', {
            defaultValue: 'Superseded by {{label}} on {{date}}: {{reason}}',
            label: s.superseded_by.label,
            date: s.superseded_by.sealed_at.slice(0, 10),
            reason: s.superseded_by.reason,
          })}
        </div>
      )}
      <FingerprintStrip seal={s} verifyResult={verify.data?.ok} />
      {live && <SessionBar opening={live} onChanged={refresh} />}
      <KpiBand
        columns={5}
        items={[
          {
            key: 'total',
            label: t('estimate_archive.kpi.sealed_total', { defaultValue: 'Sealed total' }),
            value: <MoneyDisplay amount={s.award_total} currency={s.currency} />,
          },
          { key: 'positions', label: t('estimate_archive.kpi.positions', { defaultValue: 'Positions' }), value: s.positions },
          {
            key: 'breakdown',
            label: t('estimate_archive.kpi.with_breakdown', { defaultValue: 'With breakdown' }),
            value: s.with_breakdown,
            tone: s.with_breakdown < s.positions ? 'warning' : undefined,
          },
          { key: 'openings', label: t('estimate_archive.tab.openings', { defaultValue: 'Openings' }), value: s.openings },
          {
            key: 'receipt',
            label: t('estimate_archive.col.receipt', { defaultValue: 'Receipt' }),
            value: t(`estimate_archive.receipt.${s.receipt_status}`, { defaultValue: s.receipt_status }),
          },
        ]}
      />
      {s.findings.length > 0 && (
        <ul className="space-y-1">
          {s.findings.map((f) => (
            <li key={`${f.rule_id}-${f.message}`} className="text-sm text-content-secondary">
              <Badge variant={f.severity === 'error' ? 'error' : f.severity === 'warning' ? 'warning' : 'neutral'} size="sm">
                {f.code}
              </Badge>{' '}
              {f.message}
            </li>
          ))}
        </ul>
      )}
      <TabBar<Tab>
        ariaLabel={s.label}
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: 'contents', label: t('estimate_archive.tab.contents', { defaultValue: 'Contents' }) },
          { id: 'openings', label: t('estimate_archive.tab.openings', { defaultValue: 'Openings' }), badge: s.openings || undefined },
          { id: 'receipt', label: t('estimate_archive.tab.receipt', { defaultValue: 'Receipt and files' }) },
          { id: 'audit', label: t('estimate_archive.tab.audit', { defaultValue: 'Audit' }) },
        ]}
      />
      {tab === 'contents' && (
        <ContentsTab seal={s} sessionOpen={live?.status === 'open'} onRequestOpening={() => setOpeningModal(true)} />
      )}
      {tab === 'openings' && (
        <Card>{openings.isLoading ? <SkeletonTable rows={3} /> : <OpeningsTable rows={openings.data ?? []} />}</Card>
      )}
      {tab === 'receipt' && <ReceiptTab seal={s} onChanged={refresh} />}
      {tab === 'audit' && <AuditTab sealId={s.id} />}
      {openingModal && (
        <OpeningModal
          sealId={s.id}
          requireBothParties={s.policy.require_both_parties}
          onClose={() => setOpeningModal(false)}
        />
      )}
      {supersede && s.source_boq_id && (
        <SealModal
          projectId={s.project_id}
          boqId={s.source_boq_id}
          supersedeId={s.id}
          onClose={() => setSupersede(false)}
          onSealed={() => setSupersede(false)}
        />
      )}
    </div>
  );
}

function FingerprintStrip({ seal, verifyResult }: { seal: SealDetail; verifyResult?: boolean }) {
  const { t } = useTranslation();
  const ok = verifyResult ?? seal.last_verified_ok;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border-light bg-surface-secondary px-4 py-2 text-sm">
      <Lock size={14} className="text-content-tertiary" aria-hidden />
      <span className="text-content-secondary">{t('estimate_archive.fingerprint', { defaultValue: 'Fingerprint (SHA-256)' })}</span>
      <bdi dir="ltr" className="font-mono" title={seal.content_hash}>{shortHash(seal.content_hash)}</bdi>
      <button
        type="button"
        className="text-content-tertiary hover:text-content-primary"
        aria-label={t('estimate_archive.copy_fingerprint', { defaultValue: 'Copy fingerprint' })}
        onClick={() => void navigator.clipboard?.writeText(seal.content_hash)}
      >
        <Copy size={12} />
      </button>
      <span className="text-content-tertiary">
        {t('estimate_archive.sealed_at_utc', { defaultValue: 'sealed at {{when}} UTC', when: seal.sealed_at.slice(0, 16).replace('T', ' ') })}
      </span>
      {seal.tsa_authority && (
        <span className="text-content-tertiary">
          {t('estimate_archive.tsa_line', { defaultValue: 'Timestamp: {{authority}}', authority: seal.tsa_authority })}
        </span>
      )}
      {ok != null && (
        <span role={ok ? 'status' : 'alert'} className={ok ? 'text-semantic-success' : 'text-semantic-error'}>
          {ok
            ? t('estimate_archive.verified_ok', { defaultValue: 'Matches the sealed record' })
            : t('estimate_archive.verified_bad', { defaultValue: 'Does not match the sealed record' })}
          {seal.last_verified_at && (
            <>
              {' · '}
              <DateDisplay value={seal.last_verified_at} format="datetime" />
            </>
          )}
        </span>
      )}
    </div>
  );
}

function SessionBar({ opening, onChanged }: { opening: Opening; onChanged: () => void }) {
  const { t } = useTranslation();
  const [present, setPresent] = useState<string[]>(opening.attendees.map((a) => a.name));
  const start = useMutation({ mutationFn: () => archiveApi.startOpening(opening.id, present), onSuccess: onChanged });
  const close = useMutation({ mutationFn: () => archiveApi.closeOpening(opening.id), onSuccess: onChanged });
  const result = start.data ?? opening;
  return (
    <section
      role="region"
      aria-label={t('estimate_archive.session_label', { defaultValue: 'Opening in progress' })}
      className="sticky top-0 z-10 space-y-2 rounded-lg border border-oe-blue/40 bg-surface-primary p-3 shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-medium">
          {t('estimate_archive.session_title', {
            defaultValue: 'Opening for {{reference}}, attendees: {{count}}',
            reference: opening.reference_label,
            count: opening.attendees.length,
          })}
        </span>
        {opening.scope === 'positions' && (
          <bdi dir="ltr" className="font-mono text-xs">{opening.scope_ordinals.join(', ')}</bdi>
        )}
        <span className="ms-auto flex gap-2">
          {opening.status === 'requested' && (
            <Button size="sm" variant="primary" loading={start.isPending} onClick={() => start.mutate()}>
              {t('estimate_archive.start_opening', { defaultValue: 'Start opening' })}
            </Button>
          )}
          <Button size="sm" variant="secondary" loading={close.isPending} onClick={() => close.mutate()}>
            {t('estimate_archive.close_opening', { defaultValue: 'Close opening' })}
          </Button>
        </span>
      </div>
      {opening.status === 'requested' && (
        <fieldset className="flex flex-wrap gap-3 text-sm">
          <legend className="sr-only">{t('estimate_archive.attendance', { defaultValue: 'Attendance' })}</legend>
          {opening.attendees.map((a) => (
            <label key={a.name} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={present.includes(a.name)}
                onChange={(e) =>
                  setPresent((p) => (e.target.checked ? [...p, a.name] : p.filter((n) => n !== a.name)))
                }
              />
              {a.name}
              {a.organisation && <span className="text-content-tertiary">({a.organisation})</span>}
            </label>
          ))}
        </fieldset>
      )}
      {result.hash_check && (
        <p
          role={result.hash_check === 'ok' ? 'status' : 'alert'}
          className={result.hash_check === 'ok' ? 'text-base text-semantic-success' : 'text-base text-semantic-error'}
        >
          {result.hash_check === 'ok'
            ? t('estimate_archive.hash_matches', { defaultValue: 'Fingerprint matches the sealed record' })
            : t('estimate_archive.hash_mismatch_stop', {
                defaultValue: 'Fingerprint does not match: now {{actual}}. Stop and record this.',
                actual: shortHash(result.hash_seen ?? ''),
              })}
        </p>
      )}
    </section>
  );
}

function ContentsTab({
  seal,
  sessionOpen,
  onRequestOpening,
}: {
  seal: SealDetail;
  sessionOpen: boolean;
  onRequestOpening: () => void;
}) {
  const { t } = useTranslation();
  const allowed = seal.can_read_contents || sessionOpen;
  const contents = useQuery({
    queryKey: ['estimate-archive', 'contents', seal.id],
    queryFn: () => archiveApi.contents(seal.id),
    enabled: allowed,
  });
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [pricing, setPricing] = useState<SealedPosition | null>(null);
  if (!allowed) {
    return (
      <Card>
        <EmptyState
          icon={<Lock size={28} />}
          title={t('estimate_archive.empty.contents_locked', {
            defaultValue: 'Sealed. Its contents open only in a recorded opening.',
          })}
          action={{ label: t('estimate_archive.request_opening', { defaultValue: 'Request opening' }), onClick: onRequestOpening }}
        />
      </Card>
    );
  }
  if (contents.isLoading) return <SkeletonTable rows={6} />;
  if (contents.isError || !contents.data) {
    return <ErrorState title={getErrorMessage(contents.error)} onRetry={() => void contents.refetch()} />;
  }
  const { positions, markups } = contents.data.payload;
  const toggle = (p: SealedPosition) => {
    const next = !expanded[p.ordinal];
    setExpanded((e) => ({ ...e, [p.ordinal]: next }));
    if (next) void archiveApi.positionViewed(seal.id, p.ordinal);
  };
  return (
    <Card>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('estimate_archive.reading_logged', { defaultValue: 'Your reading is recorded in the audit log.' })}
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-xs text-content-tertiary">
            <th className="px-2 py-1.5 text-start font-medium">{t('estimate_archive.col.ordinal', { defaultValue: 'Ordinal' })}</th>
            <th className="px-2 py-1.5 text-start font-medium">{t('estimate_archive.col.description', { defaultValue: 'Description' })}</th>
            <th className="px-2 py-1.5 text-end font-medium">{t('estimate_archive.col.quantity', { defaultValue: 'Quantity' })}</th>
            <th className="px-2 py-1.5 text-end font-medium">{t('estimate_archive.price.rate', { defaultValue: 'Rate' })}</th>
            <th className="px-2 py-1.5 text-end font-medium">{t('estimate_archive.col.total', { defaultValue: 'Total' })}</th>
            <th className="px-2 py-1.5" />
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const priced = p.resources.length > 0 || p.unit_rate !== '0';
            const open = !!expanded[p.ordinal];
            return (
              <Fragment key={p.ordinal}>
                <tr className="border-b border-border-light">
                  <td className="px-2 py-1.5">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1"
                      aria-expanded={open}
                      disabled={!p.resources.length}
                      onClick={() => toggle(p)}
                    >
                      {p.resources.length ? open ? <ChevronDown size={12} /> : <ChevronRight size={12} className="rtl:rotate-180" /> : null}
                      <bdi dir="ltr" className="font-mono text-xs">{p.ordinal}</bdi>
                    </button>
                  </td>
                  <td className="px-2 py-1.5">{p.description}</td>
                  <td className="px-2 py-1.5 text-end font-mono text-xs" dir="ltr">{fmtDecimal(p.quantity)} {p.unit}</td>
                  <td className="px-2 py-1.5 text-end font-mono text-xs" dir="ltr">{fmtRate(p.unit_rate)}</td>
                  <td className="px-2 py-1.5 text-end"><MoneyDisplay amount={p.total} currency={seal.currency} /></td>
                  <td className="px-2 py-1.5 text-end">
                    {priced && p.resources.length > 0 && seal.status !== 'superseded' && (
                      <Button size="sm" variant="ghost" onClick={() => setPricing(p)}>
                        {t('estimate_archive.price_change', { defaultValue: 'Price a change' })}
                      </Button>
                    )}
                  </td>
                </tr>
                {open &&
                  p.resources.map((r) => (
                    <tr key={`${p.ordinal}-${r.code}`} className="border-b border-border-light bg-surface-secondary text-xs">
                      <td />
                      <td className="px-2 py-1 ps-6">
                        {r.description} <bdi dir="ltr" className="font-mono text-content-tertiary">{r.code}</bdi>
                      </td>
                      <td className="px-2 py-1 text-end font-mono" dir="ltr">{fmtDecimal(r.consumption)} {r.unit}</td>
                      <td className="px-2 py-1 text-end font-mono" dir="ltr">{fmtRate(r.unit_cost)}</td>
                      <td colSpan={2} className="px-2 py-1 text-content-tertiary">{[r.quote_ref, r.price_date].filter(Boolean).join(' · ')}</td>
                    </tr>
                  ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <p className="mt-3 flex flex-wrap items-center gap-1 text-xs text-content-secondary">
        <span>{t('estimate_archive.price.markups', { defaultValue: 'Markups (sealed stack, read-only)' })}:</span>
        {markups.filter((m) => m.is_active).map((m, i) => (
          <span key={`${m.key}-${i}`} className="inline-flex items-center gap-1">
            {i > 0 && <ChevronRight size={12} aria-hidden className="rtl:rotate-180" />}
            {m.name} {fmtStepPercent(m.percentage)}
          </span>
        ))}
      </p>
      {pricing && (
        <PricingDrawer sealId={seal.id} position={pricing} currency={seal.currency} onClose={() => setPricing(null)} />
      )}
    </Card>
  );
}

function ReceiptTab({ seal, onChanged }: { seal: SealDetail; onChanged: () => void }) {
  const { t } = useTranslation();
  const [reference, setReference] = useState('');
  const ask = useMutation({ mutationFn: () => archiveApi.requestReceipt(seal.id), onSuccess: onChanged });
  const external = useMutation({ mutationFn: () => archiveApi.externalReceipt(seal.id, reference), onSuccess: onChanged });
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <h3 className="mb-2 text-sm font-semibold">{t('estimate_archive.col.receipt', { defaultValue: 'Receipt' })}</h3>
        <Badge variant={receiptVariant(seal.receipt_status)}>
          {t(`estimate_archive.receipt.${seal.receipt_status}`, { defaultValue: seal.receipt_status })}
        </Badge>
        <ul className="mt-2 space-y-1 text-xs text-content-secondary">
          {seal.receipts.map((r) => (
            <li key={r.id}>
              {r.kind === 'external' ? r.external_reference : t('estimate_archive.receipt.signing', { defaultValue: 'Signing request' })} ·{' '}
              {t(`estimate_archive.receipt.${r.status}`, { defaultValue: r.status })} · <DateDisplay value={r.signed_at ?? r.created_at} />
            </li>
          ))}
        </ul>
        {seal.receipt_status === 'none' && seal.status !== 'superseded' && (
          <div className="mt-3 space-y-2">
            <Button size="sm" variant="secondary" loading={ask.isPending} onClick={() => ask.mutate()}>
              {t('estimate_archive.ask_receipt_short', { defaultValue: 'Ask the client to acknowledge' })}
            </Button>
            <div className="flex gap-2">
              <input
                className="oe-input"
                placeholder={t('estimate_archive.receipt_reference', { defaultValue: 'Receipt reference' })}
                value={reference}
                onChange={(e) => setReference(e.target.value)}
              />
              <Button size="sm" variant="secondary" disabled={!reference.trim()} onClick={() => external.mutate()}>
                {t('estimate_archive.record_external', { defaultValue: 'Record paper receipt' })}
              </Button>
            </div>
          </div>
        )}
      </Card>
      <Card>
        <h3 className="mb-2 text-sm font-semibold">{t('estimate_archive.files', { defaultValue: 'Files sealed with it' })}</h3>
        {seal.attachments.length === 0 ? (
          <p className="text-sm text-content-tertiary">{t('estimate_archive.no_files', { defaultValue: 'No files were sealed.' })}</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {seal.attachments.map((a) => (
              <li key={a.id} className="flex items-center gap-2">
                <span className="flex-1">{a.name}</span>
                <bdi dir="ltr" className="font-mono text-xs text-content-tertiary">{shortHash(a.file_hash)}</bdi>
                {checks[a.id] != null && (
                  <Badge size="sm" variant={checks[a.id] ? 'success' : 'error'}>
                    {checks[a.id]
                      ? t('estimate_archive.hash.ok', { defaultValue: 'OK' })
                      : t('estimate_archive.hash.mismatch', { defaultValue: 'Mismatch' })}
                  </Badge>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    const res = await archiveApi.checkAttachment(seal.id, a.id);
                    setChecks((c) => ({ ...c, [a.id]: res.ok }));
                  }}
                >
                  {t('estimate_archive.check_file', { defaultValue: 'Check' })}
                </Button>
              </li>
            ))}
          </ul>
        )}
        {seal.retention_until && (
          <p className="mt-3 text-xs text-content-tertiary">
            {t('estimate_archive.retention', { defaultValue: 'Kept until {{date}}', date: seal.retention_until })}
          </p>
        )}
      </Card>
    </div>
  );
}

function AuditTab({ sealId }: { sealId: string }) {
  const events = useQuery({ queryKey: ['estimate-archive', 'events', 'seal', sealId], queryFn: () => archiveApi.events(sealId) });
  return <Card>{events.isLoading ? <SkeletonTable rows={5} /> : <AuditTimeline events={events.data ?? []} />}</Card>;
}

