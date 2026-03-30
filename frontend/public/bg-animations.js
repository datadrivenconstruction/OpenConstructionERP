/**
 * OpenConstructionERP Background Animations
 * Animated estimation tables, dashboard charts, construction blueprints
 */

var OCE_BG_CONFIG = {
  cellInterval: 500,    // ms between cell updates
  barInterval: 800,     // ms between bar jitters
  activateCount: 3,     // cells to activate per tick
  deactivateCount: 2,   // cells to deactivate per tick
  seedPercent: 0.45     // initial visible cells percentage
};

// === Estimation Data ===
var OCE_DATA = {
  headers: ['Pos.', 'Description', 'Unit', 'Qty', 'Rate', 'Total', 'CG'],
  rows: [
    {t:'s', v:['300','Structure — Building Construction','','','','','']},
    {t:'p', v:['01.001','Reinforced concrete C30/37, slab','m\u00B3','86.40','\u20AC295.00','\u20AC25,488','330']},
    {t:'p', v:['01.002','Formwork base slab, smooth','m\u00B2','432.00','\u20AC38.50','\u20AC16,632','330']},
    {t:'p', v:['01.003','Reinforcement BSt 500S, mesh','kg','10,368','\u20AC2.18','\u20AC22,602','330']},
    {t:'p', v:['01.004','Reinforced concrete C30/37, walls','m\u00B3','156.00','\u20AC285.00','\u20AC44,460','330']},
    {t:'p', v:['01.005','Formwork walls, smooth finish','m\u00B2','1,248','\u20AC42.50','\u20AC53,040','330']},
    {t:'s', v:['','Subtotal CG 330','','','','\u20AC162,222','330']},
    {t:'s', v:['340','Structure — Interior Walls','','','','','']},
    {t:'p', v:['02.001','Masonry KS 24cm','m\u00B2','890.00','\u20AC68.00','\u20AC60,520','340']},
    {t:'p', v:['02.002','Masonry KS 11.5cm','m\u00B2','620.00','\u20AC48.00','\u20AC29,760','340']},
    {t:'s', v:['','Subtotal CG 340','','','','\u20AC90,280','340']},
    {t:'s', v:['400','Building Services','','','','','']},
    {t:'p', v:['04.001','Heating pipes, copper DN15','m','840.00','\u20AC28.50','\u20AC23,940','420']},
    {t:'p', v:['04.002','Cable NYM-J 3x1.5','m','2,800','\u20AC4.80','\u20AC13,440','440']}
  ],
  rightCols: [3, 4, 5, 6]
};

