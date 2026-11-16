// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared reads of the group's companies.
 *
 * Every picker and filter asks `useCompaniesUi()` first: with fewer than two
 * active companies it answers `multiCompany: false` and the caller renders
 * nothing, so a single-company install sees no new control anywhere.
 */

import { useQuery } from '@tanstack/react-query';

import { LEGAL_ENTITIES_KEY, LEGAL_ENTITIES_UI_KEY, legalEntitiesApi, type LegalEntity } from './api';

export function useCompaniesUi() {
  const q = useQuery({
    queryKey: LEGAL_ENTITIES_UI_KEY,
    queryFn: legalEntitiesApi.uiState,
    staleTime: 60_000,
    retry: false,
  });
  return {
    multiCompany: q.data?.multi_company ?? false,
    defaultEntityId: q.data?.default_entity_id ?? null,
    myEntityIds: q.data?.my_entity_ids ?? [],
    isLoading: q.isLoading,
  };
}

export function useCompanies(enabled = true) {
  return useQuery({
    queryKey: [...LEGAL_ENTITIES_KEY, 'list'],
    queryFn: () => legalEntitiesApi.list(true),
    staleTime: 60_000,
    enabled,
    select: (data): LegalEntity[] => data.items,
  });
}

/** The company a new project defaults to: the person's only company, else the default one. */
export function defaultCompanyFor(myEntityIds: string[], defaultEntityId: string | null): string | null {
  if (myEntityIds.length === 1) return myEntityIds[0] ?? null;
  return defaultEntityId;
}
