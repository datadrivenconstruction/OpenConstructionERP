"""Parametric formula engine for assembly components.

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


class FormulaError(ValueError):
    """Raised when a formula cannot be evaluated."""


class FormulaEvaluator:
    """Safe parametric formula evaluator.

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

            return float(result)

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
                raise FormulaError(
                    f"Parameter '{name}' is a string ('{val}'), cannot use in arithmetic"
                )
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
                raise FormulaError(
                    f"Lookup '{table_name}[{key}]' returned a dict — use specific field"
                )
            return str(val)

        return re.sub(pattern, replace_lookup, formula)

    def _expand_conditionals(self, formula: str) -> str:
        """Replace if(cond, true_val, false_val) with evaluated branch."""
        pattern = r"if\s*\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"

        max_iterations = 10
        for _ in range(max_iterations):
            match = re.search(pattern, formula)
            if not match:
                break
            cond_str = match.group(1).strip()
            true_val = match.group(2).strip()
            false_val = match.group(3).strip()

            cond_result = self._eval_condition(cond_str)
            replacement = true_val if cond_result else false_val
            formula = formula[: match.start()] + replacement + formula[match.end() :]

        return formula

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
                except Exception:
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
