"""Comprehensive test of all AI Estimate endpoints."""
import requests
import time
import struct
import zlib
import json

BASE = "http://localhost:8000"
tests = []

# Login
r = requests.post(f"{BASE}/api/v1/users/auth/login", json={
    "email": "demo@openestimator.io", "password": "DemoPass1234!"
})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
hm = {"Authorization": f"Bearer {token}"}

def log(name, status_code, elapsed, response_json=None, raw_text=None):
    if response_json:
        d = response_json
        st = d.get("status", "?")
        items = len(d.get("items", []))
        total = d.get("grand_total", 0)
        err = d.get("error_message", "")
        model = d.get("model_used", "")
        dur = d.get("duration_ms", 0)
        job_id = d.get("id", "")
        print(f"  HTTP {status_code} in {elapsed:.1f}s | status={st} items={items} total={total} model={model} dur={dur}ms")
        if err:
            print(f"  ERROR: {err[:200]}")
        for i, item in enumerate(d.get("items", [])[:3]):
            print(f"    [{item.get('ordinal','')}] {item.get('description','')[:50]} | {item.get('unit','')} | qty={item.get('quantity')} | rate={item.get('unit_rate')} | total={item.get('total')}")
        if items > 3:
            print(f"    ... and {items - 3} more")
        tests.append({"name": name, "http": status_code, "status": st, "items": items, "total": total, "error": (err or "")[:100], "job_id": job_id})
    else:
        print(f"  HTTP {status_code} in {elapsed:.1f}s | body: {(raw_text or '')[:200]}")
        tests.append({"name": name, "http": status_code, "status": "http_error", "items": 0, "error": (raw_text or "")[:100]})


def make_png(w=10, h=10):
    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            raw += b"\xff\x00\x00"  # red
    compressed = zlib.compress(raw)
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


# ── Test 1: Text - Office Building Berlin ──
print("=" * 60)
print("Test 1: Text Estimate - Office Building Berlin")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/quick-estimate", headers=h, json={
    "description": "3-story office building, 2000 m2, Berlin, reinforced concrete frame, flat roof, curtain wall facade",
    "location": "Berlin", "currency": "EUR", "standard": "din276",
    "project_type": "commercial_office", "area_m2": 2000
}, timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("text_office_berlin", r.status_code, elapsed, r.json())
else:
    log("text_office_berlin", r.status_code, elapsed, raw_text=r.text)


# ── Test 2: Text - Residential Villa Dubai ──
print("\n" + "=" * 60)
print("Test 2: Text Estimate - Residential Villa Dubai")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/quick-estimate", headers=h, json={
    "description": "Luxury residential villa 500m2 with swimming pool, landscaping, 4 bedrooms in Dubai Marina",
    "location": "Dubai", "currency": "AED", "standard": "masterformat",
    "project_type": "residential", "area_m2": 500
}, timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("text_villa_dubai", r.status_code, elapsed, r.json())
else:
    log("text_villa_dubai", r.status_code, elapsed, raw_text=r.text)


# ── Test 3: Text - Warehouse Hamburg ──
print("\n" + "=" * 60)
print("Test 3: Text Estimate - Warehouse Hamburg")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/quick-estimate", headers=h, json={
    "description": "Large industrial warehouse 5000m2, steel structure, 10m clear height, Hamburg port area",
    "location": "Hamburg", "currency": "EUR", "standard": "din276",
    "project_type": "industrial", "area_m2": 5000
}, timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("text_warehouse_hamburg", r.status_code, elapsed, r.json())
else:
    log("text_warehouse_hamburg", r.status_code, elapsed, raw_text=r.text)


# ── Test 4: Text - Short description (edge case) ──
print("\n" + "=" * 60)
print("Test 4: Text Estimate - Minimal description")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/quick-estimate", headers=h, json={
    "description": "small house 100m2"
}, timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("text_minimal", r.status_code, elapsed, r.json())
else:
    log("text_minimal", r.status_code, elapsed, raw_text=r.text)


# ── Test 5: Photo - real PNG ──
print("\n" + "=" * 60)
print("Test 5: Photo Estimate - PNG image")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/photo-estimate", headers=hm,
    files={"file": ("building.png", make_png(100, 100), "image/png")},
    data={"location": "Berlin", "currency": "EUR", "standard": "din276"},
    timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("photo_png", r.status_code, elapsed, r.json())
else:
    log("photo_png", r.status_code, elapsed, raw_text=r.text)


