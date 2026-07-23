"""Cryptographic utilities for AirPlay in MiAirX"""

import base64
import logging
from typing import Optional

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA

log = logging.getLogger(__name__)

# AirPort Express RSA private key (used for AirPlay 1 authentication)
AIRPORT_PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEpQIBAAKCAQEA59dE8qLieItsH1WgjrcFRKj6eUWqi+bGLOX1HL3U3GhC/j0Qg90u3sG/1CUt\n"
    "wC5vOYvfDmFI6oSFXi5ELabWJmT2dKHzBJKa3k9ok+8t9ucRqMd6DZHJ2YCCLlDRKSKv6kDqnw4U\n"
    "wPdpOMXziC/AMj3Z/lUVX1G7WSHCAWKf1zNS1eLvqr+boEjXuBOitnZ/bDzPHrTOZz0Dew0uowxf\n"
    "/+sG+NCK3eQJVxqcaJ/vEHKIVd2M+5qL71yJQ+87X6oV3eaYvt3zWZYD6z5vYTcrtij2VZ9Zmni/\n"
    "UAaHqn9JdsBWLUEpVviYnhimNVvYFZeCXg/IdTQ+x4IRdiXNv5hEewIDAQABAoIBAQDl8Axy9XfW\n"
    "BLmkzkEiqoSwF0PsmVrPzH9KsnwLGH+QZlvjWd8SWYGN7u1507HvhF5N3drJoVU3O14nDY4TFQAa\n"
    "LlJ9VM35AApXaLyY1ERrN7u9ALKd2LUwYhM7Km539O4yUFYikE2nIPscEsA5ltpxOgUGCY7b7ez5\n"
    "NtD6nL1ZKauw7aNXmVAvmJTcuPxWmoktF3gDJKK2wxZuNGcJE0uFQEG4Z3BrWP7yoNuSK3dii2jm\n"
    "lpPHr0O/KnPQtzI3eguhe0TwUem/eYSdyzMyVx/YpwkzwtYL3sR5k0o9rKQLtvLzfAqdBxBurciz\n"
    "aaA/L0HIgAmOit1GJA2saMxTVPNhAoGBAPfgv1oeZxgxmotiCcMXFEQEWflzhWYTsXrhUIuz5jFu\n"
    "a39GLS99ZEErhLdrwj8rDDViRVJ5skOp9zFvlYAHs0xh92ji1E7V/ysnKBfsMrPkk5KSKPrnjndM\n"
    "oPdevWnVkgJ5jxFuNgxkOLMuG9i53B4yMvDTCRiIPMQ++N2iLDaRAoGBAO9v//mU8eVkQaoANf0Z\n"
    "oMjW8CN4xwWA2cSEIHkd9AfFkftuv8oyLDCG3ZAf0vrhrrtkrfa7ef+AUb69DNggq4mHQAYBp7L+\n"
    "k5DKzJrKuO0r+R0YbY9pZD1+/g9dVt91d6LQNepUE/yY2PP5CNoFmjedpLHMOPFdVgqDzDFxU8hL\n"
    "AoGBANDrr7xAJbqBjHVwIzQ4To9pb4BNeqDndk5Qe7fT3+/H1njGaC0/rXE0Qb7q5ySgnsCb3DvA\n"
    "cJyRM9SJ7OKlGt0FMSdJD5KG0XPIpAVNwgpXXH5MDJg09KHeh0kXo+QA6viFBi21y340NonnEfdf\n"
    "54PX4ZGS/Xac1UK+pLkBB+zRAoGAf0AY3H3qKS2lMEI4bzEFoHeK3G895pDaK3TFBVmD7fV0Zhov\n"
    "17fegFPMwOII8MisYm9ZfT2Z0s5Ro3s5rkt+nvLAdfC/PYPKzTLalpGSwomSNYJcB9HNMlmhkGzc\n"
    "1JnLYT4iyUyx6pcZBmCd8bD0iwY/FzcgNDaUmbX9+XDvRA0CgYEAkE7pIPlE71qvfJQgoA9em0gI\n"
    "LAuE4Pu13aKiJnfft7hIjbK+5kyb3TysZvoyDnb3HOKvInK7vXbKuU4ISgxB2bB3HcYzQMGsz1qJ\n"
    "2gG0N5hvJpzwwhbhXqFKA4zaaSrw622wDniAK5MlIE0tIAKKP4yxNGjoD2QYjhBGuhvkWKY=\n"
    "-----END RSA PRIVATE KEY-----"
)


class AirplayCrypto:
    """Cryptographic utilities for AirPlay protocol."""

    @staticmethod
    def decrypt_rsa_aes_key(encrypted_key_b64: str) -> bytes:
        """Decrypt AES key using RSA (AirPlay 1 method).
        
        Args:
            encrypted_key_b64: Base64-encoded encrypted AES key
            
        Returns:
            Decrypted AES key (16 bytes)
        """
        try:
            airport_key = RSA.importKey(AIRPORT_PRIVATE_KEY)
            cipher = PKCS1_OAEP.new(airport_key)
            encrypted_key = base64.standard_b64decode(encrypted_key_b64 + "==")
            aes_key = cipher.decrypt(encrypted_key)
            
            if len(aes_key) != 16:
                log.warning(f"Unexpected AES key length: {len(aes_key)}")
            
            return aes_key
        except Exception as e:
            log.error(f"RSA AES key decryption failed: {e}")
            raise

    @staticmethod
    def decrypt_aes_cbc(data: bytes, key: bytes, iv: bytes) -> bytes:
        """Decrypt data using AES-CBC.
        
        Args:
            data: Encrypted data
            key: AES key (16 bytes)
            iv: AES IV (16 bytes)
            
        Returns:
            Decrypted data
        """
        try:
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(data)
            return decrypted
        except Exception as e:
            log.error(f"AES-CBC decryption failed: {e}")
            raise

    @staticmethod
    def decode_base64(data: str) -> bytes:
        """Decode base64 data (with padding fix).
        
        Args:
            data: Base64-encoded string
            
        Returns:
            Decoded bytes
        """
        # Add padding if needed
        padded = data + "=="
        return base64.standard_b64decode(padded)

    @staticmethod
    def encode_base64(data: bytes) -> str:
        """Encode data to base64 (without padding).
        
        Args:
            data: Bytes to encode
            
        Returns:
            Base64-encoded string (without trailing ==)
        """
        encoded = base64.standard_b64encode(data)
        # Remove trailing ==
        if encoded.endswith(b"=="):
            encoded = encoded[:-2]
        return encoded.decode("ascii")

    @staticmethod
    def generate_device_id() -> str:
        """Generate a random device ID in MAC address format.
        
        Returns:
            Device ID string (e.g., "AA:BB:CC:DD:EE:FF")
        """
        import random
        bytes_list = [random.randint(0, 255) for _ in range(6)]
        return ":".join(f"{b:02X}" for b in bytes_list)
