// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { SolutionPackage } from '../api';

const installPackages = vi.fn();
const seedPackageDemo = vi.fn();
vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  installPackages: (...a: unknown[]) => installPackages(...a),
  seedPackageDemo: (...a: unknown[]) => seedPackageDemo(...a),
}));
vi.mock('../applyLayout', () => ({ applyPackageLayout: vi.fn() }));

import { PackagePicker } from '../PackagePicker';

const pkg = (id: string, required: string[], demo: string | null = null, depends_on: string[] = []): SolutionPackage => ({
  id,
  icon: 'X',
  image: `illustration:${id}`,
  name_key: `packages.${id}.name`,
  value_key: `packages.${id}.value`,
  audience_key: `packages.${id}.audience`,
  required,
  optional: [],
  menu: [],
  widgets: [],
  demo_id: demo,
  depends_on,
});

const PACKAGES = [pkg('estimate_quote', ['boq', 'validation'], 'd1'), pkg('tender_procurement', ['tendering'], 'd2', ['estimate_quote'])];

function renderPicker(onInstalled = vi.fn()) {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <PackagePicker packages={PACKAGES} onInstalled={onInstalled} />
    </QueryClientProvider>,
  );
  return onInstalled;
}

describe('PackagePicker', () => {
  beforeEach(() => {
    installPackages.mockReset();
    seedPackageDemo.mockReset();
  });

  it('selecting a package selects the package it builds on and sums the modules', () => {
    renderPicker();
    const install = screen.getByRole('button', { name: /packages.install|Install/ });
    expect(install).toBeDisabled();
    fireEvent.click(screen.getByTestId('package-card-tender_procurement'));
    expect(screen.getByTestId('package-card-estimate_quote')).toHaveAttribute('aria-pressed', 'true');
    expect(install).not.toBeDisabled();
  });

  it('installs, seeds each demo and reports progress', async () => {
    installPackages.mockResolvedValue({
      installed: ['estimate_quote'],
      optional: [],
      modules: {},
      packaged: true,
      added: ['estimate_quote'],
      enabled_modules: ['boq'],
      demos: ['d1'],
    });
    seedPackageDemo.mockResolvedValue({ demo_id: 'd1' });
    const onInstalled = renderPicker();
    fireEvent.click(screen.getByTestId('package-card-estimate_quote'));
    fireEvent.click(screen.getByRole('button', { name: /packages.install|Install/ }));
    expect(await screen.findByTestId('package-install-progress')).toBeInTheDocument();
    await waitFor(() => expect(onInstalled).toHaveBeenCalled());
    expect(installPackages).toHaveBeenCalledWith(['estimate_quote']);
    expect(seedPackageDemo).toHaveBeenCalledWith('estimate_quote');
  });
});
