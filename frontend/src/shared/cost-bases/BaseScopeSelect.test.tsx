// @ts-nocheck
/**
 * BaseScopeSelect + cost-database store scope contract (v3-P8 multibase).
 *
 * Two things are pinned:
 *
 *  1. The store's scope / loadedBases state and its mutators
 *     (setScope / toggleScopeBase / clearScope / setLoadedBases /
 *     addLoadedBase / removeLoadedBase / clearLoadedBases) behave as a
 *     scope model where an empty scope means "all loaded bases", and
 *     setActiveRegion keeps its back-compat single-base selection.
 *
 *  2. BaseScopeSelect is additive and self-hiding: with zero or one loaded
 *     base it renders nothing (today's behaviour, no new chrome); the scope
 *     affordance only appears once two or more bases are loaded.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useCostDatabaseStore, REGION_MAP } from '@/stores/useCostDatabaseStore';
import { BaseScopeSelect } from './BaseScopeSelect';

const store = () => useCostDatabaseStore.getState();

function resetStore() {
  // Empty scope + no loaded bases is the neutral starting point; an empty
  // scope means "every loaded base is in scope".
  useCostDatabaseStore.setState({ scope: [], loadedBases: [] });
}

// ── Store: loaded bases ────────────────────────────────────────────────────

describe('useCostDatabaseStore loaded bases', () => {
  beforeEach(resetStore);

  it('setLoadedBases replaces the loaded set', () => {
    store().setLoadedBases(['DE_BERLIN', 'CH_ZURICH']);
    expect(store().loadedBases).toEqual(['DE_BERLIN', 'CH_ZURICH']);
  });

  it('addLoadedBase and removeLoadedBase mutate the set', () => {
    store().setLoadedBases(['DE_BERLIN']);
    store().addLoadedBase('CH_ZURICH');
    expect(store().loadedBases).toContain('CH_ZURICH');
    store().removeLoadedBase('DE_BERLIN');
    expect(store().loadedBases).not.toContain('DE_BERLIN');
    expect(store().loadedBases).toContain('CH_ZURICH');
  });

  it('addLoadedBase does not duplicate an already-loaded base', () => {
    store().setLoadedBases(['DE_BERLIN']);
    store().addLoadedBase('DE_BERLIN');
    expect(store().loadedBases).toEqual(['DE_BERLIN']);
  });

  it('clearLoadedBases empties the set', () => {
    store().setLoadedBases(['DE_BERLIN', 'CH_ZURICH']);
    store().clearLoadedBases();
    expect(store().loadedBases).toEqual([]);
  });
});

// ── Store: scope ───────────────────────────────────────────────────────────

describe('useCostDatabaseStore scope', () => {
  beforeEach(resetStore);

  it('setScope replaces the scope', () => {
    store().setScope(['DE_BERLIN', 'CH_ZURICH']);
    expect(store().scope).toEqual(['DE_BERLIN', 'CH_ZURICH']);
  });

  it('toggleScopeBase adds then removes a base', () => {
    store().toggleScopeBase('DE_BERLIN');
    expect(store().scope).toContain('DE_BERLIN');
    store().toggleScopeBase('DE_BERLIN');
    expect(store().scope).not.toContain('DE_BERLIN');
  });

  it('clearScope empties the scope (back to "all loaded")', () => {
    store().setScope(['DE_BERLIN']);
    store().clearScope();
    expect(store().scope).toEqual([]);
  });

  it('setActiveRegion keeps the back-compat single-base selection', () => {
    store().setActiveRegion('DE_BERLIN');
    expect(store().activeRegion).toBe('DE_BERLIN');
  });

  it('REGION_MAP still exposes label / flag / currency for known bases', () => {
    expect(REGION_MAP.DE_BERLIN).toBeTruthy();
    expect(REGION_MAP.DE_BERLIN.currency).toBe('EUR');
    expect(REGION_MAP.DE_BERLIN.flag).toBe('de');
  });
});

// ── BaseScopeSelect: self-hide contract ────────────────────────────────────

describe('BaseScopeSelect self-hide', () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  function renderSelect() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <BaseScopeSelect />
      </QueryClientProvider>,
    );
  }

  it('renders nothing when no base is loaded', () => {
    const { container } = renderSelect();
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when exactly one base is loaded (no new chrome)', () => {
    useCostDatabaseStore.setState({ loadedBases: ['DE_BERLIN'], scope: [] });
    const { container } = renderSelect();
    expect(container).toBeEmptyDOMElement();
  });

  it('surfaces the scope affordance once two or more bases are loaded', () => {
    useCostDatabaseStore.setState({
      loadedBases: ['DE_BERLIN', 'CH_ZURICH'],
      scope: [],
    });
    const { container } = renderSelect();
    expect(container).not.toBeEmptyDOMElement();
  });
});
