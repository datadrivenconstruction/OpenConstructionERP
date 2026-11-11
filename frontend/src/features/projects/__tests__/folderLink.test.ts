import { describe, it, expect } from 'vitest';

import { FOLDER_LINK_MAX, folderLinkHref, folderLinkProblem } from '../folderLink';

describe('folderLinkProblem', () => {
  it.each([
    'https://example.sharepoint.com/sites/tower',
    'http://nas.local/projects/tower',
    'file:///Z:/Projects/Tower',
    'smb://nas/projects/tower',
    '\\\\nas\\projects\\tower',
    '',
    '   ',
  ])('accepts %s', (v) => expect(folderLinkProblem(v)).toBeNull());

  it.each(['javascript:alert(1)', 'ftp://host/x', '/etc/passwd', '\\\\nas', 'https://a b', 'Z:\\x'])(
    'refuses %s',
    (v) => expect(folderLinkProblem(v)).toBe('format'),
  );

  it('refuses a link over the length cap', () => {
    expect(folderLinkProblem('https://e.co/' + 'a'.repeat(FOLDER_LINK_MAX))).toBe('too_long');
  });
});

describe('folderLinkHref', () => {
  it('turns a UNC path into a file link and leaves URLs alone', () => {
    expect(folderLinkHref('\\\\nas\\projects\\tower')).toBe('file://nas/projects/tower');
    expect(folderLinkHref(' https://example.com/x ')).toBe('https://example.com/x');
  });
});
