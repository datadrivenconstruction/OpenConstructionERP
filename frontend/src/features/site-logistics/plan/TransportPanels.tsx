// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Heavy, oversize and outbound transports, and the permits that let them
// run. Whether a transport counts as heavy, and whether its permit covers
// it, is decided by the server and only shown here.

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, FileCheck2, Truck } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { fmtList } from '@/shared/lib/formatters';

import { fetchGates } from '../api';
import type { Permit, Transport } from './api';
import { day, num, span, when } from './format';
import { useConcept, useCustoms, usePermits, useResource, useTransports, useWords } from './hooks';
import { Card, Fact, FormDialog, Loaded, PanelHead, PlanEmpty, RowActions, StateBadge } from './PlanBits';
import { codeLabel, codeOptions, enumLabel, findingText, frozenOf, weekdayOptions, type Field } from './rules';
import type { PanelProps } from './SitePanels';
import { tx } from './texts';

const LOAD_FIELDS = ['gross_weight_t', 'axle_load_t', 'height_m', 'width_m', 'length_m', 'turning_radius_m'] as const;

/* ── Transports ───────────────────────────────────────────────────────── */

export function TransportsPanel({ projectId, catalogue }: PanelProps) {
  const zone = useConcept(projectId).data?.site_timezone;
  const words = useWords();
  const { t, language } = words;
  const transports = useTransports(projectId);
  const customs = useCustoms(projectId);
  // Same key as the gates tab, so both read one cache entry.
  const gates = useQuery({
    queryKey: ['site-logistics-gates', projectId],
    queryFn: () => fetchGates(projectId),
    enabled: !!projectId,
  });
  const resource = useResource<Transport>(projectId, 'transport', { catalogue });

  const gateOptions = useMemo(() => (gates.data ?? []).map((g) => ({ value: g.id, label: g.name })), [gates.data]);
  const caseOptions = useMemo(
    () => (customs.data ?? []).map((c) => ({ value: c.id, label: c.title || c.incoterm })),
    [customs.data],
  );
  const fields: Field[] = [
    { name: 'title', label: 'f.title', kind: 'text', required: true, wide: true },
    {
      name: 'direction',
      label: 'f.direction',
      kind: 'select',
      required: true,
      options: ['inbound', 'outbound'].map((v) => ({ value: v, label: enumLabel(t, 'direction', v) })),
    },
    {
      name: 'transport_kind',
      label: 'f.transport_kind',
      kind: 'select',
      required: true,
      options: codeOptions(words, 'transport_kinds', catalogue),
    },
    { name: 'planned_window_start', label: 'f.planned_window_start', kind: 'datetime' },
    { name: 'planned_window_end', label: 'f.planned_window_end', kind: 'datetime' },
    { name: 'gate_id', label: 'f.gate', kind: 'select', options: gateOptions },
    { name: 'carrier_name', label: 'f.carrier_name', kind: 'text' },
    { name: 'origin', label: 'f.origin', kind: 'text' },
    { name: 'destination', label: 'f.destination', kind: 'text' },
    ...LOAD_FIELDS.map((name): Field => ({ name, label: `f.${name}`, kind: 'decimal' })),
    { name: 'load_class', label: 'f.load_class', kind: 'select', options: codeOptions(words, 'load_classes', catalogue) },
    { name: 'escort_required', label: 'f.escort_required', kind: 'checkbox' },
    { name: 'customs_case_id', label: 'f.customs_case', kind: 'select', options: caseOptions },
    { name: 'po_id', label: 'f.purchase_order', kind: 'link', link: 'purchase_order' },
    { name: 'waste_record_ref', label: 'f.waste_record_ref', kind: 'text' },
    { name: 'route_notes', label: 'f.route_notes', kind: 'textarea' },
  ];

  return (
    <section className="space-y-3" data-testid="plan-transports">
      <PanelHead title="tab.transports" action="add_transport" may={resource.mayCreate} onAction={() => resource.open()} />
      {(gates.isError || customs.isError) && (
        <p role="alert" className="text-sm text-semantic-error" data-testid="plan-transport-options-failed">
          {tx(t, 'transport.options_failed')}
        </p>
      )}
      <Loaded query={transports}>
        {(rows) =>
          rows.length === 0 ? (
            <PlanEmpty
              icon={<Truck size={28} />}
              title="empty.transports_title"
              body="empty.transports_body"
              action="add_transport"
              may={resource.mayCreate}
              onAction={() => resource.open()}
            />
          ) : (
            <ul className="space-y-2">
              {rows.map((x) => {
                // Above the limit is only a blocker when no permit lets the load through; the server says which.
                const blocked = x.gate_blocked || !!x.permit_finding || x.gate_needs_timezone;
                return (
                  <Card key={x.id} testId="plan-transport" alert={blocked}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-content-primary">{x.title}</span>
                      <Badge variant="neutral" size="sm">
                        {codeLabel(words, 'transport_kinds', x.transport_kind, catalogue)}
                      </Badge>
                      <span className="text-xs text-content-secondary">{enumLabel(t, 'direction', x.direction)}</span>
                      <StateBadge state={x.state} />
                      {x.is_heavy && (
                        <span data-testid="plan-transport-heavy">
                          <Badge variant="warning" size="sm">
                            {tx(t, 'transport.heavy')}
                          </Badge>
                        </span>
                      )}
                      <span className="ml-auto">
                        <RowActions resource={resource} record={x} lifecycle="transport" />
                      </span>
                    </div>
                    <dl className="mt-2 grid gap-3 sm:grid-cols-4">
                      <Fact label="transport.window">
                        {span(t, when(x.planned_window_start, language, zone), when(x.planned_window_end, language, zone))}
                      </Fact>
                      <Fact label="f.gate">{gateOptions.find((g) => g.value === x.gate_id)?.label}</Fact>
                      <Fact label="f.carrier_name">{x.carrier_name}</Fact>
                      <Fact label="transport.route">{span(t, x.origin || null, x.destination || null)}</Fact>
                      {LOAD_FIELDS.map((name) => (
                        <Fact key={name} label={`f.${name}`}>
                          {num(x[name])}
                        </Fact>
                      ))}
                      <Fact label="f.load_class">
                        {x.load_class ? codeLabel(words, 'load_classes', x.load_class, catalogue) : null}
                      </Fact>
                      <Fact label="transport.escort">{x.escort_required ? tx(t, 'yes') : null}</Fact>
                    </dl>
                    {blocked && (
                      <div className="mt-2 space-y-1" data-testid="plan-transport-blockers">
                        {x.gate_blocked && (
                          <p className="flex items-start gap-1.5 text-sm text-semantic-error">
                            <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
                            {tx(t, 'transport.gate_exceeded')}
                          </p>
                        )}
                        {x.gate_needs_timezone && !x.permit_finding && (
                          <p className="flex items-start gap-1.5 text-sm text-semantic-error">
                            <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
                            {tx(t, 'transport.needs_timezone')}
                          </p>
                        )}
                        {x.permit_finding && (
                          <p className="flex items-start gap-1.5 text-sm text-semantic-error">
                            <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
                            {findingText(words, { code: x.permit_finding }, catalogue)}
                          </p>
                        )}
                      </div>
                    )}
                    {x.gate_passed_by_permit && (
                      <p className="mt-2 text-sm text-content-secondary" data-testid="plan-transport-gate-passed">
                        {tx(t, 'transport.gate_passed', { reference: x.gate_passed_by_permit.reference })}
                      </p>
                    )}
                    {(x.permits.length > 0 || x.is_heavy) && (
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
                        <span className="font-medium">{tx(t, 'transport.permits')}</span>
                        {x.permits.length === 0 && <span>{tx(t, 'transport.no_permit')}</span>}
                        {x.permits.map((p) => (
                          <span key={p.id} className="inline-flex items-center gap-1">
                            {codeLabel(words, 'permit_kinds', p.permit_kind, catalogue)}
                            <StateBadge state={p.state} />
                          </span>
                        ))}
                      </div>
                    )}
                  </Card>
                );
              })}
            </ul>
          )
        }
      </Loaded>
      {resource.editing && (
        <FormDialog
          title="edit_title.transport"
          fields={fields}
          record={resource.editing.record}
          defaults={{ direction: 'inbound' }}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={resource.save}
          onSaved={resource.saved}
          onClose={resource.close}
        />
      )}
    </section>
  );
}

