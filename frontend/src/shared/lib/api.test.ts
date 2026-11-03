// @ts-nocheck
/**
 * Anti-regression for ``extractErrorMessageFromBody``.
 *
 * Pins behaviour for the v2.6.43 export-error fix: the seven export functions
 * (contacts/tasks/fieldreports/rfi/costs/import/finance) now route through
 * this helper instead of ``body.detail || 'Export failed'``. Drifting back
 * to the simple ``||`` would re-introduce the ``[object Object]`` toast on
 * FastAPI 422 validation responses, since the array-of-objects ``detail`` is
 * truthy and JS coerces it via ``.toString()`` → ``[object Object]``.
 */
import { describe, it, expect } from 'vitest';
import { extractErrorMessageFromBody, getErrorMessage } from './api';

describe('extractErrorMessageFromBody', () => {
  it('returns null for null/undefined', () => {
    expect(extractErrorMessageFromBody(null)).toBeNull();
    expect(extractErrorMessageFromBody(undefined)).toBeNull();
  });

  it('turns the module guard refusal into a translated, actionable message', () => {
    const msg = extractErrorMessageFromBody({ detail: 'module_disabled', module: 'ai' });
    expect(msg).not.toBe('module_disabled');
    expect(msg).toContain('ai');
  });

  it('returns short string body as-is', () => {
    expect(extractErrorMessageFromBody('Something went wrong')).toBe('Something went wrong');
  });

  it('rejects HTML-looking string bodies (server crash pages)', () => {
    expect(extractErrorMessageFromBody('<html><body>500</body></html>')).toBeNull();
  });

  it('rejects very long string bodies (likely full HTML)', () => {
    expect(extractErrorMessageFromBody('x'.repeat(500))).toBeNull();
  });

  it('reads FastAPI HTTPException string detail', () => {
    expect(extractErrorMessageFromBody({ detail: 'Project not found' })).toBe(
      'Project not found',
    );
  });

  it('flattens FastAPI 422 validation detail array - single field', () => {
    const body = {
      detail: [
        { type: 'missing', loc: ['query', 'project_id'], msg: 'Field required' },
      ],
    };
    const msg = extractErrorMessageFromBody(body);
    expect(msg).toContain('query.project_id');
    expect(msg).toContain('Field required');
    // The critical regression — never let this be `[object Object]`
    expect(msg).not.toContain('[object Object]');
  });

  it('flattens FastAPI 422 validation detail array - multiple fields', () => {
    const body = {
      detail: [
        { type: 'missing', loc: ['body', 'name'], msg: 'Field required' },
        { type: 'value_error', loc: ['body', 'email'], msg: 'Invalid email' },
        { type: 'missing', loc: ['body', 'role'], msg: 'Field required' },
      ],
    };
    const msg = extractErrorMessageFromBody(body) as string;
    expect(msg).toContain('Field required');
    expect(msg).toContain('Invalid email');
    expect(msg).not.toContain('[object Object]');
    // Joined with semicolons; first 3 entries kept (sanity cap).
    expect(msg.split(';').length).toBeGreaterThan(0);
  });

  it('strips the `body` segment from the loc path for readability', () => {
    const body = {
      detail: [{ type: 'missing', loc: ['body', 'workforce', 0, 'count'], msg: 'Required' }],
    };
    const msg = extractErrorMessageFromBody(body) as string;
    // `body` is dropped, but other path parts remain.
    expect(msg.startsWith('body')).toBe(false);
    expect(msg).toContain('workforce');
    expect(msg).toContain('Required');
  });

  it('reads generic `message` envelope', () => {
    expect(extractErrorMessageFromBody({ message: 'Out of stock' })).toBe('Out of stock');
  });

  it('reads generic `error` envelope', () => {
    expect(extractErrorMessageFromBody({ error: 'Permission denied' })).toBe(
      'Permission denied',
    );
  });

  it('returns null when nothing actionable is present', () => {
    expect(extractErrorMessageFromBody({ irrelevant: true })).toBeNull();
    expect(extractErrorMessageFromBody({})).toBeNull();
  });

  it('survives malformed validation entries (no msg)', () => {
    const body = { detail: [{ type: 'missing', loc: ['body', 'x'] /* no msg */ }] };
    // Skipped silently → no parts → falls through to null.
    expect(extractErrorMessageFromBody(body)).toBeNull();
  });

  it('reads STRUCTURED detail object (message + remediation)', () => {
    // bim_hub-style geometry error: `detail` is an object, not a string/array.
    // Without the structured branch the caller renders "[object Object]".
    const body = {
      detail: {
        error: 'geometry_pending',
        message: '3D geometry is still being generated',
        remediation: 'Try again shortly',
      },
    };
    const msg = extractErrorMessageFromBody(body) as string;
    expect(msg).toContain('3D geometry is still being generated');
    expect(msg).toContain('Try again shortly');
    expect(msg).not.toContain('[object Object]');
  });
});

/**
 * Anti-regression for ``getErrorMessage`` against raw thrown values.
 *
 * A code path that does ``throw responseBody`` (a plain object/array rather
 * than an ``Error``) used to surface as ``[object Object]``. ``getErrorMessage``
 * now routes such raw values through ``extractErrorMessageFromBody`` so a
 * thrown FastAPI ``{detail: [...]}`` becomes a readable string.
 */
describe('getErrorMessage', () => {
  it('normalises a thrown FastAPI 422 body (array detail) - never [object Object]', () => {
    const thrownObject = {
      detail: [{ loc: ['body', 'email'], msg: 'Field required', type: 'missing' }],
    };
    const msg = getErrorMessage(thrownObject);
    expect(typeof msg).toBe('string');
    expect(msg.length).toBeGreaterThan(0);
    expect(msg).toContain('Field required');
    // The critical regression — a thrown plain object must not coerce.
    expect(msg).not.toContain('[object Object]');
  });
});
