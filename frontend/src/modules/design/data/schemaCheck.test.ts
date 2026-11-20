import { describe, expect, it } from 'vitest';
import { isRequiredAt, jsonEqual, schemaAt, toPointer, validate, type Schema } from './schemaCheck';
import { BRIEF_SCHEMA } from './briefModel';
import example from './fixtures/brief.de-residential.json';

describe('schema checking', () => {
  it('accepts the contract example', () => {
    expect(validate(example, BRIEF_SCHEMA)).toEqual([]);
  });

  it('reports each keyword at the pointer of the value', () => {
    const schema: Schema = {
      type: 'object',
      additionalProperties: false,
      required: ['a'],
      properties: {
        a: { type: 'integer', minimum: 1 },
        b: { type: 'array', minItems: 2, items: { type: 'string', pattern: '^[A-Z]+$' } },
        c: { enum: ['x', null] },
        d: { type: 'string', format: 'date-time' },
        e: { type: 'object', propertyNames: { pattern: '^/' }, additionalProperties: { $ref: '#/$defs/n' } },
      },
      $defs: { n: { type: 'number', exclusiveMinimum: 0 } },
    };
    const errors = validate(
      { a: 0, b: ['OK', 'no'], c: 'y', d: '2026-02-29T10:00:00Z', e: { bad: 1, '/x': 0 }, z: 1 },
      schema,
    );
    expect(errors.map((e) => `${e.pointer} ${e.code}`).sort()).toEqual([
      '/a minimum',
      '/b/1 pattern',
      '/c enum',
      '/d date_time',
      '/e/bad property_name_pattern',
      '/e/~1x exclusive_minimum',
      '/z not_allowed',
    ]);
    expect(validate({}, schema)).toEqual([{ pointer: '/a', code: 'required' }]);
    expect(validate({ a: 2.0, d: '2024-02-29T23:59:60+01:00' }, schema)).toEqual([]);
  });

  it('treats booleans apart from numbers and compares JSON values', () => {
    expect(validate(true, { type: 'integer' })).toHaveLength(1);
    expect(jsonEqual({ a: [1, { b: null }] }, { a: [1, { b: null }] })).toBe(true);
    expect(jsonEqual({ a: 1 }, { a: 1, b: undefined })).toBe(false);
  });

  it('finds the sub-schema and required flag of a field', () => {
    expect(schemaAt(BRIEF_SCHEMA, '/programme/units/4/rooms/2/kind')?.minLength).toBe(1);
    expect(schemaAt(BRIEF_SCHEMA, '/site/plot')?.required).toEqual(['type', 'coordinates']);
    expect(schemaAt(BRIEF_SCHEMA, '/nope')).toBeNull();
    expect(isRequiredAt(BRIEF_SCHEMA, '/massing/floors_above')).toBe(true);
    expect(isRequiredAt(BRIEF_SCHEMA, '/massing/lift')).toBe(false);
    expect(toPointer(['a/b', '~c', 0])).toBe('/a~1b/~0c/0');
  });
});
