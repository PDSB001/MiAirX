"""Unit tests for SOAP handler"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from miairx.const import AVTRANSPORT_URN
from miairx.protocols.dlna.soap import SoapHandler, parse_soap_action, parse_soap_body


def test_parse_soap_action():
    """Test SOAP action parsing."""
    # Valid SOAPAction
    service_urn, action = parse_soap_action('"urn:schemas-upnp-org:service:AVTransport:1#Play"')
    assert service_urn == "urn:schemas-upnp-org:service:AVTransport:1"
    assert action == "Play"
    
    # Without quotes
    service_urn, action = parse_soap_action("urn:schemas-upnp-org:service:AVTransport:1#Stop")
    assert service_urn == "urn:schemas-upnp-org:service:AVTransport:1"
    assert action == "Stop"
    
    # Invalid format
    service_urn, action = parse_soap_action("InvalidAction")
    assert service_urn == ""
    assert action == "InvalidAction"


def test_parse_soap_body():
    """Test SOAP body parsing."""
    # Valid SOAP body
    body = """<?xml version="1.0" encoding="UTF-8"?>
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body>
        <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
          <InstanceID>0</InstanceID>
          <CurrentURI>http://example.com/song.mp3</CurrentURI>
          <CurrentURIMetaData></CurrentURIMetaData>
        </u:SetAVTransportURI>
      </s:Body>
    </s:Envelope>"""
    
    params = parse_soap_body(body)
    assert params["InstanceID"] == "0"
    assert params["CurrentURI"] == "http://example.com/song.mp3"


def test_parse_soap_body_empty():
    """Test empty SOAP body parsing."""
    params = parse_soap_body("")
    assert params == {}


def test_parse_soap_body_invalid():
    """Test invalid SOAP body parsing."""
    params = parse_soap_body("invalid xml")
    assert params == {}


@pytest.mark.asyncio
async def test_action_failure_returns_soap_fault():
    """Device failures should remain valid SOAP responses."""
    renderer = MagicMock()
    renderer.friendly_name = "Test Speaker"
    renderer.play = AsyncMock(side_effect=RuntimeError("cloud timeout"))

    response, status = await SoapHandler.handle_request(
        renderer,
        AVTRANSPORT_URN,
        "Play",
        {},
    )

    assert status == 500
    assert "Fault" in response
    assert "Action failed" in response
