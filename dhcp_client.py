#!/usr/bin/env python3

import socket
import struct
import random
import time
import logging
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DHCPClient:
    # DHCP Message Types
    DHCPDISCOVER = 1
    DHCPOFFER = 2
    DHCPREQUEST = 3
    DHCPDECLINE = 4
    DHCPACK = 5
    DHCPNAK = 6
    DHCPRELEASE = 7

    def __init__(self):
        self.client_mac = bytes([random.randint(0, 255) for _ in range(6)])
        self.transaction_id = random.randint(0, 0xFFFFFFFF)
        self.server_ip = None
        self.offered_ip = None
        self.lease_time = None
        self.subnet_mask = None
        self.router = None
        
    def create_packet(self, message_type: int, requested_ip: Optional[str] = None) -> bytes:
        """Create a DHCP packet."""
        # Create a basic DHCP packet
        packet = bytearray(240)
        
        # Set message type and hardware info
        packet[0] = 1  # Boot Request
        packet[1] = 1  # Ethernet
        packet[2] = 6  # Hardware address length
        packet[3] = 0  # Hops
        
        # Transaction ID
        packet[4:8] = struct.pack('!I', self.transaction_id)
        
        # Client MAC address
        packet[28:34] = self.client_mac
        
        # Magic cookie
        packet[236:240] = struct.pack('!I', 0x63825363)
        
        # Add DHCP options
        options = bytearray()
        
        # Message type
        options.extend([53, 1, message_type])
        
        # Client identifier (MAC address)
        options.extend([61, 7, 1])  # Hardware type 1 (Ethernet)
        options.extend(self.client_mac)
        
        if requested_ip:
            # Requested IP address
            options.extend([50, 4])
            options.extend(socket.inet_aton(requested_ip))
            
            # Server identifier (if we know it)
            if self.server_ip:
                options.extend([54, 4])
                options.extend(socket.inet_aton(self.server_ip))
        
        # Parameter request list
        options.extend([55, 4, 1, 3, 6, 42])  # Request subnet mask, router, DNS, NTP
        
        # End option
        options.append(255)
        
        logger.debug(f"Created DHCP packet type {message_type}: {(packet + options).hex()}")
        return packet + options
        
    def parse_response(self, data: bytes) -> Tuple[int, Optional[str], Optional[str]]:
        """Parse DHCP response and extract message type, offered IP, and server IP."""
        try:
            message_type = 0
            offered_ip = None
            server_ip = None
            
            # Extract offered IP
            if data[0] == 2:  # Boot Reply
                offered_ip = socket.inet_ntoa(data[16:20])
                server_ip = socket.inet_ntoa(data[20:24])
            
            # Parse options
            options = data[240:]
            i = 0
            while i < len(options):
                if options[i] == 255:  # End
                    break
                if options[i] == 53:  # Message Type
                    message_type = options[i + 2]
                elif options[i] == 51:  # Lease Time
                    self.lease_time = struct.unpack('!I', options[i + 2:i + 6])[0]
                elif options[i] == 1:  # Subnet Mask
                    self.subnet_mask = socket.inet_ntoa(options[i + 2:i + 6])
                elif options[i] == 3:  # Router
                    self.router = socket.inet_ntoa(options[i + 2:i + 6])
                i += options[i + 1] + 2
                
            return message_type, offered_ip, server_ip
        except Exception as e:
            logger.error(f"Error parsing DHCP response: {e}")
            return 0, None, None
            
    def release_ip(self, sock: socket.socket) -> None:
        """Release the leased IP address."""
        if not (self.offered_ip and self.server_ip):
            logger.warning("No IP lease to release")
            return
            
        release_packet = self.create_packet(self.DHCPRELEASE, self.offered_ip)
        try:
            sock.sendto(release_packet, (self.server_ip, 67))
            logger.info(f"Sent DHCP RELEASE for IP {self.offered_ip}")
        except Exception as e:
            logger.error(f"Error sending DHCP RELEASE: {e}")

def main():
    client = DHCPClient()
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Bind to the client port
    sock.bind(('0.0.0.0', 68))
    sock.settimeout(5)  # 5 second timeout
    
    try:
        # Step 1: Send DISCOVER
        discover_packet = client.create_packet(client.DHCPDISCOVER)
        logger.info(f"Sending DHCP DISCOVER with transaction ID: {client.transaction_id}")
        logger.info(f"Client MAC: {':'.join(f'{b:02x}' for b in client.client_mac)}")
        
        sock.sendto(discover_packet, ('255.255.255.255', 67))
        
        # Step 2: Receive OFFER
        try:
            logger.debug("Waiting for DHCP OFFER...")
            data, addr = sock.recvfrom(1024)
            logger.info(f"Received response from {addr}")
            
            message_type, offered_ip, server_ip = client.parse_response(data)
            if message_type == client.DHCPOFFER and offered_ip and server_ip:
                client.offered_ip = offered_ip
                client.server_ip = server_ip
                logger.info(f"Received DHCP OFFER - IP: {offered_ip}, Server: {server_ip}")
                
                # Step 3: Send REQUEST
                request_packet = client.create_packet(client.DHCPREQUEST, offered_ip)
                logger.info(f"Sending DHCP REQUEST for IP {offered_ip}")
                sock.sendto(request_packet, ('255.255.255.255', 67))
                
                # Step 4: Receive ACK
                logger.debug("Waiting for DHCP ACK...")
                data, addr = sock.recvfrom(1024)
                message_type, ack_ip, server_ip = client.parse_response(data)
                
                if message_type == client.DHCPACK:
                    logger.info(f"Received DHCP ACK - Lease acquired!")
                    logger.info(f"IP Address: {client.offered_ip}")
                    logger.info(f"Subnet Mask: {client.subnet_mask}")
                    logger.info(f"Router: {client.router}")
                    logger.info(f"Lease Time: {client.lease_time} seconds")
                    
                    # Wait a bit then release the IP
                    time.sleep(2)
                    client.release_ip(sock)
                elif message_type == client.DHCPNAK:
                    logger.error("Received DHCP NAK - Request rejected")
                else:
                    logger.error(f"Unexpected message type: {message_type}")
            else:
                logger.error("Did not receive a valid DHCP OFFER")
                
        except socket.timeout:
            logger.error("Timeout waiting for DHCP response")
            
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    main() 