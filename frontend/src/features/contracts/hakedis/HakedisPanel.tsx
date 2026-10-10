// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// HakedisPanel - the payment certificate (hakediş) of a progress claim or of a
// subcontractor payment application.
//
// One panel serves both documents: it is told which kind it is looking at and
// everything below it is the same. It shows only where the server says the
// contract has a certificate layout, and renders nothing anywhere else, so a
// claim of any other country looks exactly as it did.
//
// The certificate is the server's. This screen prints its header, its list of
// works and its lettered summary in the order and under the letters given,
// lets a person fill what only a person can (the entered lines, the tax
// choices), and says at the top what still stands between the document and
// its certification. It works out no amount.
//
// It is certified by the source document's own transition, which lives beside
// this panel. Once certified the certificate is frozen: what is shown is the
// stored snapshot, and nothing on it can be changed.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowDownRight, CheckCircle2, Lock, ShieldX } from 'lucide-react';

import { Badge, Card } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { DocumentExportMenu } from '@/shared/ui/DocumentExportMenu';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { ROLE_RANK } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';
import { useNumberLocale } from '@/stores/usePreferencesStore';
import {
  HAKEDIS_LOCALES,
  downloadHakedis,
  getHakedis,
  putHakedisOptions,
  type HakedisDocument,
  type HakedisFinding,
  type HakedisLabelledRow,
  type HakedisSource,
} from './api';
import {
  clearHakedisRefusal,
  hakedisKey,
  hakedisRefusalKey,
  isHakedisNotAvailable,
  readRefusal,
  screenLocale,
  type HakedisRefusal,
} from './hakedisQueries';
import {
  BlockTitle,
  RefusalNote,
  anchorId,
  jumpTo,
  lineAnchor,
  lineName,
  lineNamer,
  rankOf,
  taxAnchor,
} from './hakedisParts';
import { DERIVED_REASONS, TAX_SET_REASONS, reasonSentence, type ReasonContext } from './hakedisText';
import { CHOICE_OF_FIGURE, HakedisSummaryTable } from './HakedisSummaryTable';
import { HakedisTaxes } from './HakedisTaxes';
import { HakedisWorksTable } from './HakedisWorksTable';

/** Rules whose finding is already said by a line or by the tax block. */
const FINDINGS_SAID_ELSEWHERE: readonly string[] = [
  'hakedis.lines_complete',
  'hakedis.taxes_stale',
  'hakedis.taxes_confirmed',
];

function isBlocking(finding: HakedisFinding): boolean {
  return finding.severity === 'error' || finding.engine_error;
}

/** One thing a person still has to do, with the place on the screen where it is done. */
interface AttentionItem {
  id: string;
  text: string;
  target: string;
}

export interface HakedisPanelProps {
  /** Which document the certificate belongs to. */
  source: HakedisSource;
  className?: string;
}

