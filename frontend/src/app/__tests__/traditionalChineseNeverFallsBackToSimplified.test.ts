import { describe, expect, it } from 'vitest';
import { isTraditionalChinese, matchSupportedLanguage } from '../i18n';

describe('Traditional Chinese never resolves to Simplified', () => {
  it.each(['zh-HK', 'zh-hk', 'zh-MO', 'zh-TW', 'zh-Hant', 'zh-Hant-TW', 'zh-Hant-SG', 'zh_TW'])(
    '%s resolves to zh-HK',
    (tag) => {
      expect(isTraditionalChinese(tag)).toBe(true);
      expect(matchSupportedLanguage(tag)).toBe('zh-HK');
    },
  );

  it.each(['zh', 'zh-CN', 'zh-SG', 'zh-Hans', 'zh-Hans-HK'])('%s stays Simplified', (tag) => {
    expect(isTraditionalChinese(tag)).toBe(false);
    expect(matchSupportedLanguage(tag)).toBe('zh');
  });

  it('leaves other languages as they were', () => {
    expect(matchSupportedLanguage('en-HK')).toBe('en-GB');
    expect(matchSupportedLanguage('pt-BR')).toBe('pt-BR');
  });
});
