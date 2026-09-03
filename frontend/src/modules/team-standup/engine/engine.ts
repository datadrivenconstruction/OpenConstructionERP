// @ts-nocheck
/* eslint-disable */
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The Team Standup & Delivery Board engine.
//
// Ported from the approved interactive preview (Sep 2026) - the preview
// went through two full stress passes and IS the spec, so the
// interaction code below is kept as close to verbatim as the data layer
// allows. What changed in the port:
//
//   * Every piece of board data (stages, activities, waiting reasons,
//     tasks, entries, the log, jobs, people) comes off the server's
//     /team-standup/full-board payload instead of hard-coded seeds.
//   * Every mutation is optimistic-local THEN calls the API; a failure
//     toasts and the next poll reconciles. Stage moves are the
//     exception: the server owns stage templates and recurrence, so the
//     follow-ups/repeats an actual move creates come back in the move
//     response and are inserted from there - the client never invents
//     them.
//   * localStorage now holds ONLY per-viewer UI prefs (tile collapse,
//     table sizing, column widths) - never data.
//
// This file is deliberately vanilla JS in a .ts wrapper (ts-nocheck):
// typing 3,000 lines of ported DOM code adds risk, not safety - the
// typed surface is the adapter boundary in ../api.ts.

import * as API from '../api';
import { UNASSIGNED, assigneeMatches, dueMatches, isWorkshopRequest } from '../data/board';
import { fmtFixed, fmtList } from '@/shared/lib/formatters';

export interface StandupEngineHandle {
  dispose(): void;
  refresh(board: unknown): void;
}

