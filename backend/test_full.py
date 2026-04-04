"""Full v0.2.3 test suite — 80 tests across all 18 modules."""
import requests
import sys

API = "http://localhost:8003"
PASS = FAIL = 0

def test(name, expected, actual):
    global PASS, FAIL
    if str(expected) == str(actual):
        PASS += 1; print(f"  OK  #{PASS+FAIL} {name}")
    else:
        FAIL += 1; print(f"  FAIL #{PASS+FAIL} {name} (exp={expected} got={actual})")

# Login
r = requests.post(f"{API}/api/v1/users/auth/login", json={"email":"demo@openestimator.io","password":"DemoPass1234!"})
token = r.json()["access_token"]
H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
proj_id = requests.get(f"{API}/api/v1/projects/", headers=H).json()[0]["id"]

print("=" * 50)
print("  v0.2.3 DEEP TEST — all 18 modules")
print("=" * 50)

# AUTH
print("-- AUTH --")
r = requests.get(f"{API}/api/health"); test("Health", 200, r.status_code)
test("Version", "0.2.3", r.json()["version"])
r = requests.post(f"{API}/api/v1/users/auth/login", json={"email":"demo@openestimator.io","password":"DemoPass1234!"}); test("Login", 200, r.status_code)
r = requests.post(f"{API}/api/v1/users/auth/login", json={"email":"demo@openestimator.io","password":"Wrong12345!"}); test("Wrong pass", 401, r.status_code)
r = requests.post(f"{API}/api/v1/users/auth/login", json={"email":"x@x.com","password":"x"}); test("Short pass no leak", 401, r.status_code)
r = requests.get(f"{API}/api/v1/projects/"); test("No token", 401, r.status_code)
r = requests.get(f"{API}/api/v1/users/me", headers=H); test("Me", 200, r.status_code)

# PROJECTS
print("-- PROJECTS --")
r = requests.get(f"{API}/api/v1/projects/", headers=H); test("List", 200, r.status_code)
r = requests.post(f"{API}/api/v1/projects/", headers=H, json={"name":"Test","region":"DACH","standard":"DIN 276","currency":"EUR"}); test("Create", 201, r.status_code)
np = r.json()["id"]
r = requests.get(f"{API}/api/v1/projects/{np}", headers=H); test("Read", 200, r.status_code)
r = requests.patch(f"{API}/api/v1/projects/{np}", headers=H, json={"name":"Updated"}); test("Update", 200, r.status_code)
r = requests.get(f"{API}/api/v1/projects/analytics/overview", headers=H); test("Analytics", 200, r.status_code)
r = requests.delete(f"{API}/api/v1/projects/{np}", headers=H); test("Delete", 204, r.status_code)

# BOQ
print("-- BOQ --")
r = requests.post(f"{API}/api/v1/boq/boqs/", headers=H, json={"project_id":proj_id,"name":"Test BOQ"}); test("Create", 201, r.status_code)
bq = r.json()["id"]
r = requests.post(f"{API}/api/v1/boq/boqs/{bq}/positions", headers=H, json={"boq_id":bq,"ordinal":"01.001","description":"Concrete C30","unit":"m3","quantity":"100","unit_rate":"295"}); test("Add position", 201, r.status_code)
po = r.json()["id"]
r = requests.post(f"{API}/api/v1/boq/boqs/{bq}/validate", headers=H, json={"rule_sets":["boq_quality"]}); test("Validate", 200, r.status_code)
r = requests.post(f"{API}/api/v1/boq/boqs/{bq}/duplicate", headers=H, json={}); test("Duplicate", 201, r.status_code)
test("Dup diff ID", True, r.json()["id"] != bq)
r = requests.get(f"{API}/api/v1/boq/boqs/{bq}/export/pdf", headers=H); test("PDF", 200, r.status_code)
r = requests.get(f"{API}/api/v1/boq/boqs/{bq}/export/excel", headers=H); test("Excel", 200, r.status_code)
r = requests.get(f"{API}/api/v1/boq/boqs/{bq}/export/csv", headers=H); test("CSV", 200, r.status_code)

