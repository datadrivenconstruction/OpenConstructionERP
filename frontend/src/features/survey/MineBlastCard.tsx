// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Blast patterns of the mine: paste the design collars, hand the stake list to
 * the instrument, import the as-drilled holes and see which ones miss the
 * pattern tolerance (SRV-093). Tolerances are the pattern's own; none is preset.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Plus, Upload } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, EmptyState, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtFixed } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { createPattern, getPattern, importAsDrilled, listPatterns, stakeListUrl, type BlastHole } from './mineApi';

const m3 = (v: number | null | undefined) => (v == null ? '' : fmtFixed(v, 3));

function HoleVerdict({ h }: { h: BlastHole }) {
  const { t } = useTranslation();
  if (h.collar_ok === null && h.depth_ok === null) return <span className="text-content-tertiary">-</span>;
  const bad = h.collar_ok === false || h.depth_ok === false;
  return (
    <Badge variant={bad ? 'error' : 'success'} size="sm">
      {bad ? t('mine.blast.out', { defaultValue: 'Out of tolerance' }) : t('mine.blast.ok', { defaultValue: 'Within tolerance' })}
    </Badge>
  );
}

export function MineBlastCard({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [openId, setOpenId] = useState<string | null>(null);
  const [form, setForm] = useState<{ name: string; collar: string; depth: string; text: string } | null>(null);
  const [drilled, setDrilled] = useState('');

  const patterns = useQuery({ queryKey: ['mine', 'blast', projectId], queryFn: () => listPatterns(projectId) });
  const detail = useQuery({
    queryKey: ['mine', 'blast', 'detail', openId, i18n.language],
    queryFn: () => getPattern(openId!, i18n.language),
    enabled: !!openId,
  });
  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const create = useMutation({
    mutationFn: () =>
      createPattern(
        projectId,
        {
          name: form!.name,
          collar_tol_m: form!.collar ? Number(form!.collar) : null,
          depth_tol_m: form!.depth ? Number(form!.depth) : null,
          design_text: form!.text,
        },
        i18n.language,
      ),
    onSuccess: (p) => {
      setForm(null);
      setOpenId(p.id);
      qc.invalidateQueries({ queryKey: ['mine', 'blast'] });
    },
    onError,
  });
  const asDrilled = useMutation({
    mutationFn: () => importAsDrilled(openId!, drilled, i18n.language),
    onSuccess: () => {
      setDrilled('');
      qc.invalidateQueries({ queryKey: ['mine', 'blast'] });
    },
    onError,
  });

  const d = detail.data;
  return (
    <Card data-testid="mine-blast">
      <CardHeader
        title={t('mine.blast.title', { defaultValue: 'Blast patterns' })}
        subtitle={t('mine.blast.subtitle', {
          defaultValue: 'Design collars and depths, the stake list for the rig, and the as-drilled check against the pattern tolerance.',
        })}
        action={
          canWrite && !form ? (
            <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setForm({ name: '', collar: '', depth: '', text: '' })}>
              {t('mine.blast.new', { defaultValue: 'New pattern' })}
            </Button>
          ) : undefined
        }
      />
      <CardContent className="space-y-4">
        {form && (
          <div className="grid gap-3 rounded-lg border border-border-light p-3 sm:grid-cols-3">
            <label className="text-sm sm:col-span-3">
              {t('mine.blast.name', { defaultValue: 'Pattern name' })}
              <input className="oe-input mt-1 w-full" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="text-sm">
              {t('mine.blast.collar_tol', { defaultValue: 'Collar tolerance (m)' })}
              <input className="oe-input mt-1 w-full" inputMode="decimal" value={form.collar} onChange={(e) => setForm({ ...form, collar: e.target.value })} />
            </label>
            <label className="text-sm">
              {t('mine.blast.depth_tol', { defaultValue: 'Depth tolerance (m)' })}
              <input className="oe-input mt-1 w-full" inputMode="decimal" value={form.depth} onChange={(e) => setForm({ ...form, depth: e.target.value })} />
            </label>
            <label className="text-sm sm:col-span-3">
              {t('mine.blast.design_csv', { defaultValue: 'Design holes, one per line: hole, E, N, Z, depth' })}
              <textarea rows={6} className="oe-textarea mt-1 w-full font-mono text-xs" value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
            </label>
            <div className="flex justify-end gap-2 sm:col-span-3">
              <Button size="sm" variant="ghost" onClick={() => setForm(null)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button size="sm" variant="primary" disabled={!form.name.trim()} loading={create.isPending} onClick={() => create.mutate()}>
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
          </div>
        )}

        {patterns.isLoading ? (
          <Skeleton className="h-16" />
        ) : (patterns.data ?? []).length === 0 ? (
          <EmptyState title={t('mine.blast.empty', { defaultValue: 'No blast patterns yet.' })} />
        ) : (
          <div className="flex flex-wrap gap-2" role="list">
            {(patterns.data ?? []).map((p) => (
              <button
                key={p.id}
                type="button"
                role="listitem"
                onClick={() => setOpenId(p.id)}
                className={`rounded-lg border px-3 py-1.5 text-sm ${openId === p.id ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light hover:bg-surface-secondary'}`}
              >
                <span className="font-mono">{p.code}</span> {p.name}
                <span className="ms-2 text-xs text-content-secondary">
                  {t('mine.blast.count', { defaultValue: '{{drilled}}/{{holes}} drilled, {{failed}} out', drilled: p.drilled, holes: p.holes, failed: p.failed })}
                </span>
              </button>
            ))}
          </div>
        )}

        {d && (
          <div className="space-y-3" data-testid="mine-blast-detail">
            <div className="flex flex-wrap items-center gap-2">
              <a href={stakeListUrl(d.id)} download>
                <Button size="sm" variant="secondary" icon={<Download size={14} />}>
                  {t('mine.blast.stake_list', { defaultValue: 'Stake list (CSV)' })}
                </Button>
              </a>
              {(d.collar_tol_m == null || d.depth_tol_m == null) && (
                <span className="text-xs text-content-secondary">
                  {t('mine.blast.no_tol', { defaultValue: 'Set both tolerances on the pattern to judge the holes.' })}
                </span>
              )}
            </div>
            {canWrite && (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <label className="flex-1 text-sm">
                  {t('mine.blast.drilled_csv', { defaultValue: 'As-drilled holes, same columns as the design' })}
                  <textarea rows={4} className="oe-textarea mt-1 w-full font-mono text-xs" value={drilled} onChange={(e) => setDrilled(e.target.value)} />
                </label>
                <Button size="sm" variant="primary" icon={<Upload size={14} />} disabled={!drilled.trim()} loading={asDrilled.isPending} onClick={() => asDrilled.mutate()}>
                  {t('mine.blast.import_drilled', { defaultValue: 'Import as-drilled' })}
                </Button>
              </div>
            )}
            {d.findings.length > 0 && (
              <ul className="space-y-1 text-sm">
                {d.findings.map((f, i) => (
                  <li key={`${f.rule_id}-${i}`} className="flex gap-2">
                    <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span>
                    {f.message}
                  </li>
                ))}
              </ul>
            )}
            <div className="overflow-x-auto">
              <table className="oe-table w-full text-sm">
                <thead>
                  <tr>
                    <th>{t('mine.blast.hole', { defaultValue: 'Hole' })}</th>
                    <th className="text-end">{t('mine.blast.design_depth', { defaultValue: 'Design depth (m)' })}</th>
                    <th className="text-end">{t('mine.blast.drilled_depth', { defaultValue: 'Drilled depth (m)' })}</th>
                    <th className="text-end">{t('mine.blast.collar_off', { defaultValue: 'Collar offset (m)' })}</th>
                    <th className="text-end">{t('mine.blast.depth_diff', { defaultValue: 'Depth difference (m)' })}</th>
                    <th>{t('mine.blast.verdict', { defaultValue: 'Check' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((h) => (
                    <tr key={h.id}>
                      <td className="font-mono">{h.hole_id}</td>
                      <td className="text-end tabular-nums">{m3(h.design_depth_m)}</td>
                      <td className="text-end tabular-nums">{m3(h.drilled_depth_m)}</td>
                      <td className="text-end tabular-nums">{m3(h.collar_offset_m)}</td>
                      <td className="text-end tabular-nums">{m3(h.depth_diff_m)}</td>
                      <td><HoleVerdict h={h} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
