// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Names for everything the Videos page labels: roles and stages come from the
// Cases hub keys, result families from `videos.result.*`, and country and
// language names from the browser (`Intl.DisplayNames`) in the reader's own
// language, so no locale file has to spell out a country.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ROLE_BY_ID } from '@/features/cases/roles';
import { STAGE_BY_ID } from '@/features/cases/stages';
import type { LifecycleStage, ProfessionalRole } from '@/features/cases/types';
import type { AcademySeries, AcademyVideo, ResultFamily } from './academyTypes';
import { fmtList } from '@/shared/lib/formatters';
import { exampleToShow, seriesById } from './academy';

const RESULT_LABELS: Record<ResultFamily, [key: string, fallback: string]> = {
  cost: ['videos.result.cost', 'Cost estimate'],
  qty: ['videos.result.qty', 'Quantities'],
  bill: ['videos.result.bill', 'Bill of quantities'],
  rate: ['videos.result.rate', 'Unit rates'],
  gaeb: ['videos.result.gaeb', 'GAEB exchange'],
  award: ['videos.result.award', 'Bid comparison and award'],
  order: ['videos.result.order', 'Purchase orders'],
  programme: ['videos.result.programme', 'Programme'],
  site: ['videos.result.site', 'Site records'],
  change: ['videos.result.change', 'Changes and variations'],
  invoice: ['videos.result.invoice', 'Payments and invoices'],
  handover: ['videos.result.handover', 'Handover'],
};

function displayNames(locale: string, type: 'region' | 'language'): Intl.DisplayNames | null {
  try {
    return new Intl.DisplayNames([locale, 'en'], { type });
  } catch {
    return null;
  }
}

export function useVideoLabels() {
  const { t, i18n } = useTranslation();
  const locale = i18n.language || 'en';
  const regions = useMemo(() => displayNames(locale, 'region'), [locale]);
  const languages = useMemo(() => displayNames(locale, 'language'), [locale]);

  const role = useCallback(
    (id: ProfessionalRole) => {
      const meta = ROLE_BY_ID[id];
      return meta ? t(meta.labelKey, { defaultValue: meta.labelDefault }) : id;
    },
    [t],
  );
  const stage = useCallback(
    (id: LifecycleStage) => {
      const meta = STAGE_BY_ID[id];
      return meta ? t(meta.labelKey, { defaultValue: meta.labelDefault }) : id;
    },
    [t],
  );
  const stageShort = useCallback(
    (id: LifecycleStage) => {
      const meta = STAGE_BY_ID[id];
      return meta ? t(meta.shortKey, { defaultValue: meta.shortDefault }) : id;
    },
    [t],
  );
  const result = useCallback(
    (id: ResultFamily) => t(RESULT_LABELS[id][0], { defaultValue: RESULT_LABELS[id][1] }),
    [t],
  );
  const country = useCallback(
    (code: string) => {
      try {
        return regions?.of(code) ?? code;
      } catch {
        return code;
      }
    },
    [regions],
  );
  const language = useCallback(
    (code: string) => {
      try {
        const name = languages?.of(code) ?? code;
        return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1);
      } catch {
        return code;
      }
    },
    [languages, locale],
  );
  const series = useCallback(
    (idOrSeries: string | AcademySeries) => {
      const s = typeof idOrSeries === 'string' ? seriesById(idOrSeries) : idOrSeries;
      if (!s) return typeof idOrSeries === 'string' ? idOrSeries : '';
      return s.titleKey ? t(s.titleKey, { defaultValue: s.title }) : s.title;
    },
    [t],
  );

  /** "Example: Denver, United States", or null when there is nothing to add. */
  const example = useCallback(
    (video: AcademyVideo) => {
      const ex = exampleToShow(video);
      if (!ex) return null;
      const where = ex.place ? `${ex.place}, ${country(ex.country)}` : country(ex.country);
      return t('videos.example', { defaultValue: 'Example: {{place}}', place: where });
    },
    [t, country],
  );

  /** "Subtitles: German, Russian", in the reader's language, or null. */
  const subtitles = useCallback(
    (video: AcademyVideo) =>
      video.subtitles?.length
        ? t('videos.subtitles', {
            defaultValue: 'Subtitles: {{languages}}',
            languages: fmtList(video.subtitles.map(language)),
          })
        : null,
    [t, language],
  );
  /** "Audio tracks: English", or null when only the spoken language exists. */
  const audioTracks = useCallback(
    (video: AcademyVideo) =>
      video.audioTracks?.length
        ? t('videos.audio_tracks', {
            defaultValue: 'Audio tracks: {{languages}}',
            languages: fmtList(video.audioTracks.map(language)),
          })
        : null,
    [t, language],
  );
  /** Compact card form, "subtitles: DE, RU +3": codes, at most three named. */
  const subtitlesShort = useCallback(
    (video: AcademyVideo) => {
      const codes = video.subtitles ?? [];
      if (!codes.length) return null;
      const shown = fmtList(codes.slice(0, 3).map((c) => c.toUpperCase()));
      const more = codes.length > 3 ? ` +${codes.length - 3}` : '';
      return t('videos.subtitles_short', { defaultValue: 'subtitles: {{languages}}', languages: shown + more });
    },
    [t],
  );

  return {
    role,
    stage,
    stageShort,
    result,
    country,
    language,
    series,
    example,
    subtitles,
    audioTracks,
    subtitlesShort,
  };
}

export type VideoLabels = ReturnType<typeof useVideoLabels>;
