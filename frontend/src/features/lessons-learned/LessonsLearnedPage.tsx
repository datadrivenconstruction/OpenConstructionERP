// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge, Button, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { lessonsApi, type Impact, type Lesson, type LessonInput } from './api';

const IMPACTS: Impact[] = ['low', 'medium', 'high'];
const FIELD =
  'h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

function blank(projectId: string): LessonInput {
  return {
    project_id: projectId,
    title: '',
    description: '',
    recommendation: '',
    trade: '',
    cost_code: '',
    risk_category: '',
    impact: 'medium',
  };
}

export function LessonsLearnedPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const [allProjects, setAllProjects] = useState(false);
  const [form, setForm] = useState<LessonInput | null>(null);

  const scope = allProjects ? undefined : projectId;
  const { data: lessons = [], isLoading } = useQuery({
    queryKey: ['lessons-learned', 'list', scope ?? 'all'],
    queryFn: () => lessonsApi.list(scope),
    enabled: allProjects || !!projectId,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ['lessons-learned'] });
  const onError = (e: unknown) =>
    toast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const create = useMutation({
    mutationFn: (body: LessonInput) => lessonsApi.create(body),
    onSuccess: () => {
      setForm(null);
      refresh();
    },
    onError,
  });
  const confirm = useMutation({ mutationFn: (id: string) => lessonsApi.confirm(id), onSuccess: refresh, onError });
  const remove = useMutation({ mutationFn: (id: string) => lessonsApi.remove(id), onSuccess: refresh, onError });

  const set = (patch: Partial<LessonInput>) => setForm((f) => (f ? { ...f, ...patch } : f));

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('lessons_learned.title', { defaultValue: 'Lessons learned' })}
        subtitle={t('lessons_learned.subtitle', {
          defaultValue: 'Write down what a project taught you at closeout. Estimates and risks then show where it was seen before.',
        })}
        actions={
          <Button variant="primary" disabled={!projectId} onClick={() => setForm(blank(projectId))}>
            <Plus size={16} className="me-1.5" />
            {t('lessons_learned.add', { defaultValue: 'Add lesson' })}
          </Button>
        }
      />

      <label className="inline-flex items-center gap-2 text-sm text-content-secondary">
        <input type="checkbox" checked={allProjects} onChange={(e) => setAllProjects(e.target.checked)} />
        {t('lessons_learned.all_projects', { defaultValue: 'Show all my projects' })}
      </label>

      {form && (
        <form
          data-testid="lesson-form"
          className="grid gap-3 rounded-lg border border-border-light p-4 md:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(form);
          }}
        >
          <label className="md:col-span-2 text-xs text-content-secondary">
            {t('lessons_learned.field.title', { defaultValue: 'Title' })}
            <input className={FIELD} value={form.title} onChange={(e) => set({ title: e.target.value })} required />
          </label>
          <label className="text-xs text-content-secondary">
            {t('lessons_learned.field.trade', { defaultValue: 'Trade' })}
            <input className={FIELD} value={form.trade} onChange={(e) => set({ trade: e.target.value })} />
          </label>
          <label className="text-xs text-content-secondary">
            {t('lessons_learned.field.cost_code', { defaultValue: 'Cost code' })}
            <input className={FIELD} value={form.cost_code} onChange={(e) => set({ cost_code: e.target.value })} />
          </label>
          <label className="text-xs text-content-secondary">
            {t('lessons_learned.field.risk_category', { defaultValue: 'Risk category' })}
            <input className={FIELD} value={form.risk_category} onChange={(e) => set({ risk_category: e.target.value })} />
          </label>
          <label className="text-xs text-content-secondary">
            {t('lessons_learned.field.impact', { defaultValue: 'Impact' })}
            <select className={FIELD} value={form.impact} onChange={(e) => set({ impact: e.target.value as Impact })}>
              {IMPACTS.map((i) => (
                <option key={i} value={i}>
                  {t(`lessons_learned.impact.${i}`, { defaultValue: i })}
                </option>
              ))}
            </select>
          </label>
          <label className="md:col-span-2 text-xs text-content-secondary">
            {t('lessons_learned.field.description', { defaultValue: 'What happened' })}
            <textarea className={`${FIELD} h-20 py-1.5`} value={form.description} onChange={(e) => set({ description: e.target.value })} />
          </label>
          <label className="md:col-span-2 text-xs text-content-secondary">
            {t('lessons_learned.field.recommendation', { defaultValue: 'What to do next time' })}
            <textarea className={`${FIELD} h-20 py-1.5`} value={form.recommendation} onChange={(e) => set({ recommendation: e.target.value })} />
          </label>
          <div className="md:col-span-2 flex gap-2">
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button type="button" variant="secondary" onClick={() => setForm(null)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </form>
      )}

      {!isLoading && lessons.length === 0 ? (
        <EmptyState
          title={t('lessons_learned.empty_title', { defaultValue: 'No lessons yet' })}
          description={t('lessons_learned.empty', {
            defaultValue: 'Add the first lesson when a project closes. A manager confirms it before other projects see it.',
          })}
        />
      ) : (
        <ul className="space-y-2">
          {lessons.map((l) => (
            <LessonRow key={l.id} lesson={l} onConfirm={() => confirm.mutate(l.id)} onDelete={() => remove.mutate(l.id)} />
          ))}
        </ul>
      )}
    </div>
  );
}

function LessonRow(props: { lesson: Lesson; onConfirm: () => void; onDelete: () => void }) {
  const { t } = useTranslation();
  const { lesson: l } = props;
  const tags = [l.trade, l.cost_code, l.risk_category].filter(Boolean);
  return (
    <li data-testid="lesson-row" className="rounded-lg border border-border-light p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-content-primary">{l.title}</span>
        <Badge variant={l.status === 'confirmed' ? 'success' : 'neutral'}>
          {t(`lessons_learned.status.${l.status}`, { defaultValue: l.status })}
        </Badge>
        <Badge variant={l.impact === 'high' ? 'error' : 'neutral'}>
          {t(`lessons_learned.impact.${l.impact}`, { defaultValue: l.impact })}
        </Badge>
        {tags.map((tag) => (
          <Badge key={tag} variant="neutral">
            {tag}
          </Badge>
        ))}
      </div>
      {l.description && <p className="mt-1 text-sm text-content-secondary">{l.description}</p>}
      {l.recommendation && <p className="mt-1 text-sm text-content-primary">{l.recommendation}</p>}
      {l.findings.length > 0 && (
        <ul data-testid="lesson-findings" className="mt-1 list-disc ps-5 text-xs text-content-tertiary">
          {l.findings.map((f) => (
            <li key={f.rule_id}>
              {t(`lessons_learned.finding.${f.rule_id.split('.').pop()}`, { defaultValue: f.message })}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex gap-2">
        {l.status === 'draft' && (
          <Button
            size="sm"
            variant="secondary"
            disabled={l.findings.some((f) => f.severity === 'error')}
            onClick={props.onConfirm}
          >
            {t('lessons_learned.confirm', { defaultValue: 'Confirm' })}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={props.onDelete}>
          {t('common.delete', { defaultValue: 'Delete' })}
        </Button>
      </div>
    </li>
  );
}

export default LessonsLearnedPage;
