"""XML templates for DLNA/UPnP in MiAirX"""

from xml.sax.saxutils import escape

from miairx.const import (
    AVTRANSPORT_SCPD,
    CONNECTION_MANAGER_SCPD,
    DEVICE_TYPE,
    RENDERING_CONTROL_SCPD,
)


def device_description_xml(udn: str, friendly_name: str, manufacturer: str = "MiAirX") -> str:
    """Generate device description XML."""
    from xml.sax.saxutils import escape
    # Ensure UDN has uuid: prefix
    if not udn.startswith("uuid:"):
        udn = f"uuid:{udn}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0" xmlns:dlna="urn:schemas-dlna-org:device-1-0">
  <specVersion>
    <major>1</major>
    <minor>0</minor>
  </specVersion>
  <device>
    <deviceType>{DEVICE_TYPE}</deviceType>
    <friendlyName>{escape(friendly_name)}</friendlyName>
    <manufacturer>{manufacturer}</manufacturer>
    <manufacturerURL>https://github.com/user/miairx</manufacturerURL>
    <modelDescription>MiAirX - Xiaomi Speaker DLNA Audio Renderer</modelDescription>
    <modelName>MiAirX Speaker</modelName>
    <modelNumber>1.0</modelNumber>
    <serialNumber>1</serialNumber>
    <UDN>{udn}</UDN>
    <dlna:X_DLNADOC>DMR-1.50</dlna:X_DLNADOC>
    <dlna:X_DLNACAP>audio-only</dlna:X_DLNACAP>
    <qq:X_QPlay_SoftwareCapability xmlns:qq="http://www.tencent.com">QPlay:2</qq:X_QPlay_SoftwareCapability>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
        <SCPDURL>/device/{udn}/AVTransport.xml</SCPDURL>
        <controlURL>/device/{udn}/AVTransport/control</controlURL>
        <eventSubURL>/device/{udn}/AVTransport/event</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
        <SCPDURL>/device/{udn}/RenderingControl.xml</SCPDURL>
        <controlURL>/device/{udn}/RenderingControl/control</controlURL>
        <eventSubURL>/device/{udn}/RenderingControl/event</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
        <SCPDURL>/device/{udn}/ConnectionManager.xml</SCPDURL>
        <controlURL>/device/{udn}/ConnectionManager/control</controlURL>
        <eventSubURL>/device/{udn}/ConnectionManager/event</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>"""


def soap_response(service_urn: str, action: str, params: dict[str, str]) -> str:
    """Generate SOAP response XML (with proper escaping like original project)."""
    params_xml = ""
    for key, value in params.items():
        params_xml += f"        <{key}>{escape(str(value))}</{key}>\n"

    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action}Response xmlns:u="{service_urn}">
{params_xml}    </u:{action}Response>
  </s:Body>
</s:Envelope>"""


def soap_fault(error_code: int, error_description: str) -> str:
    """Generate SOAP fault XML."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <s:Fault>
      <faultcode>s:Client</faultcode>
      <faultstring>UPnPError</faultstring>
      <detail>
        <UPnPError xmlns="urn:schemas-upnp-org:control-1-0">
          <errorCode>{error_code}</errorCode>
          <errorDescription>{error_description}</errorDescription>
        </UPnPError>
      </detail>
    </s:Fault>
  </s:Body>
</s:Envelope>"""