# ── Test 6: Photo - JPEG content type with wrong data ──
print("\n" + "=" * 60)
print("Test 6: Photo Estimate - JPEG (minimal)")
print("=" * 60)
start = time.time()
# minimal JPEG header
jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
r = requests.post(f"{BASE}/api/v1/ai/photo-estimate", headers=hm,
    files={"file": ("photo.jpg", jpg, "image/jpeg")},
    data={"location": "Munich", "currency": "EUR"},
    timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("photo_jpg", r.status_code, elapsed, r.json())
else:
    log("photo_jpg", r.status_code, elapsed, raw_text=r.text)


# ── Test 7: CSV file ──
print("\n" + "=" * 60)
print("Test 7: CSV File Estimate")
print("=" * 60)
csv_data = b"Pos,Description,Unit,Quantity,Rate\n1,Concrete foundation,m3,50,120\n2,Steel reinforcement,kg,2000,2.5\n3,Brickwork walls,m2,300,45\n4,Roof waterproofing,m2,400,30"
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/file-estimate", headers=hm,
    files={"file": ("boq.csv", csv_data, "text/csv")},
    data={"location": "Berlin", "currency": "EUR"},
    timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("csv_file", r.status_code, elapsed, r.json())
else:
    log("csv_file", r.status_code, elapsed, raw_text=r.text)


# ── Test 8: PDF file (dummy) ──
print("\n" + "=" * 60)
print("Test 8: PDF File Estimate (dummy PDF)")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/file-estimate", headers=hm,
    files={"file": ("specs.pdf", b"%PDF-1.4 dummy content", "application/pdf")},
    data={"location": "London", "currency": "GBP", "standard": "nrm"},
    timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("pdf_file", r.status_code, elapsed, r.json())
else:
    log("pdf_file", r.status_code, elapsed, raw_text=r.text)


# ── Test 9: Excel file (dummy) ──
print("\n" + "=" * 60)
print("Test 9: Excel File Estimate (dummy .xlsx)")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/file-estimate", headers=hm,
    files={"file": ("boq.xlsx", b"PK\x03\x04 dummy xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    data={"location": "Berlin", "currency": "EUR"},
    timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("xlsx_file", r.status_code, elapsed, r.json())
else:
    log("xlsx_file", r.status_code, elapsed, raw_text=r.text)


# ── Test 10: CAD file (.ifc) ──
print("\n" + "=" * 60)
print("Test 10: CAD File Estimate (.ifc)")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/file-estimate", headers=hm,
    files={"file": ("model.ifc", b"ISO-10303-21; HEADER; dummy IFC", "application/x-step")},
    data={"location": "Berlin", "currency": "EUR"},
    timeout=180)
elapsed = time.time() - start
if r.status_code == 200:
    log("ifc_file", r.status_code, elapsed, r.json())
else:
    log("ifc_file", r.status_code, elapsed, raw_text=r.text)


# ── Test 11: Unsupported file type ──
print("\n" + "=" * 60)
print("Test 11: Unsupported File Type (.zip)")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/file-estimate", headers=hm,
    files={"file": ("archive.zip", b"PK dummy zip", "application/zip")},
    data={"location": "Berlin"},
    timeout=30)
elapsed = time.time() - start
log("zip_unsupported", r.status_code, elapsed, raw_text=r.text)


# ── Test 12: Empty file ──
print("\n" + "=" * 60)
print("Test 12: Empty File Upload")
print("=" * 60)
start = time.time()
r = requests.post(f"{BASE}/api/v1/ai/file-estimate", headers=hm,
    files={"file": ("empty.csv", b"", "text/csv")},
    data={"location": "Berlin"},
    timeout=30)
elapsed = time.time() - start
log("empty_file", r.status_code, elapsed, raw_text=r.text)


# ── Test 13: Create BOQ from estimate (if we have a completed job) ──
completed_jobs = [t for t in tests if t.get("status") == "completed" and t.get("job_id")]
if completed_jobs:
    job = completed_jobs[0]
    print("\n" + "=" * 60)
    print(f"Test 13: Create BOQ from estimate (job {job['job_id'][:8]}...)")
    print("=" * 60)

    # Get a project ID first
    r = requests.get(f"{BASE}/api/v1/projects/?page_size=1", headers=h, timeout=10)
    if r.status_code == 200:
        projects = r.json()
        if isinstance(projects, list) and projects:
            pid = projects[0]["id"]
        elif isinstance(projects, dict) and projects.get("items"):
            pid = projects["items"][0]["id"]
        else:
            pid = None
    else:
        pid = None

    if pid:
        start = time.time()
        r = requests.post(f"{BASE}/api/v1/ai/estimate/{job['job_id']}/create-boq", headers=h, json={
            "project_id": pid,
            "boq_name": "QA Test BOQ"
        }, timeout=30)
        elapsed = time.time() - start
        print(f"  HTTP {r.status_code} in {elapsed:.1f}s")
        print(f"  Body: {r.text[:300]}")
        tests.append({"name": "create_boq", "http": r.status_code, "status": "pass" if r.status_code == 200 else "fail", "error": r.text[:100] if r.status_code != 200 else ""})
    else:
        print("  SKIP: No projects found")
        tests.append({"name": "create_boq", "http": 0, "status": "skip", "error": "no projects"})
else:
    print("\n  SKIP Test 13: No completed jobs to create BOQ from")
    tests.append({"name": "create_boq", "http": 0, "status": "skip", "error": "no completed jobs"})


# ── SUMMARY ──
print("\n" + "=" * 70)
print("FULL TEST SUMMARY")
print("=" * 70)
passed = 0
failed = 0
for t in tests:
    icon = "PASS" if t.get("status") in ("completed",) or (t.get("http") == 400 and "unsupported" in t.get("name","")) else "FAIL"
    if icon == "PASS":
        passed += 1
    else:
        failed += 1
    err = t.get("error", "")
    items = t.get("items", 0)
    total = t.get("total", "")
    print(f"  [{icon}] {t['name']}: HTTP {t['http']} | status={t['status']} | items={items} | {err[:60]}")

print(f"\nTotal: {passed} passed, {failed} failed out of {len(tests)}")
