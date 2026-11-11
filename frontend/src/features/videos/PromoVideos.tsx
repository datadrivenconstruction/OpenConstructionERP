/**
 * "Watch and share": the three promo videos plus the installation video, each
 * a click-to-play facade (thumbnail first, the privacy-enhanced embed only
 * after a click) with a button that copies the YouTube link for a colleague.
 */
import { useState } from 'react';
import { Check, Link2, Play } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/** Promo videos first, then the installation video. */
export const PROMO_VIDEO_IDS = ['pTaeQRzTFxY', 'vENnh7bBVVM', 'X06cIaroAeI', 'WjDK-uk9b1w'] as const;

export function youtubeUrl(id: string): string {
  return `https://www.youtube.com/watch?v=${id}`;
}

function PromoTile({ id, title }: { id: string; title: string }) {
  const { t } = useTranslation();
  const [playing, setPlaying] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(youtubeUrl(id));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked: the link is still reachable by playing the video */
    }
  };

  return (
    <li className="min-w-0" data-testid={`promo-video-${id}`}>
      <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black">
        {playing ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`}
            title={title}
            className="absolute inset-0 h-full w-full"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            referrerPolicy="strict-origin-when-cross-origin"
            allowFullScreen
          />
        ) : (
          <button
            type="button"
            onClick={() => setPlaying(true)}
            aria-label={t('videos.promo.play', { defaultValue: 'Play: {{title}}', title })}
            className="group absolute inset-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          >
            <img
              src={`https://i.ytimg.com/vi/${id}/hqdefault.jpg`}
              alt=""
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              className="h-full w-full object-cover"
            />
            <span className="absolute inset-0 flex items-center justify-center bg-black/20 transition-colors group-hover:bg-black/10">
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-white/95 text-black/85 shadow-md">
                <Play size={18} fill="currentColor" aria-hidden />
              </span>
            </span>
          </button>
        )}
      </div>
      <div className="mt-2 flex items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-medium leading-snug text-content-primary">{title}</p>
        <button
          type="button"
          onClick={copy}
          data-testid={`promo-copy-${id}`}
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
        >
          {copied ? <Check size={13} aria-hidden /> : <Link2 size={13} aria-hidden />}
          <span aria-live="polite">
            {copied
              ? t('videos.promo.copied', { defaultValue: 'Link copied' })
              : t('videos.promo.copy_link', { defaultValue: 'Copy link' })}
          </span>
        </button>
      </div>
    </li>
  );
}

export function PromoVideos() {
  const { t } = useTranslation();
  const titles = [
    t('videos.promo.main', { defaultValue: 'Free open-source construction ERP' }),
    t('videos.promo.release', { defaultValue: 'Release walkthrough' }),
    t('videos.promo.tender', { defaultValue: 'Drawing in, tender out' }),
    t('videos.promo.install', { defaultValue: 'How to install OpenConstructionERP' }),
  ];
  return (
    <section
      data-testid="promo-videos"
      aria-labelledby="promo-videos-title"
      className="rounded-xl border border-border-light bg-surface-primary/70 p-4"
    >
      <h2 id="promo-videos-title" className="text-sm font-semibold text-content-primary">
        {t('videos.promo.title', { defaultValue: 'Watch and share' })}
      </h2>
      <p className="mt-0.5 text-xs text-content-tertiary">
        {t('videos.promo.subtitle', { defaultValue: 'Short videos you can send to a colleague.' })}
      </p>
      <ul className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {PROMO_VIDEO_IDS.map((id, i) => (
          <PromoTile key={id} id={id} title={titles[i] ?? ''} />
        ))}
      </ul>
    </section>
  );
}

export default PromoVideos;
