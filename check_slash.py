"""Compare frontend API calls with backend routes for trailing slash mismatches."""
import re
import os
import glob

base_dir = 'backend/app/modules'
backend_routes = set()

# Extract all routes from router files
for router_file in sorted(glob.glob(f'{base_dir}/*/router.py')):
    module_dir = os.path.basename(os.path.dirname(router_file))
    prefix = f'/api/v1/{module_dir}'
    with open(router_file, 'r', encoding='utf-8') as f:
        content = f.read()
    for m in re.finditer(r'@(?:router|r)\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']*)["\']', content):
        method = m.group(1).upper()
        path = m.group(2)
        full_path = prefix + path
        backend_routes.add((method, full_path))

# Core routers
for core_file in glob.glob('backend/app/core/*_router.py'):
    with open(core_file, 'r', encoding='utf-8') as f:
        content = f.read()
    prefix_m = re.search(r'APIRouter\([^)]*prefix\s*=\s*["\']([^"\']*)["\']', content)
    core_prefix = prefix_m.group(1) if prefix_m else ''
    for m in re.finditer(r'@(?:router|r)\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']*)["\']', content):
        method = m.group(1).upper()
        path = m.group(2)
        full_path = core_prefix + path
        backend_routes.add((method, full_path))

# Main.py routes
with open('backend/app/main.py', 'r', encoding='utf-8') as f:
    content = f.read()
for m in re.finditer(r'@app\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']*)["\']', content):
    method = m.group(1).upper()
    path = m.group(2)
    backend_routes.add((method, path))

# Build backend lookup: (method, path_without_slash) -> actual_path
backend_lookup = {}
for method, path in backend_routes:
    key = path.rstrip('/')
    if not key:
        key = '/'
    backend_lookup[(method, key)] = path

# Now scan frontend
frontend_calls = []  # (file, line, method, url_with_api_prefix)

for ts_file in glob.glob('frontend/src/**/*.ts', recursive=True) + glob.glob('frontend/src/**/*.tsx', recursive=True):
    if 'node_modules' in ts_file:
        continue
    with open(ts_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line_no, line in enumerate(lines, 1):
        # apiGet('/v1/...') -> actual URL is /api/v1/...
        for m in re.finditer(r'api(Get|Post|Patch|Delete|Put)\s*(?:<[^>]*>)?\s*\(\s*[`"\']([^`"\']*)', line):
            http_method = m.group(1).upper()
            url = m.group(2)
            # Handle template literals - replace ${...} with {param}
            url = re.sub(r'\$\{[^}]+\}', '{param}', url)
            # Strip query params
            url = url.split('?')[0]
            actual_url = '/api' + url
            frontend_calls.append((ts_file, line_no, http_method, actual_url, line.strip()))

        # fetch('/api/v1/...')
        for m in re.finditer(r'fetch\s*\(\s*[`"\'](/api/v1/[^`"\']*)', line):
            url = m.group(1)
            url = re.sub(r'\$\{[^}]+\}', '{param}', url)
            url = url.split('?')[0]
            # Detect method from context
            if 'method: ' in line or "method:" in line:
                method_m = re.search(r"method:\s*['\"](\w+)['\"]", line)
                if method_m:
                    http_method = method_m.group(1).upper()
                else:
                    http_method = 'GET'
            else:
                http_method = 'GET'
            frontend_calls.append((ts_file, line_no, http_method, url, line.strip()))

        # fetch('/api/system/...')
        for m in re.finditer(r'fetch\s*\(\s*[`"\'](/api/(?:system|demo|health|marketplace|source)[^`"\']*)', line):
            url = m.group(1)
            url = re.sub(r'\$\{[^}]+\}', '{param}', url)
            url = url.split('?')[0]
            http_method = 'GET'
            if 'method: ' in line or "method:" in line:
                method_m = re.search(r"method:\s*['\"](\w+)['\"]", line)
                if method_m:
                    http_method = method_m.group(1).upper()
            frontend_calls.append((ts_file, line_no, http_method, url, line.strip()))

# Now compare
mismatches = []
for file, line_no, method, url, line_text in frontend_calls:
    url_stripped = url.rstrip('/')
    if not url_stripped:
        url_stripped = '/'

    # Try to find matching backend route
    # First try exact match
    if (method, url) in backend_routes:
        continue  # exact match, OK

    # Try without trailing slash
    if (method, url_stripped) in backend_routes:
        if url != url_stripped:
            # Frontend has trailing slash, backend doesn't
            mismatches.append((file, line_no, method, url, url_stripped, 'REMOVE trailing slash'))
        continue

    # Try with trailing slash
    url_with_slash = url_stripped + '/'
    if (method, url_with_slash) in backend_routes:
        if url != url_with_slash:
            # Frontend missing trailing slash, backend has it
            mismatches.append((file, line_no, method, url, url_with_slash, 'ADD trailing slash'))
        continue

    # Try matching with parametric routes
    # Replace {param} in frontend URL and try to match pattern
    url_pattern = re.sub(r'\{[^}]+\}', '{PARAM}', url)
    url_pattern_stripped = url_pattern.rstrip('/')

    found = False
    for (b_method, b_path) in backend_routes:
        if b_method != method:
            continue
        b_pattern = re.sub(r'\{[^}]+\}', '{PARAM}', b_path)
        if b_pattern == url_pattern:
            found = True
            break
        if b_pattern == url_pattern_stripped:
            if url != url_stripped:
                mismatches.append((file, line_no, method, url, b_path, 'REMOVE trailing slash (parametric)'))
            found = True
            break
        b_pattern_stripped = b_pattern.rstrip('/')
        if b_pattern_stripped == url_pattern_stripped:
            if url_pattern != b_pattern:
                expected = b_path  # Use the actual backend path pattern
                mismatches.append((file, line_no, method, url, expected, 'FIX trailing slash (parametric)'))
            found = True
            break

print(f"\n{'='*80}")
print(f"MISMATCHES FOUND: {len(mismatches)}")
print(f"{'='*80}\n")

for file, line_no, method, current, expected, action in sorted(mismatches):
    print(f"  {file}:{line_no}")
    print(f"    {method:7s} {current}")
    print(f"    -> should be: {expected}")
    print(f"    Action: {action}")
    print()
