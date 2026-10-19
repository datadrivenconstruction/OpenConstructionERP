"""ETA serialization and signature, pinned to the samples ETA publishes.

The fixtures in ``tests/fixtures/eta`` are copied unedited from the ETA SDK
(https://sdk.invoicing.eta.gov.eg/files/, read 2026-10-19), except that the
UTF-8 byte order mark at the start of ``one-doc-I.json`` was dropped:

* ``one-doc.json``                 a document (version 0.9, unsigned)
* ``one-doc-serialized.json.txt``  ETA's canonical serialization of it
* ``one-doc-I.json``               the same document signed by the issuer

Together they pin the whole chain: our serialization is ETA's byte for byte,
its SHA-256 is the digest inside ETA's own signature, our CMS builder rebuilds
that signature byte for byte, and the RSA value ETA's signer produced verifies
over the bytes we say are signed. No network, no token.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.einvoice_eta import der, serialization, signing

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "eta"


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _signature_value() -> str:
    return json.loads(_text("one-doc-I.json"))["signatures"][0]["value"]


class TestCanonicalSerialization:
    def test_the_sdk_sample_serializes_byte_for_byte(self):
        assert serialization.canonical_string(_text("one-doc.json")) == _text("one-doc-serialized.json.txt")

    def test_number_literals_survive_as_written(self):
        # A float round trip would print 947.0; ETA hashes the literal 947.00.
        out = serialization.canonical_string('{"a": 947.00, "b": 5, "c": 0.0}')
        assert out == '"A""947.00""B""5""C""0.0"'

    def test_an_array_repeats_its_name_before_every_element(self):
        out = serialization.canonical_string('{"lines": [{"x": "1"}, {"x": "2"}], "after": "z"}')
        assert out == '"LINES""LINES""X""1""LINES""X""2""AFTER""z"'

    def test_nested_objects_are_prefixed_once(self):
        out = serialization.canonical_string('{"issuer": {"address": {"country": "EG"}, "id": "1"}}')
        assert out == '"ISSUER""ADDRESS""COUNTRY""EG""ID""1"'

    def test_formatting_does_not_change_the_canonical_form(self):
        compact = json.dumps(json.loads(_text("one-doc.json")), separators=(",", ":"))
        # json round trip loses 947.00 -> 947.0, so compare against a reformat
        # that keeps the literals: strip the whitespace only.
        reformatted = "".join(line.strip() for line in _text("one-doc.json").splitlines())
        assert serialization.canonical_string(reformatted) == _text("one-doc-serialized.json.txt")
        assert serialization.canonical_string(compact) != _text("one-doc-serialized.json.txt")

    def test_signatures_are_not_part_of_what_is_signed(self):
        signed = _text("one-doc-I.json")
        assert serialization.canonical_string(signed) == _text("one-doc-serialized.json.txt")

    def test_a_non_object_is_refused(self):
        with pytest.raises(serialization.EtaSerializationError):
            serialization.canonical_string('[{"a": 1}]')
        with pytest.raises(serialization.EtaSerializationError):
            serialization.canonical_string("not json")


class TestSignature:
    def test_the_digest_eta_signed_is_the_hash_of_our_serialization(self):
        parsed = signing.parse_cades(_signature_value())
        assert parsed.message_digest == hashlib.sha256(serialization.canonical_bytes(_text("one-doc.json"))).digest()
        assert parsed.message_digest.hex().upper().startswith("D43FAE25")

    def test_the_sdk_signature_verifies_over_our_signed_attributes(self):
        # Proves the RSA value covers the DER SET of the attributes, which is
        # what our signer hands to the token.
        signing.verify_cades(_signature_value(), serialization.canonical_bytes(_text("one-doc-I.json")))

    def test_our_builder_rebuilds_the_sdk_signature_byte_for_byte(self):
        value = _signature_value()
        parsed = signing.parse_cades(value)
        moment = datetime.strptime(parsed.signing_time, "%y%m%d%H%M%SZ").replace(tzinfo=UTC)
        digest = hashlib.sha256(serialization.canonical_bytes(_text("one-doc.json"))).digest()
        attributes = signing.signed_attributes(parsed.certificate, digest, moment)
        assert attributes == parsed.attributes
        rebuilt = signing.assemble(parsed.certificate, attributes, parsed.signature)
        assert rebuilt == base64.b64decode(value)

    def test_a_changed_document_fails_verification(self):
        altered = _text("one-doc.json").replace('"IID1"', '"IID2"')
        with pytest.raises(signing.EtaSigningError, match="different document"):
            signing.verify_cades(_signature_value(), serialization.canonical_bytes(altered))

    def test_the_test_signer_produces_a_signature_that_verifies(self):
        canonical = serialization.canonical_bytes(_text("one-doc.json"))
        fixed = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
        value = asyncio.run(signing.make_test_signer(clock=lambda: fixed).sign(canonical))
        signing.verify_cades(value, canonical)
        parsed = signing.parse_cades(value)
        assert parsed.signing_time == "261019080000Z"
        # Same shape as ETA's: four signed attributes, detached digestedData.
        assert len(parsed.attributes) == 4

    def test_a_signature_by_another_key_does_not_verify(self):
        canonical = serialization.canonical_bytes(_text("one-doc.json"))
        value = asyncio.run(signing.make_test_signer().sign(canonical))
        raw = bytearray(base64.b64decode(value))
        raw[-1] ^= 0x01  # flip one bit of the RSA value
        with pytest.raises(signing.EtaSigningError, match="does not verify"):
            signing.verify_cades(base64.b64encode(bytes(raw)).decode(), canonical)


class TestSignerResolution:
    def test_a_test_signer_is_refused_on_a_live_registration(self):
        with pytest.raises(signing.EtaSigningError, match="live"):
            signing.resolve_signer({"kind": "test"}, sandbox=False)
        assert signing.resolve_signer({"kind": "test"}, sandbox=True).is_test

    def test_an_unknown_or_missing_kind_is_refused_by_name(self):
        with pytest.raises(signing.EtaSigningError, match="No signer"):
            signing.resolve_signer({}, sandbox=True)
        with pytest.raises(signing.EtaSigningError, match="Unknown signer kind 'magic'"):
            signing.resolve_signer({"kind": "magic"}, sandbox=True)

    def test_pkcs11_names_every_missing_setting(self):
        with pytest.raises(signing.EtaSigningError, match="library, token_label, key_label, pin_env"):
            signing.resolve_signer({"kind": "pkcs11"}, sandbox=False)

    def test_pkcs11_signs_through_the_token_library(self, monkeypatch):
        # A stand-in for python-pkcs11 with the calls the signer makes, backed
        # by a software key. Proves the wiring, not a token.
        import sys
        import types

        key, cert = signing._throwaway_key()

        class _Obj(dict):
            pass

        class _Key:
            def sign(self, data, mechanism):
                assert mechanism == "SHA256_RSA_PKCS"
                return asyncio.run(signing.SoftwareKey(key, cert).sign(data))

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_objects(self, attrs):
                assert attrs["LABEL"] == "seal-cert"
                return [_Obj({"VALUE": cert})]

            def get_key(self, object_class, label):
                assert label == "seal"
                return _Key()

        class _Token:
            def open(self, user_pin):
                assert user_pin == "1234"
                return _Session()

        class _Lib:
            def __init__(self, path):
                assert path == "/opt/token/pkcs11.so"

            def get_token(self, token_label):
                assert token_label == "ePass"
                return _Token()

        fake = types.SimpleNamespace(
            lib=_Lib,
            Attribute=types.SimpleNamespace(CLASS="CLASS", LABEL="LABEL", VALUE="VALUE"),
            ObjectClass=types.SimpleNamespace(CERTIFICATE="CERTIFICATE", PRIVATE_KEY="PRIVATE_KEY"),
            Mechanism=types.SimpleNamespace(SHA256_RSA_PKCS="SHA256_RSA_PKCS"),
        )
        monkeypatch.setitem(sys.modules, "pkcs11", fake)
        monkeypatch.setenv("OE_TEST_TOKEN_PIN", "1234")
        signer = signing.resolve_signer(
            {
                "kind": "pkcs11",
                "library": "/opt/token/pkcs11.so",
                "token_label": "ePass",
                "key_label": "seal",
                "certificate_label": "seal-cert",
                "pin_env": "OE_TEST_TOKEN_PIN",
            },
            sandbox=False,
        )
        canonical = serialization.canonical_bytes(_text("one-doc.json"))
        signing.verify_cades(asyncio.run(signer.sign(canonical)), canonical)

    def test_pkcs11_without_the_library_says_what_to_install(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "pkcs11", None)
        monkeypatch.setenv("OE_TEST_TOKEN_PIN", "1234")
        signer = signing.resolve_signer(
            {"kind": "pkcs11", "library": "x", "token_label": "t", "key_label": "k", "pin_env": "OE_TEST_TOKEN_PIN"},
            sandbox=False,
        )
        with pytest.raises(signing.EtaSigningError, match="python-pkcs11"):
            asyncio.run(signer.sign(b"x"))


class TestDer:
    def test_integer_gets_a_leading_zero_when_the_top_bit_is_set(self):
        assert der.integer(127) == b"\x02\x01\x7f"
        assert der.integer(128) == b"\x02\x02\x00\x80"
        assert der.integer(0) == b"\x02\x01\x00"

    def test_oid_encodes_the_sha256_identifier(self):
        assert der.oid("2.16.840.1.101.3.4.2.1").hex() == "0609608648016503040201"

    def test_long_lengths_round_trip(self):
        element = der.octet_string(b"x" * 300)
        assert der.read(element).content == b"x" * 300
