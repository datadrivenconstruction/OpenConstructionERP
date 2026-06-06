// OpenConstructionERP - AI tools cross-link strip (CONN-82).
//
// The four AI surfaces (Agents, Cost Advisor, Chat, Quick Estimate) are
// siblings that never pointed at each other. AiToolsStrip renders the set with
// the current surface dropped, so each page links to the others. These tests
// pin that the current route is excluded and the rest are reachable links.

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AiToolsStrip } from '../AgentsPage';

function renderStrip(current: string) {
  return render(
    <MemoryRouter>
      <AiToolsStrip current={current} />
    </MemoryRouter>,
  );
}

describe('AiToolsStrip (CONN-82)', () => {
  it('drops the current surface and links to the three others', () => {
    renderStrip('/ai-agents');
    const links = screen.getAllByRole('link');
    const hrefs = links.map((a) => a.getAttribute('href'));
    expect(hrefs).not.toContain('/ai-agents');
    expect(hrefs).toEqual(expect.arrayContaining(['/advisor', '/chat', '/ai-estimate']));
    expect(links).toHaveLength(3);
  });

  it('excludes /advisor when rendered on the advisor page', () => {
    renderStrip('/advisor');
    const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'));
    expect(hrefs).not.toContain('/advisor');
    expect(hrefs).toEqual(expect.arrayContaining(['/ai-agents', '/chat', '/ai-estimate']));
  });
});
