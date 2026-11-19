// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  chooseColumn,
  columnsForPreset,
  detectDelimiter,
  fileFormatFor,
  selfDescribing,
  guessPreset,
  mappingProblems,
  parseNumber,
  presetOf,
  sampleRows,
  splitLine,
} from './importMapping';

// First rows of the Riverside Yard control.csv (PNEZD, EPSG 32633).
const CONTROL = 'CP1,5818990.000,388990.000,33.900,CP\nCP2,5818990.000,389110.000,35.100,CP\nCP3,5819070.000,389110.000,35.100,CP\n';

describe('survey import mapping', () => {
  it('detects the comma of the demo control file with full confidence', () => {
    expect(detectDelimiter(CONTROL)).toEqual({ value: ',', confidence: 1 });
  });

  it('detects tabs and blank-separated instrument files', () => {
    expect(detectDelimiter('P1\t1.0\t2.0\nP2\t1.5\t2.5\n').value).toBe('\t');
    expect(detectDelimiter('1  389000.0  5819000.0  34.0\n2  389010.0  5819000.0  34.1\n').value).toBe(' ');
  });

  it('reads northing first on the demo file from the magnitudes', () => {
    const guess = guessPreset(sampleRows(CONTROL, ','));
    expect(guess.value).toBe('PNEZD');
    expect(guess.confidence).toBeGreaterThan(0.5);
  });

  it('lets a header row decide the order', () => {
    expect(guessPreset([['Point', 'Easting', 'Northing', 'Elevation', 'Code']])).toEqual({ value: 'PENZD', confidence: 0.95 });
    expect(guessPreset([['N', 'E', 'Z'], ['1', '2', '3']]).value).toBe('NEZ');
  });

  it('says it is unsure on a local grid where E and N look alike', () => {
    expect(guessPreset([['1', '1000.0', '1005.0', '50.0']]).confidence).toBeLessThan(0.5);
  });

  it('lays a preset over the columns and recognises it back', () => {
    const cols = columnsForPreset('PNEZD', 6);
    expect(cols).toEqual(['point_id', 'n', 'e', 'z', 'code', '']);
    expect(presetOf(cols)).toBe('PNEZD');
    expect(presetOf(['e', 'z', 'n'])).toBeNull();
  });

  it('moves a field when it is chosen for another column', () => {
    expect(chooseColumn(['point_id', 'n', 'e', 'z'], 2, 'n')).toEqual(['point_id', '', 'n', 'z']);
    expect(chooseColumn(['point_id', 'n', 'e', 'z'], 3, '')).toEqual(['point_id', 'n', 'e', '']);
  });

  it('needs both plan coordinates before preview', () => {
    expect(mappingProblems(['point_id', 'e', 'z'])).toEqual(['missing_n']);
    expect(mappingProblems(columnsForPreset('ENZ', 3))).toEqual([]);
  });

  it('reads decimal commas and quoted cells', () => {
    expect(parseNumber('389000,125')).toBe(389000.125);
    expect(parseNumber('abc')).toBeNull();
    expect(splitLine('"P,1";1.0;2.0', ';')).toEqual(['P,1', '1.0', '2.0']);
  });

  it('chooses the reader from the file name', () => {
    expect(fileFormatFor('parcels.geojson')).toBe('geojson');
    expect(fileFormatFor('field.TXT')).toBe('txt');
    expect(fileFormatFor('control.csv')).toBe('csv');
    expect(fileFormatFor('job.GSI')).toBe('gsi');
    expect(fileFormatFor('job.jxl')).toBe('jobxml');
    expect(fileFormatFor('job.xml', '<?xml version="1.0"?><JOBFile jobName="x">')).toBe('jobxml');
    expect(fileFormatFor('surface.xml', '<LandXML>')).toBe('landxml');
    expect(selfDescribing('gsi')).toBe(true);
    expect(selfDescribing('csv')).toBe(false);
  });
});
