import { describe, expect, it } from 'vitest';
import { ApiError, fkConflictMessage } from '../api';

describe('fkConflictMessage', () => {
  it('names the linked records that block a delete', () => {
    const msg = fkConflictMessage(409, { code: 'fk_conflict', blocked_by: 'tendering package', detail: 'x' });
    expect(msg).toContain('tendering package');
  });

  it('explains a conflict without a table name', () => {
    expect(fkConflictMessage(409, { code: 'fk_conflict', blocked_by: null })).toMatch(/other records/i);
  });

  it('ignores other 409s and other statuses', () => {
    expect(fkConflictMessage(409, { detail: 'BOQ is locked' })).toBeNull();
    expect(fkConflictMessage(500, { code: 'fk_conflict' })).toBeNull();
  });

  it('becomes the ApiError message that every delete toast shows', () => {
    const err = new ApiError(409, 'Conflict', { code: 'fk_conflict', blocked_by: 'contracts contract', detail: 'raw' });
    expect(err.message).toContain('contracts contract');
  });
});
