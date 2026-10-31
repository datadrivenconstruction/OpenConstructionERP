import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { RequiredCertificatesInput, addCertificate } from './RequiredCertificatesInput';

describe('addCertificate', () => {
  it('trims, ignores blanks and case-insensitive duplicates', () => {
    expect(addCertificate(['Crane Operator'], '  First Aid ')).toEqual(['Crane Operator', 'First Aid']);
    expect(addCertificate(['Crane Operator'], 'crane operator')).toEqual(['Crane Operator']);
    expect(addCertificate([], '   ')).toEqual([]);
  });
});

describe('RequiredCertificatesInput', () => {
  it('adds on Enter, removes a chip, offers suggestions', () => {
    const onChange = vi.fn();
    const { container } = render(
      <RequiredCertificatesInput value={['Crane Operator']} onChange={onChange} suggestions={['First Aid']} />,
    );
    expect(container.querySelector('datalist option')?.getAttribute('value')).toBe('First Aid');
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: 'First Aid' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith(['Crane Operator', 'First Aid']);
    fireEvent.click(screen.getByRole('button', { name: /Remove Crane Operator/ }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});
