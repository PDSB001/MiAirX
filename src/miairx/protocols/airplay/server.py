"""AirPlay RTSP server for MiAirX"""

import asyncio
import logging
import socket
import threading
from typing import Callable, Optional

from miairx.protocols.airplay.crypto import AirplayCrypto
from miairx.protocols.airplay.audio import AudioStreamServer
from miairx.protocols.airplay.mdns import AirplayMdns

log = logging.getLogger(__name__)


class AirplayServer:
    """AirPlay RTSP server implementing RAOP protocol.
    
    This server handles AirPlay 1 (RAOP) connections from iOS devices.
    It receives audio streams and forwards them to Xiaomi speakers via HTTP.
    """

    def __init__(
        self,
        hostname: str,
        device_name: str,
        shared_zeroconf=None,
        speaker_hardware: str = "",
    ):
        self.hostname = hostname
        self.device_name = device_name
        self.speaker_hardware = speaker_hardware
        
        # Generate device ID
        self.device_id = AirplayCrypto.generate_device_id()
        
        # RTSP server
        self.rtsp_port = 0
        self._server_socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Audio stream server
        self._audio_server = AudioStreamServer(hostname, audio_format="wav")
        
        # mDNS advertiser
        self._mdns = AirplayMdns(
            hostname=hostname,
            device_name=device_name,
            device_id=self.device_id,
            rtsp_port=0,  # Will be updated after port allocation
            shared_zeroconf=shared_zeroconf,
        )
        
        # Callbacks
        self.on_play_start: Optional[Callable[[str], None]] = None
        self.on_play_stop: Optional[Callable[[], None]] = None
        self.on_volume_change: Optional[Callable[[float], None]] = None
        
        # Session state
        self._session_active = False
        self._aes_key: Optional[bytes] = None
        self._aes_iv: Optional[bytes] = None

    async def start(self):
        """Start the AirPlay server."""
        # Start audio stream server
        await self._audio_server.start()
        
        # Create RTSP server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(("0.0.0.0", 0))
        self._server_socket.listen(5)
        self.rtsp_port = self._server_socket.getsockname()[1]
        
        # Update mDNS port
        self._mdns.update_port(self.rtsp_port)
        
        # Start mDNS advertiser
        self._mdns.start()
        
        # Start RTSP server thread
        self._running = True
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
        
        log.info(f"AirPlay server started: {self.device_name} (port {self.rtsp_port})")

    async def stop(self):
        """Stop the AirPlay server."""
        self._running = False
        
        # Stop mDNS
        self._mdns.stop()
        
        # Stop RTSP server
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        
        if self._server_thread:
            self._server_thread.join(timeout=2)
        
        # Stop audio server
        await self._audio_server.stop()
        
        log.info(f"AirPlay server stopped: {self.device_name}")

    def _run_server(self):
        """Run RTSP server in background thread."""
        try:
            while self._running:
                try:
                    self._server_socket.settimeout(1.0)
                    client_socket, addr = self._server_socket.accept()
                    log.info(f"AirPlay client connected: {addr}")
                    
                    # Handle client in new thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, addr),
                        daemon=True,
                    )
                    client_thread.start()
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        log.error(f"RTSP server error: {e}")
                    break
        except Exception as e:
            log.error(f"RTSP server thread error: {e}")

    def _handle_client(self, client_socket: socket.socket, addr: tuple):
        """Handle RTSP client connection."""
        try:
            buffer = b""
            while self._running:
                data = client_socket.recv(4096)
                if not data:
                    break
                
                buffer += data
                
                # Process complete RTSP requests
                while b"\r\n\r\n" in buffer:
                    header_end = buffer.index(b"\r\n\r\n") + 4
                    request_data = buffer[:header_end]
                    buffer = buffer[header_end:]
                    
                    # Parse and handle request
                    response = self._process_request(request_data, client_socket)
                    if response:
                        client_socket.sendall(response)
                        
        except Exception as e:
            log.error(f"Client handler error: {e}")
        finally:
            try:
                client_socket.close()
            except Exception:
                pass
            log.info(f"AirPlay client disconnected: {addr}")

    def _process_request(self, request_data: bytes, client_socket: socket.socket) -> Optional[bytes]:
        """Process RTSP request and return response."""
        try:
            request_str = request_data.decode("utf-8", errors="replace")
            lines = request_str.split("\r\n")
            
            if not lines:
                return None
            
            # Parse request line
            request_line = lines[0]
            parts = request_line.split(" ")
            if len(parts) < 2:
                return None
            
            method = parts[0]
            uri = parts[1]
            
            # Parse headers
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            
            # Handle different RTSP methods
            if method == "OPTIONS":
                return self._handle_options(uri, headers)
            elif method == "ANNOUNCE":
                return self._handle_announce(uri, headers, request_data)
            elif method == "SETUP":
                return self._handle_setup(uri, headers)
            elif method == "RECORD":
                return self._handle_record(uri, headers)
            elif method == "SET_PARAMETER":
                return self._handle_set_parameter(uri, headers, request_data)
            elif method == "TEARDOWN":
                return self._handle_teardown(uri, headers)
            elif method == "FLUSH":
                return self._handle_flush(uri, headers)
            else:
                log.warning(f"Unhandled RTSP method: {method}")
                return self._build_response(405, "Method Not Allowed")
                
        except Exception as e:
            log.error(f"Request processing error: {e}")
            return self._build_response(500, "Internal Server Error")

    def _handle_options(self, uri: str, headers: dict) -> bytes:
        """Handle OPTIONS request."""
        response_headers = {
            "Public": "ANNOUNCE, SETUP, RECORD, PAUSE, FLUSH, TEARDOWN, OPTIONS, GET_PARAMETER, SET_PARAMETER",
        }
        return self._build_response(200, "OK", response_headers)

    def _handle_announce(self, uri: str, headers: dict, request_data: bytes) -> bytes:
        """Handle ANNOUNCE request (SDP with encryption keys)."""
        try:
            # Extract SDP body
            body = request_data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in request_data else b""
            body_str = body.decode("utf-8", errors="replace")
            
            # Parse SDP
            for line in body_str.split("\n"):
                line = line.strip()
                if line.startswith("a=rsaaeskey:"):
                    key_b64 = line.split(":", 1)[1]
                    self._aes_key = AirplayCrypto.decrypt_rsa_aes_key(key_b64)
                    log.info("Got RSA AES key")
                elif line.startswith("a=aesiv:"):
                    iv_b64 = line.split(":", 1)[1]
                    self._aes_iv = AirplayCrypto.decode_base64(iv_b64)
                    log.info("Got AES IV")
            
            return self._build_response(200, "OK")
            
        except Exception as e:
            log.error(f"ANNOUNCE error: {e}")
            return self._build_response(500, "Internal Server Error")

    def _handle_setup(self, uri: str, headers: dict) -> bytes:
        """Handle SETUP request (transport parameters)."""
        response_headers = {
            "Transport": "RTP/AVP/UDP;unicast;mode=record;server_port=6000;control_port=6001;timing_port=6002",
        }
        return self._build_response(200, "OK", response_headers)

    def _handle_record(self, uri: str, headers: dict) -> bytes:
        """Handle RECORD request (start playback)."""
        self._session_active = True
        
        # Start audio streaming
        self._audio_server.start_streaming()
        
        # Notify play start
        if self.on_play_start:
            self.on_play_start(self._audio_server.stream_url)
        
        return self._build_response(200, "OK")

    def _handle_set_parameter(self, uri: str, headers: dict, request_data: bytes) -> bytes:
        """Handle SET_PARAMETER request (volume, metadata)."""
        try:
            body = request_data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in request_data else b""
            body_str = body.decode("utf-8", errors="replace")
            
            for line in body_str.split("\n"):
                line = line.strip()
                if line.startswith("volume:"):
                    volume_str = line.split(":", 1)[1].strip()
                    try:
                        volume = float(volume_str)
                        # Convert from dB to percentage (-28.125 to 0 dB -> 6% to 100%)
                        volume_pct = max(6, min(100, int((volume + 28.125) / 28.125 * 100)))
                        if self.on_volume_change:
                            self.on_volume_change(volume_pct)
                    except ValueError:
                        pass
            
            return self._build_response(200, "OK")
            
        except Exception as e:
            log.error(f"SET_PARAMETER error: {e}")
            return self._build_response(500, "Internal Server Error")

    def _handle_teardown(self, uri: str, headers: dict) -> bytes:
        """Handle TEARDOWN request (stop playback)."""
        self._session_active = False
        self._audio_server.stop_streaming()
        
        if self.on_play_stop:
            self.on_play_stop()
        
        return self._build_response(200, "OK")

    def _handle_flush(self, uri: str, headers: dict) -> bytes:
        """Handle FLUSH request."""
        return self._build_response(200, "OK")

    def _build_response(
        self,
        status_code: int,
        reason: str,
        headers: Optional[dict] = None,
    ) -> bytes:
        """Build RTSP response."""
        response = f"RTSP/1.0 {status_code} {reason}\r\n"
        
        if headers:
            for key, value in headers.items():
                response += f"{key}: {value}\r\n"
        
        response += "\r\n"
        return response.encode("utf-8")
