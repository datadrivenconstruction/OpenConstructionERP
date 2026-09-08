// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The hub is the only way into the twenty country routes, so "does it cover all
// twenty" is the whole of its job and the thing that has to stay true.
//
// It matters because of how the gap it closes was allowed to open. The twenty
// routes were mounted, tested, translated and shipped, and no menu row, journey
// chip, playbook step, help entry or command-palette result anywhere under
// `frontend/src` pointed at a single one of them: measured over 2234 non-test
// source files, the count of in-app links to `/uk-nrm-exchange` and its
// nineteen siblings was zero. Every gate the repo owns was green, because every
// gate asked whether the route mounts, never whether anyone can get to it.
//
// So this file asserts reachability, not rendering. Card count alone would not
// do it — twenty cards all pointing at Spain would pass a count — so it pairs
// every registry entry with the href it must carry, and asserts the hrefs are
// exactly the manifest's country route paths, as sets, in both directions. A
// twenty-first country added to `COUNTRY_TEMPLATES` gets a route and a card or
// this goes red.

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import RegionalExchangeHubPage from './RegionalExchangeHubPage';
import { COUNTRY_TEMPLATES } from './regionalRegistry';
import { manifest } from './manifest';

const HUB_PATH = '/regional-exchange';

function renderHub() {
  return render(
    <MemoryRouter initialEntries={[HUB_PATH]}>
      <RegionalExchangeHubPage />
    </MemoryRouter>,
  );
}

describe('the regional exchange hub', () => {
  it('is the route the manifest enters the module by', () => {
    // First, so `routes[0]` is the picker and not whichever country happens to
    // sort first in the registry.
    expect(manifest.routes[0]?.path).toBe(HUB_PATH);
    expect(manifest.routes).toHaveLength(COUNTRY_TEMPLATES.length + 1);
  });

  it('offers a card for every country the registry carries', () => {
    renderHub();
    for (const tpl of COUNTRY_TEMPLATES) {
      const card = screen.getByTestId(`regional-hub-card-${tpl.id}`);
      expect(card).toHaveAttribute('href', `/${tpl.routeSlug}`);
      // The label is the one thing that tells two cards apart, and it is
      // deliberately not translated (a measurement standard's name travels
      // with it), so assert the registry's own wording reached the screen.
      expect(card).toHaveTextContent(tpl.label);
    }
  });

  it('reaches every country route the manifest mounts, and no other path', () => {
    renderHub();
    const linked = new Set(
      COUNTRY_TEMPLATES.map(
        (tpl) => screen.getByTestId(`regional-hub-card-${tpl.id}`).getAttribute('href') ?? '',
      ),
    );
    const mounted = new Set(
      manifest.routes.map((r) => r.path).filter((p) => p !== HUB_PATH),
    );
    // Two sets built from different sources — the rendered DOM and the route
    // table — so equality is a claim about both, not a restatement of one.
    expect([...linked].sort()).toEqual([...mounted].sort());
    expect(linked.size).toBe(COUNTRY_TEMPLATES.length);
  });
});
