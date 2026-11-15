// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The chip exists because the header used to say nothing when no pack was
// applied, which is the state a stock install is actually in: eighteen packs
// on disk, active_slug null. So the no-pack rendering is the first test here,
// not an edge case appended to the end.
//
// Assertions are on data attributes and hrefs rather than on translated text.
// Every string in the component is an i18n key, and asserting on the English
// default would make the suite pass or fail on whether a translation loaded,
// which is a different question from whether the chip resolved the right pack.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const hookMock = vi.hoisted(() => ({
  usePartnerPack: vi.fn(),
  useInstalledPacks: vi.fn(),
  partnerLogoUrl: vi.fn(() => '/api/v1/partner-pack/logo'),
}));
vi.mock('@/shared/hooks/usePartnerPack', () => hookMock);

const demoPack = vi.hoisted(() => ({ value: { inDemo: false, manifest: null as unknown } }));
vi.mock('@/shared/hooks/useDemoPack', () => ({ useDemoPack: () => demoPack.value }));

import { ActivePackChip } from './ActivePackChip';

const PACKS = [
  {
    slug: 'uk-jct',
    partner_name: 'UK JCT',
    type: 'country',
    default_locale: 'en-GB',
    metadata: { country: 'GB' },
    branding: { primary_color: '#123456', accent_color: null },
  },
  {
    slug: 'china-gbt50500',
    partner_name: 'China GB/T 50500',
    type: 'country',
    default_locale: 'zh-CN',
    metadata: { country: 'CN' },
    branding: { primary_color: '#654321', accent_color: null },
  },
];

function mountWith(activeSlug: string | null, isLoading = false) {
  hookMock.useInstalledPacks.mockReturnValue({
    isLoading,
    data: isLoading ? undefined : { active_slug: activeSlug, installed: PACKS },
  });
  return render(
    <MemoryRouter>
      <ActivePackChip />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  cleanup();
  hookMock.useInstalledPacks.mockReset();
  demoPack.value = { inDemo: false, manifest: null };
});

describe('<ActivePackChip />', () => {
  it('still says something when no pack is applied', () => {
    // The state the founder reported: eighteen packs available, none applied,
    // and the header silent. "No pack" and "a pack I have not noticed" look
    // identical from inside the app and produce different numbers.
    mountWith(null);
    const chip = screen.getByTestId('active-pack-chip');
    expect(chip.getAttribute('data-pack-state')).toBe('none');
    expect(chip.getAttribute('href')).toBe('/modules?tab=packs');
  });

  it('names the applied pack, and the two states are not the same rendering', () => {
    // Written as a comparison rather than as two independent checks: the
    // deployment this was built on has active_slug null, so a chip that never
    // consulted it would render the empty state in both calls and a pair of
    // one-sided assertions would both pass on it.
    const none = mountWith(null).container.innerHTML;
    cleanup();
    mountWith('china-gbt50500');

    const chip = screen.getByTestId('active-pack-chip');
    expect(chip.getAttribute('data-pack-state')).toBe('applied');
    expect(chip.getAttribute('data-pack-slug')).toBe('china-gbt50500');
    expect(chip.outerHTML).not.toBe(none);
    // The pack's country is what identifies it, so the emblem must be the flag
    // and not the fallback monogram.
    expect(chip.querySelector('[data-pack-emblem]')?.getAttribute('data-country')).toBe('cn');
  });

  it('says nothing at all while the pack list is in flight', () => {
    // "None" during loading would be wrong for every reader who does have a
    // pack, and would flip a moment later.
    const { container } = mountWith(null, true);
    expect(container.firstChild).toBeNull();
  });

  it('does not claim a pack that is applied but not on this machine', () => {
    // active_slug naming a pack absent from the list is what an operator sees
    // mid-upgrade, when the pinned pack has been removed from disk. Inventing
    // a name for it would be worse than the empty state.
    mountWith('pack-that-was-removed');
    expect(screen.getByTestId('active-pack-chip').getAttribute('data-pack-state')).toBe('none');
  });

  it('in an open demo names the demo project pack, not the applied one', () => {
    // One shared demo account carries the US pack; the London demo is British.
    demoPack.value = { inDemo: true, manifest: PACKS[0] };
    mountWith('china-gbt50500');
    const chip = screen.getByTestId('active-pack-chip');
    expect(chip.getAttribute('data-pack-slug')).toBe('uk-jct');
  });

  it('in an open demo without a pack for its country claims none', () => {
    demoPack.value = { inDemo: true, manifest: null };
    mountWith('china-gbt50500');
    expect(screen.queryByTestId('active-pack-chip')).toBeNull();
  });
});
