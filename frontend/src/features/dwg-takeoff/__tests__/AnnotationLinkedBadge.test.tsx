// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { AnnotationLinkedBadge } from '../AnnotationLinkedBadge';

describe('AnnotationLinkedBadge', () => {
  it('shows a titled indicator when the annotation is linked', () => {
    render(<AnnotationLinkedBadge linkedBoqPositionId="pos-1" />);
    const badge = screen.getByTestId('annotation-linked-badge');
    expect(badge.getAttribute('title')).toBeTruthy();
  });

  it('renders nothing when the annotation is not linked', () => {
    const { container } = render(<AnnotationLinkedBadge linkedBoqPositionId={null} />);
    expect(container.firstChild).toBeNull();
  });
});
