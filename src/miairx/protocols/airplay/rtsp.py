"""Bounded RTSP framing. Binary bodies are never parsed as headers."""

from dataclasses import dataclass

MAX_HEADER = 16 * 1024
MAX_BODY = 2 * 1024 * 1024


@dataclass(frozen=True)
class Request:
    method: str
    uri: str
    headers: dict[str, str]
    body: bytes
    version: str = "RTSP/1.0"


def extract_request(buffer: bytes) -> tuple[Request | None, bytes]:
    end = buffer.find(b"\r\n\r\n")
    if end < 0:
        if len(buffer) > MAX_HEADER:
            raise ValueError("RTSP header too large")
        return None, buffer
    if end > MAX_HEADER:
        raise ValueError("RTSP header too large")
    lines = buffer[:end].decode("ascii").split("\r\n")
    method, uri, version = lines[0].split()
    if version not in ("RTSP/1.0", "HTTP/1.1"):
        raise ValueError("Unsupported request version")
    headers = {}
    for line in lines[1:]:
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key in headers:
            raise ValueError("Duplicate RTSP header")
        headers[key] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length < 0 or length > MAX_BODY:
        raise ValueError("Invalid RTSP body size")
    size = end + 4 + length
    if len(buffer) < size:
        return None, buffer
    return Request(method.upper(), uri, headers, buffer[end + 4 : size], version), buffer[size:]


def response(
    status: int, cseq: str = "0", headers=None, body: bytes = b"", *, version="RTSP/1.0"
) -> bytes:
    if version not in ("RTSP/1.0", "HTTP/1.1"):
        raise ValueError("Unsupported response version")
    reasons = {
        200: "OK",
        400: "Bad Request",
        403: "Forbidden",
        405: "Method Not Allowed",
        415: "Unsupported Media Type",
        453: "Not Enough Bandwidth",
        454: "Session Not Found",
        455: "Method Not Valid in This State",
        461: "Unsupported Transport",
        501: "Not Implemented",
        503: "Service Unavailable",
    }
    fields = {"CSeq": cseq, "Server": "AirTunes/105.1", "Content-Length": str(len(body))}
    fields.update(headers or {})
    if any("\r" in str(v) or "\n" in str(v) for v in fields.values()):
        raise ValueError("Invalid response header")
    head = f"{version} {status} {reasons.get(status, 'Error')}\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n"
    return head.encode("ascii") + body
