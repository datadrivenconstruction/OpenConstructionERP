// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Document assistant: ask the project's documents, get an answer where every claim is cited.
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BookOpenText, FileQuestion, Loader2, NotebookPen, Search, ShieldCheck } from 'lucide-react';
import clsx from 'clsx';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { Button, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import {
  SOURCE_KINDS,
  citationLocation,
  docAssistantApi,
  safeDeepLink,
  type AskResponse,
  type Citation,
  type SourceKind,
} from './api';

function ConfidenceBadge({ value, threshold }: { value: number; threshold: number }) {
  const { t } = useTranslation();
  const tone = value >= Math.max(threshold + 0.2, 0.8) ? 'high' : value >= threshold ? 'medium' : 'low';
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium',
        tone === 'high' && 'bg-green-500/10 text-green-700 dark:text-green-300',
        tone === 'medium' && 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
        tone === 'low' && 'bg-red-500/10 text-red-700 dark:text-red-300',
      )}
      title={t('doc_assistant.confidence_hint', {
        defaultValue: 'How much of your question the best passage covers. Below {{threshold}}% the assistant does not answer.',
        threshold: Math.round(threshold * 100),
      })}
    >
      <ShieldCheck className="h-3 w-3" />
      {t('doc_assistant.confidence', { defaultValue: 'Confidence {{value}}%', value: Math.round(value * 100) })}
    </span>
  );
}

function CitationCard({ c }: { c: Citation }) {
  const { t } = useTranslation();
  const link = safeDeepLink(c);
  const where = citationLocation(c).join(' · ');
  const body = (
    <>
      <div className="flex items-center gap-2">
        <span className="rounded bg-oe-blue/10 px-1.5 text-2xs font-semibold text-oe-blue">[{c.ref}]</span>
        <span className="truncate text-sm font-medium text-content-primary">{c.title}</span>
        <span className="text-2xs uppercase text-content-tertiary">
          {t(`doc_assistant.kind.${c.source_kind}`, { defaultValue: c.source_kind })}
        </span>
      </div>
      {where && <div className="mt-0.5 text-xs text-content-secondary">{where}</div>}
      <p className="mt-1 line-clamp-3 text-xs text-content-tertiary">{c.snippet}</p>
    </>
  );
  return link ? (
    <Link
      to={link}
      className="block rounded-lg border border-border-light p-2 hover:border-oe-blue/50 hover:bg-surface-secondary"
      aria-label={t('doc_assistant.open_source', { defaultValue: 'Open {{title}} at this page', title: c.title })}
    >
      {body}
    </Link>
  ) : (
    <div className="rounded-lg border border-border-light p-2">{body}</div>
  );
}