export function bootStandupEngine(opts: {
  root: HTMLElement;
  board: unknown;
  navigate: (path: string) => void;
}): StandupEngineHandle {
  'use strict';

  var LS = 'oe-standup-ui-v1';

  var COLORS = ['slate','violet','indigo','blue','cyan','teal','green','lime','amber','orange','rose','red'];

  function load() { try { return JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) { return null; } }
  var saved = load() || {};

  var CLEANUP = [];
  function docListen(target, type, fn, cap) {
    target.addEventListener(type, fn, cap);
    CLEANUP.push(function () { target.removeEventListener(type, fn, cap); });
  }
  function fail(msg) {
    return function (err) {
      toast(msg + ' - ' + ((err && err.message) ? err.message : 'server error'));
    };
  }

  /* ---------- server data, rebuilt wholesale on every refresh ---------- */
  var BOARD, ME_ID, ME_NAME, TODAY, SOON, TOMORROW, ENDWEEK, NEXTWEEK;
  var STAGES = [], ACTS = [], WAITS = [], JOBS = [], CLIENT_COLOR = {}, PEOPLE = {};
  // Per-job stage runs keyed by project id. A job in here shows ONLY
  // these columns; every other job shows STAGES.
  var OVERRIDES = {};
  // Client brand colours (hex) off the client contact, keyed by client
  // label - wins over the CLIENT_COLOR palette wherever a chip is tinted.
  var CLIENT_HEX = {};
  var TASKS = [], TEAM = [], WEEK = {}, LOG = [], DAYS = [], DAY_ISO = [];

  var PRIOS = [
    { key: 'urgent', label: 'Urgent', gl: '\u25b2', c: 'red', loud: true },
    { key: 'high', label: 'High', gl: '\u25b4', c: 'orange' },
    { key: 'medium', label: 'Medium', gl: '\u25ac', c: 'amber' },
    { key: 'low', label: 'Low', gl: '\u25be', c: 'blue' }
  ];

  /* A task rarely stands alone here: it comes off an RFI you raised, an
     order you placed, or an email that landed. `link` is that tie back to
     whichever ERP module owns the record. The engine speaks the short
     kinds; REG_KIND translates to the register module's vocabulary. */
  var LINK_KINDS = [
    { k: 'rfi', label: 'RFI', c: 'violet', mod: 'Registers', path: '/comms-intelligence' },
    { k: 'rfq', label: 'RFQ', c: 'indigo', mod: 'Registers', path: '/comms-intelligence' },
    { k: 'order', label: 'Order', c: 'blue', mod: 'Procurement', path: '/comms-intelligence' },
    { k: 'vo', label: 'Variation', c: 'orange', mod: 'Registers', path: '/comms-intelligence' },
    { k: 'del', label: 'Delay', c: 'teal', mod: 'Registers', path: '/comms-intelligence' },
    { k: 'tbx', label: 'Toolbox', c: 'lime', mod: 'Registers', path: '/comms-intelligence' },
    // A department request (engineering, drafting, workshop, automation,
    // hazardous area) lives in the Work requests module. Its chip opens
    // the request itself - see linkPath() - not the module's front door.
    { k: 'request', label: 'Request', c: 'rose', mod: 'Work requests', path: '/work-requests' },
    // Correspondence lives on the register item's thread in this build,
    // so an email link lands on Comms Intelligence rather than a separate
    // mail module that is not mounted here.
    { k: 'mail', label: 'Email', c: 'cyan', mod: 'Comms Intelligence', path: '/comms-intelligence' }
  ];
  var REG_KIND = { rfi: 'rfi', rfq: 'rfq', order: 'order', vo: 'variation', del: 'delay', tbx: 'toolbox' };
  var ENGINE_KIND = { rfi: 'rfi', rfq: 'rfq', order: 'order', variation: 'vo', delay: 'del', toolbox: 'tbx' };
  function linkKind(k) { for (var i = 0; i < LINK_KINDS.length; i++) if (LINK_KINDS[i].k === k) return LINK_KINDS[i]; return null; }
  /** Where a linked record opens. Register kinds land on their module's
      workspace; a work request opens on the request itself when the link
      carries its id (a hand-typed reference falls back to the module). */
  function linkPath(l) {
    var lk = l ? linkKind(l.kind) : null;
    if (!lk) return '/';
    if (lk.k === 'request' && l.targetId) return lk.path + '/' + encodeURIComponent(l.targetId);
    return lk.path;
  }
  /** The Work requests module owns its raise dialog - the board only
      opens it on the right job. */
  function raiseRequestPath(pid) { return '/work-requests?raise=1&project=' + encodeURIComponent(pid); }

  function linkChip(l) {
    if (!l) return '';
    var lk = linkKind(l.kind);
    if (!lk) return '';
    return '<span class="linkchip" data-act="link" style="' + tint(lk.c) + '" title="' + esc(lk.label) + ' in ' + esc(lk.mod) + ': ' + esc(l.ref) + '">' +
      esc(l.ref) + '</span>';
  }

  /* Recurrence display rules - CREATION lives on the server (the move
     endpoint), these mirrors only paint tooltips and the month view's
     dashed projections. Same semantics: monthly means the same day of
     the month (clamped), and the next date reads off the SCHEDULE. */
  var REPEATS = [
    { key: '', label: 'Does not repeat' },
    { key: 'weekly', label: 'Weekly' },
    { key: 'fortnightly', label: 'Fortnightly' },
    { key: 'monthly', label: 'Monthly, same date' },
    { key: 'monthly-last', label: 'Monthly, last working day' }
  ];
  function repeatOf(k) { for (var i = 0; i < REPEATS.length; i++) if (REPEATS[i].key === k) return REPEATS[i]; return REPEATS[0]; }

  var DOW = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  var MON3 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function ymd(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function parseISO(s) { var p = s.split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); }
  function lastWorkingDay(year, month) {
    var d = new Date(year, month + 1, 0);
    while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
    return d;
  }
  function nextOccurrence(iso, rep) {
    if (!iso || !rep) return null;
    var d = parseISO(iso);
    if (rep === 'weekly') { d.setDate(d.getDate() + 7); return ymd(d); }
    if (rep === 'fortnightly') { d.setDate(d.getDate() + 14); return ymd(d); }
    if (rep === 'monthly-last') return ymd(lastWorkingDay(d.getFullYear(), d.getMonth() + 1));
    if (rep === 'monthly') {
      var day = d.getDate();
      var target = new Date(d.getFullYear(), d.getMonth() + 1, 1);
      var lastOfMonth = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
      target.setDate(Math.min(day, lastOfMonth));
      return ymd(target);
    }
    return null;
  }
  function describeRepeat(t) {
    if (!t.rep) return 'Does not repeat';
    if (!t.due) return repeatOf(t.rep).label + ' (needs a due date to set the rhythm)';
    var d = parseISO(t.due);
    if (t.rep === 'weekly') return 'Every ' + DOW[d.getDay()];
    if (t.rep === 'fortnightly') return 'Every second ' + DOW[d.getDay()];
    if (t.rep === 'monthly') return 'The ' + ordinal(d.getDate()) + ' of each month';
    if (t.rep === 'monthly-last') return 'The last working day of each month';
    return repeatOf(t.rep).label;
  }
  function ordinal(n) {
    var s = ['th','st','nd','rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function dayLabel(iso) { var p = iso.split('-'); return parseInt(p[2], 10) + ' ' + MON3[parseInt(p[1], 10) - 1]; }
  function whenParts(isoDateTime) {
    var d = new Date(isoDateTime);
    if (isNaN(d.getTime())) return { at: '', day: '' };
    return { at: pad2(d.getHours()) + ':' + pad2(d.getMinutes()), day: ymd(d) };
  }
  function stamp() { var d = new Date(); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()); }

  /* ---------- server -> engine mapping ---------- */
  function stageFromServer(s) {
    return { id: String(s.id), name: s.name, color: s.color, wip: s.wip_limit == null ? null : s.wip_limit, done: !!s.is_done, spawn: (s.spawn || []).slice() };
  }
  function actFromServer(a) {
    return { id: String(a.id), name: a.name, color: a.color, excl: !!a.exclusive };
  }
  function jobIdOf(code) { var j = job(code); return j ? j.id : null; }
  function codeOfJobId(id) {
    for (var i = 0; i < JOBS.length; i++) if (JOBS[i].id === String(id)) return JOBS[i].code;
    return '';
  }
  function commentFromServer(c) {
    var w = whenParts(c.created_at);
    return { id: String(c.id), who: c.author_name, body: c.body, at: w.at, day: w.day };
  }
  var thumbTimer = null;
  function scheduleRedraw() {
    if (thumbTimer) return;
    thumbTimer = setTimeout(function () { thumbTimer = null; redrawAll(true); }, 150);
  }
  var THUMB_CACHE = {};
  function fileFromServer(fkind, f) {
    var rec = { fileId: String(f.id), fkind: fkind, name: f.filename, size: f.size_bytes, type: f.mime_type, url: null };
    if ((rec.type || '').indexOf('image') === 0) {
      // Object URLs are cached per file id so a poll refresh never
      // re-downloads every thumbnail on the board.
      if (THUMB_CACHE[rec.fileId]) {
        rec.url = THUMB_CACHE[rec.fileId];
      } else {
        API.fileObjectUrl(fkind, rec.fileId).then(function (u) {
          THUMB_CACHE[rec.fileId] = u;
          rec.url = u;
          scheduleRedraw();
        }).catch(function () {});
      }
    }
    return rec;
  }
  function taskFromServer(t) {
    return {
      id: String(t.id), sub: !!t.is_sub, t: t.title,
      job: codeOfJobId(t.project_id) || '?', st: String(t.stage_id),
      who: String(t.assignee_id), due: t.due || null, p: t.priority || 'medium',
      wait: t.waiting_on || '', notes: t.notes || '', rep: t.repeat_rule || '',
      link: (t.link_kind && t.link_ref) ? { kind: t.link_kind, ref: t.link_ref, targetId: t.link_target_id || '' } : null,
      // 'private' reaches only its creator, assignee and admins - the
      // server already filtered, so anything here is ours to see.
      vis: t.visibility === 'private' ? 'private' : 'public',
      by: t.created_by || '',
      files: (t.files || []).map(function (f) { return fileFromServer('task', f); }),
      comments: (t.comments || []).map(commentFromServer)
    };
  }
  function lockGlyph(t) {
    return t.vis === 'private'
      ? '<span class="lock" title="Private - only you and the assignee see it">&#128274;</span>'
      : '';
  }

  function lastEntryBefore(userId) {
    var best = null;
    (BOARD.week.entries || []).forEach(function (e) {
      if (e.user_id !== userId || e.day >= TODAY) return;
      if (!best || e.day > best.day) best = e;
    });
    return best;
  }

  function buildTeam() {
    var byUser = {};
    (BOARD.entries || []).forEach(function (e) { byUser[e.user_id] = e; });
    TEAM = (BOARD.people || []).map(function (p) {
      var e = byUser[p.id];
      if (!e) {
        var last = lastEntryBefore(p.id);
        return { who: p.id, me: p.id === ME_ID, acts: null, jobs: [], posted: '', comments: [], photos: [],
                 last: last ? { day: dayLabel(last.day), text: last.today || last.blockers || '', at: whenParts(last.created_at).at } : null };
      }
      var created = whenParts(e.created_at);
      var editedTs = whenParts(e.updated_at);
      var wasEdited = (e.updated_at || '').slice(0, 16) !== (e.created_at || '').slice(0, 16);
      return {
        who: p.id, me: p.id === ME_ID, entryId: String(e.id),
        acts: (e.activities || []).slice(),
        jobs: (e.job_ids || []).map(codeOfJobId).filter(Boolean),
        posted: created.at, edited: wasEdited ? editedTs.at : '',
        y: e.yesterday || '', t: e.today || '', b: e.blockers || '', bBy: e.blocker_by || '',
        comments: (e.comments || []).map(commentFromServer),
        photos: (e.files || []).map(function (f) { return fileFromServer('entry', f); })
      };
    });
    TEAM.sort(function (a, b) {
      return ((b.me ? 1 : 0) - (a.me ? 1 : 0)) ||
        (((b.acts && b.acts.length) ? 1 : 0) - ((a.acts && a.acts.length) ? 1 : 0)) ||
        ((PEOPLE[a.who] || {}).name || '').localeCompare(((PEOPLE[b.who] || {}).name || ''));
    });
    // The @mention pips are DERIVED from the comment bodies on the wire,
    // not remembered locally - a counter bumped at post time was wiped
    // by the next poll refresh, so a pip lived at most 45 seconds.
    var mentions = {};
    function countMentions(body) {
      Object.keys(PEOPLE).forEach(function (k) {
        var n = PEOPLE[k].name, f = n.split(' ')[0];
        if (body.indexOf('@' + n) > -1 || body.indexOf('@' + f) > -1) {
          mentions[k] = (mentions[k] || 0) + 1;
        }
      });
    }
    (BOARD.entries || []).forEach(function (e) {
      (e.comments || []).forEach(function (c) { countMentions(c.body || ''); });
    });
    (BOARD.tasks || []).forEach(function (t) {
      (t.comments || []).forEach(function (c) { countMentions(c.body || ''); });
    });
    TEAM.forEach(function (p) { if (mentions[p.who]) p.mentions = mentions[p.who]; });
  }

  function buildWeek() {
    WEEK = {};
    (BOARD.week.entries || []).forEach(function (e) {
      var label = isoToLabel(e.day);
      if (!label) return;
      (WEEK[e.user_id] = WEEK[e.user_id] || {})[label] = {
        acts: (e.activities || []).slice(),
        txt: e.today || e.yesterday || '',
        blk: !!e.blockers,
        at: whenParts(e.created_at).at
      };
    });
  }

  function buildFromBoard(b) {
    BOARD = b;
    ME_ID = String(BOARD.me.user_id);
    ME_NAME = BOARD.me.name;
    TODAY = BOARD.today;
    SOON = addDays(TODAY, 3);
    TOMORROW = addDays(TODAY, 1);
    NEXTWEEK = addDays(TODAY, 7);
    var td = parseISO(TODAY);
    ENDWEEK = addDays(TODAY, (5 - td.getDay() + 7) % 7);

    STAGES = (BOARD.stages || []).map(stageFromServer);
    OVERRIDES = {};
    Object.keys(BOARD.stage_overrides || {}).forEach(function (pid) {
      var rows = (BOARD.stage_overrides[pid] || []).map(stageFromServer);
      if (rows.length) OVERRIDES[String(pid)] = rows;
    });
    ACTS = (BOARD.activities || []).map(actFromServer);
    WAITS = (BOARD.waits || []).slice();

    JOBS = (BOARD.jobs || []).map(function (j) {
      return { id: String(j.id), code: j.code, client: j.client || '', name: j.label || j.name, color: j.client_color || '' };
    });
    CLIENT_COLOR = {};
    CLIENT_HEX = {};
    (function () {
      var pal = ['blue','violet','teal','orange','cyan','rose','lime','indigo','green','amber','red','slate'];
      var seen = [];
      JOBS.forEach(function (j) {
        if (seen.indexOf(j.client) === -1) seen.push(j.client);
        CLIENT_COLOR[j.client] = pal[seen.indexOf(j.client) % pal.length];
        // The client's own brand colour, when the contact carries one.
        if (j.color && !CLIENT_HEX[j.client]) CLIENT_HEX[j.client] = j.color;
      });
    })();

    PEOPLE = {};
    (BOARD.people || []).forEach(function (p) {
      PEOPLE[String(p.id)] = { name: p.name, ini: p.initials, color: p.color };
    });

    // The standup week the day navigation walks: Monday to Sunday of the
    // week the server anchored, capped at today (the future is not a
    // standup yet).
    DAY_ISO = [];
    DAYS = [];
    for (var i = 0; i < 7; i++) {
      var iso = addDays(BOARD.week.start, i);
      if (iso > TODAY) break;
      DAY_ISO.push(iso);
      DAYS.push(dayLabel(iso));
    }
    if (DAY_ISO.indexOf(TODAY) === -1) { DAY_ISO.push(TODAY); DAYS.push(dayLabel(TODAY)); }

    TASKS = (BOARD.tasks || []).map(taskFromServer);
    LOG = (BOARD.log || []).map(function (l) {
      return { at: whenParts(l.created_at).at, who: l.author_name, what: l.what, where: l.where_label, kind: l.kind, c: l.color };
    });
    buildTeam();
    buildWeek();
    for (var mi = 0; mi < TEAM.length; mi++) {
      if (TEAM[mi].who === ME_ID) {
        lastSavedAt = TEAM[mi].edited || TEAM[mi].posted || lastSavedAt;
        break;
      }
    }
  }
  buildFromBoard(opts.board);

  function isoToLabel(iso) { var i = DAY_ISO.indexOf(iso); return i > -1 ? DAYS[i] : ''; }

  var viewDay = TODAY;
  function longDate(iso) {
    var d = parseISO(iso);
    return DOW[d.getDay()] + ', ' + d.getDate() + ' ' +
      ['January','February','March','April','May','June','July','August','September','October','November','December'][d.getMonth()] +
      ' ' + d.getFullYear();
  }
  /** The team's entries as they stand on `viewDay`. */
  function teamOn(iso) {
    if (iso === TODAY) return TEAM;
    var label = isoToLabel(iso);
    return TEAM.map(function (p) {
      var e = label && WEEK[p.who] ? WEEK[p.who][label] : null;
      if (!e) return { who: p.who, me: p.me, acts: null, jobs: [], posted: '', comments: [], readonly: true };
      return { who: p.who, me: p.me, acts: e.acts, jobs: p.jobs || [], posted: e.at, edited: '',
               y: '', t: e.txt, b: e.blk ? 'Had a blocker that day.' : '', bBy: '',
               comments: [], readonly: true };
    });
  }

  function logIt(what, where, kind, c) {
    LOG.unshift({ at: stamp(), who: ME_NAME, what: what, where: where || '', kind: kind || 'task', c: c || 'blue' });
    if (LOG.length > 200) LOG.length = 200;
  }

  /* localStorage carries UI prefs ONLY - the data lives on the server.
     The task filters count as a pref: they are this viewer's lens on
     the board, and the board opens with them next time. */
  function save() {
    try {
      localStorage.setItem(LS, JSON.stringify({
        tblSize: tblSize, colW: colW, tiles: tileState(), allCardsOpen: allCardsOpen,
        filters: syncFiltersFromDom(), defaultFilters: DEFAULT_F,
        groupBy: groupBy, groupClosed: groupClosed
      }));
    } catch (e) {}
  }

  /* ---------- sync: entry (debounced), config (debounced) ---------- */
  var entrySaveTimer = null;
  function queueEntrySave() {
    clearTimeout(entrySaveTimer);
    entrySaveTimer = setTimeout(function () { entrySaveTimer = null; pushEntry(); }, 900);
    saveFlash = 'pending';
    paintSaveState();
  }
  function pushEntry(cb) {
    clearTimeout(entrySaveTimer); entrySaveTimer = null;
    var m = me();
    API.saveEntryV3({
      day: TODAY, status: 'office',
      yesterday: m.y || '', today: m.t || '', blockers: m.b || '',
      blocker_by: m.bBy || '', activities: m.acts || [],
      job_ids: (m.jobs || []).map(jobIdOf).filter(Boolean)
    }).then(function (e) {
      m.entryId = String(e.id);
      var c = whenParts(e.created_at);
      if (!m.posted) m.posted = c.at;
      var wasEdited = (e.updated_at || '').slice(0, 16) !== (e.created_at || '').slice(0, 16);
      m.edited = wasEdited ? whenParts(e.updated_at).at : '';
      saveFlash = '';
      lastSavedAt = stamp();
      paintSaveState();
      if (cb) cb(e);
    }).catch(function (err) {
      saveFlash = 'error';
      paintSaveState();
      fail('Could not save your update')(err);
    });
  }

  /* One save path for every stage list: '' is the standard run, a
     project id is that job's own run. Same debounce, same remap. */
  var stagesSaveTimers = {};
  function stagesSaving() { return Object.keys(stagesSaveTimers).length > 0; }
  function looksServerId(id) { return /^[0-9a-fA-F-]{36}$/.test(String(id)); }
  function queueStagesSave(pid) {
    pid = pid || '';
    clearTimeout(stagesSaveTimers[pid]);
    stagesSaveTimers[pid] = setTimeout(function () { delete stagesSaveTimers[pid]; pushStages(pid); }, 900);
  }
  function stageRows(list) {
    return list.map(function (s) {
      return { id: looksServerId(s.id) ? s.id : null, name: s.name || 'Stage', color: s.color, wip_limit: s.wip == null ? null : s.wip, is_done: !!s.done, spawn: s.spawn || [] };
    });
  }
  function pushStages(pid, cb) {
    pid = pid || '';
    clearTimeout(stagesSaveTimers[pid]); delete stagesSaveTimers[pid];
    var list = listOfScope(pid);
    if (!list) return;
    var prev = list.slice();
    var req = pid ? API.putJobStages(pid, stageRows(list)) : API.putStages(stageRows(list));
    req.then(function (rows) {
      var fresh = rows.map(stageFromServer);
      if (pid) OVERRIDES[pid] = fresh; else STAGES = fresh;
      var ids = {}, byName = {};
      fresh.forEach(function (s) { ids[s.id] = 1; byName[s.name] = s.id; });
      // Re-point the tasks this list owns: a locally-added stage now has
      // its real id (same position wins); a task the server carried
      // across from another run followed its stage NAME, so mirror that.
      TASKS.forEach(function (t) {
        if (pid ? jobIdOf(t.job) !== pid : jobHasOwn(t.job)) return;
        if (ids[t.st]) return;
        var idx = -1;
        prev.forEach(function (p, i) { if (p.id === t.st) idx = i; });
        var was = stageOrNull(t.st);
        t.st = (idx > -1 && fresh[idx]) ? fresh[idx].id : (byName[was ? was.name : ''] || fresh[0].id);
      });
      redrawAll(true);
      if (cb) cb(fresh);
    }).catch(fail('Could not save the stages'));
  }

  var actsSaveTimer = null;
  function queueActsSave() { clearTimeout(actsSaveTimer); actsSaveTimer = setTimeout(function () { actsSaveTimer = null; pushActs(); }, 900); }
  function pushActs() {
    clearTimeout(actsSaveTimer); actsSaveTimer = null;
    API.putActivities(ACTS.map(function (a) {
      return { id: looksServerId(a.id) ? a.id : null, name: a.name || 'Activity', color: a.color, exclusive: !!a.excl };
    })).then(function (rows) {
      ACTS = rows.map(actFromServer);
      redrawAll(true);
    }).catch(fail('Could not save the activities'));
  }

  function saveWaits() {
    API.putWaits(WAITS).then(function (r) {
      WAITS = (r.reasons || []).slice();
    }).catch(fail('Could not save the waiting-on list'));
  }

  function pushTaskField(t, fields) {
    API.patchBoardTask(t.id, fields).catch(fail('Could not save the change'));
  }

  /* Every "give them a task" / "add a task here" / day-cell click lands
     a real "New task" on the server the moment it is clicked - a
     mis-click used to leave junk rows behind. The toast now carries an
     Undo that deletes it again (closing the editor if it is open on it). */
  function createSingleTask(fields, andEdit) {
    API.createBoardTasks([fields]).then(function (rows) {
      var t = taskFromServer(rows[0]);
      TASKS.push(t);
      logIt('Created "' + t.t + '"', t.job, 'task', 'green');
      redrawAll();
      if (andEdit) openEdit(t);
      toast('Task created' + (t.due ? ' - due ' + fmt(t.due) : ''), 'on ' + t.job, function () {
        if (editing === t) closeEdit();
        var i = TASKS.indexOf(t);
        if (i > -1) TASKS.splice(i, 1);
        API.deleteBoardTask(t.id).catch(fail('Could not remove the task'));
        logIt('Removed "' + t.t + '" again', t.job, 'task', 'red');
        redrawAll();
        toast('Task removed');
      });
    }).catch(fail('Could not create the task'));
  }
  function defaultJobId() {
    var m = me();
    if (m && m.jobs && m.jobs.length) { var jid = jobIdOf(m.jobs[0]); if (jid) return jid; }
    return JOBS.length ? JOBS[0].id : null;
  }

  /* ---------- linked records, fetched from their own modules ---------- */
  var EXISTING = [];
  var RECORDS_LOADED = {};
  function fieldsNote(fields) {
    if (!fields) return '';
    var keys = Object.keys(fields).filter(function (k) { return k.indexOf('_') !== 0 && typeof fields[k] === 'string' && fields[k]; });
    return keys.slice(0, 4).map(function (k) { return k + ': ' + fields[k]; }).join('\n');
  }
  function recFromRegister(r) {
    return {
      kind: ENGINE_KIND[r.kind] || r.kind, ref: r.reference, job: codeOfJobId(r.project_id),
      title: r.title || '(untitled)',
      date: (r.created_at || '').slice(0, 10) || r.due_date || '',
      status: r.status + (r.current_step ? ' - ' + r.current_step : ''),
      party: r.ball_in_court_name || r.responsible || '',
      body: fieldsNote(r.fields), files: 0, targetId: String(r.id)
    };
  }
  function recFromMail(m, jobCode) {
    return {
      kind: 'mail', ref: m.reference_number || 'COR', job: jobCode,
      title: m.subject || '(no subject)',
      date: m.date_received || m.date_sent || (m.created_at || '').slice(0, 10) || '',
      status: m.status || '', party: m.direction === 'incoming' ? 'Received' : 'Sent',
      body: m.notes || '', files: 0, targetId: String(m.id)
    };
  }
  /* Department requests come off the Work requests module, which ships
     separately - when it is not mounted its endpoints 404 and the picker
     simply lists none, no toast, no error. Department names are fetched
     once and cached; a key with no name shows as the key. */
  var DEPT_NAMES = null, deptLoad = null;
  function loadDepartments() {
    if (deptLoad) return deptLoad;
    deptLoad = API.fetchWorkRequestDepartments().then(function (rows) {
      DEPT_NAMES = {};
      (rows || []).forEach(function (d) { DEPT_NAMES[d.key] = d.name; });
      return DEPT_NAMES;
    }).catch(function () { DEPT_NAMES = {}; return DEPT_NAMES; });
    return deptLoad;
  }
  function deptName(key) { return (DEPT_NAMES && DEPT_NAMES[key]) || key || ''; }
  function recFromRequest(r) {
    var dept = deptName(r.department);
    var bits = [];
    if (r.request_type) bits.push('Type: ' + r.request_type);
    if (r.responsible && r.responsible.name) bits.push('Responsible: ' + r.responsible.name);
    if (r.ball_in_court) bits.push('Ball in court: ' + (r.ball_in_court === 'requester' ? 'the requester' : (dept || 'the department')));
    if (r.quoted_hours || r.hours_logged) bits.push('Hours: ' + (r.hours_logged || 0) + ' logged of ' + (r.quoted_hours || 0) + ' quoted');
    return {
      kind: 'request', ref: r.reference, job: codeOfJobId(r.project_id) || r.project_code || '',
      title: r.title || '(untitled)',
      date: (r.created_at || '').slice(0, 10) || r.due_date || '',
      status: r.stage || r.status || '',
      party: dept, body: bits.join('\n'), files: 0, targetId: String(r.id)
    };
  }
  function loadRecordsFor(code, done) {
    done = done || function () {};
    if (RECORDS_LOADED[code]) { done(); return; }
    var pid = jobIdOf(code);
    if (!pid) { RECORDS_LOADED[code] = 1; done(); return; }
    Promise.all([
      API.fetchRegisterItems(pid).catch(function () { return []; }),
      API.fetchCorrespondence(pid).catch(function () { return { items: [] }; }),
      API.fetchWorkRequests(pid).catch(function () { return []; }),
      loadDepartments()
    ]).then(function (res) {
      RECORDS_LOADED[code] = 1;
      (res[0] || []).forEach(function (r) {
        if (!EXISTING.some(function (x) { return x.targetId === String(r.id); })) EXISTING.push(recFromRegister(r));
      });
      (((res[1] || {}).items) || []).forEach(function (m) {
        if (!EXISTING.some(function (x) { return x.targetId === String(m.id); })) EXISTING.push(recFromMail(m, code));
      });
      (Array.isArray(res[2]) ? res[2] : []).forEach(function (r) {
        if (!EXISTING.some(function (x) { return x.targetId === String(r.id); })) EXISTING.push(recFromRequest(r));
      });
      done();
    });
  }
  function loadAllRecords(done) {
    var codes = [];
    TASKS.forEach(function (t) { if (t.job && codes.indexOf(t.job) === -1) codes.push(t.job); });
    (me().jobs || []).forEach(function (c) { if (codes.indexOf(c) === -1) codes.push(c); });
    var left = codes.length;
    if (!left) { done(); return; }
    codes.forEach(function (c) { loadRecordsFor(c, function () { if (--left === 0) done(); }); });
  }

  /* ---------- helpers ---------- */
  var toasts = document.getElementById('toasts');
  function toast(msg, mono, undo) {
    var el = document.createElement('div');
    el.className = 'toast';
    var txt = document.createElement('div');
    txt.textContent = msg;
    if (mono) { var s = document.createElement('span'); s.className = 'mono'; s.textContent = mono; txt.appendChild(s); }
    el.appendChild(txt);
    if (undo) {
      var u = document.createElement('button');
      u.className = 'undo'; u.textContent = 'Undo';
      u.addEventListener('click', function () { undo(); el.remove(); });
      el.appendChild(u);
    }
    toasts.appendChild(el);
    setTimeout(function () { el.remove(); }, undo ? 6500 : 3200);
  }
  /** A stage by id from ANY scope - the standard run or a job's own. */
  function stageOrNull(id) {
    for (var i = 0; i < STAGES.length; i++) if (STAGES[i].id === id) return STAGES[i];
    var pids = Object.keys(OVERRIDES);
    for (var k = 0; k < pids.length; k++) {
      var own = OVERRIDES[pids[k]];
      for (var m = 0; m < own.length; m++) if (own[m].id === id) return own[m];
    }
    return null;
  }
  function stage(id) { return stageOrNull(id) || STAGES[0]; }
  /** The stage run a job's board shows: its own when it has one, else the standard set. */
  function stagesOfJob(code) {
    var j = job(code);
    if (j && OVERRIDES[j.id] && OVERRIDES[j.id].length) return OVERRIDES[j.id];
    return STAGES;
  }
  function jobHasOwn(code) { var j = job(code); return !!(j && OVERRIDES[j.id] && OVERRIDES[j.id].length); }
  /** The scope a stage row belongs to: '' for the standard run, else the project id. */
  function scopeOf(s) {
    if (STAGES.indexOf(s) > -1) return '';
    var pids = Object.keys(OVERRIDES);
    for (var k = 0; k < pids.length; k++) if (OVERRIDES[pids[k]].indexOf(s) > -1) return pids[k];
    return '';
  }
  function listOfScope(pid) { return pid ? (OVERRIDES[pid] || null) : STAGES; }
  /** What the Board tab is showing right now: the filtered job's run, else the standard set. */
  function activeStages() {
    var jf = document.getElementById('jobFilter').value;
    return jf ? stagesOfJob(jf) : STAGES;
  }
  function activeScopePid() {
    var jf = document.getElementById('jobFilter').value;
    return (jf && jobHasOwn(jf)) ? jobIdOf(jf) : '';
  }
  /** Where a task shows on a list of columns that may not be its own:
   *  its stage if the list has it, else the column with the same NAME,
   *  else the first column. Display only - moves go through the server. */
  function displayStageIn(t, list) {
    for (var i = 0; i < list.length; i++) if (list[i].id === t.st) return list[i].id;
    var nm = (stageOrNull(t.st) || {}).name;
    for (var k = 0; k < list.length; k++) if (list[k].name === nm) return list[k].id;
    return list[0].id;
  }
  function act(id) { for (var i = 0; i < ACTS.length; i++) if (ACTS[i].id === id) return ACTS[i]; return null; }
  function prio(k) { for (var i = 0; i < PRIOS.length; i++) if (PRIOS[i].key === k) return PRIOS[i]; return PRIOS[2]; }
  function job(code) { for (var i = 0; i < JOBS.length; i++) if (JOBS[i].code === code) return JOBS[i]; return null; }
  function jobName(code) { var j = job(code); return j ? j.client + ' - ' + j.name : code; }
  function taskById(id) { for (var i = 0; i < TASKS.length; i++) if (TASKS[i].id === id) return TASKS[i]; return null; }
  /* textContent -> innerHTML escapes & < > but NOT the double quote, and
     half the markup below drops esc() output into title="..." and
     data-label="..." - a task called Fix "door" used to cut the attribute
     short (and could open a new one). &quot; is inert in text too. */
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML.replace(/"/g, '&quot;'); }
  /** "1 task" / "3 tasks" - never "3 task(s)". */
  function plural(n, word, words) { return n + ' ' + (n === 1 ? word : (words || word + 's')); }
  /* A colour is a palette name ('teal') or, for a client with a brand
     colour, a hex string ('#d62828'). Every tint/swatch goes through
     these two so both spellings paint the same way. */
  function isHex(c) { return typeof c === 'string' && c.charAt(0) === '#'; }
  function cvar(c) { return isHex(c) ? c : 'var(--c-' + (c || 'slate') + ')'; }
  function tint(c) {
    if (isHex(c)) return 'background:color-mix(in srgb,' + c + ' 14%,transparent);color:' + c + ';border-color:color-mix(in srgb,' + c + ' 32%,transparent);';
    return 'background:var(--w-' + c + ');color:var(--c-' + c + ');border-color:color-mix(in srgb,var(--c-' + c + ') 28%,transparent);';
  }
  /** The colour a client's chips wear: its brand colour, else its palette slot. */
  function clientTone(client) { return CLIENT_HEX[client] || CLIENT_COLOR[client] || 'slate'; }
  function jobTone(code) { var j = job(code); return j ? clientTone(j.client) : 'slate'; }
  function fmt(d) {
    if (!d) return '';
    var mon = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var p = d.split('-');
    // "2 Sep", the same shape dayLabel() gives the week headers - the
    // table used to say "02 Sep" beside a header that said "2 Sep".
    return parseInt(p[2], 10) + ' ' + mon[parseInt(p[1], 10) - 1];
  }
  function dueClass(d, done) {
    if (!d || done) return '';
    if (d < TODAY) return ' over';
    if (d <= SOON) return ' soon';
    return '';
  }
  function when(c) {
    // "01 Sep 7:14 am" - short date first so a thread reads chronologically.
    return (c.day ? fmt(c.day) + ' ' : '') + hhmm(c.at);
  }
  function hhmm(t) {
    if (!t) return '';
    var p = t.split(':'), h = parseInt(p[0], 10), ap = h < 12 ? 'am' : 'pm';
    var h12 = h % 12; if (h12 === 0) h12 = 12;
    return h12 + ':' + p[1] + ' ' + ap;
  }
  function avatar(k, small) {
    // A departed assignee's id can outlive the people list - render a
    // neutral chip rather than throwing mid-board.
    var p = PEOPLE[k] || { name: 'Former member', ini: '?', color: '#6b7684' };
    return '<span class="av' + (small ? ' av-sm' : '') + '" style="background:' + p.color + '" title="' + esc(p.name) + '">' + esc(p.ini) + '</span>';
  }
  function addDays(iso, n) {
    if (!iso) return null;
    var p = iso.split('-').map(Number);
    var d = new Date(p[0], p[1] - 1, p[2] + n);
    var m = String(d.getMonth() + 1).padStart(2, '0'), dd = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + dd;
  }

  /* Moving a task into a stage is the moment its follow-ups become real,
     and closing a recurring task is the moment the next one is due. The
     SERVER owns both rails now - every path (drag, menu, tick, dialog)
     funnels here, the stage flips optimistically, and whatever the move
     endpoint actually created (template follow-ups, the next
     occurrence) is inserted from its response. Undo hands the server
     back exactly the ids that response named. */
  function moveToStage(t, stageId) {
    var was = t.st;
    if (was === stageId) return;
    var s = stage(stageId);
    t.st = stageId;
    logIt('Moved "' + t.t + '" to ' + s.name, t.job, 'task', s.color);
    redrawAll();
    API.moveBoardTask(t.id, stageId).then(function (res) {
      var spawned = (res.spawned || []).map(taskFromServer);
      spawned.forEach(function (n) { TASKS.push(n); });
      var repeated = res.repeated ? taskFromServer(res.repeated) : null;
      if (repeated) TASKS.push(repeated);
      if (spawned.length) logIt('Stage template added ' + plural(spawned.length, 'follow-up'), t.job, 'task', 'cyan');
      if (repeated) logIt('"' + t.t + '" repeats - next one due ' + fmt(repeated.due), t.job, 'task', 'cyan');
      if (spawned.length || repeated) redrawAll();
      var extra = [];
      if (spawned.length) extra.push('+' + spawned.length + ' follow-up' + (spawned.length === 1 ? '' : 's'));
      if (repeated) extra.push('next due ' + fmt(repeated.due));
      toast('Moved to ' + s.name + (extra.length ? ' - ' + fmtList(extra) : ''), null, function () {
        API.undoBoardMove(t.id, {
          to_stage_id: was,
          spawned_ids: spawned.map(function (x) { return x.id; }),
          repeated_id: repeated ? repeated.id : null
        }).then(function () {
          t.st = was;
          spawned.concat(repeated ? [repeated] : []).forEach(function (n) {
            var i = TASKS.indexOf(n);
            if (i > -1) TASKS.splice(i, 1);
          });
          redrawAll();
          toast('Moved back');
        }).catch(fail('Could not undo the move'));
      });
    }).catch(function (err) {
      t.st = was;
      redrawAll();
      fail('Could not move the task')(err);
    });
  }
  function markDone(t) {
    var list = stagesOfJob(t.job);
    var d = list.filter(function (s) { return s.done; })[0] || list[list.length - 1];
    moveToStage(t, d.id);
  }
  /* Render @Name as a highlighted mention. */
  function renderMentions(text) {
    var names = Object.keys(PEOPLE).map(function (k) { return PEOPLE[k].name; });
    var out = esc(text);
    names.forEach(function (n) {
      out = out.split('@' + esc(n)).join('<span class="mention">@' + esc(n) + '</span>');
      var first = n.split(' ')[0];
      out = out.split('@' + esc(first)).join('<span class="mention">@' + esc(first) + '</span>');
    });
    return out;
  }
  function mentionedIn(text) {
    var hit = [];
    Object.keys(PEOPLE).forEach(function (k) {
      var n = PEOPLE[k].name, f = n.split(' ')[0];
      if (text.indexOf('@' + n) > -1 || text.indexOf('@' + f) > -1) hit.push(k);
    });
    return hit;
  }

  /* ---------- tiles ---------- */
  function tileState() {
    var o = {};
    Array.prototype.forEach.call(document.querySelectorAll('.tile'), function (t) { o[t.id] = t.getAttribute('open-state'); });
    return o;
  }
  Array.prototype.forEach.call(document.querySelectorAll('.tile'), function (t) {
    if (saved.tiles && saved.tiles[t.id]) t.setAttribute('open-state', saved.tiles[t.id]);
    t.querySelector('[data-toggle]').addEventListener('click', function (e) {
      if (e.target.closest('.tile-tools')) return;
      t.setAttribute('open-state', t.getAttribute('open-state') === '1' ? '0' : '1');
      paintTilesToggle();
      save();
    });
  });
  /* One control, not two: it shows the chevron for what it will DO, so it
     needs no label and takes a single square instead of two words. */
  var tilesToggle = document.getElementById('tilesToggle');
  function anyTileOpen() {
    return Array.prototype.some.call(document.querySelectorAll('.tile'), function (t) {
      return t.getAttribute('open-state') === '1';
    });
  }
  function paintTilesToggle() {
    var open = anyTileOpen();
    tilesToggle.innerHTML = open ? '&#9650;' : '&#9660;';
    tilesToggle.title = open ? 'Close every tile' : 'Open every tile';
  }
  tilesToggle.addEventListener('click', function () {
    var to = anyTileOpen() ? '0' : '1';
    Array.prototype.forEach.call(document.querySelectorAll('.tile'), function (t) { t.setAttribute('open-state', to); });
    paintTilesToggle();
    save();
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-settings]'), function (b) {
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      var panel = document.getElementById('set-' + b.dataset.settings);
      var open = panel.classList.toggle('open');
      b.setAttribute('aria-pressed', open ? 'true' : 'false');
      b.closest('.tile').setAttribute('open-state', '1');
    });
  });

  /* ---------- customise rows (big targets, drag to reorder) ---------- */
  function colourDots(current, onPick) {
    var wrap = document.createElement('span');
    wrap.className = 'dots';
    COLORS.forEach(function (c) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'dot-pick';
      b.style.background = 'var(--c-' + c + ')';
      b.title = c;
      if (c === current) b.setAttribute('aria-pressed', 'true');
      b.addEventListener('click', function (e) { e.stopPropagation(); onPick(c); });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function buildCfgList(box, items, opts) {
    box.innerHTML = '';
    items.forEach(function (item, i) {
      var row = document.createElement('div');
      row.className = 'cfg';
      row.style.setProperty('--rc', 'var(--c-' + item.color + ')');
      row.draggable = true;
      row.dataset.i = i;

      var grip = document.createElement('span');
      grip.className = 'grip'; grip.textContent = '\u2630'; grip.title = 'Drag to reorder';
      row.appendChild(grip);

      var name = document.createElement('input');
      name.type = 'text'; name.className = 'cfg-name'; name.value = item.name;
      name.addEventListener('input', function () { item.name = name.value; opts.softRedraw(); });
      row.appendChild(name);

      row.appendChild(colourDots(item.color, function (c) { item.color = c; opts.redraw(); }));

      if (opts.wip) {
        var wf = document.createElement('label');
        wf.className = 'cfg-field';
        wf.innerHTML = '<span>WIP limit</span>';
        var wi = document.createElement('input');
        wi.type = 'number'; wi.min = '0'; wi.placeholder = 'none';
        wi.value = item.wip == null ? '' : item.wip;
        wi.addEventListener('input', function () {
          item.wip = wi.value === '' ? null : Math.max(0, parseInt(wi.value, 10) || 0);
          opts.softRedraw();
        });
        wf.appendChild(wi);
        row.appendChild(wf);
      }

      if (opts.spawn) {
        var sf = document.createElement('label');
        sf.className = 'cfg-field';
        sf.innerHTML = '<span>Also creates</span>';
        var si = document.createElement('input');
        si.type = 'text'; si.className = 'spawn-in';
        si.style.cssText = 'width:190px;font-size:12px;padding:6px 8px';
        si.placeholder = 'nothing';
        si.title = 'Comma-separated follow-ups created whenever a task enters this stage';
        si.value = (item.spawn || []).join(', ');
        si.addEventListener('input', function () {
          item.spawn = si.value.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
          opts.softRedraw();
        });
        sf.appendChild(si);
        row.appendChild(sf);
      }

      var sw = document.createElement('label');
      sw.className = 'switch';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = opts.flagKey === 'done' ? !!item.done : !!item.excl;
      cb.addEventListener('change', function () {
        if (opts.flagKey === 'done') item.done = cb.checked; else item.excl = cb.checked;
        opts.softRedraw();
      });
      sw.appendChild(cb);
      sw.appendChild(document.createTextNode(opts.flagLabel));
      row.appendChild(sw);

      var mv = document.createElement('span');
      mv.className = 'cfg-move';
      var up = document.createElement('button');
      up.className = 'mv'; up.innerHTML = '&#9650;'; up.title = 'Move up'; up.disabled = i === 0;
      up.addEventListener('click', function (e) {
        e.stopPropagation();
        items.splice(i - 1, 0, items.splice(i, 1)[0]);
        opts.redraw();
      });
      var dn = document.createElement('button');
      dn.className = 'mv'; dn.innerHTML = '&#9660;'; dn.title = 'Move down'; dn.disabled = i === items.length - 1;
      dn.addEventListener('click', function (e) {
        e.stopPropagation();
        items.splice(i + 1, 0, items.splice(i, 1)[0]);
        opts.redraw();
      });
      var del = document.createElement('button');
      del.className = 'mv del'; del.innerHTML = '&#10005;'; del.title = 'Delete';
      del.addEventListener('click', function (e) { e.stopPropagation(); opts.remove(item, i); });
      mv.appendChild(up); mv.appendChild(dn); mv.appendChild(del);
      row.appendChild(mv);

      row.addEventListener('dragstart', function (e) {
        row.classList.add('dragging');
        if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)); }
      });
      row.addEventListener('dragend', function () { row.classList.remove('dragging'); });
      row.addEventListener('dragover', function (e) { e.preventDefault(); row.classList.add('dropinto'); });
      row.addEventListener('dragleave', function () { row.classList.remove('dropinto'); });
      row.addEventListener('drop', function (e) {
        e.preventDefault();
        row.classList.remove('dropinto');
        var from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        if (isNaN(from) || from === i) return;
        items.splice(i, 0, items.splice(from, 1)[0]);
        opts.redraw();
      });

      box.appendChild(row);
    });
  }

  /* ---------- stage scopes: the standard run vs one job's own ---------- */
  /** Remove a stage from whichever run it belongs to; its tasks go to
   *  the row above (the server applies the same rule). */
  function removeStage(list, pid, s, i) {
    if (list.length <= 2) { toast('A board needs at least two stages'); return; }
    var moved = TASKS.filter(function (t) { return t.st === s.id; });
    var target = list[i === 0 ? 1 : i - 1];
    moved.forEach(function (t) { t.st = target.id; });
    list.splice(i, 1);
    logIt('Deleted the "' + s.name + '" stage', 'Settings', 'config', 'red');
    queueStagesSave(pid);
    redrawAll();
    toast('Stage deleted' + (moved.length ? ', ' + plural(moved.length, 'task') + ' moved to ' + target.name : ''));
  }
  function addStageTo(pid) {
    var list = listOfScope(pid) || STAGES;
    list.push({ id: 's' + Date.now(), name: 'New stage', color: COLORS[list.length % COLORS.length], wip: null, done: false, spawn: [] });
    logIt('Added a delivery stage', 'Settings', 'config', 'green');
    queueStagesSave(pid);
    redrawAll();
  }
  /** Give a job its own stage run, starting as a copy of the standard
   *  one. The server carries the job's tasks across by stage name. */
  function startOwnStages(code) {
    var pid = jobIdOf(code);
    if (!pid) { toast('Unknown job'); return; }
    if (jobHasOwn(code)) { toast(code + ' already has its own stages'); return; }
    OVERRIDES[pid] = STAGES.map(function (s, i) {
      return { id: 'o' + Date.now() + '-' + i, name: s.name, color: s.color, wip: s.wip, done: s.done, spawn: (s.spawn || []).slice() };
    });
    logIt('Gave job ' + code + ' its own stages', code, 'config', 'violet');
    cfgScope = code;
    redrawAll();
    pushStages(pid, function () { toast(code + ' now has its own stages', 'changes here leave the other jobs alone'); });
  }
  /** Put a job back on the standard run. Its tasks cross by stage name. */
  function dropOwnStages(code) {
    var pid = jobIdOf(code);
    if (!pid || !OVERRIDES[pid]) return;
    var own = OVERRIDES[pid];
    API.deleteJobStages(pid).then(function (rows) {
      STAGES = rows.map(stageFromServer);
      var byName = {};
      STAGES.forEach(function (s) { byName[s.name] = s.id; });
      var names = {};
      own.forEach(function (s) { names[s.id] = s.name; });
      var moved = 0;
      TASKS.forEach(function (t) {
        if (jobIdOf(t.job) !== pid) return;
        if (names[t.st] === undefined) return;
        t.st = byName[names[t.st]] || STAGES[0].id; moved++;
      });
      delete OVERRIDES[pid];
      if (cfgScope === code) cfgScope = '';
      logIt('Put job ' + code + ' back on the standard stages', code, 'config', 'slate');
      redrawAll();
      toast(code + ' is back on the standard stages', moved ? plural(moved, 'task') + ' followed by name' : null);
    }).catch(fail("Could not remove the job's stages"));
  }
  /** Promote a job's own run to the standard one. Standard stages with
   *  the same name keep their ids (their tasks stay put). */
  function makeStandard(pid) {
    var own = OVERRIDES[pid];
    if (!own) return;
    var byName = {};
    STAGES.forEach(function (s) { byName[s.name] = s.id; });
    STAGES = own.map(function (s, i) {
      return { id: byName[s.name] || 'n' + Date.now() + '-' + i, name: s.name, color: s.color, wip: s.wip, done: s.done, spawn: (s.spawn || []).slice() };
    });
    logIt('Made job ' + codeOfJobId(pid) + '\'s stages the standard', 'Settings', 'config', 'violet');
    redrawAll();
    pushStages('', function () { toast('These are now the standard stages', 'every job without its own set uses them'); });
  }

  var cfgScope = '';   // '' = the standard run, else a job code
  function renderStageCfg() {
    var jf = document.getElementById('jobFilter').value;
    if (cfgScope && cfgScope !== jf) cfgScope = '';
    var scopeOpts = [{ label: 'All jobs', c: '' }];
    if (jf) scopeOpts.push({ label: 'Only ' + jf, c: jf, color: jobTone(jf) });
    chipRow(document.getElementById('stageScope'), scopeOpts,
      function (o) { return cfgScope === o.c; },
      function (o) { cfgScope = o.c; renderStageCfg(); }, true);
    document.getElementById('stageScopeHint').textContent = jf ? '' : 'Filter the tasks to one job to give it its own stages.';

    var box = document.getElementById('stageCfg');
    var note = document.getElementById('stageScopeNote');
    var addBtn = document.getElementById('addStage'), resetBtn = document.getElementById('resetStages');
    var startBtn = document.getElementById('startOwnStages'), removeBtn = document.getElementById('removeOwnStages');
    var pid = cfgScope ? jobIdOf(cfgScope) : '';
    var own = pid ? OVERRIDES[pid] : null;

    note.hidden = !cfgScope;
    resetBtn.hidden = !!cfgScope;
    startBtn.hidden = !(cfgScope && !own);
    removeBtn.hidden = !(cfgScope && own);
    addBtn.hidden = !!(cfgScope && !own);

    if (cfgScope && !own) {
      note.innerHTML = 'Job <b>' + esc(cfgScope) + '</b> uses the standard stages. Start its own set to change the columns for this job only - the other jobs stay as they are.';
      box.innerHTML = '';
      return;
    }
    if (cfgScope) {
      note.innerHTML = 'These stages apply to job <b>' + esc(cfgScope) + '</b> only. The standard run below the filter is untouched.';
    }
    var list = own || STAGES;
    buildCfgList(box, list, {
      wip: true, spawn: true, flagKey: 'done', flagLabel: 'Closes the task',
      redraw: function () { logIt('Changed the delivery stages' + (cfgScope ? ' for ' + cfgScope : ''), 'Settings', 'config', 'slate'); queueStagesSave(pid); redrawAll(); },
      softRedraw: function () { queueStagesSave(pid); redrawAll(true); },
      remove: function (s, i) { removeStage(list, pid, s, i); }
    });
  }
  document.getElementById('startOwnStages').addEventListener('click', function () { if (cfgScope) startOwnStages(cfgScope); });
  document.getElementById('removeOwnStages').addEventListener('click', function () { if (cfgScope) dropOwnStages(cfgScope); });
  function renderActCfg() {
    buildCfgList(document.getElementById('actCfg'), ACTS, {
      wip: false, flagKey: 'excl', flagLabel: 'Exclusive',
      redraw: function () { logIt('Changed the activity list', 'Settings', 'config', 'slate'); queueActsSave(); redrawAll(); },
      softRedraw: function () { queueActsSave(); redrawAll(true); },
      remove: function (a, i) {
        if (ACTS.length <= 2) { toast('Keep at least two activities'); return; }
        TEAM.forEach(function (p) { if (p.acts) p.acts = p.acts.filter(function (x) { return x !== a.id; }); });
        ACTS.splice(i, 1);
        logIt('Deleted the "' + a.name + '" activity', 'Settings', 'config', 'red');
        queueActsSave();
        redrawAll();
      }
    });
  }
  document.getElementById('addStage').addEventListener('click', function () {
    var pid = cfgScope ? jobIdOf(cfgScope) : '';
    addStageTo(pid && OVERRIDES[pid] ? pid : '');
  });
  document.getElementById('addAct').addEventListener('click', function () {
    ACTS.push({ id: 'a' + Date.now(), name: 'New activity', color: COLORS[ACTS.length % COLORS.length], excl: false });
    logIt('Added an activity', 'Settings', 'config', 'green');
    queueActsSave();
    redrawAll();
  });
  document.getElementById('resetStages').addEventListener('click', function () {
    API.resetStagesToDefault().then(function (rows) {
      // The server remapped tasks across by stage NAME - mirror it.
      var prevName = {};
      STAGES.forEach(function (s) { prevName[s.id] = s.name; });
      STAGES = rows.map(stageFromServer);
      var byName = {};
      STAGES.forEach(function (s) { byName[s.name] = s.id; });
      // A job on its own stages was not reset - leave its tasks be.
      TASKS.forEach(function (t) { if (!jobHasOwn(t.job)) t.st = byName[prevName[t.st]] || STAGES[0].id; });
      logIt('Reset the stages to the electrical run', 'Settings', 'config', 'slate');
      redrawAll();
      toast('Stages reset');
    }).catch(fail('Could not reset the stages'));
  });

  /* ---------- my update ---------- */
  function me() {
    for (var i = 0; i < TEAM.length; i++) if (TEAM[i].who === ME_ID) return TEAM[i];
    return TEAM[0];
  }
  function hydrateMine() {
    var m = me();
    if (!m) return;
    document.getElementById('fYest').value = m.y || '';
    document.getElementById('fToday').value = m.t || '';
    document.getElementById('fBlock').value = m.b || '';
    document.getElementById('fBlockBy').value = m.bBy || '';
  }
  function renderStatusChips() {
    var box = document.getElementById('statusChips');
    box.innerHTML = '';
    ACTS.forEach(function (a) {
      var on = me().acts && me().acts.indexOf(a.id) !== -1;
      var b = document.createElement('button');
      b.className = 'chip';
      b.textContent = a.name;
      b.dataset.menu = 'activity'; b.dataset.who = ME_ID; b.dataset.label = a.name;
      if (on) { b.setAttribute('aria-pressed', 'true'); b.setAttribute('style', tint(a.color)); }
      b.addEventListener('click', function () {
        var acts = me().acts ? me().acts.slice() : [];
        var has = acts.indexOf(a.id) !== -1;
        if (has) acts = acts.filter(function (x) { return x !== a.id; });
        else if (a.excl) acts = [a.id];
        else acts = acts.filter(function (x) { var o = act(x); return !(o && o.excl); }).concat([a.id]);
        me().acts = acts;
        logIt('Set where they are: ' + (acts.map(function (x) { return act(x) ? act(x).name : ''; }).join(' + ') || 'nothing'), 'Standup', 'standup', a.color);
        queueEntrySave();
        redrawAll();
      });
      box.appendChild(b);
    });
    var names = (me().acts || []).map(function (x) { return act(x) ? act(x).name : ''; }).filter(Boolean);
    document.getElementById('meMeta').textContent =
      (names.length ? fmtList(names) : 'Not posted yet') + ' \u00b7 ' + plural(me().jobs.length, 'job');
    paintSaveState();
  }

  var clientFilter = '';
  function renderClientChips() {
    var counts = {};
    JOBS.forEach(function (j) { counts[j.client] = (counts[j.client] || 0) + 1; });
    var opts = [{ label: 'All clients', c: '' }].concat(
      Object.keys(counts).sort().map(function (c) {
        return { label: c + '  ' + counts[c], c: c, color: clientTone(c) };
      }));
    chipRow(document.getElementById('clientChips'), opts,
      function (o) { return clientFilter === o.c; },
      function (o) { clientFilter = o.c; renderJobPicker(); renderClientChips(); }, true);
  }

  function renderJobPicker() {
    var body = document.getElementById('jobBody');
    var scroller = body.closest('.tablewrap');
    var keep = scroller ? scroller.scrollTop : 0;
    var q = document.getElementById('jobSearch').value.trim().toLowerCase();
    var onlyMine = document.getElementById('showPicked').getAttribute('aria-pressed') === 'true';
    body.innerHTML = '';
    var rows = JOBS.filter(function (j) {
      if (onlyMine && me().jobs.indexOf(j.code) === -1) return false;
      if (clientFilter && j.client !== clientFilter) return false;
      if (!q) return true;
      return (j.code + ' ' + j.client + ' ' + j.name).toLowerCase().indexOf(q) !== -1;
    });
    rows.forEach(function (j) {
      var on = me().jobs.indexOf(j.code) !== -1;
      var n = TASKS.filter(function (t) { return t.job === j.code && t.who === ME_ID && !stage(t.st).done; }).length;
      var tr = document.createElement('tr');
      if (on) tr.className = 'on';
      tr.dataset.menu = 'job'; tr.dataset.label = j.code;
      var cc = clientTone(j.client);
      var over = TASKS.filter(function (t) { return t.job === j.code && t.who === ME_ID && !stage(t.st).done && t.due && t.due < TODAY; }).length;
      tr.innerHTML =
        '<td class="cbx"><span class="box">' + (on ? '&#10003;' : '') + '</span></td>' +
        '<td class="jn"><span class="code" style="' + tint(cc) + '">' + j.code + '</span></td>' +
        '<td class="cl"><span class="cdotx" style="background:' + cvar(cc) + '"></span>' + esc(j.client) + '</td>' +
        '<td class="wk">' + esc(j.name) + '</td>' +
        '<td class="tk">' + (n
            ? '<span class="n" style="' + (over ? 'background:var(--crit-soft);color:var(--crit)' : tint('slate')) + '">' + n + (over ? '!' : '') + '</span>'
            : '<span style="color:var(--hairline)">&mdash;</span>') +
          '<button class="rowadd" type="button" title="Add a task on ' + esc(j.code) + '">+</button></td>';
      // The fastest way to a task on this job is from the job itself.
      tr.querySelector('.rowadd').addEventListener('click', function (e) {
        e.stopPropagation();
        // Reuse a blank line if there is one, else start a fresh one.
        var blank = -1;
        addRows.forEach(function (r, ix) { if (blank === -1 && !r.job && !r.title.trim()) blank = ix; });
        if (blank === -1) { addRows.push({ job: j.code, title: '', due: '' }); blank = addRows.length - 1; }
        else addRows[blank].job = j.code;
        renderAddRows(blank);
        toast('Adding a task on ' + j.code, j.client + ' - ' + j.name);
      });
      tr.addEventListener('click', function () {
        var i = me().jobs.indexOf(j.code);
        if (i === -1) me().jobs.push(j.code); else me().jobs.splice(i, 1);
        logIt((i === -1 ? 'Added ' : 'Removed ') + j.code + ' on their standup', j.code, 'standup', CLIENT_COLOR[j.client]);
        queueEntrySave();
        redrawAll(true);
      });
      body.appendChild(tr);
    });
    if (!rows.length) body.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:16px">No job matches that.</td></tr>';
    document.getElementById('jobPickMeta').innerHTML = '<b>' + me().jobs.length + '</b> selected of ' + JOBS.length + ' \u00b7 showing ' + rows.length;
    if (scroller) scroller.scrollTop = keep;
  }
  document.getElementById('jobSearch').addEventListener('input', renderJobPicker);
  document.getElementById('showPicked').addEventListener('click', function () {
    this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    renderJobPicker();
  });

  document.getElementById('sameAsYesterday').addEventListener('click', function (e) {
    e.stopPropagation();
    var y = document.getElementById('fYest').value.trim();
    if (!y) { toast('Nothing in yesterday to copy'); return; }
    document.getElementById('fToday').value = y;
    me().t = y;
    logIt('Copied yesterday into today', 'Standup', 'standup', 'blue');
    queueEntrySave();
    redrawAll(true);
    toast('Yesterday copied into today');
  });

  /* Typing must not rebuild the whole page - a full redraw per keystroke
     made the job table visibly "refresh" under the cursor. Only the
     surfaces that actually show this text (my team card, the blockers
     tile) repaint, and only once the typing pauses. */
  var typingRedrawTimer = null;
  function queueTypingRedraw() {
    clearTimeout(typingRedrawTimer);
    typingRedrawTimer = setTimeout(function () {
      typingRedrawTimer = null;
      renderTeam();
      renderBlockers();
    }, 700);
  }
  ['fYest','fToday','fBlock'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', function () {
      var k = id === 'fYest' ? 'y' : id === 'fToday' ? 't' : 'b';
      me()[k] = this.value;
      queueEntrySave();
      queueTypingRedraw();
    });
  });
  document.getElementById('fBlockBy').addEventListener('change', function () {
    me().bBy = this.value;
    logIt('Set the blocker need-by date to ' + fmt(this.value), 'Standup', 'standup', 'amber');
    queueEntrySave();
    redrawAll(true);
  });

  document.getElementById('saveBtn').addEventListener('click', function () {
    logIt('Saved their standup', 'Standup', 'standup', 'blue');
    pushEntry(function () {
      redrawAll();
      toast('Update saved');
    });
  });

  /* ---------- multi-row task composer ----------
     One line per task, so a site walk that produces six jobs is six lines
     and one Add, not six round trips. Duplicating a line keeps its job and
     date, which is the usual case. */
  var addRows = [{ job: '', title: '', due: '' }];

  /* A toast is gone in seconds and the new tasks land two tiles further
     down - which read as "my tasks just disappeared". The receipt is the
     durable answer: a green block right where the lines were, naming
     what was added, clickable through to each task, with its own Undo.
     It stays until dismissed. */
  var addedReceipts = [];
  function renderReceipts() {
    var box = document.getElementById('addedReceipts');
    if (!box) return;
    box.innerHTML = '';
    addedReceipts.slice(-3).forEach(function (r) {
      var el = document.createElement('div');
      el.className = 'receipt' + (r.undone ? ' gone' : '');
      var head = document.createElement('div');
      head.className = 'rline';
      head.innerHTML = r.undone
        ? '<b>Removed again</b>'
        : '<b>✓ ' + r.tasks.length + ' task' + (r.tasks.length === 1 ? '' : 's') +
          ' added to the board</b><span class="rtm">at ' + hhmm(r.at) + '</span>';
      var tools = document.createElement('span');
      tools.className = 'rtools';
      if (!r.undone) {
        var undo = document.createElement('button');
        undo.type = 'button'; undo.className = 'rundo'; undo.textContent = 'Undo';
        undo.addEventListener('click', function () {
          r.tasks.forEach(function (t) {
            API.deleteBoardTask(t.id).catch(function () {});
            var i = TASKS.indexOf(t);
            if (i > -1) TASKS.splice(i, 1);
          });
          r.undone = true;
          logIt('Removed the ' + plural(r.tasks.length, 'task') + ' just added', r.tasks[0].job, 'task', 'red');
          redrawAll();
          renderReceipts();
        });
        tools.appendChild(undo);
      }
      var x = document.createElement('button');
      x.type = 'button'; x.className = 'rx'; x.innerHTML = '&#10005;'; x.title = 'Dismiss';
      x.addEventListener('click', function () {
        var i = addedReceipts.indexOf(r);
        if (i > -1) addedReceipts.splice(i, 1);
        renderReceipts();
      });
      tools.appendChild(x);
      head.appendChild(tools);
      el.appendChild(head);
      if (!r.undone) {
        r.tasks.forEach(function (t) {
          var line = document.createElement('button');
          line.type = 'button'; line.className = 'ritem';
          line.innerHTML = esc(t.t) +
            '<span class="rmeta">' + esc(t.job) + (t.due ? ' · due ' + fmt(t.due) : '') + '</span>';
          line.title = 'Open the task';
          line.addEventListener('click', function () {
            var live = taskById(t.id);
            if (live) openEdit(live); else toast('That task is gone');
          });
          el.appendChild(line);
        });
      }
      box.appendChild(el);
    });
  }

  /* The save line by the button answers two questions the page used to
     leave hanging: "did that save?" and "what do I actually have to fill
     in?" (Nothing is mandatory - but you only count as POSTED once at
     least one "Where I am today" chip is picked.) */
  // NO initializer on lastSavedAt: buildFromBoard (which runs above this
  // line at boot) already hydrated it from today's entry, and `var x =
  // null` mid-file would silently wipe that value when execution reaches
  // it - the hoisting trap that made the save line forget its timestamp.
  var lastSavedAt;
  var saveFlash = '';
  function paintSaveState() {
    var el = document.getElementById('saveHint');
    if (!el) return;
    var m = me();
    if (saveFlash === 'pending') {
      el.className = 'hint savestate';
      el.textContent = 'Saving...';
      return;
    }
    if (saveFlash === 'error') {
      el.className = 'hint savestate err';
      el.textContent = 'Could not save - check the connection and try again';
      return;
    }
    if (!m || !m.acts || !m.acts.length) {
      el.className = 'hint savestate warn';
      el.textContent = "Pick at least one 'Where I am today' chip - until then the team sees you as not posted. Everything else is optional.";
      return;
    }
    if (lastSavedAt) {
      el.className = 'hint savestate ok';
      el.textContent = '✓ Saved ' + hhmm(lastSavedAt) + ' - keeps saving automatically as you type';
    } else {
      el.className = 'hint savestate';
      el.textContent = 'Saves automatically as you type';
    }
  }

  /** Work out how far the text has to slide to reveal its tail. */
  function fitMarquee(root) {
    Array.prototype.forEach.call(root.querySelectorAll('.marquee'), function (box) {
      var inner = box.querySelector('.mq');
      if (!inner) return;
      var over = inner.scrollWidth - box.clientWidth;
      box.style.setProperty('--shift', (over > 2 ? over + 6 : 0) + 'px');
    });
  }

  function renderAddRows(focusIdx) {
    var box = document.getElementById('addRows');
    box.innerHTML = '';
    addRows.forEach(function (r, i) {
      var j = job(r.job);
      var el = document.createElement('div');
      // No "ready/green" state on the row itself: green used to appear the
      // moment a line was merely valid, which read as "submitted" before it
      // was. Submission is now the explicit per-row Add button below.
      el.className = 'addrow';
      // Right-click on the line for its own edits (clear, duplicate, remove).
      el.dataset.menu = 'addrow'; el.dataset.i = i; el.dataset.label = 'Task line ' + (i + 1);

      var jb = document.createElement('button');
      jb.type = 'button';
      jb.className = 'jobbtn' + (j ? '' : ' empty');
      jb.innerHTML = j
        ? '<span class="code" style="color:' + cvar(clientTone(j.client)) + '">' + j.code + '</span>' +
          '<span class="cl marquee"><span class="mq">' + esc(j.client + ' - ' + j.name) + '</span></span>'
        : '<span class="cl">Pick a job...</span>';
      if (j) { jb.title = j.code + '  ' + j.client + ' - ' + j.name; setTimeout(function () { fitMarquee(jb); }, 0); }
      jb.addEventListener('click', function (e) {
        e.preventDefault();
        var rect = jb.getBoundingClientRect();
        renderMenu('Job for this line', jobOptions(true).map(function (o) {
          return { label: o.label, note: o.note, color: o.color, run: function () {
            r.job = o.value; renderAddRows(i);
          } };
        }), rect.left, rect.bottom + 4, { search: 'Search jobs...' });
      });
      el.appendChild(jb);

      // The per-line Add button, created up front so the description's input
      // handler can enable/disable it live as you type.
      var addb = document.createElement('button');
      addb.type = 'button'; addb.className = 'rowadd'; addb.textContent = 'Add task';
      addb.title = 'Add this task to the board';
      function refreshReady() { addb.disabled = !(job(r.job) && (r.title || '').trim()); }

      var ti = document.createElement('input');
      ti.type = 'text'; ti.className = 't'; ti.placeholder = 'What needs doing...'; ti.value = r.title;
      ti.addEventListener('input', function () {
        r.title = ti.value;
        // Follow the cursor so a long description keeps scrolling into view
        // instead of typing off the right edge of the field.
        if (ti.selectionStart === ti.value.length) ti.scrollLeft = ti.scrollWidth;
        refreshReady();
        paintAddHint();
      });
      ti.addEventListener('keydown', function (e) {
        // Enter submits this line when it is ready — the fast path.
        if (e.key === 'Enter') { e.preventDefault(); if (job(r.job) && ti.value.trim()) submitRow(i); }
      });
      el.appendChild(ti);

      var di = document.createElement('input');
      di.type = 'date'; di.className = 'd'; di.value = r.due || '';
      di.addEventListener('change', function () { r.due = di.value; });
      el.appendChild(di);

      // Public until you say otherwise: the lock flips this one line.
      var lk = document.createElement('button');
      var priv = r.vis === 'private';
      lk.type = 'button'; lk.className = 'rowbtn lock' + (priv ? ' on' : '');
      lk.innerHTML = priv ? '&#128274;' : '&#128275;';
      lk.setAttribute('aria-pressed', priv ? 'true' : 'false');
      lk.title = priv ? 'Private - only you and the assignee see it' : 'Public - the whole team sees it. Click to make it private';
      lk.addEventListener('click', function () { r.vis = priv ? 'public' : 'private'; renderAddRows(i); });
      el.appendChild(lk);

      addb.addEventListener('click', function () { submitRow(i); });
      refreshReady();
      el.appendChild(addb);

      var rm = document.createElement('button');
      rm.type = 'button'; rm.className = 'rowbtn rm'; rm.innerHTML = '&#10005;';
      rm.title = 'Remove this line';
      rm.disabled = addRows.length === 1 && !r.job && !r.title;
      rm.addEventListener('click', function () {
        addRows.splice(i, 1);
        if (!addRows.length) addRows.push({ job: '', title: '', due: '' });
        renderAddRows(Math.max(0, i - 1));
      });
      el.appendChild(rm);

      box.appendChild(el);
    });
    paintAddHint();
    if (focusIdx != null) {
      var inputs = box.querySelectorAll('input.t');
      if (inputs[focusIdx]) inputs[focusIdx].focus();
    }
  }
  function addAnother(afterIdx) {
    var src = addRows[afterIdx] || {};
    addRows.splice(afterIdx + 1, 0, { job: src.job || '', title: '', due: src.due || '', vis: src.vis || 'public' });
    renderAddRows(afterIdx + 1);
  }
  function paintAddHint() {
    // Only a gentle nudge about lines that have words but no job - each
    // line is added on its own, so there is no batch "N ready" count. A
    // line with a job and nothing typed yet is the normal state right
    // after an add (the job is kept for the next task), not a problem.
    var noJob = addRows.filter(function (r) { return r.title.trim() && !job(r.job); }).length;
    document.getElementById('addHint').textContent = noJob
      ? plural(noJob, 'line') + ' still need' + (noJob === 1 ? 's' : '') + ' a job - pick one on the left'
      : '';
  }
  // Submit ONE line - the per-row Add button (and Enter) route here. Green
  // (the receipt + toast) appears only after the server actually creates it,
  // so "it went green" now genuinely means "it was added".
  function submitRow(i) {
    var r = addRows[i];
    if (!(job(r.job) && (r.title || '').trim())) { toast('Pick a job and say what needs doing first'); return; }
    var vis = r.vis === 'private' ? 'private' : 'public';
    API.createBoardTasks([{ title: r.title.trim(), project_id: jobIdOf(r.job), due: r.due || '', assignee_id: ME_ID, visibility: vis }]).then(function (rows) {
      var made = rows.map(taskFromServer);
      made.forEach(function (t) { TASKS.push(t); });
      logIt('Created 1 task' + (vis === 'private' ? ' (private)' : ''), made[0].job, 'task', 'green');
      // The undo lives on the receipt (durable), not the toast (gone in
      // seconds) - two undo paths would double-delete.
      addedReceipts.push({ at: stamp(), tasks: made, undone: false });
      // Keep the job (and the lock) so the next task on it is one field
      // away; clear the rest.
      addRows[i] = { job: r.job, title: '', due: '', vis: vis };
      renderAddRows(i);
      renderReceipts();
      redrawAll();
      toast(vis === 'private' ? 'Private task added - only you and the assignee see it' : 'Task added - receipt below the composer');
    }).catch(fail('Could not add the task'));
  }
  document.getElementById('addLine').addEventListener('click', function () { addAnother(addRows.length - 1); });
  document.getElementById('addClear').addEventListener('click', function () {
    addRows = [{ job: '', title: '', due: '', vis: 'public' }];
    renderAddRows(0);
  });

  // Right-click anywhere on the board for a fast jump to the ERP screens the
  // standup feeds into - the registers (RFI / RFQ / orders), the RFI screen
  // and the procurement modules - so a task on a job is one click from
  // raising the paperwork it needs. Text fields keep their native menu so
  // copy/paste still works there.
  docListen(opts.root, 'contextmenu', function (e) {
    var tag = (e.target && e.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)) return;
    // Anything with its own menu is handled by the document listener
    // below - painting "Go to" first only to overwrite it made the menu
    // flash and land at the wrong size.
    if (e.target.closest('[data-menu]')) return;
    e.preventDefault();
    renderMenu('Go to', [
      { label: 'Registers — RFI / RFQ / Orders', note: 'raise & track correspondence', run: function () { opts.navigate('/comms-intelligence'); } },
      { label: 'Work requests', note: 'engineering, drafting, workshop, automation, HA', run: function () { opts.navigate('/work-requests'); } },
      { label: 'RFIs', run: function () { opts.navigate('/rfi'); } },
      { label: 'Procurement', run: function () { opts.navigate('/procurement'); } },
      { label: 'Bid management', run: function () { opts.navigate('/bid-management'); } },
      { label: 'Supplier catalogues', run: function () { opts.navigate('/supplier-catalogs'); } }
    ], e.clientX, e.clientY);
  });

  /* ---------- team ---------- */
  // Comments and the full task list are open by default; `cardOpen` holds
  // any per-person override the reader has made since.
  var allCardsOpen = saved.allCardsOpen !== undefined ? saved.allCardsOpen : true;
  var cardOpen = {};
  //: taskId -> timeout for the two-stage tickbox grace period.
  var pendingTicks = {};

  /* Comments cycle through three states rather than just on/off, because
     "what did the team say about this person's day" and "what did they say
     about each of their tasks" are different questions:
       0  nothing            arrow down
       1  the card's own     arrow up
       2  plus every task's  two arrows up
     The glyph says which state you are in, not what the click will do. */
  var cmtState = {};
  var CMT_ARROW = ['\u25bc', '\u25b2', '\u23eb'];

  /* The same three-step reveal for a whole card:
       0  just the header      arrow down
       1  the update as usual  arrow up
       2  everything open      two arrows up                       */
  /* One tooltip showing the whole cycle with a marker on where you are,
     so the third click is never a surprise. */
  var CYCLE_STEPS = {
    card: ['Header only', 'The update', 'Everything, comments and all'],
    cmt: ['Comments hidden', "This update's comments", "Plus every task's comments"]
  };
  function cycleTip(kind, now) {
    var steps = CYCLE_STEPS[kind];
    return 'Click to cycle:\n' + steps.map(function (label, i) {
      return (i === now ? '\u25b8 ' : '   ') + CMT_ARROW[i] + '  ' + label + (i === now ? '   (now)' : '');
    }).join('\n');
  }

  var cardState = {};
  function cardStateOf(who) {
    return cardState[who] !== undefined ? cardState[who] : (allCardsOpen ? 1 : 1);
  }
  function cmtOf(who) {
    return cmtState[who] !== undefined ? cmtState[who] : (allCardsOpen ? 1 : 0);
  }
  function taskCommentCount(who) {
    return TASKS.reduce(function (n, t) {
      return n + ((t.who === who && !stage(t.st).done && t.comments) ? t.comments.length : 0);
    }, 0);
  }

  function actPills(ids) {
    if (!ids || !ids.length) return '<span class="pill pill-none">No update yet</span>';
    return ids.map(function (id) {
      var a = act(id);
      return a ? '<span class="pill" style="' + tint(a.color) + '">' + esc(a.name) + '</span>' : '';
    }).join('');
  }
  function renderTeam() {
    var box = document.getElementById('teamBoard');
    box.innerHTML = '';
    var posted = 0;
    var roster = teamOn(viewDay);
    roster.forEach(function (p) {
      var has = p.acts && p.acts.length;
      if (has) posted++;
      var person = PEOPLE[p.who];
      // Needed by the header, which is built first.
      var cst = cardStateOf(p.who);
      var open = TASKS.filter(function (t) { return t.who === p.who && !stage(t.st).done; });
      var card = document.createElement('div');
      card.className = 'member' + (p.me ? ' is-me' : '') + (has ? '' : ' not-posted');
      card.style.setProperty('--pc', person.color);
      card.dataset.menu = 'card'; card.dataset.who = p.who; card.dataset.label = person.name;

      var timeChip = has
        ? '<span class="posted' + (p.posted > '08:00' ? ' late' : '') + '" title="Posted at ' + p.posted + (p.edited ? ', edited ' + p.edited : '') + '">' +
          hhmm(p.posted) + (p.edited ? ' \u00b7 ed ' + hhmm(p.edited) : '') + '</span>'
        : '<span class="posted none">not posted</span>';

      var html = '<div class="member-head"><span data-menu="person" data-who="' + p.who + '" data-label="' + person.name + '">' + avatar(p.who, true) + '</span>' +
        '<span class="who">' + person.name + '</span>' + (p.me ? '<span class="me-tag">me</span>' : '') +
        (p.mentions ? '<span class="mentionpip" title="Mentioned in a comment">@' + p.mentions + '</span>' : '') +
        timeChip + '<span class="pills" data-menu="activity" data-who="' + p.who + '" data-label="Where they are">' + actPills(p.acts) + '</span>' +
        '<button class="cardarrow" data-who="' + p.who + '" title="' + esc(cycleTip('card', cst)) + '">' +
          CMT_ARROW[cst] + '</button></div>';

      if (cst === 0) {
        // Header only - who they are, when they posted, where they are.
        card.innerHTML = html;
        box.appendChild(card);
        return;
      }

      if (p.jobs && p.jobs.length) {
        var shown = p.jobs.slice(0, 3), extra = p.jobs.length - shown.length;
        html += '<div class="jobline">' + shown.map(function (c) {
          var j = job(c), col = j ? clientTone(j.client) : 'slate';
          // The chip carries the actual job, not just a number nobody
          // can hold in their head: client family plus the work.
          var label = j ? (j.client ? j.client + ' - ' + j.name : j.name) : c;
          return '<a class="jobchip" data-menu="job" data-label="' + c + '" style="' + tint(col) + '" title="' + esc(c + '  ' + label) + '">' +
                 '<span class="code">' + c + '</span> ' + esc(label) + '</a>';
        }).join('') + (extra ? '<span class="jobchip" style="background:var(--surface-3);color:var(--muted)">+' + extra + '</span>' : '') + '</div>';
      }

      if (has) {
        if (p.y) html += '<div class="seg"><span class="lbl">Yesterday</span><p>' + esc(p.y) + '</p></div>';
        if (p.t) html += '<div class="seg"><span class="lbl">Today</span><p>' + esc(p.t) + '</p></div>';
        if (p.b) {
          var over = p.bBy && p.bBy < TODAY;
          html += '<div class="seg blocked"><span class="lbl">Blocker' +
            (p.bBy ? '<span class="needby' + (over ? ' over' : '') + '">need by ' + fmt(p.bBy) + '</span>' : '') +
            '</span><p>' + esc(p.b) + '</p></div>';
        }
      } else if (p.last) {
        html += '<p class="stale">Last update <span class="when">' + p.last.day + ' ' + hhmm(p.last.at) + '</span> &mdash; <b>' + esc(p.last.text) + '</b></p>';
      } else {
        html += '<p class="stale">No updates yet.</p>';
      }

      // Nothing on a card is a dead end: the hidden tasks and the comments
      // both open from here, and the tile header can do the whole team.
      var openCard = cst === 2 || (cardOpen[p.who] !== undefined ? cardOpen[p.who] : allCardsOpen);
      var shownTasks = openCard ? open : open.slice(0, 4);

      if (open.length) {
        html += '<div class="mtasks"><span class="lbl">Open tasks <span class="pipcount" style="' + tint('slate') + '">' + open.length + '</span></span>' +
          shownTasks.map(function (t) {
            var dc = dueClass(t.due, false);
            var openThread = (cst === 2 || cmtOf(p.who) === 2) && t.comments && t.comments.length;
            var ticked = !!pendingTicks[t.id];
            return '<div class="mtask' + (openThread ? ' has-thread' : '') + '" data-menu="task" data-id="' + t.id + '" data-label="' + esc(t.t) + '">' +
              '<button class="tickbox' + (ticked ? ' ticked' : '') + '"' +
                (p.me
                  ? ' title="' + (ticked ? 'Closing - click again to keep it open' : 'Tick it off') + '"'
                  : ' disabled title="Only the owner ticks their own"') +
                '>' + (ticked ? '&#10003;' : '') + '</button>' +
              '<div><span class="title">' + esc(t.t) + '</span>' + lockGlyph(t) +
              (t.rep ? '<span class="rep">&#8635;</span>' : '') +
              (t.due ? ' <span class="due' + dc + '">' + fmt(t.due) + (dc === ' over' ? ' overdue' : '') + '</span>' : '') +
              (t.wait ? ' <span class="kwait">waiting: ' + esc(t.wait) + '</span>' : '') +
              ((t.comments && t.comments.length) ? ' <span class="cmt">&#128172;' + t.comments.length + '</span>' : '') +
              // State 2 opens each task's own thread underneath it.
              (((cst === 2 || cmtOf(p.who) === 2) && t.comments && t.comments.length)
                ? '<div class="tthread">' + t.comments.map(function (c) {
                    return '<div class="tline"><b>' + esc(c.who) + '</b><span class="tm">' + when(c) + '</span> ' + renderMentions(c.body) + '</div>';
                  }).join('') + '</div>'
                : '') +
              '</div></div>';
          }).join('') +
          (open.length > shownTasks.length
            ? '<button class="moretasks" data-who="' + p.who + '">and ' + (open.length - shownTasks.length) + ' more &#9660;</button>'
            : (openCard && open.length > 4 ? '<button class="moretasks" data-who="' + p.who + '">show fewer &#9650;</button>' : '')) +
          '</div>';
      }

      if (has) {
        var cs = cst === 2 ? 2 : cmtOf(p.who);
        var vis = cs >= 1 ? '' : 'display:none';
        var tcn = taskCommentCount(p.who);
        var label = p.comments.length
          ? p.comments.length + ' comment' + (p.comments.length === 1 ? '' : 's')
          : 'Comment';
        if (cs === 2 && tcn) label += ' + ' + tcn + ' on tasks';
        else if (cs < 2 && tcn) label += ' &middot; ' + tcn + ' on tasks';
        html += '<div class="comments" data-state="' + cs + '"><button class="comments-toggle" title="' + esc(cycleTip('cmt', cs)) + '">' +
          label + ' <span class="cmtarrow">' + CMT_ARROW[cs] + '</span></button>' +
          p.comments.map(function (c, ci) {
            return '<div class="comment" data-menu="comment" data-who="' + p.who + '" data-ci="' + ci + '" data-label="comment" style="' + vis + '">' +
              '<b>' + esc(c.who) + '</b><span class="tm">' + when(c) + '</span> ' + renderMentions(c.body) + '</div>';
          }).join('') +
          '<form class="reply-row" data-reply style="' + vis + '">' +
          '<input type="text" placeholder="Reply... type @ to mention"><button class="send" type="submit">&rarr;</button></form></div>';
      }

      card.innerHTML = html;
      box.appendChild(card);
    });
    document.getElementById('teamMeta').innerHTML = posted + ' of ' + roster.length +
      (viewDay === TODAY ? ' posted today' : ' posted on ' + isoToLabel(viewDay));
    var tt = document.getElementById('teamToggle');
    tt.innerHTML = allCardsOpen ? '&#9650;' : '&#9660;';
    tt.title = allCardsOpen ? 'Collapse every card' : 'Expand every card';

    var nudge = document.getElementById('nudge');
    nudge.innerHTML = (viewDay === TODAY && posted < roster.length)
      ? '<div class="banner"><b>' + (roster.length - posted) + '</b> still to post today: ' +
        fmtList(roster.filter(function (p) { return !(p.acts && p.acts.length); }).map(function (p) { return PEOPLE[p.who].name; })) +
        '<span class="spacer"></span><button class="icon-btn" id="nudgeBtn">Nudge them</button></div>'
      : (viewDay !== TODAY
          ? '<div class="banner"><b>Looking back at ' + isoToLabel(viewDay) + '.</b> Past days are read-only.' +
            '<span class="spacer"></span><button class="icon-btn" id="backToday">Back to today</button></div>'
          : '');
    var bt = document.getElementById('backToday');
    if (bt) bt.addEventListener('click', function () { setDay(TODAY); });
    var nb = document.getElementById('nudgeBtn');
    if (nb) nb.addEventListener('click', function () {
      nb.disabled = true;
      API.sendNudge().then(function (r) {
        logIt('Nudged ' + fmtList(r.nudged) + ' to post', 'Standup', 'standup', 'blue');
        renderLog();
        toast('Nudged ' + fmtList(r.nudged), 'they have a notification in the ERP');
      }).catch(function (err) {
        nb.disabled = false;
        fail('Could not send the nudge')(err);
      });
    });
    wireTeam();
  }
  function wireTeam() {
    Array.prototype.forEach.call(document.querySelectorAll('.comments-toggle'), function (b) {
      b.addEventListener('click', function () {
        var who = b.closest('.member').dataset.who;
        cmtState[who] = (cmtOf(who) + 1) % 3;   // none -> card -> card + tasks
        renderTeam();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.cardarrow'), function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var who = b.dataset.who;
        cardState[who] = (cardStateOf(who) + 1) % 3;   // header -> update -> everything
        renderTeam();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.moretasks'), function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var who = b.dataset.who;
        cardOpen[who] = !(cardOpen[who] !== undefined ? cardOpen[who] : allCardsOpen);
        renderTeam();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-reply]'), function (f) {
      var input = f.querySelector('input');
      // Typing @ offers the team; picking one inserts the name.
      input.addEventListener('keyup', function (e) {
        if (e.key !== '@') return;
        var r = input.getBoundingClientRect();
        popover(r.left, r.bottom + 4, 'Mention', Object.keys(PEOPLE).map(function (k) {
          return { label: PEOPLE[k].name, run: function () {
            input.value = input.value.replace(/@$/, '') + '@' + PEOPLE[k].name + ' ';
            input.focus();
          } };
        }));
      });
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!input.value.trim()) return;
        var card = f.closest('.member');
        var p = TEAM.filter(function (x) { return x.who === card.dataset.who; })[0];
        var body = input.value.trim();
        if (!p || !p.entryId) { toast('Nothing posted yet to comment on'); return; }
        API.postComment(p.entryId, body).then(function (row) {
          p.comments.push(commentFromServer(row));
          var hits = mentionedIn(body);
          hits.forEach(function (k) {
            var target = TEAM.filter(function (x) { return x.who === k; })[0];
            if (target) target.mentions = (target.mentions || 0) + 1;
          });
          logIt('Commented on ' + PEOPLE[p.who].name + "'s update" +
            (hits.length ? ', mentioning ' + hits.map(function (k) { return PEOPLE[k].name; }).join(' and ') : ''),
            'Standup', 'standup', hits.length ? 'blue' : 'violet');
          redrawAll();
          toast(hits.length ? 'Posted - ' + fmtList(hits.map(function (k) { return PEOPLE[k].name; })) + ' notified' : 'Comment posted');
        }).catch(fail('Could not post the comment'));
        input.value = '';
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.tickbox'), function (b) {
      b.addEventListener('click', function () {
        if (b.disabled) return;
        var t = taskById(b.closest('[data-id]').dataset.id);
        if (!t) return;
        // Two-stage tick: the first click turns the circle green and
        // waits a beat; a second click cancels. A mis-click never makes
        // a task vanish on the spot.
        if (pendingTicks[t.id]) {
          clearTimeout(pendingTicks[t.id]);
          delete pendingTicks[t.id];
          renderTeam();
          toast('Kept open');
          return;
        }
        pendingTicks[t.id] = setTimeout(function () {
          delete pendingTicks[t.id];
          markDone(t);
        }, 2500);
        renderTeam();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.jobchip'), function (a) {
      a.addEventListener('click', function () {
        var jid = jobIdOf(a.dataset.label);
        if (jid) opts.navigate('/projects/' + jid);
      });
    });
    // Clicking a task on someone's card opens it for editing, same as the
    // list; the comment pip jumps straight to the thread.
    Array.prototype.forEach.call(document.querySelectorAll('.mtask'), function (row) {
      var t = taskById(row.dataset.id);
      if (!t) return;
      var title = row.querySelector('.title');
      if (title) title.addEventListener('click', function () { openEdit(t); });
      var pip = row.querySelector('.cmt');
      if (pip) pip.addEventListener('click', function (e) {
        e.stopPropagation();
        openEdit(t);
        setTimeout(function () {
          document.getElementById('mCommentsWrap').scrollIntoView({ block: 'center' });
          document.getElementById('mCommentBox').focus();
        }, 60);
      });
    });
  }

  /* ---------- info dialog (digest, photo viewer) ---------- */
  var infoScrim = document.getElementById('infoScrim');
  var infoAt = 0;
  function openInfo(title, html, action, actionLabel) {
    document.getElementById('infoTitle').textContent = title;
    document.getElementById('infoBody').innerHTML = html;
    var btn = document.getElementById('infoAction');
    btn.textContent = actionLabel || 'OK';
    btn.style.display = action ? '' : 'none';
    btn.onclick = function () { if (action) action(); };
    infoAt = Date.now();
    infoScrim.classList.add('open');
  }
  function closeInfo() { infoScrim.classList.remove('open'); }
  document.getElementById('infoClose').addEventListener('click', closeInfo);
  document.getElementById('infoCancel').addEventListener('click', closeInfo);
  infoScrim.addEventListener('click', function (e) {
    if (e.target === infoScrim && Date.now() - infoAt > 400) closeInfo();
  });
  function openViewer(ph) {
    openInfo(ph.name, '<img src="' + ph.url + '" alt="' + esc(ph.name) + '" style="width:100%;border-radius:9px">', null);
  }

  /* ---------- capacity ---------- */
  function renderCapacity() {
    var wrap = document.getElementById('capWrap');
    wrap.innerHTML = '';
    var rows = Object.keys(PEOPLE).map(function (k) {
      var open = TASKS.filter(function (t) { return t.who === k && !stage(t.st).done; });
      return {
        k: k,
        over: open.filter(function (t) { return t.due && t.due < TODAY; }).length,
        wait: open.filter(function (t) { return t.wait && !(t.due && t.due < TODAY); }).length,
        run: open.filter(function (t) { return !t.wait && !(t.due && t.due < TODAY); }).length,
        total: open.length
      };
    });
    var max = Math.max.apply(null, rows.map(function (r) { return r.total; }).concat([1]));
    rows.sort(function (a, b) { return b.total - a.total; });
    rows.forEach(function (r) {
      var el = document.createElement('div');
      el.className = 'cap';
      el.style.setProperty('--pc', PEOPLE[r.k].color);
      el.dataset.menu = 'person'; el.dataset.who = r.k; el.dataset.label = PEOPLE[r.k].name;
      var w = function (n) { return fmtFixed(n / max * 100, 1) + '%'; };
      el.innerHTML =
        '<span class="nm">' + avatar(r.k, true) + PEOPLE[r.k].name + '</span>' +
        '<span class="capbar">' +
          (r.over ? '<span style="width:' + w(r.over) + ';background:var(--crit)">' + r.over + '</span>' : '') +
          (r.wait ? '<span style="width:' + w(r.wait) + ';background:var(--c-amber)">' + r.wait + '</span>' : '') +
          (r.run ? '<span style="width:' + w(r.run) + ';background:var(--c-teal)">' + r.run + '</span>' : '') +
          (!r.total ? '<span style="width:100%;color:var(--muted)">clear</span>' : '') +
        '</span>' +
        '<span class="capnums">' +
          (r.over ? '<span style="background:var(--crit-soft);color:var(--crit)">' + r.over + ' overdue</span>' : '') +
          (r.wait ? '<span style="' + tint('amber') + '">' + r.wait + ' waiting</span>' : '') +
          '<span style="' + tint('slate') + '">' + r.total + ' open</span>' +
        '</span>';
      el.addEventListener('click', function () {
        document.getElementById('tile-tasks').setAttribute('open-state', '1');
        setPeople([r.k]);
        toast('Tasks filtered to ' + PEOPLE[r.k].name);
      });
      wrap.appendChild(el);
    });
  }

  /* ---------- weekly digest ---------- */
  function buildDigest() {
    var moved = LOG.filter(function (l) { return l.kind === 'task' && l.what.indexOf('Moved') === 0; });
    var waiting = TASKS.filter(function (t) { return t.wait && !stage(t.st).done; });
    var slipped = TASKS.filter(function (t) { return t.due && t.due < TODAY && !stage(t.st).done; });
    var closed = TASKS.filter(function (t) { return stage(t.st).done; });
    var byPerson = Object.keys(PEOPLE).map(function (k) {
      var open = TASKS.filter(function (t) { return t.who === k && !stage(t.st).done; });
      return PEOPLE[k].name + ' - ' + open.length + ' open, ' +
        open.filter(function (t) { return t.due && t.due < TODAY; }).length + ' overdue';
    });
    function ul(arr, empty) {
      if (!arr.length) return '<p class="none">' + empty + '</p>';
      return '<ul>' + arr.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ul>';
    }
    return '<div class="digest">' +
      '<h5>Closed out this week</h5>' + ul(closed.map(function (t) { return esc(t.t) + ' <b>' + t.job + '</b>'; }), 'Nothing closed out yet.') +
      '<h5>Still waiting on someone</h5>' + ul(waiting.map(function (t) { return esc(t.wait) + ' &mdash; ' + esc(t.t) + ' <b>' + t.job + '</b>'; }), 'Nothing waiting. Rare.') +
      '<h5>Slipped past its date</h5>' + ul(slipped.map(function (t) { return esc(t.t) + ' <b>' + t.job + '</b>, due ' + fmt(t.due); }), 'Nothing overdue.') +
      '<h5>Where everyone is at</h5>' + ul(byPerson, '') +
      '<h5>Movement</h5><p>' + moved.length + ' stage change' + (moved.length === 1 ? '' : 's') + ' recorded today.</p>' +
      '</div>';
  }

  /* ---------- attachments on a standup ----------
     Anything, not just photos: an image gets a thumbnail, everything else
     gets its type on a coloured tile. */
  function renderPhotos() {
    var box = document.getElementById('myPhotos');
    box.innerHTML = '';
    (me().photos || []).forEach(function (ph, i) {
      var k = fileKind(ph.name, ph.type);
      var el;
      if (k.k === 'img' && ph.url) {
        el = document.createElement('img');
        el.className = 'photo'; el.src = ph.url; el.alt = ph.name;
      } else {
        el = document.createElement('span');
        el.className = 'photo filetile';
        el.style.background = 'var(--w-' + k.c + ')';
        el.style.color = 'var(--c-' + k.c + ')';
        el.innerHTML = '<b>' + k.tag + '</b><span>' + esc(ph.name.length > 12 ? ph.name.slice(0, 11) + '\u2026' : ph.name) + '</span>';
      }
      el.title = ph.name + (ph.size ? '  (' + human(ph.size) + ')' : '');
      el.dataset.menu = 'photo'; el.dataset.i = i; el.dataset.label = ph.name;
      el.addEventListener('click', function () {
        if (k.k === 'img' && ph.url) openViewer(ph);
        else toast('Opens ' + ph.name, k.tag + (ph.size ? ' - ' + human(ph.size) : ''));
      });
      box.appendChild(el);
    });
    var add = document.createElement('button');
    add.className = 'photo-add'; add.type = 'button'; add.textContent = '+';
    add.title = 'Attach a file';
    add.addEventListener('click', function () { document.getElementById('photoInput').click(); });
    box.appendChild(add);
  }
  document.getElementById('photoInput').addEventListener('change', function (e) {
    var files = Array.prototype.slice.call(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;
    var m = me();
    m.photos = m.photos || [];
    function doUpload() {
      var left = files.length;
      files.forEach(function (f) {
        API.uploadEntryFile(m.entryId, f).then(function (row) {
          m.photos.push(fileFromServer('entry', row));
        }).catch(fail('Could not attach ' + f.name)).then(function () {
          if (--left > 0) return;
          logIt('Attached ' + plural(files.length, 'file') + ' to their standup', 'Standup', 'standup', 'teal');
          redrawAll();
          toast(plural(files.length, 'file') + ' attached');
        });
      });
    }
    // Attachments hang off the entry row - make sure today's exists first.
    if (m.entryId) doUpload(); else pushEntry(doUpload);
  });

  /* ---------- week ---------- */
  function renderWeek() {
    document.getElementById('weekHead').innerHTML = '<th class="stick-l">Who</th>' + DAYS.map(function (d, i) {
      return '<th' + (DAY_ISO[i] === TODAY ? ' class="today"' : '') + '>' + d + '</th>';
    }).join('');
    var body = document.getElementById('weekBody');
    body.innerHTML = '';
    TEAM.forEach(function (p) {
      var cells = DAYS.map(function (d) {
        var e = (WEEK[p.who] || {})[d];
        if (!e) return '<td class="empty">&ndash;</td>';
        var dots = e.acts.map(function (id) {
          var a = act(id);
          return a ? '<span class="wdot" style="background:var(--c-' + a.color + ')"></span>' : '';
        }).join('');
        return '<td data-menu="cell" data-label="' + PEOPLE[p.who].name + ' - ' + d + '"><div class="cell">' +
          '<span class="wdots">' + dots + '</span>' + (e.blk ? '<span class="bang">!</span>' : '') +
          '<span class="txt">' + esc(e.txt) + '</span><span class="tm">' + hhmm(e.at) + '</span></div></td>';
      }).join('');
      body.innerHTML += '<tr><td class="who stick-l">' + avatar(p.who, true) + ' ' + PEOPLE[p.who].name + '</td>' + cells + '</tr>';
    });
  }
  function teamView(which) {
    var map = { today: 'viewToday', week: 'viewWeek', cap: 'viewCap' };
    Object.keys(map).forEach(function (k) {
      document.getElementById(map[k]).setAttribute('aria-pressed', k === which ? 'true' : 'false');
    });
    document.getElementById('teamBoard').style.display = which === 'today' ? '' : 'none';
    document.getElementById('weekWrap').style.display = which === 'week' ? '' : 'none';
    document.getElementById('weekNote').style.display = which === 'week' ? '' : 'none';
    document.getElementById('capWrap').style.display = which === 'cap' ? '' : 'none';
    document.getElementById('capNote').style.display = which === 'cap' ? '' : 'none';
    document.getElementById('tile-team').setAttribute('open-state', '1');
  }
  ['today','week','cap'].forEach(function (k) {
    document.getElementById(k === 'today' ? 'viewToday' : k === 'week' ? 'viewWeek' : 'viewCap')
      .addEventListener('click', function (e) { e.stopPropagation(); teamView(k); });
  });
  document.getElementById('teamToggle').addEventListener('click', function (e) {
    e.stopPropagation();
    allCardsOpen = !allCardsOpen;
    cardOpen = {};
    cmtState = {};
    cardState = {};
    document.getElementById('tile-team').setAttribute('open-state', '1');
    renderTeam(); save();
  });
  document.getElementById('digestBtn').addEventListener('click', function (e) {
    e.stopPropagation();
    openInfo('Weekly digest - week to ' + fmt(TODAY), buildDigest(), function () {
      var txt = document.getElementById('infoBody').innerText;
      if (navigator.clipboard) navigator.clipboard.writeText(txt).catch(function () {});
      logIt('Copied the weekly digest', 'Standup', 'standup', 'teal');
      toast('Digest copied - paste it into an email');
    }, 'Copy it');
  });

  /* ---------- blockers ---------- */
  function renderBlockers() {
    var list = document.getElementById('blkList');
    list.innerHTML = '';
    var rows = [];
    TEAM.forEach(function (p) {
      if (p.b) rows.push({ who: PEOPLE[p.who].name, by: p.bBy || '', text: p.b, src: 'from standup' });
    });
    TASKS.forEach(function (t) {
      if (t.wait && !stage(t.st).done) {
        rows.push({ who: PEOPLE[t.who].name, by: t.due || '', text: t.wait + ' \u2014 ' + t.t, src: t.job, taskid: t.id });
      }
    });
    rows.sort(function (a, b) { return (a.by || '9999') < (b.by || '9999') ? -1 : 1; });
    rows.forEach(function (r) {
      var over = r.by && r.by < TODAY;
      var li = document.createElement('li');
      li.className = 'blk' + (over ? ' over' : '');
      li.dataset.menu = 'blocker';
      li.dataset.label = r.who;
      if (r.taskid) li.dataset.taskid = r.taskid;
      li.style.cursor = 'pointer';
      li.addEventListener('click', function () {
        if (r.taskid) { openEdit(taskById(r.taskid)); }
        else { document.getElementById('tile-me').setAttribute('open-state', '1'); document.getElementById('fBlock').focus(); }
      });
      li.innerHTML = '<span><b>' + esc(r.who) + '</b> ' + esc(r.text) +
        (r.by ? ' <span class="needby' + (over ? ' over' : '') + '">by ' + fmt(r.by) + '</span>' : '') + '</span>' +
        '<span class="src">' + esc(r.src) + '</span>';
      list.appendChild(li);
    });
    var late = rows.filter(function (r) { return r.by && r.by < TODAY; }).length;
    document.getElementById('blkMeta').innerHTML = rows.length + ' open' +
      (late ? ' <span class="pipcount" style="background:var(--crit-soft);color:var(--crit)">' + late + ' past due</span>' : '');
  }

  /* ---------- task filters + list ---------- */
  var sortBy = 'due', sortDir = 1;

  /* Filter state. The four original controls (text, job, waiting,
     overdue) and the client select keep the DOM as their source of
     truth and are read into F on every pass; the newer pickers live
     only in F and paint their own buttons. F is persisted per browser
     with the other UI prefs; a snapshot can be kept as "my default"
     (right-click the toolbar) and the board opens with that instead. */
  function emptyFilters() {
    return { q: '', job: '', client: '', people: [], deliv: '', record: '', stages: [], prios: [],
             due: 'any', dueFrom: '', dueTo: '', vis: 'all', waitOnly: false, dueOnly: false };
  }
  function normFilters(o) {
    var f = emptyFilters();
    if (o && typeof o === 'object') Object.keys(f).forEach(function (k) {
      if (o[k] === undefined || o[k] === null) return;
      if (Array.isArray(f[k])) { if (Array.isArray(o[k])) f[k] = o[k].map(String); }
      else if (typeof f[k] === 'boolean') f[k] = !!o[k];
      else f[k] = String(o[k]);
    });
    return f;
  }
  var DEFAULT_F = saved.defaultFilters ? normFilters(saved.defaultFilters) : null;
  var F = normFilters(DEFAULT_F || saved.filters);
  var groupBy = saved.groupBy || '';
  var groupClosed = saved.groupClosed || {};
  var DUE_MODES = [
    { k: 'any', label: 'Any date' }, { k: 'overdue', label: 'Overdue' }, { k: 'today', label: 'Due today' },
    { k: 'week', label: 'This week' }, { k: 'nextweek', label: 'Next week' }, { k: 'none', label: 'No date' },
    { k: 'range', label: 'Date range...' }
  ];
  var VIS_MODES = [
    { k: 'all', label: 'All tasks' }, { k: 'public', label: 'Public only' }, { k: 'private', label: 'Private (mine)' }
  ];
  var GROUP_MODES = [
    { k: '', label: 'None' }, { k: 'job', label: 'Job' }, { k: 'person', label: 'Person' }, { k: 'deliv', label: 'Deliverable' }
  ];
  // The deliverable chip row: every record kind a task can hang off,
  // plus Switchboards (workshop work requests) and Not linked.
  var DELIV_KINDS = [{ label: 'All', k: '' }].concat(
    LINK_KINDS.map(function (lk) { return { label: lk.label, k: lk.k, color: lk.c }; }),
    [{ label: 'Switchboards', k: 'switchboards', color: 'amber' }, { label: 'Not linked', k: 'none', color: 'slate' }]);

  function syncFiltersFromDom() {
    F.q = document.getElementById('taskFilter').value;
    F.job = document.getElementById('jobFilter').value;
    F.client = document.getElementById('clientFilter').value;
    F.waitOnly = document.getElementById('waitOnly').getAttribute('aria-pressed') === 'true';
    F.dueOnly = document.getElementById('dueOnly').getAttribute('aria-pressed') === 'true';
    F.dueFrom = document.getElementById('dueFrom').value || '';
    F.dueTo = document.getElementById('dueTo').value || '';
    return F;
  }
  function applyFiltersToDom() {
    document.getElementById('taskFilter').value = F.q || '';
    // A job or client that no longer exists falls back to "all" rather
    // than leaving a select on a value it cannot show.
    var jf = document.getElementById('jobFilter');
    jf.value = F.job || ''; if (jf.value !== (F.job || '')) { jf.value = ''; F.job = ''; }
    var cf = document.getElementById('clientFilter');
    cf.value = F.client || ''; if (cf.value !== (F.client || '')) { cf.value = ''; F.client = ''; }
    document.getElementById('waitOnly').setAttribute('aria-pressed', F.waitOnly ? 'true' : 'false');
    document.getElementById('dueOnly').setAttribute('aria-pressed', F.dueOnly ? 'true' : 'false');
    document.getElementById('dueFrom').value = F.dueFrom || '';
    document.getElementById('dueTo').value = F.dueTo || '';
    paintFilterButtons();
  }
  function setFilters(patch) {
    Object.keys(patch).forEach(function (k) { F[k] = patch[k]; });
    applyFiltersToDom(); renderStageCfg(); redrawAll(true);
  }
  function clearFilters() { F = emptyFilters(); applyFiltersToDom(); renderStageCfg(); redrawAll(true); }
  function setPeople(list) { setFilters({ people: list.slice() }); }
  function toggleIn(list, v) { var i = list.indexOf(v); if (i > -1) list.splice(i, 1); else list.push(v); }
  function anyFilterOn() {
    var e = emptyFilters();
    return Object.keys(e).some(function (k) { return JSON.stringify(F[k]) !== JSON.stringify(e[k]); });
  }
  function setGroupBy(k) { groupBy = k; save(); paintFilterButtons(); renderList(); }

  /* Switchboards = work requests owned by the workshop. The Work requests
     module says which department a request belongs to; the board asks it
     per job (the same call the record picker makes) and keys the answer
     by request id. A 404 (module not mounted) stays silent - the
     reference's own department code decides then. */
  var WR_DEPT = {}, WR_LOADED = {};
  function loadWorkshopIndex(done) {
    var codes = [];
    TASKS.forEach(function (t) {
      if (t.link && t.link.kind === 'request' && !WR_LOADED[t.job] && codes.indexOf(t.job) === -1) codes.push(t.job);
    });
    var left = codes.length;
    if (!left) { if (done) done(); return; }
    codes.forEach(function (code) {
      var pid = jobIdOf(code);
      (pid ? API.fetchWorkRequests(pid) : Promise.resolve([]))
        .then(function (rows) { (Array.isArray(rows) ? rows : []).forEach(function (r) { WR_DEPT[String(r.id)] = r.department || ''; }); })
        .catch(function () {})
        .then(function () { WR_LOADED[code] = 1; if (--left === 0 && done) done(); });
    });
  }
  function isSwitchboard(t) {
    return !!(t.link && t.link.kind === 'request' && isWorkshopRequest(t.link.ref, WR_DEPT[t.link.targetId]));
  }
  function delivMatches(t, k) {
    if (k === 'none') return !t.link;
    if (k === 'switchboards') return isSwitchboard(t);
    return !!(t.link && t.link.kind === k);
  }
  function linkKey(l) { return l ? l.kind + ':' + l.ref : ''; }
  function recordFor(l) {
    return EXISTING.filter(function (r) {
      return (l.targetId && r.targetId === l.targetId) || (r.kind === l.kind && r.ref === l.ref);
    })[0] || null;
  }
  function matchesFilters(t, q) {
    var s = stage(t.st);
    if (F.job && t.job !== F.job) return false;
    if (F.client) { var j = job(t.job); if (!j || j.client !== F.client) return false; }
    if (!assigneeMatches(t.who, function (k) { return !!PEOPLE[k]; }, F.people)) return false;
    if (F.waitOnly && !t.wait) return false;
    if (F.dueOnly && !(t.due && t.due < TODAY && !s.done)) return false;
    // Stages match by NAME so a job on its own run still answers to
    // "Pricing" when the standard run has a Pricing too.
    if (F.stages.length && F.stages.indexOf(s.name) === -1) return false;
    if (F.prios.length && F.prios.indexOf(t.p) === -1) return false;
    if (!dueMatches(t.due, s.done, F.due, { today: TODAY, endWeek: ENDWEEK, from: F.dueFrom, to: F.dueTo })) return false;
    if (F.vis === 'private' && t.vis !== 'private') return false;
    if (F.vis === 'public' && t.vis === 'private') return false;
    if (F.deliv && !delivMatches(t, F.deliv)) return false;
    if (F.record && linkKey(t.link) !== F.record) return false;
    if (q && t.t.toLowerCase().indexOf(q) === -1 && t.job.toLowerCase().indexOf(q) === -1 &&
        !(t.link && t.link.ref.toLowerCase().indexOf(q) > -1)) return false;
    return true;
  }
  /** The tasks every task surface (list, board, month, tray) shows. */
  function visible() {
    syncFiltersFromDom();
    var q = (F.q || '').trim().toLowerCase();
    var out = TASKS.filter(function (t) { return matchesFilters(t, q); });
    out.sort(function (a, b) {
      var x, y;
      if (sortBy === 'due') { x = a.due || '9999'; y = b.due || '9999'; }
      else if (sortBy === 'job') { x = a.job; y = b.job; }
      else if (sortBy === 'stage') { x = stagesOfJob(a.job).indexOf(stage(a.st)); y = stagesOfJob(b.job).indexOf(stage(b.st)); }
      else if (sortBy === 'who') { x = PEOPLE[a.who].name; y = PEOPLE[b.who].name; }
      else if (sortBy === 'prio') { x = PRIOS.indexOf(prio(a.p)); y = PRIOS.indexOf(prio(b.p)); }
      else { x = a.t.toLowerCase(); y = b.t.toLowerCase(); }
      return x < y ? -sortDir : x > y ? sortDir : 0;
    });
    return out;
  }

  /* ---------- the filter pickers ---------- */
  function fbtnPaint(id, label, on) {
    var b = document.getElementById(id);
    b.innerHTML = '<span class="fl">' + esc(label) + '</span>';
    b.classList.toggle('on', !!on);
  }
  function peopleLabel() {
    if (!F.people.length) return 'Everyone';
    var names = F.people.map(function (k) { return k === UNASSIGNED ? 'Unassigned' : ((PEOPLE[k] || {}).name || '?'); });
    return names.length === 1 ? names[0] : names.length + ' people';
  }
  function recordLabel() { return F.record ? F.record.split(':').slice(1).join(':') : 'Specific deliverable…'; }
  function dueChipLabel() {
    if (F.due === 'range') return 'Due ' + (F.dueFrom ? fmt(F.dueFrom) : '…') + ' – ' + (F.dueTo ? fmt(F.dueTo) : '…');
    var dm = DUE_MODES.filter(function (m) { return m.k === F.due; })[0] || DUE_MODES[0];
    return dm.label;
  }
  function paintFilterButtons() {
    fbtnPaint('whoFilter', peopleLabel(), F.people.length);
    fbtnPaint('recordFilter', recordLabel(), !!F.record);
    fbtnPaint('stageFilter', F.stages.length ? (F.stages.length === 1 ? F.stages[0] : F.stages.length + ' stages') : 'Any stage', F.stages.length);
    fbtnPaint('prioFilter', F.prios.length ? fmtList(F.prios.map(function (k) { return prio(k).label; })) : 'Any priority', F.prios.length);
    fbtnPaint('dueFilter', F.due === 'any' ? 'Due: any' : dueChipLabel(), F.due !== 'any');
    document.getElementById('dueRange').hidden = F.due !== 'range';
    var vm = VIS_MODES.filter(function (m) { return m.k === F.vis; })[0] || VIS_MODES[0];
    fbtnPaint('visFilter', vm.label, F.vis !== 'all');
    var gm = GROUP_MODES.filter(function (m) { return m.k === groupBy; })[0] || GROUP_MODES[0];
    fbtnPaint('groupBy', 'Group: ' + gm.label.toLowerCase(), !!groupBy);
    chipRow(document.getElementById('delivKinds'), DELIV_KINDS,
      function (o) { return (F.deliv || '') === o.k; },
      function (o) {
        F.deliv = o.k;
        if (o.k === 'switchboards') loadWorkshopIndex(function () { redrawAll(true); });
        applyFiltersToDom(); redrawAll(true);
      }, true);
  }
  /** A menu that stays open while you tick things: each pick repaints
   *  the same menu in place (a tick on the right marks what is on). */
  function checkMenu(head, x, y, build, opts) {
    (function paint() {
      renderMenu(head, build().map(function (it) {
        if (!it) return null;
        return { label: it.label, note: it.note, color: it.color, cls: it.cls, key: it.on ? '✓' : '',
                 run: function () { if (it.pick() !== false) paint(); } };
      }), x, y, opts);
    })();
  }
  function below(el) { var r = el.getBoundingClientRect(); return { x: r.left, y: r.bottom + 4 }; }
  function stageNames() {
    var all = STAGES.slice();
    Object.keys(OVERRIDES).forEach(function (p) { all = all.concat(OVERRIDES[p]); });
    var out = [];
    all.forEach(function (s) { if (!out.some(function (o) { return o.name === s.name; })) out.push({ name: s.name, color: s.color }); });
    return out;
  }
  document.getElementById('whoFilter').addEventListener('click', function () {
    var at = below(this);
    checkMenu('People', at.x, at.y, function () {
      var items = [{ label: 'Everyone', on: !F.people.length, pick: function () { setPeople([]); return false; } }, null];
      Object.keys(PEOPLE).forEach(function (k) {
        items.push({ label: PEOPLE[k].name, on: F.people.indexOf(k) > -1, pick: function () { toggleIn(F.people, k); applyFiltersToDom(); redrawAll(true); } });
      });
      items.push(null);
      items.push({ label: 'Unassigned', note: 'nobody on the board', on: F.people.indexOf(UNASSIGNED) > -1,
                   pick: function () { toggleIn(F.people, UNASSIGNED); applyFiltersToDom(); redrawAll(true); } });
      return items;
    }, Object.keys(PEOPLE).length > 8 ? { search: 'Type a name...' } : null);
  });
  document.getElementById('stageFilter').addEventListener('click', function () {
    var at = below(this);
    checkMenu('Stage', at.x, at.y, function () {
      return [{ label: 'Any stage', on: !F.stages.length, pick: function () { setFilters({ stages: [] }); return false; } }, null]
        .concat(stageNames().map(function (s) {
          return { label: s.name, color: s.color, on: F.stages.indexOf(s.name) > -1,
                   pick: function () { toggleIn(F.stages, s.name); applyFiltersToDom(); redrawAll(true); } };
        }));
    });
  });
  document.getElementById('prioFilter').addEventListener('click', function () {
    var at = below(this);
    checkMenu('Priority', at.x, at.y, function () {
      return [{ label: 'Any priority', on: !F.prios.length, pick: function () { setFilters({ prios: [] }); return false; } }, null]
        .concat(PRIOS.map(function (p) {
          return { label: p.label, color: p.c, on: F.prios.indexOf(p.key) > -1,
                   pick: function () { toggleIn(F.prios, p.key); applyFiltersToDom(); redrawAll(true); } };
        }));
    });
  });
  document.getElementById('dueFilter').addEventListener('click', function () {
    var at = below(this);
    renderMenu('Due', DUE_MODES.map(function (m) {
      return { label: m.label, key: F.due === m.k ? '✓' : '', run: function () {
        setFilters({ due: m.k });
        if (m.k === 'range') setTimeout(function () { document.getElementById('dueFrom').focus(); }, 30);
      } };
    }), at.x, at.y);
  });
  ['dueFrom', 'dueTo'].forEach(function (id) {
    document.getElementById(id).addEventListener('change', function () { syncFiltersFromDom(); redrawAll(true); });
  });
  document.getElementById('visFilter').addEventListener('click', function () {
    var at = below(this);
    renderMenu('Who can see it', VIS_MODES.map(function (m) {
      return { label: m.label, key: F.vis === m.k ? '✓' : '', run: function () { setFilters({ vis: m.k }); } };
    }), at.x, at.y);
  });
  document.getElementById('groupBy').addEventListener('click', function () {
    var at = below(this);
    renderMenu('Group the list by', GROUP_MODES.map(function (m) {
      return { label: m.label, key: groupBy === m.k ? '✓' : '', run: function () {
        setGroupBy(m.k);
        if (m.k) document.querySelector('.subtabs button[data-sub="list"]').click();
      } };
    }), at.x, at.y);
  });
  /* "Specific deliverable": the linked records present on the tasks
     right now, reference + title (titles come off the registers, so
     they are fetched for the listed jobs and the menu repaints once). */
  document.getElementById('recordFilter').addEventListener('click', function () {
    var at = below(this), HEAD = 'Specific deliverable', SEARCH = { search: 'Search reference or title...' };
    function items() {
      var seen = {}, out = [{ label: 'Any record', note: 'clear', run: function () { setFilters({ record: '' }); } }];
      TASKS.forEach(function (t) {
        var k = linkKey(t.link);
        if (!k || seen[k]) return;
        seen[k] = 1;
        var lk = linkKind(t.link.kind), rec = recordFor(t.link);
        out.push({ label: t.link.ref, color: lk ? lk.c : 'slate', key: F.record === k ? '✓' : '',
                   note: (rec ? rec.title : (lk ? lk.label : t.link.kind)) + ' · ' + t.job,
                   run: function () { setFilters({ record: k }); } });
      });
      return out;
    }
    renderMenu(HEAD, items(), at.x, at.y, SEARCH);
    loadAllRecords(function () {
      if (!ctx.classList.contains('open') || ctxHead.textContent !== HEAD) return;
      var inp = ctxBody.querySelector('.menusearch input');
      var typed = inp ? inp.value : '';
      renderMenu(HEAD, items(), at.x, at.y, SEARCH);
      inp = ctxBody.querySelector('.menusearch input');
      if (inp && typed) { inp.value = typed; inp.dispatchEvent(new Event('input')); }
    });
  });
  /** Right-click on the toolbar: the filter set as a whole. */
  function toolbarMenu() {
    var items = [
      { label: 'Clear filters', note: anyFilterOn() ? null : 'nothing set', run: function () { clearFilters(); toast('Filters cleared'); } },
      null,
      { label: 'Save these as my default', note: 'the board opens with them', run: function () {
          DEFAULT_F = normFilters(syncFiltersFromDom()); save(); toast('Saved as your default filters', 'the board opens with them from now on');
        } }
    ];
    if (DEFAULT_F) {
      items.push({ label: 'Apply my default', run: function () { F = normFilters(DEFAULT_F); applyFiltersToDom(); renderStageCfg(); redrawAll(true); toast('Default filters applied'); } });
      items.push({ label: 'Reset default', cls: 'danger', note: 'forget it', run: function () { DEFAULT_F = null; save(); toast('Default forgotten', 'the board opens unfiltered next time'); } });
    }
    items.push(null);
    items.push({ label: 'Group the list by...', note: (GROUP_MODES.filter(function (m) { return m.k === groupBy; })[0] || GROUP_MODES[0]).label.toLowerCase(), sub: function (x, y) {
      popover(x, y, 'Group by', GROUP_MODES.map(function (m) {
        return { label: m.label, key: groupBy === m.k ? '✓' : '', run: function () { setGroupBy(m.k); } };
      }));
    } });
    return items;
  }
  /** Which section a task sits in when the list is grouped. */
  function groupOf(t) {
    if (groupBy === 'job') {
      var j = job(t.job);
      return { key: 'job:' + t.job, label: t.job + (j ? '  ' + j.client + ' - ' + j.name : ''), color: jobTone(t.job) };
    }
    if (groupBy === 'person') {
      var p = PEOPLE[t.who];
      return { key: 'who:' + (p ? t.who : '-'), label: p ? p.name : 'Unassigned', color: p ? p.color : 'slate' };
    }
    if (groupBy === 'deliv') {
      if (!t.link) return { key: 'd:', label: 'Not linked', color: 'slate' };
      var lk = linkKind(t.link.kind);
      return { key: 'd:' + linkKey(t.link), color: lk ? lk.c : 'slate',
               label: (lk ? lk.label : t.link.kind) + ' ' + t.link.ref + (isSwitchboard(t) ? '  (switchboard)' : '') };
    }
    return null;
  }
  var COLS = [
    { k: 'stripe', label: '' }, { k: 'type', label: '' },
    { k: 'summary', label: 'Summary', sort: 'summary' },
    { k: 'link', label: 'Record' },
    { k: 'job', label: 'Job', sort: 'job' },
    { k: 'stage', label: 'Stage', sort: 'stage' },
    { k: 'wait', label: 'Waiting on' },
    { k: 'who', label: 'Assignee', sort: 'who' },
    { k: 'due', label: 'Due', sort: 'due' },
    { k: 'prio', label: 'Priority', sort: 'prio' }
  ];
  /* ---------- table sizing + column widths ---------- */
  var DEFAULT_W = { summary: 300, link: 178, job: 82, stage: 132, wait: 140, who: 148, due: 74, prio: 104 };
  var tblSize = saved.tblSize || 12.5;
  var colW = saved.colW || {};
  function applySize() {
    var tbl = document.getElementById('listTable');
    tbl.style.setProperty('--tsz', tblSize + 'px');
    tbl.style.setProperty('--trow', Math.max(3, Math.round(tblSize * 0.48)) + 'px');
    document.getElementById('szVal').textContent = fmtFixed(tblSize, 1);
  }
  function widthOf(k) { return colW[k] || DEFAULT_W[k] || 100; }
  /* The task table fills its tile. When the tile is wider than the
     columns add up to, the spare width is shared out - half to the
     summary, the rest in proportion - so the table always spans the
     tile; narrower, the saved widths stand and the wrap scrolls. A
     manual drag first freezes every column at what it shows, so the
     column you sized is the only one that changes. */
  var FIXED_W = 4 + 30;   // the stripe and type columns
  /* Re-fitting has to be RELIABLE, not best-effort: the widths the table
     is wearing were computed for whatever the wrap measured at the time,
     so every later change to that width - a narrower window, the page's
     own scrollbar appearing as rows arrive, the toolbar wrapping onto
     another line, the List tab coming back into view - has to run the
     fit again or the table keeps a stale width and the wrap scrolls
     sideways for good.
     A rAF alone cannot carry that: a hidden or throttled tab never
     paints a frame, so a coalescing guard waiting on one wedges shut and
     every notification after it is dropped. Arm BOTH a frame and a
     timer; whichever lands first runs the fit and cancels the other. */
  var fitRaf = 0, fitTimer = 0, fitPasses = 0;
  function scheduleFit() {
    if (fitRaf || fitTimer) return;
    function run() {
      if (fitRaf) { cancelAnimationFrame(fitRaf); fitRaf = 0; }
      if (fitTimer) { clearTimeout(fitTimer); fitTimer = 0; }
      fitListColumns();
    }
    if (typeof requestAnimationFrame === 'function') fitRaf = requestAnimationFrame(run);
    fitTimer = setTimeout(run, 60);
  }
  function fitListColumns() {
    var tbl = document.getElementById('listTable');
    // A ResizeObserver frame can land after the module has unmounted
    // (route change, HMR) - there is no table to fit then.
    var wrap = tbl && tbl.parentElement;
    var ths = document.querySelectorAll('#listHead th[data-col]');
    if (!wrap || !ths.length) return;
    // clientWidth is inside the wrap's border and minus its vertical
    // scrollbar - the width the table has to land on.
    var avail = wrap.clientWidth;
    // Hidden (the Board or Month tab is showing) - measuring gives 0 and
    // fitting to it would be nonsense; switching back to the list
    // schedules the fit it is owed.
    if (!avail) return;
    // Aim ONE pixel under it. Column widths carry fractions the browser
    // rounds up, so a table asked to land exactly on the wrap reports a
    // single pixel of overflow - and Chrome paints a real 10px scrollbar
    // for that hair. The lost pixel is invisible; the scrollbar was not.
    var target = avail - 1;
    // The stripe/type columns as they really render (padding included).
    var fixed = 0;
    Array.prototype.forEach.call(document.querySelectorAll('#listHead th:not([data-col])'), function (th) { fixed += th.getBoundingClientRect().width; });
    var forCols = Math.floor(target - Math.ceil(fixed || FIXED_W));
    var sum = 0, sumBase = widthOf('summary');
    Array.prototype.forEach.call(ths, function (th) { sum += widthOf(th.dataset.col); });
    var want = {};
    if (forCols >= sum) {
      // Wider than the columns add up to: share the spare width out,
      // half to the summary, the rest in proportion.
      var extra = forCols - sum, rest = sum - sumBase;
      Array.prototype.forEach.call(ths, function (th) {
        var k = th.dataset.col, base = widthOf(k);
        want[k] = base + (k === 'summary' ? extra * 0.5 : (rest ? extra * 0.5 * (base / rest) : 0));
      });
    } else {
      // Narrower: scale the other columns down pro-rata to their
      // minimums first, the summary column last. Below every minimum the
      // table's own 940px floor takes over and the wrap scrolls.
      var need = sum - forCols, room = 0;
      Array.prototype.forEach.call(ths, function (th) {
        var k = th.dataset.col;
        if (k !== 'summary') room += Math.max(0, widthOf(k) - minColW(k));
      });
      var take = Math.min(need, room);
      Array.prototype.forEach.call(ths, function (th) {
        var k = th.dataset.col, base = widthOf(k);
        if (k === 'summary') return;
        var give = room ? take * (Math.max(0, base - minColW(k)) / room) : 0;
        want[k] = base - give;
      });
      want.summary = Math.max(minColW('summary'), sumBase - (need - take));
    }
    // Whole pixels, rounded DOWN - landing a hair under the wrap is fine,
    // a hair over is a scrollbar.
    Array.prototype.forEach.call(ths, function (th) { th.style.width = Math.floor(want[th.dataset.col]) + 'px'; });
    // Cell padding, borders and border-spacing are the browser's to add:
    // measure what it made of that and settle the residual on the summary
    // column so the table lands at, never over, the wrap's inner width.
    var sumTh = document.querySelector('#listHead th[data-col="summary"]');
    for (var pass = 0; pass < 4 && sumTh; pass++) {
      var diff = tbl.getBoundingClientRect().width - target;
      if (diff <= 0 && diff > -1) break;
      var cur = parseFloat(sumTh.style.width);
      var next = diff > 0 ? cur - Math.ceil(diff) : cur + Math.floor(-diff);
      next = Math.max(minColW('summary'), Math.floor(next));
      if (next === cur) break;
      sumTh.style.width = next + 'px';
    }
    // The table's own box can land inside the wrap and the wrap STILL
    // report itself scrollable: the column widths carry fractions, the
    // right-most edge falls a hair past the wrap, and scrollWidth rounds
    // that up to a whole pixel of overflow - which Chrome paints as a
    // real horizontal scrollbar. Measuring the table is therefore not
    // enough; ask the wrap itself and keep trimming the summary column
    // until it says it no longer scrolls.
    // ``floored`` = the table cannot get any narrower (it is pinned at its
    // own 940px min-width, or the summary column is at its floor). Below
    // that the wrap is meant to scroll, so a lingering overflow there is by
    // design and must NOT provoke another pass.
    var floored = false;
    for (var over = 0; over < 4 && sumTh && wrap.scrollWidth > wrap.clientWidth; over++) {
      var curW = parseFloat(sumTh.style.width);
      var nextW = Math.max(minColW('summary'), Math.floor(curW - Math.max(1, wrap.scrollWidth - wrap.clientWidth)));
      if (nextW === curW) { floored = true; break; }    // already at its floor
      var wasW = tbl.getBoundingClientRect().width;
      sumTh.style.width = nextW + 'px';
      if (tbl.getBoundingClientRect().width === wasW) {
        // The table is pinned at its own 940px minimum - the wrap is
        // narrower than the table can ever be, so scrolling here is by
        // design. Give the column its width back and stop.
        sumTh.style.width = curW + 'px';
        floored = true;
        break;
      }
    }
    // Read the wrap ONE more time: laying the table out can itself change
    // it (the rows we just sized push the page over its own scrollbar
    // threshold), and a fit measured against a width that no longer
    // exists is exactly the stale-width bug. A fresh load settles later
    // still - fonts swap, the page gains its scrollbar - and the hair of
    // overflow comes BACK after the trim loop has already run, which is
    // why the width alone is not enough to decide: re-fit while the wrap
    // still says it scrolls and the table has room left to give.
    var unsettled = wrap.clientWidth !== avail || (!floored && wrap.scrollWidth > wrap.clientWidth);
    if (unsettled && fitPasses < 3) { fitPasses++; scheduleFit(); }
    else fitPasses = 0;
  }
  /** The narrowest a column may be squeezed to before the table scrolls. */
  function minColW(k) { return k === 'summary' ? 160 : k === 'link' ? 90 : k === 'who' ? 84 : 52; }
  function freezeListColumns() {
    Array.prototype.forEach.call(document.querySelectorAll('#listHead th[data-col]'), function (th) {
      colW[th.dataset.col] = th.offsetWidth;
    });
  }
  (function () {
    var wrap = document.getElementById('view-list');
    if (!wrap) return;
    // The window itself, because a resize is the common case and it must
    // not depend on the observer being in a healthy state.
    docListen(window, 'resize', scheduleFit);
    // A hidden page runs no rendering steps, so it is served NO resize
    // events and NO observer callbacks at all - a window resized while
    // the tab sat in the background comes back to a table sized for the
    // old width. Fit on the way back in.
    docListen(document, 'visibilitychange', function () {
      if (!document.hidden) scheduleFit();
    });
    if (typeof ResizeObserver === 'undefined') return;
    var ro = new ResizeObserver(scheduleFit);
    ro.observe(wrap);
    // The toolbars too: a filter row wrapping onto another line changes
    // the tile's height, which is what puts the page over (or under) its
    // scrollbar - and that changes the width the table has to fit.
    Array.prototype.forEach.call(document.querySelectorAll('.toolbar'), function (bar) { ro.observe(bar); });
    CLEANUP.push(function () { ro.disconnect(); });
  })();

  function renderListHead() {
    document.getElementById('listHead').innerHTML = COLS.map(function (c) {
      if (!c.label) return '<th style="width:' + (c.k === 'stripe' ? 4 : 30) + 'px"></th>';
      var on = sortBy === c.sort;
      return '<th data-col="' + c.k + '" style="width:' + widthOf(c.k) + 'px"' +
        (c.sort ? ' class="sortable" data-sort="' + c.sort + '"' : '') + '>' + c.label +
        (on ? ' <span class="arrow">' + (sortDir === 1 ? '&#9650;' : '&#9660;') + '</span>' : '') +
        '<span class="colgrip" data-grip="' + c.k + '"></span></th>';
    }).join('');
    Array.prototype.forEach.call(document.querySelectorAll('#listHead .sortable'), function (th) {
      th.addEventListener('click', function (e) {
        if (e.target.classList.contains('colgrip')) return;   // dragging, not sorting
        if (sortBy === th.dataset.sort) sortDir = -sortDir; else { sortBy = th.dataset.sort; sortDir = 1; }
        renderListHead(); renderList();
      });
    });
    // Drag the right edge of a header to set that column's width.
    Array.prototype.forEach.call(document.querySelectorAll('#listHead .colgrip'), function (g) {
      g.addEventListener('mousedown', function (e) {
        e.preventDefault(); e.stopPropagation();
        var th = g.closest('th');
        var key = g.dataset.grip;
        var startX = e.clientX, startW = th.offsetWidth;
        freezeListColumns();
        g.classList.add('dragging');
        document.body.classList.add('col-resizing');
        function move(ev) {
          var w = Math.max(52, startW + (ev.clientX - startX));
          colW[key] = w;
          th.style.width = w + 'px';
        }
        function up() {
          g.classList.remove('dragging');
          document.body.classList.remove('col-resizing');
          document.removeEventListener('mousemove', move);
          document.removeEventListener('mouseup', up);
          fitListColumns();
          save();
        }
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
      });
    });
    fitListColumns();
  }
  document.getElementById('szUp').addEventListener('click', function () {
    tblSize = Math.min(17, tblSize + 0.5); applySize(); save();
  });
  document.getElementById('szDown').addEventListener('click', function () {
    tblSize = Math.max(9.5, tblSize - 0.5); applySize(); save();
  });
  document.getElementById('szReset').addEventListener('click', function () {
    tblSize = 12.5; colW = {}; applySize(); renderListHead(); renderList(); save();
    toast('Table reset');
  });
  function renderList() {
    var body = document.getElementById('listBody');
    body.innerHTML = '';
    var rows = visible();
    function rowEl(t) {
      var s = stage(t.st), p = prio(t.p), j = job(t.job), jc = j ? clientTone(j.client) : 'slate';
      var dc = dueClass(t.due, s.done);
      var tr = document.createElement('tr');
      tr.dataset.menu = 'row'; tr.dataset.id = t.id; tr.dataset.label = t.t;
      // A completed task must LOOK completed - struck through and dimmed,
      // not just wearing a green badge you have to read.
      if (s.done) tr.className = 'done';
      tr.innerHTML =
        '<td class="stripe" style="background:var(--c-' + s.color + ')"></td>' +
        '<td style="width:34px"><span class="rowtype" style="background:var(--c-' + (t.sub ? 'slate' : 'blue') + ')">' + (t.sub ? '&#9707;' : '&#10003;') + '</span></td>' +
        // The whole summary cell opens the task - not just the words.
        '<td class="sum" data-act="open" title="Open this task"><span class="summary-cell">' + esc(t.t) + '</span>' + lockGlyph(t) +
          (t.rep ? '<span class="rep" data-act="rep" title="' + esc(describeRepeat(t)) + '">&#8635;</span>' : '') +
          ((t.files && t.files.length) ? '<span class="clip" data-act="files" title="' + plural(t.files.length, 'attachment') + '"> &#128206;' + t.files.length + '</span>' : '') +
          ((t.comments && t.comments.length) ? '<span class="cmt" data-act="comments" title="' + plural(t.comments.length, 'comment') + '"> &#128172;' + t.comments.length + '</span>' : '') +
          '<span class="editpen">edit</span></td>' +
        // The whole cell is the target, not just the words inside it.
        '<td class="hot" data-act="link">' + (t.link ? linkChip(t.link) : '<span class="ghost">Add link...</span>') + '</td>' +
        '<td class="hot" data-act="job"><span class="jobcell" style="' + tint(jc) + '">' + t.job + '</span></td>' +
        '<td class="hot" data-act="stage"><span class="badge" style="' + tint(s.color) + '">' + esc(s.name) + '</span></td>' +
        '<td class="hot" data-act="wait">' + (t.wait ? '<span class="wait-flag">' + esc(t.wait) + '</span>'
                         : '<span class="wait-flag off">not waiting</span>') + '</td>' +
        '<td class="hot" data-act="who"><span class="assignee">' + avatar(t.who, true) + PEOPLE[t.who].name + '</span></td>' +
        '<td class="hot" data-act="due"><span class="datecell' + dc + '">' + (t.due ? fmt(t.due) : '<span class="ghost">Set date...</span>') + '</span></td>' +
        '<td class="hot" data-act="prio"><span class="prio' + (p.loud ? ' loud' : '') + '" style="color:var(--c-' + p.c + ')"><span class="gl">' + p.gl + '</span>' + p.label + '</span></td>';
      tr.addEventListener('dblclick', function () { openEdit(t); });
      return tr;
    }
    if (!groupBy) {
      rows.forEach(function (t) { body.appendChild(rowEl(t)); });
    } else {
      // Section rows with counts; a section remembers being collapsed.
      var groups = [], byKey = {};
      rows.forEach(function (t) {
        var g = groupOf(t);
        if (!byKey[g.key]) { byKey[g.key] = { key: g.key, label: g.label, color: g.color, rows: [] }; groups.push(byKey[g.key]); }
        byKey[g.key].rows.push(t);
      });
      groups.sort(function (a, b) { return a.label.localeCompare(b.label); });
      groups.forEach(function (g) {
        var closed = !!groupClosed[g.key];
        var gh = document.createElement('tr');
        gh.className = 'grouprow' + (closed ? ' closed' : '');
        gh.title = closed ? 'Click to open this section' : 'Click to collapse this section';
        gh.innerHTML = '<td colspan="' + COLS.length + '"><span class="gtw">&#9662;</span>' +
          '<span class="gdot" style="background:' + cvar(g.color) + '"></span>' + esc(g.label) +
          '<span class="pipcount" style="' + tint('slate') + '">' + plural(g.rows.length, 'task') + '</span></td>';
        gh.addEventListener('click', function () {
          if (groupClosed[g.key]) delete groupClosed[g.key]; else groupClosed[g.key] = true;
          save(); renderList();
        });
        body.appendChild(gh);
        if (closed) return;
        g.rows.forEach(function (t) { body.appendChild(rowEl(t)); });
      });
    }
    var w = rows.filter(function (t) { return t.wait; }).length;
    var od = rows.filter(function (t) { return t.due && t.due < TODAY && !stage(t.st).done; }).length;
    document.getElementById('taskMeta').innerHTML = rows.length + ' shown' +
      (w ? ' <span class="pipcount" style="' + tint('amber') + '">' + w + ' waiting</span>' : '') +
      (od ? ' <span class="pipcount" style="background:var(--crit-soft);color:var(--crit)">' + od + ' overdue</span>' : '');
    renderActiveFilters();
    // Rows just changed: a filter, a group collapse or a poll refresh can
    // all change how tall the table is and so whether the page carries a
    // scrollbar. Coalesced, so a redraw storm still fits once.
    scheduleFit();
  }
  /* Every active filter as a removable chip, whichever control set it. */
  function renderActiveFilters() {
    syncFiltersFromDom();
    paintFilterButtons();
    var box = document.getElementById('activeFilters');
    box.innerHTML = '';
    var fs = [];
    function chip(label, clear) { fs.push({ label: label, clear: clear }); }
    if ((F.q || '').trim()) chip('"' + F.q.trim() + '"', function () { F.q = ''; });
    if (F.job) chip('Job ' + F.job, function () { F.job = ''; });
    if (F.client) chip('Client ' + F.client, function () { F.client = ''; });
    F.people.forEach(function (k) {
      chip(k === UNASSIGNED ? 'Unassigned' : ((PEOPLE[k] || {}).name || '?'), function () { toggleIn(F.people, k); });
    });
    if (F.deliv) {
      var dk = DELIV_KINDS.filter(function (d) { return d.k === F.deliv; })[0];
      chip((dk ? dk.label : F.deliv) + (F.deliv === 'none' ? '' : ' only'), function () { F.deliv = ''; });
    }
    if (F.record) chip('Record ' + recordLabel(), function () { F.record = ''; });
    F.stages.forEach(function (n) { chip('Stage ' + n, function () { toggleIn(F.stages, n); }); });
    F.prios.forEach(function (k) { chip(prio(k).label + ' priority', function () { toggleIn(F.prios, k); }); });
    if (F.due !== 'any') chip(dueChipLabel(), function () { F.due = 'any'; F.dueFrom = ''; F.dueTo = ''; });
    if (F.vis !== 'all') chip(F.vis === 'private' ? 'Private only' : 'Public only', function () { F.vis = 'all'; });
    if (F.waitOnly) chip('Waiting only', function () { F.waitOnly = false; });
    if (F.dueOnly) chip('Overdue only', function () { F.dueOnly = false; });
    if (!fs.length) return;
    fs.forEach(function (f) {
      var c = document.createElement('span');
      c.className = 'fchip';
      c.innerHTML = esc(f.label) + '<button title="Clear">&#10005;</button>';
      c.querySelector('button').addEventListener('click', function () {
        f.clear(); applyFiltersToDom(); renderStageCfg(); redrawAll(true);
      });
      box.appendChild(c);
    });
    var all = document.createElement('button');
    all.className = 'icon-btn'; all.textContent = 'Clear filters';
    all.addEventListener('click', function () { clearFilters(); });
    box.appendChild(all);
  }

  /* ---------- month ---------- */
  var monthCursor = (function () { var d = parseISO(TODAY); return { y: d.getFullYear(), m: d.getMonth() }; })();
  var MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

  /** Future occurrences a rule will produce inside [from,to], without
   *  creating anything. Capped so a bad rule cannot run away. */
  function projections(from, to) {
    var out = [];
    visible().forEach(function (t) {
      if (!t.rep || !t.due || stage(t.st).done) return;
      var d = t.due, guard = 0;
      while (guard++ < 24) {
        d = nextOccurrence(d, t.rep);
        if (!d || d > to) break;
        if (d >= from) out.push({ task: t, day: d });
      }
    });
    return out;
  }

  function renderMonth() {
    var y = monthCursor.y, m = monthCursor.m;
    document.getElementById('monthLabel').textContent = MONTHS[m] + ' ' + y;

    var first = new Date(y, m, 1);
    var start = new Date(y, m, 1 - ((first.getDay() + 6) % 7));   // back to Monday
    var cells = [];
    for (var i = 0; i < 42; i++) {
      var d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      cells.push(d);
      if (i >= 34 && d.getMonth() !== m) break;                    // stop at 5 rows when it fits
    }
    var from = ymd(cells[0]), to = ymd(cells[cells.length - 1]);

    var vis = visible();
    var real = {};
    vis.forEach(function (t) {
      if (!t.due || t.due < from || t.due > to) return;
      (real[t.due] = real[t.due] || []).push(t);
    });
    var proj = {};
    projections(from, to).forEach(function (p) { (proj[p.day] = proj[p.day] || []).push(p.task); });

    renderMonthTray(vis);

    var grid = document.getElementById('monthGrid');
    grid.innerHTML = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
      .map(function (n) { return '<div class="dow">' + n + '</div>'; }).join('');

    /** One task line in a day: job-coloured bar, title, who has it, a
     *  waiting mark. Ghost = a repeat still to come, not a task yet. */
    function evHtml(t, ghost) {
      var s = stage(t.st);
      var over = !ghost && t.due < TODAY && !s.done;
      var jc = cvar(jobTone(t.job));
      var title = esc(t.t) + ' - ' + t.job + (ghost ? ' - repeats: ' + esc(describeRepeat(t)) : (t.wait ? ' - waiting on ' + esc(t.wait) : ''));
      // A real event carries the task's own right-click menu (the same
      // one as the list row); a ghost gets a menu about the repeat.
      return '<span class="ev' + (over ? ' over' : '') + (ghost ? ' proj' : '') + '"' + (ghost ? '' : ' draggable="true"') +
        ' data-taskid="' + t.id + '" data-id="' + t.id + '" data-menu="' + (ghost ? 'ghost' : 'row') + '" data-label="' + esc(t.t) + (ghost ? ' (repeat to come)' : '') + '"' +
        ' style="--ec:' + jc + '" title="' + title + '">' +
        '<span class="evt">' + (t.rep ? '&#8635; ' : '') + esc(t.t) + '</span>' + (ghost ? '' : lockGlyph(t)) +
        (t.wait && !ghost ? '<span class="wt" title="Waiting on ' + esc(t.wait) + '">&#9203;</span>' : '') +
        (ghost ? '' : avatar(t.who, true)) + '</span>';
    }
    var MAX_PER_DAY = 4;

    cells.forEach(function (d) {
      var iso = ymd(d);
      var out = d.getMonth() !== m;
      var weekend = d.getDay() === 0 || d.getDay() === 6;
      var cell = document.createElement('div');
      cell.className = 'day' + (out ? ' out' : '') + (weekend ? ' weekend' : '') + (iso === TODAY ? ' today' : '');
      cell.dataset.menu = 'day'; cell.dataset.day = iso; cell.dataset.label = fmt(iso);

      var items = (real[iso] || []).map(function (t) { return { t: t, ghost: false }; })
        .concat((proj[iso] || []).map(function (t) { return { t: t, ghost: true }; }));
      var html = '<span class="dnum">' + d.getDate() + '</span>';
      var head = items.length > MAX_PER_DAY ? items.slice(0, MAX_PER_DAY - 1) : items;
      var rest = items.slice(head.length);
      head.forEach(function (it) { html += evHtml(it.t, it.ghost); });
      if (rest.length) html += '<button type="button" class="evmore" title="Show all ' + items.length + '">+' + rest.length + ' more</button>';
      cell.innerHTML = html;

      if (rest.length) {
        cell.querySelector('.evmore').addEventListener('click', function (e) {
          e.stopPropagation();
          var r = e.target.getBoundingClientRect();
          renderMenu(fmt(iso) + ' - ' + items.length + ' tasks', items.map(function (it) {
            var t = it.t;
            return {
              label: (t.rep ? '↻ ' : '') + t.t,
              note: it.ghost ? 'repeat to come' : t.job + ' · ' + (PEOPLE[t.who] || {}).ini + (t.wait ? ' · waiting' : ''),
              color: jobTone(t.job),
              run: function () {
                if (it.ghost) toast('Not a task yet - ' + describeRepeat(t).toLowerCase(), 'it is created when the current one is closed');
                else openEdit(t);
              }
            };
          }), r.left, r.bottom + 4);
        });
      }

      cell.addEventListener('click', function (e) {
        var ev = e.target.closest('.ev');
        if (ev) {
          e.stopPropagation();
          var t = taskById(ev.dataset.taskid);
          if (!t) return;
          if (ev.classList.contains('proj')) {
            toast('Not a task yet - ' + describeRepeat(t).toLowerCase(), 'it is created when the current one is closed');
          } else openEdit(t);
          return;
        }
        newTaskOn(iso);
      });
      // Dated tasks can be dragged between days too.
      Array.prototype.forEach.call(cell.querySelectorAll('.ev[draggable="true"]'), function (ev) {
        ev.addEventListener('dragstart', function (e) {
          dragDue = ev.dataset.taskid;
          ev.classList.add('dragging');
          if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'task:' + ev.dataset.taskid); }
        });
        ev.addEventListener('dragend', function () { ev.classList.remove('dragging'); dragDue = null; });
      });
      cell.addEventListener('dragover', function (e) { if (dragDue) { e.preventDefault(); cell.classList.add('over'); } });
      cell.addEventListener('dragleave', function () { cell.classList.remove('over'); });
      cell.addEventListener('drop', function (e) {
        cell.classList.remove('over');
        var raw = e.dataTransfer ? e.dataTransfer.getData('text/plain') : '';
        var id = dragDue || (raw.indexOf('task:') === 0 ? raw.slice(5) : '');
        if (!id) return;
        e.preventDefault(); e.stopPropagation();
        var t = taskById(id);
        dragDue = null;
        if (!t || t.due === iso) return;
        setDue(t, iso);
      });
      grid.appendChild(cell);
    });
  }
  /* The tray above the grid: open tasks with no date yet, each a chip
     you drag onto a day. Empty = hidden. */
  var dragDue = null;
  function renderMonthTray(vis) {
    var tray = document.getElementById('monthTray');
    var body = document.getElementById('monthTrayBody');
    var undated = vis.filter(function (t) { return !t.due && !stage(t.st).done; });
    tray.hidden = !undated.length;
    body.innerHTML = '';
    document.getElementById('monthTrayCount').textContent = String(undated.length);
    undated.forEach(function (t) {
      var chip = document.createElement('span');
      chip.className = 'mtchip';
      chip.draggable = true;
      chip.dataset.menu = 'row'; chip.dataset.id = t.id; chip.dataset.label = t.t;
      chip.style.setProperty('--ec', cvar(jobTone(t.job)));
      chip.title = t.t + ' - ' + t.job + (t.wait ? ' - waiting on ' + t.wait : '') + ' - drag onto a day, click to open';
      chip.innerHTML = '<span class="jc">' + esc(t.job) + '</span><span class="t">' + esc(t.t) + '</span>' + lockGlyph(t) +
        (t.wait ? '<span class="wt" title="Waiting on ' + esc(t.wait) + '">&#9203;</span>' : '') + avatar(t.who, true);
      chip.addEventListener('click', function () { openEdit(t); });
      chip.addEventListener('dragstart', function (e) {
        dragDue = t.id;
        chip.classList.add('dragging');
        if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'task:' + t.id); }
      });
      chip.addEventListener('dragend', function () { chip.classList.remove('dragging'); dragDue = null; });
      body.appendChild(chip);
    });
  }
  function newTaskOn(iso) {
    createSingleTask({ title: 'New task', project_id: defaultJobId(), assignee_id: ME_ID, due: iso }, true);
  }
  document.getElementById('monthPrev').addEventListener('click', function () {
    monthCursor.m--; if (monthCursor.m < 0) { monthCursor.m = 11; monthCursor.y--; } renderMonth();
  });
  document.getElementById('monthNext').addEventListener('click', function () {
    monthCursor.m++; if (monthCursor.m > 11) { monthCursor.m = 0; monthCursor.y++; } renderMonth();
  });
  document.getElementById('monthToday').addEventListener('click', function () {
    var d = parseISO(TODAY);
    monthCursor = { y: d.getFullYear(), m: d.getMonth() };
    renderMonth();
  });

  /* ---------- board ---------- */
  /** Rename a column in place - the header text becomes an input. */
  function renameStageInline(span, s, pid) {
    var inp = document.createElement('input');
    inp.type = 'text'; inp.value = s.name;
    inp.style.cssText = 'width:130px;font-size:11px;padding:2px 5px;font-weight:700;text-transform:uppercase';
    span.replaceWith(inp);
    inp.focus(); inp.select();
    var done = false;
    function commit() {
      if (done) return;
      done = true;
      var v = inp.value.trim();
      if (v && v !== s.name) {
        s.name = v;
        logIt('Renamed a stage to "' + v + '"', 'Settings', 'config', s.color);
        queueStagesSave(pid);
        toast('Stage renamed');
      }
      redrawAll();
    }
    inp.addEventListener('blur', commit);
    inp.addEventListener('keydown', function (ev) {
      // Commit directly - blur() only fires the handler when the input
      // actually holds focus, which it does not in an unfocused window.
      if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
      if (ev.key === 'Escape') { inp.value = s.name; commit(); }
    });
    // A header is draggable; typing must not start a drag.
    inp.addEventListener('mousedown', function (ev) { ev.stopPropagation(); });
    inp.addEventListener('dragstart', function (ev) { ev.preventDefault(); ev.stopPropagation(); });
  }
  function stageColourMenu(s, pid, x, y) {
    renderMenu('Colour for ' + s.name, COLORS.map(function (c) {
      return { label: c.charAt(0).toUpperCase() + c.slice(1) + (c === s.color ? '  (current)' : ''), color: c, run: function () {
        s.color = c;
        logIt('Recoloured the "' + s.name + '" stage', 'Settings', 'config', c);
        queueStagesSave(pid);
        redrawAll();
      } };
    }), x, y);
  }
  function renderBoardScope() {
    var box = document.getElementById('boardScope');
    var jf = document.getElementById('jobFilter').value;
    box.innerHTML = '';
    box.hidden = !jf;
    if (!jf) return;
    var own = jobHasOwn(jf);
    box.innerHTML = 'Job <span class="own">' + esc(jf) + '</span> ' +
      (own ? 'is on <b>its own stages</b> - changes to these columns leave the other jobs alone. '
           : 'is on the <b>standard stages</b> shared by every job. ');
    var b = document.createElement('button');
    b.type = 'button';
    b.textContent = own ? 'Put it back on the standard stages' : 'Give this job its own stages';
    b.addEventListener('click', function () { if (own) dropOwnStages(jf); else startOwnStages(jf); });
    box.appendChild(b);
  }
  function renderBoard() {
    var k = document.getElementById('kanban');
    k.innerHTML = '';
    renderBoardScope();
    var vis = visible();
    var list = activeStages();
    var pid = activeScopePid();
    // A task whose job is on its own stages still shows on the shared
    // board (and the other way round): it sits in the column with the
    // same NAME, else the first. Moving it is resolved on drop.
    var shown = {};
    vis.forEach(function (t) { shown[t.id] = displayStageIn(t, list); });
    list.forEach(function (s, idx) {
      var col = document.createElement('div');
      col.className = 'col';
      col.style.setProperty('--sc', 'var(--c-' + s.color + ')');
      col.dataset.stage = s.id;
      var mine = vis.filter(function (t) { return shown[t.id] === s.id; });
      var head = document.createElement('div');
      head.className = 'col-head';
      head.draggable = true;
      head.dataset.menu = 'stagecol'; head.dataset.stage = s.id; head.dataset.label = s.name;
      head.title = 'Drag to reorder';
      head.innerHTML = '<span class="cdot" title="Change the colour"></span>' +
        '<span class="name" title="Double-click to rename">' + esc(s.name) + '</span>' +
        '<span class="n" style="' + tint(s.color) + '">' + mine.length + '</span>' +
        (s.wip != null ? '<span class="wip' + (mine.length > s.wip ? ' breach' : '') + '" title="WIP limit">' + mine.length + '/' + s.wip + '</span>' : '') +
        '<button class="cog" title="Stage options">&#8942;</button>';
      head.querySelector('.cog').addEventListener('click', function (e) {
        e.stopPropagation();
        var r = e.target.getBoundingClientRect();
        openCtx(r.left, r.bottom + 4, head);
      });
      head.querySelector('.cdot').addEventListener('click', function (e) {
        e.stopPropagation();
        var r = e.target.getBoundingClientRect();
        stageColourMenu(s, pid, r.left, r.bottom + 4);
      });
      // Double-click the stage name renames it in place.
      head.querySelector('.name').addEventListener('dblclick', function (e) {
        e.stopPropagation(); e.preventDefault();
        renameStageInline(e.target, s, pid);
      });
      head.addEventListener('dragstart', function (e) {
        dragCol = s.id;
        head.classList.add('dragging');
        if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'stage:' + s.id); }
      });
      head.addEventListener('dragend', function () { head.classList.remove('dragging'); dragCol = null; });
      col.appendChild(head);
      var cbody = document.createElement('div');
      cbody.className = 'col-body';
      col.appendChild(cbody);
      mine.forEach(function (t) {
        var p = prio(t.p), j = job(t.job), jc = j ? clientTone(j.client) : 'slate';
        var dc = dueClass(t.due, s.done);
        var c = document.createElement('div');
        c.className = 'kcard' + (t.wait ? ' waiting' : '') + (s.done ? ' done' : '');
        c.draggable = true;
        c.dataset.id = t.id; c.dataset.menu = 'row'; c.dataset.label = t.t;
        // Same data-act hooks as the list, so left-click edits a value on
        // the board exactly as it does in the table.
        c.innerHTML = '<span class="kt">' + esc(t.t) + lockGlyph(t) +
          (t.rep ? '<span class="rep" data-act="rep" title="' + esc(describeRepeat(t)) + '">&#8635;</span>' : '') +
          ((t.files && t.files.length) ? '<span class="clip"> &#128206;' + t.files.length + '</span>' : '') +
          ((t.comments && t.comments.length) ? '<span class="cmt" data-act="comments"> &#128172;' + t.comments.length + '</span>' : '') + '</span>' +
          (t.link ? '<span>' + linkChip(t.link) + '</span>' : '') +
          (t.wait ? '<span class="kwait" data-act="wait">Waiting: ' + esc(t.wait) + '</span>' : '') +
          '<span class="kmeta"><span class="jobcell" data-act="job" style="' + tint(jc) + '">' + t.job + '</span>' +
          '<span class="prio' + (p.loud ? ' loud' : '') + '" data-act="prio" style="color:var(--c-' + p.c + ')" title="' + p.label + '"><span class="gl">' + p.gl + '</span>' + (p.loud ? 'Urgent' : '') + '</span>' +
          (t.due ? '<span class="kdue' + dc + '" data-act="due">' + fmt(t.due) + '</span>'
                 : '<span class="kdue" data-act="due" style="opacity:.6">set due</span>') +
          '<span class="spacer"></span><span data-act="who">' + avatar(t.who, true) + '</span></span>';
        c.addEventListener('dblclick', function () { openEdit(t); });
        cbody.appendChild(c);
      });
      if (!mine.length) { var e = document.createElement('div'); e.className = 'empty-slot'; e.textContent = 'Drop here'; cbody.appendChild(e); }
      k.appendChild(col);
    });
    var add = document.createElement('button');
    add.className = 'addcol'; add.textContent = '+ Add stage';
    add.title = pid ? 'Adds a stage to this job\'s own run' : 'Adds a stage to the standard run';
    add.addEventListener('click', function () { addStageTo(pid); });
    k.appendChild(add);
    wireDrag();
  }
  /** Drop a task on a column that may not be one of its own: the same
   *  stage id when it is, else its job's stage with the same NAME. */
  function dropTargetFor(t, stageId) {
    var own = stagesOfJob(t.job);
    for (var i = 0; i < own.length; i++) if (own[i].id === stageId) return own[i].id;
    var nm = (stageOrNull(stageId) || {}).name;
    for (var k = 0; k < own.length; k++) if (own[k].name === nm) return own[k].id;
    return null;
  }
  var dragId = null, dragCol = null;
  function wireDrag() {
    var k = document.getElementById('kanban');
    Array.prototype.forEach.call(k.querySelectorAll('.kcard'), function (c) {
      c.addEventListener('dragstart', function (e) {
        e.stopPropagation();
        dragId = c.dataset.id;
        c.classList.add('dragging');
        if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', c.dataset.id); }
      });
      c.addEventListener('dragend', function () { c.classList.remove('dragging'); dragId = null; });
    });
    Array.prototype.forEach.call(k.querySelectorAll('.col'), function (col) {
      col.addEventListener('dragover', function (e) {
        e.preventDefault();
        col.classList.add(dragCol ? 'colover' : 'over');
      });
      col.addEventListener('dragleave', function () { col.classList.remove('over'); col.classList.remove('colover'); });
      col.addEventListener('drop', function (e) {
        e.preventDefault(); col.classList.remove('over'); col.classList.remove('colover');
        var raw = e.dataTransfer ? e.dataTransfer.getData('text/plain') : '';
        var colId = dragCol || (raw.indexOf('stage:') === 0 ? raw.slice(6) : null);
        if (colId) {
          // A column dropped on a column: reorder within the run shown.
          var list = activeStages(), pid = activeScopePid();
          var from = -1, to = -1;
          list.forEach(function (s, i) { if (s.id === colId) from = i; if (s.id === col.dataset.stage) to = i; });
          if (from === -1 || to === -1 || from === to) return;
          var moved = list.splice(from, 1)[0];
          list.splice(to, 0, moved);
          logIt('Moved "' + moved.name + '" ' + (to < from ? 'earlier' : 'later'), 'Settings', 'config', 'slate');
          queueStagesSave(pid);
          redrawAll();
          return;
        }
        var t = taskById(dragId || raw);
        if (!t) return;
        var target = dropTargetFor(t, col.dataset.stage);
        if (!target) { toast(t.job + ' has its own stages', 'filter to that job to move this task'); return; }
        if (t.st === target) return;
        moveToStage(t, target);
      });
    });
  }

  /* ---------- inline edit ---------- */
  function setWait(t, text) {
    t.wait = text;
    logIt(text ? '"' + t.t + '" is waiting on ' + text : 'Cleared the waiting flag on "' + t.t + '"', t.job, 'task', text ? 'amber' : 'green');
    pushTaskField(t, { waiting_on: text });
    redrawAll();
    toast(text ? 'Waiting: ' + text : 'Waiting flag cleared');
  }
  /* One handler, both surfaces: the list rows and the board cards carry
     the same data-act hooks, so "left-click the value to change it" means
     the same thing wherever you are. */
  function wireInline(container, rowSel) {
    container.addEventListener('click', function (e) {
      var a = e.target.closest('[data-act]');
      var holder = e.target.closest(rowSel);
      if (!holder) return;
      if (!a) {
        var s = e.target.closest('.summary-cell') || e.target.closest('.editpen') || e.target.closest('.kt');
        if (s) openEdit(taskById(holder.dataset.id));
        return;
      }
      inlineEdit(a, taskById(holder.dataset.id));
    });
  }
  function inlineEdit(a, t) {
    if (!t) return;
    var r = a.getBoundingClientRect();
    if (a.dataset.act === 'link') {
      renderMenu(t.link ? 'Linked record' : 'Add a link', linkItems(t), r.left, r.bottom + 4);
    } else if (a.dataset.act === 'files') {
      openEdit(t);
      setTimeout(function () { document.getElementById('mDrop').scrollIntoView({ block: 'center' }); }, 60);
    } else if (a.dataset.act === 'comments') {
      openEdit(t);
      setTimeout(function () {
        document.getElementById('mCommentsWrap').scrollIntoView({ block: 'center' });
        document.getElementById('mCommentBox').focus();
      }, 60);
    } else if (a.dataset.act === 'rep') {
      popover(r.left, r.bottom + 4, 'Repeat', REPEATS.map(function (rp) {
        return { label: rp.label, run: function () {
          t.rep = rp.key;
          logIt('"' + t.t + '" ' + (rp.key ? 'repeats ' + rp.label.toLowerCase() : 'no longer repeats'), t.job, 'task', 'cyan');
          pushTaskField(t, { repeat_rule: rp.key });
          redrawAll(); toast(rp.key ? 'Repeats ' + rp.label.toLowerCase() : 'Repeat removed');
        } };
      }));
    } else if (a.dataset.act === 'open') {
      openEdit(t);
    } else if (a.dataset.act === 'stage') {
      popover(r.left, r.bottom + 4, 'Move to', stagesOfJob(t.job).map(function (s) {
        return { label: s.name, color: s.color, run: function () { moveToStage(t, s.id); } };
      }));
    } else if (a.dataset.act === 'wait') {
      renderMenu('Waiting on', waitItems(t), r.left, r.bottom + 4);
    } else if (a.dataset.act === 'who') {
      popover(r.left, r.bottom + 4, 'Assign to', Object.keys(PEOPLE).map(function (kk) {
        return { label: PEOPLE[kk].name, run: function () {
          t.who = kk; logIt('Assigned "' + t.t + '" to ' + PEOPLE[kk].name, t.job, 'task', 'blue');
          pushTaskField(t, { assignee_id: kk });
          redrawAll(); toast('Assigned to ' + PEOPLE[kk].name);
        } };
      }));
    } else if (a.dataset.act === 'prio') {
      popover(r.left, r.bottom + 4, 'Priority', PRIOS.map(function (p) {
        return { label: p.label, color: p.c, run: function () {
          t.p = p.key; logIt('Set "' + t.t + '" priority to ' + p.label, t.job, 'task', p.c);
          pushTaskField(t, { priority: p.key });
          redrawAll(); toast('Priority ' + p.label);
        } };
      }));
    } else if (a.dataset.act === 'due') {
      popover(r.left, r.bottom + 4, 'Due date', [
        { label: 'Today', run: function () { setDue(t, TODAY); } },
        { label: 'Tomorrow', run: function () { setDue(t, TOMORROW); } },
        { label: 'End of the week', run: function () { setDue(t, ENDWEEK); } },
        { label: 'Next week', run: function () { setDue(t, NEXTWEEK); } },
        { label: 'Clear the date', run: function () { setDue(t, null); } },
        { label: 'Pick a date...', run: function () { openEdit(t); document.getElementById('mDue').focus(); } }
      ]);
    } else if (a.dataset.act === 'job') {
      renderMenu('Move to job', JOBS.map(function (j) {
        return { label: j.code, note: j.client, color: clientTone(j.client), run: function () {
          t.job = j.code; logIt('Moved "' + t.t + '" to job ' + j.code, j.code, 'task', CLIENT_COLOR[j.client]);
          pushTaskField(t, { project_id: j.id });
          redrawAll(); toast('Now on ' + j.code, j.client + ' - ' + j.name);
        } };
      }), r.left, r.bottom + 4, { search: 'Search jobs...' });
    }
  }
  wireInline(document.getElementById('listBody'), 'tr[data-id]');
  wireInline(document.getElementById('kanban'), '.kcard[data-id]');

  function setDue(t, d) {
    t.due = d;
    logIt(d ? 'Set "' + t.t + '" due ' + fmt(d) : 'Cleared the due date on "' + t.t + '"', t.job, 'task', d && d < TODAY ? 'red' : 'blue');
    pushTaskField(t, { due: d || '' });
    redrawAll();
    toast(d ? 'Due ' + fmt(d) : 'Due date cleared');
  }

  /* ---------- combo: type to predict, or open the list ---------- */
  /* Each field says what it can offer instead of making you remember it:
     typing filters, the caret shows everything, arrows and Enter work. */
  function makeCombo(inputId, getOptions, onPick) {
    var input = document.getElementById(inputId);
    var wrap = input.parentElement;
    var list = document.createElement('div');
    list.className = 'combo-list';
    wrap.appendChild(list);
    var cursor = -1;

    function paint(q, showAll) {
      // Never wider than whatever holds it - a dialog, or the tile.
      var host = input.closest('.modal') || input.closest('.tile') || document.body;
      list.style.maxWidth = Math.max(240, host.clientWidth - 34) + 'px';
      var opts = getOptions() || [];
      var ql = (q || '').toLowerCase().trim();
      var shown = (showAll || !ql) ? opts : opts.filter(function (o) {
        return (o.label + ' ' + (o.note || '')).toLowerCase().indexOf(ql) > -1;
      });
      list.innerHTML = '';
      cursor = -1;
      if (!shown.length) {
        list.innerHTML = '<div class="cnone">' + (ql ? 'No match - your text is kept as typed.' : 'Nothing to suggest.') + '</div>';
        list.classList.add('open');
        return;
      }
      shown.slice(0, 40).forEach(function (o) {
        var b = document.createElement('button');
        b.type = 'button';
        if (o.color) {
          var d = document.createElement('span');
          d.className = 'cdot';
          d.style.background = 'var(--c-' + o.color + ')';
          b.appendChild(d);
        }
        var s = document.createElement('span');
        s.textContent = o.label;
        b.appendChild(s);
        if (o.note) { var n = document.createElement('span'); n.className = 'cnote'; n.textContent = o.note; b.appendChild(n); }
        b.addEventListener('mousedown', function (e) {
          e.preventDefault();           // keep focus so blur does not race the pick
          input.value = o.value !== undefined ? o.value : o.label;
          close();
          if (onPick) onPick(o);
        });
        list.appendChild(b);
      });
      list.classList.add('open');
    }
    function close() { list.classList.remove('open'); cursor = -1; }
    function move(step) {
      var btns = list.querySelectorAll('button');
      if (!btns.length) return;
      if (cursor > -1) btns[cursor].classList.remove('on');
      cursor = (cursor + step + btns.length) % btns.length;
      btns[cursor].classList.add('on');
      btns[cursor].scrollIntoView({ block: 'nearest' });
    }

    input.addEventListener('input', function () { paint(input.value, false); });
    input.addEventListener('focus', function () { paint(input.value, !input.value); });
    input.addEventListener('blur', function () { setTimeout(close, 120); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (!list.classList.contains('open')) paint(input.value, true); else move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') {
        var btns = list.querySelectorAll('button');
        if (cursor > -1 && btns[cursor]) { e.preventDefault(); btns[cursor].dispatchEvent(new MouseEvent('mousedown')); }
        else close();
      } else if (e.key === 'Escape') { close(); }
    });
    var btn = wrap.querySelector('.combo-btn[data-for="' + inputId + '"]');
    if (btn) btn.addEventListener('mousedown', function (e) {
      e.preventDefault();
      if (list.classList.contains('open')) close();
      else { input.focus(); paint('', true); }
    });
    return { refresh: function () { if (list.classList.contains('open')) paint(input.value, false); }, close: close };
  }

  /** A dropdown that keeps its colour. Scales past a wall of chips. */
  function pickButton(btnId, getOptions, getCurrent, onPick) {
    var btn = document.getElementById(btnId);
    btn.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      var r = btn.getBoundingClientRect();
      renderMenu(btn.dataset.head || 'Choose', getOptions().map(function (o) {
        return {
          label: o.label, color: o.raw ? null : o.color, note: o.note,
          run: function () { onPick(o); }
        };
      }), r.left, r.bottom + 4, getOptions().length > 8 ? { search: 'Type to filter...' } : null);
    });
    return function paint() {
      var cur = getCurrent();
      btn.innerHTML = '';
      if (!cur) { btn.innerHTML = '<span class="pname" style="color:var(--muted)">Choose...</span>'; return; }
      if (cur.raw) {
        var av = document.createElement('span');
        av.className = 'pav'; av.style.background = cur.color; av.textContent = cur.ini || '';
        btn.appendChild(av);
      } else if (cur.color) {
        var d = document.createElement('span');
        d.className = 'pdot'; d.style.background = cvar(cur.color);
        btn.appendChild(d);
      }
      var n = document.createElement('span');
      n.className = 'pname marquee';
      var inner = document.createElement('span');
      inner.className = 'mq';
      inner.textContent = cur.label;
      n.appendChild(inner);
      btn.appendChild(n);
      btn.title = cur.label;
      setTimeout(function () { fitMarquee(btn); }, 0);
    };
  }

  /** A row of colour chips - one click, all options visible. */
  function chipRow(el, options, isOn, onPick, small) {
    el.innerHTML = '';
    options.forEach(function (o) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pchip' + (small ? ' sm' : '');
      if (o.color) {
        var d = document.createElement('span');
        d.className = 'pdot';
        d.style.background = o.raw ? o.color : cvar(o.color);
        b.appendChild(d);
      }
      b.appendChild(document.createTextNode(o.label));
      if (isOn(o)) {
        b.setAttribute('aria-pressed', 'true');
        if (o.color) b.setAttribute('style', o.raw
          ? 'background:' + o.color + '22;color:' + o.color + ';border-color:' + o.color
          : tint(o.color));
      }
      b.addEventListener('click', function (e) { e.preventDefault(); onPick(o); });
      el.appendChild(b);
    });
  }

  /* ---------- edit modal ---------- */
  var editing = null;
  var draft = { st: null, p: null, who: null, rep: '', link: null, vis: 'public' };
  var openedAt = 0;
  var scrim = document.getElementById('scrim');
  /* Public/private is its own call, not part of the field patch: the
     server refuses it from anyone but the creator, assignee or an admin
     (403), and that refusal must put the glyph back rather than leave
     the row lying about what the server holds. */
  function setVisibility(t, v) {
    if (t.vis === v) return;
    var was = t.vis;
    t.vis = v;
    redrawAll(true);
    API.patchBoardTask(t.id, { visibility: v }).then(function () {
      logIt('Made "' + t.t + '" ' + v, t.job, 'task', v === 'private' ? 'amber' : 'green');
      renderLog();
      toast(v === 'private' ? 'Now private' : 'Now public',
        v === 'private' ? 'only you, the assignee and admins see it' : 'the whole team sees it');
    }).catch(function (err) {
      t.vis = was;
      redrawAll(true);
      fail('Could not change who sees it')(err);
    });
  }
  function openEdit(t) {
    if (!t) return;
    editing = t;
    // A double-click opens the dialog on the FIRST click; the second click
    // then lands on the backdrop that just appeared under the cursor and
    // would close it again. Ignore backdrop clicks for a moment after open.
    openedAt = Date.now();
    // Pending values live here until Save, so nothing is committed by a
    // stray click on a chip.
    draft = { st: t.st, p: t.p, who: t.who, rep: t.rep || '', vis: t.vis || 'public', link: t.link ? { kind: t.link.kind, ref: t.link.ref, targetId: t.link.targetId || '' } : null };
    document.getElementById('mTitle').textContent = 'Edit task';
    document.getElementById('mSummary').value = t.t;
    document.getElementById('mJob').value = t.job;
    document.getElementById('mDue').value = t.due || '';
    document.getElementById('mWait').value = t.wait || '';
    document.getElementById('mNotes').value = t.notes || '';
    document.getElementById('mLinkRef').value = t.link ? t.link.ref : '';
    paintEditChips();
    renderFiles(t);
    // Warm the record cache so the reference combo has real suggestions.
    loadRecordsFor(t.job);
    scrim.classList.add('open');
    setTimeout(function () { document.getElementById('mSummary').focus(); }, 30);
  }

  /** Everything in the dialog that is a choice, drawn as colour chips. */
  function paintEditChips() {
    var t = editing;
    if (!t) return;
    var s = stage(draft.st), p = prio(draft.p);

    document.getElementById('mModal').style.setProperty('--mc', 'var(--c-' + s.color + ')');
    var hs = document.getElementById('mHeadStage');
    hs.textContent = s.name;
    hs.setAttribute('style', tint(s.color));
    document.getElementById('mHeadRef').textContent =
      t.job + (draft.link ? '  ' + draft.link.ref : '');
    // Who can see it: the segmented control, the header pill and a line
    // saying who that actually is.
    document.getElementById('mHeadVis').hidden = draft.vis !== 'private';
    Array.prototype.forEach.call(document.querySelectorAll('#mVis button'), function (b) {
      b.setAttribute('aria-pressed', b.dataset.vis === draft.vis ? 'true' : 'false');
    });
    var whoName = (PEOPLE[draft.who] || {}).name;
    document.getElementById('mVisNote').textContent = draft.vis === 'private'
      ? 'Only its creator, ' + (draft.who === ME_ID ? 'you (the assignee)' : (whoName || 'the assignee')) + ' and admins see it.'
      : 'The whole team sees it.';

    paintStageBtn(); paintPrioBtn(); paintWhoBtn(); paintRepBtn();
    renderTaskComments();

    var due = document.getElementById('mDue').value;
    chipRow(document.getElementById('mDueQuick'), [
      { label: 'Today', id: TODAY }, { label: 'Tomorrow', id: TOMORROW },
      { label: 'End of week', id: ENDWEEK }, { label: 'Next week', id: NEXTWEEK },
      { label: 'Clear', id: '' }
    ], function (o) { return due === o.id && o.id !== ''; },
      function (o) { document.getElementById('mDue').value = o.id; paintEditChips(); }, true);

    // Linked record: a single dropdown button that opens the full record
    // picker (search, type filter, live preview) - the same flow as "add a
    // link" on a card, instead of a kind chip plus a typed reference.
    var lbtn = document.getElementById('mLinkBtn');
    if (draft.link && draft.link.ref) {
      var lkc = linkKind(draft.link.kind);
      lbtn.innerHTML = '<span class="ptag" style="' + tint(lkc.c) + '">' + lkc.label + '</span> ' +
        '<span class="pname">' + esc(draft.link.ref) + '</span>';
    } else {
      // Same words and same ghost style as the link cell on the task list,
      // so "Add link..." means one thing everywhere.
      lbtn.innerHTML = '<span class="pname ghost">Add link...</span>';
    }
    // Keep the hidden ref in step with the draft so Save and "Open it" (which
    // both read it) stay correct without a visible input.
    document.getElementById('mLinkRef').value = draft.link ? draft.link.ref : '';
    document.getElementById('mLinkOpen').style.display = (draft.link && draft.link.ref) ? '' : 'none';

    var sp = s.spawn || [];
    document.getElementById('mSpawn').textContent = sp.length
      ? 'Reaching ' + s.name + ' also creates: ' + fmtList(sp)
      : '';
    document.getElementById('mRepNote').textContent = draft.rep
      ? describeRepeat({ rep: draft.rep, due: document.getElementById('mDue').value })
      : '';
  }
  document.getElementById('mDue').addEventListener('change', paintEditChips);
  Array.prototype.forEach.call(document.querySelectorAll('#mVis button'), function (b) {
    b.addEventListener('click', function (e) {
      e.preventDefault();
      draft.vis = b.dataset.vis === 'private' ? 'private' : 'public';
      paintEditChips();
    });
  });

  var paintStageBtn = pickButton('mStageBtn',
    function () { return stagesOfJob(editing ? editing.job : '').map(function (x) { return { label: x.name, id: x.id, color: x.color }; }); },
    function () { var s = stage(draft.st); return { label: s.name, color: s.color }; },
    function (o) { draft.st = o.id; paintEditChips(); });
  var paintPrioBtn = pickButton('mPrioBtn',
    function () { return PRIOS.map(function (x) { return { label: x.label, id: x.key, color: x.c }; }); },
    function () { var p = prio(draft.p); return { label: p.label, color: p.c }; },
    function (o) { draft.p = o.id; paintEditChips(); });
  var paintWhoBtn = pickButton('mWhoBtn',
    function () {
      return Object.keys(PEOPLE).map(function (k) {
        return { label: PEOPLE[k].name, id: k, color: PEOPLE[k].color, ini: PEOPLE[k].ini, raw: true };
      });
    },
    function () { var p = PEOPLE[draft.who]; return p ? { label: p.name, color: p.color, ini: p.ini, raw: true } : null; },
    function (o) { draft.who = o.id; paintEditChips(); });
  var paintRepBtn = pickButton('mRepBtn',
    function () { return REPEATS.map(function (r) { return { label: r.label, id: r.key, color: r.key ? 'cyan' : 'slate' }; }); },
    function () { var r = repeatOf(draft.rep); return { label: r.label, color: r.key ? 'cyan' : 'slate' }; },
    function (o) { draft.rep = o.id; paintEditChips(); });
  document.getElementById('mStageBtn').dataset.head = 'Stage in the run';
  document.getElementById('mPrioBtn').dataset.head = 'Priority';
  document.getElementById('mWhoBtn').dataset.head = 'Assign to';
  document.getElementById('mRepBtn').dataset.head = 'Repeats';
  // The Linked record dropdown is the SAME menu as "Add link..." on a task
  // row - Existing (the full picker) / New (raise one), plus Open / Show
  // beside / Unlink once something is linked. Everything is staged on the
  // draft (Save persists it), so other unsaved edits in the dialog survive.
  document.getElementById('mLinkBtn').addEventListener('click', function () {
    if (!editing) return;
    var rect = this.getBoundingClientRect();
    var items = [];
    if (draft.link && draft.link.ref) {
      var lk = linkKind(draft.link.kind);
      items.push({ label: 'Open ' + lk.label + ' ' + draft.link.ref, color: lk.c, run: function () { opts.navigate(linkPath(draft.link)); } });
      items.push({ label: 'Show it beside the task', run: function () { showRecordPanel(draft.link.kind, draft.link.ref); } });
      items.push({ label: 'Unlink', cls: 'danger', run: function () { draft.link = null; paintEditChips(); } });
      items.push(null);
    }
    items.push({ label: 'Existing', note: 'pick one', run: function () { openRecordPicker(editing, true); } });
    items.push({ label: 'New', note: 'raise one', run: function () { openNewRecord(editing, true); } });
    renderMenu('Linked record', items, rect.left, rect.bottom + 4);
  });

  /* ---------- comments on a task ---------- */
  function renderTaskComments() {
    var t = editing;
    if (!t) return;
    t.comments = t.comments || [];
    var box = document.getElementById('mComments');
    box.innerHTML = '';
    if (!t.comments.length) {
      box.innerHTML = '<span class="none">No comments yet.</span>';
    } else {
      t.comments.forEach(function (c, i) {
        var el = document.createElement('div');
        el.className = 'tcomment';
        el.innerHTML = '<button class="del" title="Delete">&#10005;</button>' +
          '<span class="who">' + esc(c.who) + '</span><span class="tm">' + when(c) + '</span><br>' +
          renderMentions(c.body);
        el.querySelector('.del').addEventListener('click', function () {
          if (c.id) API.deleteBoardTaskComment(c.id).catch(fail('Could not delete the comment'));
          t.comments.splice(i, 1);
          logIt('Deleted a comment on "' + t.t + '"', t.job, 'task', 'red');
          renderTaskComments(); redrawAll(true);
        });
        box.appendChild(el);
      });
    }
    document.getElementById('mCommentCount').textContent =
      t.comments.length ? '(' + t.comments.length + ')' : '';
  }
  function addTaskComment(t, body) {
    if (!body) return;
    API.addBoardTaskComment(t.id, body).then(function (row) {
      t.comments = t.comments || [];
      t.comments.push(commentFromServer(row));
      var hits = mentionedIn(body);
      hits.forEach(function (k) {
        var target = TEAM.filter(function (x) { return x.who === k; })[0];
        if (target) target.mentions = (target.mentions || 0) + 1;
      });
      logIt('Commented on "' + t.t + '"' +
        (hits.length ? ', mentioning ' + hits.map(function (k) { return PEOPLE[k].name; }).join(' and ') : ''),
        t.job, 'task', 'violet');
      redrawAll();
      if (editing === t) renderTaskComments();
      toast(hits.length ? 'Posted - ' + fmtList(hits.map(function (k) { return PEOPLE[k].name; })) + ' notified' : 'Comment added');
    }).catch(fail('Could not post the comment'));
  }
  document.getElementById('mCommentForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var i = document.getElementById('mCommentBox');
    var v = i.value.trim();
    if (!v || !editing) return;
    addTaskComment(editing, v);
    i.value = '';
    renderTaskComments();
  });
  document.getElementById('mCommentBox').addEventListener('keyup', function (e) {
    if (e.key !== '@') return;
    var inp = this, r = inp.getBoundingClientRect();
    renderMenu('Mention', Object.keys(PEOPLE).map(function (k) {
      return { label: PEOPLE[k].name, run: function () {
        inp.value = inp.value.replace(/@$/, '') + '@' + PEOPLE[k].name + ' '; inp.focus();
      } };
    }), r.left, r.bottom + 4);
  });
  /* ---------- attachments ---------- */
  function fileKind(name, type) {
    var ext = (name.split('.').pop() || '').toLowerCase();
    if ((type || '').indexOf('image') === 0) return { k: 'img', c: 'teal', tag: 'IMG' };
    if ((type || '').indexOf('video') === 0) return { k: 'vid', c: 'violet', tag: 'VID' };
    if (ext === 'pdf') return { k: 'pdf', c: 'red', tag: 'PDF' };
    if (['dwg','dxf'].indexOf(ext) > -1) return { k: 'cad', c: 'indigo', tag: 'CAD' };
    if (['xls','xlsx','csv'].indexOf(ext) > -1) return { k: 'xls', c: 'green', tag: 'XLS' };
    if (['doc','docx'].indexOf(ext) > -1) return { k: 'doc', c: 'blue', tag: 'DOC' };
    return { k: 'file', c: 'slate', tag: (ext || 'FILE').slice(0, 3).toUpperCase() };
  }
  function human(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return fmtFixed(bytes / 1024, 0) + ' KB';
    return fmtFixed(bytes / 1048576, 1) + ' MB';
  }
  function renderFiles(t) {
    var box = document.getElementById('mFiles');
    box.innerHTML = '';
    (t.files || []).forEach(function (f, i) {
      var k = fileKind(f.name, f.type);
      var row = document.createElement('div');
      row.className = 'filerow';
      row.innerHTML =
        (k.k === 'img' && f.url ? '<img class="thumb" src="' + f.url + '" alt="">'
          : '<span class="ic" style="background:var(--c-' + k.c + ')">' + k.tag + '</span>') +
        '<span class="fn">' + esc(f.name) + '</span><span class="sz">' + human(f.size) + '</span>' +
        '<button class="mv del" type="button" title="Remove">&#10005;</button>';
      row.querySelector('.mv').addEventListener('click', function () {
        if (f.fileId) API.deleteTaskFile(f.fileId).catch(fail('Could not remove the file'));
        t.files.splice(i, 1);
        logIt('Removed "' + f.name + '" from "' + t.t + '"', t.job, 'task', 'red');
        renderFiles(t); redrawAll(true);
      });
      if (k.k === 'img' && f.url) {
        row.querySelector('.thumb').style.cursor = 'pointer';
        row.querySelector('.thumb').addEventListener('click', function () { openViewer(f); });
      }
      box.appendChild(row);
    });
    if (!(t.files || []).length) {
      box.innerHTML = '<span class="hint">Nothing attached yet.</span>';
    }
  }
  function takeFiles(t, files) {
    t.files = t.files || [];
    var list = Array.prototype.slice.call(files);
    if (!list.length) return;
    var left = list.length;
    list.forEach(function (f) {
      API.uploadTaskFile(t.id, f).then(function (row) {
        t.files.push(fileFromServer('task', row));
      }).catch(fail('Could not attach ' + f.name)).then(function () {
        if (--left === 0) doneFiles(t, list);
      });
    });
  }
  function doneFiles(t, list) {
    logIt('Attached ' + plural(list.length, 'file') + ' to "' + t.t + '"', t.job, 'task', 'teal');
    renderFiles(t);
    redrawAll(true);
    toast(plural(list.length, 'file') + ' attached');
  }
  document.getElementById('mDrop').addEventListener('click', function () { document.getElementById('mFileInput').click(); });
  document.getElementById('mFileInput').addEventListener('change', function (e) {
    if (editing) takeFiles(editing, e.target.files);
    e.target.value = '';
  });
  ['dragenter','dragover'].forEach(function (ev) {
    document.getElementById('mDrop').addEventListener(ev, function (e) { e.preventDefault(); this.classList.add('hot'); });
  });
  ['dragleave','drop'].forEach(function (ev) {
    document.getElementById('mDrop').addEventListener(ev, function (e) { e.preventDefault(); this.classList.remove('hot'); });
  });
  document.getElementById('mDrop').addEventListener('drop', function (e) {
    if (editing && e.dataTransfer) takeFiles(editing, e.dataTransfer.files);
  });
  /* ---------- the record, alongside the task ---------- */
  function showRecordPanel(kind, ref) {
    var lk = linkKind(kind);
    var r = EXISTING.filter(function (x) { return x.ref === ref; })[0];
    // Records load lazily per job - if this one has not arrived yet,
    // fetch the task's job and repaint once, rather than telling the
    // user a reference that exists "is not in the register yet".
    if (!r && editing && editing.job && !RECORDS_LOADED[editing.job]) {
      loadRecordsFor(editing.job, function () {
        if (document.getElementById('pairWrap').classList.contains('side')) {
          showRecordPanel(kind, ref);
        }
      });
    }
    var panel = document.getElementById('recPanel');
    panel.querySelector('.recpanel-inner').style.setProperty('--rc', 'var(--c-' + lk.c + ')');
    var tag = document.getElementById('recTag');
    tag.textContent = lk.label;
    tag.setAttribute('style', tint(lk.c));
    document.getElementById('recTitle').textContent = r ? r.title : ref;

    document.getElementById('recBody').innerHTML = r
      ? '<span class="mref">' + esc(r.ref) + '</span>' +
        '<dl>' +
          '<dt>Job</dt><dd>' + esc(r.job) + ' &middot; ' + esc(jobName(r.job)) + '</dd>' +
          '<dt>Raised</dt><dd>' + fmt(r.date) + '</dd>' +
          '<dt>Status</dt><dd>' + esc(r.status) + '</dd>' +
          '<dt>With</dt><dd>' + esc(r.party) + '</dd>' +
          '<dt>Module</dt><dd>' + esc(lk.mod) + '</dd>' +
          (r.files ? '<dt>Files</dt><dd>' + r.files + ' attached</dd>' : '') +
        '</dl>' +
        '<div class="rec-body">' + esc(r.body) + '</div>'
      : '<span class="mref">' + esc(ref) + '</span>' +
        '<p class="hint" style="margin-top:10px">This reference is not in the register yet - it will resolve once the record is raised.</p>';

    document.getElementById('recOpenModule').onclick = function () {
      opts.navigate(r ? linkPath({ kind: kind, targetId: r.targetId }) : lk.path);
    };
    document.getElementById('pairWrap').classList.add('side');
  }
  function hideRecordPanel() { document.getElementById('pairWrap').classList.remove('side'); }
  document.getElementById('recClose').addEventListener('click', hideRecordPanel);

  document.getElementById('mLinkOpen').addEventListener('click', function () {
    var ref = document.getElementById('mLinkRef').value.trim();
    if (!draft.link || !ref) { toast('Pick a record type and a reference first'); return; }
    var wrap = document.getElementById('pairWrap');
    if (wrap.classList.contains('side')) { hideRecordPanel(); return; }
    showRecordPanel(draft.link.kind, ref);
  });

  /* ---------- the dialog's four predicting fields ---------- */
  /* The quick-add job picker. Bare numbers are unmemorable, so the list
     carries the client and the work, my own jobs come first, and the chip
     beside the box names whatever is currently typed. */
  function jobOptions(preferMine) {
    var mine = me().jobs || [];
    var list = JOBS.slice();
    if (preferMine) {
      list.sort(function (a, b) {
        return (mine.indexOf(b.code) > -1 ? 1 : 0) - (mine.indexOf(a.code) > -1 ? 1 : 0);
      });
    }
    return list.map(function (j) {
      return {
        label: j.code + '  ' + j.client,
        value: j.code,
        note: mine.indexOf(j.code) > -1 ? 'on my day' : j.name,
        color: clientTone(j.client)
      };
    });
  }

  makeCombo('mSummary', function () {
    // Suggest from what the team already writes, plus the stage templates.
    var seen = {}, out = [];
    STAGES.forEach(function (s) {
      (s.spawn || []).forEach(function (n) {
        if (!seen[n]) { seen[n] = 1; out.push({ label: n, note: s.name, color: s.color }); }
      });
    });
    TASKS.forEach(function (t) {
      if (!seen[t.t]) { seen[t.t] = 1; out.push({ label: t.t, note: t.job }); }
    });
    return out;
  });
  makeCombo('mJob', function () { return jobOptions(false); }, function () { paintEditChips(); });
  makeCombo('mWait', function () {
    return WAITS.map(function (w) { return { label: w, color: 'amber' }; });
  });
  // (The manual reference autocomplete is gone: the Linked record dropdown
  // now opens the full record picker, so there is no free-text ref to
  // complete.)

  function closeEdit() { hideRecordPanel(); scrim.classList.remove('open'); editing = null; }
  document.getElementById('mClose').addEventListener('click', closeEdit);
  document.getElementById('mCancel').addEventListener('click', closeEdit);
  scrim.addEventListener('click', function (e) {
    if (e.target === scrim && Date.now() - openedAt > 400) closeEdit();
  });
  document.getElementById('mSave').addEventListener('click', function () {
    if (!editing) return;
    var t = editing, changes = [], patch = {};
    var v = document.getElementById('mSummary').value.trim();
    if (v && v !== t.t) { changes.push('renamed to "' + v + '"'); t.t = v; patch.title = v; }
    var nj = document.getElementById('mJob').value.trim();
    var jm = JOBS.filter(function (x) { return x.code === nj; })[0];
    if (jm && nj !== t.job) { changes.push('moved to job ' + nj); t.job = nj; patch.project_id = jm.id; }
    if ((draft.rep || '') !== (t.rep || '')) {
      changes.push(draft.rep ? 'repeats ' + repeatOf(draft.rep).label.toLowerCase() : 'no longer repeats');
      t.rep = draft.rep;
      patch.repeat_rule = draft.rep || '';
    }
    if (draft.who !== t.who) { changes.push('assigned to ' + PEOPLE[draft.who].name); t.who = draft.who; patch.assignee_id = draft.who; }
    if (draft.p !== t.p) { changes.push('priority ' + prio(draft.p).label); t.p = draft.p; patch.priority = draft.p; }
    var nd = document.getElementById('mDue').value || null;
    if (nd !== t.due) { changes.push(nd ? 'due ' + fmt(nd) : 'due date cleared'); t.due = nd; patch.due = nd || ''; }
    var nwait = document.getElementById('mWait').value.trim();
    var learnWait = null;
    if (nwait !== t.wait) {
      changes.push(nwait ? 'waiting on ' + nwait : 'waiting cleared');
      t.wait = nwait;
      patch.waiting_on = nwait;
      // Do NOT quietly adopt whatever was typed - a half-finished word
      // would become a permanent reason for the whole team. Offer it.
      if (nwait && WAITS.indexOf(nwait) === -1) learnWait = nwait;
    }
    var nn = document.getElementById('mNotes').value;
    if (nn !== t.notes) { changes.push('notes updated'); t.notes = nn; patch.notes = nn; }
    var lref = document.getElementById('mLinkRef').value.trim();
    var lmatch = EXISTING.filter(function (r) { return r.ref === lref; })[0];
    var newLink = (draft.link && lref)
      ? { kind: draft.link.kind, ref: lref, targetId: lmatch ? lmatch.targetId : (t.link && t.link.ref === lref ? t.link.targetId : '') }
      : null;
    var oldRef = t.link ? t.link.kind + ':' + t.link.ref : '';
    var newRef = newLink ? newLink.kind + ':' + newLink.ref : '';
    if (oldRef !== newRef) {
      changes.push(newLink ? 'linked to ' + linkKind(newLink.kind).label + ' ' + lref : 'link removed');
      t.link = newLink;
      patch.link_kind = newLink ? newLink.kind : '';
      patch.link_ref = newLink ? newLink.ref : '';
      patch.link_target_id = newLink ? (newLink.targetId || '') : '';
    }
    logIt(changes.length ? 'Edited "' + t.t + '": ' + fmtList(changes) : 'Opened "' + t.t + '" without changes', t.job, 'task', 'blue');
    if (Object.keys(patch).length) pushTaskField(t, patch);
    // Visibility on its own call - it can be refused, and a refusal must
    // roll the glyph back (see setVisibility).
    if ((draft.vis || 'public') !== (t.vis || 'public')) { changes.push('made ' + draft.vis); setVisibility(t, draft.vis); }
    // Stage last: the move endpoint owns templates and recurrence.
    if (draft.st !== t.st) { changes.push('stage ' + stage(draft.st).name); moveToStage(t, draft.st); }
    closeEdit();
    redrawAll();
    if (learnWait) {
      toast('Task saved. Keep "' + learnWait + '" as a reason?', 'it is on this task either way', function () {
        WAITS.push(learnWait);
        logIt('Added waiting reason "' + learnWait + '"', 'Settings', 'config', 'amber');
        saveWaits(); toast('Added to the list');
      });
    } else {
      toast(changes.length ? 'Task saved' : 'Nothing changed');
    }
  });
  document.getElementById('mDelete').addEventListener('click', function () {
    if (!editing) return;
    var t = editing, at = TASKS.indexOf(t);
    TASKS.splice(at, 1);
    logIt('Deleted "' + t.t + '"', t.job, 'task', 'red');
    API.deleteBoardTask(t.id).catch(fail('Could not delete the task'));
    closeEdit();
    redrawAll();
    toast('Task deleted', null, function () {
      API.restoreBoardTask(t.id).then(function () {
        TASKS.splice(at, 0, t);
        logIt('Restored "' + t.t + '"', t.job, 'task', 'green');
        redrawAll();
        toast('Task restored');
      }).catch(fail('Could not restore the task'));
    });
  });
  docListen(document, 'keydown', function (e) {
    if (e.key === 'Escape' && scrim.classList.contains('open')) closeEdit();
  });

  /* ---------- log ---------- */
  function renderLog() {
    var body = document.getElementById('logBody');
    var f = document.getElementById('logFilter').value;
    body.innerHTML = '';
    var rows = LOG.filter(function (l) { return !f || l.kind === f; });
    rows.slice(0, 60).forEach(function (l) {
      body.innerHTML += '<tr data-menu="logrow" data-where="' + esc(l.where) + '" data-label="' + hhmm(l.at) + '"><td class="tm">' + hhmm(l.at) + '</td>' +
        '<td style="white-space:nowrap">' + esc(l.who) + '</td>' +
        '<td><span class="logdot" style="background:var(--c-' + (l.c || 'slate') + ')"></span>' + esc(l.what) + '</td>' +
        '<td class="act" style="color:var(--muted);font-family:\'IBM Plex Mono\',monospace;font-size:11.5px">' + esc(l.where) + '</td></tr>';
    });
    if (!rows.length) body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:16px">Nothing logged yet.</td></tr>';
    document.getElementById('logMeta').textContent = LOG.length + ' entries today';
    // Left-click a log line jumps to the job it happened on.
    Array.prototype.forEach.call(body.querySelectorAll('tr[data-where]'), function (tr) {
      tr.addEventListener('click', function () {
        var w = tr.dataset.where;
        if (!w || !JOBS.some(function (j) { return j.code === w; })) { toast('No job on that entry'); return; }
        document.getElementById('jobFilter').value = w;
        document.getElementById('tile-tasks').setAttribute('open-state', '1');
        redrawAll(true);
        toast('Filtered to ' + w);
      });
    });
  }
  document.getElementById('logFilter').addEventListener('change', function (e) { e.stopPropagation(); renderLog(); });
  document.getElementById('logFilter').addEventListener('click', function (e) { e.stopPropagation(); });

  /* ---------- shared pickers ---------- */
  /** Small one-field prompt in the info dialog (the browser's own prompt()
   *  can be blocked, and a popover is a button list). */
  function askFor(title, placeholder, value, cb) {
    openInfo(title,
      '<input type="text" id="askInput" placeholder="' + esc(placeholder) + '" value="' + esc(value || '') + '" style="width:100%">',
      function () {
        var v = document.getElementById('askInput').value.trim();
        if (!v) { toast('Type something first'); return; }
        closeInfo(); cb(v);
      }, 'Save');
    setTimeout(function () {
      var i = document.getElementById('askInput');
      if (i) { i.focus(); i.select();
        i.addEventListener('keydown', function (e) { if (e.key === 'Enter') document.getElementById('infoAction').click(); });
      }
    }, 40);
  }

  /** Editable list manager: rename in place, remove, add. */
  function manageList(title, list, onSave) {
    function body() {
      return '<div class="filelist" id="mgrRows">' + list.map(function (v, i) {
        return '<div class="filerow"><input type="text" class="fn" data-i="' + i + '" value="' + esc(v) + '" ' +
          'style="border:1px solid var(--hairline);border-radius:6px;padding:6px 9px;font-size:13px;background:var(--surface);color:var(--ink)">' +
          '<button class="mv del" type="button" data-del="' + i + '" title="Remove">&#10005;</button></div>';
      }).join('') + '</div>' +
      (list.length ? '' : '<span class="hint">The list is empty.</span>') +
      '<button class="btn btn-quiet" id="mgrAdd" style="margin-top:10px">+ Add an entry</button>';
    }
    function wire() {
      var box = document.getElementById('infoBody');
      Array.prototype.forEach.call(box.querySelectorAll('[data-del]'), function (b) {
        b.addEventListener('click', function () {
          list.splice(parseInt(b.dataset.del, 10), 1);
          box.innerHTML = body(); wire();
        });
      });
      Array.prototype.forEach.call(box.querySelectorAll('input[data-i]'), function (inp) {
        inp.addEventListener('input', function () { list[parseInt(inp.dataset.i, 10)] = inp.value; });
      });
      var add = document.getElementById('mgrAdd');
      if (add) add.addEventListener('click', function () {
        list.push('New entry');
        box.innerHTML = body(); wire();
        var last = box.querySelectorAll('input[data-i]');
        if (last.length) { last[last.length - 1].focus(); last[last.length - 1].select(); }
      });
    }
    openInfo(title, body(), function () {
      for (var i = list.length - 1; i >= 0; i--) if (!String(list[i]).trim()) list.splice(i, 1);
      closeInfo();
      if (onSave) onSave();
    }, 'Done');
    setTimeout(wire, 30);
  }

  /** The Waiting-on picker, used by the cell and the right-click menu. */
  function waitItems(t) {
    return WAITS.map(function (w) {
      return { label: w, color: 'amber', run: function () { setWait(t, w); } };
    }).concat([
      { label: 'Nothing - clear it', run: function () { setWait(t, ''); } },
      null,
      { label: 'Add a new reason...', run: function () {
          askFor('New waiting reason', 'e.g. Council inspection', '', function (v) {
            if (WAITS.indexOf(v) === -1) WAITS.push(v);
            logIt('Added waiting reason "' + v + '"', 'Settings', 'config', 'amber');
            setWait(t, v); saveWaits();
          });
        } },
      { label: 'Edit the list...', run: function () {
          manageList('Waiting-on reasons', WAITS, function () {
            logIt('Edited the waiting-on list', 'Settings', 'config', 'slate');
            saveWaits(); redrawAll(true); toast('List saved');
          });
        } }
    ]);
  }

  /* ---------- record picker (full window) ----------
     A reference on its own tells you nothing, so this shows what each
     record actually is - title, party, status, and the text - before you
     commit to linking it. */
  var pickScrim = document.getElementById('pickScrim');
  var pickState = { task: null, sel: null, kind: '', scope: true, q: '' };

  function openRecordPicker(t, fromEdit) {
    pickState = { task: t, sel: null, kind: '', scope: true, q: '', fromEdit: !!fromEdit };
    document.getElementById('pickFor').textContent = t.t + '  ' + t.job;
    document.getElementById('pickSearch').value = '';
    document.getElementById('pickScope').setAttribute('aria-pressed', 'true');
    document.getElementById('pickScope').textContent = 'This job only';
    chipRow(document.getElementById('pickKinds'),
      [{ label: 'All types', k: '' }].concat(LINK_KINDS.map(function (lk) { return { label: lk.label, k: lk.k, color: lk.c }; })),
      function (o) { return pickState.kind === o.k; },
      function (o) { pickState.kind = o.k; paintPicker(); }, true);
    document.getElementById('pickList').innerHTML = '<div class="pv-empty">Loading the registers...</div>';
    pickScrim.classList.add('open');
    loadRecordsFor(t.job, paintPicker);
    setTimeout(function () { document.getElementById('pickSearch').focus(); }, 40);
  }
  function closePicker() { pickScrim.classList.remove('open'); }

  function pickRows() {
    var t = pickState.task;
    return EXISTING.filter(function (r) {
      if (pickState.kind && r.kind !== pickState.kind) return false;
      if (pickState.scope && r.job !== t.job) return false;
      if (pickState.q) {
        var hay = (r.ref + ' ' + r.title + ' ' + r.party + ' ' + r.status + ' ' + r.job).toLowerCase();
        if (hay.indexOf(pickState.q.toLowerCase()) === -1) return false;
      }
      return true;
    });
  }
  function paintPicker() {
    var rows = pickRows();
    var list = document.getElementById('pickList');
    list.innerHTML = '';
    rows.forEach(function (r) {
      var lk = linkKind(r.kind);
      var el = document.createElement('div');
      el.className = 'prow';
      if (pickState.sel && pickState.sel.ref === r.ref) el.setAttribute('aria-selected', 'true');
      el.innerHTML =
        '<span class="ptag" style="' + tint(lk.c) + '">' + lk.label + '</span>' +
        '<span class="pmain">' +
          '<span class="ptitle">' + esc(r.title) + '</span>' +
          '<span class="pmeta">' + r.ref + '  &middot;  ' + r.job + '  &middot;  ' + fmt(r.date) + '</span>' +
          '<span class="pstatus">' + esc(r.status) + '  &middot;  ' + esc(r.party) + '</span>' +
        '</span>';
      el.addEventListener('click', function () { pickState.sel = r; paintPicker(); });
      el.addEventListener('dblclick', function () { pickState.sel = r; confirmPick(); });
      list.appendChild(el);
    });
    if (!rows.length) {
      list.innerHTML = '<div class="pv-empty">Nothing matches. Try widening to all jobs, or raise a new record.</div>';
    }
    document.getElementById('pickCount').textContent =
      rows.length + ' record' + (rows.length === 1 ? '' : 's') + (pickState.scope ? ' on ' + pickState.task.job : ' across all jobs');

    var view = document.getElementById('pickView');
    var r = pickState.sel;
    if (!r) {
      view.innerHTML = '<div class="pv-empty">Pick a record on the left to see what it is.</div>';
    } else {
      var lk2 = linkKind(r.kind);
      view.innerHTML =
        '<span class="ptag" style="' + tint(lk2.c) + ';display:inline-block;margin-bottom:8px">' + lk2.label + '</span>' +
        '<h4>' + esc(r.title) + '</h4>' +
        '<span class="pv-ref">' + r.ref + '</span>' +
        '<dl>' +
          '<dt>Job</dt><dd>' + r.job + ' &middot; ' + esc(jobName(r.job)) + '</dd>' +
          '<dt>Raised</dt><dd>' + fmt(r.date) + '</dd>' +
          '<dt>Status</dt><dd>' + esc(r.status) + '</dd>' +
          '<dt>With</dt><dd>' + esc(r.party) + '</dd>' +
          '<dt>Module</dt><dd>' + esc(lk2.mod) + '</dd>' +
          (r.files ? '<dt>Files</dt><dd>' + r.files + ' attached</dd>' : '') +
        '</dl>' +
        '<div class="pv-body">' + esc(r.body) + '</div>';
    }
    document.getElementById('pickConfirm').disabled = !pickState.sel;
  }
  function confirmPick() {
    var r = pickState.sel, t = pickState.task;
    if (!r || !t) return;
    if (pickState.fromEdit) {
      // Chosen inside the edit dialog: stage it on the draft and let Save
      // persist it, so any other unsaved edits on the card survive. No
      // commit here, and the dialog is NOT re-opened (which would reset it).
      draft.link = { kind: r.kind, ref: r.ref, targetId: r.targetId || '' };
      closePicker();
      paintEditChips();
      return;
    }
    t.link = { kind: r.kind, ref: r.ref, targetId: r.targetId || '' };
    pushTaskField(t, { link_kind: r.kind, link_ref: r.ref, link_target_id: r.targetId || '' });
    logIt('Linked "' + t.t + '" to ' + linkKind(r.kind).label + ' ' + r.ref, t.job, 'task', linkKind(r.kind).c);
    closePicker();
    redrawAll();
    if (editing === t) openEdit(t);
    toast('Linked to ' + r.ref, r.title);
  }
  document.getElementById('pickSearch').addEventListener('input', function () { pickState.q = this.value; paintPicker(); });
  document.getElementById('pickScope').addEventListener('click', function () {
    pickState.scope = !pickState.scope;
    this.setAttribute('aria-pressed', pickState.scope ? 'true' : 'false');
    this.textContent = pickState.scope ? 'This job only' : 'All jobs';
    if (!pickState.scope) {
      document.getElementById('pickList').innerHTML = '<div class="pv-empty">Loading the other jobs...</div>';
      loadAllRecords(paintPicker);
    } else paintPicker();
  });
  document.getElementById('pickConfirm').addEventListener('click', confirmPick);
  document.getElementById('pickCancel').addEventListener('click', closePicker);
  document.getElementById('pickClose').addEventListener('click', closePicker);
  pickScrim.addEventListener('click', function (e) { if (e.target === pickScrim) closePicker(); });

  /* ---------- raise a new record ---------- */
  var newRecScrim = document.getElementById('newRecScrim');
  var newRecState = { task: null, kind: 'rfi', fromEdit: false };
  function openNewRecord(t, fromEdit) {
    newRecState = { task: t, kind: 'rfi', fromEdit: !!fromEdit };
    document.getElementById('newRecTitle').value = '';
    document.getElementById('newRecJob').value = t.job + ' - ' + jobName(t.job);
    paintNewRec();
    newRecScrim.classList.add('open');
    setTimeout(function () { document.getElementById('newRecTitle').focus(); }, 40);
  }
  function paintNewRec() {
    var t = newRecState.task;
    // An email cannot be "raised" - it arrives. Every register kind can.
    chipRow(document.getElementById('newRecKinds'),
      LINK_KINDS.filter(function (lk) { return lk.k !== 'mail'; })
        .map(function (lk) { return { label: lk.k === 'request' ? 'Work request' : lk.label, k: lk.k, color: lk.c, note: lk.mod }; }),
      function (o) { return newRecState.kind === o.k; },
      function (o) { newRecState.kind = o.k; paintNewRec(); });
    var lk = linkKind(newRecState.kind);
    document.getElementById('newRecPreview').textContent = lk.k === 'request'
      ? 'Work request on ' + t.job + ' - opens the Work requests module, which asks for the department and mints the number'
      : lk.label + ' on ' + t.job + ' - the register mints the number when it lands in ' + lk.mod;
  }
  document.getElementById('newRecSave').addEventListener('click', function () {
    var t = newRecState.task;
    var lk = linkKind(newRecState.kind);
    var pid = jobIdOf(t.job);
    if (!pid) { toast('That task has no job to raise against'); return; }
    if (lk.k === 'request') {
      // The module owns the raise dialog (department, type, quote) - hand
      // over on the right job rather than half-raising it from here.
      newRecScrim.classList.remove('open');
      opts.navigate(raiseRequestPath(pid));
      return;
    }
    var title = document.getElementById('newRecTitle').value.trim();
    if (!title) { toast('Give it a title first'); return; }
    API.raiseRegisterItem(pid, REG_KIND[lk.k], title).then(function (row) {
      var rec = recFromRegister(row);
      EXISTING.unshift(rec);
      if (newRecState.fromEdit) {
        // Raised from inside the edit dialog: stage the link on the draft
        // and let Save persist it - re-opening the dialog would wipe the
        // other unsaved edits.
        draft.link = { kind: rec.kind, ref: rec.ref, targetId: rec.targetId };
        logIt('Raised ' + lk.label + ' ' + rec.ref + ' from "' + t.t + '"', t.job, 'task', lk.c);
        newRecScrim.classList.remove('open');
        paintEditChips();
        toast('Raised ' + rec.ref, 'linked once you save the task');
        return;
      }
      t.link = { kind: rec.kind, ref: rec.ref, targetId: rec.targetId };
      pushTaskField(t, { link_kind: rec.kind, link_ref: rec.ref, link_target_id: rec.targetId });
      logIt('Raised ' + lk.label + ' ' + rec.ref + ' from "' + t.t + '"', t.job, 'task', lk.c);
      newRecScrim.classList.remove('open');
      redrawAll();
      if (editing === t) openEdit(t);
      toast('Raised ' + rec.ref, 'created in ' + lk.mod);
    }).catch(fail('Could not raise the ' + lk.label));
  });
  document.getElementById('newRecCancel').addEventListener('click', function () { newRecScrim.classList.remove('open'); });
  document.getElementById('newRecClose').addEventListener('click', function () { newRecScrim.classList.remove('open'); });
  newRecScrim.addEventListener('click', function (e) { if (e.target === newRecScrim) newRecScrim.classList.remove('open'); });

  /** Link menu: Add a link -> New / Existing -> a full window. */
  function linkItems(t) {
    var out = [];
    if (t.link) {
      var lk = linkKind(t.link.kind);
      out.push({ label: 'Open ' + lk.label + ' ' + t.link.ref, color: lk.c, run: function () {
        opts.navigate(linkPath(t.link));
      } });
      out.push({ label: 'Show it beside the task', run: function () {
        if (editing !== t) openEdit(t);
        showRecordPanel(t.link.kind, t.link.ref);
      } });
      out.push({ label: 'Unlink', cls: 'danger', run: function () {
        t.link = null;
        pushTaskField(t, { link_kind: '', link_ref: '', link_target_id: '' });
        logIt('Unlinked "' + t.t + '"', t.job, 'task', 'red'); redrawAll(); toast('Unlinked');
      } });
      out.push(null);
    }
    out.push({ label: 'Existing', note: 'pick one', run: function () { openRecordPicker(t); } });
    out.push({ label: 'New', note: 'raise one', run: function () { openNewRecord(t); } });
    return out;
  }

  /* ---------- menus ---------- */
  function rowMenu(el) {
    var t = taskById(el.dataset.id);
    if (!t) return [];
    return [
      { label: 'Edit task...', key: 'dbl click', run: function () { openEdit(t); } },
      { label: (t.comments && t.comments.length) ? 'Comments (' + t.comments.length + ')...' : 'Add a comment...',
        color: 'violet', run: function () {
          askFor('Comment on "' + t.t + '"', 'Type @ to mention someone', '', function (v) {
            addTaskComment(t, v);
          });
        } },
      { label: 'Open job ' + t.job, run: function () {
          var jid = jobIdOf(t.job);
          if (jid) opts.navigate('/projects/' + jid); else toast('Unknown job');
        } },
      { label: t.vis === 'private' ? 'Make public' : 'Make private',
        color: t.vis === 'private' ? 'green' : 'amber',
        note: t.vis === 'private' ? 'the whole team will see it' : 'only you, the assignee and admins',
        run: function () { setVisibility(t, t.vis === 'private' ? 'public' : 'private'); } },
      null,
      { label: 'Move to...', sub: function (x, y) {
          popover(x, y, 'Move to', stagesOfJob(t.job).map(function (s) {
            return { label: s.name, color: s.color, run: function () { moveToStage(t, s.id); } };
          }));
        } },
      { label: 'Repeats...', sub: function (x, y) {
          popover(x, y, 'Repeat', REPEATS.map(function (r) {
            return { label: r.label + (t.rep === r.key ? '  (current)' : ''), run: function () {
              t.rep = r.key;
              logIt('"' + t.t + '" ' + (r.key ? 'repeats ' + r.label.toLowerCase() : 'no longer repeats'), t.job, 'task', 'cyan');
              pushTaskField(t, { repeat_rule: r.key });
              redrawAll(); toast(r.key ? 'Repeats ' + r.label.toLowerCase() : 'Repeat removed');
            } };
          }));
        } },
      { label: 'Waiting on...', sub: function (x, y) { renderMenu('Waiting on', waitItems(t), x, y); } },
      { label: t.link ? 'Linked record...' : 'Add a link...', sub: function (x, y) {
          renderMenu(t.link ? 'Linked record' : 'Add a link', linkItems(t), x, y);
        } },
      { label: 'Move to job...', sub: function (x, y) {
          renderMenu('Move to job', JOBS.map(function (j) {
            return { label: j.code, note: j.client, color: clientTone(j.client), run: function () {
              t.job = j.code; logIt('Moved "' + t.t + '" to job ' + j.code, j.code, 'task', CLIENT_COLOR[j.client]);
              pushTaskField(t, { project_id: j.id });
              redrawAll(); toast('Now on ' + j.code);
            } };
          }), x, y, { search: 'Search jobs...' });
        } },
      { label: 'Attachments...', run: function () {
          openEdit(t);
          setTimeout(function () { document.getElementById('mDrop').scrollIntoView({ block: 'center' }); }, 60);
        } },
      { label: t.due ? 'Due date...' : 'Set a date...', note: t.due ? fmt(t.due) : 'no date yet', sub: function (x, y) {
          // The same choices as the Due cell offers, so the menu never
          // knows less than a left-click does.
          popover(x, y, 'Due', [
            { label: 'Today', run: function () { setDue(t, TODAY); } },
            { label: 'Tomorrow', run: function () { setDue(t, TOMORROW); } },
            { label: 'End of the week', run: function () { setDue(t, ENDWEEK); } },
            { label: 'Next week', run: function () { setDue(t, NEXTWEEK); } },
            { label: 'Pick a date...', run: function () { openEdit(t); document.getElementById('mDue').focus(); } },
            null,
            { label: t.due ? 'Clear the date' : 'No date', run: function () { if (t.due) setDue(t, null); } }
          ]);
        } },
      { label: 'Reassign...', sub: function (x, y) {
          popover(x, y, 'Assign to', Object.keys(PEOPLE).map(function (kk) {
            return { label: PEOPLE[kk].name, run: function () {
              t.who = kk; logIt('Assigned "' + t.t + '" to ' + PEOPLE[kk].name, t.job, 'task', 'blue');
              pushTaskField(t, { assignee_id: kk });
              redrawAll(); toast('Assigned to ' + PEOPLE[kk].name);
            } };
          }));
        } },
      null,
      { label: 'Mark closed out', run: function () { markDone(t); } },
      { label: 'Add to my standup today', run: function () {
          var ta = document.getElementById('fToday');
          ta.value = (ta.value ? ta.value.replace(/\s*$/, '') + ' ' : '') + t.t + '.';
          me().t = ta.value;
          logIt('Added "' + t.t + '" to their standup', 'Standup', 'standup', 'blue');
          queueEntrySave();
          redrawAll();
          toast('Added to your Today line');
        } },
      { label: 'Filter to job ' + t.job, run: function () {
          document.getElementById('jobFilter').value = t.job; redrawAll(true); toast('Filtered to ' + t.job);
        } },
      null,
      { label: 'Delete task', cls: 'danger', run: function () {
          var at = TASKS.indexOf(t);
          TASKS.splice(at, 1);
          logIt('Deleted "' + t.t + '"', t.job, 'task', 'red');
          API.deleteBoardTask(t.id).catch(fail('Could not delete the task'));
          redrawAll();
          toast('Task deleted', null, function () {
            API.restoreBoardTask(t.id).then(function () {
              TASKS.splice(at, 0, t); redrawAll(); toast('Task restored');
            }).catch(fail('Could not restore the task'));
          });
        } }
    ];
  }
  function cardMenu(el) {
    var who = el.dataset.who;
    return [
      { label: 'Comment on this update', run: function () {
          var box = el.querySelector('.comments');
          if (!box) { toast('Nothing posted yet'); return; }
          Array.prototype.forEach.call(box.querySelectorAll('.comment, [data-reply]'), function (n) { n.style.display = ''; });
          box.dataset.open = '1';
          var i = box.querySelector('input'); if (i) i.focus();
        } },
      { label: 'See their week', run: function () { document.getElementById('viewWeek').click(); } },
      { label: 'Only their tasks', run: function () {
          document.getElementById('tile-tasks').setAttribute('open-state', '1');
          setPeople([who]);
          toast('Tasks filtered to ' + PEOPLE[who].name);
        } },
      { label: 'Give them a task', run: function () {
          createSingleTask({ title: 'New task', project_id: defaultJobId(), assignee_id: who }, true);
        } },
      null,
      { label: 'Copy update as text', run: function () {
          if (navigator.clipboard) navigator.clipboard.writeText(el.innerText.replace(/\n{2,}/g, '\n').trim()).catch(function () {});
          toast('Copied');
        } }
    ];
  }
  /** Renaming a job number has to carry everything with it - my day, every
   *  task, and every record reference - or the job splits in two. */
  function renumberJob(j, newCode) {
    var old = j.code;
    if (!newCode || newCode === old) return;
    if (JOBS.some(function (x) { return x.code === newCode; })) { toast('That number is already used by another job'); return; }
    API.patchProject(j.id, { project_code: newCode }).then(function () {
      j.code = newCode;
      var touched = 0;
      // Tasks key on the project GUID server-side; only the display code
      // moves here, so nothing can split.
      TASKS.forEach(function (t) { if (t.job === old) { t.job = newCode; touched++; } });
      EXISTING.forEach(function (r) { if (r.job === old) r.job = newCode; });
      TEAM.forEach(function (p) { if (p.jobs) p.jobs = p.jobs.map(function (c) { return c === old ? newCode : c; }); });
      ['jobFilter'].forEach(function (id) {
        var sel = document.getElementById(id);
        Array.prototype.forEach.call(sel.options, function (o) {
          if (o.value === old) { o.value = newCode; o.textContent = o.textContent.replace(old, newCode); }
        });
        if (sel.value === old) sel.value = newCode;
      });
      logIt('Changed the job number ' + old + ' to ' + newCode + ' (' + plural(touched, 'task') + ' followed)', newCode, 'config', 'blue');
      redrawAll();
      toast('Job is now ' + newCode, plural(touched, 'task') + ' followed it');
    }).catch(fail('Could not change the job number'));
  }

  function jobMenu(el) {
    var code = el.dataset.label;
    var j = job(code) || { code: code, client: '', name: '' };
    var mine = me().jobs.indexOf(code) !== -1;
    // The catalogue falls back to a slice of the project's own id when no
    // the job number has been set - that shape means "not numbered yet".
    var auto = !!(j.id && j.id.indexOf(code) === 0);
    function patchName() {
      return API.patchProject(j.id, { name: (j.client ? j.client + ' - ' : '') + j.name });
    }
    return [
      { label: mine ? 'Take off my day' : 'Add to my day today', color: mine ? 'slate' : 'blue', run: function () {
          var i = me().jobs.indexOf(code);
          if (i === -1) me().jobs.push(code); else me().jobs.splice(i, 1);
          logIt((i === -1 ? 'Added ' : 'Removed ') + code + ' on their standup', code, 'standup', 'blue');
          queueEntrySave();
          redrawAll();
        } },
      null,
      { label: auto ? 'Set the job number...' : 'Change the job number...', color: auto ? 'amber' : null,
        note: auto ? 'not set' : code, run: function () {
          askFor(auto ? 'Set the job number' : 'Change the job number',
            'e.g. 26910', auto ? '' : code, function (v) { renumberJob(j, v.trim()); });
        } },
      { label: 'Rename the job...', run: function () {
          askFor('Job description', 'What the job is', j.name, function (v) {
            j.name = v;
            patchName().then(function () {
              logIt('Renamed job ' + code, code, 'config', 'blue'); redrawAll(); toast('Job renamed');
            }).catch(fail('Could not rename the job'));
          });
        } },
      { label: 'Change the client...', run: function () {
          askFor('Client', 'Who it is for', j.client, function (v) {
            j.client = v;
            if (!CLIENT_COLOR[v]) CLIENT_COLOR[v] = COLORS[Object.keys(CLIENT_COLOR).length % COLORS.length];
            patchName().then(function () {
              logIt('Changed the client on ' + code, code, 'config', 'blue'); redrawAll(); toast('Client updated');
            }).catch(fail('Could not change the client'));
          });
        } },
      null,
      { label: 'Open the job', run: function () { opts.navigate('/projects/' + j.id); } },
      { label: "The job's registers", color: 'violet', run: function () { opts.navigate('/comms-intelligence'); } },
      { label: 'Its email thread', color: 'cyan', run: function () { opts.navigate('/comms-intelligence'); } },
      null,
      { label: 'Raise an RFI', color: 'violet', run: function () { quickRaise(code, 'rfi'); } },
      { label: 'Raise an RFQ', color: 'indigo', run: function () { quickRaise(code, 'rfq'); } },
      { label: 'Raise a variation', color: 'orange', run: function () { quickRaise(code, 'vo'); } },
      { label: 'Log a toolbox talk', color: 'lime', run: function () { quickRaise(code, 'tbx'); } },
      { label: 'Raise a work request', color: 'rose', note: 'engineering, drafting, workshop...', run: function () {
          opts.navigate(raiseRequestPath(j.id));
        } },
      null,
      { label: 'Only this job\'s tasks', run: function () {
          document.getElementById('jobFilter').value = code;
          document.getElementById('tile-tasks').setAttribute('open-state', '1');
          redrawAll(true); toast('Filtered to ' + code);
        } },
      { label: 'Add a task on this job', color: 'green', run: function () {
          createSingleTask({ title: 'New task', project_id: j.id, assignee_id: ME_ID }, true);
        } },
      { label: 'Copy the job number', run: function () {
          if (navigator.clipboard) navigator.clipboard.writeText(code).catch(function () {});
          toast('Copied ' + code);
        } }
    ];
  }
  function quickRaise(code, kind) {
    var lk = linkKind(kind);
    askFor('Raise a ' + lk.label + ' on ' + code, 'What is it about?', '', function (title) {
      var pid = jobIdOf(code);
      if (!pid) { toast('Unknown job'); return; }
      API.raiseRegisterItem(pid, REG_KIND[kind], title).then(function (row) {
        var rec = recFromRegister(row);
        EXISTING.unshift(rec);
        logIt('Raised ' + lk.label + ' ' + rec.ref, code, 'task', lk.c);
        redrawAll();
        toast('Raised ' + rec.ref, 'created in ' + lk.mod);
      }).catch(fail('Could not raise the ' + lk.label));
    });
  }
  /* A task is a task wherever you meet it - on a member's card, in the
     list, or on a board card - so it gets the same full menu. Anything
     less means remembering which surface can do what. */
  function taskLineMenu(el) { return rowMenu(el); }
  function cellMenu(el) {
    return [
      { label: 'Open that day', run: function () { document.getElementById('viewToday').click(); toast('Opened ' + el.dataset.label); } },
      { label: 'Copy the update', run: function () {
          if (navigator.clipboard) navigator.clipboard.writeText(el.innerText.trim()).catch(function () {});
          toast('Copied');
        } }
    ];
  }
  /* Menus for everything else on the page, so right-click always answers. */
  function activityMenu(el) {
    var who = el.dataset.who;
    var mine = who === ME_ID;
    return ACTS.map(function (a) {
      var on = mine && me().acts && me().acts.indexOf(a.id) !== -1;
      return { label: (on ? 'Remove ' : 'Set ') + a.name, run: function () {
        if (!mine) { toast('You can only change your own'); return; }
        var acts = me().acts ? me().acts.slice() : [];
        if (on) acts = acts.filter(function (x) { return x !== a.id; });
        else if (a.excl) acts = [a.id];
        else acts = acts.filter(function (x) { var o = act(x); return !(o && o.excl); }).concat([a.id]);
        me().acts = acts;
        logIt('Set where they are: ' + (acts.map(function (x) { return act(x).name; }).join(' + ') || 'nothing'), 'Standup', 'standup', a.color);
        queueEntrySave();
        redrawAll();
      } };
    }).concat([null, { label: 'Customise the list...', run: function () {
      document.querySelector('[data-settings="me"]').click();
    } }]);
  }
  function personMenu(el) {
    var k = el.dataset.who;
    return [
      { label: 'Only ' + PEOPLE[k].name + "'s tasks", run: function () {
          document.getElementById('tile-tasks').setAttribute('open-state', '1');
          setPeople([k]); toast('Filtered to ' + PEOPLE[k].name);
        } },
      { label: 'See their week', run: function () { teamView('week'); } },
      { label: 'See the capacity view', run: function () { teamView('cap'); } },
      { label: 'Give them a task', run: function () {
          createSingleTask({ title: 'New task', project_id: defaultJobId(), assignee_id: k }, true);
        } },
      { label: 'Mention them in a comment', run: function () {
          var card = document.querySelector('.member[data-who="' + ME_ID + '"] .comments');
          if (!card) return;
          Array.prototype.forEach.call(card.querySelectorAll('.comment, [data-reply]'), function (n) { n.style.display = ''; });
          card.dataset.open = '1';
          var i = card.querySelector('input');
          if (i) { i.value = '@' + PEOPLE[k].name + ' '; i.focus(); }
        } }
    ];
  }
  function blockerMenu(el) {
    var id = el.dataset.taskid || null;
    var t = id ? taskById(id) : null;
    var out = [];
    if (t) {
      out.push({ label: 'Edit the task...', run: function () { openEdit(t); } });
      out.push({ label: 'It has landed - clear the flag', run: function () { setWait(t, ''); } });
      out.push({ label: 'Chase it', run: function () {
        // A chase is a real event - it lands as a comment on the task, so
        // the whole team sees it was chased and when.
        addTaskComment(t, 'Chased: ' + t.wait);
      } });
      out.push(null);
      out.push({ label: 'Open job ' + t.job, run: function () {
        var jid = jobIdOf(t.job);
        if (jid) opts.navigate('/projects/' + jid); else toast('Unknown job');
      } });
    } else {
      out.push({ label: 'Clear my blocker', run: function () {
        me().b = ''; me().bBy = '';
        document.getElementById('fBlock').value = '';
        logIt('Cleared their blocker', 'Standup', 'standup', 'green');
        queueEntrySave();
        redrawAll(); toast('Blocker cleared');
      } });
      out.push({ label: 'Change the need-by date', run: function () {
        document.getElementById('tile-me').setAttribute('open-state', '1');
        document.getElementById('fBlockBy').focus();
      } });
    }
    return out;
  }
  function stageColMenu(el) {
    var s = stage(el.dataset.stage);
    var pid = scopeOf(s);
    var list = listOfScope(pid) || STAGES;
    var idx = list.indexOf(s);
    var jf = document.getElementById('jobFilter').value;
    var jfPid = jf ? jobIdOf(jf) : '';
    function saved(what, c) { logIt(what, 'Settings', 'config', c || 'slate'); queueStagesSave(pid); redrawAll(); }
    function openPanel(sel) {
      cfgScope = pid ? codeOfJobId(pid) : '';
      document.getElementById('set-stages').classList.add('open');
      document.querySelector('[data-settings="stages"]').setAttribute('aria-pressed', 'true');
      renderStageCfg();
      var row = document.querySelectorAll('#stageCfg .cfg')[idx];
      if (row) { row.scrollIntoView({ block: 'center' }); var n = row.querySelector(sel); if (n) { n.focus(); n.select(); } }
    }
    var items = [
      { label: 'Rename...', note: 'or double-click the name', run: function () {
          askFor('Stage name', 'What this column is called', s.name, function (v) {
            if (v === s.name) return;
            s.name = v; saved('Renamed a stage to "' + v + '"', s.color); toast('Stage renamed');
          });
        } },
      { label: 'Colour...', color: s.color, sub: function (x, y) { stageColourMenu(s, pid, x, y); } },
      { label: 'WIP limit...', note: s.wip == null ? 'none' : String(s.wip), run: function () {
          askFor('WIP limit for ' + s.name, 'How many tasks before it warns - 0 for none', s.wip == null ? '' : String(s.wip), function (v) {
            var n = parseInt(v, 10);
            s.wip = (isNaN(n) || n <= 0) ? null : Math.min(99, n);
            saved('WIP limit changed on ' + s.name); toast(s.wip == null ? 'WIP limit cleared' : 'WIP limit ' + s.wip);
          });
        } },
      { label: s.done ? 'No longer closes tasks' : 'This stage closes tasks', run: function () {
          s.done = !s.done; saved('"' + s.name + '" ' + (s.done ? 'now closes' : 'no longer closes') + ' tasks');
        } },
      null,
      { label: 'Move left', note: idx === 0 ? 'already first' : null, run: function () {
          if (idx === 0) { toast('Already first'); return; }
          list.splice(idx - 1, 0, list.splice(idx, 1)[0]);
          saved('Moved "' + s.name + '" earlier');
        } },
      { label: 'Move right', note: idx === list.length - 1 ? 'already last' : null, run: function () {
          if (idx === list.length - 1) { toast('Already last'); return; }
          list.splice(idx + 1, 0, list.splice(idx, 1)[0]);
          saved('Moved "' + s.name + '" later');
        } },
      { label: 'Follow-ups on entry (' + (s.spawn || []).length + ')...', run: function () { openPanel('.spawn-in'); } },
      { label: 'Add a task here', color: 'green', run: function () {
          createSingleTask({ title: 'New task', project_id: pid || jfPid || defaultJobId(), assignee_id: ME_ID, stage_id: s.id }, true);
        } },
      null
    ];
    if (pid) {
      var code = codeOfJobId(pid);
      items.push({ label: 'Make this the standard for all jobs', color: 'violet', note: 'from ' + code, run: function () { makeStandard(pid); } });
      items.push({ label: 'Put ' + code + ' back on the standard stages', run: function () { dropOwnStages(code); } });
    } else if (jf && !jobHasOwn(jf)) {
      items.push({ label: 'Use these stages for ' + jf + ' only', color: 'violet', note: 'its own copy', run: function () { startOwnStages(jf); } });
    } else if (!jf) {
      items.push({ label: 'Stages for one job only...', note: 'filter to a job first', run: function () {
          toast('Pick a job in the filter first', 'then give it its own stages');
        } });
    }
    items.push(null);
    items.push({ label: 'Remove this stage', cls: 'danger', run: function () { removeStage(list, pid, s, idx); } });
    return items;
  }
  function logMenu(el) {
    var where = el.dataset.where || '';
    return [
      { label: 'Copy this line', run: function () {
          if (navigator.clipboard) navigator.clipboard.writeText(el.innerText.replace(/\s+/g, ' ').trim()).catch(function () {});
          toast('Copied');
        } },
      { label: where ? 'Filter to ' + where : 'No job on this entry', run: function () {
          if (!where) return;
          document.getElementById('jobFilter').value = where;
          document.getElementById('tile-tasks').setAttribute('open-state', '1');
          redrawAll(true); toast('Filtered to ' + where);
        } },
      { label: 'Show only settings changes', run: function () {
          document.getElementById('logFilter').value = 'config'; renderLog();
        } },
      { label: 'Show everything', run: function () {
          document.getElementById('logFilter').value = ''; renderLog();
        } }
    ];
  }
  function tileMenu(el) {
    var tile = el.closest('.tile');
    return [
      { label: tile.getAttribute('open-state') === '1' ? 'Collapse this tile' : 'Open this tile', run: function () {
          tile.setAttribute('open-state', tile.getAttribute('open-state') === '1' ? '0' : '1'); save();
        } },
      { label: 'Collapse the others', run: function () {
          Array.prototype.forEach.call(document.querySelectorAll('.tile'), function (t) {
            t.setAttribute('open-state', t === tile ? '1' : '0');
          });
          save();
        } },
      { label: 'Expand everything', run: function () {
          Array.prototype.forEach.call(document.querySelectorAll('.tile'), function (t) {
            t.setAttribute('open-state', '1');
          });
          paintTilesToggle();
          save();
        } }
    ];
  }
  function fieldMenu(el) {
    return [
      { label: 'Clear this field', run: function () {
          document.getElementById('fBlock').value = ''; me().b = '';
          logIt('Cleared their blocker', 'Standup', 'standup', 'green');
          queueEntrySave();
          redrawAll(); toast('Cleared');
        } },
      { label: 'Set need-by: today', run: function () { setBlockBy(TODAY); } },
      { label: 'Set need-by: tomorrow', run: function () { setBlockBy(TOMORROW); } },
      { label: 'Set need-by: end of week', run: function () { setBlockBy(ENDWEEK); } }
    ];
  }
  function setBlockBy(d) {
    me().bBy = d;
    document.getElementById('fBlockBy').value = d;
    logIt('Blocker needed by ' + fmt(d), 'Standup', 'standup', 'amber');
    queueEntrySave();
    redrawAll(); toast('Need it by ' + fmt(d));
  }
  function photoMenu(el) {
    var i = parseInt(el.dataset.i, 10);
    var ph = me().photos[i] || {};
    var k = fileKind(ph.name || '', ph.type);
    return [
      { label: k.k === 'img' ? 'View it' : 'Open it', color: k.c, run: function () {
          if (k.k === 'img' && ph.url) openViewer(ph); else toast('Opens ' + ph.name);
        } },
      { label: 'Copy the file name', run: function () {
          if (navigator.clipboard) navigator.clipboard.writeText(ph.name || '').catch(function () {});
          toast('Copied');
        } },
      null,
      { label: 'Remove it', cls: 'danger', run: function () {
          if (ph.fileId) API.deleteEntryFile(ph.fileId).catch(fail('Could not remove it'));
          me().photos.splice(i, 1);
          logIt('Removed an attachment', 'Standup', 'standup', 'red');
          redrawAll();
          toast('Removed', ph.name);
        } }
    ];
  }
  function commentMenu(el) {
    var p = TEAM.filter(function (x) { return x.who === el.dataset.who; })[0];
    var ci = parseInt(el.dataset.ci, 10);
    var c = p && p.comments[ci];
    return [
      { label: 'Copy it', run: function () {
          if (navigator.clipboard && c) navigator.clipboard.writeText(c.body).catch(function () {});
          toast('Copied');
        } },
      { label: 'Reply mentioning them', run: function () {
          var box = el.closest('.comments');
          var i = box.querySelector('input');
          if (i && c) { i.value = '@' + c.who + ' '; i.focus(); }
        } },
      { label: 'Delete it', cls: 'danger', run: function () {
          if (!c) return;
          if (c.id) API.deleteComment(c.id).catch(fail('Could not delete the comment'));
          p.comments.splice(ci, 1);
          logIt('Deleted a comment', 'Standup', 'standup', 'red');
          redrawAll();
          toast('Comment deleted');
        } }
    ];
  }
  function dayMenu(el) {
    var iso = el.dataset.day;
    var due = TASKS.filter(function (t) { return t.due === iso && !stage(t.st).done; });
    return [
      { label: 'Add a task due ' + fmt(iso), color: 'green', run: function () { newTaskOn(iso); } },
      { label: due.length ? 'Show the ' + plural(due.length, 'task') + ' due this day' : 'Nothing due this day',
        run: function () {
          if (!due.length) { toast('Nothing due ' + fmt(iso)); return; }
          document.querySelector('.subtabs button[data-sub="list"]').click();
          sortBy = 'due'; sortDir = 1;
          renderListHead(); redrawAll(true);
          toast(plural(due.length, 'task') + ' due ' + fmt(iso), fmtList(due.map(function (t) { return t.t; })).slice(0, 60));
        } },
      { label: 'Open that day on the standup', run: function () {
          if (DAY_ISO.indexOf(iso) > -1) { setDay(iso); document.getElementById('tile-team').scrollIntoView({ block: 'start' }); }
          else toast('No standup recorded for ' + fmt(iso));
        } },
      null,
      { label: 'Copy the date', run: function () {
          if (navigator.clipboard) navigator.clipboard.writeText(iso).catch(function () {});
          toast('Copied ' + iso);
        } }
    ];
  }
  /** A dashed repeat on the month grid: not a task yet, so the menu is
   *  about the rule that will make it. */
  function ghostMenu(el) {
    var t = taskById(el.dataset.taskid);
    if (!t) return [];
    return [
      { label: 'Open the task it repeats from', run: function () { openEdit(t); } },
      { label: 'Not a task yet', note: describeRepeat(t), run: function () {
          toast('Not a task yet - ' + describeRepeat(t).toLowerCase(), 'it is created when the current one is closed');
        } },
      null,
      { label: 'Change how it repeats...', sub: function (x, y) {
          popover(x, y, 'Repeat', REPEATS.map(function (r) {
            return { label: r.label + (t.rep === r.key ? '  (current)' : ''), run: function () {
              t.rep = r.key;
              logIt('"' + t.t + '" ' + (r.key ? 'repeats ' + r.label.toLowerCase() : 'no longer repeats'), t.job, 'task', 'cyan');
              pushTaskField(t, { repeat_rule: r.key });
              redrawAll(); toast(r.key ? 'Repeats ' + r.label.toLowerCase() : 'Repeat removed');
            } };
          }));
        } },
      { label: 'Stop it repeating', cls: 'danger', run: function () {
          t.rep = '';
          logIt('"' + t.t + '" no longer repeats', t.job, 'task', 'cyan');
          pushTaskField(t, { repeat_rule: '' });
          redrawAll(); toast('Repeat removed');
        } }
    ];
  }
  /** The composer's task lines: each one is a small form of its own. */
  function addrowMenu(el) {
    var i = parseInt(el.dataset.i, 10), r = addRows[i];
    if (!r) return [];
    var ready = !!(job(r.job) && (r.title || '').trim());
    function due(d) { r.due = d || ''; renderAddRows(i); }
    return [
      { label: 'Add this task', color: 'green', key: 'Enter', note: ready ? null : 'needs a job and a description', run: function () { submitRow(i); } },
      { label: 'Pick the job...', note: r.job || 'none yet', sub: function (x, y) {
          renderMenu('Job for this line', jobOptions(true).map(function (o) {
            return { label: o.label, note: o.note, color: o.color, run: function () { r.job = o.value; renderAddRows(i); } };
          }), x, y, { search: 'Search jobs...' });
        } },
      { label: 'Due date...', note: r.due ? fmt(r.due) : 'none', sub: function (x, y) {
          popover(x, y, 'Due', [
            { label: 'Today', run: function () { due(TODAY); } },
            { label: 'Tomorrow', run: function () { due(TOMORROW); } },
            { label: 'End of the week', run: function () { due(ENDWEEK); } },
            { label: 'Next week', run: function () { due(NEXTWEEK); } },
            { label: 'No date', run: function () { due(''); } }
          ]);
        } },
      null,
      { label: 'Duplicate line', note: 'keeps the job and date', run: function () {
          addRows.splice(i + 1, 0, { job: r.job, title: r.title, due: r.due });
          renderAddRows(i + 1);
        } },
      { label: 'Add a line below', run: function () { addAnother(i); } },
      { label: 'Clear line', run: function () { addRows[i] = { job: '', title: '', due: '' }; renderAddRows(i); } },
      null,
      { label: 'Remove line', cls: 'danger', run: function () {
          addRows.splice(i, 1);
          if (!addRows.length) addRows.push({ job: '', title: '', due: '' });
          renderAddRows(Math.max(0, i - 1));
        } }
    ];
  }
  /** The month view's "No date yet" tray as a whole. */
  function trayMenu() {
    var undated = visible().filter(function (t) { return !t.due && !stage(t.st).done; });
    function dateAll(d, label) {
      if (!undated.length) { toast('Nothing in the tray'); return; }
      undated.forEach(function (t) { t.due = d; pushTaskField(t, { due: d }); });
      logIt('Gave ' + plural(undated.length, 'undated task') + ' a due date of ' + fmt(d), 'Month', 'task', 'blue');
      redrawAll();
      toast(plural(undated.length, 'task') + ' now due ' + label, fmt(d), function () {
        undated.forEach(function (t) { t.due = null; pushTaskField(t, { due: '' }); });
        redrawAll();
        toast('Dates cleared again');
      });
    }
    return [
      { label: 'Add a task with no date', color: 'green', run: function () {
          createSingleTask({ title: 'New task', project_id: defaultJobId(), assignee_id: ME_ID }, true);
        } },
      { label: 'Show them in the list', note: plural(undated.length, 'task'), run: function () {
          document.querySelector('.subtabs button[data-sub="list"]').click();
          sortBy = 'due'; sortDir = -1;   // no date sorts as "9999" - first when descending
          renderListHead(); redrawAll(true);
          toast(plural(undated.length, 'undated task') + ' at the top of the list');
        } },
      null,
      { label: 'Give them all a date: today', note: 'undo on the toast', run: function () { dateAll(TODAY, 'today'); } },
      { label: 'Give them all a date: end of the week', note: 'undo on the toast', run: function () { dateAll(ENDWEEK, 'end of the week'); } }
    ];
  }
  var MENU_FOR = {
    row: rowMenu, card: cardMenu, job: jobMenu, task: taskLineMenu, cell: cellMenu,
    activity: activityMenu, person: personMenu, blocker: blockerMenu, stagecol: stageColMenu,
    logrow: logMenu, tile: tileMenu, field: fieldMenu, photo: photoMenu, comment: commentMenu,
    day: dayMenu, ghost: ghostMenu, addrow: addrowMenu, tray: trayMenu, toolbar: toolbarMenu
  };

  var ctx = document.getElementById('ctx'), ctxHead = document.getElementById('ctxHead'), ctxBody = document.getElementById('ctxBody');
  //! The click that OPENS a menu keeps bubbling up to the document, where
  //! the close-on-click-outside handler sees a target outside #ctx and
  //! shuts the menu again in the same tick. Right-click was fine (a
  //! contextmenu event fires no click), which is why only the left-click
  //! pickers looked dead. Stamp the open and let that one click through.
  var ctxOpenedAt = 0;
  function closeCtx() { ctx.classList.remove('open'); }
  function place(x, y) {
    ctx.classList.add('open');
    ctxOpenedAt = Date.now();
    var w = ctx.offsetWidth, h = ctx.offsetHeight;
    ctx.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + 'px';
    ctx.style.top = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + 'px';
  }
  /* One renderer for every menu, so a colour swatch, a submenu arrow or a
     shortcut hint behaves the same wherever the menu was opened from. */
  function renderMenu(head, items, x, y, opts) {
    opts = opts || {};
    ctxHead.textContent = head;
    ctxBody.innerHTML = '';

    // A long list gets a filter box under the heading - 19 jobs is more
    // than anyone should have to scan.
    if (opts.search) {
      var wrap = document.createElement('div');
      wrap.className = 'menusearch';
      var inp = document.createElement('input');
      inp.type = 'text';
      inp.placeholder = opts.search;
      wrap.appendChild(inp);
      ctxBody.appendChild(wrap);
      var listBox = document.createElement('div');
      ctxBody.appendChild(listBox);
      var paint = function (q) {
        listBox.innerHTML = '';
        var shown = items.filter(function (it) {
          if (!it) return false;
          if (!q) return true;
          return (it.label + ' ' + (it.note || '')).toLowerCase().indexOf(q.toLowerCase()) > -1;
        });
        if (!shown.length) {
          var none = document.createElement('div');
          none.className = 'menunone';
          none.textContent = 'Nothing matches that.';
          listBox.appendChild(none);
          return;
        }
        shown.forEach(function (it) { listBox.appendChild(menuButton(it)); });
      };
      inp.addEventListener('input', function () { paint(inp.value); });
      inp.addEventListener('click', function (e) { e.stopPropagation(); });
      paint('');
      place(x, y);
      setTimeout(function () { inp.focus(); }, 20);
      return;
    }

    items.forEach(function (it) {
      if (!it) { ctxBody.appendChild(document.createElement('hr')); return; }
      ctxBody.appendChild(menuButton(it));
    });
    place(x, y);
  }
  function menuButton(it) {
    var b = document.createElement('button');
    b.type = 'button';
    if (it.cls) b.className = it.cls;
    if (it.color) {
      var sw = document.createElement('span');
      sw.className = 'mdot';
      sw.style.background = cvar(it.color);
      b.appendChild(sw);
    }
    var lab = document.createElement('span');
    lab.className = 'mlabel';
    lab.textContent = it.label;
    b.appendChild(lab);
    if (it.note) { var n = document.createElement('span'); n.className = 'mnote'; n.textContent = it.note; b.appendChild(n); }
    if (it.sub) { var a = document.createElement('span'); a.className = 'k'; a.innerHTML = '&#9656;'; b.appendChild(a); }
    else if (it.key) { var k = document.createElement('span'); k.className = 'k'; k.textContent = it.key; b.appendChild(k); }
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      if (it.sub) { var r = b.getBoundingClientRect(); it.sub(r.right - 6, r.top); }
      else { closeCtx(); it.run(ev); }
    });
    return b;
  }
  function popover(x, y, head, items) { renderMenu(head, items, x, y); }
  function openCtx(x, y, el) {
    var build = MENU_FOR[el.dataset.menu];
    if (!build) return;
    renderMenu(el.dataset.label || el.dataset.menu, build(el), x, y);
  }
  docListen(document, 'contextmenu', function (e) {
    // Text fields keep the browser's own menu (copy, paste, spelling) even
    // when they sit inside something that has a menu, like a composer line.
    var tag = (e.target && e.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)) return;
    var target = e.target.closest('[data-menu]');
    if (!target) return;
    // Only inside the board - the rest of the ERP keeps its own menus.
    if (!e.target.closest('.standup-root')) return;
    e.preventDefault();
    openCtx(e.clientX, e.clientY, target);
  });
  docListen(document, 'click', function (e) {
    if (Date.now() - ctxOpenedAt < 250) return;
    if (!e.target.closest('#ctx')) closeCtx();
  });
  docListen(document, 'keydown', function (e) { if (e.key === 'Escape') closeCtx(); });
  docListen(window, 'resize', closeCtx);
  docListen(window, 'scroll', closeCtx, true);

  /* ---------- day navigation ---------- */
  function setDay(iso) {
    if (!iso) return;
    var i = DAY_ISO.indexOf(iso);
    if (i === -1) { toast('No standup recorded for that day'); return; }
    viewDay = iso;
    document.getElementById('dayPick').value = iso;
    document.getElementById('dateLine').textContent = longDate(iso);
    document.getElementById('dayPrev').disabled = (i === 0);
    document.getElementById('dayNext').disabled = (i === DAY_ISO.length - 1);
    var td = document.getElementById('dayToday');
    td.style.display = iso === TODAY ? 'none' : '';
    document.getElementById('tile-me').style.display = iso === TODAY ? '' : 'none';
    renderTeam();
    save();
  }
  document.getElementById('dayPrev').addEventListener('click', function () {
    var i = DAY_ISO.indexOf(viewDay);
    if (i > 0) setDay(DAY_ISO[i - 1]);
  });
  document.getElementById('dayNext').addEventListener('click', function () {
    var i = DAY_ISO.indexOf(viewDay);
    if (i > -1 && i < DAY_ISO.length - 1) setDay(DAY_ISO[i + 1]);
  });
  document.getElementById('dayPick').addEventListener('change', function () { setDay(this.value); });
  document.getElementById('dayToday').addEventListener('click', function () { setDay(TODAY); });

  /* The preview's theme/hook-highlight chrome is gone - the ERP's own
     theme store drives dark mode via the `dark` class on <html>. */

  Array.prototype.forEach.call(document.querySelectorAll('.subtabs button'), function (b) {
    b.addEventListener('click', function () {
      Array.prototype.forEach.call(document.querySelectorAll('.subtabs button'), function (o) { o.setAttribute('aria-selected', 'false'); });
      b.setAttribute('aria-selected', 'true');
      var v = b.dataset.sub;
      document.getElementById('view-list').style.display = v === 'list' ? 'block' : 'none';
      document.getElementById('view-board').style.display = v === 'board' ? 'block' : 'none';
      document.getElementById('view-month').style.display = v === 'month' ? 'block' : 'none';
      if (v === 'month') renderMonth();
      // The list could not be measured while it was hidden - fit it now
      // that it has a width again.
      if (v === 'list') scheduleFit();
    });
  });
  ['taskFilter','jobFilter','clientFilter'].forEach(function (id) {
    document.getElementById(id).addEventListener(id === 'taskFilter' ? 'input' : 'change', function () {
      redrawAll(true);
      // The stage panel's "Only <job>" scope follows the job filter.
      if (id === 'jobFilter') renderStageCfg();
    });
  });
  ['waitOnly','dueOnly'].forEach(function (id) {
    document.getElementById(id).addEventListener('click', function () {
      this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      redrawAll(true);
    });
  });
  document.getElementById('createBtn').addEventListener('click', function () {
    createSingleTask({ title: 'New task', project_id: defaultJobId(), assignee_id: ME_ID }, true);
  });

  /* ---------- boot ---------- */
  function fillSelects() {
    var f = document.getElementById('jobFilter'), c = document.getElementById('clientFilter');
    // Idempotent: a refresh rebuilds the option lists from scratch.
    var fKeep = f.value, cKeep = c.value;
    f.innerHTML = '<option value="">All jobs</option>';
    c.innerHTML = '<option value="">All clients</option>';
    JOBS.forEach(function (j) {
      var o2 = document.createElement('option');
      o2.value = j.code;
      o2.textContent = j.code + '  ' + j.client + ' - ' + j.name;
      f.appendChild(o2);
    });
    // Clients come off the jobs - the same family the job chips are
    // coloured by - so "Client" here is the job's client, nothing else.
    var clients = [];
    JOBS.forEach(function (j) { if (j.client && clients.indexOf(j.client) === -1) clients.push(j.client); });
    clients.sort().forEach(function (name) {
      var o = document.createElement('option'); o.value = name; o.textContent = name; c.appendChild(o);
    });
    f.value = fKeep || '';
    c.value = cKeep || '';
    document.getElementById('avatarStack').innerHTML =
      Object.keys(PEOPLE).map(function (k) { return avatar(k); }).join('');
  }
  function redrawAll(skipCfg) {
    renderStatusChips(); renderJobPicker(); renderClientChips(); renderPhotos(); renderTeam(); renderWeek();
    renderCapacity(); renderBlockers(); renderList(); renderBoard(); renderLog();
    // The month grid is only built while it is showing.
    if (document.getElementById('view-month').style.display !== 'none') renderMonth();
    if (!skipCfg) { renderStageCfg(); renderActCfg(); }
    save();
  }
  /** The host's poll hands in a fresh board; skip while the user is
   *  mid-interaction so a refetch can never eat a half-typed field. */
  function refreshFromBoard(newBoard) {
    if (document.querySelector('.scrim.open')) return;
    if (ctx.classList.contains('open')) return;
    var ae = document.activeElement;
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA')) return;
    if (entrySaveTimer || stagesSaving() || actsSaveTimer) return;
    buildFromBoard(newBoard);
    fillSelects();
    applyFiltersToDom();
    hydrateMine();
    renderListHead();
    if (DAY_ISO.indexOf(viewDay) === -1) viewDay = TODAY;
    setDay(viewDay);
    if (F.deliv === 'switchboards') loadWorkshopIndex(function () { redrawAll(true); });
    redrawAll();
    paintTilesToggle();
  }

  var dayPickEl = document.getElementById('dayPick');
  dayPickEl.min = DAY_ISO[0];
  dayPickEl.max = DAY_ISO[DAY_ISO.length - 1];
  fillSelects();
  // The saved filters land in the DOM BEFORE anything can save() - a
  // save reads the DOM back, and an unfilled DOM would wipe them.
  applyFiltersToDom();
  hydrateMine();
  renderAddRows();
  setDay(TODAY);
  applySize();
  renderListHead();
  redrawAll();
  paintTilesToggle();
  if (F.deliv === 'switchboards') loadWorkshopIndex(function () { redrawAll(true); });

  return {
    dispose: function () {
      CLEANUP.forEach(function (fn) { fn(); });
      clearTimeout(entrySaveTimer);
      Object.keys(stagesSaveTimers).forEach(function (k) { clearTimeout(stagesSaveTimers[k]); });
      clearTimeout(actsSaveTimer);
      clearTimeout(typingRedrawTimer);
      Object.keys(pendingTicks).forEach(function (k) { clearTimeout(pendingTicks[k]); });
      if (thumbTimer) clearTimeout(thumbTimer);
      if (fitTimer) clearTimeout(fitTimer);
      if (fitRaf && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(fitRaf);
    },
    refresh: refreshFromBoard
  };
}
