# src/pclink/core/e2ee.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Fixed application-wide salt & info for HKDF key expansion
E2EE_SALT = b"pclink-e2ee-payload-salt-v1"
E2EE_INFO = b"pclink-aes-256-gcm"


def derive_e2ee_key(api_key: str) -> bytes:
    """Derives a deterministic 32-byte AES-GCM key from the pairing API key using HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=E2EE_SALT,
        info=E2EE_INFO,
    )
    return hkdf.derive(api_key.encode("utf-8"))


def encrypt_payload(data: bytes, aes_key: bytes) -> bytes:
    """
    Encrypts plaintext data into wire format:
    [12-byte IV] + [Ciphertext + 16-byte Auth Tag]
    """
    iv = os.urandom(12)  # Fresh random 12-byte nonce per message
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(iv, data, None)
    return iv + ciphertext


def decrypt_payload(encrypted_data: bytes, aes_key: bytes) -> bytes:
    """
    Decrypts wire format payload:
    Extracts 12-byte IV from head, decrypts and validates auth tag.
    """
    if len(encrypted_data) < 28:
        raise ValueError("Payload too short to be valid AES-GCM ciphertext")

    iv = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    aesgcm = AESGCM(aes_key)
    return aesgcm.decrypt(iv, ciphertext, None)
