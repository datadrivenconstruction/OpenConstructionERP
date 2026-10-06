// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cost-catalogue step of the wizard: what it pre-selects, when "Auto"
// is allowed, and what the session is told when the user picks Auto.

import { useState } from 'react';
import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import type { MatchReadiness } from '../api';
import {
  autoBlockedReason,
  preselectFor,
  sessionCatalogueValue,
  useCataloguePreselect,
} from '../catalogueChoice';

function readiness(over: Partial<MatchReadiness> = {}): MatchReadiness {
  return {
    can_match: true,
    blockers: [],
    warnings: [],
    project_region: 'Italy',
    project_language: 'it',
    project_country: 'IT',
    installed_languages: ['it', 'en'],
    recommended_catalogue: { region: 'IT_ROME', language: 'it', country_iso: 'IT', installed: true },
    bound_catalogue: null,
    can_change_catalogue: true,
    ...over,
  };
}

const LOADED = ['IT_ROME', 'USA_USD'];

function useHarness(r: MatchReadiness | undefined, loaded: string[]) {
  const [catalogueId, setCatalogueId] = useState<string | null>(null);
  const { choose } = useCataloguePreselect(r, loaded, catalogueId, setCatalogueId);
  return { catalogueId, choose };
}

describe('useCataloguePreselect', () => {
  it('pre-selects the recommended installed catalogue once', () => {
    const { result } = renderHook(() => useHarness(readiness(), LOADED));
    expect(result.current.catalogueId).toBe('IT_ROME');
  });

  it('keeps Auto once the user chose it', () => {
    const r = readiness();
    const { result, rerender } = renderHook(() => useHarness(r, LOADED));
    expect(result.current.catalogueId).toBe('IT_ROME');
    act(() => result.current.choose(null));
    rerender();
    expect(result.current.catalogueId).toBe(null);
  });

  it('does not replace a catalogue the project is already bound to', () => {
    // A custom import the registry does not know, or a binding people
    // confirmed matches against: Auto keeps it, a pre-select would not.
    const { result } = renderHook(() =>
      useHarness(readiness({ bound_catalogue: 'ACME-RATES-2026' }), LOADED),
    );
    expect(result.current.catalogueId).toBe(null);
  });

  it('does not guess when the project states no language', () => {
    const r = readiness({
      project_region: 'INTL',
      project_language: null,
      recommended_catalogue: null,
      warnings: [{ code: 'region_unknown', params: { region: 'INTL' } }],
    });
    const { result } = renderHook(() => useHarness(r, LOADED));
    expect(result.current.catalogueId).toBe(null);
  });

  it('waits for both answers before deciding', () => {
    let r: MatchReadiness | undefined;
    let loaded: string[] = [];
    const { result, rerender } = renderHook(() => useHarness(r, loaded));
    expect(result.current.catalogueId).toBe(null);
    r = readiness();
    rerender();
    expect(result.current.catalogueId).toBe(null);
    loaded = LOADED;
    rerender();
    expect(result.current.catalogueId).toBe('IT_ROME');
  });
});

describe('preselectFor', () => {
  it('ignores a recommendation that is not installed', () => {
    expect(preselectFor(readiness(), ['USA_USD'])).toBe(null);
  });
});

describe('autoBlockedReason', () => {
  it('blocks Auto when the region tells no language and nothing is bound', () => {
    const r = readiness({
      project_language: null,
      warnings: [{ code: 'region_unknown', params: { region: 'INTL' } }],
    });
    expect(autoBlockedReason(r)).toBe('region_unknown');
  });

  it('names a several-language group as such', () => {
    const r = readiness({
      project_region: 'Nordics',
      project_language: null,
      warnings: [{ code: 'region_language_unknown', params: { region: 'Nordics' } }],
    });
    expect(autoBlockedReason(r)).toBe('region_language_unknown');
  });

  it('allows Auto when the project is bound or states a language', () => {
    expect(autoBlockedReason(readiness())).toBe(null);
    expect(
      autoBlockedReason(readiness({ project_language: null, bound_catalogue: 'US' })),
    ).toBe(null);
    expect(autoBlockedReason(undefined)).toBe(null);
  });
});

describe('sessionCatalogueValue', () => {
  it('sends an empty string for Auto so the server clears the pick', () => {
    // The session PATCH ignores null ("field not sent") and clears on "".
    expect(sessionCatalogueValue(null)).toBe('');
    expect(sessionCatalogueValue('IT_ROME')).toBe('IT_ROME');
  });
});
