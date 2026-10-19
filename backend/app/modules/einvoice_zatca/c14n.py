# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A small XML tree and its Canonical XML 1.1 form.

ZATCA hashes an invoice as "remove three elements, canonicalize with C14N 1.1,
SHA-256" (XML Implementation Standard v1.2, BR-KSA-26 and the ``ds:Transforms``
block of the Security Features standard). The standard library cannot do that:
``xml.etree.ElementTree.canonicalize`` implements C14N 2.0, which moves every
namespace declaration down to the first element that uses it, so the root of an
invoice loses ``xmlns:ext`` once the extensions are removed and the hash comes
out different. ``lxml`` would do it but is a test-only dependency here.

So this module carries the part of C14N 1.1 an invoice needs:

* namespace declarations are inclusive: an element renders every in-scope
  binding its nearest rendered ancestor did not, sorted by prefix, the default
  namespace first;
* attributes are sorted by namespace URI, then local name, unqualified first;
* text escapes ``& < >`` and ``\\r``; attribute values escape ``& < "`` and
  ``\\t \\n \\r``; empty elements are written as a start and an end tag;
* comments are dropped, whitespace text inside the document element is kept
  exactly, and nothing outside the document element is written.

What it does not carry: DTDs and entity declarations (refused at parse time,
which is also the safe answer for an untrusted payload), ``xml:*`` attribute
inheritance into a document subset (no ZATCA document uses ``xml:`` attributes)
and relative namespace URIs.

The same tree is what the invoice builder writes, so the document sent and the
bytes hashed come out of one serializer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from xml.parsers import expat

XML_NS = "http://www.w3.org/XML/1998/namespace"


class XmlError(ValueError):
    """The text is not XML this module will read."""


@dataclass
class Element:
    """One element, with its prefixes kept as written.

    ``tag`` is the qualified name (``cbc:ID``, or ``Invoice`` under a default
    namespace). ``ns`` holds only the declarations made on this element, prefix
    to URI, ``""`` for the default namespace. ``attrs`` keeps document order;
    canonical order is applied when written. ``children`` mixes elements, text
    (``str``) and processing instructions (:class:`PI`).
    """

    tag: str
    ns: dict[str, str] = field(default_factory=dict)
    attrs: list[tuple[str, str]] = field(default_factory=list)
    children: list[Element | str | PI] = field(default_factory=list)

    # ── Building ─────────────────────────────────────────────────────────────

    def add(self, tag: str, text: str | None = None, **attrs: str) -> Element:
        """Append a child element, optionally with text, and return it."""
        child = Element(tag, attrs=[(k, v) for k, v in attrs.items()])
        if text is not None:
            child.children.append(text)
        self.children.append(child)
        return child

    def append(self, child: Element) -> Element:
        self.children.append(child)
        return child

    # ── Reading ──────────────────────────────────────────────────────────────

    @property
    def prefix(self) -> str:
        return self.tag.split(":", 1)[0] if ":" in self.tag else ""

    @property
    def local(self) -> str:
        return self.tag.split(":", 1)[1] if ":" in self.tag else self.tag

    def elements(self) -> Iterator[Element]:
        for child in self.children:
            if isinstance(child, Element):
                yield child

    def find(self, *tags: str) -> Element | None:
        """The first descendant reached by a path of qualified names."""
        node: Element | None = self
        for tag in tags:
            if node is None:
                return None
            node = next((c for c in node.elements() if c.tag == tag), None)
        return node

    def find_all(self, tag: str) -> list[Element]:
        return [c for c in self.elements() if c.tag == tag]

    def text(self) -> str:
        """The concatenated direct text of this element."""
        return "".join(c for c in self.children if isinstance(c, str))

    def attr(self, name: str, default: str = "") -> str:
        for key, value in self.attrs:
            if key == name:
                return value
        return default

    def iter(self) -> Iterator[Element]:
        yield self
        for child in self.elements():
            yield from child.iter()


@dataclass(frozen=True)
class PI:
    """A processing instruction inside the document element."""

    target: str
    data: str


# ── Parsing ──────────────────────────────────────────────────────────────────


def parse(text: str | bytes) -> Element:
    """The document element of ``text``.

    Refuses a document type declaration outright: an invoice has none, and a
    DTD is the only way an entity expansion or an external fetch gets in.
    """
    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.ordered_attributes = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack: list[Element] = []
    root: list[Element] = []

    def start(name: str, attributes: list[str]) -> None:
        element = Element(name)
        for index in range(0, len(attributes), 2):
            key, value = attributes[index], attributes[index + 1]
            if key == "xmlns":
                element.ns[""] = value
            elif key.startswith("xmlns:"):
                element.ns[key[6:]] = value
            else:
                element.attrs.append((key, value))
        if stack:
            stack[-1].children.append(element)
        elif root:
            raise XmlError("The document has more than one top-level element.")
        else:
            root.append(element)
        stack.append(element)

    def end(_name: str) -> None:
        stack.pop()

    def data(value: str) -> None:
        if stack:
            stack[-1].children.append(value)

    def instruction(target: str, value: str) -> None:
        if stack:
            stack[-1].children.append(PI(target, value))

    def refuse_doctype(*_args: object) -> None:
        raise XmlError("A document type declaration is not accepted in an invoice.")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = data
    parser.ProcessingInstructionHandler = instruction
    parser.StartDoctypeDeclHandler = refuse_doctype
    parser.EntityDeclHandler = refuse_doctype
    try:
        parser.Parse(text, True)
    except expat.ExpatError as exc:
        raise XmlError(f"The document is not well-formed XML: {exc}.") from exc
    if not root:
        raise XmlError("The document has no element.")
    return root[0]


