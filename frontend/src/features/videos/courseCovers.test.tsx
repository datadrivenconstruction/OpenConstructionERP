// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ACADEMY_ITEMS } from './academyItems.generated';
import { AcademyItemCard } from './AcademyItemLinks';
import { stepRange, stepStates } from './CourseCardCover';
import { CourseCover } from './CourseCover';
import { COVER_ACCENT, coverSeed, coverSubject } from './courseCovers';

const ROOT = [resolve(process.cwd(), '..'), process.cwd()].find((p) => existsSync(resolve(p, 'frontend/src/app/App.tsx')))!;
const PUBLIC = resolve(ROOT, 'frontend/public/academy-courses');

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

  it('put the project photo, role and path on a course card and keep the title as text', () => {
    const item = ACADEMY_ITEMS.find((i) => i.kind === 'course' && i.steps && i.steps.length > 1 && i.people)!;
    const { getByTestId, getByText } = render(<AcademyItemCard item={item} media />);
    const media = getByTestId('academy-item-media');
    const photo = media.querySelector<HTMLImageElement>('[data-testid="course-photo"]')!;
    expect(photo.getAttribute('src')).toMatch(/academy-courses\/[a-z0-9-]+\.webp$/);
    expect(photo.getAttribute('loading')).toBe('lazy');
    expect(media.querySelector('[data-testid="course-role"]')).not.toBeNull();
    const steps = [...getByTestId('course-path').querySelectorAll('li')];
    expect(steps).toHaveLength(item.steps!.length);
    expect(steps.map((li) => li.getAttribute('data-state'))).toEqual(['current', ...item.steps!.slice(1).map(() => 'ahead')]);
    expect(getByText(item.title)).toBeTruthy();
  });

  it('show every step done once the course is marked done', () => {
    const item = ACADEMY_ITEMS.find((i) => i.kind === 'course' && i.steps && i.steps.length > 1)!;
    const { getByTestId } = render(<AcademyItemCard item={item} media done />);
    const states = [...getByTestId('course-path').querySelectorAll('li')].map((li) => li.getAttribute('data-state'));
    expect(new Set(states)).toEqual(new Set(['done']));
  });

  it('keep the drawn cover, without a path, on checklists and guides', () => {
    for (const kind of ['checklist', 'article'] as const) {
      const item = ACADEMY_ITEMS.find((i) => i.kind === kind)!;
      const { getByTestId, queryByTestId, unmount } = render(<AcademyItemCard item={item} media />);
      const media = getByTestId('academy-item-media');
      expect(media.querySelector('[data-testid="course-cover"]')).not.toBeNull();
      expect(media.querySelector('img')).toBeNull();
      expect(queryByTestId('course-path')).toBeNull();
      unmount();
    }
  });

  it('number steps by the tasks they cover', () => {
    expect(stepStates([{ module: 'boq', from: 1, to: 2 }, { module: 'contracts', from: 3, to: 3 }], false)).toEqual(['current', 'ahead']);
    expect(stepRange({ module: 'boq', from: 1, to: 2 })).toBe('1–2');
    expect(stepRange({ module: 'contracts', from: 3, to: 3 })).toBe('3');
  });

  it('ship a small photo for every course and every portrait it names', () => {
    let total = 0;
    for (const i of ACADEMY_ITEMS.filter((x) => x.kind === 'course')) {
      const file = resolve(PUBLIC, `${i.id.split(':')[1]}.webp`);
      expect(existsSync(file), i.id).toBe(true);
      const size = readFileSync(file).length;
      expect(size, i.id).toBeLessThan(60_000);
      total += size;
      expect(i.steps?.length, i.id).toBeGreaterThan(0);
      for (const img of i.people ? [i.people.you, ...i.people.others] : []) {
        expect(existsSync(resolve(PUBLIC, 'people', `${img}.webp`)), img).toBe(true);
      }
    }
    expect(total).toBeLessThan(1_200_000);
  });
});
