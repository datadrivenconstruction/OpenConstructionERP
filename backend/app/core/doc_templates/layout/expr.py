# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A small, closed expression language for computed columns and totals.

``quantity * unit_rate``, ``round(amount * 0.95, 2)``, ``if(retention > 0, amount * retention / 100, 0)``.

The parser is hand-written and the evaluator walks its own tree: no ``eval``,
no Python objects, no attribute access, no imports, no loops, no file or
network access. Names are column ids or dotted field paths looked up in a dict
the caller supplies. Numbers are ``Decimal``; a missing value or a division by
zero yields ``None`` rather than an error, so a template can never stop a
document from printing. Length, token count and nesting depth are capped.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from decimal import Decimal, DivisionByZero, InvalidOperation
from functools import lru_cache
from typing import Any

__all__ = ["FUNCTIONS", "ExprError", "evaluate", "names_in", "parse"]

MAX_LENGTH = 300
MAX_TOKENS = 120
MAX_DEPTH = 24

_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<str>'[^'\n]{0,200}'|\"[^\"\n]{0,200}\")"
    r"|(?P<name>[a-z_][a-z0-9_]{0,40}(?:\.[a-z_][a-z0-9_]{0,40}){0,3})"
    r"|(?P<op>==|!=|<=|>=|[-+*/%(),<>])"
    r")",
    re.IGNORECASE,
)
_WORDS = {"and", "or", "not", "true", "false", "null"}


class ExprError(ValueError):
    """The text is not an expression of this language."""


