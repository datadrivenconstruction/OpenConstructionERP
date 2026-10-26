// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NotificationChannelsCard } from './NotificationChannelsCard';

describe('<NotificationChannelsCard>', () => {
  it('links to the preferences tab of the notifications page', () => {
    render(
      <MemoryRouter>
        <NotificationChannelsCard />
      </MemoryRouter>,
    );
    const link = screen.getByRole('link', { name: /Set notification channels/ });
    expect(link.getAttribute('href')).toBe('/notifications?tab=preferences');
  });
});
