// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The site over time: expansion stages, the areas of the site with their use
// per stage, and the balance that shows whether each stage adds up.

import { useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Layers, Map as MapIcon, Scale } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';

import { putAllocations, type PlanCatalogue, type SiteArea, type Stage, type StageBalance } from './api';
import { day, m2, num, span, withUnit } from './format';
import { useAreas, useBalance, useInvalidatePlan, useResource, useStages, useWords } from './hooks';
import { Card, Fact, FormDialog, Loaded, PanelHead, PlanEmpty, RowActions, StateBadge } from './PlanBits';
import { codeLabel, codeOptions, enumLabel, findingText, type Field } from './rules';
import { tx } from './texts';

export interface PanelProps {
  projectId: string;
  catalogue: PlanCatalogue | null;
}

export function stageName(stage: Pick<Stage, 'title' | 'code'>): string {
  return stage.title || stage.code;
}

/* ── Stages ───────────────────────────────────────────────────────────── */

const STAGE_FIELDS: Field[] = [
  { name: 'title', label: 'f.title', kind: 'text', required: true },
  { name: 'code', label: 'f.code', hint: 'f.code_hint', kind: 'text', required: true },
  { name: 'from_date', label: 'f.from_date', kind: 'date' },
  { name: 'to_date', label: 'f.to_date', kind: 'date' },
  { name: 'from_activity_id', label: 'f.from_activity', kind: 'link', link: 'activity' },
  { name: 'to_activity_id', label: 'f.to_activity', kind: 'link', link: 'activity' },
  { name: 'ordinal', label: 'f.ordinal', kind: 'int' },
];