def _tokens(text: str) -> list[tuple[str, str]]:
    if len(text) > MAX_LENGTH:
        raise ExprError("too long")
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise ExprError(f"unexpected character at {pos}")
        pos = match.end()
        kind = match.lastgroup or ""
        value = match.group(kind)
        if kind == "name" and value.lower() in _WORDS:
            kind, value = "word", value.lower()
        elif kind == "name":
            if "__" in value:
                raise ExprError(f"unknown name at {match.start()}")
            value = value.lower()
        out.append((kind, value))
        if len(out) > MAX_TOKENS:
            raise ExprError("too many tokens")
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.depth = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, value: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (value is not None and token[1] != value):
            raise ExprError(f"expected {value or 'a value'}")
        self.pos += 1
        return token

    def at(self, *values: str) -> bool:
        token = self.peek()
        return token is not None and token[1] in values and token[0] in {"op", "word"}

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError("nested too deeply")

    def expr(self) -> tuple:
        self.enter()
        node = self.and_()
        while self.at("or"):
            self.take()
            node = ("or", node, self.and_())
        self.depth -= 1
        return node

    def and_(self) -> tuple:
        node = self.not_()
        while self.at("and"):
            self.take()
            node = ("and", node, self.not_())
        return node

    def not_(self) -> tuple:
        if self.at("not"):
            self.take()
            self.enter()
            node = ("not", self.not_())
            self.depth -= 1
            return node
        return self.compare()

    def compare(self) -> tuple:
        node = self.add()
        if self.at("==", "!=", "<", "<=", ">", ">="):
            op = self.take()[1]
            node = ("cmp", op, node, self.add())
        return node

    def add(self) -> tuple:
        node = self.mul()
        while self.at("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.mul())
        return node

    def mul(self) -> tuple:
        node = self.unary()
        while self.at("*", "/", "%"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self) -> tuple:
        if self.at("-"):
            self.take()
            self.enter()
            node = ("neg", self.unary())
            self.depth -= 1
            return node
        return self.primary()

    def primary(self) -> tuple:
        token = self.peek()
        if token is None:
            raise ExprError("unexpected end")
        kind, value = token
        if kind == "num":
            self.take()
            return ("lit", Decimal(value))
        if kind == "str":
            self.take()
            return ("lit", value[1:-1])
        if kind == "word" and value in {"true", "false", "null"}:
            self.take()
            return ("lit", {"true": True, "false": False, "null": None}[value])
        if kind == "name":
            self.take()
            if self.at("("):
                if value not in FUNCTIONS:
                    raise ExprError(f"unknown function {value}")
                self.take("(")
                args: list[tuple] = []
                if not self.at(")"):
                    args.append(self.expr())
                    while self.at(","):
                        self.take()
                        args.append(self.expr())
                self.take(")")
                return ("call", value, tuple(args))
            return ("name", value)
        if self.at("("):
            self.take()
            node = self.expr()
            self.take(")")
            return node
        raise ExprError(f"unexpected {value}")


@lru_cache(maxsize=512)
def parse(text: str) -> tuple:
    """Parse *text* into a tree. Raises :class:`ExprError` on anything outside the language."""
    tokens = _tokens(str(text or ""))
    if not tokens:
        raise ExprError("empty")
    parser = _Parser(tokens)
    node = parser.expr()
    if parser.peek() is not None:
        raise ExprError(f"unexpected {parser.peek()[1]}")  # type: ignore[index]
    return node


def names_in(node: tuple) -> set[str]:
    """Every name the tree reads."""
    tag = node[0]
    if tag == "name":
        return {node[1]}
    if tag == "lit":
        return set()
    if tag == "call":
        out: set[str] = set()
        for arg in node[2]:
            out |= names_in(arg)
        return out
    out = set()
    for part in node[1:]:
        if isinstance(part, tuple):
            out |= names_in(part)
    return out


def _num(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _truthy(value: Any) -> bool:
    if isinstance(value, Decimal):
        return value != 0
    return bool(value)


def _round(value: Any, places: Any = Decimal(2)) -> Decimal | None:
    number, digits = _num(value), _num(places)
    if number is None:
        return None
    digits_int = int(digits) if digits is not None else 2
    digits_int = max(0, min(digits_int, 6))
    return number.quantize(Decimal(1).scaleb(-digits_int))


def _minmax(pick: Callable[..., Any]) -> Callable[..., Any]:
    def _fn(*args: Any) -> Decimal | None:
        numbers = [n for n in (_num(a) for a in args) if n is not None]
        return pick(numbers) if numbers else None

    return _fn


def _abs(value: Any) -> Decimal | None:
    number = _num(value)
    return abs(number) if number is not None else None


def _coalesce(*args: Any) -> Any:
    return next((a for a in args if a not in (None, "")), None)


def _if(cond: Any, yes: Any = None, no: Any = None) -> Any:
    return yes if _truthy(cond) else no


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "round": _round,
    "min": _minmax(min),
    "max": _minmax(max),
    "abs": _abs,
    "coalesce": _coalesce,
    "if": _if,
}


def _compare(op: str, left: Any, right: Any) -> bool:
    a, b = _num(left), _num(right)
    if a is not None and b is not None:
        pair: tuple[Any, Any] = (a, b)
    elif op in {"==", "!="}:
        pair = ("" if left is None else str(left), "" if right is None else str(right))
    else:
        return False
    x, y = pair
    return {
        "==": x == y,
        "!=": x != y,
        "<": x < y,
        "<=": x <= y,
        ">": x > y,
        ">=": x >= y,
    }[op]


def _eval(node: tuple, lookup: Mapping[str, Any]) -> Any:
    tag = node[0]
    if tag == "lit":
        return node[1]
    if tag == "name":
        return lookup.get(node[1])
    if tag == "neg":
        number = _num(_eval(node[1], lookup))
        return -number if number is not None else None
    if tag == "not":
        return not _truthy(_eval(node[1], lookup))
    if tag == "and":
        return _truthy(_eval(node[1], lookup)) and _truthy(_eval(node[2], lookup))
    if tag == "or":
        return _truthy(_eval(node[1], lookup)) or _truthy(_eval(node[2], lookup))
    if tag == "cmp":
        return _compare(node[1], _eval(node[2], lookup), _eval(node[3], lookup))
    if tag == "call":
        return FUNCTIONS[node[1]](*(_eval(arg, lookup) for arg in node[2]))
    if tag == "bin":
        a, b = _num(_eval(node[2], lookup)), _num(_eval(node[3], lookup))
        if a is None or b is None:
            return None
        op = node[1]
        try:
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                return a / b if b != 0 else None
            return a % b if b != 0 else None
        except (InvalidOperation, DivisionByZero, OverflowError):
            return None
    return None


def evaluate(text: str, lookup: Mapping[str, Any]) -> Any:
    """Evaluate *text* against *lookup*. ``None`` for a malformed expression or a missing value; never raises."""
    try:
        return _eval(parse(text), lookup)
    except (ExprError, RecursionError, ArithmeticError, TypeError):
        return None