// === Chart SVG Templates ===
var OCE_CHARTS = {
  bars: '<svg viewBox="0 0 250 180"><rect x="5" y="5" width="240" height="170" rx="6" fill="none" stroke="#0050dc" stroke-width=".8"/><text x="15" y="22" font-size="8" fill="#0050dc" opacity=".3" font-weight="700">COST PER TRADE</text><rect x="20" y="140" width="20" height="30" rx="3" fill="#0050dc" opacity=".15"/><rect x="50" y="100" width="20" height="70" rx="3" fill="#0050dc" opacity=".18"/><rect x="80" y="80" width="20" height="90" rx="3" fill="#0050dc" opacity=".22"/><rect x="110" y="110" width="20" height="60" rx="3" fill="#0050dc" opacity=".14"/><rect x="140" y="60" width="20" height="110" rx="3" fill="#0050dc" opacity=".25"/><rect x="170" y="90" width="20" height="80" rx="3" fill="#0050dc" opacity=".17"/><rect x="200" y="120" width="20" height="50" rx="3" fill="#0050dc" opacity=".12"/></svg>',

  donut: '<svg viewBox="0 0 180 180"><circle cx="90" cy="90" r="60" fill="none" stroke="#0050dc" stroke-width="14" stroke-dasharray="130 377" transform="rotate(-90 90 90)"/><circle cx="90" cy="90" r="60" fill="none" stroke="#0050dc" stroke-width="14" stroke-dasharray="95 377" stroke-dashoffset="-130" transform="rotate(-90 90 90)" opacity=".7"/><circle cx="90" cy="90" r="60" fill="none" stroke="#0050dc" stroke-width="14" stroke-dasharray="75 377" stroke-dashoffset="-225" transform="rotate(-90 90 90)" opacity=".5"/></svg>',

  sparkline: '<svg viewBox="0 0 250 100"><defs><linearGradient id="oceSpkG" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#0050dc" stop-opacity=".1"/><stop offset="100%" stop-color="#0050dc" stop-opacity="0"/></linearGradient></defs><polygon points="10,80 30,70 55,75 80,60 105,55 130,65 155,45 180,35 205,38 230,25 230,90 10,90" fill="url(#oceSpkG)"/><polyline points="10,80 30,70 55,75 80,60 105,55 130,65 155,45 180,35 205,38 230,25" fill="none" stroke="#0050dc" stroke-width="1.5" stroke-linecap="round"/></svg>',

  mixed: '<svg viewBox="0 0 280 180"><rect x="5" y="5" width="130" height="170" rx="6" fill="none" stroke="#0050dc" stroke-width=".8"/><circle cx="70" cy="90" r="45" fill="none" stroke="#0050dc" stroke-width="10" stroke-dasharray="100 283" transform="rotate(-90 70 90)"/><circle cx="70" cy="90" r="45" fill="none" stroke="#0050dc" stroke-width="10" stroke-dasharray="71 283" stroke-dashoffset="-100" transform="rotate(-90 70 90)" opacity=".6"/><rect x="145" y="5" width="130" height="170" rx="6" fill="none" stroke="#0050dc" stroke-width=".8"/><rect x="160" y="130" width="15" height="30" rx="2" fill="#0050dc" opacity=".12"/><rect x="185" y="100" width="15" height="60" rx="2" fill="#0050dc" opacity=".16"/><rect x="210" y="85" width="15" height="75" rx="2" fill="#0050dc" opacity=".2"/><rect x="235" y="110" width="15" height="50" rx="2" fill="#0050dc" opacity=".14"/><rect x="260" y="70" width="15" height="90" rx="2" fill="#0050dc" opacity=".22"/></svg>'
};

