// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ProjectWorksField } from '../ProjectWorksField';

// A project's works decide whether a French contract starts from the public
// procurement code or from loi 71-584. "Not recorded" must reach the server as
// null, never as an empty string the schema would reject.
describe('ProjectWorksField', () => {
  it('shows a project with no recorded works as not recorded', () => {
    render(<ProjectWorksField id="w" value={null} onChange={() => {}} />);
    const select = screen.getByLabelText('Public or private client') as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(screen.getByRole('option', { name: 'Not recorded' })).toBeInTheDocument();
  });

  it('hands back public, private, and null for not recorded', () => {
    const onChange = vi.fn();
    render(<ProjectWorksField id="w" value="private" onChange={onChange} />);
    const select = screen.getByLabelText('Public or private client');
    fireEvent.change(select, { target: { value: 'public' } });
    fireEvent.change(select, { target: { value: '' } });
    expect(onChange.mock.calls).toEqual([['public'], [null]]);
  });
});
