// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Who the reader is, as far as the Videos page can tell, for "Recommended for
// you". Nothing here is written anywhere but the page's own store.
//
// Role: the one chosen on this page, else the first role picked on the Cases
// hub. The profile has no role field, so there is nothing further to ask.
//
// Market: the one chosen on this page, else the active project's country,
// else the market picked on the Cases hub, else the market the interface
// language points at. A market no video teaches is kept as it is rather than
// dropped: the reader then gets the videos that apply anywhere, and the page
// can say so, which is better than quietly showing another country's rules.

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { projectsApi } from '@/features/projects/api';
import { homeMarketForLanguage, normalizeLanguageTag } from '@/features/cases/homeMarket';
import { useCasesStore } from '@/features/cases/useCasesStore';
import type { ProfessionalRole } from '@/features/cases/types';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { catalogMarkets } from './academy';
import { useVideosStore } from './useVideosStore';

export type RoleSource = 'chosen' | 'cases' | null;
export type MarketSource = 'chosen' | 'project' | 'cases' | 'language' | 'any' | null;

export interface VideoContext {
  role: ProfessionalRole | null;
  roleSource: RoleSource;
  market: string | null;
  marketSource: MarketSource;
  /** The interface language's base code, for ranking. */
  language: string;
  /** True when a market is known but no video teaches it. */
  marketUncovered: boolean;
}

export function useVideoContext(): VideoContext {
  const { i18n } = useTranslation();
  const chosenRole = useVideosStore((s) => s.role);
  const chosenMarket = useVideosStore((s) => s.market);
  const casesRole = useCasesStore((s) => s.roles[0] ?? null);
  const casesRegion = useCasesStore((s) => s.region);
  const projectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: project } = useQuery({
    queryKey: ['projects', 'detail', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId && chosenMarket === 'auto',
    staleTime: 5 * 60_000,
  });

  const language = (normalizeLanguageTag(i18n.language).split('-')[0] || 'en').toLowerCase();

  let role: ProfessionalRole | null = null;
  let roleSource: RoleSource = null;
  if (chosenRole) {
    role = chosenRole;
    roleSource = 'chosen';
  } else if (casesRole) {
    role = casesRole;
    roleSource = 'cases';
  }

  let market: string | null = null;
  let marketSource: MarketSource = null;
  const projectCountry = project?.country_code?.toUpperCase();
  if (chosenMarket === 'any') {
    marketSource = 'any';
  } else if (chosenMarket !== 'auto') {
    market = chosenMarket;
    marketSource = 'chosen';
  } else if (projectCountry && /^[A-Z]{2}$/.test(projectCountry)) {
    market = projectCountry;
    marketSource = 'project';
  } else if (casesRegion && casesRegion !== 'all') {
    market = casesRegion;
    marketSource = 'cases';
  } else {
    market = homeMarketForLanguage(i18n.language, catalogMarkets());
    marketSource = market ? 'language' : null;
  }

  return {
    role,
    roleSource,
    market,
    marketSource,
    language,
    marketUncovered: !!market && !catalogMarkets().includes(market),
  };
}
