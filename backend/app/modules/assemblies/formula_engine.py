"""‌⁠‍Parametric formula engine for assembly components.

Evaluates formulas with variable substitution, conditionals, and lookups.
Used to calculate resource quantities dynamically based on parameters
like height, length, thickness, etc.

Example:
    evaluator = FormulaEvaluator()
    result = evaluator.evaluate(
        "${height} * ${length} * ${thickness}",
        parameters={"height": 3.0, "length": 12.0, "thickness": 0.24},
    )
    # result = 8.64
"""

import math
import re
from typing import Any, Union

# Cheap structural caps applied BEFORE any recursive work, so a
# pathological input (e.g. 5000 nested parens) is rejected in O(n)
# instead of burning the C stack until Python raises RecursionError.
_MAX_FORMULA_LEN = 4096
_MAX_PAREN_DEPTH = 64


class FormulaError(ValueError):
    """‌⁠‍Raised when a formula cannot be evaluated."""


class FormulaEvaluator:
    """‌⁠‍Safe parametric formula evaluator.

    Supports:
    - Basic math: +, -, *, /, (), decimals
    - Variables: ${height}, ${length}
    - Functions: max(a, b), min(a, b), round(x, n), abs(x), sqrt(x)
    - Conditionals: if(a > b, true_val, false_val)
    - Lookups: lookup("table_name", "key")
    """

    def evaluate(
        self,
        formula: str,
        parameters: dict[str, Union[float, int, str]] | None = None,
        lookup_tables: dict[str, dict[str, Any]] | None = None,
    ) -> float:
        """Evaluate a formula string with parameter substitution.

        Args:
            formula: Formula string, e.g. "${height} * ${length} * 0.24"
            parameters: Named values, e.g. {"height": 3.0, "length": 12.0}
            lookup_tables: Named tables, e.g. {"steel_weights": {"HEB300": 117.7}}

        Returns:
            Computed float result.

        Raises:
            FormulaError: If formula is invalid or evaluation fails.
        """
        params = parameters or {}
        lookups = lookup_tables or {}

        # Reject pathological structure cheaply, up front — never let a
        # caller drive the recursive-descent parser to a RecursionError.
        if not isinstance(formula, str):
            raise FormulaError("Formula must be a string")
        if len(formula) > _MAX_FORMULA_LEN:
            raise FormulaError(f"Formula too long ({len(formula)} > {_MAX_FORMULA_LEN} chars)")
        depth = 0
        for ch in formula:
            if ch == "(":
                depth += 1
                if depth > _MAX_PAREN_DEPTH:
                    raise FormulaError(f"Parenthesis nesting too deep (> {_MAX_PAREN_DEPTH})")
            elif ch == ")":
                depth -= 1

        try:
            # Step 1: Substitute ${param} with values
            substituted = self._substitute_params(formula, params)

            # Step 2: Expand lookup() calls
            expanded = self._expand_lookups(substituted, lookups)

            # Step 3: Expand if() conditionals
            resolved = self._expand_conditionals(expanded)

            # Step 4: Expand built-in functions
            resolved = self._expand_functions(resolved)

            # Step 5: Safe math evaluation
            result = self._safe_eval(resolved)

            if not isinstance(result, (int, float)):
                raise FormulaError(f"Formula must evaluate to a number, got {type(result)}")

            result_f = float(result)
            # A non-finite result (overflow to inf, or 0*inf → nan) must
            # NOT be returned silently — it would propagate as a corrupt
            # null total downstream (same class as ASM-002).
            if not math.isfinite(result_f):
                raise FormulaError("Formula produced a non-finite result (overflow / NaN)")

            return result_f

        except FormulaError:
            raise
        except Exception as exc:
            raise FormulaError(f"Formula evaluation failed: {exc}") from exc

    def _substitute_params(self, formula: str, params: dict) -> str:
        """Replace ${param_name} with parameter values."""

        def replace_var(match: re.Match) -> str:
            name = match.group(1)
            if name not in params:
                raise FormulaError(f"Unknown parameter: '{name}'")
            val = params[name]
            if isinstance(val, str):
                raise FormulaError(f"Parameter '{name}' is a string ('{val}'), cannot use in arithmetic")
            return str(val)

        return re.sub(r"\$\{([a-zA-Z_]\w*)\}", replace_var, formula)

    def _expand_lookups(self, formula: str, lookups: dict) -> str:
        """Replace lookup("table", "key") with looked-up value."""
        pattern = r'lookup\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)'

        def replace_lookup(match: re.Match) -> str:
            table_name = match.group(1)
            key = match.group(2)
            if table_name not in lookups:
                raise FormulaError(f"Unknown lookup table: '{table_name}'")
            table = lookups[table_name]
            if key not in table:
                raise FormulaError(f"Key '{key}' not found in table '{table_name}'")
            val = table[key]
            if isinstance(val, dict):
                raise FormulaError(f"Lookup '{table_name}[{key}]' returned a dict — use specific field")
            return str(val)

        return re.sub(pattern, replace_lookup, formula)

    def _expand_conditionals(self, formula: str) -> str:
        """Replace if(cond, true_val, false_val) with the evaluated branch.

        The previous implementation used a flat ``[^,]`` regex that
        could not represent a comma inside a branch — so any nested
        ``if(...)`` (whose own commas live inside the parent's branch)
        was sliced apart into a malformed expression. This resolves the
        *innermost* ``if(...)`` first using brace-aware argument
        splitting, then loops, so arbitrarily nested conditionals
        collapse correctly from the inside out.
        """
        max_iterations = 100  # generous; each pass removes one if()
        for _ in range(max_iterations):
            span = self._find_innermost_if(formula)
            if span is None:
                break
            start, end = span
            args = self._split_call_args(formula[start:end])
            if len(args) != 3:
                raise FormulaError(f"if() takes exactly 3 arguments, got {len(args)}: '{formula[start:end]}'")
            cond_str, true_val, false_val = (a.strip() for a in args)
            cond_result = self._eval_condition(cond_str)
            replacement = true_val if cond_result else false_val
            formula = formula[:start] + replacement + formula[end:]
        else:
            raise FormulaError("if() nesting too deep")

        return formula

    def _find_innermost_if(self, formula: str) -> tuple[int, int] | None:
        """Locate an ``if(...)`` whose argument list contains no nested ``if(``.

        Returns the ``(start, end)`` slice — ``start`` at the ``i`` of
        ``if``, ``end`` one past its matching ``)`` — or ``None`` when
        there is no ``if(`` left to expand. Resolving an *innermost*
        ``if`` first guarantees its branches are plain expressions, so
        the brace-aware arg split is unambiguous.
        """
        for m in re.finditer(r"\bif\s*\(", formula):
            open_idx = formula.index("(", m.start())
            depth = 0
            for i in range(open_idx, len(formula)):
                ch = formula[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        # Body strictly between the if()'s own parens.
                        body = formula[open_idx + 1 : i]
                        if not re.search(r"\bif\s*\(", body):
                            return (m.start(), i + 1)
                        break  # nested → try the next match (deeper one)
        return None

    @staticmethod
    def _split_call_args(call: str) -> list[str]:
        """Split ``if(a, b, c)`` into ``['a',' b',' c']`` at top-level commas.

        Commas inside nested parentheses are NOT split points, so a
        branch like ``min(1, 2)`` survives intact.
        """
        inner = call[call.index("(") + 1 : call.rindex(")")]
        args: list[str] = []
        depth = 0
        current = ""
        for ch in inner:
            if ch == "(":
                depth += 1
                current += ch
            elif ch == ")":
                depth -= 1
                current += ch
            elif ch == "," and depth == 0:
                args.append(current)
                current = ""
            else:
                current += ch
        args.append(current)
        return args

    def _eval_condition(self, cond: str) -> bool:
        """Evaluate a comparison: 'a > b', 'a == b', etc."""
        for op in (">=", "<=", "!=", "==", ">", "<"):
            if op in cond:
                parts = cond.split(op, 1)
                if len(parts) != 2:
                    continue
                try:
                    left = self._safe_eval(parts[0].strip())
                    right = self._safe_eval(parts[1].strip())
                except FormulaError:
                    # Wrong split — try the next operator. Programmer
                    # errors (TypeError etc.) propagate so they don't
                    # silently corrupt cost numbers.
                    continue
                if op == ">=":
                    return left >= right
                if op == "<=":
                    return left <= right
                if op == "!=":
                    return left != right
                if op == "==":
                    return left == right
                if op == ">":
                    return left > right
                if op == "<":
                    return left < right
        raise FormulaError(f"Invalid condition: '{cond}'")

    def _expand_functions(self, formula: str) -> str:
        """Expand max(), min(), round(), abs(), sqrt()."""
        # max(a, b, ...)
        formula = re.sub(
            r"max\s*\(([^)]+)\)",
            lambda m: str(max(float(x.strip()) for x in m.group(1).split(","))),
            formula,
        )
        # min(a, b, ...)
        formula = re.sub(
            r"min\s*\(([^)]+)\)",
            lambda m: str(min(float(x.strip()) for x in m.group(1).split(","))),
            formula,
        )
        # round(x, n)
        formula = re.sub(
            r"round\s*\(\s*([^,]+)\s*,\s*(\d+)\s*\)",
            lambda m: str(round(float(m.group(1).strip()), int(m.group(2)))),
            formula,
        )
        # abs(x)
        formula = re.sub(
            r"abs\s*\(\s*([^)]+)\s*\)",
            lambda m: str(abs(float(m.group(1).strip()))),
            formula,
        )
        # sqrt(x)
        formula = re.sub(
            r"sqrt\s*\(\s*([^)]+)\s*\)",
            lambda m: str(math.sqrt(float(m.group(1).strip()))),
            formula,
        )
        return formula

    def _safe_eval(self, expr: str) -> float:
        """Safely evaluate a math expression (no eval/exec).

        Uses a simple recursive descent parser.
        Only allows: numbers, +, -, *, /, (, ), spaces, decimals.
        """
        expr = expr.strip()
        if not expr:
            raise FormulaError("Empty expression")

        # Validate: only safe characters
        if not re.match(r"^[\d+\-*/().\s]+$", expr):
            raise FormulaError(f"Unsafe characters in expression: '{expr}'")

        tokens = self._tokenize(expr)
        pos = [0]  # mutable index

        def parse_expr() -> float:
            result = parse_term()
            while pos[0] < len(tokens) and tokens[pos[0]] in ("+", "-"):
                op = tokens[pos[0]]
                pos[0] += 1
                right = parse_term()
                result = result + right if op == "+" else result - right
            return result

        def parse_term() -> float:
            result = parse_factor()
            while pos[0] < len(tokens) and tokens[pos[0]] in ("*", "/"):
                op = tokens[pos[0]]
                pos[0] += 1
                right = parse_factor()
                if op == "/":
                    if right == 0:
                        raise FormulaError("Division by zero")
                    result /= right
                else:
                    result *= right
            return result

        def parse_factor() -> float:
            if pos[0] >= len(tokens):
                raise FormulaError("Unexpected end of expression")
            tok = tokens[pos[0]]
            if tok == "-":
                pos[0] += 1
                return -parse_factor()
            if tok == "+":
                pos[0] += 1
                return parse_factor()
            if tok == "(":
                pos[0] += 1
                val = parse_expr()
                if pos[0] >= len(tokens) or tokens[pos[0]] != ")":
                    raise FormulaError("Missing closing parenthesis")
                pos[0] += 1
                return val
            try:
                val = float(tok)
                pos[0] += 1
                return val
            except ValueError:
                raise FormulaError(f"Unexpected token: '{tok}'")

        result = parse_expr()
        if pos[0] < len(tokens):
            raise FormulaError(f"Unexpected token: '{tokens[pos[0]]}'")
        return result

    def _tokenize(self, expr: str) -> list[str]:
        """Tokenize a math expression into numbers and operators."""
        tokens: list[str] = []
        i = 0
        while i < len(expr):
            ch = expr[i]
            if ch == " ":
                i += 1
                continue
            if ch in "+-*/()":
                tokens.append(ch)
                i += 1
            elif ch.isdigit() or ch == ".":
                num = ""
                while i < len(expr) and (expr[i].isdigit() or expr[i] == "."):
                    num += expr[i]
                    i += 1
                tokens.append(num)
            else:
                raise FormulaError(f"Unexpected character: '{ch}'")
        return tokens
