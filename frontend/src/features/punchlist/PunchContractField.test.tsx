import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { listContracts } from '@/features/contracts/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { updatePunchItem, type PunchItem } from './api';
import { PunchContractAssignment, PunchContractField } from './PunchContractField';

vi.mock('@/features/contracts/api', () => ({ listContracts: vi.fn() }));
vi.mock('./api', () => ({ updatePunchItem: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

function wrap(child: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{child}</QueryClientProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ userRole: 'editor' });
  vi.mocked(listContracts).mockResolvedValue({ items: [{ id: 'c1', code: 'C1', title: 'Main works' }], total: 1 } as never);
  vi.mocked(updatePunchItem).mockResolvedValue({} as PunchItem);
});

describe('explicit punch contract ownership', () => {
  it('keeps old items unassigned and offers contracts beyond the first page', async () => {
    vi.mocked(listContracts).mockResolvedValueOnce({ items: [{ id: 'c1', code: 'C1', title: 'First' }], total: 2 } as never)
      .mockResolvedValueOnce({ items: [{ id: 'c2', code: 'C2', title: 'Second' }], total: 2 } as never);
    const onChange = vi.fn();
    wrap(<PunchContractField projectId="p1" value={null} onChange={onChange} />);
    await screen.findByRole('option', { name: /Second/ });
    expect(screen.getByRole('combobox')).toHaveValue('');
    expect(screen.getByRole('option', { name: 'common.not_set' })).toBeInTheDocument();
    expect(listContracts).toHaveBeenNthCalledWith(2, { project_id: 'p1', offset: 1, limit: 100 });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'c2' } });
    expect(onChange).toHaveBeenCalledWith('c2');
  });

  it('sends an explicit null to clear a contract and refreshes the item', async () => {
    const onSaved = vi.fn();
    wrap(<PunchContractAssignment item={{ id: 'i1', project_id: 'p1', contract_id: 'c1' } as PunchItem} onSaved={onSaved} />);
    await screen.findByRole('option', { name: /Main works/ });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } });
    await waitFor(() => expect(updatePunchItem).toHaveBeenCalledWith('i1', { contract_id: null }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it('does not offer a viewer an editable contract selector', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    wrap(<PunchContractAssignment item={{ id: 'i1', project_id: 'p1' } as PunchItem} onSaved={vi.fn()} />);
    await screen.findByRole('option', { name: /Main works/ });
    expect(screen.getByRole('combobox')).toBeDisabled();
    expect(updatePunchItem).not.toHaveBeenCalled();
  });
});