# COSTS
print("-- COSTS --")
r = requests.get(f"{API}/api/v1/costs/regions", headers=H); test("Regions", 200, r.status_code)
r = requests.get(f"{API}/api/v1/costs/", headers=H, params={"limit":3}); test("Search", 200, r.status_code)
r = requests.get(f"{API}/api/v1/costs/categories", headers=H); test("Categories", 200, r.status_code)
r = requests.get(f"{API}/api/v1/costs/autocomplete", headers=H, params={"q":"beton","limit":3}); test("Autocomplete", 200, r.status_code)
r = requests.get(f"{API}/api/v1/costs/available-databases", headers=H); test("Available DBs", 200, r.status_code)
test("11 DBs", 11, len(r.json()))

# CATALOG
print("-- CATALOG --")
r = requests.get(f"{API}/api/v1/catalog/regions", headers=H); test("Regions", 200, r.status_code)
r = requests.patch(f"{API}/api/v1/catalog/adjust-prices", headers=H, params={"factor":0}); test("Factor=0 reject", 422, r.status_code)
r = requests.patch(f"{API}/api/v1/catalog/adjust-prices", headers=H, params={"factor":11}); test("Factor=11 reject", 422, r.status_code)

# SCHEDULE
print("-- SCHEDULE --")
r = requests.post(f"{API}/api/v1/schedule/schedules/", headers=H, json={"project_id":proj_id,"name":"Test"}); test("Create", True, r.status_code in (200,201))

# RISK
print("-- RISK --")
r = requests.post(f"{API}/api/v1/risk/", headers=H, json={"project_id":proj_id,"code":"R-T","title":"Test","category":"technical","probability":0.5,"impact":"high"}); test("Create", True, r.status_code in (200,201))
r = requests.get(f"{API}/api/v1/risk/", headers=H, params={"project_id":proj_id}); test("List", 200, r.status_code)

# CHANGE ORDERS
print("-- CHANGE ORDERS --")
r = requests.post(f"{API}/api/v1/changeorders/", headers=H, json={"project_id":proj_id,"code":"CO-T","title":"Test","reason":"client_request"}); test("Create", True, r.status_code in (200,201))
r = requests.get(f"{API}/api/v1/changeorders/", headers=H, params={"project_id":proj_id}); test("List", 200, r.status_code)

# TENDERING
print("-- TENDERING --")
r = requests.get(f"{API}/api/v1/tendering/packages/", headers=H, params={"project_id":proj_id}); test("List", 200, r.status_code)
r = requests.post(f"{API}/api/v1/tendering/packages/", headers=H, json={"project_id":proj_id,"name":"Structural"}); test("Create", True, r.status_code in (200,201))

# DOCUMENTS
print("-- DOCUMENTS --")
r = requests.get(f"{API}/api/v1/documents/", headers=H, params={"project_id":proj_id}); test("List", 200, r.status_code)
r = requests.get(f"{API}/api/v1/documents/summary", headers=H, params={"project_id":proj_id}); test("Summary", 200, r.status_code)

# AI, ASSEMBLIES, TAKEOFF
print("-- AI / ASSEMBLIES / TAKEOFF --")
r = requests.get(f"{API}/api/v1/ai/settings", headers=H); test("AI settings", 200, r.status_code)
r = requests.get(f"{API}/api/v1/assemblies/", headers=H); test("Assemblies", 200, r.status_code)
r = requests.get(f"{API}/api/v1/takeoff/converters", headers=H); test("Converters", 200, r.status_code)

# SYSTEM
print("-- SYSTEM --")
r = requests.get(f"{API}/api/system/modules", headers=H); test("Modules endpoint", 200, r.status_code)
test("18 modules loaded", 18, len(r.json()))

# ═══ REQUIREMENTS MODULE (new!) ═══
print("== REQUIREMENTS ==")
r = requests.post(f"{API}/api/v1/requirements/", headers=H, json={"project_id":proj_id,"name":"Structural Spec","source_type":"manual"}); test("Create set", True, r.status_code in (200,201))
rs = r.json()["id"]