export function HakedisPanel({ source, className }: HakedisPanelProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const numberLocale = useNumberLocale();
  const role = useAuthStore((s) => s.userRole);
  const locale = screenLocale(i18n.language);

  const docQ = useQuery({
    queryKey: hakedisKey(source, locale),
    queryFn: () => getHakedis(source, locale),
    enabled: source.id !== '',
    // "No layout for this contract" is an answer, not a failure to retry.
    retry: false,
  });
  // Written by the certifying transition when the server refuses it; never fetched.
  const refusalQ = useQuery<HakedisRefusal | null>({
    queryKey: hakedisRefusalKey(source),
    queryFn: () => null,
    enabled: false,
  });

  const onUpdated = (next: HakedisDocument) => {
    qc.setQueryData(hakedisKey(source, locale), next);
    clearHakedisRefusal(qc, source);
  };
  const finalMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: (isFinal: boolean) => putHakedisOptions(source, isFinal, locale),
    onSuccess: onUpdated,
  });

  const doc = docQ.data;
  const context = useMemo<ReasonContext | null>(
    () => (doc ? { currency: doc.currency, locale: numberLocale, lineName: lineNamer(doc) } : null),
    [doc, numberLocale],
  );

  // Nothing is shown while the answer is awaited: on every contract without a
  // layout a placeholder would flash and vanish.
  if (docQ.isPending) return null;
  if (docQ.isError) {
    if (isHakedisNotAvailable(docQ.error)) return null;
    return (
      <Card className={className} data-testid="hakedis-panel-error">
        <BlockTitle>{t('hakedis.title', { defaultValue: 'Payment certificate' })}</BlockTitle>
        <RefusalNote t={t} refusal={readRefusal(docQ.error)} />
      </Card>
    );
  }
  if (!doc || !context) return null;

  const canEdit = doc.editable && rankOf(role) >= ROLE_RANK.editor;
  // A refusal recorded before the certificate was completed says nothing once
  // the server calls it ready, or once it has been certified.
  const refusal = !doc.frozen && !doc.can_certify ? (refusalQ.data ?? null) : null;
  // A refused certification carries the findings the server judged it on.
  const findings = doc.findings.length > 0 ? doc.findings : (refusal?.findings ?? []);
  const lineKeys = new Set(doc.summary.map((line) => line.key));
  const lineFindings = new Map<string, HakedisFinding[]>();
  const otherFindings: HakedisFinding[] = [];
  for (const finding of findings) {
    if (FINDINGS_SAID_ELSEWHERE.includes(finding.rule_id)) continue;
    if (finding.element_ref && lineKeys.has(finding.element_ref)) {
      const list = lineFindings.get(finding.element_ref) ?? [];
      list.push(finding);
      lineFindings.set(finding.element_ref, list);
    } else {
      otherFindings.push(finding);
    }
  }
  const errors = otherFindings.filter(isBlocking);
  const warnings = otherFindings.filter((finding) => !isBlocking(finding));

  // What a person still has to do. A line that only waits for another line is
  // left out (its operand is listed), and the tax lines that share one reason
  // about the stored set are one item, because one action resolves them.
  const attention: AttentionItem[] = [];
  if (!doc.frozen) {
    let taxSetListed = false;
    for (const line of doc.summary) {
      if (line.status !== 'held' || DERIVED_REASONS.includes(line.reason_key)) continue;
      const sentence = reasonSentence(t, line.reason_key, line.reason_params, context, line.reason_text[0]);
      if (line.op === 'tax' && TAX_SET_REASONS.includes(line.reason_key)) {
        if (taxSetListed) continue;
        taxSetListed = true;
        attention.push({ id: 'taxes', text: sentence, target: anchorId(source, 'taxes') });
        continue;
      }
      const choice = line.op === 'tax' ? CHOICE_OF_FIGURE[line.tax_kind] : undefined;
      attention.push({
        id: `line-${line.key}`,
        text: t('hakedis.attention.line', {
          defaultValue: '{{line}}: {{reason}}',
          line: lineName(line),
          reason: sentence,
        }),
        target: choice ? taxAnchor(source, choice) : lineAnchor(source, line.key),
      });
    }
    if (doc.taxes.stored && doc.taxes.status === 'draft' && !taxSetListed) {
      attention.push({
        id: 'taxes-unconfirmed',
        text: t('hakedis.attention.taxes_unconfirmed', {
          defaultValue: 'The taxes are saved but not confirmed yet.',
        }),
        target: anchorId(source, 'taxes'),
      });
    }
    for (const finding of [...lineFindings.entries()].flatMap(([key, list]) =>
      list.filter(isBlocking).map((item) => ({ key, item })),
    )) {
      attention.push({
        id: `finding-${finding.key}-${finding.item.rule_id}`,
        text: finding.item.message,
        target: lineAnchor(source, finding.key),
      });
    }
    errors.forEach((finding, index) => {
      attention.push({
        id: `finding-${finding.rule_id}-${index}`,
        text: finding.message,
        target: anchorId(source, 'findings'),
      });
    });
  }

  const header = doc.header;
  const fileName = `hakedis-${header.certificate_number}`;
  const headerRows = (rows: HakedisLabelledRow[]) => (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[minmax(8rem,auto)_1fr]">
      {rows.map((row) => (
        <div key={row.labels.join('|')} className="contents">
          <dt className="break-words text-content-tertiary">{row.labels.join(' / ')}</dt>
          <dd className="min-w-0 break-words text-content-primary">{row.value}</dd>
        </div>
      ))}
    </dl>
  );

  return (
    <Card className={className} data-testid="hakedis-panel" data-source-kind={source.kind}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words text-base font-semibold text-content-primary">
            {t('hakedis.title', { defaultValue: 'Payment certificate' })}{' '}
            <span className="whitespace-nowrap tabular-nums">
              {t('hakedis.header.number', { defaultValue: 'No. {{number}}', number: header.certificate_number })}
            </span>
          </h2>
          <p className="mt-0.5 text-xs text-content-secondary">
            <DateDisplay value={header.period_start} format="numeric" />
            {' - '}
            <DateDisplay value={header.period_end} format="numeric" />
            <span className="ml-2">
              {t('hakedis.header.currency', { defaultValue: 'Currency: {{currency}}', currency: doc.currency })}
            </span>
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Badge variant="neutral" size="sm">
              {doc.options.is_final
                ? t('hakedis.header.final', { defaultValue: 'Final certificate' })
                : t('hakedis.header.interim', { defaultValue: 'Interim certificate' })}
            </Badge>
            {doc.frozen ? (
              <span data-testid="hakedis-frozen-badge">
                <Badge variant="success" size="sm">
                  <Lock size={11} className="mr-1 inline" aria-hidden="true" />
                  {t('hakedis.frozen.badge', { defaultValue: 'Frozen' })}
                </Badge>
              </span>
            ) : (
              doc.is_draft && (
                <span data-testid="hakedis-draft-badge">
                  <Badge variant="warning" size="sm">
                    {t('hakedis.draft.badge', { defaultValue: 'Draft' })}
                  </Badge>
                </span>
              )
            )}
          </div>
        </div>
        <DocumentExportMenu
          label={t('hakedis.export.label', { defaultValue: 'Download' })}
          locales={HAKEDIS_LOCALES}
          testId="hakedis-export"
          note={
            doc.is_draft && !doc.frozen
              ? t('hakedis.export.draft_note', {
                  defaultValue: 'The document prints as a draft until every line has its figure.',
                })
              : undefined
          }
          items={[
            {
              id: 'pdf',
              kind: 'pdf',
              label: t('hakedis.export.pdf', { defaultValue: 'Certificate (PDF)' }),
              run: (language) => downloadHakedis(source, 'pdf', language, fileName),
            },
            {
              id: 'xlsx',
              kind: 'xlsx',
              label: t('hakedis.export.xlsx', { defaultValue: 'Certificate (Excel)' }),
              run: (language) => downloadHakedis(source, 'xlsx', language, fileName),
            },
          ]}
        />
      </div>

      {doc.frozen && (
        <p
          className="mt-3 flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-primary"
          data-testid="hakedis-frozen-note"
        >
          <Lock size={15} className="mt-0.5 shrink-0 text-content-tertiary" aria-hidden="true" />
          <span className="min-w-0 break-words">
            {t('hakedis.frozen.note', {
              defaultValue:
                'This certificate was certified and is frozen. What is shown is the stored snapshot: it no longer follows the contract or the claim.',
            })}
            {doc.frozen_at && (
              <>
                {' '}
                <DateDisplay value={doc.frozen_at} format="datetime" />
              </>
            )}
          </span>
        </p>
      )}

      {!doc.frozen && (
        <section
          className={
            attention.length > 0
              ? 'mt-3 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 dark:border-amber-900 dark:bg-amber-950/30'
              : 'mt-3 rounded-lg border border-border-light bg-surface-secondary px-3 py-2'
          }
          aria-label={t('hakedis.attention.title', { defaultValue: 'Needs your attention' })}
          data-testid="hakedis-attention"
        >
          {attention.length > 0 ? (
            <>
              <p className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                <AlertTriangle size={15} className="shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
                {t('hakedis.attention.title', { defaultValue: 'Needs your attention' })}
                <span className="font-normal text-content-tertiary">({attention.length})</span>
              </p>
              <ul className="mt-1.5 space-y-1">
                {attention.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => jumpTo(item.target)}
                      className="flex w-full items-start gap-1.5 rounded text-left text-sm text-content-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                      data-testid={`hakedis-attention-${item.id}`}
                    >
                      <ArrowDownRight size={13} className="mt-1 shrink-0 text-content-tertiary" aria-hidden="true" />
                      <span className="min-w-0 break-words">{item.text}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : doc.can_certify ? (
            <p className="flex items-center gap-2 text-sm text-content-primary" data-testid="hakedis-ready">
              <CheckCircle2 size={15} className="shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
              {t('hakedis.attention.ready', { defaultValue: 'Nothing is missing. The certificate is ready to certify.' })}
            </p>
          ) : (
            <p className="text-sm text-content-secondary" data-testid="hakedis-not-ready">
              {t('hakedis.attention.not_ready', {
                defaultValue: 'No line is waiting for you, but the certificate cannot be certified yet.',
              })}
            </p>
          )}
        </section>
      )}

      {refusal && (
        <div className="mt-3">
          <RefusalNote t={t} refusal={refusal} testId="hakedis-certify-refusal" />
        </div>
      )}

      {(errors.length > 0 || warnings.length > 0) && (
        <section id={anchorId(source, 'findings')} tabIndex={-1} className="mt-3 space-y-2 focus:outline-none">
          {errors.length > 0 && (
            <div
              className="rounded-lg border border-red-200 bg-red-50/60 px-3 py-2 dark:border-red-900 dark:bg-red-950/30"
              data-testid="hakedis-findings-errors"
            >
              <BlockTitle count={errors.length}>
                {t('hakedis.findings.errors', { defaultValue: 'Blocks certification' })}
              </BlockTitle>
              <FindingList findings={errors} blocking />
            </div>
          )}
          {warnings.length > 0 && (
            <div
              className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 dark:border-amber-900 dark:bg-amber-950/30"
              data-testid="hakedis-findings-warnings"
            >
              <BlockTitle count={warnings.length}>
                {t('hakedis.findings.warnings', { defaultValue: 'Worth a look, does not block' })}
              </BlockTitle>
              <FindingList findings={warnings} blocking={false} />
            </div>
          )}
        </section>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <BlockTitle>{t('hakedis.section.header', { defaultValue: 'Certificate details' })}</BlockTitle>
          {headerRows(header.rows)}
        </div>
        <div className="min-w-0">
          <BlockTitle>{t('hakedis.section.parties', { defaultValue: 'Parties' })}</BlockTitle>
          {headerRows(header.party_rows)}
        </div>
      </div>

      {canEdit && (
        <label className="mt-3 flex items-start gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            className="mt-1"
            checked={doc.options.is_final}
            disabled={finalMut.isPending}
            onChange={(e) => finalMut.mutate(e.target.checked)}
            data-testid="hakedis-final-toggle"
          />
          <span className="min-w-0 break-words">
            {t('hakedis.options.is_final', { defaultValue: 'This is the final certificate of the contract' })}
          </span>
        </label>
      )}
      {finalMut.isError && (
        <div className="mt-2">
          <RefusalNote t={t} refusal={readRefusal(finalMut.error)} />
        </div>
      )}

      <section id={anchorId(source, 'works')} tabIndex={-1} className="mt-5 focus:outline-none">
        <BlockTitle>{t('hakedis.section.works', { defaultValue: 'Works done' })}</BlockTitle>
        <HakedisWorksTable
          works={doc.works}
          currency={doc.currency}
          numberLocale={numberLocale}
          caption={t('hakedis.section.works', { defaultValue: 'Works done' })}
        />
      </section>

      <section className="mt-5">
        <BlockTitle>{t('hakedis.section.summary', { defaultValue: 'Summary' })}</BlockTitle>
        <HakedisSummaryTable
          source={source}
          doc={doc}
          locale={locale}
          numberLocale={numberLocale}
          canEdit={canEdit}
          onUpdated={onUpdated}
          lineFindings={lineFindings}
        />
        {doc.carried_total !== null && (
          <p className="mt-2 flex flex-wrap justify-end gap-2 text-xs text-content-secondary">
            {t('hakedis.summary.carried_total', { defaultValue: 'Carried to the next certificate as its previous total' })}
            <MoneyDisplay amount={doc.carried_total} currency={doc.currency || undefined} className="tabular-nums" />
          </p>
        )}
      </section>

      <div id={anchorId(source, 'taxes')} tabIndex={-1} className="mt-5 focus:outline-none">
        <HakedisTaxes
          // The block keeps the choices being made; a new stored set starts it afresh.
          key={`${doc.taxes.stored}|${doc.taxes.status}|${doc.frozen}`}
          source={source}
          doc={doc}
          locale={locale}
          numberLocale={numberLocale}
          canEdit={canEdit}
          onUpdated={onUpdated}
        />
      </div>

      {doc.notes.length > 0 && (
        <section className="mt-5" data-testid="hakedis-notes">
          <BlockTitle>{t('hakedis.section.notes', { defaultValue: 'Notes' })}</BlockTitle>
          <p className="mb-1 text-xs text-content-secondary">
            {t('hakedis.draft.reasons', { defaultValue: 'Why the document prints as a draft' })}
          </p>
          <ol className="space-y-1 text-sm">
            {doc.notes.map((note) => (
              <li key={note.number} className="flex gap-2">
                <span className="shrink-0 tabular-nums text-content-tertiary">{note.number}.</span>
                <span className="min-w-0 break-words text-content-primary">
                  {reasonSentence(t, note.reason_key, note.reason_params, context, note.text[0])}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {doc.signature_roles.length > 0 && (
        <section className="mt-5">
          <BlockTitle>{t('hakedis.section.signatures', { defaultValue: 'Signed by' })}</BlockTitle>
          <ul className="flex flex-wrap gap-2 text-sm">
            {doc.signature_roles.map((signer) => (
              <li key={signer.key} className="rounded-md border border-border-light px-2 py-1 text-content-secondary">
                {signer.labels.join(' / ')}
              </li>
            ))}
          </ul>
        </section>
      )}
    </Card>
  );
}

/** Findings in the conventions of the claim's submission check: the message, then how to resolve it. */
function FindingList({ findings, blocking }: { findings: HakedisFinding[]; blocking: boolean }) {
  return (
    <ul className="space-y-1.5">
      {findings.map((finding, index) => (
        <li key={`${finding.rule_id}|${finding.element_ref ?? ''}|${index}`} className="flex items-start gap-2 text-sm">
          {blocking ? (
            <ShieldX size={14} className="mt-0.5 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
          ) : (
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
          )}
          <span className="min-w-0">
            <span className="block break-words text-content-primary">{finding.message}</span>
            {finding.suggestion && (
              <span className="mt-0.5 block break-words text-xs text-content-secondary">{finding.suggestion}</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
