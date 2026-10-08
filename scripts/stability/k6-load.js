// k6 load profile for the stability workflow (.github/workflows/stability.yml).
//
// One iteration is what an estimator does in a minute of real work: open the
// project list, open a seeded project's BOQ list, open one BOQ with its
// positions, edit one position, and search the cost database. Each VU signs in
// once through the demo login (the same endpoint the login page uses), so the
// login path is exercised at the VU count without turning the run into a
// login benchmark.
//
// Env:
//   BASE_URL     app root, default http://127.0.0.1:8080
//   VUS          virtual users, default 20
//   DURATION     steady-state duration, default 5m
//   DEMO_EMAIL   seeded demo admin, default demo@openconstructionerp.com
//   SUMMARY_OUT  path for the JSON summary, default k6-summary.json

import http from 'k6/http';
import { check, fail, sleep } from 'k6';

const BASE = (__ENV.BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
const API = `${BASE}/api/v1`;
const DEMO_EMAIL = __ENV.DEMO_EMAIL || 'demo@openconstructionerp.com';
const SEARCH_TERMS = ['concrete', 'rebar', 'brick', 'excavation', 'formwork', 'insulation'];

export const options = {
  scenarios: {
    estimator: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: Number(__ENV.VUS || 20) },
        { duration: __ENV.DURATION || '5m', target: Number(__ENV.VUS || 20) },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{kind:read}': ['p(95)<1500'],
    // Writes are reported but only guarded against pathological latency.
    'http_req_duration{kind:write}': ['p(95)<3000'],
    checks: ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function login() {
  const res = http.post(`${API}/users/auth/demo-login/`, JSON.stringify({ email: DEMO_EMAIL }), {
    headers: { 'Content-Type': 'application/json' },
    tags: { kind: 'login', name: 'demo-login' },
  });
  if (!check(res, { 'login 200': (r) => r.status === 200 })) {
    return null;
  }
  return res.json('access_token');
}

function auth(token) {
  return { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
}

// Find one seeded project that has a BOQ with at least one position. Runs once.
export function setup() {
  const token = login();
  if (!token) fail('demo login failed in setup - is SEED_DEMO on and the seed finished?');
  const projects = http.get(`${API}/projects/?limit=100`, auth(token));
  if (projects.status !== 200) fail(`projects list answered ${projects.status}`);
  for (const p of projects.json()) {
    const boqs = http.get(`${API}/boq/boqs/?project_id=${p.id}`, auth(token));
    if (boqs.status !== 200) continue;
    for (const b of boqs.json()) {
      const full = http.get(`${API}/boq/boqs/${b.id}`, auth(token));
      if (full.status !== 200) continue;
      const positions = (full.json('positions') || []).filter((x) => x.quantity !== null && x.quantity !== undefined);
      if (positions.length > 0) {
        return { projectId: p.id, boqId: b.id, positionId: positions[0].id, quantity: Number(positions[0].quantity) };
      }
    }
  }
  fail('no seeded project with a BOQ position found');
  return null;
}

let vuToken = null;

export default function (data) {
  if (!vuToken) {
    vuToken = login();
    if (!vuToken) {
      sleep(1);
      return;
    }
  }
  const p = auth(vuToken);
  const read = (url, name) => http.get(url, Object.assign({ tags: { kind: 'read', name } }, p));

  check(read(`${API}/projects/?limit=50`, 'projects-list'), { 'projects 200': (r) => r.status === 200 });
  check(read(`${API}/boq/boqs/?project_id=${data.projectId}`, 'boq-list'), { 'boq list 200': (r) => r.status === 200 });
  check(read(`${API}/boq/boqs/${data.boqId}`, 'boq-get'), { 'boq get 200': (r) => r.status === 200 });

  // Idempotent edit: write the seeded quantity back, so the BOQ total is the
  // same after the run and parallel VUs do not drift each other's numbers.
  const edit = http.patch(
    `${API}/boq/positions/${data.positionId}`,
    JSON.stringify({ quantity: data.quantity }),
    Object.assign({ tags: { kind: 'write', name: 'position-patch' } }, p),
  );
  check(edit, { 'position patch 200': (r) => r.status === 200 });

  const term = SEARCH_TERMS[(__VU + __ITER) % SEARCH_TERMS.length];
  check(read(`${API}/costs/?q=${term}&limit=20`, 'costs-search'), { 'costs search 200': (r) => r.status === 200 });

  // A 401 means the access token expired mid-run; sign in again next iteration.
  if (edit.status === 401) vuToken = null;
  sleep(1 + Math.random());
}

export function handleSummary(data) {
  const out = __ENV.SUMMARY_OUT || 'k6-summary.json';
  const m = data.metrics;
  const p95 = (k) => (m[k] && m[k].values ? m[k].values['p(95)'] : null);
  const line =
    `VUS=${__ENV.VUS || 20} reqs=${m.http_reqs ? m.http_reqs.values.count : 0} ` +
    `failed=${m.http_req_failed ? (m.http_req_failed.values.rate * 100).toFixed(2) : '?'}% ` +
    `p95_read=${p95('http_req_duration{kind:read}')}ms p95_write=${p95('http_req_duration{kind:write}')}ms\n`;
  return { [out]: JSON.stringify(data, null, 2), stdout: line };
}
