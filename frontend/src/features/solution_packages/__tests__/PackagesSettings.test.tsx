// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const removePackage = vi.fn();
vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  removePackage: (...a: unknown[]) => removePackage(...a),
  useSolutionPackages: () => ({
    isLoading: false,
    data: {
      packages: [
        {
          id: 'takeoff', icon: 'X', image: '', name_key: 'packages.takeoff.name', value_key: 'v', audience_key: 'a',
          required: ['takeoff'], optional: [], menu: [], widgets: [], demo_id: null, depends_on: [],
        },
      ],
      modules: [{ key: 'takeoff', depends: [] }],
      state: { installed: ['takeoff'], optional: [], modules: { takeoff: true }, packaged: true },
    },
  }),
}));

import { PackagesSettings } from '../PackagesSettings';

describe('PackagesSettings remove', () => {
  it('lists the modules removal hides and removes only after confirming', async () => {
    removePackage.mockResolvedValueOnce({ hidden: ['takeoff', 'dwg_takeoff'], removed: false });
    removePackage.mockResolvedValueOnce({ hidden: ['takeoff', 'dwg_takeoff'], removed: true });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PackagesSettings />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByTestId('package-remove-takeoff'));
    const alert = await screen.findByRole('alert');
    expect(removePackage).toHaveBeenLastCalledWith('takeoff', false);
    expect(alert.textContent).toContain('packages.remove_warning');
    fireEvent.click(screen.getByRole('button', { name: /packages.remove_confirm|Remove package/ }));
    await waitFor(() => expect(removePackage).toHaveBeenLastCalledWith('takeoff', true));
  });
});
