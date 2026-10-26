// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// MeetingGlossaryDialog - the project vocabulary for minutes from audio. Names,
// companies, abbreviations and trade terms are sent to the speech service as
// hints and to the minutes AI as the correct spelling. "Fill from project"
// adds attendee, contact, stakeholder, project and BOQ section names; known
// mis-hearings typed under "Heard as" are corrected in every transcript.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, Sparkles, Trash2 } from 'lucide-react';
import { Badge, Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  addGlossaryTerm,
  deleteGlossaryTerm,
  fetchGlossary,
  seedGlossary,
  updateGlossaryTerm,
  type GlossaryKind,
  type GlossaryTerm,
} from './audioApi';

const KINDS: GlossaryKind[] = ['person', 'company', 'abbreviation', 'term', 'boq', 'place'];

const fieldCls =
  'h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

interface MeetingGlossaryDialogProps {
  projectId: string;
  onClose: () => void;
}

export function MeetingGlossaryDialog({ projectId, onClose }: MeetingGlossaryDialogProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const key = ['meeting-glossary', projectId];
  const termsQ = useQuery({ queryKey: key, queryFn: () => fetchGlossary(projectId) });
  const [term, setTerm] = useState('');
  const [kind, setKind] = useState<GlossaryKind>('term');
  const [expansion, setExpansion] = useState('');
  const [aliases, setAliases] = useState('');

  const kindLabel = (k: GlossaryKind) =>
    t(`meetings.audio.glossary_kind_${k}`, {
      defaultValue: {
        person: 'Person',
        company: 'Company',
        abbreviation: 'Abbreviation',
        term: 'Term',
        boq: 'BOQ / section',
        place: 'Place',
      }[k],
    });

  const onError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('meetings.audio.glossary_failed', { defaultValue: 'Could not update the glossary' }),
      message: getErrorMessage(e),
    });

  const refresh = () => qc.invalidateQueries({ queryKey: key });

  const addMut = useMutation({
    mutationFn: () =>
      addGlossaryTerm(projectId, {
        term: term.trim(),
        kind,
        expansion: expansion.trim() || null,
        aliases: splitAliases(aliases),
      }),
    onSuccess: () => {
      setTerm('');
      setExpansion('');
      setAliases('');
      refresh();
    },
    onError,
  });

  const seedMut = useMutation({
    mutationFn: () => seedGlossary(projectId),
    onSuccess: (res) => {
      qc.setQueryData(key, res.terms);
      addToast({
        type: 'success',
        title: t('meetings.audio.glossary_seeded', {
          defaultValue: 'Terms added from the project: {{n}}',
          n: res.added,
        }),
      });
    },
    onError,
  });

  const aliasMut = useMutation({
    mutationFn: ({ row, value }: { row: GlossaryTerm; value: string }) =>
      updateGlossaryTerm(row.id, { aliases: splitAliases(value) }),
    onSuccess: refresh,
    onError,
  });

  const deleteMut = useMutation({
    mutationFn: (row: GlossaryTerm) => deleteGlossaryTerm(row.id),
    onSuccess: refresh,
    onError,
  });

  const terms = termsQ.data ?? [];
  const busy = addMut.isPending || seedMut.isPending;

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      title={t('meetings.audio.glossary_title', { defaultValue: 'Project meeting glossary' })}
      subtitle={t('meetings.audio.glossary_subtitle', {
        defaultValue:
          'Names and terms the speech service should know. They improve the transcript and the spelling in the minutes.',
      })}
      footer={
        <div className="flex w-full items-center justify-between">
          <Button variant="secondary" size="sm" onClick={() => seedMut.mutate()} disabled={busy}>
            {seedMut.isPending ? (
              <Loader2 size={14} className="mr-1.5 animate-spin" />
            ) : (
              <Sparkles size={14} className="mr-1.5" />
            )}
            {t('meetings.audio.glossary_seed', { defaultValue: 'Fill from project' })}
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4" data-testid="meeting-glossary">
        <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,2fr)_minmax(0,2fr)_auto] gap-2 items-end">
          <label className="text-xs text-content-secondary space-y-0.5">
            <span>{t('meetings.audio.glossary_term', { defaultValue: 'Term' })}</span>
            <input className={fieldCls} value={term} onChange={(e) => setTerm(e.target.value)} />
          </label>
          <label className="text-xs text-content-secondary space-y-0.5">
            <span>{t('meetings.audio.glossary_kind', { defaultValue: 'Kind' })}</span>
            <select className={fieldCls} value={kind} onChange={(e) => setKind(e.target.value as GlossaryKind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {kindLabel(k)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-content-secondary space-y-0.5">
            <span>{t('meetings.audio.glossary_expansion', { defaultValue: 'Meaning (optional)' })}</span>
            <input className={fieldCls} value={expansion} onChange={(e) => setExpansion(e.target.value)} />
          </label>
          <label className="text-xs text-content-secondary space-y-0.5">
            <span>{t('meetings.audio.glossary_aliases', { defaultValue: 'Heard as (comma separated)' })}</span>
            <input className={fieldCls} value={aliases} onChange={(e) => setAliases(e.target.value)} />
          </label>
          <Button
            variant="primary"
            size="sm"
            onClick={() => addMut.mutate()}
            disabled={busy || term.trim().length < 2}
          >
            <Plus size={14} className="mr-1" />
            {t('common.add', { defaultValue: 'Add' })}
          </Button>
        </div>

        {termsQ.isLoading ? (
          <Loader2 size={16} className="animate-spin text-content-tertiary" />
        ) : terms.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('meetings.audio.glossary_empty', {
              defaultValue: 'No terms yet. Fill the glossary from the project or add terms by hand.',
            })}
          </p>
        ) : (
          <div className="divide-y divide-border-light rounded-lg border border-border-light">
            {terms.map((row) => (
              <div key={row.id} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                <span className="font-medium text-content-primary min-w-0 flex-1 truncate">
                  {row.term}
                  {row.expansion && (
                    <span className="ml-1.5 font-normal text-content-tertiary">{row.expansion}</span>
                  )}
                </span>
                <Badge variant="neutral" size="sm">
                  {kindLabel(row.kind)}
                </Badge>
                <input
                  className={`${fieldCls} max-w-[220px]`}
                  defaultValue={row.aliases.join(', ')}
                  placeholder={t('meetings.audio.glossary_aliases_short', { defaultValue: 'Heard as' })}
                  onBlur={(e) => {
                    if (e.target.value !== row.aliases.join(', ')) aliasMut.mutate({ row, value: e.target.value });
                  }}
                  aria-label={t('meetings.audio.glossary_aliases_short', { defaultValue: 'Heard as' })}
                />
                <button
                  type="button"
                  className="text-content-tertiary hover:text-semantic-error"
                  onClick={() => deleteMut.mutate(row)}
                  aria-label={t('common.delete', { defaultValue: 'Delete' })}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </WideModal>
  );
}

function splitAliases(value: string): string[] {
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}
