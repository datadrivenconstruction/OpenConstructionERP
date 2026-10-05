// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

const modeState = vi.hoisted(() => ({ current: { academyMode: false } as { academyMode: boolean } }));
vi.mock('./useTrainerMode', () => ({ useTrainerMode: () => modeState.current }));

import { TrainerCourseRoute } from './TrainerCourseRoute';

afterEach(() => cleanup());

describe('TrainerCourseRoute', () => {
  it('off renders the catch-all branch and never builds the map', () => {
    modeState.current = { academyMode: false };
    const on = vi.fn(() => <div>map</div>);
    render(<TrainerCourseRoute on={on} off={() => <div>not found</div>} />);
    expect(screen.getByText('not found')).toBeInTheDocument();
    expect(on).not.toHaveBeenCalled();
  });

  it('academy mode (live or cached) renders the map and never builds the catch-all', () => {
    modeState.current = { academyMode: true };
    const off = vi.fn(() => <div>not found</div>);
    render(<TrainerCourseRoute on={() => <div>map</div>} off={off} />);
    expect(screen.getByText('map')).toBeInTheDocument();
    expect(off).not.toHaveBeenCalled();
  });
});
