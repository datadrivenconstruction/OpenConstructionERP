// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The surroundings of the site: the noise limits and quiet hours that apply,
// the complaints that came in and when each must be answered, and the log of
// talks with the municipality, utilities and neighbours.

import { useMemo, useState } from 'react';
import { Handshake, Home, MessageSquareWarning } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';

import { putNeighbourhood, type Complaint, type CoordinationEntry, type Neighbourhood } from './api';
import { day, num, span } from './format';
import {
  useComplaints,
  useCoordination,
  useInvalidatePlan,
  useNeighbourhood,
  useResource,
  useTransports,
  useWords,
} from './hooks';
import { Card, Fact, FormDialog, Loaded, PanelHead, PlanEmpty, RowActions, StateBadge } from './PlanBits';
import { codeLabel, codeOptions, enumLabel, type Field } from './rules';
import type { PanelProps } from './SitePanels';
import { tx } from './texts';

const ZONES = ['residential', 'mixed', 'industrial'] as const;
const BODIES = ['municipality', 'utility', 'police', 'neighbours', 'authority', 'other'] as const;

/** The server answers the defaults with `id` null until the plan was saved once. */
function planIsEmpty(plan: Neighbourhood): boolean {
  return plan.id === null;
}

export function NeighbourhoodPanel({ projectId, catalogue }: PanelProps) {
  const words = useWords();
  const { t } = words;
  const plan = useNeighbourhood(projectId);
  const complaints = useComplaints(projectId);
  const coordination = useCoordination(projectId);
  const transports = useTransports(projectId);
  const invalidate = useInvalidatePlan(projectId);
  const complaintRes = useResource<Complaint>(projectId, 'complaint', { catalogue });
  const coordinationRes = useResource<CoordinationEntry>(projectId, 'coordination', { catalogue });
  const [editingPlan, setEditingPlan] = useState(false);

  const transportOptions = useMemo(
    () => (transports.data ?? []).map((x) => ({ value: x.id, label: x.title })),
    [transports.data],
  );

  const planFields: Field[] = [
    {
      name: 'zone_type',
      label: 'f.zone_type',
      kind: 'select',
      options: ZONES.map((v) => ({ value: v, label: enumLabel(t, 'zone_type', v) })),
    },
    {
      name: 'noise_limit_source',
      label: 'f.noise_limit_source',
      hint: 'f.noise_limit_source_hint',
      kind: 'select',
      options: codeOptions(words, 'noise_limits', catalogue),
    },
    { name: 'day_dba', label: 'f.day_dba', kind: 'decimal' },
    { name: 'night_dba', label: 'f.night_dba', kind: 'decimal' },
    { name: 'quiet_from', label: 'f.quiet_from', kind: 'time' },
    { name: 'quiet_to', label: 'f.quiet_to', kind: 'time' },
    { name: 'municipality_contact', label: 'f.municipality_contact', kind: 'text', wide: true },
    { name: 'parking_note', label: 'f.parking_note', kind: 'textarea' },
  ];
  const complaintFields: Field[] = [
    {
      name: 'kind',
      label: 'f.issue_kind',
      kind: 'select',
      required: true,
      options: codeOptions(words, 'neighbour_issue_kinds', catalogue),
    },
    { name: 'reported_on', label: 'f.reported_on', hint: 'f.date_default_hint', kind: 'date' },
    { name: 'reporter', label: 'f.reporter', kind: 'text' },
    { name: 'response_due', label: 'f.response_due', kind: 'date' },
    { name: 'description', label: 'f.description', kind: 'textarea', required: true },
    { name: 'owner_user_id', label: 'f.owner_user', kind: 'person' },
    { name: 'transport_id', label: 'f.transport', kind: 'select', options: transportOptions },
    { name: 'response', label: 'f.response', kind: 'textarea' },
  ];
  const coordinationFields: Field[] = [
    { name: 'entry_date', label: 'f.entry_date', hint: 'f.date_default_hint', kind: 'date' },
    {
      name: 'body',
      label: 'f.body',
      kind: 'select',
      required: true,
      options: BODIES.map((v) => ({ value: v, label: enumLabel(t, 'body', v) })),
    },
    { name: 'topic', label: 'f.topic', kind: 'text', required: true, wide: true },
    { name: 'outcome', label: 'f.outcome', kind: 'textarea' },
    { name: 'next_action_due', label: 'f.next_action_due', kind: 'date' },
  ];

  return (
    <section className="space-y-5" data-testid="plan-neighbourhood">
      <div className="space-y-3">
        <Loaded query={plan}>
          {(p) => (
            <>
              <PanelHead title="neighbourhood.plan">
                {!planIsEmpty(p) && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={p.can?.edit ? !p.can.edit.allowed : false}
                    onClick={() => setEditingPlan(true)}
                    data-testid="plan-edit-neighbourhood"
                  >
                    {tx(t, 'edit')}
                  </Button>
                )}
              </PanelHead>
              {planIsEmpty(p) ? (
                <PlanEmpty
                  icon={<Home size={28} />}
                  title="empty.neighbourhood_title"
                  body="empty.neighbourhood_body"
                  action="neighbourhood.write"
                  may={p.can?.edit}
                  onAction={() => setEditingPlan(true)}
                />
              ) : (
                <ul>
                  <Card testId="plan-neighbourhood-card">
                    <dl className="grid gap-3 sm:grid-cols-4">
                      <Fact label="f.zone_type">{p.zone_type ? enumLabel(t, 'zone_type', p.zone_type) : null}</Fact>
                      <Fact label="f.noise_limit_source">
                        {p.noise_limit_source ? codeLabel(words, 'noise_limits', p.noise_limit_source, catalogue) : null}
                      </Fact>
                      <Fact label="neighbourhood.day">
                        {p.day_dba ? tx(t, 'neighbourhood.dba', { value: num(p.day_dba) }) : null}
                      </Fact>
                      <Fact label="neighbourhood.night">
                        {p.night_dba ? tx(t, 'neighbourhood.dba', { value: num(p.night_dba) }) : null}
                      </Fact>
                      <Fact label="neighbourhood.quiet_hours">{span(t, p.quiet_hours[0] ?? null, p.quiet_hours[1] ?? null)}</Fact>
                      <Fact label="f.municipality_contact">{p.municipality_contact}</Fact>
                      <Fact label="f.parking_note">{p.parking_note}</Fact>
                    </dl>
                  </Card>
                </ul>
              )}
              {editingPlan && (
                <FormDialog
                  title="edit_title.neighbourhood"
                  fields={planFields}
                  record={planIsEmpty(p) ? null : { ...p, quiet_from: p.quiet_hours[0] ?? '', quiet_to: p.quiet_hours[1] ?? '' }}
                  defaults={p}
                  projectId={projectId}
                  catalogue={catalogue}
                  // The form holds the quiet hours as two times; the plan stores them as one pair.
                  shape={({ quiet_from, quiet_to, ...rest }, values) =>
                    quiet_from === undefined && quiet_to === undefined
                      ? rest
                      : {
                          ...rest,
                          quiet_hours: values.quiet_from && values.quiet_to ? [values.quiet_from, values.quiet_to] : null,
                        }
                  }
                  onSubmit={(body) => putNeighbourhood(projectId, body)}
                  onSaved={invalidate}
                  onClose={() => setEditingPlan(false)}
                />
              )}
            </>
          )}
        </Loaded>
      </div>

      <div className="space-y-3">
        <PanelHead title="neighbourhood.complaints" action="add_complaint" may={complaintRes.mayCreate} onAction={() => complaintRes.open()} />
        <Loaded query={complaints}>
          {(rows) =>
            rows.length === 0 ? (
              <PlanEmpty
                icon={<MessageSquareWarning size={28} />}
                title="empty.complaints_title"
                body="empty.complaints_body"
                action="add_complaint"
                may={complaintRes.mayCreate}
                onAction={() => complaintRes.open()}
              />
            ) : (
              <ul className="space-y-2">
                {rows.map((c) => (
                  <Card key={c.id} testId="plan-complaint" alert={c.overdue}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-content-primary">
                        {codeLabel(words, 'neighbour_issue_kinds', c.kind, catalogue)}
                      </span>
                      <StateBadge state={c.state} />
                      {c.overdue && (
                        <span data-testid="plan-complaint-overdue">
                          <Badge variant="error" size="sm">
                            {tx(t, 'neighbourhood.overdue')}
                          </Badge>
                        </span>
                      )}
                      {c.reported_on && (
                        <span className="text-xs text-content-secondary">
                          {tx(t, 'neighbourhood.reported', { date: day(c.reported_on) })}
                        </span>
                      )}
                      {c.response_due && c.state !== 'closed' && (
                        <span className="text-xs text-content-secondary">
                          {tx(t, 'neighbourhood.due', { date: day(c.response_due) })}
                        </span>
                      )}
                      <span className="ml-auto">
                        <RowActions resource={complaintRes} record={c} lifecycle="complaint" />
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-content-primary">{c.description}</p>
                    <dl className="mt-2 grid gap-3 sm:grid-cols-3">
                      <Fact label="f.reporter">{c.reporter}</Fact>
                      <Fact label="f.transport">{transportOptions.find((o) => o.value === c.transport_id)?.label}</Fact>
                      <Fact label="neighbourhood.response">{c.response}</Fact>
                    </dl>
                  </Card>
                ))}
              </ul>
            )
          }
        </Loaded>
      </div>

      <div className="space-y-3">
        <PanelHead title="neighbourhood.coordination" action="add_coordination" may={coordinationRes.mayCreate} onAction={() => coordinationRes.open()} />
        <Loaded query={coordination}>
          {(rows) =>
            rows.length === 0 ? (
              <PlanEmpty
                icon={<Handshake size={28} />}
                title="empty.coordination_title"
                body="empty.coordination_body"
                action="add_coordination"
                may={coordinationRes.mayCreate}
                onAction={() => coordinationRes.open()}
              />
            ) : (
              <ul className="space-y-2">
                {rows.map((e) => (
                  <Card key={e.id} testId="plan-coordination">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-content-primary">{e.topic}</span>
                      <Badge variant="neutral" size="sm">
                        {enumLabel(t, 'body', e.body)}
                      </Badge>
                      <span className="text-xs text-content-secondary">{day(e.entry_date)}</span>
                      {e.next_action_due && (
                        <span className="text-xs text-content-secondary">
                          {tx(t, 'neighbourhood.next_due', { date: day(e.next_action_due) })}
                        </span>
                      )}
                      <span className="ml-auto">
                        <RowActions resource={coordinationRes} record={e} />
                      </span>
                    </div>
                    <dl className="mt-2">
                      <Fact label="neighbourhood.outcome">{e.outcome}</Fact>
                    </dl>
                  </Card>
                ))}
              </ul>
            )
          }
        </Loaded>
      </div>

      {complaintRes.editing && (
        <FormDialog
          title="edit_title.complaint"
          fields={complaintFields}
          record={complaintRes.editing.record}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={complaintRes.save}
          onSaved={complaintRes.saved}
          onClose={complaintRes.close}
        />
      )}
      {coordinationRes.editing && (
        <FormDialog
          title="edit_title.coordination"
          fields={coordinationFields}
          record={coordinationRes.editing.record}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={coordinationRes.save}
          onSaved={coordinationRes.saved}
          onClose={coordinationRes.close}
        />
      )}
    </section>
  );
}
