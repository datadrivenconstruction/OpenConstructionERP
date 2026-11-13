// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ACADEMY_ITEMS } from './academyItems.generated';
import { AcademyItemCard } from './AcademyItemLinks';
import { CourseCover } from './CourseCover';
import { COVER_ACCENT, coverSeed, coverSubject } from './courseCovers';

describe('course covers', () => {
  it('give every shipped course a subject of its own, never the kind fallback', () => {
    for (const item of ACADEMY_ITEMS.filter((i) => i.kind === 'course')) {
      expect(['checklist', 'guide'], item.id).not.toContain(coverSubject(item));
    }
  });

  it('resolve every shipped item to a cover with a brand accent', () => {
    for (const item of ACADEMY_ITEMS) expect(COVER_ACCENT[coverSubject(item)], item.id).toBeDefined();
  });

  it('fall back by kind when nothing names a subject', () => {
    expect(coverSubject({ topics: ['unknown'], routes: [], kind: 'checklist' })).toBe('checklist');
    expect(coverSubject({ topics: [], routes: [], kind: 'article' })).toBe('guide');
    expect(coverSubject({ topics: [], routes: ['/boq'], kind: 'course' })).toBe('estimate');
    expect(coverSubject({ topics: ['BOQ', 'Schedule'], routes: [], kind: 'course' })).toBe('estimate');
  });

  it('draw from tokens only, small, with no picture fetched', () => {
    for (const item of ACADEMY_ITEMS) {
      const svg = renderToStaticMarkup(<CourseCover item={item} />);
      expect(svg.length, item.id).toBeLessThan(15_000);
      expect(svg).not.toMatch(/#[0-9a-f]{6}\b/i);
      expect(svg).not.toMatch(/<image|href="http/);
    }
  });

  it('vary covers of one subject by id', () => {
    expect(coverSeed('course:a')).not.toBe(coverSeed('course:b'));
    expect(coverSeed('course:a')).toBe(coverSeed('course:a'));
  });

  it('put the cover on every card and keep the title as text', () => {
    const item = ACADEMY_ITEMS.find((i) => i.kind === 'course')!;
    const { getByTestId, getByText } = render(<AcademyItemCard item={item} media />);
    expect(getByTestId('academy-item-media').querySelector('[data-testid="course-cover"]')).not.toBeNull();
    expect(getByText(item.title)).toBeTruthy();
    expect(getByTestId('academy-item-media').querySelector('img')).toBeNull();
  });
});
