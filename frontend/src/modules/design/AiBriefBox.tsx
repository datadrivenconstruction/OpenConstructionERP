// Design module (ERP side of the design editor link).
/**
 * "Describe the building": the text goes to the brief extraction (R5, the person's own AI settings); every value
 * comes back with the words it was read from, and only the values the person ticks are saved and confirmed.
 * AI chooses parameters only; nothing is filled in that the text does not say.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { confirmBrief, extractBrief, saveBrief, type Extraction } from './api';
import { briefErrors, formatValue, tidy, type BriefDoc } from './data/briefModel';
import { keepConfirmed, proposals } from './data/workspace';
import { fieldLabel, tr } from './BriefFields';

export interface AiOutcome { status: 'confirmed' | 'declined'; brief_version?: number; brief?: BriefDoc; confirmed?: string[] }

export function AiBriefBox({ projectId, brief, aiReady, initialText = '', onDone }: {
  projectId: string;
  brief: BriefDoc | null;
  aiReady: boolean;
  initialText?: string;
  onDone?: (o: AiOutcome) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [text, setText] = useState(initialText);
  const [draft, setDraft] = useState<Extraction | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<'read' | 'save' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<number | null>(null);

  const read = async () => {
    setBusy('read'); setError(null); setSaved(null);
    try {
      const x = await extractBrief(projectId, text.trim(), brief);
      setDraft(x);
      setTicked(new Set());
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const finish = async () => {
    if (!draft) return;
    const confirmed = [...ticked];
    if (!confirmed.length) {
      setDraft(null);
      onDone?.({ status: 'declined' });
      return;
    }
    setBusy('save'); setError(null);
    try {
      const doc = tidy(keepConfirmed(draft.brief, draft.summary.proposed, confirmed));
      const missing = Object.values(briefErrors(doc)).flat().filter((e) => e.code === 'required').length;
      const stored = await saveBrief(projectId, doc, brief?.version ?? 0, missing > 0);
      const done = await confirmBrief(projectId, confirmed, stored.version);
      qc.setQueryData(['design-brief', projectId], done);
      void qc.invalidateQueries({ queryKey: ['design-model', projectId] });
      setSaved(done.version);
      setDraft(null);
      onDone?.({ status: 'confirmed', brief_version: done.version, brief: done, confirmed });
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const list = draft ? proposals(draft.brief, draft.summary.proposed) : [];
  const toggle = (p: string) => setTicked((s) => {
    const n = new Set(s);
    if (n.has(p)) n.delete(p); else n.add(p);
    return n;
  });

  return (
    <section data-testid="ai-brief" aria-labelledby="ai-brief-title" className="flex flex-col gap-2">
      <h2 id="ai-brief-title" className="flex items-center gap-2 text-sm font-medium text-content-primary">
        <Sparkles size={14} aria-hidden /> {tr(t, 'design.workspace.ai.title')}
      </h2>
      <textarea aria-label={tr(t, 'design.workspace.ai.title')} value={text} onChange={(e) => setText(e.target.value)}
        rows={4} maxLength={20000} placeholder={tr(t, 'design.workspace.ai.placeholder')}
        className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary" />
      {!aiReady && <p className="text-xs text-content-tertiary" data-testid="ai-off">{tr(t, 'design.workspace.ai.no_ai')}</p>}
      <div>
        <Button size="sm" variant="secondary" loading={busy === 'read'} disabled={!text.trim() || busy !== null} onClick={() => void read()}>
          {tr(t, 'design.workspace.ai.read')}
        </Button>
      </div>
      {error && <p role="alert" className="text-sm text-semantic-error">{error}</p>}
      {saved !== null && <p role="status" className="text-sm">{tr(t, 'design.workspace.ai.saved', { version: saved })}</p>}
      {draft && (
        <div className="flex flex-col gap-2 rounded-lg border border-border-light p-2" data-testid="ai-proposals">
          <p className="text-xs text-content-secondary">
            {list.length ? tr(t, 'design.workspace.ai.confirm_each') : tr(t, 'design.workspace.ai.nothing')}
          </p>
          <ul className="flex flex-col gap-2">
            {list.map((p) => (
              <li key={p.pointer}>
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={ticked.has(p.pointer)} onChange={() => toggle(p.pointer)} />
                  <span className="flex flex-col">
                    <span><span className="text-content-secondary">{fieldLabel(t, p.pointer)}:</span> {formatValue(p.value)}</span>
                    {p.quote && <q className="text-xs text-content-tertiary">{p.quote}</q>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {draft.summary.questions.length > 0 && (
            <p className="text-xs text-content-secondary">
              {tr(t, 'design.workspace.ai.questions', { count: draft.summary.questions.length })}{' '}
              <Link className="text-oe-blue-text underline" to="/design/brief">{tr(t, 'design.brief.title')}</Link>
            </p>
          )}
          <div className="flex gap-2">
            <Button size="sm" loading={busy === 'save'} disabled={busy !== null} onClick={() => void finish()}>
              {tr(t, 'design.workspace.ai.apply', { count: ticked.size })}
            </Button>
            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => { setDraft(null); onDone?.({ status: 'declined' }); }}>
              {tr(t, 'design.workspace.ai.discard')}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
