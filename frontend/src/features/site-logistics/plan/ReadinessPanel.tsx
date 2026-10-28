// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Whether the logistics area is ready for its gate: the six checks the
// server evaluates, every open finding behind them, the dated sweep, the
// exports for the file, and the catalogue the project's figures come from.

import { useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleAlert, Download, RefreshCw, XCircle } from 'lucide-react';

import { fmtList } from '@/shared/lib/formatters';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { useToastStore } from '@/stores/useToastStore';

import { REGISTERS, exportRegister, pinCatalogue, runSweep, type CatalogueChoice, type Register } from './api';
import { useCatalogueChoices, useConcept, useInvalidatePlan, useReadiness, useReportProblem, useWords } from './hooks';
import { ChecksPanel } from './ChecksPanel';
import { Card, FormDialog, Loaded, PanelHead } from './PlanBits';
import { denied, enumLabel, findingText, humanise, type Field } from './rules';
import type { PanelProps } from './SitePanels';
import { isTextKey, served, tx } from './texts';

const PINNABLE: string[] = ['shipped', 'tenant', 'pack'];

/** The two lists of open heavy transports an item may carry, each with its line. */
const OPEN = [
  ['applied', 'readiness.open.permit_applied'],
  ['missing', 'readiness.open.permit_missing'],
] as const;

