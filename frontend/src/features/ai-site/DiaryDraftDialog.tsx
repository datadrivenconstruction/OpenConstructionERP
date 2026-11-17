// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Draft with AI" for the daily diary: photos and voice transcripts in, reviewable entries out. */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Loader2, Sparkles } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { confirmProposal, draftDiary, rejectProposal, type DiaryDraftEnvelope, type DiaryDraftItem } from './api';
import { ProposalReview } from './ProposalReview';

interface Props {
  open: boolean;
  onClose: () => void;
  projectId: string;
  diaryDate: string;
  onSaved: () => void;
}

const inputCls =
  'w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary';

export function DiaryDraftDialog({ open, onClose, projectId, diaryDate, onSaved }: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [transcripts, setTranscripts] = useState('');
  const [draft, setDraft] = useState<DiaryDraftEnvelope | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const close = () => {
    setDraft(null);
    setErrors({});
    onClose();
  };

  const run = useMutation({
    mutationFn: () =>
      draftDiary(
        projectId,
        diaryDate,
        transcripts
          .split(/\n{2,}/)
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    onSuccess: setDraft,
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('site_ai.diary.draft_failed', { defaultValue: 'Could not draft the diary' }), message: e.message }),
  });

  const save = useMutation({
    mutationFn: (sel: Parameters<typeof confirmProposal>[1]) => confirmProposal(draft!.proposal_id!, sel),
    onSuccess: (res) => {
      const bad = res.results.filter((r) => r.status === 'error');
      if (bad.length) {
        setErrors(Object.fromEntries(bad.map((r) => [r.id, typeof r.detail === 'string' ? r.detail : JSON.stringify(r.detail)])));
        return;
      }
      addToast({
        type: 'success',
        title: t('site_ai.diary.saved', { defaultValue: 'Diary entries saved: {{n}}', n: res.results.length }),
      });
      onSaved();
      close();
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('site_ai.save_failed', { defaultValue: 'Could not save' }), message: e.message }),
  });

  const photosTitle = (i: DiaryDraftItem) =>
    t('site_ai.diary.photos_title', { defaultValue: 'Site photos ({{n}})', n: i.photo_count });

  return (
    <WideModal
      open={open}
      onClose={close}
      size="lg"
      busy={run.isPending || save.isPending}
      title={t('site_ai.diary.title', { defaultValue: 'Draft the diary with AI' })}
      subtitle={t('site_ai.diary.subtitle', {
        defaultValue: 'Entries are proposed from the photos taken on {{date}} and any voice notes. Nothing is saved until you accept it.',
        date: diaryDate,
      })}
      testId="diary-draft-dialog"
    >
      {!draft ? (
        <div className="flex flex-col gap-3">
          <label className="text-sm font-medium text-content-primary" htmlFor="diary-draft-transcripts">
            {t('site_ai.diary.transcripts', { defaultValue: 'Voice notes (optional, separate notes with a blank line)' })}
          </label>
          <textarea
            id="diary-draft-transcripts"
            className={`${inputCls} min-h-[120px]`}
            value={transcripts}
            onChange={(e) => setTranscripts(e.target.value)}
            data-testid="diary-draft-transcripts"
          />
          <p className="text-xs text-content-tertiary">
            {t('site_ai.diary.privacy', {
              defaultValue: 'Only photo captions, times and your notes are used. Locations are never sent to the AI provider.',
            })}
          </p>
          <div className="flex justify-end">
            <Button
              variant="primary"
              onClick={() => run.mutate()}
              disabled={run.isPending}
              icon={run.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              data-testid="diary-draft-run"
            >
              {t('site_ai.diary.run', { defaultValue: 'Draft entries' })}
            </Button>
          </div>
        </div>
      ) : (
        <ProposalReview<DiaryDraftItem>
          items={draft.items}
          degraded={draft.degraded}
          errors={errors}
          busy={save.isPending}
          onRejectAll={() => {
            void rejectProposal(draft.proposal_id!).finally(close);
          }}
          onConfirm={(sel) => save.mutate(sel)}
          defaultEdits={(i) => (i.activity ? undefined : { activity: photosTitle(i) })}
          renderItem={(i) => (
            <div className="flex flex-col gap-0.5">
              <span className="font-medium">{i.activity || photosTitle(i)}</span>
              <span className="text-xs text-content-tertiary">
                {[
                  i.time && (i.time_to && i.time_to !== i.time ? `${i.time}-${i.time_to}` : i.time),
                  i.trade,
                  i.crew_count != null &&
                    t('site_ai.diary.crew', { defaultValue: 'crew {{n}}', n: i.crew_count }),
                  i.weather_notes,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
              {i.source === 'transcript' && i.raw && (
                <span className="text-xs italic text-content-tertiary">{i.raw}</span>
              )}
            </div>
          )}
          renderEdit={(i, d, set) => (
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                className={`${inputCls} sm:col-span-2`}
                aria-label={t('site_ai.diary.activity', { defaultValue: 'Activity' })}
                defaultValue={i.activity}
                onChange={(e) => set({ activity: e.target.value })}
              />
              <input
                className={inputCls}
                aria-label={t('site_ai.diary.trade', { defaultValue: 'Trade' })}
                placeholder={t('site_ai.diary.trade', { defaultValue: 'Trade' })}
                defaultValue={i.trade ?? ''}
                onChange={(e) => set({ trade: e.target.value || null })}
              />
              <input
                className={inputCls}
                type="number"
                min={0}
                aria-label={t('site_ai.diary.crew_label', { defaultValue: 'Crew count' })}
                defaultValue={i.crew_count ?? ''}
                onChange={(e) => set({ crew_count: e.target.value === '' ? null : Number(e.target.value) })}
              />
              <input
                className={`${inputCls} sm:col-span-2`}
                aria-label={t('site_ai.diary.weather', { defaultValue: 'Weather notes' })}
                placeholder={t('site_ai.diary.weather', { defaultValue: 'Weather notes' })}
                defaultValue={i.weather_notes ?? ''}
                onChange={(e) => set({ weather_notes: e.target.value || null })}
              />
              <span hidden>{Object.keys(d).length}</span>
            </div>
          )}
        />
      )}
    </WideModal>
  );
}
