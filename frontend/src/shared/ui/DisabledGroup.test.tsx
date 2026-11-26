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

  it('leaves the controls active when there is no reason', () => {
    render(
      <DisabledGroup>
        <button type="button">Save</button>
      </DisabledGroup>,
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
  });
});
