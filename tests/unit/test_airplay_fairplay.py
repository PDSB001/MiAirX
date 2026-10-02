"""FairPlay state/security and independent C/Go reference-vector checks."""

import sys

import pytest

from miairx.protocols.airplay.fairplay import FairPlayError, FairPlaySession


def first(mode):
    return b"FPLY\x03\x01\x01\0\0\0\0\x04\x02\0" + bytes([mode, 0])


@pytest.mark.parametrize("mode", range(4))
def test_handshake_modes(mode):
    session = FairPlaySession()
    reply = session.setup(first(mode))
    assert len(reply) == 142 and reply[:12] == b"FPLY\x03\x01\x02\0\0\0\0\x82"
    assert reply[13] == mode
    message = b"FPLY\x03\x01\x03\0\0\0\0\x98" + bytes([mode]) + bytes(range(151))
    assert session.setup(message) == b"FPLY\x03\x01\x04\0\0\0\0\x14" + message[-20:]
    with pytest.raises(FairPlayError) as error:
        session.setup(message)
    assert error.value.status == 455


def test_captured_reference_decrypt_has_no_output_or_global_side_effect(fairplay_vector, capsys):
    message, encrypted, expected = fairplay_vector
    output = sys.stdout
    session = FairPlaySession()
    session.setup(first(message[12]))
    session.setup(message)
    assert session.decrypt_key(encrypted) == expected
    assert sys.stdout is output
    assert capsys.readouterr() == ("", "")
    with pytest.raises(FairPlayError) as error:
        session.decrypt_key(encrypted)
    assert error.value.status == 455


def test_expiry_restart_and_connection_isolation(fairplay_vector, monkeypatch):
    message, encrypted, expected = fairplay_vector
    clock = [100.0]
    monkeypatch.setattr("miairx.protocols.airplay.fairplay.time.monotonic", lambda: clock[0])
    session = FairPlaySession()
    session.setup(first(1))
    session.setup(message)
    with pytest.raises(FairPlayError) as error:
        FairPlaySession().decrypt_key(encrypted)
    assert error.value.status == 455
    clock[0] += 31
    with pytest.raises(FairPlayError) as error:
        session.decrypt_key(encrypted)
    assert error.value.status == 455
    session.setup(first(1))
    session.setup(message)
    assert session.decrypt_key(encrypted) == expected


@pytest.mark.parametrize("body", [b"", bytes(16), first(4), first(0)[:-1], first(0) + b"x"])
def test_malformed_handshake(body):
    with pytest.raises(FairPlayError) as error:
        FairPlaySession().setup(body)
    assert error.value.status == 400


def test_out_of_order_wrong_mode_version_and_key_header(fairplay_vector):
    message, encrypted, _ = fairplay_vector
    session = FairPlaySession()
    with pytest.raises(FairPlayError) as error:
        session.setup(message)
    assert error.value.status == 455
    session.setup(first(0))
    with pytest.raises(FairPlayError) as error:
        session.setup(message)
    assert error.value.status == 400
    with pytest.raises(FairPlayError) as error:
        session.setup(first(1)[:4] + b"\2" + first(1)[5:])
    assert error.value.status == 415
    session.setup(first(1))
    session.setup(message)
    with pytest.raises(FairPlayError) as error:
        session.decrypt_key(b"BAD!" + encrypted[4:])
    assert error.value.status == 400
