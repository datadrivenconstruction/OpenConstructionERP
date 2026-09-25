// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The generated video catalogue against the product it describes.
//
// scripts/build_video_catalog.py reads the playbook files as text and restates
// two runtime rules in Python: how a step route is normalised and which stage a
// case sits at when it names none. A Python copy of a TypeScript rule drifts
// silently, so this file checks the output against the real `PLAYBOOKS`,
// `normalizeCaseRoute` and `stageForPlaybook`. It is also the check that every
// case a video links to exists.

import { existsSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { PLAYBOOKS } from '@/features/cases/playbooks';
import { modulesForPlaybook } from '@/features/cases/playbookModules';
import { stageForPlaybook, STAGE_META } from '@/features/cases/stages';
import { ROLE_META } from '@/features/cases/roles';
import { ACADEMY_CATALOG } from './academyCatalog.generated';
import { RESULT_FAMILIES } from './academy';

const byId = new Map(PLAYBOOKS.map((pb) => [pb.id, pb]));
const videos = ACADEMY_CATALOG.videos;

describe('the video catalogue', () => {
  it('links only to cases that exist', () => {
    const missing = videos.flatMap((v) => v.cases.filter((c) => !byId.has(c)).map((c) => `${v.id} -> ${c}`));
    expect(missing).toEqual([]);
  });

  it('carries each linked case the way the Cases hub knows it', () => {
    const drift: string[] = [];
    for (const [id, ref] of Object.entries(ACADEMY_CATALOG.cases)) {
      const pb = byId.get(id);
      if (!pb) {
        drift.push(`${id}: not a case`);
        continue;
      }
      if (ref.titleKey !== pb.titleKey) drift.push(`${id}: titleKey ${ref.titleKey} vs ${pb.titleKey}`);
      if (ref.titleDefault !== pb.titleDefault) drift.push(`${id}: titleDefault`);
      if ((ref.region ?? null) !== (pb.region ?? null)) drift.push(`${id}: region ${ref.region} vs ${pb.region}`);
      if (ref.stage !== stageForPlaybook(pb)) drift.push(`${id}: stage ${ref.stage} vs ${stageForPlaybook(pb)}`);
      const routes = modulesForPlaybook(pb).map((m) => m.route);
      if (JSON.stringify(ref.routes) !== JSON.stringify(routes)) {
        drift.push(`${id}: routes ${ref.routes.join(',')} vs ${routes.join(',')}`);
      }
    }
    expect(drift).toEqual([]);
  });

  it('gives every video the modules its cases walk through', () => {
    for (const v of videos) {
      const expected = [...new Set(v.cases.flatMap((c) => ACADEMY_CATALOG.cases[c]!.routes))];
      expect(v.routes, v.id).toEqual(expected);
    }
  });

  it('uses the Cases hub vocabulary for stage and role', () => {
    const stages = new Set(STAGE_META.map((s) => s.id));
    const roles = new Set(ROLE_META.map((r) => r.id));
    for (const v of videos) {
      expect(stages.has(v.stage), `${v.id} stage ${v.stage}`).toBe(true);
      for (const r of v.roles) expect(roles.has(r), `${v.id} role ${r}`).toBe(true);
      if (v.result) expect(RESULT_FAMILIES, v.id).toContain(v.result);
    }
  });

  it('is published exactly when it has a well-formed YouTube id, each used once', () => {
    const ids = videos.map((v) => v.youtubeId).filter(Boolean);
    expect(new Set(ids).size).toBe(ids.length);
    for (const v of videos) {
      if (v.youtubeId) expect(v.youtubeId).toMatch(/^[A-Za-z0-9_-]{11}$/);
      expect(v.status, v.id).toBe(v.youtubeId ? 'published' : 'coming_soon');
    }
  });

  it('names a known series, in order, with no gaps or repeats', () => {
    const series = new Set(ACADEMY_CATALOG.series.map((s) => s.id));
    for (const s of series) {
      const orders = videos.filter((v) => v.series === s).map((v) => v.seriesOrder);
      expect(new Set(orders).size, s).toBe(orders.length);
    }
    for (const v of videos) expect(series.has(v.series), v.id).toBe(true);
  });

  it('keeps chapters inside the video and in order', () => {
    for (const v of videos) {
      v.chapters.forEach((c, i) => {
        expect(Number.isInteger(c.t), v.id).toBe(true);
        if (i > 0) expect(c.t, `${v.id} chapter ${i}`).toBeGreaterThanOrEqual(v.chapters[i - 1]!.t);
        if (v.duration) expect(c.t, `${v.id} chapter ${i}`).toBeLessThan(v.duration);
      });
    }
  });

  it('shows the channel cover for a published video and ships a local one only for the rest', () => {
    const publicDir = [resolve(process.cwd(), 'public'), resolve(process.cwd(), 'frontend/public')].find((d) =>
      existsSync(d),
    )!;
    const coversDir = resolve(publicDir, 'assets/videos/academy');
    for (const v of videos) {
      if (v.youtubeId) {
        expect(v.cover, v.id).toBe(`https://i.ytimg.com/vi/${v.youtubeId}/maxresdefault.jpg`);
      } else {
        expect(v.cover, v.id).toMatch(/^\/assets\/videos\/academy\/[a-z0-9-]+\.webp$/);
        expect(existsSync(resolve(publicDir, `.${v.cover}`)), v.cover).toBe(true);
      }
    }
    // A published video's old local cover is deleted by the generator, so the
    // folder holds exactly the covers the catalogue still points at.
    const local = new Set(videos.filter((v) => !v.youtubeId).map((v) => v.cover.split('/').pop()));
    // Git keeps no empty folder, so once every video is out the folder is gone.
    expect(new Set(existsSync(coversDir) ? readdirSync(coversDir) : [])).toEqual(local);
    const text = JSON.stringify(ACADEMY_CATALOG);
    expect(text).not.toMatch(/\.mp4|\.srt|\.vtt|file:\/\/|[A-Z]:\\/i);
  });

  it('has one entry point for somebody new, and it is published', () => {
    const start = videos.filter((v) => v.startHere);
    expect(start).toHaveLength(1);
    expect(start[0]!.status).toBe('published');
  });
});
