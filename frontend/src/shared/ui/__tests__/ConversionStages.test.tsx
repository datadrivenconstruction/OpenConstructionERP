// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One conversion experience for BIM and DWG: named stages, the current one marked,
// finished ones ticked, the time limit in plain minutes.

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ConversionStages } from '../ConversionStages';
import {
  BIM_STAGES,
  DWG_STAGES,
  conversionErrorKind,
  limitMinutes,
  stageFromServer,
  stageStates,
} from '@/shared/lib/conversionStages';

describe('conversion stage helpers', () => {
  it('maps server steps to UI stages and defaults to the long step', () => {
    expect(stageFromServer('preparing_converter')).toBe('converter');
    expect(stageFromServer('building_3d')).toBe('model3d');
    expect(stageFromServer('reading_elements')).toBe('table');
    expect(stageFromServer('reading_entities')).toBe('entities');
    expect(stageFromServer('converting')).toBe('convert');
    expect(stageFromServer(undefined)).toBe('convert');
  });

  it('ticks finished stages and marks one current', () => {
    expect(stageStates(BIM_STAGES, 'convert')).toEqual(['done', 'done', 'current', 'pending', 'pending']);
    expect(stageStates(DWG_STAGES, 'upload')).toEqual(['current', 'pending', 'pending', 'pending']);
  });

  it('reads the limit as plain minutes, 30 by default', () => {
    expect(limitMinutes(null)).toBe(30);
    expect(limitMinutes(3600)).toBe(60);
  });

  it('groups server codes into what the user can act on', () => {
    expect(conversionErrorKind('convert_timeout')).toBe('timeout');
    expect(conversionErrorKind('ddc_failed')).toBe('unreadable');
    expect(conversionErrorKind('converter_missing')).toBe('converter_install');
    expect(conversionErrorKind('zero_elements')).toBe('empty');
    expect(conversionErrorKind('something_new')).toBe('generic');
  });
});

describe('ConversionStages', () => {
  it('shows every stage, the current one in progress, and the limit while converting', () => {
    render(
      <ConversionStages
        stages={BIM_STAGES}
        current="convert"
        format="RVT"
        startedAt={Date.now() - 125_000}
        limitS={1800}
      />,
    );
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(5);
    expect(items.map((li) => li.getAttribute('data-state'))).toEqual(['done', 'done', 'current', 'pending', 'pending']);
    expect(screen.getByTestId('conversion-elapsed').textContent).toContain('30');
    expect(screen.getByTestId('conversion-note').textContent).toMatch(/leave this page/i);
  });

  it('asks to keep the tab open and shows the real percent during upload', () => {
    render(<ConversionStages stages={DWG_STAGES} current="upload" uploadPercent={42} />);
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('42');
    expect(screen.getByTestId('conversion-note').textContent).toMatch(/keep this browser tab open/i);
  });
});
