"""Test SSDP discovery with detailed logging"""

import socket
import struct
import time

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

def test_ssdp():
    """Test SSDP M-SEARCH."""
    print("Testing SSDP discovery...")
    print(f"Target: {SSDP_ADDR}:{SSDP_PORT}")
    
    # Create socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(5)
    
    # Bind to all interfaces
    sock.bind(("", 0))
    local_port = sock.getsockname()[1]
    print(f"Local port: {local_port}")
    
    # Join multicast group
    try:
        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(SSDP_ADDR),
            socket.inet_aton("0.0.0.0"),
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        print("Joined multicast group")
    except Exception as e:
        print(f"Failed to join multicast group: {e}")
    
    # Send M-SEARCH
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        "MAN: \"ssdp:discover\"\r\n"
        "MX: 3\r\n"
        "ST: ssdp:all\r\n"
        "\r\n"
    )
    
    print(f"Sending M-SEARCH...")
    try:
        sock.sendto(message.encode(), (SSDP_ADDR, SSDP_PORT))
        print("M-SEARCH sent")
    except Exception as e:
        print(f"Failed to send M-SEARCH: {e}")
        return
    
    # Listen for responses
    print("Listening for responses...")
    devices = []
    start_time = time.time()
    
    try:
        while time.time() - start_time < 5:
            try:
                data, addr = sock.recvfrom(4096)
                response = data.decode("utf-8", errors="ignore")
                
                print(f"\nReceived response from {addr}:")
                print(response[:200])
                
                # Check if it's a response to our M-SEARCH
                if "HTTP/1.1 200 OK" in response:
                    # Parse LOCATION
                    for line in response.split("\r\n"):
                        if line.startswith("LOCATION:"):
                            location = line.split(":", 1)[1].strip()
                            if location not in devices:
                                devices.append(location)
                                print(f"Found device: {location}")
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        print("\nInterrupted")
    
    sock.close()
    
    print(f"\nFound {len(devices)} devices")
    if devices:
        for device in devices:
            print(f"  - {device}")
    else:
        print("No devices found. Possible reasons:")
        print("  1. MiAirX service not running")
        print("  2. No speakers configured")
        print("  3. Firewall blocking SSDP")
        print("  4. Network interface issue")


if __name__ == "__main__":
    test_ssdp()