export function StagesPanel({ projectId, catalogue }: PanelProps) {
  const { t } = useWords();
  const stages = useStages(projectId);
  const resource = useResource<Stage>(projectId, 'stage', { catalogue });
  return (
    <section className="space-y-3" data-testid="plan-stages">
      <PanelHead title="tab.stages" action="add_stage" may={resource.mayCreate} onAction={() => resource.open()} />
      <Loaded query={stages}>
        {(rows) =>
          rows.length === 0 ? (
            <PlanEmpty
              icon={<Layers size={28} />}
              title="empty.stages_title"
              body="empty.stages_body"
              action="add_stage"
              may={resource.mayCreate}
              onAction={() => resource.open()}
            />
          ) : (
            <ul className="space-y-2">
              {rows.map((s) => (
                <Card key={s.id} testId="plan-stage">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-content-primary">{stageName(s)}</span>
                    <span className="font-mono text-xs text-content-tertiary">{s.code}</span>
                    <StateBadge state={s.state} />
                    <span className="ml-auto">
                      <RowActions resource={resource} record={s} lifecycle="stage" />
                    </span>
                  </div>
                  <dl className="mt-2 grid gap-3 sm:grid-cols-3">
                    <Fact label="stage.period">{span(t, day(s.start), day(s.end))}</Fact>
                  </dl>
                </Card>
              ))}
            </ul>
          )
        }
      </Loaded>
      {resource.editing && (
        <FormDialog
          title="edit_title.stage"
          fields={STAGE_FIELDS}
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

/* ── Areas ────────────────────────────────────────────────────────────── */

export function AreasPanel({ projectId, catalogue }: PanelProps) {
  const words = useWords();
  const { t } = words;
  const areas = useAreas(projectId);
  const stages = useStages(projectId);
  const resource = useResource<SiteArea>(projectId, 'area', { catalogue });
  const invalidate = useInvalidatePlan(projectId);
  const [allocating, setAllocating] = useState<SiteArea | null>(null);

  const kinds = useMemo(() => codeOptions(words, 'area_kinds', catalogue), [words, catalogue]);
  const stageOptions = useMemo(
    () => (stages.data ?? []).map((s) => ({ value: s.id, label: stageName(s) })),
    [stages.data],
  );
  const stageOf = (id: string) => stageOptions.find((o) => o.value === id)?.label ?? '';

  const areaFields: Field[] = [
    { name: 'name', label: 'f.name', kind: 'text', required: true },
    { name: 'code', label: 'f.code', hint: 'f.code_hint', kind: 'text', required: true },
    { name: 'area_kind', label: 'f.area_kind', kind: 'select', options: kinds, required: true },
    { name: 'area_m2_declared', label: 'f.area_m2_declared', hint: 'f.area_m2_declared_hint', kind: 'decimal' },
    { name: 'owner_party', label: 'f.owner_party', kind: 'text' },
    { name: 'takt_location_id', label: 'f.takt_location', kind: 'link', link: 'takt_location' },
  ];
  const allocationFields: Field[] = [
    {
      name: 'items',
      label: 'area.allocations',
      kind: 'rows',
      columns: [
        { name: 'stage_id', label: 'f.stage', kind: 'select', options: stageOptions, required: true },
        { name: 'area_kind', label: 'f.area_kind', kind: 'select', options: kinds },
        { name: 'allocated_m2', label: 'f.allocated_m2', kind: 'decimal' },
        { name: 'use_note', label: 'f.use_note', kind: 'text', wide: true },
      ],
    },
  ];

  return (
    <section className="space-y-3" data-testid="plan-areas">
      <PanelHead title="tab.areas" action="add_area" may={resource.mayCreate} onAction={() => resource.open()} />
      <Loaded query={areas}>
        {(rows) =>
          rows.length === 0 ? (
            <PlanEmpty
              icon={<MapIcon size={28} />}
              title="empty.areas_title"
              body="empty.areas_body"
              action="add_area"
              may={resource.mayCreate}
              onAction={() => resource.open()}
            />
          ) : (
            <ul className="space-y-2">
              {rows.map((a) => (
                <Card key={a.id} testId="plan-area">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-content-primary">{a.name || a.code}</span>
                    <span className="font-mono text-xs text-content-tertiary">{a.code}</span>
                    <Badge variant="neutral" size="sm">
                      {codeLabel(words, 'area_kinds', a.area_kind, catalogue)}
                    </Badge>
                    <span className="ml-auto flex items-center gap-1.5">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={a.can?.edit ? !a.can.edit.allowed : false}
                        onClick={() => setAllocating(a)}
                        data-testid="plan-allocate"
                      >
                        {tx(t, 'area.allocate')}
                      </Button>
                      <RowActions resource={resource} record={a} />
                    </span>
                  </div>
                  <dl className="mt-2 grid gap-3 sm:grid-cols-3">
                    <Fact label="area.size">
                      {m2(t, a.effective_m2)}
                      {a.effective_m2 && (
                        <span className="ml-2 text-xs text-content-tertiary">
                          {tx(t, a.area_m2 ? 'area.measured' : 'area.declared')}
                        </span>
                      )}
                    </Fact>
                    <Fact label="f.owner_party">{a.owner_party}</Fact>
                  </dl>
                  {a.allocations.length === 0 ? (
                    <p className="mt-2 text-xs text-content-tertiary">{tx(t, 'area.no_allocations')}</p>
                  ) : (
                    <ul className="mt-2 flex flex-wrap gap-2" aria-label={tx(t, 'area.allocations')}>
                      {a.allocations.map((x) => (
                        <li key={x.id} className="rounded-md bg-surface-secondary px-2 py-1 text-xs text-content-secondary">
                          <span className="font-medium text-content-primary">{stageOf(x.stage_id)}</span>{' '}
                          {m2(t, x.allocated_m2)}
                          {x.area_kind !== a.area_kind && <> · {codeLabel(words, 'area_kinds', x.area_kind, catalogue)}</>}
                          {x.use_note && <> · {x.use_note}</>}
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              ))}
            </ul>
          )
        }
      </Loaded>
      {resource.editing && (
        <FormDialog
          title="edit_title.area"
          fields={areaFields}
          record={resource.editing.record}
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={resource.save}
          onSaved={resource.saved}
          onClose={resource.close}
        />
      )}
      {allocating && (
        <FormDialog
          title="edit_title.allocations"
          fields={allocationFields}
          record={{ items: allocating.allocations }}
          sendAll
          projectId={projectId}
          catalogue={catalogue}
          onSubmit={(body) => putAllocations(projectId, allocating.id, (body.items as Record<string, unknown>[]) ?? [])}
          onSaved={invalidate}
          onClose={() => setAllocating(null)}
        />
      )}
    </section>
  );
}

/* ── Balance ──────────────────────────────────────────────────────────── */

function Warning({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-1.5 text-sm text-semantic-error" data-testid="plan-balance-warning">
      <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

function StageBalanceCard({ row, catalogue }: { row: StageBalance; catalogue: PlanCatalogue | null }) {
  const words = useWords();
  const { t } = words;
  const { area } = row;
  const noTotal = Number(area.site_total_m2) === 0;
  return (
    <Card testId="plan-balance-stage" alert={!area.closed}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-content-primary">{stageName(row.stage)}</span>
        <StateBadge state={row.stage.state} />
        <span className="ml-auto" data-testid="plan-balance-verdict" data-closed={area.closed}>
          <Badge variant={area.closed ? 'success' : 'error'} size="sm">
            {area.closed ? (
              <>
                <CheckCircle2 size={12} className="mr-1 inline" aria-hidden />
                {tx(t, 'balance.closed')}
              </>
            ) : (
              tx(t, 'balance.open', { difference: num(area.difference_m2) ?? '' })
            )}
          </Badge>
        </span>
      </div>
      <dl className="mt-2 grid gap-3 sm:grid-cols-4">
        <Fact label="balance.site_total">{m2(t, area.site_total_m2)}</Fact>
        <Fact label="balance.counted">{m2(t, area.counted_m2)}</Fact>
        <Fact label="balance.difference">{m2(t, area.difference_m2)}</Fact>
        <Fact label="balance.by_group">
          {Object.entries(area.by_group).map(([group, value]) => (
            <span key={group} className="mr-3 inline-block text-xs text-content-secondary">
              {enumLabel(t, 'group', group)} {m2(t, value)}
            </span>
          ))}
        </Fact>
      </dl>
      <p className="mt-1 text-xs text-content-tertiary">{tx(t, 'balance.tolerance', { pct: row.tolerance_pct })}</p>
      <div className="mt-2 space-y-1">
        {noTotal && <Warning>{tx(t, 'balance.no_site_total')}</Warning>}
        {row.overlaps.length > 0 && <Warning>{tx(t, 'balance.overlaps')}</Warning>}
        {row.exceeding.length > 0 && <Warning>{tx(t, 'balance.exceeding')}</Warning>}
        {row.gaps.map((gap) => (
          <Warning key={gap}>{findingText(words, { code: gap, params: { stage: stageName(row.stage) } }, catalogue)}</Warning>
        ))}
      </div>
      {row.media.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {tx(t, 'balance.utilities')}
          </h4>
          <ul className="mt-1 space-y-1">
            {row.media.map((m) => (
              <li key={m.media_kind} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" data-testid="plan-balance-media">
                <span className="w-32 font-medium text-content-primary">
                  {codeLabel(words, 'media_kinds', m.media_kind, catalogue)}
                </span>
                <span className="text-content-secondary">
                  {tx(t, 'balance.required')} {withUnit(t, m.required, m.capacity_unit)}
                </span>
                <span className="text-content-secondary">
                  {tx(t, 'balance.contracted')} {withUnit(t, m.contracted, m.capacity_unit)}
                </span>
                <Badge variant={m.short ? 'error' : 'success'} size="sm">
                  {tx(t, m.short ? 'balance.short' : 'balance.enough')}
                </Badge>
                {m.unsourced.length > 0 && (
                  <span className="text-xs text-semantic-error">{tx(t, 'balance.unsourced', { n: m.unsourced.length })}</span>
                )}
                {m.late.length > 0 && <span className="text-xs text-semantic-error">{tx(t, 'balance.late')}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-content-tertiary">
            {tx(t, 'balance.reserve', { pct: row.media[0]?.reserve_pct ?? '' })}
          </p>
        </div>
      )}
    </Card>
  );
}

export function BalancePanel({ projectId, catalogue, onGoTo }: PanelProps & { onGoTo: (tab: 'areas') => void }) {
  const balance = useBalance(projectId);
  return (
    <section className="space-y-3" data-testid="plan-balance">
      <PanelHead title="tab.balance" />
      <Loaded query={balance}>
        {(rows) =>
          rows.every((r) => Number(r.area.counted_m2) === 0 && Number(r.area.site_total_m2) === 0 && r.media.length === 0) ? (
            <PlanEmpty
              icon={<Scale size={28} />}
              title="empty.balance_title"
              body="empty.balance_body"
              action="add_area"
              onAction={() => onGoTo('areas')}
            />
          ) : (
            <ul className="space-y-2">
              {rows.map((r) => (
                <StageBalanceCard key={r.stage.id} row={r} catalogue={catalogue} />
              ))}
            </ul>
          )
        }
      </Loaded>
    </section>
  );
}