// === Blueprint SVG Templates ===
var OCE_BLUEPRINTS = {
  plot: '<svg viewBox="0 0 600 400"><line x1="50" y1="350" x2="550" y2="350" stroke="#0050dc" stroke-width="1.5" class="oce-draw" style="--len:500"/><line x1="100" y1="350" x2="100" y2="320" stroke="#0050dc" stroke-width="1" class="oce-draw" style="--len:30"/><line x1="500" y1="350" x2="500" y2="320" stroke="#0050dc" stroke-width="1" class="oce-draw" style="--len:30"/><rect x="120" y="280" width="360" height="70" rx="2" fill="none" stroke="#0050dc" stroke-width=".8" stroke-dasharray="8 6"/><text x="300" y="388" text-anchor="middle" font-size="10" fill="#0050dc" font-family="monospace">46.00 m</text></svg>',

  frame: '<svg viewBox="0 0 600 400"><line x1="50" y1="350" x2="550" y2="350" stroke="#0050dc" stroke-width="1.5"/><line x1="150" y1="350" x2="150" y2="120" stroke="#0050dc" stroke-width="1.2" class="oce-draw" style="--len:230"/><line x1="250" y1="350" x2="250" y2="120" stroke="#0050dc" stroke-width="1.2" class="oce-draw" style="--len:230"/><line x1="350" y1="350" x2="350" y2="120" stroke="#0050dc" stroke-width="1.2" class="oce-draw" style="--len:230"/><line x1="450" y1="350" x2="450" y2="120" stroke="#0050dc" stroke-width="1.2" class="oce-draw" style="--len:230"/><line x1="140" y1="200" x2="460" y2="200" stroke="#0050dc" stroke-width="1" class="oce-draw" style="--len:320"/><line x1="140" y1="270" x2="460" y2="270" stroke="#0050dc" stroke-width="1" class="oce-draw" style="--len:320"/><line x1="140" y1="120" x2="460" y2="120" stroke="#0050dc" stroke-width="1" class="oce-draw" style="--len:320"/></svg>',

  walls: '<svg viewBox="0 0 600 400"><line x1="50" y1="350" x2="550" y2="350" stroke="#0050dc" stroke-width="1.5"/><rect x="130" y="120" width="340" height="230" rx="2" fill="none" stroke="#0050dc" stroke-width="1.2" class="oce-draw" style="--len:1140"/><path d="M130 120 L300 60 L470 120" fill="none" stroke="#0050dc" stroke-width="1" class="oce-draw" style="--len:360"/><rect x="170" y="170" width="40" height="50" rx="1" fill="none" stroke="#0050dc" stroke-width=".7"/><rect x="260" y="170" width="40" height="50" rx="1" fill="none" stroke="#0050dc" stroke-width=".7"/><rect x="350" y="170" width="40" height="50" rx="1" fill="none" stroke="#0050dc" stroke-width=".7"/><rect x="270" y="290" width="60" height="60" rx="1" fill="none" stroke="#0050dc" stroke-width=".8"/></svg>',

  interior: '<svg viewBox="0 0 600 400"><line x1="50" y1="350" x2="550" y2="350" stroke="#0050dc" stroke-width="1.5"/><rect x="130" y="120" width="340" height="230" rx="2" fill="none" stroke="#0050dc" stroke-width="1"/><path d="M130 120 L300 60 L470 120" fill="none" stroke="#0050dc" stroke-width=".8"/><line x1="300" y1="120" x2="300" y2="350" stroke="#0050dc" stroke-width=".6"/><line x1="130" y1="200" x2="470" y2="200" stroke="#0050dc" stroke-width=".5"/><line x1="130" y1="270" x2="470" y2="270" stroke="#0050dc" stroke-width=".5"/><path d="M300 270 L320 250 L320 270 L340 250 L340 270 L360 250 L360 270" fill="none" stroke="#0050dc" stroke-width=".6"/></svg>',

  drawing: '<svg viewBox="0 0 600 400"><rect x="80" y="60" width="440" height="280" rx="2" fill="none" stroke="#0050dc" stroke-width="1.2" class="oce-draw" style="--len:1440"/><line x1="250" y1="60" x2="250" y2="200" stroke="#0050dc" stroke-width=".8"/><line x1="80" y1="200" x2="400" y2="200" stroke="#0050dc" stroke-width=".8"/><line x1="400" y1="60" x2="400" y2="340" stroke="#0050dc" stroke-width=".8"/><line x1="80" y1="360" x2="520" y2="360" stroke="#0050dc" stroke-width=".4" stroke-dasharray="4 3"/><circle cx="250" cy="200" r="25" fill="none" stroke="#0050dc" stroke-width=".5" stroke-dasharray="3 3"/></svg>',

  skyline: '<svg viewBox="0 0 600 300"><rect x="50" y="80" width="120" height="220" rx="2" fill="none" stroke="#0050dc" stroke-width="1.5"/><rect x="200" y="30" width="100" height="270" rx="2" fill="none" stroke="#0050dc" stroke-width="1.5"/><rect x="330" y="100" width="80" height="200" rx="2" fill="none" stroke="#0050dc" stroke-width="1.5"/><rect x="440" y="60" width="90" height="240" rx="2" fill="none" stroke="#0050dc" stroke-width="1.5"/><line x1="20" y1="300" x2="560" y2="300" stroke="#0050dc" stroke-width="1"/></svg>'
};

