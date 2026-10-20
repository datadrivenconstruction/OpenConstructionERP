/**
 * Browser-side SVG to PNG conversion for logos. The server prints PDFs from the
 * PNG, so an SVG logo is rasterised once at upload time and stored beside it.
 */

const FALLBACK_W = 300;
const FALLBACK_H = 150;

export function isSvgDataUrl(dataUrl: string | null | undefined): boolean {
  return Boolean(dataUrl && dataUrl.startsWith('data:image/svg+xml'));
}

/** Size from the SVG's viewBox, for files that declare no width/height. */
function viewBoxSize(svgDataUrl: string): { w: number; h: number } | null {
  try {
    const comma = svgDataUrl.indexOf(',');
    const head = svgDataUrl.slice(0, comma);
    const body = svgDataUrl.slice(comma + 1);
    const text = head.includes(';base64') ? atob(body) : decodeURIComponent(body);
    const m = /viewBox\s*=\s*["']\s*[-\d.eE]+[\s,]+[-\d.eE]+[\s,]+([\d.eE]+)[\s,]+([\d.eE]+)\s*["']/.exec(text);
    if (!m) return null;
    const w = Number(m[1]);
    const h = Number(m[2]);
    return w > 0 && h > 0 ? { w, h } : null;
  } catch {
    return null;
  }
}

export function rasteriseSvgToPng(svgDataUrl: string, maxSide = 1200): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      let w = img.naturalWidth;
      let h = img.naturalHeight;
      if (!w || !h) {
        const vb = viewBoxSize(svgDataUrl);
        w = vb?.w ?? FALLBACK_W;
        h = vb?.h ?? FALLBACK_H;
      }
      const scale = maxSide / Math.max(w, h);
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(w * scale));
      canvas.height = Math.max(1, Math.round(h * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Canvas is not available'));
        return;
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      try {
        resolve(canvas.toDataURL('image/png'));
      } catch (e) {
        reject(e instanceof Error ? e : new Error('Could not rasterise the SVG'));
      }
    };
    img.onerror = () => reject(new Error('Could not load the SVG'));
    img.src = svgDataUrl;
  });
}
