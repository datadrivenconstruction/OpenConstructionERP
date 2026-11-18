// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Whether a bill shows the norm code and labour grade columns: only when the
// project's country pack declares a norm base. For every other market the
// profile answers `available: false` and the grid gets null.

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { normPricingApi } from './api';

export interface NormBaseColumns {
  classificationKey: string;
  gradeField: string;
}

export function useNormBaseColumns(projectId: string | null | undefined): NormBaseColumns | null {
  const { i18n } = useTranslation();
  const locale = i18n.language;
  const { data } = useQuery({
    queryKey: ['norm-pricing', 'profile', projectId, locale],
    queryFn: () => normPricingApi.profile(projectId as string, locale),
    enabled: Boolean(projectId),
    staleTime: 5 * 60_000,
  });
  const base = data?.available ? data.norm_bases[0] : undefined;
  const key = base?.classification_key ?? '';
  const field = base?.grade_field || 'grade';
  return useMemo(() => (key ? { classificationKey: key, gradeField: field } : null), [key, field]);
}
