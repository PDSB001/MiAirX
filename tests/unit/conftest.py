"""Public interoperability vector data; no real user's credentials."""

import pytest


@pytest.fixture
def fairplay_vector():
    # omarroth/doubletake @ ae067228d76df011375164814b729932ed55ca2f,
    # internal/airplay/fairplay_key_test.go,
    # TestCapturedFairPlayKeyDecrypt: expected key cross-checked by C PlayFair.
    message = bytes.fromhex(
        "46504c590301030000000098018f1a9c7d0af257b31f21f5c2d2bc814c032d45"
        "7835ad0b06250574bbc7ab4a58cca6eead2c911d7f3e1e7ed4c058955dff3d5c"
        "eef014387a985bdb34995015e3dfbdacc56047cb926e093b13e9fdb5e1eee317c"
        "018bbc87fc5453c7671647da686da3d564875d03f8aea9d60092de06110bc7be0"
        "c16f391c369c75344ae47f33acfcf10e63a9b58bfce215e96001c49e4be967c50"
        "67f2a"
    )
    encrypted = bytes.fromhex(
        "46504c59010201000000003c0000000088e4f82c8178c18b4751ac24b27c0c2a"
        "00000010c899dc6965c1081de6a9d966e2ba3e34548cdbc651c322db18dc22f5"
        "8fe154a60aecee18"
    )
    return message, encrypted, bytes.fromhex("8e1214398d46d72e7b1b8e32f80c8bf0")
