/**
 * Render the README's mermaid diagrams to standalone SVG files with a white
 * background baked in.
 *
 * GitHub paints the canvas from the body of its own iframe and no mermaid
 * option reaches it, measured on both mermaid 10 and 11. An image is the only
 * thing whose background we own, so render each block once, put an opaque
 * white rect behind it, and write it out.
 *
 * The colours are pinned rather than inherited: the diagrams already set node
 * fills through classDef, but lines, arrowheads and any unstyled label take
 * their colour from the theme, and on white those have to be dark.
 */
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';

const req = createRequire(
  'file:///C:/Users/Artem%20Boiko/Desktop/CodeProjects/ERP_26030500/frontend/package.json',
);
const { chromium } = req('playwright');

const REPO = 'C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500';
const README = path.join(REPO, 'README.md');
const OUTDIR = path.join(REPO, 'docs', 'readme-diagrams');

const md = fs.readFileSync(README, 'utf8');
const lines = md.split('\n');

// Collect every fenced mermaid block with its line span and a name taken from
// the nearest heading above it, so the files are identifiable in a directory
// listing rather than numbered blindly.
const blocks = [];
let heading = 'diagram';
for (let i = 0; i < lines.length; i++) {
  const l = lines[i];
  const h = l.match(/^#{2,4}\s+(.*)$/);
  if (h) {
    heading = h[1]
      .replace(/<[^>]*>/g, '')
      .replace(/[<>]/g, '')
      .replace(/[^A-Za-z0-9 ]+/g, ' ')
      .trim()
      .toLowerCase()
      .split(/\s+/)
      .slice(0, 4)
      .join('-');
  }
  if (l.trim() === '```mermaid') {
    const start = i;
    let end = i + 1;
    while (end < lines.length && lines[end].trim() !== '```') end++;
    blocks.push({
      start,
      end,
      heading: heading || 'diagram',
      source: lines.slice(i + 1, end).join('\n'),
    });
    i = end;
  }
}

console.log(`mermaid blocks found: ${blocks.length}`);
blocks.forEach((b, i) => console.log(`  ${String(i + 1).padStart(2)} line ${b.start + 1} "${b.heading}"`));

fs.mkdirSync(OUTDIR, { recursive: true });

const INIT =
  '%%{init: {"theme":"base","themeVariables":{' +
  '"fontFamily":"-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif",' +
  '"fontSize":"15px","lineColor":"#57606a","textColor":"#1f2328",' +
  '"primaryColor":"#f6f8fa","primaryTextColor":"#1f2328","primaryBorderColor":"#d0d7de",' +
  '"secondaryColor":"#eaeef2","tertiaryColor":"#ffffff",' +
  '"clusterBkg":"#ffffff","clusterBorder":"#d0d7de",' +
  '"edgeLabelBackground":"#ffffff"' +
  '}}}%%\n';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.setContent('<body style="margin:0;background:#fff"><div id="out"></div></body>');
await page.addScriptTag({ url: 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js' });

const written = [];
for (let i = 0; i < blocks.length; i++) {
  const b = blocks[i];
  const name = `${String(i + 1).padStart(2, '0')}-${b.heading}.svg`;
  const res = await page.evaluate(async (text) => {
    window.mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });
    const host = document.getElementById('out');
    host.innerHTML = '';
    try {
      const { svg } = await window.mermaid.render('r' + Math.floor(performance.now() * 1000), text);
      host.innerHTML = svg;
      const el = host.querySelector('svg');
      const box = el.getBBox();
      return { svg, w: Math.ceil(box.width), h: Math.ceil(box.height) };
    } catch (e) {
      return { error: String(e).slice(0, 200) };
    }
  }, INIT + b.source);

  if (res.error) {
    console.log(`  FAILED ${name}: ${res.error}`);
    continue;
  }

  // Bake the background in. A rect as the first child covers the whole
  // viewBox, so the file is opaque wherever it is shown, including a GitHub
  // page in dark mode.
  let svg = res.svg;
  const vb = svg.match(/viewBox="([^"]+)"/);
  const [vx, vy, vw, vh] = vb ? vb[1].split(/\s+/).map(Number) : [0, 0, res.w, res.h];
  const pad = 16;
  const bg = `<rect x="${vx - pad}" y="${vy - pad}" width="${vw + pad * 2}" height="${vh + pad * 2}" fill="#ffffff"/>`;
  svg = svg.replace(/(<svg[^>]*>)/, `$1${bg}`);
  // A fixed max-width in the file fights GitHub's own sizing; let the img tag decide.
  svg = svg.replace(/style="max-width:[^"]*"/, 'style="background:#ffffff"');
  if (!/xmlns=/.test(svg)) svg = svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ');

  fs.writeFileSync(path.join(OUTDIR, name), svg, 'utf8');
  written.push({ ...b, name, w: res.w, h: res.h, bytes: svg.length });
  console.log(`  wrote ${name}  ${res.w}x${res.h}  ${svg.length} bytes`);
}

await browser.close();

fs.writeFileSync(
  path.join(process.env.SCRATCH || '.', 'diagram_manifest.json'),
  JSON.stringify(written, null, 1),
  'utf8',
);
console.log(`\n${written.length} of ${blocks.length} rendered`);
