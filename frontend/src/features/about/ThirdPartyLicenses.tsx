// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ThirdPartyLicenses — the LGPL components inside the build, and their texts.
 *
 * The About panel used to describe AGPL-3.0 and stop there, which is our own
 * licence and not the whole story: the product also redistributes components
 * under LGPL-2.1 and LGPL-3.0, and LGPL-3.0 section 4(c) asks that a Combined
 * Work displaying copyright notices during execution include a notice for the
 * Library among them and point the reader at the licence texts.
 *
 * The texts are read from `/api/v1/licenses/`, which serves the copies that
 * ship inside the artefact. That is the point of the endpoint: on a desktop
 * install with no network a link to gnu.org is a link to nothing, and that is
 * exactly where somebody is most likely to be reading this.
 *
 * Fetched lazily on first expand rather than with the page. Nobody opens
 * About to read 35 kB of GPL, and the ones who do are not in a hurry.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ExternalLink, FileText } from 'lucide-react';
import clsx from 'clsx';
import { Button } from '@/shared/ui';
import { apiGet, ApiError } from '@/shared/lib/api';

/** One licence text as the listing describes it, without its body. */
export interface LicenseTextSummary {
  name: string;
  title: string;
  size_bytes: number;
}

/**
 * The listing envelope.
 *
 * Named rather than written inline at the call site. An inline `{ items: T[] }`
 * reads as an unmigrated bare-array consumer to the repo's structural guard,
 * and a named type is what the rest of the tree uses. Not `Page<T>` from
 * `shared/lib/api`, because this endpoint does not page and would have to
 * invent an offset and a limit to claim that shape.
 */
export interface LicenseTextList {
  items: LicenseTextSummary[];
  total: number;
}

/** One licence text in full. */
export interface LicenseTextDetail extends LicenseTextSummary {
  text: string;
}

const NOTICE_URL = 'https://github.com/datadrivenconstruction/OpenConstructionERP/blob/main/NOTICE';

/**
 * The bundled LGPL components and their licence texts.
 *
 * @param className - Optional wrapper classes, so the caller owns the spacing.
 */