/* ── Permits ──────────────────────────────────────────────────────────── */

export function PermitsPanel({ projectId, catalogue }: PanelProps) {
  const words = useWords();
  const { t, language } = words;
  const permits = usePermits(projectId);
  const transports = useTransports(projectId);
  const resource = useResource<Permit>(projectId, 'permit', { catalogue });
  const days = useMemo(() => weekdayOptions(language), [language]);
  const transportOptions = useMemo(
    () => (transports.data ?? []).map((x) => ({ value: x.id, label: x.title })),
    [transports.data],
  );
  const fields: Field[] = [
    {
      name: 'permit_kind',
      label: 'f.permit_kind',
      kind: 'select',
      required: true,
      options: codeOptions(words, 'permit_kinds', catalogue),
    },
    { name: 'reference', label: 'f.reference', kind: 'text' },
    { name: 'authority', label: 'f.authority', kind: 'text' },
    { name: 'applied_on', label: 'f.applied_on', kind: 'date' },
    { name: 'valid_from', label: 'f.valid_from', kind: 'date' },
    { name: 'valid_to', label: 'f.valid_to', kind: 'date' },
    { name: 'covers_transport_ids', label: 'f.covers_transports', kind: 'multi', options: transportOptions },
    {
      name: 'allowed_windows',
      label: 'f.allowed_windows',
      kind: 'rows',
      columns: [
        { name: 'from', label: 'f.window_from', kind: 'time', required: true },
        { name: 'to', label: 'f.window_to', kind: 'time', required: true },
        { name: 'weekdays', label: 'f.weekdays', kind: 'multi', options: days, wide: true },
      ],
    },
    { name: 'conditions', label: 'f.conditions', kind: 'textarea' },
    { name: 'document_ref', label: 'f.document_ref', kind: 'text' },
  ];

  // The dialog leaves out the fields the server keeps once a permit is decided (409 permit_frozen); this says why.
  const frozen = frozenOf(resource.editing?.record).length > 0;

  return (
    <section className="space-y-3" data-testid="plan-permits">
      <PanelHead title="tab.permits" action="add_permit" may={resource.mayCreate} onAction={() => resource.open()} />
      <Loaded query={permits}>
        {(rows) =>
          rows.length === 0 ? (
            <PlanEmpty
              icon={<FileCheck2 size={28} />}
              title="empty.permits_title"
              body="empty.permits_body"
              action="add_permit"
              may={resource.mayCreate}
              onAction={() => resource.open()}
            />
          ) : (
            <ul className="space-y-2">
              {rows.map((p) => (
                <Card key={p.id} testId="plan-permit" alert={p.state === 'expired' || p.state === 'refused'}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-content-primary">
                      {codeLabel(words, 'permit_kinds', p.permit_kind, catalogue)}
                    </span>
                    {p.reference && <span className="font-mono text-xs text-content-tertiary">{p.reference}</span>}
                    <StateBadge state={p.state} />
                    <span className="ml-auto">
                      <RowActions resource={resource} record={p} lifecycle="permit" />
                    </span>
                  </div>
                  <dl className="mt-2 grid gap-3 sm:grid-cols-4">
                    <Fact label="f.authority">{p.authority}</Fact>
                    <Fact label="permit.validity">{span(t, day(p.valid_from), day(p.valid_to))}</Fact>
                    <Fact label="f.applied_on">{day(p.applied_on)}</Fact>
                    <Fact label="f.covers_transports">
                      {p.covers_transport_ids.length > 0 ? num(p.covers_transport_ids.length) : null}
                    </Fact>
                    <Fact label="permit.windows">
                      {p.allowed_windows.length === 0
                        ? tx(t, 'permit.any_time')
                        : p.allowed_windows.map((w, i) => (
                            <span key={i} className="block">
                              {fmtList((w.weekdays ?? []).map((d) => days[d]?.label ?? String(d)))}{' '}
                              {span(t, w.from, w.to)}
                            </span>
                          ))}
                    </Fact>
                    <Fact label="permit.conditions">{p.conditions}</Fact>
                  </dl>
                </Card>
              ))}
            </ul>
          )
        }
      </Loaded>
      {resource.editing && (
        <FormDialog
          title="edit_title.permit"
          fields={fields}
          note={frozen ? 'permit.frozen_note' : undefined}
          record={resource.editing.record}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={resource.save}
          onSaved={resource.saved}
          onClose={resource.close}
        />
      )}
    </section>
  );
}
