// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Import and export cases with their goods lines and the documents the
// incoterm requires. Commercial values arrive only for a reader with the
// customs permission; for everyone else the server sends `values_hidden`.

import { useState } from 'react';
import { ChevronDown, ChevronRight, EyeOff, PackageSearch } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { fmtCurrency } from '@/shared/lib/formatters';

import type { CustomsCase, CustomsDocument, CustomsLine, PlanCatalogue } from './api';
import { day, withUnit } from './format';
import { useCustoms, useDocuments, useLines, useResource, useWords } from './hooks';
import { Card, Fact, FormDialog, Loaded, PanelHead, PlanEmpty, RowActions, StateBadge } from './PlanBits';
import { codeLabel, codeOptions, enumLabel, type Field, denied } from './rules';
import type { PanelProps } from './SitePanels';
import { tx } from './texts';

const MODES = ['road', 'rail', 'sea', 'inland_waterway', 'air', 'multimodal'] as const;

function CaseDetails({ projectId, record, catalogue }: { projectId: string; record: CustomsCase; catalogue: PlanCatalogue | null }) {
  const words = useWords();
  const { t } = words;
  const lines = useLines(projectId, record.id);
  const documents = useDocuments(projectId, record.id);
  const lineRes = useResource<CustomsLine>(projectId, 'line', { parentId: record.id, catalogue });
  const docRes = useResource<CustomsDocument>(projectId, 'document', { parentId: record.id, catalogue, moveByPatch: true });

  const lineFields: Field[] = [
    { name: 'description', label: 'f.description', kind: 'text', required: true, wide: true },
    { name: 'hs_code', label: 'f.hs_code', kind: 'text', required: true },
    { name: 'origin_country', label: 'f.country_of_origin', hint: 'f.country_hint', kind: 'text' },
    { name: 'quantity', label: 'f.quantity', kind: 'decimal' },
    { name: 'unit', label: 'f.unit', kind: 'text' },
    { name: 'net_mass_kg', label: 'f.net_mass_kg', kind: 'decimal' },
    // A reader who may not see values may not write them either; the field is left out.
    ...(record.values_hidden
      ? []
      : ([
          { name: 'value', label: 'f.value', kind: 'decimal' },
          // The server refuses a value that names no currency.
          { name: 'currency', label: 'f.currency', hint: 'f.currency_hint', kind: 'text' },
        ] as Field[])),
    { name: 'preferential_origin', label: 'f.preferential_origin', kind: 'checkbox' },
  ];
  // A listed document only takes a reference; a new one only says which document it is.
  const docFields: Field[] = docRes.editing?.record
    ? [{ name: 'document_ref', label: 'f.document_ref', kind: 'text', wide: true }]
    : [
        {
          name: 'kind',
          label: 'f.document_kind',
          kind: 'select',
          required: true,
          wide: true,
          options: codeOptions(words, 'customs_document_kinds', catalogue),
        },
      ];

  return (
    <div className="mt-3 grid gap-4 border-t border-border-light pt-3 lg:grid-cols-2" data-testid="plan-customs-details">
      <div>
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">{tx(t, 'customs.lines')}</h4>
          <Button size="sm" variant="secondary" disabled={denied(lineRes.mayCreate) || denied(record.can?.add_line)} onClick={() => lineRes.open()} data-testid="plan-add-line">
            {tx(t, 'add_line')}
          </Button>
        </div>
        <Loaded query={lines}>
          {(rows) =>
            rows.length === 0 ? (
              <p className="mt-1 text-xs text-content-tertiary">{tx(t, 'empty.lines')}</p>
            ) : (
              <ul className="mt-1 divide-y divide-border-light">
                {rows.map((l) => (
                  <li key={l.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm" data-testid="plan-line">
                    <span className="font-mono text-xs text-content-secondary">{l.hs_code}</span>
                    <span className="text-content-primary">{l.description}</span>
                    <span className="text-content-secondary">{withUnit(t, l.quantity, l.unit)}</span>
                    {l.value !== null && (
                      <span className="tabular-nums text-content-secondary">{fmtCurrency(l.value, l.currency ?? record.currency)}</span>
                    )}
                    {l.origin_country && <span className="text-xs text-content-tertiary">{l.origin_country}</span>}
                    {l.preferential_origin && (
                      <Badge variant="blue" size="sm">
                        {tx(t, 'customs.preferential')}
                      </Badge>
                    )}
                    <span className="ml-auto">
                      <RowActions resource={lineRes} record={l} />
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        </Loaded>
      </div>
      <div>
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {tx(t, 'customs.documents')}
          </h4>
          <Button size="sm" variant="secondary" disabled={denied(docRes.mayCreate) || denied(record.can?.add_document)} onClick={() => docRes.open()} data-testid="plan-add-document">
            {tx(t, 'add_document')}
          </Button>
        </div>
        <Loaded query={documents}>
          {(rows) =>
            rows.length === 0 ? (
              <p className="mt-1 text-xs text-content-tertiary">{tx(t, 'empty.documents')}</p>
            ) : (
              <ul className="mt-1 divide-y divide-border-light">
                {rows.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm" data-testid="plan-document">
                    <span className="text-content-primary">
                      {codeLabel(words, 'customs_document_kinds', d.kind, catalogue)}
                    </span>
                    <span className="text-xs text-content-tertiary">
                      {tx(t, d.required ? 'customs.required' : 'customs.optional')}
                    </span>
                    {d.document_ref && <span className="font-mono text-xs text-content-secondary">{d.document_ref}</span>}
                    <StateBadge state={d.state} />
                    <span className="ml-auto">
                      <RowActions resource={docRes} record={d} lifecycle="document" noDelete />
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        </Loaded>
      </div>
      {lineRes.editing && (
        <FormDialog
          title="edit_title.line"
          fields={lineFields}
          record={lineRes.editing.record}
          defaults={record.currency ? { currency: record.currency } : undefined}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={lineRes.save}
          onSaved={lineRes.saved}
          onClose={lineRes.close}
        />
      )}
      {docRes.editing && (
        <FormDialog
          title="edit_title.document"
          fields={docFields}
          record={docRes.editing.record}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={docRes.save}
          onSaved={docRes.saved}
          onClose={docRes.close}
        />
      )}
    </div>
  );
}

export function CustomsPanel({ projectId, catalogue }: PanelProps) {
  const words = useWords();
  const { t } = words;
  const cases = useCustoms(projectId);
  const resource = useResource<CustomsCase>(projectId, 'customs', { catalogue });
  const [openId, setOpenId] = useState<string | null>(null);
  const valuesHidden = (cases.data ?? []).some((c) => c.values_hidden);

  const fields: Field[] = [
    { name: 'title', label: 'f.title', kind: 'text', required: true, wide: true },
    { name: 'po_id', label: 'f.purchase_order', kind: 'link', link: 'purchase_order' },
    {
      name: 'direction',
      label: 'f.direction',
      kind: 'select',
      required: true,
      options: ['import', 'export'].map((v) => ({ value: v, label: enumLabel(t, 'direction', v) })),
    },
    {
      name: 'incoterm',
      label: 'f.incoterm',
      kind: 'select',
      required: true,
      options: (catalogue?.incoterms ?? []).map((i) => ({ value: i.code, label: i.code })),
    },
    { name: 'named_place', label: 'f.named_place', kind: 'text' },
    {
      name: 'transport_mode',
      label: 'f.transport_mode',
      kind: 'select',
      options: MODES.map((v) => ({ value: v, label: enumLabel(t, 'transport_mode', v) })),
    },
    { name: 'country_of_origin', label: 'f.country_of_origin', hint: 'f.country_hint', kind: 'text' },
    { name: 'country_of_destination', label: 'f.country_of_destination', hint: 'f.country_hint', kind: 'text' },
    {
      name: 'declarant_party',
      label: 'f.declarant_party',
      kind: 'select',
      options: ['buyer', 'seller'].map((v) => ({ value: v, label: enumLabel(t, 'declarant', v) })),
    },
    { name: 'broker_name', label: 'f.broker_name', kind: 'text' },
    ...(valuesHidden
      ? []
      : ([
          { name: 'customs_value', label: 'f.customs_value', kind: 'decimal' },
          { name: 'currency', label: 'f.currency', hint: 'f.currency_hint', kind: 'text' },
        ] as Field[])),
    { name: 'declaration_ref', label: 'f.declaration_ref', kind: 'text' },
    { name: 'cleared_on', label: 'f.cleared_on', kind: 'date' },
  ];

  return (
    <section className="space-y-3" data-testid="plan-customs">
      <PanelHead title="tab.customs" action="add_customs" may={resource.mayCreate} onAction={() => resource.open()} />
      {valuesHidden && (
        <p className="flex items-center gap-1.5 text-xs text-content-secondary" data-testid="plan-values-hidden">
          <EyeOff size={13} aria-hidden />
          {tx(t, 'customs.values_hidden')}
        </p>
      )}
      <Loaded query={cases}>
        {(rows) =>
          rows.length === 0 ? (
            <PlanEmpty
              icon={<PackageSearch size={28} />}
              title="empty.customs_title"
              body="empty.customs_body"
              action="add_customs"
              may={resource.mayCreate}
              onAction={() => resource.open()}
            />
          ) : (
            <ul className="space-y-2">
              {rows.map((c) => {
                const open = openId === c.id;
                return (
                  <Card key={c.id} testId="plan-customs-case">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-sm font-semibold text-content-primary"
                        aria-expanded={open}
                        title={tx(t, open ? 'hide_details' : 'show_details')}
                        onClick={() => setOpenId(open ? null : c.id)}
                        data-testid="plan-customs-toggle"
                      >
                        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
                        {c.title || c.incoterm}
                      </button>
                      <Badge variant="neutral" size="sm">
                        {enumLabel(t, 'direction', c.direction)}
                      </Badge>
                      <span className="font-mono text-xs text-content-secondary">{c.incoterm}</span>
                      {c.named_place && <span className="text-xs text-content-secondary">{c.named_place}</span>}
                      <StateBadge state={c.state} />
                      <span className="ml-auto">
                        <RowActions resource={resource} record={c} lifecycle="customs" />
                      </span>
                    </div>
                    <dl className="mt-2 grid gap-3 sm:grid-cols-4">
                      <Fact label="transport.route">
                        {c.country_of_origin && c.country_of_destination
                          ? tx(t, 'customs.route', { origin: c.country_of_origin, destination: c.country_of_destination })
                          : null}
                      </Fact>
                      <Fact label="f.transport_mode">{c.transport_mode ? enumLabel(t, 'transport_mode', c.transport_mode) : null}</Fact>
                      <Fact label="f.declarant_party">{c.declarant_party ? enumLabel(t, 'declarant', c.declarant_party) : null}</Fact>
                      <Fact label="f.broker_name">{c.broker_name}</Fact>
                      <Fact label="customs.value">
                        {c.values_hidden || c.customs_value === null ? null : (
                          <span className="tabular-nums">{fmtCurrency(c.customs_value, c.currency)}</span>
                        )}
                      </Fact>
                      <Fact label="f.declaration_ref">{c.declaration_ref}</Fact>
                      <Fact label="f.cleared_on">{day(c.cleared_on)}</Fact>
                    </dl>
                    {open && <CaseDetails projectId={projectId} record={c} catalogue={catalogue} />}
                  </Card>
                );
              })}
            </ul>
          )
        }
      </Loaded>
      {resource.editing && (
        <FormDialog
          title="edit_title.customs"
          fields={fields}
          record={resource.editing.record}
          defaults={{ direction: 'import' }}
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
