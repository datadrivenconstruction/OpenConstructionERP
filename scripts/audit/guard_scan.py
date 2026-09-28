"""Guard-bypass scanner (lane S8). Reads backend/app/modules, writes JSON + text.

Usage: python guard_scan.py <modules_root> <out_prefix>

1. Finds refusal guards: functions whose body raises 409/422/423 (or 400/403 under a
   lock-ish condition, or a domain Locked/Immutable/... error) guarded by a status or
   lock attribute.
2. For each guard, the protected models are the ones its callers write.
3. Candidates: every non-repository function in the same module that writes one of those
   models and is not covered by an equivalent guard (downward through its own calls, or
   because every in-module caller of it is covered).
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.abspath(sys.argv[1])
OUT = sys.argv[2]
FOLLOW_HELPERS = os.environ.get("FOLLOW_HELPERS", "1") == "1"

LOCKISH_ATTR = re.compile(
    r"^(status|state|stage|phase|lifecycle|lifecycle_state|workflow_status|workflow_state|approval_status|"
    r"payment_status|review_status|contract_status|claim_status|invoice_status|period_status|"
    r"is_locked|locked|locked_at|locked_by|lock|is_closed|closed|closed_at|is_final|final|finalized|finalised|"
    r"is_finalized|is_approved|approved|approved_at|approved_by|signed|signed_at|is_signed|certified|"
    r"certified_at|is_certified|posted|is_posted|posted_at|issued|is_issued|issued_at|is_published|published|"
    r"published_at|frozen|is_frozen|submitted|is_submitted|submitted_at|is_void|voided|voided_at|"
    r"is_archived|archived|archived_at|is_baseline|is_readonly|read_only|readonly|is_read_only|is_editable|"
    r"editable|is_immutable|immutable|sealed|is_sealed|released|is_released|awarded|is_awarded|awarded_at|"
    r"is_completed|completed_at|cancelled_at|is_cancelled|executed|executed_at|is_executed|is_paid|paid_at|"
    r"is_committed|committed|committed_at|is_active|is_current|is_superseded|superseded|superseded_by|"
    r"is_frozen_baseline|baseline_locked|is_open|revision_locked|is_template|is_system|is_builtin|"
    r"is_default|approval_state|sign_status|signature_status|is_settled|settled|is_reconciled|reconciled)$"
)
LOCKISH_WORD = re.compile(
    r"(lock|status|state|frozen|immutable|editable|mutable|writable|final|approved|signed|certified|posted|"
    r"issued|closed|awarded|sealed|terminal|decided|published|submitted|void|archived|baseline|readonly|"
    r"read_only|settled|reconciled|executed|committed|released)",
    re.I,
)
LOCKISH_VALUES = {
    "approved", "locked", "signed", "certified", "paid", "closed", "awarded", "issued", "posted", "final",
    "finalized", "finalised", "submitted", "cancelled", "canceled", "void", "voided", "archived", "completed",
    "released", "published", "executed", "active", "draft", "open", "superseded", "rejected", "settled",
    "reconciled", "committed", "frozen", "sealed", "terminated", "suspended", "accepted", "sent", "in_review",
    "under_review", "pending_approval", "baseline", "certified_paid", "partially_paid", "invoiced", "billed",
}
GUARD_NAME = re.compile(
    r"^_*(assert|ensure|check|guard|require|verify|forbid|refuse|reject_if|raise_if|deny|block|protect|"
    r"validate_(not_)?(locked|mutable|editable|writable|state|status|open|draft)|fail_if|must_be)"
    r"|(mutable|editable|writable|not_locked|unlocked|is_open|_open|_draft|not_frozen|not_closed|"
    r"not_final|not_signed|not_approved|modifiable|changeable)$",
    re.I,
)
TRANSITION_NAME = re.compile(
    r"^_*(approve|submit|reject|close|reopen|lock|unlock|sign|certify|issue|cancel|void|publish|unpublish|"
    r"activate|deactivate|complete|award|archive|unarchive|restore|transition|set_status|change_status|"
    r"update_status|mark_|finali[sz]e|post|execute|release|freeze|unfreeze|accept|decline|send|resend|"
    r"withdraw|revert|return_|start|stop|pause|resume|open|settle|reconcile|commit|supersede|baseline|"
    r"terminate|suspend|advance|move_to|promote|escalate|resolve|verify|confirm|invoice|pay|apply_status|"
    r"record_payment|handle_|on_)",
    re.I,
)
EDIT_NAME = re.compile(
    r"^_*(update|delete|edit|add|create|remove|patch|set|replace|import|bulk|upsert|save|modify|change|"
    r"append|insert|move|reorder|duplicate|clone|copy|merge|split|link|unlink|attach|detach|assign|"
    r"unassign|apply|recalc|recompute|rename|clear|reset|purge|sync|write|put|store|upload)",
    re.I,
)
REPO_WRITE_NAME = re.compile(
    r"^_*(create|add|update|delete|remove|save|upsert|set_|bulk|insert|replace|clear|purge|soft_delete|"
    r"archive|restore|mark_|write|store|put|increment|decrement|reorder|move|attach|detach|link|unlink|"
    r"assign|unassign|touch|bump|reset|apply|merge|record|append|persist|commit|patch)",
    re.I,
)
REFUSAL_EXC = re.compile(
    r"(Locked|Immutable|Conflict|NotAllowed|Forbidden|Frozen|StateError|Status|Transition|Closed|ReadOnly|"
    r"Readonly|NotEditable|NotMutable|Finali[sz]ed|Signed|Certified|Approved|Posted|Issued|Guard|Refus|"
    r"Invariant|Business|Domain|Workflow|Lifecycle)",
)
GUARD_CODES = {409, 422, 423}
SOFT_CODES = {400, 403}
BOOKKEEPING_MODEL = re.compile(
    r"(ActivityLog|AuditLog|Audit|Activity|Event|Notification|History|Log|Snapshot|Outbox|Message|"
    r"Comment|Attachment|Watcher|Subscription|Idempotency|Job|Task$|Webhook|Revision)$"
)
SESSION_NAMES = {"session", "db", "_session", "_db", "s", "sess", "async_session"}


def status_code_of(call: ast.Call) -> int | None:
    for kw in call.keywords:
        if kw.arg == "status_code":
            return _code(kw.value)
    if call.args:
        return _code(call.args[0])
    return None


def _code(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute):
        m = re.search(r"HTTP_(\d{3})", node.attr)
        if m:
            return int(m.group(1))
    if isinstance(node, ast.Name):
        m = re.search(r"(\d{3})", node.id)
        if m:
            return int(m.group(1))
    return None


def names_in_annotation(node: ast.AST | None) -> set[str]:
    out: set[str] = set()
    if node is None:
        return out
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return out
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


# ── pass 1: models ─────────────────────────────────────────────────────────


def iter_py(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__", "migrations", "alembic")]
        for f in filenames:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


PARSED: dict[str, ast.Module] = {}


def parse(path: str) -> ast.Module | None:
    if path in PARSED:
        return PARSED[path]
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (SyntaxError, UnicodeDecodeError):
        tree = None
    PARSED[path] = tree
    return tree


MODELS: dict[str, dict] = {}  # name -> {table, module, file}
TABLE_TO_MODEL: dict[str, str] = {}
CASCADE_CHILDREN: dict[str, set[str]] = defaultdict(set)  # parent model -> child models deleted with it

files = list(iter_py(ROOT))
if os.environ.get("ONLY"):
    _only = set(os.environ["ONLY"].split(","))
    files = [p for p in files if os.path.relpath(p, ROOT).split(os.sep)[0] in _only]
for path in files:
    tree = parse(path)
    if tree is None:
        continue
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        table = None
        for st in node.body:
            if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in st.targets):
                if isinstance(st.value, ast.Constant):
                    table = st.value.value
        if table:
            mod = os.path.relpath(path, ROOT).split(os.sep)[0]
            MODELS[node.name] = {"table": table, "module": mod, "file": path, "node": node}
            TABLE_TO_MODEL[table] = node.name

for name, info in MODELS.items():
    node = info["node"]
    for st in node.body:
        for n in ast.walk(st):
            if isinstance(n, ast.Call):
                fn = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")
                if fn == "ForeignKey" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    cascade = any(kw.arg == "ondelete" and isinstance(kw.value, ast.Constant)
                                  and str(kw.value.value).upper() == "CASCADE" for kw in n.keywords)
                    if cascade:
                        tbl = n.args[0].value.rsplit(".", 1)[0]
                        parent = TABLE_TO_MODEL.get(tbl)
                        if parent and parent != name:
                            CASCADE_CHILDREN[parent].add(name)
                if fn == "relationship" and n.args:
                    target = n.args[0].value if isinstance(n.args[0], ast.Constant) else (
                        n.args[0].id if isinstance(n.args[0], ast.Name) else None)
                    casc = next((kw.value.value for kw in n.keywords if kw.arg == "cascade"
                                 and isinstance(kw.value, ast.Constant)), "")
                    if target and "delete" in str(casc) and target in MODELS and target != name:
                        CASCADE_CHILDREN[name].add(target)
    info.pop("node")


# ── pass 2: per-module functions ──────────────────────────────────────────


class Func:
    def __init__(self, module, path, cls, node):
        self.module = module
        self.path = path
        self.rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        self.cls = cls
        self.node = node
        self.name = node.name
        self.line = node.lineno
        self.is_repo = bool(cls and re.search(r"(Repository|Repo|Store|DAO|Dao)$", cls)) or \
            os.path.basename(path).startswith("repositor")
        self.is_router = "router" in os.path.basename(path) or any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in
            ("get", "post", "put", "patch", "delete", "api_route")
            for d in node.decorator_list)
        self.calls: list[tuple] = []
        self.writes: list[tuple] = []  # (model, kind, line)
        self.guard_raises: list[dict] = []
        self.ret_models: set[str] = set()
        self.ret_self_model = False
        self.lockish_refs: set[str] = set()

    @property
    def fid(self):
        return f"{self.rel}:{self.cls + '.' if self.cls else ''}{self.name}"


def module_of(path):
    return os.path.relpath(path, ROOT).split(os.sep)[0]


by_module_files: dict[str, list[str]] = defaultdict(list)
for p in files:
    by_module_files[module_of(p)].append(p)

results = {"guards": [], "candidates": [], "modules": 0}


def lockish_in_expr(expr: ast.AST) -> tuple[set[str], set[str]]:
    attrs, vals = set(), set()
    for n in ast.walk(expr):
        if isinstance(n, ast.Attribute) and LOCKISH_ATTR.match(n.attr):
            attrs.add(n.attr)
        elif isinstance(n, ast.Name) and re.search(r"(STATUS|STATE|LOCK|FROZEN|TERMINAL|IMMUTABLE|EDITABLE|"
                                                   r"MUTABLE|DECIDED|FINAL|CLOSED|SIGNED|APPROVED|ALLOWED)", n.id):
            attrs.add(n.id)
        elif isinstance(n, ast.Attribute) and re.search(r"(STATUS|STATE|LOCK|FROZEN|TERMINAL|IMMUTABLE|EDITABLE|"
                                                        r"MUTABLE|DECIDED|FINAL|CLOSED|SIGNED|APPROVED|ALLOWED)", n.attr):
            attrs.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.lower() in LOCKISH_VALUES:
            vals.add(n.value.lower())
        elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str) \
                and LOCKISH_ATTR.match(n.slice.value):
            attrs.add(n.slice.value)
    return attrs, vals


for module, mfiles in sorted(by_module_files.items()):
    classes: dict[str, dict] = {}
    funcs: list[Func] = []
    mod_funcs: dict[str, list[Func]] = defaultdict(list)  # name -> funcs
    for path in mfiles:
        tree = parse(path)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                f = Func(module, path, None, node)
                funcs.append(f)
                mod_funcs[node.name].append(f)
            elif isinstance(node, ast.ClassDef):
                info = {"bases": [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases],
                        "methods": {}, "attr_types": {}, "model": None, "path": path}
                for st in node.body:
                    if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) \
                            and st.targets[0].id in ("model", "_model", "model_class", "MODEL", "orm_model") \
                            and isinstance(st.value, ast.Name):
                        info["model"] = st.value.id
                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                        for nm in names_in_annotation(st.annotation):
                            if nm[:1].isupper():
                                info["attr_types"].setdefault(st.target.id, nm)
                    if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        f = Func(module, path, node.name, st)
                        funcs.append(f)
                        info["methods"][st.name] = f
                        mod_funcs[st.name].append(f)
                        for n in ast.walk(st):
                            tgt_val = None
                            if isinstance(n, ast.Assign) and len(n.targets) == 1:
                                tgt, tgt_val = n.targets[0], n.value
                            elif isinstance(n, ast.AnnAssign):
                                tgt, tgt_val = n.target, n.value
                                if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                                    for nm in names_in_annotation(n.annotation):
                                        if nm[:1].isupper():
                                            info["attr_types"].setdefault(tgt.attr, nm)
                            else:
                                continue
                            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self" \
                                    and isinstance(tgt_val, ast.Call):
                                fn = tgt_val.func
                                cname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                                if cname and cname[:1].isupper():
                                    info["attr_types"].setdefault(tgt.attr, cname)
                classes[node.name] = info
                if info["model"] is None and re.search(r"(Repository|Repo)$", node.name):
                    guess = re.sub(r"(Repository|Repo)$", "", node.name)
                    if guess in MODELS:
                        info["model"] = guess

    # repo model fallback: most referenced model in class body
    for cname, info in classes.items():
        if info["model"] is None and re.search(r"(Repository|Repo|Store)$", cname):
            counts = defaultdict(int)
            for f in info["methods"].values():
                for n in ast.walk(f.node):
                    if isinstance(n, ast.Name) and n.id in MODELS:
                        counts[n.id] += 1
            if counts:
                info["model"] = max(counts, key=counts.get)

    def class_model(cname):
        seen = set()
        while cname and cname not in seen:
            seen.add(cname)
            info = classes.get(cname)
            if info is None:
                return None
            if info["model"]:
                return info["model"]
            cname = next((b for b in info["bases"] if b in classes), None)
        return None

    def find_method(cname, meth):
        seen = set()
        while cname and cname not in seen:
            seen.add(cname)
            info = classes.get(cname)
            if info is None:
                return None
            if meth in info["methods"]:
                return info["methods"][meth]
            cname = next((b for b in info["bases"] if b in classes), None)
        return None

    # ── pre-pass: return types ──
    for f in funcs:
        f.ret_models = {nm for nm in names_in_annotation(f.node.returns) if nm in MODELS}
        for n in ast.walk(f.node):
            if isinstance(n, ast.Return) and n.value is not None:
                for x in ast.walk(n.value):
                    if isinstance(x, ast.Attribute) and x.attr == "model" and isinstance(x.value, ast.Name)                             and x.value.id in ("self", "cls"):
                        f.ret_self_model = True
                    if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in MODELS                             and not f.ret_models:
                        f.ret_models = {x.func.id}

    # ── pre-pass: guard factories (p181) ──
    # A function that *returns* an HTTPException (or a refusal-named domain error) is a factory:
    # `raise _conflict(...)` / `raise self._refuse(409, ...)` raises through it. Record the status
    # code it builds, either a literal or the index/name of the parameter that carries it.
    factories: dict[str, dict] = {}
    for f in funcs:
        params = [a.arg for a in f.node.args.args if a.arg not in ("self", "cls")]
        for n in ast.walk(f.node):
            if not (isinstance(n, ast.Return) and isinstance(n.value, ast.Call)):
                continue
            fn = n.value.func
            en = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if en not in ("HTTPException", "_HTTPException") and not (en and REFUSAL_EXC.search(en)):
                continue
            code_node = next((kw.value for kw in n.value.keywords if kw.arg == "status_code"),
                             n.value.args[0] if n.value.args else None)
            info = {"exc": "HTTPException" if "HTTPException" in en else en, "code": None, "param": None}
            if code_node is not None:
                info["code"] = _code(code_node) if not (isinstance(code_node, ast.Name) and code_node.id in params) \
                    else None
                if isinstance(code_node, ast.Name) and code_node.id in params:
                    info["param"] = (params.index(code_node.id), code_node.id)
            factories[f.name] = info
            break

    def factory_raise(call: ast.Call) -> tuple[str, int | None] | None:
        fn = call.func
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in ("self", "cls"):
            name = fn.attr
        else:
            return None
        info = factories.get(name)
        if info is None:
            return None
        code = info["code"]
        if info["param"] is not None:
            idx, pname = info["param"]
            node = next((kw.value for kw in call.keywords if kw.arg == pname),
                        call.args[idx] if len(call.args) > idx else None)
            code = _code(node) if node is not None else None
        return info["exc"], code

    # ── analyse bodies ──
    for f in funcs:
        cls = f.cls
        vtypes: dict[str, str] = {}  # var -> model name or class name or SELF_MODEL
        for a in f.node.args.args + f.node.args.kwonlyargs:
            for nm in names_in_annotation(a.annotation):
                if nm in MODELS or nm in classes:
                    vtypes[a.arg] = nm
                    break
        f.ret_models = {nm for nm in names_in_annotation(f.node.returns) if nm in MODELS}

        def recv_class(expr):
            """Class name of a receiver expression, if known."""
            if isinstance(expr, ast.Name):
                t = vtypes.get(expr.id)
                if t in classes:
                    return t
                return None
            if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id == "self" and cls:
                cinfo = classes.get(cls)
                seen = set()
                c = cls
                while c and c not in seen:
                    seen.add(c)
                    ci = classes.get(c)
                    if ci is None:
                        break
                    if expr.attr in ci["attr_types"]:
                        return ci["attr_types"][expr.attr]
                    c = next((b for b in ci["bases"] if b in classes), None)
            return None

        def infer(expr):
            if isinstance(expr, ast.Await):
                return infer(expr.value)
            if isinstance(expr, ast.Name):
                return vtypes.get(expr.id)
            if isinstance(expr, ast.Call):
                fn = expr.func
                if isinstance(fn, ast.Name):
                    if fn.id in MODELS or fn.id in classes:
                        return fn.id
                    cands = mod_funcs.get(fn.id)
                    if cands and cands[0].ret_models:
                        return next(iter(cands[0].ret_models))
                if isinstance(fn, ast.Attribute):
                    if fn.attr == "get" and expr.args:
                        a0 = expr.args[0]
                        if isinstance(a0, ast.Name) and a0.id in MODELS:
                            return a0.id
                        if isinstance(a0, ast.Attribute) and a0.attr == "model":
                            return "SELF_MODEL"
                    # self.meth(...)
                    if isinstance(fn.value, ast.Name) and fn.value.id == "self" and cls:
                        m = find_method(cls, fn.attr)
                        if m is not None and m.ret_models:
                            return next(iter(m.ret_models))
                        if m is not None and m.ret_self_model:
                            return "SELF_MODEL"
                    rc = recv_class(fn.value)
                    if rc:
                        m = find_method(rc, fn.attr)
                        if m is not None and m.ret_models:
                            return next(iter(m.ret_models))
                        if re.match(r"^_*(get|find|load|fetch|by_|one|first|require|list|all)", fn.attr):
                            cm = class_model(rc)
                            if cm:
                                return cm
                # select(Model) anywhere inside
                for n in ast.walk(expr):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "select" and n.args:
                        a0 = n.args[0]
                        if isinstance(a0, ast.Name) and a0.id in MODELS:
                            return a0.id
                        if isinstance(a0, ast.Attribute) and a0.attr == "model":
                            return "SELF_MODEL"
                # obj.scalars().first() chains
                if isinstance(fn, ast.Attribute):
                    return infer(fn.value) if fn.attr in ("scalar_one_or_none", "scalar_one", "first", "one",
                                                         "one_or_none", "scalar", "all", "scalars") else None
            if isinstance(expr, ast.Attribute) and expr.attr in ("scalars",):
                return infer(expr.value)
            if isinstance(expr, (ast.ListComp, ast.List)) and isinstance(expr, ast.List) and expr.elts:
                return infer(expr.elts[0])
            return None

        # pass in statement order so vtypes fill before use
        body_nodes = []
        for n in ast.walk(f.node):
            body_nodes.append(n)
        body_nodes.sort(key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)))
        for n in body_nodes:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                t = infer(n.value)
                if t:
                    vtypes[n.targets[0].id] = t
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                t = None
                for nm in names_in_annotation(n.annotation):
                    if nm in MODELS or nm in classes:
                        t = nm
                        break
                t = t or (infer(n.value) if n.value else None)
                if t:
                    vtypes[n.target.id] = t
            elif isinstance(n, (ast.For, ast.AsyncFor)) and isinstance(n.target, ast.Name):
                t = infer(n.iter)
                if t:
                    vtypes[n.target.id] = t
            elif isinstance(n, ast.Return) and n.value is not None:
                t = infer(n.value)
                if t == "SELF_MODEL":
                    f.ret_self_model = True
                elif t in MODELS and not f.ret_models:
                    f.ret_models = {t}

        def model_of_var(expr):
            if isinstance(expr, ast.Name):
                if expr.id == "self":
                    return None
                return vtypes.get(expr.id) or ("?" + expr.id)
            if isinstance(expr, ast.Call):
                return infer(expr) or "?call"
            if isinstance(expr, ast.Attribute):
                return "?" + ast.unparse(expr)[:40]
            return "?"

        for n in body_nodes:
            # attribute writes
            targets = []
            if isinstance(n, ast.Assign):
                targets = n.targets
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
                targets = [n.target]
            for t in targets:
                for tt in (t.elts if isinstance(t, ast.Tuple) else [t]):
                    base = tt
                    while isinstance(base, ast.Subscript):
                        base = base.value
                    if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id not in ("self", "cls"):
                        m = vtypes.get(base.value.id)
                        if m in MODELS or m == "SELF_MODEL":
                            f.writes.append((m, "set:" + base.attr, n.lineno))
            if isinstance(n, ast.Call):
                fn = n.func
                # setattr
                if isinstance(fn, ast.Name) and fn.id == "setattr" and n.args:
                    m = model_of_var(n.args[0])
                    if m in MODELS or m == "SELF_MODEL":
                        f.writes.append((m, "setattr", n.lineno))
                # session.delete / add / merge
                if isinstance(fn, ast.Attribute) and fn.attr in ("delete", "add", "add_all", "merge") and n.args:
                    recv = fn.value
                    rname = recv.id if isinstance(recv, ast.Name) else (recv.attr if isinstance(recv, ast.Attribute) else "")
                    if rname in SESSION_NAMES or rname.endswith("session") or rname == "db":
                        a0 = n.args[0]
                        kind = {"delete": "delete", "add": "create", "add_all": "create", "merge": "merge"}[fn.attr]
                        if fn.attr == "add_all":
                            if isinstance(a0, (ast.List, ast.ListComp)):
                                el = a0.elts[0] if isinstance(a0, ast.List) and a0.elts else (a0.elt if isinstance(a0, ast.ListComp) else None)
                                m = model_of_var(el) if el is not None else "?"
                            else:
                                m = model_of_var(a0)
                        else:
                            m = model_of_var(a0)
                        if kind == "create" and isinstance(a0, ast.Name) and m and m.startswith("?"):
                            # add(var) where var = Model(...) handled by vtypes; else unknown
                            pass
                        f.writes.append((m, kind, n.lineno))
                # sqlalchemy core update/delete/insert
                fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in ("sa", "sqlalchemy") else None)
                if fname and re.match(r"^(sa_|sql_|sqla_|pg_|sqlite_|_)?(update|delete|insert)$", fname) and n.args:
                    a0 = n.args[0]
                    kind = "bulk_" + re.sub(r"^(sa_|sql_|sqla_|pg_|sqlite_|_)", "", fname)
                    if isinstance(a0, ast.Name) and a0.id in MODELS:
                        f.writes.append((a0.id, kind, n.lineno))
                    elif isinstance(a0, ast.Attribute) and a0.attr == "model":
                        f.writes.append(("SELF_MODEL", kind, n.lineno))
                    elif isinstance(a0, ast.Attribute) and a0.attr == "__table__" and isinstance(a0.value, ast.Name) and a0.value.id in MODELS:
                        f.writes.append((a0.value.id, kind, n.lineno))
                # call edges
                if isinstance(fn, ast.Name):
                    f.calls.append(("name", fn.id, n.lineno))
                elif isinstance(fn, ast.Attribute):
                    if isinstance(fn.value, ast.Name) and fn.value.id in ("self", "cls"):
                        f.calls.append(("self", fn.attr, n.lineno))
                    else:
                        rc = recv_class(fn.value)
                        if rc:
                            f.calls.append(("cls", rc, fn.attr, n.lineno))
                        else:
                            f.calls.append(("any", fn.attr, n.lineno))
                # function references passed as callables (e.g. run_in_threadpool(self.x))
                for a in n.args:
                    if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) and a.value.id == "self":
                        f.calls.append(("self", a.attr, n.lineno))

        # guard raises
        parents = {}
        for p in ast.walk(f.node):
            for c in ast.iter_child_nodes(p):
                parents[c] = p
        body_attrs, _ = lockish_in_expr(f.node)
        f.lockish_refs = body_attrs
        for n in body_nodes:
            if not isinstance(n, ast.Raise) or n.exc is None:
                continue
            exc = n.exc
            code, exc_name, via = None, None, None
            if isinstance(exc, ast.Call):
                fn = exc.func
                exc_name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                if exc_name == "HTTPException":
                    code = status_code_of(exc)
                else:
                    fr = factory_raise(exc)
                    if fr is not None:
                        exc_name, code = fr
                        via = ast.unparse(exc.func)
            elif isinstance(exc, ast.Name):
                exc_name = exc.id
            # enclosing if tests
            conds = []
            p = parents.get(n)
            while p is not None and p is not f.node:
                if isinstance(p, ast.If):
                    conds.append(p.test)
                p = parents.get(p)
            attrs, vals = set(), set()
            cond_models = set()
            for c in conds:
                a, v = lockish_in_expr(c)
                attrs |= a
                vals |= v
                for x in ast.walk(c):
                    if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)                             and vtypes.get(x.value.id) in MODELS:
                        cond_models.add(vtypes[x.value.id])
            msg = ast.unparse(exc)[:200] if exc is not None else ""
            msg_lock = bool(re.search(r"(locked|immutable|cannot be (modified|edited|changed|deleted)|can only be|"
                                      r"frozen|already (approved|signed|certified|posted|issued|closed|awarded|"
                                      r"submitted|finali[sz]ed|paid|locked)|read-only|read only|is (approved|signed|"
                                      r"certified|closed|posted|issued|final|locked)|not editable|no longer)", msg, re.I))
            is_guard = False
            if exc_name == "HTTPException":
                if code in GUARD_CODES and (attrs or vals or msg_lock or body_attrs):
                    is_guard = True
                elif code in SOFT_CODES and (attrs and (vals or msg_lock)):
                    is_guard = True
                elif code in SOFT_CODES and msg_lock:
                    is_guard = True
            elif exc_name and REFUSAL_EXC.search(exc_name) and (attrs or msg_lock):
                is_guard = True
            elif exc_name in ("ValueError", "PermissionError", "RuntimeError") and attrs and (vals or msg_lock):
                is_guard = True
            cond_src = " ".join(ast.unparse(c) for c in conds)
            if is_guard and re.search(r"(new_status|\btarget\b|transition|allowed_|data\.status|payload\.status|"
                                      r"body\.status|requested|to_status|next_status|new_state)", cond_src) \
                    and not msg_lock:
                is_guard = False  # a transition-validity check, not an immutability guard
            if is_guard:
                f.guard_raises.append({"line": n.lineno, "code": code, "exc": exc_name,
                                       "attrs": sorted(attrs), "vals": sorted(vals),
                                       "cond": " / ".join(ast.unparse(c)[:120] for c in conds[:2]),
                                       "msg_lock": msg_lock, "cond_based": bool(attrs or vals or msg_lock),
                                       "via": via, "models": sorted(cond_models)})

    # ── resolution ──
    fid_map = {f.fid: f for f in funcs}

    def resolve(f: Func, call) -> list[Func]:
        kind = call[0]
        if kind == "self":
            if f.cls:
                m = find_method(f.cls, call[1])
                return [m] if m else []
            return []
        if kind == "cls":
            m = find_method(call[1], call[2])
            return [m] if m else []
        if kind == "name":
            nm = call[1]
            if nm in classes:
                return []
            return [g for g in mod_funcs.get(nm, []) if g.cls is None]
        if kind == "any":
            nm = call[1]
            if nm.startswith("__") or nm in ("get", "list", "delete", "update", "create", "add", "execute", "flush",
                                             "commit", "refresh", "get_by_id", "append", "extend", "items", "keys",
                                             "values", "pop", "setdefault", "scalar", "scalars", "all", "first",
                                             "where", "order_by", "limit", "offset", "join", "filter", "one",
                                             "model_dump", "model_validate", "format", "strip", "lower", "upper",
                                             "split", "join", "replace", "copy", "count", "sort", "remove",
                                             "discard", "close", "run", "send", "read", "write", "save", "load"):
                return []
            cands = [g for g in mod_funcs.get(nm, []) if g.cls is not None and not g.is_repo]
            return cands if len(cands) <= 2 else []
        return []

    callees: dict[str, list[tuple[Func, int]]] = defaultdict(list)
    callers: dict[str, set[str]] = defaultdict(set)
    for f in funcs:
        for call in f.calls:
            for g in resolve(f, call):
                if g is f:
                    continue
                callees[f.fid].append((g, call[-1]))
                callers[g.fid].add(f.fid)

    # repo write effect per (receiver class, method)
    def repo_writes(g: Func, recv_cls: str | None) -> list[tuple]:
        cm = class_model(recv_cls) if recv_cls else class_model(g.cls)
        out = []
        for (m, k, ln) in g.writes:
            out.append((cm if m == "SELF_MODEL" else m, k, ln))
        # repo helper chain one level (self.x inside repo)
        for (cg, ln) in callees.get(g.fid, []):
            if cg.is_repo:
                for (m, k, _l) in cg.writes:
                    out.append((cm if m == "SELF_MODEL" else m, k + "@" + cg.name, ln))
        out = [(m, k, ln) for (m, k, ln) in out if m and m in MODELS]
        if not out and REPO_WRITE_NAME.match(g.name) and cm:
            out.append((cm, "repo:" + g.name, g.line))
        return out

    # primary writes of non-repo functions: direct writes + writes through repo calls
    prim: dict[str, list[tuple]] = {}
    for f in funcs:
        if f.is_repo:
            continue
        ws = [(m, k, ln) for (m, k, ln) in f.writes if m in MODELS]
        for call in f.calls:
            targets = resolve(f, call)
            for g in targets:
                if g.is_repo:
                    recv = call[1] if call[0] == "cls" else None
                    if call[0] == "self":
                        recv = None
                    for (m, k, _ln) in repo_writes(g, recv or g.cls):
                        ws.append((m, "via " + (recv or g.cls or "") + "." + g.name + ":" + k, call[-1]))
        # cascade deletes
        extra = []
        for (m, k, ln) in ws:
            if "delete" in k:
                stack, seen = [m], {m}
                while stack:
                    p = stack.pop()
                    for c in CASCADE_CHILDREN.get(p, ()):
                        if c not in seen:
                            seen.add(c)
                            stack.append(c)
                            extra.append((c, "cascade-delete from " + m, ln))
        prim[f.fid] = ws + extra

    # ── guards ──
    guard_funcs = []
    for f in funcs:
        if f.is_repo or not f.guard_raises:
            continue
        nm = f.name
        has_callers = bool(callers.get(f.fid))
        own_writes = [w for w in prim.get(f.fid, []) if not BOOKKEEPING_MODEL.search(w[0])]
        if GUARD_NAME.search(nm) or (has_callers and not own_writes and not f.is_router):
            gtype = "helper"
        elif own_writes and not f.is_router and EDIT_NAME.match(nm) and not TRANSITION_NAME.match(nm)                 and any(gr["cond_based"] for gr in f.guard_raises):
            gtype = "inline"
        elif own_writes and f.is_router and EDIT_NAME.match(nm.replace("_endpoint", ""))                 and not TRANSITION_NAME.match(nm) and any(gr["cond_based"] for gr in f.guard_raises):
            gtype = "inline"
        else:
            continue
        attrs = set()
        vals = set()
        for gr in f.guard_raises:
            attrs |= set(gr["attrs"])
            vals |= set(gr["vals"])
        if not attrs:
            attrs = set(a for a in f.lockish_refs)
        guard_funcs.append((f, gtype, frozenset(attrs), frozenset(vals)))

    # reach: does f reach any guard in group (downward)?
    from functools import lru_cache

    GENERIC = {"status", "state", "stage", "phase"}
    sigs = {g.fid: (attrs, vals) for (g, gtype, attrs, vals) in guard_funcs}

    def same_group(s1, s2) -> bool:
        a1, v1 = s1
        a2, v2 = s2
        if not (a1 & a2):
            return False
        specific = (a1 & a2) - GENERIC
        if specific:
            return True
        # generic status/state: values must match (or both empty)
        return v1 == v2 or (bool(v1 & v2) and (v1 <= v2 or v2 <= v1))

    REACH: dict[str, frozenset] = {}

    def reach_of(start: str) -> frozenset:
        r = REACH.get(start)
        if r is not None:
            return r
        stack, seen = [start], {start}
        while stack:
            x = stack.pop()
            for (g, _ln) in callees.get(x, []):
                if g.fid not in seen and not g.is_repo:
                    seen.add(g.fid)
                    stack.append(g.fid)
        r = frozenset(seen)
        REACH[start] = r
        return r

    def down_reach(start: str, targets: set[str]) -> bool:
        return not reach_of(start).isdisjoint(targets)

    def has_own_check(fid: str, sig) -> bool:
        f = fid_map[fid]
        attrs, vals = sig
        for gr in f.guard_raises:
            ga, gv = set(gr["attrs"]), set(gr["vals"])
            if not gr["attrs"] and gr["msg_lock"]:
                return True
            if ga & attrs and ((ga & attrs) - GENERIC or not vals or not gv or gv & vals):
                return True
        return False

    HELPER_COVER: dict[tuple, str] = {}
    CUR_PROTECTED: set[str] = set()

    def helper_check(fid: str, sig) -> bool:
        """S8s: one level of helper calls. The writer calls a same-module function that itself
        raises an equivalent guard (a helper the group signature did not match)."""
        if not FOLLOW_HELPERS:
            return False
        for (g, _ln) in callees.get(fid, []):
            if g.is_repo or g.fid == fid:
                continue
            if helper_raises_equivalent(g, sig):
                HELPER_COVER[(fid, sig)] = g.fid
                return True
        return False

    def helper_raises_equivalent(g: Func, sig) -> bool:
        """A helper counts only when it refuses on the state of a record the writer writes.

        Model match first: the refusal's condition reads a model the guard protects (or,
        when the condition names no model, the helper takes one as a typed parameter). Without
        any model evidence fall back to a non-generic lock attribute shared with the guard. A
        bare `status` overlap, a refusal-sounding name or message alone is not enough, so a
        precondition such as a compliance or vendor gate is not credited as a guard."""
        attrs, vals = sig
        if not g.guard_raises:
            return False
        param_models = set()
        for a in g.node.args.args + g.node.args.kwonlyargs:
            param_models |= {nm for nm in names_in_annotation(a.annotation) if nm in MODELS}
        for gr in g.guard_raises:
            ms = set(gr.get("models") or []) or param_models
            if ms and not ms & CUR_PROTECTED:
                continue  # refuses on some other record's state
            ga, gv = set(gr["attrs"]), set(gr["vals"])
            specific = bool((ga & attrs) - GENERIC)
            same_vals = bool(ga & attrs and vals and gv and gv & vals)
            if specific or same_vals:
                return True
            if gr.get("models") and GUARD_NAME.search(g.name):
                return True  # a named guard whose condition reads the protected record
        return False

    def covered(fid: str, targets: set[str], attrs: frozenset, memo: dict, stack=()) -> bool:
        if fid in memo:
            return memo[fid]
        if fid in stack:
            return True
        if down_reach(fid, targets) or has_own_check(fid, attrs) or helper_check(fid, attrs):
            memo[fid] = True
            return True
        cs = callers.get(fid, set())
        if not cs:
            memo[fid] = False
            return False
        res = all(covered(c, targets, attrs, memo, stack + (fid,)) for c in cs)
        memo[fid] = res
        return res

    def uncovered_entries(fid: str, memo: dict, targets, attrs) -> list[str]:
        out, stack, seen = [], [fid], {fid}
        while stack:
            x = stack.pop()
            cs = callers.get(x, set())
            if not cs:
                out.append(x)
                continue
            for c in cs:
                if c not in seen and not covered(c, targets, attrs, memo):
                    seen.add(c)
                    stack.append(c)
        return sorted(out)[:6]

    module_has = False
    emitted: dict[tuple, dict] = {}
    for (g, gtype, attrs, vals) in guard_funcs:
        # equivalence group: guards with the same signature in this module
        group = {fid for fid, sg in sigs.items() if same_group(sg, (attrs, vals))}
        group.add(g.fid)
        attrs = (attrs, vals)
        # protected models
        protected = defaultdict(int)
        if gtype == "helper":
            direct_callers = callers.get(g.fid, set())
            for c in direct_callers:
                own = [w for w in prim.get(c, []) if not BOOKKEEPING_MODEL.search(w[0]) and "cascade" not in w[1]]
                if not own:
                    # caller runs the guard and delegates the write: take its transitive writes
                    for x in reach_of(c):
                        own += [w for w in prim.get(x, []) if not BOOKKEEPING_MODEL.search(w[0])
                                and "cascade" not in w[1]]
                for (m, k, ln) in own:
                    protected[m] += 1
        else:
            for (m, k, ln) in prim.get(g.fid, []):
                if not BOOKKEEPING_MODEL.search(m) and "cascade" not in k:
                    protected[m] += 1
        gi = {"module": module, "guard": g.fid, "line": g.line, "type": gtype, "attrs": sorted(attrs[0]),
              "vals": sorted(attrs[1]),
              "raises": g.guard_raises[:3], "callers": sorted(callers.get(g.fid, set()))[:12],
              "protected": dict(protected)}
        results["guards"].append(gi)
        if not protected:
            gi["empty_protected"] = True
            continue
        memo: dict = {}
        CUR_PROTECTED.clear()
        CUR_PROTECTED.update(protected)
        gkey = frozenset(group)
        for f in funcs:
            if f.is_repo or f.fid == g.fid or f.fid in group:
                continue
            hits = [(m, k, ln) for (m, k, ln) in prim.get(f.fid, []) if m in protected]
            if not hits:
                continue
            if covered(f.fid, group, attrs, memo):
                continue
            module_has = True
            if (gkey, f.fid) in emitted:
                emitted[(gkey, f.fid)]["also_guards"].append(g.fid)
                continue
            cand = {"also_guards": [],
                "module": module, "guard": g.fid, "guard_type": gtype, "attrs": sorted(attrs[0]),
                "seed": bool(re.search(r"(seed|demo|fixture|sample)", f.rel.rsplit("/", 1)[-1] + f.name, re.I)),
                "writer": f.fid, "writer_file": f.rel, "writer_line": f.line,
                "writes": sorted({f"{m}:{k}@{ln}" for (m, k, ln) in hits})[:8],
                "is_router": f.is_router,
                "uncovered_entries": uncovered_entries(f.fid, memo, group, attrs),
                "transition_like": bool(TRANSITION_NAME.match(f.name)),
            }
            emitted[(gkey, f.fid)] = cand
            results["candidates"].append(cand)
    results["modules"] += 1 if module_has else 0
    results.setdefault("helper_covered", [])
    for (wfid, sig), hfid in HELPER_COVER.items():
        results["helper_covered"].append({"writer": wfid, "helper": hfid, "attrs": sorted(sig[0]),
                                          "vals": sorted(sig[1])})

cands = results["candidates"]
helpers = [g for g in results["guards"] if g["type"] == "helper"]
inline = [g for g in results["guards"] if g["type"] == "inline"]
with open(OUT + ".json", "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=1)
guards_with = {c["guard"] for c in cands}
import time as _t
print(f"cpu={_t.process_time():.1f}s")
print(f"files={len(files)} models={len(MODELS)} cascade_parents={len(CASCADE_CHILDREN)}")
print(f"guards: helper={len(helpers)} inline={len(inline)} with_candidates={len(guards_with)} "
      f"empty_protected={sum(1 for g in results['guards'] if g.get('empty_protected'))} "
      f"(helper {sum(1 for g in helpers if g.get('empty_protected'))})")
hc = [c for c in cands if c["guard_type"] == "helper"]
print(f"helper-guard candidates={len(hc)} helpers_with={len({c['guard'] for c in hc})} "
      f"modules={len({c['module'] for c in hc})}; inline-guard candidates={len(cands) - len(hc)}; "
      f"seed candidates={sum(1 for c in cands if c['seed'])}")
print(f"candidates (guard,writer pairs)={len(cands)} unique writers={len({c['writer'] for c in cands})} "
      f"modules={len({c['module'] for c in cands})}")
