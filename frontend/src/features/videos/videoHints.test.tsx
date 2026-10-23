// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Watch how" chips: every hint points at a real screen and a real chapter,
// the reader's market and language win, and an unfit reader gets no chip.

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ReactNode } from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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

import { VIDEOS, chapterStartingAt, videoById } from './academy';
import { VIDEO_HINTS, pickVideoHint, type VideoHintTopic } from './videoHints';
import VideoHintButton from './VideoHintButton';

const TOPICS = Object.keys(VIDEO_HINTS) as VideoHintTopic[];
const APP = readFileSync(resolve(__dirname, '../../app/App.tsx'), 'utf8');
const SRC = resolve(__dirname, '../..');

describe('VIDEO_HINTS', () => {
  it.each(TOPICS)('%s points at a routed screen and at chapter starts', (topic) => {
    const spot = VIDEO_HINTS[topic];
    expect(APP).toContain(`path="${spot.route}"`);
    for (const [id, t] of spot.chapters) {
      const video = videoById(id);
      expect(video, id).toBeDefined();
      expect(chapterStartingAt(video!, t), `${id}@${t}`).toBeDefined();
    }
  });

  it.each(TOPICS)('%s has a chip for an English reader with no market', (topic) => {
    const hint = pickVideoHint(topic, { market: null, language: 'en' }, VIDEOS);
    expect(hint?.video.language).toBe('en');
  });

  it('every topic is placed on a screen', () => {
    const files = [
      'features/finance/RetentionLedgerTab.tsx',
      'features/finance/FinancePage.tsx',
      'features/tendering/TenderingPage.tsx',
      'features/daily-diary/DailyDiaryPage.tsx',
      'features/changeorders/ChangeOrdersPage.tsx',
      'features/payment-clock/PaymentClockPage.tsx',
      'features/punchlist/PunchListPage.tsx',
    ];
    const text = files.map((f) => {
      try {
        return readFileSync(resolve(SRC, f), 'utf8');
      } catch {
        return '';
      }
    });
    for (const topic of TOPICS) expect(text.some((s) => s.includes(`topic="${topic}"`)), topic).toBe(true);
  });
});

describe('pickVideoHint', () => {
  it('prefers the reader market, then their language', () => {
    expect(pickVideoHint('retention', { market: 'IT', language: 'it' }, VIDEOS)?.video.id).toBe('IT08');
    expect(pickVideoHint('bid-leveling', { market: 'DE', language: 'de' }, VIDEOS)?.video.id).toBe('DIN05');
    expect(pickVideoHint('payment-application', { market: 'CN', language: 'en' }, VIDEOS)?.video.id).toBe('CN04');
    expect(pickVideoHint('daily-diary', { market: null, language: 'es' }, VIDEOS)?.video.id).toBe('ES08');
  });

  it('offers no lesson the reader cannot follow', () => {
    const noEnglish = VIDEOS.filter((v) => v.language !== 'en');
    expect(pickVideoHint('retention', { market: 'JP', language: 'ja' }, noEnglish)).toBeNull();
    expect(pickVideoHint('retention', { market: 'BG', language: 'ja' }, noEnglish)?.video.id).toBe('BG07');
    expect(pickVideoHint('retention', { market: null, language: 'en' }, [])).toBeNull();
  });
});

describe('VideoHintButton', () => {
  afterEach(cleanup);

  it('opens the player at the hinted chapter', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <VideoHintButton topic="change-order" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const chip = screen.getByTestId('video-hint-change-order');
    expect(chip.getAttribute('title')).toMatch(/^Video: .+, from \d+:\d{2} \(.+\)$/);
    fireEvent.click(chip);
    const frame = screen.getByTestId('video-player').querySelector('iframe');
    expect(frame?.getAttribute('src')).toMatch(/start=\d+/);
  });
});
