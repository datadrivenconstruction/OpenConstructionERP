# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The encryption the KSeF API 2.0 asks of a client.

Sources (MF, https://github.com/CIRFMF/ksef-docs, read 2026-10-19):

* ``sesja-interaktywna.md``: each invoice is encrypted with AES-256-CBC and
  PKCS#7 padding under a fresh 256 bit key and 128 bit IV; the key goes to KSeF
  encrypted with RSAES-OAEP (SHA-256, MGF1 SHA-256) under the Ministry's public
  key published for ``SymmetricKeyEncryption``.
* ``uwierzytelnianie.md``: a KSeF token authenticates as
  ``RSA-OAEP-SHA256("{token}|{timestampMs}")`` under the key published for
  ``KsefTokenEncryption``, Base64.

``cryptography`` is already a core dependency (through ``python-jose``), so this
adds none.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


@dataclass(frozen=True)
class FileMetadata:
    """SHA-256 (Base64) and size, the pair KSeF wants for both forms of a document."""

    sha256_b64: str
    size: int


@dataclass(frozen=True)
class SessionKey:
    key: bytes
    iv: bytes

    @classmethod
    def generate(cls) -> SessionKey:
        return cls(key=os.urandom(32), iv=os.urandom(16))


def metadata(data: bytes) -> FileMetadata:
    return FileMetadata(base64.b64encode(hashlib.sha256(data).digest()).decode("ascii"), len(data))


def encrypt_document(data: bytes, session_key: SessionKey) -> bytes:
    """AES-256-CBC with PKCS#7 padding."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(session_key.key), modes.CBC(session_key.iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_document(data: bytes, session_key: SessionKey) -> bytes:
    """The inverse of :func:`encrypt_document`, for tests and for downloaded documents."""
    decryptor = Cipher(algorithms.AES(session_key.key), modes.CBC(session_key.iv)).decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def public_key_from_certificate(certificate_b64: str) -> RSAPublicKey:
    """The RSA key inside a certificate as ``GET /security/public-key-certificates`` returns it."""
    cert = x509.load_der_x509_certificate(base64.b64decode(certificate_b64))
    key = cert.public_key()
    if not isinstance(key, RSAPublicKey):
        raise ValueError("the KSeF public key certificate does not carry an RSA key")
    return key


def oaep_encrypt(public_key: RSAPublicKey, data: bytes) -> bytes:
    """RSAES-OAEP with SHA-256 and MGF1 SHA-256."""
    return public_key.encrypt(
        data,
        asym_padding.OAEP(mgf=asym_padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )


def encrypt_token(public_key: RSAPublicKey, token: str, timestamp_ms: int) -> str:
    """The ``encryptedToken`` field of ``POST /auth/ksef-token``."""
    return base64.b64encode(oaep_encrypt(public_key, f"{token}|{timestamp_ms}".encode())).decode("ascii")


__all__ = [
    "FileMetadata",
    "SessionKey",
    "decrypt_document",
    "encrypt_document",
    "encrypt_token",
    "metadata",
    "oaep_encrypt",
    "public_key_from_certificate",
]
