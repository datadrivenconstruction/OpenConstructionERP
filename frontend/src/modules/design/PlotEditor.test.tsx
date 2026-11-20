// Plot outline entered as coordinates (no pointer): validation, storing, localised measures.
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PlotEditor } from './PlotEditor';
import { PLOT_POINTER, newBrief } from './data/briefModel';

vi.mock('react-i18next', async () => (await import('./testStrings')).i18nMock());

vi.mock('./PlotMap', () => ({ default: () => <div />, PlotMap: () => <div /> }));

function mount(onChange = vi.fn()) {
  const doc = newBrief({ id: 'p1', country_code: 'DE' }, 'b1');
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PlotEditor doc={doc} errors={[]} focus={null} onChange={onChange} provenance={{ onConfirm: null }} />
    </QueryClientProvider>,
  );
  return onChange;
}

async function enter(user: ReturnType<typeof userEvent.setup>, corners: [string, string][]) {
  for (const [i, [lon, lat]] of corners.entries()) {
    await user.type(screen.getByLabelText(`Longitude ${i + 1}`), lon);
    await user.type(screen.getByLabelText(`Latitude ${i + 1}`), lat);
  }
}

describe('corner coordinates', () => {
  it('a valid outline typed as text reaches the brief as a closed GeoJSON ring', async () => {
    const onChange = mount();
    await enter(userEvent.setup(), [['13.4', '52.5'], ['13.4015', '52.5'], ['13.4015', '52.5009']]);
    const [pointer, polygon] = onChange.mock.calls.at(-1)!;
    expect(pointer).toBe(PLOT_POINTER);
    expect(polygon.coordinates[0]).toHaveLength(4);
    expect(polygon.coordinates[0][0]).toEqual(polygon.coordinates[0][3]);
  });

  it('three points on one line say so instead of "too few points"', async () => {
    const onChange = mount();
    await enter(userEvent.setup(), [['10', '50'], ['10.001', '50'], ['10.002', '50']]);
    expect(await screen.findByText(/lie on one line/i)).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('a hex or exponent entry is flagged, not stored', async () => {
    const onChange = mount();
    await userEvent.setup().type(screen.getByLabelText('Longitude 1'), '1e1');
    expect(screen.getByLabelText('Longitude 1').getAttribute('aria-invalid')).toBe('true');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('an outline above the size bound is refused with the bound named', async () => {
    mount();
    await enter(userEvent.setup(), [['0', '0'], ['1', '0'], ['1', '1']]);
    expect(await screen.findByText(/more than 100 km²/)).toBeTruthy();
  });
});