# ── Namespaces ───────────────────────────────────────────────────────────────


def scope_of(path: list[Element]) -> dict[str, str]:
    """The namespace bindings in scope at the last element of ``path``."""
    scope: dict[str, str] = {}
    for element in path:
        scope.update(element.ns)
    return scope


def expanded(qname: str, scope: dict[str, str], *, attribute: bool = False) -> tuple[str, str]:
    """``(namespace URI, local name)`` of a qualified name under ``scope``.

    An unprefixed attribute is in no namespace; an unprefixed element is in
    the default namespace.
    """
    if ":" in qname:
        prefix, local = qname.split(":", 1)
        if prefix == "xml":
            return XML_NS, local
        if prefix not in scope:
            raise XmlError(f"The prefix {prefix!r} of {qname!r} is not declared.")
        return scope[prefix], local
    if attribute:
        return "", qname
    return scope.get("", ""), qname


# ── Canonical form ───────────────────────────────────────────────────────────


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#xD;")


def _escape_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace('"', "&quot;")
        .replace("\t", "&#x9;")
        .replace("\n", "&#xA;")
        .replace("\r", "&#xD;")
    )


# Decides, for an element and the bindings in scope at it, whether the element
# and everything under it is left out of the canonical form.
Exclude = Callable[[Element, dict[str, str]], bool]


def canonicalize(
    element: Element,
    *,
    exclude: Exclude | None = None,
    inherited: dict[str, str] | None = None,
) -> bytes:
    """The C14N 1.1 form (without comments) of ``element`` and its subtree.

    ``inherited`` is the namespace scope of the element's parent when a
    subtree of a larger document is canonicalized: inclusive canonicalization
    writes every in-scope binding on the apex element, including the ones
    declared above it.
    """
    out: list[str] = []
    _write(element, dict(inherited or {}), {}, exclude, out)
    return "".join(out).encode("utf-8")


def _write(
    element: Element,
    parent_scope: dict[str, str],
    rendered: dict[str, str],
    exclude: Exclude | None,
    out: list[str],
) -> None:
    scope = {**parent_scope, **element.ns}
    if exclude is not None and exclude(element, scope):
        return

    declarations: list[tuple[str, str]] = []
    for prefix in sorted(scope):
        if prefix == "xml":
            continue
        uri = scope[prefix]
        if prefix == "":
            # An empty default namespace is only written to undo a non-empty
            # one the nearest rendered ancestor wrote.
            if uri == "" and rendered.get("", "") == "":
                continue
            if rendered.get("", "") == uri:
                continue
        elif rendered.get(prefix) == uri:
            continue
        declarations.append((prefix, uri))

    attributes = sorted(
        ((expanded(name, scope, attribute=True), name, value) for name, value in element.attrs),
        key=lambda item: item[0],
    )

    out.append("<" + element.tag)
    for prefix, uri in declarations:
        name = "xmlns" if prefix == "" else f"xmlns:{prefix}"
        out.append(f' {name}="{_escape_attr(uri)}"')
    for _key, name, value in attributes:
        out.append(f' {name}="{_escape_attr(value)}"')
    out.append(">")

    now_rendered = dict(rendered)
    for prefix, uri in declarations:
        now_rendered[prefix] = uri
    for child in element.children:
        if isinstance(child, Element):
            _write(child, scope, now_rendered, exclude, out)
        elif isinstance(child, PI):
            data = f" {child.data}" if child.data else ""
            out.append(f"<?{child.target}{data}?>")
        else:
            out.append(_escape_text(child))
    out.append(f"</{element.tag}>")


def serialize(element: Element) -> str:
    """The document as sent: an XML declaration, then its canonical form.

    Writing the canonical form itself means a verifier that canonicalizes what
    it received gets back these bytes, whatever parser it uses.
    """
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + canonicalize(element).decode("utf-8")


def path_to(root: Element, target: Element) -> list[Element]:
    """The elements from ``root`` down to ``target``, both included."""

    def walk(node: Element, trail: list[Element]) -> list[Element] | None:
        trail = [*trail, node]
        if node is target:
            return trail
        for child in node.elements():
            found = walk(child, trail)
            if found is not None:
                return found
        return None

    found = walk(root, [])
    if found is None:
        raise XmlError("The element is not inside this document.")
    return found


__all__ = [
    "PI",
    "XML_NS",
    "Element",
    "Exclude",
    "XmlError",
    "canonicalize",
    "expanded",
    "parse",
    "path_to",
    "scope_of",
    "serialize",
]