export function ReadinessPanel({ projectId, catalogue }: PanelProps) {
  const words = useWords();
  const { t, language } = words;
  const readiness = useReadiness(projectId);
  const mayPin = useConcept(projectId).data?.can?.pin_catalogue;
  const invalidate = useInvalidatePlan(projectId);
  const report = useReportProblem(catalogue);
  const addToast = useToastStore((s) => s.addToast);
  const [sweeping, setSweeping] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [pinning, setPinning] = useState(false);
  const choices = useCatalogueChoices(projectId, pinning);

  const sweep = async () => {
    setSweeping(true);
    try {
      const result = await runSweep(projectId);
      await invalidate();
      addToast({
        type: 'success',
        title: tx(t, 'readiness.sweep_done'),
        message: tx(t, 'readiness.sweep_result', {
          permits: Object.values(result.permits).reduce((a, b) => a + b, 0),
          complaints: result.complaints_overdue,
          arrived: result.transports_arrived,
        }),
      });
    } catch (err) {
      report(err);
    } finally {
      setSweeping(false);
    }
  };

  const download = async (register: Register, format: 'pdf' | 'xlsx') => {
    setExporting(`${register}.${format}`);
    try {
      await exportRegister(projectId, register, format);
    } catch (err) {
      report(err);
    } finally {
      setExporting(null);
    }
  };

  const evidence = (code: string) => {
    const key = `evidence.${code}`;
    return isTextKey(key) ? tx(t, key) : humanise(code);
  };

  const governance = (code: string) => {
    const key = `readiness.governance.${code}`;
    return isTextKey(key) ? tx(t, key) : humanise(code);
  };
  // A shipped catalogue is named by a key, a tenant's own by its texts.
  const catalogueName = (c: CatalogueChoice) => {
    const own = c.name.text?.[language] ?? c.name.text?.en ?? humanise(c.code || c.id);
    return c.name.key ? served(t, c.name.key, own) : own;
  };

  const pinFields: Field[] = [
    {
      name: 'choice',
      label: 'f.catalogue',
      kind: 'select',
      required: true,
      wide: true,
      // The pin takes a shipped, a tenant or a pack catalogue; any other source in the list would be refused.
      options: (choices.data ?? [])
        .filter((c) => PINNABLE.includes(c.source))
        .map((c) => ({ value: `${c.source}:${c.id}`, label: catalogueName(c) })),
    },
  ];

  // Only the server's plain no counts; while the answer is on its way nothing is claimed.
  const noGates = readiness.data?.gates_in_use === false;

  return (
    <section className="space-y-5" data-testid="plan-readiness">
      <div className="space-y-3">
        <PanelHead title="tab.readiness">
          <Button size="sm" variant="secondary" loading={sweeping} onClick={() => void sweep()} data-testid="plan-sweep">
            <RefreshCw size={14} className="mr-1" />
            {tx(t, 'readiness.sweep')}
          </Button>
        </PanelHead>
        <p className="text-sm text-content-secondary">{tx(t, noGates ? 'readiness.lead_plain' : 'readiness.lead')}</p>
        <Loaded query={readiness}>
          {(r) => (
            <>
              {/* Without gates the missing model is how the project is run, not something to repair. */}
              {noGates ? (
                <p className="text-sm text-content-secondary" data-testid="plan-ready-no-gates">
                  {tx(t, 'readiness.no_gates')}
                </p>
              ) : (
                r.governance && (
                  <p className="text-sm text-content-secondary" data-testid="plan-ready-governance">
                    {governance(r.governance)}
                  </p>
                )
              )}
              <div
                className="flex items-center gap-2 text-base font-semibold text-content-primary"
                data-testid="plan-ready-verdict"
                data-ready={r.ready}
              >
                {r.ready ? (
                  <CheckCircle2 size={18} className="text-semantic-success" aria-hidden />
                ) : (
                  <CircleAlert size={18} className="text-semantic-error" aria-hidden />
                )}
                {noGates
                  ? tx(t, r.ready ? 'readiness.ready_plain' : 'readiness.not_ready_plain')
                  : tx(t, r.ready ? 'readiness.ready' : 'readiness.not_ready')}
              </div>
              <ul className="space-y-1.5">
                {r.items.map((item) => (
                  <li key={item.code} className="flex items-start gap-2 text-sm" data-testid="plan-ready-item" data-state={item.state}>
                    {item.state === 'met' ? (
                      <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-semantic-success" aria-hidden />
                    ) : item.state === 'unknown' ? (
                      <CircleAlert size={15} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
                    ) : (
                      <XCircle size={15} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
                    )}
                    <span className="text-content-primary">
                      {evidence(item.code)}
                      {OPEN.map(([list, key]) => {
                        const titles = (item.transports?.[list] ?? []).map((x) => x.title);
                        return titles.length > 0 ? (
                          <span key={list} className="block text-xs text-content-secondary" data-testid="plan-ready-open">
                            {tx(t, key, { titles: fmtList(titles) })}
                          </span>
                        ) : null;
                      })}
                    </span>
                    {item.state === 'unknown' ? (
                      <span className="text-content-tertiary">{tx(t, 'readiness.unknown')}</span>
                    ) : (
                      <span className="sr-only">{tx(t, item.state === 'met' ? 'readiness.met' : 'readiness.not_met')}</span>
                    )}
                  </li>
                ))}
              </ul>
              {r.passed_by_permit.length > 0 && (
                <div data-testid="plan-ready-passed">
                  <h4 className="text-sm font-semibold text-content-primary">{tx(t, 'readiness.passed_title')}</h4>
                  <ul className="mt-1 space-y-1 text-sm text-content-secondary">
                    {r.passed_by_permit.map((x) => (
                      <li key={`${x.transport_id}-${x.id}`}>
                        {tx(t, 'readiness.passed_item', { title: x.title, reference: x.reference })}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div>
                <h4 className="text-sm font-semibold text-content-primary">{tx(t, 'readiness.findings')}</h4>
                {r.findings.length === 0 ? (
                  <p className="mt-1 text-sm text-content-secondary">{tx(t, 'empty.readiness_findings')}</p>
                ) : (
                  <ul className="mt-2 space-y-1.5">
                    {r.findings.map((f, i) => (
                      <li key={`${f.code}-${f.ref}-${i}`} className="flex items-start gap-2 text-sm" data-testid="plan-finding" data-severity={f.severity}>
                        <Badge variant={f.severity === 'error' ? 'error' : 'warning'} size="sm">
                          {tx(t, f.severity === 'error' ? 'readiness.error' : 'readiness.warning')}
                        </Badge>
                        <span className="text-content-primary">{findingText(words, f, catalogue)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </Loaded>
      </div>

      <ChecksPanel projectId={projectId} />

      <div className="space-y-2">
        <h3 className="text-base font-semibold text-content-primary">{tx(t, 'readiness.export')}</h3>
        <p className="text-sm text-content-secondary">{tx(t, 'readiness.export_lead')}</p>
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {REGISTERS.map((register) => (
            <li key={register} className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-2">
              <span className="text-sm text-content-primary">{tx(t, `register.${register}`)}</span>
              <span className="flex gap-1">
                {(['pdf', 'xlsx'] as const).map((format) => (
                  <Button
                    key={format}
                    size="sm"
                    variant="ghost"
                    loading={exporting === `${register}.${format}`}
                    onClick={() => void download(register, format)}
                    data-testid={`plan-export-${register}-${format}`}
                  >
                    <Download size={13} className="mr-1" />
                    {tx(t, `readiness.${format}`)}
                  </Button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {catalogue && (
        <ul>
          <Card testId="plan-catalogue">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-content-primary">{tx(t, 'readiness.catalogue')}</span>
              <span className="text-sm text-content-secondary">
                {tx(t, 'readiness.catalogue_version', {
                  id: catalogue.labels?.[language] ?? catalogue.labels?.en ?? humanise(catalogue.pin.id),
                  version: catalogue.pin.version ?? catalogue.version,
                })}
              </span>
              <Badge variant="neutral" size="sm">
                {enumLabel(t, 'source', catalogue.pin.source)}
              </Badge>
              <span className="ml-auto">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={denied(mayPin)}
                  onClick={() => setPinning(true)}
                  data-testid="plan-change-catalogue"
                >
                  {tx(t, 'readiness.change_catalogue')}
                </Button>
              </span>
            </div>
            <p className="mt-1 text-xs text-content-secondary">{tx(t, 'readiness.catalogue_hint')}</p>
            {catalogue.review_status !== 'verified' && (
              <p className="mt-1 flex items-start gap-1.5 text-xs text-semantic-warning" data-testid="plan-catalogue-unconfirmed">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden />
                {tx(t, 'readiness.catalogue_unconfirmed')}
              </p>
            )}
          </Card>
        </ul>
      )}
      {pinning && catalogue && (
        <FormDialog
          title="edit_title.catalogue"
          fields={pinFields}
          defaults={{ choice: `${catalogue.pin.source}:${catalogue.pin.id}` }}
          projectId={projectId}
          catalogue={catalogue}
          shape={(body) => {
            const [source, id] = String(body.choice ?? '').split(':');
            return { source, catalogue_id: id };
          }}
          onSubmit={(body) => pinCatalogue(projectId, body)}
          onSaved={invalidate}
          onClose={() => setPinning(false)}
        />
      )}
    </section>
  );
}
