// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The "Sites & weather" panel keeps the forecast opt-in, and the opt-in has to
// be reachable from the panel itself. Before this test the only switch lived on
// the projects page, so a user who never went there saw bare city names under a
// title promising weather and reported the panel as broken.
//
// WHAT THIS ASSERTS.
//   1. With the opt-in off, no request goes to the weather host (privacy guard
//      from 4c51b12ef still holds) and the switch reads "not pressed".
//   2. Clicking the switch in the panel turns the forecast on and the panel
//      asks the weather host for the site's coordinates.
//
// Run: npx vitest run src/features/dashboard/components/DashboardSitesPanel.test.tsx

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { DashboardSitesPanel } from './DashboardSitesPanel';
import { useWidgetSettingsStore } from '@/stores/useWidgetSettingsStore';

const projects = [{ id: 'p1', name: 'School', city: 'Ludwigsburg', lat: 48.9, lng: 9.19 }];

function renderPanel() {
  return render(
    <MemoryRouter>
      <DashboardSitesPanel projects={projects} />
    </MemoryRouter>,
  );
}

describe('DashboardSitesPanel weather switch', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch {
      // storage may be unavailable; the store state below is what matters
    }
    useWidgetSettingsStore.setState({ projectWeatherEnabled: false });
    fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        daily: {
          time: ['2026-10-17', '2026-10-18'],
          weather_code: [0, 61],
          temperature_2m_min: [5, 6],
          temperature_2m_max: [14, 12],
          precipitation_sum: [0, 3],
        },
      }),
    }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('sends nothing to the weather host while the opt-in is off', () => {
    renderPanel();
    expect(screen.getByText('Ludwigsburg')).toBeTruthy();
    const toggle = screen.getByRole('button', { pressed: false });
    expect(toggle.textContent).toContain('Weather');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('turns the forecast on from the panel itself', async () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { pressed: false }));
    expect(useWidgetSettingsStore.getState().projectWeatherEnabled).toBe(true);
    expect(screen.getByRole('button', { pressed: true })).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain('open-meteo.com');
    expect(url).toContain('latitude=48.9');
  });
});
