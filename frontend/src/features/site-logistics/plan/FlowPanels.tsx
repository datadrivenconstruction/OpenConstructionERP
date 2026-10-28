// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the site draws and how material reaches it: utility connections with
// their consumers, and the logistics concept with its delivery hours and
// material flows.

import { useMemo, useState } from 'react';
import { AlertTriangle, ClipboardList, Plug } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';

import { putConcept, type Concept, type MediaConnection, type MediaDemand, type PlanCatalogue } from './api';
import { day, num, span, withUnit } from './format';
import {
  useAreas,
  useConcept,
  useDemands,
  useInvalidatePlan,
  useMedia,
  useResource,
  useStages,
  useWords,
} from './hooks';
import { Card, Fact, FormDialog, Loaded, PanelHead, PlanEmpty, RowActions, StateBadge } from './PlanBits';
import { codeLabel, codeOptions, enumLabel, type Field, type Option, denied } from './rules';
import { stageName, type PanelProps } from './SitePanels';
import { tx, type TFn } from './texts';

function enumOptions(t: TFn, group: string, values: readonly string[]): Option[] {
  return values.map((value) => ({ value, label: enumLabel(t, group, value) }));
}

/* ── Utilities ────────────────────────────────────────────────────────── */

function Demands({
  projectId,
  media,
  catalogue,
  stageOptions,
}: {
  projectId: string;
  media: MediaConnection;
  catalogue: PlanCatalogue | null;
  stageOptions: Option[];
}) {
  const { t } = useWords();
  const demands = useDemands(projectId, media.id);
  const resource = useResource<MediaDemand>(projectId, 'demand', { parentId: media.id, catalogue });
  const fields: Field[] = [
    { name: 'consumer', label: 'f.consumer', kind: 'text', required: true },
    { name: 'stage_id', label: 'f.stage', kind: 'select', options: stageOptions, required: true },
    { name: 'peak_demand', label: 'f.peak_demand', kind: 'decimal', required: true },
    { name: 'simultaneity_factor', label: 'f.simultaneity_factor', hint: 'f.simultaneity_factor_hint', kind: 'decimal' },
  ];
  return (
    <div className="mt-3 border-t border-border-light pt-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">{tx(t, 'media.demands')}</h4>
        <Button size="sm" variant="secondary" disabled={denied(resource.mayCreate)} onClick={() => resource.open()} data-testid="plan-add-demand">
          {tx(t, 'add_demand')}
        </Button>
      </div>
      <Loaded query={demands}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="mt-1 text-xs text-content-tertiary">{tx(t, 'empty.demands')}</p>
          ) : (
            <ul className="mt-1 divide-y divide-border-light">
              {rows.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-1.5 text-sm" data-testid="plan-demand">
                  <span className="font-medium text-content-primary">{d.consumer}</span>
                  <span className="text-xs text-content-secondary">
                    {stageOptions.find((o) => o.value === d.stage_id)?.label}
                  </span>
                  <span className="text-content-secondary">
                    {tx(t, 'media.peak')} {withUnit(t, d.peak_demand, media.capacity_unit)}
                  </span>
                  <span className="text-content-secondary">
                    {tx(t, 'media.factor')} {num(d.simultaneity_factor)}
                  </span>
                  {d.from_plant_position && (
                    <span title={tx(t, 'media.from_plant_hint')} data-testid="plan-demand-from-plant">
                      <Badge variant="blue" size="sm">
                        {tx(t, 'media.from_plant')}
                      </Badge>
                    </span>
                  )}
                  <span className="ml-auto">
                    {/* A demand owned by a plant position is changed on the site plan; the server refuses it here. */}
                    <RowActions resource={resource} record={d} noEdit={d.from_plant_position} noDelete={d.from_plant_position} />
                  </span>
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
      {resource.editing && (
        <FormDialog
          title="edit_title.demand"
          fields={fields}
          record={resource.editing.record}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={resource.save}
          onSaved={resource.saved}
          onClose={resource.close}
        />
      )}
    </div>
  );
}

export function UtilitiesPanel({ projectId, catalogue }: PanelProps) {
  const words = useWords();
  const { t } = words;
  const media = useMedia(projectId);
  const stages = useStages(projectId);
  const resource = useResource<MediaConnection>(projectId, 'media', { catalogue });
  const stageOptions = useMemo(
    () => (stages.data ?? []).map((s) => ({ value: s.id, label: stageName(s) })),
    [stages.data],
  );
  const fields: Field[] = [
    { name: 'media_kind', label: 'f.media_kind', kind: 'select', options: codeOptions(words, 'media_kinds', catalogue), required: true },
    { name: 'phase', label: 'f.phase', kind: 'select', options: enumOptions(t, 'phase', ['construction', 'operation', 'both']) },
    { name: 'provider_name', label: 'f.provider_name', kind: 'text' },
    { name: 'capacity_unit', label: 'f.capacity_unit', kind: 'text' },
    { name: 'available_capacity', label: 'f.available_capacity', kind: 'decimal' },
    { name: 'contracted_capacity', label: 'f.contracted_capacity', kind: 'decimal' },
    { name: 'connection_point', label: 'f.connection_point', kind: 'textarea' },
    { name: 'application_ref', label: 'f.application_ref', kind: 'text' },
    { name: 'applied_on', label: 'f.applied_on', kind: 'date' },
    { name: 'promised_on', label: 'f.promised_on', kind: 'date' },
    { name: 'connected_on', label: 'f.connected_on', kind: 'date' },
    { name: 'document_ref', label: 'f.document_ref', kind: 'text' },
  ];
  return (
    <section className="space-y-3" data-testid="plan-media">
      <PanelHead title="tab.media" action="add_media" may={resource.mayCreate} onAction={() => resource.open()} />
      <Loaded query={media}>
        {(rows) =>
          rows.length === 0 ? (
            <PlanEmpty
              icon={<Plug size={28} />}
              title="empty.media_title"
              body="empty.media_body"
              action="add_media"
              may={resource.mayCreate}
              onAction={() => resource.open()}
            />
          ) : (
            <ul className="space-y-2">
              {rows.map((m) => (
                <Card key={m.id} testId="plan-media-row">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-content-primary">
                      {codeLabel(words, 'media_kinds', m.media_kind, catalogue)}
                    </span>
                    {m.provider_name && <span className="text-sm text-content-secondary">{m.provider_name}</span>}
                    <StateBadge state={m.state} />
                    <span className="ml-auto">
                      <RowActions resource={resource} record={m} lifecycle="media" />
                    </span>
                  </div>
                  <dl className="mt-2 grid gap-3 sm:grid-cols-4">
                    <Fact label="media.available">{withUnit(t, m.available_capacity, m.capacity_unit)}</Fact>
                    <Fact label="media.contracted">{withUnit(t, m.contracted_capacity, m.capacity_unit)}</Fact>
                    <Fact label="f.phase">{enumLabel(t, 'phase', m.phase)}</Fact>
                    <Fact label="f.promised_on">{day(m.promised_on)}</Fact>
                    <Fact label="f.applied_on">{day(m.applied_on)}</Fact>
                    <Fact label="f.connected_on">{day(m.connected_on)}</Fact>
                    <Fact label="f.connection_point">{m.connection_point}</Fact>
                    <Fact label="f.application_ref">{m.application_ref}</Fact>
                  </dl>
                  <Demands projectId={projectId} media={m} catalogue={catalogue} stageOptions={stageOptions} />
                </Card>
              ))}
            </ul>
          )
        }
      </Loaded>
      {resource.editing && (
        <FormDialog
          title="edit_title.media"
          fields={fields}
          record={resource.editing.record}
          defaults={{ phase: 'construction' }}
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

/* ── Concept ──────────────────────────────────────────────────────────── */

const FLOW_MODES = ['stock', 'just_in_time', 'kanban', 'direct_install'] as const;

function conceptIsEmpty(c: Concept): boolean {
  return c.strategy.length === 0 && !c.rules_text.trim() && !c.delivery_open && !c.delivery_close && !c.site_timezone;
}

export function ConceptPanel({ projectId, catalogue }: PanelProps) {
  const { t } = useWords();
  const concept = useConcept(projectId);
  const areas = useAreas(projectId);
  const invalidate = useInvalidatePlan(projectId);
  const [editing, setEditing] = useState(false);
  const areaOptions = useMemo(
    () => (areas.data ?? []).map((a) => ({ value: a.id, label: a.name || a.code })),
    [areas.data],
  );
  const fields: Field[] = [
    { name: 'site_timezone', label: 'f.site_timezone', hint: 'f.site_timezone_hint', kind: 'text', wide: true },
    { name: 'delivery_open', label: 'f.delivery_open', kind: 'time' },
    { name: 'delivery_close', label: 'f.delivery_close', kind: 'time' },
    { name: 'max_deliveries_per_hour', label: 'f.max_deliveries_per_hour', kind: 'int' },
    { name: 'document_ref', label: 'f.document_ref', kind: 'text' },
    { name: 'rules_text', label: 'f.rules_text', kind: 'textarea' },
    {
      name: 'strategy',
      label: 'f.strategy',
      kind: 'rows',
      columns: [
        { name: 'flow_code', label: 'f.flow_code', kind: 'text', required: true },
        { name: 'mode', label: 'f.mode', kind: 'select', options: enumOptions(t, 'flow_mode', FLOW_MODES), required: true },
        { name: 'storage_area_id', label: 'f.storage_area', kind: 'select', options: areaOptions },
        { name: 'buffer_days', label: 'f.buffer_days', kind: 'int' },
        { name: 'takt_schedule_id', label: 'f.takt_schedule', kind: 'link', link: 'takt_schedule' },
        { name: 'description', label: 'f.description', kind: 'text', wide: true },
      ],
    },
  ];
  return (
    <section className="space-y-3" data-testid="plan-concept">
      <Loaded query={concept}>
        {(c) => (
          <>
            <PanelHead title="tab.concept">
              {!conceptIsEmpty(c) && (
                <Button size="sm" disabled={denied(c.can?.edit)} onClick={() => setEditing(true)} data-testid="plan-edit-concept">
                  {tx(t, 'edit')}
                </Button>
              )}
            </PanelHead>
            {!c.site_timezone && (
              <div
                role="status"
                className="flex flex-wrap items-center gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning/5 p-3 text-sm text-content-primary"
                data-testid="plan-timezone-missing"
              >
                <AlertTriangle size={15} className="shrink-0 text-semantic-warning" aria-hidden />
                <span className="flex-1">{tx(t, 'concept.timezone_missing')}</span>
                <Button size="sm" variant="secondary" disabled={denied(c.can?.edit)} onClick={() => setEditing(true)}>
                  {tx(t, 'concept.set_timezone')}
                </Button>
              </div>
            )}
            {conceptIsEmpty(c) ? (
              <PlanEmpty
                icon={<ClipboardList size={28} />}
                title="empty.concept_title"
                body="empty.concept_body"
                action="concept.write"
                may={c.can?.edit}
                onAction={() => setEditing(true)}
              />
            ) : (
              <ul className="space-y-2">
                <Card testId="plan-concept-card">
                  <dl className="grid gap-3 sm:grid-cols-3">
                    <Fact label="concept.timezone">{c.site_timezone}</Fact>
                    <Fact label="concept.hours">{span(t, c.delivery_open, c.delivery_close)}</Fact>
                    <Fact label="concept.max_per_hour">{num(c.max_deliveries_per_hour)}</Fact>
                    <Fact label="concept.filed_as">{c.document_ref || tx(t, 'concept.not_filed')}</Fact>
                  </dl>
                  {c.rules_text && (
                    <div className="mt-3">
                      <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                        {tx(t, 'concept.rules')}
                      </h4>
                      <p className="mt-1 whitespace-pre-line text-sm text-content-primary">{c.rules_text}</p>
                    </div>
                  )}
                  {c.strategy.length > 0 && (
                    <div className="mt-3">
                      <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                        {tx(t, 'concept.flows')}
                      </h4>
                      <ul className="mt-1 divide-y divide-border-light">
                        {c.strategy.map((f) => (
                          <li key={f.flow_code} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-1.5 text-sm" data-testid="plan-flow">
                            <span className="font-medium text-content-primary">{f.flow_code}</span>
                            <Badge variant="neutral" size="sm">
                              {enumLabel(t, 'flow_mode', f.mode)}
                            </Badge>
                            {f.storage_area_id && (
                              <span className="text-content-secondary">
                                {areaOptions.find((o) => o.value === f.storage_area_id)?.label}
                              </span>
                            )}
                            {f.buffer_days > 0 && (
                              <span className="text-content-secondary">{tx(t, 'concept.buffer', { n: f.buffer_days })}</span>
                            )}
                            {f.description && <span className="text-content-secondary">{f.description}</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </Card>
              </ul>
            )}
            {editing && (
              <FormDialog
                title="edit_title.concept"
                fields={fields}
                record={c.id ? c : null}
                defaults={c}
                projectId={projectId}
                catalogue={catalogue}
                onSubmit={(body) => putConcept(projectId, body)}
                onSaved={invalidate}
                onClose={() => setEditing(false)}
              />
            )}
          </>
        )}
      </Loaded>
    </section>
  );
}
