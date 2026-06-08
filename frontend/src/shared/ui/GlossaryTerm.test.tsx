import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GlossaryTerm } from './GlossaryTerm';

// Note: the test i18n mock returns the `defaultValue`, and GlossaryTerm
// looks the definition up with `defaultValue: ''`. So in tests every term
// resolves to "no definition yet" — which exercises the graceful-degrade
// path the platform relies on until the founder-signed glossary lands.

describe('GlossaryTerm', () => {
  it('renders the label alone when the term has no definition yet', () => {
    const { container } = render(<GlossaryTerm term="evm" label={<span>EVM</span>} />);
    expect(screen.getByText('EVM')).toBeInTheDocument();
    // No (i) trigger when there is nothing to show.
    expect(container.querySelector('button')).toBeNull();
  });

  it('renders nothing when there is neither a definition nor a label', () => {
    const { container } = render(<GlossaryTerm term="evm" />);
    expect(container.firstChild).toBeNull();
  });
});
