// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { TrainerNavHeader, TrainerNewChip } from './TrainerNavHeader';
import type { TrainerNavCourse } from './useTrainerNav';

afterEach(() => cleanup());

const course: TrainerNavCourse = {
  title: 'Quillmere Depot: from bill to variation',
  lang: 'en-GB',
  done: 1,
  total: 5,
};

const mapRow = (
  <li>
    <a href="/academy">Course map</a>
  </li>
);

describe('TrainerNavHeader', () => {
  it('shows the section label, the course name in the course language, and the progress', () => {
    render(
      <TrainerNavHeader course={course} footnote="The rest of the platform opens in later courses.">
        {mapRow}
      </TrainerNavHeader>,
    );
    const section = screen.getByRole('region', { name: 'Your course' });
    const title = within(section).getByText(course.title);
    expect(title.getAttribute('lang')).toBe('en-GB');
    const bar = within(section).getByRole('progressbar', { name: '1 of 5 verified.' });
    expect(bar.getAttribute('aria-valuenow')).toBe('1');
    expect(bar.getAttribute('aria-valuemax')).toBe('5');
    expect(screen.getByTestId('trainer-nav-progress-fill').style.width).toBe('20%');
    expect(section.textContent).toContain('1/5 tasks verified');
    expect(within(section).getByRole('link', { name: 'Course map' })).toBeTruthy();
    expect(within(section).getByText('The rest of the platform opens in later courses.')).toBeTruthy();
  });

  it('labels each row list and drops a section that has no rows', () => {
    render(
      <TrainerNavHeader
        course={course}
        openModules={[
          <li key="p">
            <a href="/projects">Projects</a>
          </li>,
        ]}
        lockedModules={[]}
      >
        {mapRow}
      </TrainerNavHeader>,
    );
    const list = screen.getByRole('list', { name: 'Open modules' });
    expect(within(list).getByRole('link', { name: 'Projects' })).toBeTruthy();
    expect(screen.queryByText('Opens as you go')).toBeNull();
    expect(screen.queryByRole('list', { name: 'Opens as you go' })).toBeNull();
  });

  it('shows the locked section when it has rows', () => {
    render(
      <TrainerNavHeader
        course={course}
        lockedModules={
          <li>
            <a href="/variations" aria-label="Variations, opens after task 4">
              Variations
            </a>
          </li>
        }
      >
        {mapRow}
      </TrainerNavHeader>,
    );
    const list = screen.getByRole('list', { name: 'Opens as you go' });
    expect(within(list).getByRole('link', { name: 'Variations, opens after task 4' }).getAttribute('href')).toBe('/variations');
    expect(screen.queryByText('Open modules')).toBeNull();
  });

  it('has no footnote unless one is given', () => {
    render(<TrainerNavHeader course={course}>{mapRow}</TrainerNavHeader>);
    expect(screen.queryByText(/later courses/)).toBeNull();
  });

  it('shows a placeholder and no progress while the course loads', () => {
    render(<TrainerNavHeader course={null}>{mapRow}</TrainerNavHeader>);
    expect(screen.getByTestId('trainer-nav-placeholder')).toBeTruthy();
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.getByRole('link', { name: 'Course map' })).toBeTruthy();
  });

  it('draws an empty bar for a course with no tasks, and never overflows', () => {
    const { rerender } = render(<TrainerNavHeader course={{ ...course, done: 0, total: 0 }}>{mapRow}</TrainerNavHeader>);
    expect(screen.getByTestId('trainer-nav-progress-fill').style.width).toBe('0%');
    rerender(<TrainerNavHeader course={{ ...course, done: 7, total: 5 }}>{mapRow}</TrainerNavHeader>);
    expect(screen.getByTestId('trainer-nav-progress-fill').style.width).toBe('100%');
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('5');
  });

  it('takes a custom label', () => {
    render(
      <TrainerNavHeader course={course} label="Academy">
        {mapRow}
      </TrainerNavHeader>,
    );
    expect(screen.getByRole('region', { name: 'Academy' })).toBeTruthy();
  });

  it('collapses to icons with the course name in the accessible name', () => {
    render(
      <TrainerNavHeader
        iconified
        course={course}
        footnote="The rest of the platform opens in later courses."
        openModules={
          <li>
            <a href="/projects" aria-label="Projects" />
          </li>
        }
        lockedModules={
          <li>
            <a href="/variations" aria-label="Variations, opens after task 4" />
          </li>
        }
      >
        {mapRow}
      </TrainerNavHeader>,
    );
    const section = screen.getByRole('region', { name: `Your course ${course.title}` });
    expect(within(section).getByText(course.title).getAttribute('lang')).toBe('en-GB');
    expect(within(section).getByRole('link', { name: 'Projects' })).toBeTruthy();
    expect(within(section).getByRole('link', { name: 'Variations, opens after task 4' })).toBeTruthy();
    expect(within(section).getByRole('progressbar')).toBeTruthy();
    // No visible section words or footnote in the icon rail.
    expect(screen.queryByText('Open modules')).toBeNull();
    expect(screen.queryByText('Opens as you go')).toBeNull();
    expect(screen.queryByText(/later courses/)).toBeNull();
  });
});

describe('TrainerNewChip', () => {
  it('says New', () => {
    render(<TrainerNewChip />);
    expect(screen.getByText('New')).toBeTruthy();
  });
});
