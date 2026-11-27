import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DisabledGroup } from './DisabledGroup';

describe('DisabledGroup', () => {
  it('keeps its controls on screen and disables them when given a reason', () => {
    render(
      <DisabledGroup reason="Only an administrator can do this.">
        <input aria-label="code" />
        <button type="button">Save</button>
      </DisabledGroup>,
    );
    expect(screen.getByLabelText('code')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('group')).toHaveAttribute('title', 'Only an administrator can do this.');
  });

  it('prints the reason where a touch user can read it and links it to the group', () => {
    render(
      <DisabledGroup reason="Only an administrator can do this.">
        <button type="button">Save</button>
      </DisabledGroup>,
    );
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Only an administrator can do this.');
    expect(screen.getByRole('group')).toHaveAttribute('aria-describedby', note.id);
  });

  it('leaves the controls active when there is no reason', () => {
    render(
      <DisabledGroup>
        <button type="button">Save</button>
      </DisabledGroup>,
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.queryByRole('note')).toBeNull();
  });
});