// === Initialize Tables ===
function oceInitTable(container) {
  var rows = parseInt(container.getAttribute('data-rows') || '10');
  var grid = document.createElement('div');
  grid.className = 'oce-bg-table-grid';

  // Headers
  OCE_DATA.headers.forEach(function(h, i) {
    var d = document.createElement('div');
    d.className = 'oce-bg-cell oce-bg-cell-header' + (OCE_DATA.rightCols.indexOf(i) > -1 ? ' oce-bg-cell-right' : '');
    d.textContent = h;
    grid.appendChild(d);
  });

  // Data rows
  var cells = [];
  var dataRows = OCE_DATA.rows.slice(0, rows);
  dataRows.forEach(function(row) {
    row.v.forEach(function(val, ci) {
      var d = document.createElement('div');
      var isSection = row.t === 's';
      d.className = 'oce-bg-cell'
        + (ci === 0 ? ' oce-bg-cell-pos' : '')
        + (ci === 1 ? ' oce-bg-cell-desc' : '')
        + (ci === 5 ? ' oce-bg-cell-total' : '')
        + (OCE_DATA.rightCols.indexOf(ci) > -1 ? ' oce-bg-cell-right' : '')
        + (isSection ? ' oce-bg-cell-section' : '');
      d.setAttribute('data-txt', val);
      grid.appendChild(d);
      if (!isSection && ci > 0) cells.push(d);
    });
  });

  container.appendChild(grid);

  // Show sections & positions always
  grid.querySelectorAll('.oce-bg-cell-section').forEach(function(s) {
    s.classList.add('on-m');
    s.textContent = s.getAttribute('data-txt');
  });
  grid.querySelectorAll('.oce-bg-cell-pos').forEach(function(p) {
    p.classList.add('on');
    p.textContent = p.getAttribute('data-txt');
  });

  // Seed initial cells
  var levels = ['on', 'on-m', 'on-h'];
  var shuffled = cells.slice().sort(function() { return Math.random() - 0.5; });
  for (var i = 0; i < Math.floor(cells.length * OCE_BG_CONFIG.seedPercent); i++) {
    var c = shuffled[i];
    c.classList.add(levels[Math.floor(Math.random() * 3)]);
    c.textContent = c.getAttribute('data-txt');
  }

  // Animate
  setInterval(function() {
    for (var a = 0; a < OCE_BG_CONFIG.activateCount; a++) {
      var cell = cells[Math.floor(Math.random() * cells.length)];
      cell.classList.remove('on', 'on-m', 'on-h');
      var col = Array.from(cell.parentElement.children).indexOf(cell) % 7;
      var lvl = col === 5 ? 'on-h' : col >= 3 ? 'on-m' : levels[Math.floor(Math.random() * 3)];
      cell.classList.add(lvl);
      cell.textContent = cell.getAttribute('data-txt');
    }
    for (var d = 0; d < OCE_BG_CONFIG.deactivateCount; d++) {
      var dc = cells[Math.floor(Math.random() * cells.length)];
      if (dc.classList.contains('on') || dc.classList.contains('on-m') || dc.classList.contains('on-h')) {
        dc.classList.remove('on', 'on-m', 'on-h');
        dc.textContent = '';
      }
    }
  }, OCE_BG_CONFIG.cellInterval);
}

// === Initialize Charts ===
function oceInitChart(container) {
  var type = container.getAttribute('data-type') || 'bars';
  if (OCE_CHARTS[type]) {
    container.innerHTML = OCE_CHARTS[type];
  }
}

// === Initialize Blueprints ===
function oceInitBlueprint(container) {
  var stage = container.getAttribute('data-stage') || 'frame';
  if (OCE_BLUEPRINTS[stage]) {
    container.innerHTML = OCE_BLUEPRINTS[stage];
  }

  // Draw-on-scroll with IntersectionObserver
  var obs = new IntersectionObserver(function(entries) {
    entries.forEach(function(e) {
      if (e.isIntersecting) {
        e.target.querySelectorAll('.oce-draw').forEach(function(el) {
          el.classList.add('drawn');
        });
        obs.unobserve(e.target);
      }
    });
  }, { threshold: 0.15 });
  obs.observe(container);
}

// === Auto-initialize on DOM ready ===
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.oce-bg-table').forEach(oceInitTable);
  document.querySelectorAll('.oce-bg-chart').forEach(oceInitChart);
  document.querySelectorAll('.oce-bg-blueprint').forEach(oceInitBlueprint);
});
