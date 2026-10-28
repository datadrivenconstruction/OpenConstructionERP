"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Content-Disposition headers that survive non-ASCII document names.

Export endpoints used to build the header from
``name.encode("ascii", errors="replace")``, which turns every character outside
ASCII into a question mark. A Leistungsverzeichnis called "Bürogebäude Frankfurt
Europaviertel" was offered to the browser as ``B?rogeb?ude Frankfurt
Europaviertel.X84``, and because ``?`` is not a legal filename character on
Windows the browser then saved it as ``B_rogeb_ude...``. Every German, French,
Spanish, Turkish and Chinese name came out damaged.

RFC 6266 solved this: send the ASCII form under ``filename`` for very old
clients, and the real UTF-8 name under ``filename*`` using the RFC 5987
encoding. Every browser in use prefers ``filename*`` when both are present.
"""

from urllib.parse import quote

__all__ = ["attachment_disposition", "ascii_fallback_name"]

# Characters that are illegal in a filename on Windows, plus the separators that
# would let a name escape its directory. Replaced rather than stripped so two
# different names cannot collapse into one.
_ILLEGAL = '<>:"/\\|?*'


def ascii_fallback_name(name: str) -> str:
    """The lossy ASCII form, for the plain ``filename`` parameter.

    Latin letters keep their base form (``ü`` becomes ``u``) instead of becoming
    a question mark, so the fallback stays readable for the clients that use it.
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    ascii_only = stripped.encode("ascii", errors="replace").decode("ascii")
    cleaned = "".join("_" if c in _ILLEGAL else c for c in ascii_only).strip()
    # A name written entirely in a script with no Latin decomposition (Chinese,
    # Japanese, Korean) leaves nothing but underscores. That is a legal filename
    # and a useless one, so name it instead. The real name still travels in
    # `filename*`, which is what every current browser reads.
    if not any(c.isalnum() for c in cleaned):
        return "download"
    return cleaned


def attachment_disposition(filename: str, *, inline: bool = False) -> str:
    """Build a Content-Disposition that carries `filename` intact.

    `filename` is the full name including its extension. The caller does not need
    to sanitise it; both parameters are derived here.

    `inline` switches the disposition type for the surfaces that display a
    document in the browser rather than downloading it: a scanned invoice, a
    published record. It changes only that word. The filename handling is the
    same either way, which is the point of it living here: an inline
    disposition used to be a separate helper, and the separation is why one of
    the two carried the fallback fix and the other did not.
    """
    disposition = "inline" if inline else "attachment"
    safe = ascii_fallback_name(filename)
    # quote() leaves RFC 5987's attr-char set alone and percent-encodes the rest.
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{safe}\"; filename*=UTF-8''{encoded}"