function AnswerView({ result }: { result: AskResponse }) {
  const { t } = useTranslation();
  if (result.status === 'no_documents') {
    return (
      <EmptyState
        icon={<FileQuestion className="h-8 w-8" />}
        title={t('doc_assistant.no_documents', { defaultValue: 'No readable documents in this project yet' })}
        description={t('doc_assistant.no_documents_hint', {
          defaultValue: 'Upload specifications or drawings in Files, or record RFIs and submittals, then ask again.',
        })}
      />
    );
  }
  if (result.status === 'not_found') {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-content-primary">
            {t('doc_assistant.not_found', { defaultValue: 'Not found in project documents.' })}
          </p>
          <ConfidenceBadge value={result.confidence} threshold={result.threshold} />
        </div>
        <p className="mt-1 text-xs text-content-secondary">
          {t('doc_assistant.not_found_hint', {
            defaultValue: 'Nothing the assistant may show you answers this well enough. Try other words, or raise an RFI.',
          })}
        </p>
        {result.nearest.length > 0 && (
          <div className="mt-3 space-y-2">
            <p className="text-2xs font-semibold uppercase text-content-tertiary">
              {t('doc_assistant.nearest', { defaultValue: 'Closest passages (not used as an answer)' })}
            </p>
            {result.nearest.map((c) => (
              <CitationCard key={c.passage_id} c={c} />
            ))}
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border-light bg-surface-primary p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <ConfidenceBadge value={result.confidence} threshold={result.threshold} />
          <span className="text-2xs text-content-tertiary">
            {result.mode === 'generated'
              ? t('doc_assistant.mode_generated', { defaultValue: 'Written by AI from the cited passages, check before use' })
              : t('doc_assistant.mode_extractive', { defaultValue: 'Quoted from the documents' })}
          </span>
        </div>
        <ul className="space-y-2">
          {result.claims.map((claim, i) => (
            <li key={i} className="text-sm text-content-primary">
              {claim.quoted ? <q>{claim.text}</q> : claim.text}{' '}
              {claim.citations.map((r) => (
                <sup key={r} className="ml-0.5 font-semibold text-oe-blue">
                  [{r}]
                </sup>
              ))}
              {claim.quote && <div className="mt-0.5 text-xs italic text-content-tertiary">“{claim.quote}”</div>}
            </li>
          ))}
        </ul>
      </div>
      <div className="space-y-2">
        <p className="text-2xs font-semibold uppercase text-content-tertiary">
          {t('doc_assistant.sources', { defaultValue: 'Sources' })}
        </p>
        {result.citations.map((c) => (
          <CitationCard key={c.passage_id} c={c} />
        ))}
      </div>
    </div>
  );
}

export function DocAssistantPage() {
  const { t, i18n } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');
  const [kinds, setKinds] = useState<SourceKind[]>([]);
  const [result, setResult] = useState<AskResponse | null>(null);

  const ask = useMutation({
    mutationFn: () =>
      docAssistantApi.ask({ project_id: projectId ?? '', question, locale: i18n.language ?? 'en', kinds }),
    onSuccess: setResult,
    onError: (e: Error) => addToast({ type: 'error', title: t('doc_assistant.ask_failed', { defaultValue: 'Could not search the documents' }), message: e.message }),
  });

  const save = useMutation({
    mutationFn: (target: 'note' | 'rfi') =>
      docAssistantApi.save({
        project_id: projectId ?? '',
        question: result?.question ?? question,
        answer: result?.answer ?? '',
        claims: result?.claims ?? [],
        citations: result?.citations ?? [],
        confidence: result?.confidence ?? 0,
        locale: i18n.language ?? 'en',
        target,
      }),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['doc-assistant-saved', projectId] });
      const warned = saved.validation?.status === 'warnings';
      addToast({
        type: warned ? 'warning' : 'success',
        title:
          saved.target_kind === 'rfi'
            ? t('doc_assistant.saved_rfi', { defaultValue: 'RFI draft created' })
            : t('doc_assistant.saved_note', { defaultValue: 'Saved as a project note' }),
        message: warned ? saved.validation.findings[0]?.message : undefined,
      });
    },
    onError: (e: Error) => addToast({ type: 'error', title: t('doc_assistant.save_failed', { defaultValue: 'Could not save the answer' }), message: e.message }),
  });

  const saved = useQuery({
    queryKey: ['doc-assistant-saved', projectId],
    queryFn: () => docAssistantApi.listSaved(projectId ?? ''),
    enabled: !!projectId,
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (question.trim().length >= 2 && projectId) ask.mutate();
  };

  const toggleKind = (k: SourceKind) =>
    setKinds((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('nav.doc_assistant', { defaultValue: 'Document Assistant' })}
        subtitle={t('doc_assistant.subtitle', {
          defaultValue:
            'Ask the project documents in plain language. Every statement links to the document, revision and page it comes from.',
        })}
      />
      {!projectId ? (
        <EmptyState
          icon={<BookOpenText className="h-8 w-8" />}
          title={t('doc_assistant.pick_project', { defaultValue: 'Choose a project first' })}
          description={t('doc_assistant.pick_project_hint', {
            defaultValue: 'The assistant only searches documents of the active project that you are allowed to see.',
          })}
        />
      ) : (
        <>
          <form onSubmit={onSubmit} className="space-y-2">
            <div className="flex gap-2">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                placeholder={t('doc_assistant.placeholder', {
                  defaultValue: 'e.g. What concrete cover is required for foundations?',
                })}
                aria-label={t('doc_assistant.question', { defaultValue: 'Your question' })}
                className="h-10 flex-1 rounded-lg border border-border-light bg-surface-primary px-3 text-sm"
              />
              <Button type="submit" disabled={ask.isPending || question.trim().length < 2}>
                {ask.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                {t('doc_assistant.ask', { defaultValue: 'Ask' })}
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('doc_assistant.filter', { defaultValue: 'Search in' })}>
              {SOURCE_KINDS.map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => toggleKind(k)}
                  aria-pressed={kinds.includes(k)}
                  className={clsx(
                    'rounded-full border px-2.5 py-0.5 text-xs',
                    kinds.includes(k)
                      ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                      : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                  )}
                >
                  {t(`doc_assistant.kind.${k}`, { defaultValue: k })}
                </button>
              ))}
            </div>
          </form>

          {result && <AnswerView result={result} />}

          {result?.status === 'answered' && (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => save.mutate('note')} disabled={save.isPending}>
                <NotebookPen className="h-4 w-4" />
                {t('doc_assistant.save_note', { defaultValue: 'Save as note' })}
              </Button>
              <Button variant="secondary" onClick={() => save.mutate('rfi')} disabled={save.isPending}>
                <FileQuestion className="h-4 w-4" />
                {t('doc_assistant.save_rfi', { defaultValue: 'Create RFI draft' })}
              </Button>
            </div>
          )}

          {(saved.data?.items.length ?? 0) > 0 && (
            <section className="space-y-2 pt-2">
              <h2 className="text-2xs font-semibold uppercase text-content-tertiary">
                {t('doc_assistant.saved_title', { defaultValue: 'Saved answers' })}
              </h2>
              {saved.data!.items.map((s) => (
                <div key={s.id} className="rounded-lg border border-border-light p-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-content-primary">{s.question}</span>
                    {s.target_kind === 'rfi' && s.target_id ? (
                      <Link to={`/rfi/${s.target_id}`} className="text-xs text-oe-blue hover:underline">
                        {t('doc_assistant.open_rfi', { defaultValue: 'Open RFI' })}
                      </Link>
                    ) : null}
                  </div>
                  <p className="line-clamp-2 text-xs text-content-secondary">{s.answer}</p>
                  {s.validation?.status === 'warnings' && (
                    <p className="mt-1 text-2xs text-amber-700 dark:text-amber-300">{s.validation.findings[0]?.message}</p>
                  )}
                </div>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}
