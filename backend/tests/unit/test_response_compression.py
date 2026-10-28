# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The bundle a browser asks for compressed arrives compressed.

Measured on the local stand before this existed: the application bundle is
2,496,962 bytes and the English locale chunk 2,267,263 bytes, and both came back
at exactly those sizes with ``Accept-Encoding: gzip, deflate, br`` on the
request and no ``Content-Encoding`` on the response. That is 4.8 MB of text
every screen pays for, which is what the case audits were measuring when they
timed the snag register at 4.3 s and the bill editor at 4.1 s. The endpoints
those screens call answer in under a tenth of a second, so the page chunks,
65 KB and 59 KB, cannot account for the difference and the shared shell can.

What is asserted here is the behaviour rather than a ratio: text with a known
length is compressed, everything else is passed through byte for byte. A ratio
would drift with the bundle and would fail for reasons that are not defects.
"""

from __future__ import annotations

import gzip
import hashlib

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.compression import CompressionMiddleware

BUNDLE = "const x = 1;\n" * 4000
SMALL = "ok"


def _same(body: str | bytes, expected: str) -> bool:
    """Compare by digest.

    A failed equality assertion over 48 KB of text sends pytest into ndiff,
    which takes minutes and prints nothing anyone can read. A digest fails in
    one line.
    """
    raw = body.encode() if isinstance(body, str) else body
    return hashlib.sha256(raw).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()


def _app() -> Starlette:
    async def bundle(_request):  # noqa: ANN001, ANN202
        return Response(BUNDLE, media_type="application/javascript")

    async def payload(_request):  # noqa: ANN001, ANN202
        return Response(BUNDLE, media_type="application/json")

    async def small(_request):  # noqa: ANN001, ANN202
        return PlainTextResponse(SMALL)

    async def already(_request):  # noqa: ANN001, ANN202
        packed = gzip.compress(BUNDLE.encode())
        return Response(packed, media_type="application/javascript", headers={"Content-Encoding": "gzip"})

    async def pdf(_request):  # noqa: ANN001, ANN202
        return Response(BUNDLE.encode(), media_type="application/pdf")

    async def stream(_request):  # noqa: ANN001, ANN202
        async def chunks():  # noqa: ANN202
            for _ in range(10):
                yield BUNDLE[:1000].encode()

        return StreamingResponse(chunks(), media_type="text/csv")

    app = Starlette(
        routes=[
            Route("/bundle.js", bundle),
            Route("/payload", payload),
            Route("/small", small),
            Route("/already.js", already),
            Route("/export.pdf", pdf),
            Route("/stream.csv", stream),
        ]
    )
    app.add_middleware(CompressionMiddleware)
    return app


CLIENT = TestClient(_app())
ASKS = {"Accept-Encoding": "gzip, deflate, br"}
DOES_NOT_ASK = {"Accept-Encoding": "identity"}


def test_a_javascript_bundle_is_compressed_when_the_browser_asks() -> None:
    raw = CLIENT.get("/bundle.js", headers=DOES_NOT_ASK)
    assert raw.headers.get("content-encoding") is None
    sent_raw = int(raw.headers["content-length"])

    packed = CLIENT.get("/bundle.js", headers=ASKS)
    assert packed.headers["content-encoding"] == "gzip"
    assert _same(packed.text, BUNDLE)
    # The saving is the point; the exact ratio is not asserted because it
    # drifts with the bundle and would fail for reasons that are not defects.
    assert int(packed.headers["content-length"]) < sent_raw


def test_an_api_payload_is_compressed_too() -> None:
    packed = CLIENT.get("/payload", headers=ASKS)
    assert packed.headers["content-encoding"] == "gzip"
    assert _same(packed.text, BUNDLE)


def test_a_cache_is_told_the_body_depends_on_the_request_header() -> None:
    packed = CLIENT.get("/bundle.js", headers=ASKS)
    assert "accept-encoding" in packed.headers["vary"].lower()


def test_a_client_that_does_not_ask_gets_the_bytes_unchanged() -> None:
    plain = CLIENT.get("/bundle.js", headers=DOES_NOT_ASK)
    assert plain.headers.get("content-encoding") is None
    assert _same(plain.text, BUNDLE)


def test_a_short_body_is_left_alone() -> None:
    """Below the minimum the gzip header and trailer eat the saving."""
    short = CLIENT.get("/small", headers=ASKS)
    assert short.headers.get("content-encoding") is None
    assert short.text == SMALL


def test_an_already_compressed_response_is_not_compressed_twice() -> None:
    once = CLIENT.get("/already.js", headers=ASKS)
    assert once.headers["content-encoding"] == "gzip"
    assert _same(once.text, BUNDLE)


def test_a_pdf_export_is_passed_through() -> None:
    """Already-compressed bytes come out bigger and cost CPU to get there."""
    export = CLIENT.get("/export.pdf", headers=ASKS)
    assert export.headers.get("content-encoding") is None
    assert _same(export.content, BUNDLE)


def test_a_streaming_body_is_not_buffered_to_compress_it() -> None:
    """No length means streaming, and buffering trades transfer for memory."""
    streamed = CLIENT.get("/stream.csv", headers=ASKS)
    assert streamed.headers.get("content-encoding") is None
    assert _same(streamed.text, BUNDLE[:1000] * 10)


def test_the_asset_mount_is_where_this_has_to_work(tmp_path) -> None:  # noqa: ANN001
    """The bundle is served by a StaticFiles mount, not by a route.

    The two are different paths through Starlette and only one of them serves
    the 4.8 MB. A middleware proven over handwritten routes and never over the
    mount would be a guard on the wrong door.
    """
    from starlette.staticfiles import StaticFiles

    assets = tmp_path / "assets"
    assets.mkdir()
    # write_text would translate the newlines on Windows and change the bytes.
    (assets / "index-abc123.js").write_bytes(BUNDLE.encode())

    mounted = Starlette()
    mounted.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
    mounted.add_middleware(CompressionMiddleware)
    client = TestClient(mounted)

    packed = client.get("/assets/index-abc123.js", headers=ASKS)
    assert packed.headers["content-encoding"] == "gzip"
    assert _same(packed.text, BUNDLE)
    assert int(packed.headers["content-length"]) < len(BUNDLE)