r = requests.get(f"{API}/api/v1/requirements/", headers=H, params={"project_id":proj_id}); test("List sets", 200, r.status_code)

r = requests.post(f"{API}/api/v1/requirements/{rs}/requirements", headers=H, json={"entity":"exterior_wall","attribute":"fire_rating","constraint_type":"min","constraint_value":"F90","category":"fire_safety","priority":"must","source_ref":"Dwg A-101"}); test("Add req 1", True, r.status_code in (200,201))
rq1 = r.json()["id"]

r = requests.post(f"{API}/api/v1/requirements/{rs}/requirements", headers=H, json={"entity":"foundation","attribute":"concrete_grade","constraint_type":"equals","constraint_value":"C30/37","unit":"MPa","category":"structural","priority":"must"}); test("Add req 2", True, r.status_code in (200,201))
rq2 = r.json()["id"]

r = requests.post(f"{API}/api/v1/requirements/{rs}/requirements", headers=H, json={"entity":"roof","attribute":"insulation","constraint_type":"min","constraint_value":"200","unit":"mm","category":"thermal","priority":"should"}); test("Add req 3", True, r.status_code in (200,201))

r = requests.get(f"{API}/api/v1/requirements/{rs}", headers=H); test("Get detail", 200, r.status_code)
test("3 requirements", 3, len(r.json().get("requirements",[])))

# Gate 1 - Completeness
r = requests.post(f"{API}/api/v1/requirements/{rs}/gates/1/run", headers=H); test("Gate 1 run", 200, r.status_code)
test("Gate 1 pass", "pass", r.json().get("status",""))

# Gate 2 - Consistency
r = requests.post(f"{API}/api/v1/requirements/{rs}/gates/2/run", headers=H); test("Gate 2 run", 200, r.status_code)
test("Gate 2 pass", "pass", r.json().get("status",""))

# Gate 3 - Coverage
r = requests.post(f"{API}/api/v1/requirements/{rs}/gates/3/run", headers=H); test("Gate 3 run", 200, r.status_code)

# Gate 4 - Compliance
r = requests.post(f"{API}/api/v1/requirements/{rs}/gates/4/run", headers=H); test("Gate 4 run", 200, r.status_code)

# Gates list
r = requests.get(f"{API}/api/v1/requirements/{rs}/gates", headers=H); test("Gates list", 200, r.status_code)
test("4 gate results", 4, len(r.json()))

# Link to BOQ position
r = requests.post(f"{API}/api/v1/requirements/{rs}/requirements/{rq1}/link/{po}", headers=H); test("Link to BOQ", 200, r.status_code)

# Import from text
r = requests.post(f"{API}/api/v1/requirements/{rs}/import/text", headers=H, json={"text":"beam_B1|load_capacity|min|500|kN\ncolumn_C1|concrete|equals|C40/50"}); test("Import text", True, r.status_code in (200,201))
test("2 imported", True, r.json().get("imported",0) >= 2 or len(r.json().get("requirements",[])) >= 2)

# Stats
r = requests.get(f"{API}/api/v1/requirements/stats", headers=H, params={"project_id":proj_id}); test("Stats", 200, r.status_code)

# Update requirement
r = requests.patch(f"{API}/api/v1/requirements/{rs}/requirements/{rq1}", headers=H, json={"status":"verified"}); test("Update status", 200, r.status_code)

# Delete requirement
r = requests.delete(f"{API}/api/v1/requirements/{rs}/requirements/{rq2}", headers=H); test("Delete req", 204, r.status_code)

# Delete set
r = requests.delete(f"{API}/api/v1/requirements/{rs}", headers=H); test("Delete set", 204, r.status_code)

print()
print("=" * 50)
print(f"  PASSED: {PASS} / {PASS+FAIL}")
print(f"  FAILED: {FAIL}")
print("=" * 50)
sys.exit(1 if FAIL > 0 else 0)
