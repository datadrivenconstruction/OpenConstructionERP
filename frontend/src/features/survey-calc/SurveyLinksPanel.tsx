// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Links of one survey record (traverse, level run or import): the site diary
 * entry of its day (date, crew, instrument, weather) and the documents and
 * photos that back it (field sheet PDF, photos). The diary and the document
 * preview show the same links from their side.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BookOpen, FileText, Link2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fetchDocuments, fetchPhotos } from '@/features/documents/api';
import { createReference } from '@/features/file-references/api';
import { getSurveyLinks, linkDiary, type SurveyLinkKind } from './adjustment';

interface Props {
  projectId: string;
  kind: SurveyLinkKind;
  targetId: string;
  /** Shown on the document side as the chip label. */
  label: string;
  canWrite?: boolean;
}

const today = () => new Date().toISOString().slice(0, 10);

export function SurveyLinksPanel({ projectId, kind, targetId, label, canWrite = true }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const key = ['survey', 'links', kind, targetId];
  const links = useQuery({ queryKey: key, queryFn: () => getSurveyLinks(projectId, kind, targetId), enabled: !!projectId && !!targetId });
  const [diaryOpen, setDiaryOpen] = useState(false);
  const [docOpen, setDocOpen] = useState(false);
  const [day, setDay] = useState(today());
  const [crew, setCrew] = useState('');
  const [instrument, setInstrument] = useState('');
  const [weather, setWeather] = useState('');
  const [fileKind, setFileKind] = useState<'document' | 'photo'>('document');
  const [search, setSearch] = useState('');

  const files = useQuery({
    queryKey: ['survey', 'link-files', projectId, fileKind, search],
    queryFn: async () =>
      fileKind === 'document'
        ? (await fetchDocuments(projectId, { search, limit: 20 })).items.map((d) => ({ id: d.id, name: d.name }))
        : (await fetchPhotos(projectId, { search })).items.slice(0, 20).map((p) => ({ id: p.id, name: p.caption || p.filename })),
    enabled: docOpen && !!projectId,
  });

  const addDiary = useMutation({
    mutationFn: () => linkDiary(projectId, kind, targetId, { diary_date: day, title: label, crew, instrument, weather }),
    onSuccess: () => {
      setDiaryOpen(false);
      qc.invalidateQueries({ queryKey: key });
      addToast({ type: 'success', title: t('survey.links.diary_done', { defaultValue: 'Recorded in the site diary' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const addFile = useMutation({
    mutationFn: (fileId: string) =>
      createReference({
        project_id: projectId,
        file_kind: fileKind,
        file_id: fileId,
        target_type: kind === 'traverse' ? 'survey_traverse' : 'survey_point_set',
        target_id: targetId,
        relation: 'evidence',
        target_label: label,
      }),
    onSuccess: () => {
      setDocOpen(false);
      qc.invalidateQueries({ queryKey: key });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const data = links.data;
  return (
    <section className="space-y-2 text-sm" data-testid="survey-links">
      <h3 className="oe-card-title flex items-center gap-1"><Link2 size={14} />{t('survey.links.title', { defaultValue: 'Site diary and documents' })}</h3>
      {data && data.diary.length + data.documents.length === 0 && (
        <p className="text-content-tertiary">{t('survey.links.none', { defaultValue: 'Not linked yet.' })}</p>
      )}
      <ul className="space-y-1">
        {data?.diary.map((d) => (
          <li key={d.entry_id}>
            <button type="button" className="inline-flex items-center gap-1 text-oe-blue hover:underline" onClick={() => navigate(`/daily-diary?diary=${d.diary_id}`)}>
              <BookOpen size={12} />
              <bdi dir="ltr">{d.diary_date}</bdi>
            </button>
            <span className="text-content-secondary"> · {[d.crew, d.instrument, d.weather].filter(Boolean).join(' · ')}</span>
          </li>
        ))}
        {data?.documents.map((d) => (
          <li key={d.reference_id}>
            <button
              type="button"
              className="inline-flex items-center gap-1 text-oe-blue hover:underline"
              onClick={() => navigate(`/files?kind=${d.file_kind}${d.label ? `&q=${encodeURIComponent(d.label)}` : ''}`)}
            >
              <FileText size={12} />
              {d.label || (d.file_kind === 'photo' ? t('survey.links.photo', { defaultValue: 'Photo' }) : t('survey.links.document', { defaultValue: 'Document' }))}
            </button>
          </li>
        ))}
      </ul>
      {canWrite && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => setDiaryOpen((v) => !v)}>
            {t('survey.links.add_diary', { defaultValue: 'Record in site diary' })}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setDocOpen((v) => !v)}>
            {t('survey.links.add_document', { defaultValue: 'Link document or photo' })}
          </Button>
        </div>
      )}
      {diaryOpen && (
        <div className="grid grid-cols-2 gap-2 rounded-md border border-border-light p-2">
          <label className="block">
            <span className="oe-label">{t('survey.links.date', { defaultValue: 'Diary date' })}</span>
            <input type="date" className="oe-input w-full" value={day} max={today()} onChange={(e) => setDay(e.target.value)} />
          </label>
          <label className="block">
            <span className="oe-label">{t('survey.links.crew', { defaultValue: 'Crew' })}</span>
            <input className="oe-input w-full" value={crew} onChange={(e) => setCrew(e.target.value)} />
          </label>
          <label className="block">
            <span className="oe-label">{t('survey.import.instrument', { defaultValue: 'Instrument' })}</span>
            <input className="oe-input w-full" value={instrument} onChange={(e) => setInstrument(e.target.value)} />
          </label>
          <label className="block">
            <span className="oe-label">{t('survey.links.weather', { defaultValue: 'Weather' })}</span>
            <input className="oe-input w-full" value={weather} onChange={(e) => setWeather(e.target.value)} />
          </label>
          <div className="col-span-2 flex justify-end">
            <Button size="sm" loading={addDiary.isPending} disabled={!day} onClick={() => addDiary.mutate()}>
              {t('survey.links.save', { defaultValue: 'Link' })}
            </Button>
          </div>
        </div>
      )}
      {docOpen && (
        <div className="space-y-2 rounded-md border border-border-light p-2">
          <div className="flex gap-2">
            <select className="oe-input" value={fileKind} onChange={(e) => setFileKind(e.target.value as 'document' | 'photo')}>
              <option value="document">{t('survey.links.document', { defaultValue: 'Document' })}</option>
              <option value="photo">{t('survey.links.photo', { defaultValue: 'Photo' })}</option>
            </select>
            <input
              className="oe-input w-full"
              placeholder={t('common.search', { defaultValue: 'Search' })}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <ul className="max-h-48 space-y-1 overflow-y-auto">
            {(files.data ?? []).map((f) => (
              <li key={f.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{f.name}</span>
                <Button size="sm" variant="ghost" loading={addFile.isPending && addFile.variables === f.id} onClick={() => addFile.mutate(f.id)}>
                  {t('survey.links.save', { defaultValue: 'Link' })}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export default SurveyLinksPanel;