export function ThirdPartyLicenses({ className }: { className?: string }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [texts, setTexts] = useState<LicenseTextSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  // null while nothing has failed; the HTTP status otherwise, and 0 when the
  // request never got one. The backend answers 503 for an install that cannot
  // locate the texts it shipped with, which is a different sentence to a
  // browser that is offline from the server, so the two are not merged here.
  const [failedStatus, setFailedStatus] = useState<number | null>(null);
  const [openName, setOpenName] = useState<string | null>(null);
  const [body, setBody] = useState<LicenseTextDetail | null>(null);
  const [bodyFailed, setBodyFailed] = useState(false);

  const loadList = useCallback(async () => {
    setLoading(true);
    setFailedStatus(null);
    try {
      const page = await apiGet<LicenseTextList>('/v1/licenses/');
      setTexts(page.items);
    } catch (err) {
      // Never an empty list on failure. An empty list reads as "this build
      // bundles nothing", which is a false statement about our compliance
      // made by a broken install, so the reader is sent to NOTICE instead.
      setTexts(null);
      setFailedStatus(err instanceof ApiError ? err.status : 0);
    } finally {
      setLoading(false);
    }
  }, []);

  const toggle = useCallback(() => {
    setExpanded((was) => {
      if (!was && texts === null && !loading) void loadList();
      return !was;
    });
  }, [texts, loading, loadList]);

  const openText = useCallback(
    async (name: string) => {
      if (openName === name) {
        setOpenName(null);
        return;
      }
      setOpenName(name);
      setBody(null);
      setBodyFailed(false);
      try {
        setBody(await apiGet<LicenseTextDetail>(`/v1/licenses/${encodeURIComponent(name)}`));
      } catch {
        setBodyFailed(true);
      }
    },
    [openName],
  );

  return (
    <div className={clsx('pt-3 border-t border-border-light', className)}>
      <h3 className="text-sm font-semibold text-content-primary mb-1">
        {t('about.third_party_title', { defaultValue: 'Third-party components' })}
      </h3>
      <p className="text-xs text-content-secondary leading-relaxed mb-2">
        {t('about.third_party_desc', {
          defaultValue:
            'The product also redistributes components under the GNU Lesser General Public License, versions 2.1 and 3.0, unmodified and at pinned versions: the psycopg2 PostgreSQL driver, which is in every build; Qt 5 and the FFmpeg libraries, which arrive with OpenCV when the optional OCR feature is installed; and Qt 6 Core, in the Windows desktop installer. Their full texts ship inside the product and open below with no network connection.',
        })}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<FileText size={14} />}
          onClick={toggle}
          aria-expanded={expanded}
        >
          {expanded
            ? t('about.third_party_hide', { defaultValue: 'Hide licence texts' })
            : t('about.third_party_show', { defaultValue: 'Bundled licence texts' })}
        </Button>
        <a
          href={NOTICE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
        >
          {t('about.third_party_notice', { defaultValue: 'Full NOTICE, component by component' })}
          <ExternalLink size={12} />
        </a>
      </div>

      {expanded && (
        <div className="mt-3">
          {loading && (
            <p className="text-xs text-content-tertiary">
              {t('about.third_party_loading', { defaultValue: 'Reading the texts that ship with this build...' })}
            </p>
          )}

          {failedStatus !== null && !loading && (
            <p className="text-xs text-amber-600 dark:text-amber-400 leading-relaxed">
              {failedStatus === 503
                ? t('about.third_party_error_missing', {
                    defaultValue:
                      'This installation cannot locate the licence texts it ships with. That is a packaging fault rather than an absence of licences, and the NOTICE linked above names every component and the licence it is under.',
                  })
                : t('about.third_party_error', {
                    defaultValue:
                      'The licence texts could not be read just now. The NOTICE linked above names every component and the licence it is under.',
                  })}
            </p>
          )}

          {!loading && failedStatus === null && texts && (
            <ul className="space-y-1">
              {texts.map((item) => (
                <li key={item.name} className="border border-border-light rounded-lg overflow-hidden">
                  <button
                    type="button"
                    onClick={() => void openText(item.name)}
                    aria-expanded={openName === item.name}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-secondary"
                  >
                    <ChevronDown
                      size={14}
                      className={clsx(
                        'shrink-0 text-content-tertiary transition-transform',
                        openName === item.name && 'rotate-180',
                      )}
                    />
                    <span className="flex-1 min-w-0">
                      <span className="block text-xs font-medium text-content-primary truncate">{item.title}</span>
                      <span className="block text-2xs text-content-tertiary truncate">{item.name}</span>
                    </span>
                    <span className="shrink-0 text-2xs text-content-tertiary tabular-nums">
                      {t('about.third_party_size', {
                        kb: Math.max(1, Math.round(item.size_bytes / 1024)),
                        defaultValue: '{{kb}} kB',
                      })}
                    </span>
                  </button>
                  {openName === item.name && (
                    <div className="border-t border-border-light bg-surface-secondary">
                      {bodyFailed && (
                        <p className="px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
                          {t('about.third_party_text_error', {
                            defaultValue: 'This text could not be read from the installation.',
                          })}
                        </p>
                      )}
                      {!bodyFailed && !body && (
                        <p className="px-3 py-2 text-xs text-content-tertiary">
                          {t('about.third_party_loading', {
                            defaultValue: 'Reading the texts that ship with this build...',
                          })}
                        </p>
                      )}
                      {body && body.name === item.name && (
                        <pre className="max-h-80 overflow-auto px-3 py-2 text-2xs leading-relaxed text-content-secondary whitespace-pre-wrap break-words">
                          {body.text}
                        </pre>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
