#!/usr/bin/env python3

import socket
import struct
import logging
import threading
import queue
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
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

    def __init__(self, mac: str, hostname: str = "static-test"):
        # Convert string MAC to bytes
        self.client_mac = bytes.fromhex(mac.replace(':', ''))
        self.transaction_id = 0x12345678
        self.hostname = hostname
        self.server_ip = None
        self.offered_ip = None
        self.lease_time = None
        self.renewal_time = None
        self.rebinding_time = None
        self.lease_start = None
        
        # Create socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', 68))
        
    def create_packet(self, message_type: int, requested_ip: Optional[str] = None) -> bytes:
        """Create a DHCP packet."""
        packet = bytearray(240)  # Basic DHCP packet
        
        # Message type and hardware info
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
        
        # DHCP Options
        options = bytearray()
        
        # Message type
        options.extend([53, 1, message_type])
        
        # Client identifier
        options.extend([61, 7, 1])  # Hardware type 1 (Ethernet)
        options.extend(self.client_mac)
        
        # Hostname
        hostname_bytes = self.hostname.encode('utf-8')
        options.extend([12, len(hostname_bytes)])
        options.extend(hostname_bytes)
        
        if requested_ip:
            # Requested IP address
            options.extend([50, 4])
            options.extend(socket.inet_aton(requested_ip))
            
            if self.server_ip:
                # Server identifier
                options.extend([54, 4])
                options.extend(socket.inet_aton(self.server_ip))
        
        # Parameter request list
        options.extend([55, 4, 1, 3, 6, 42])  # Request subnet mask, router, DNS, NTP
        
        # End option
        options.append(255)
        
        return packet + options
        
    def parse_response(self, data: bytes) -> Tuple[int, Optional[str], Optional[str]]:
        """Parse DHCP response."""
        message_type = 0
        offered_ip = None
        server_ip = None
        
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
                self.lease_start = datetime.now()
                self.renewal_time = self.lease_start + timedelta(seconds=self.lease_time * 0.5)
                self.rebinding_time = self.lease_start + timedelta(seconds=self.lease_time * 0.875)
            i += options[i + 1] + 2
            
        return message_type, offered_ip, server_ip
        
    def get_lease(self) -> bool:
        """Get initial DHCP lease."""
        # Send DISCOVER
        discover = self.create_packet(self.DHCPDISCOVER)
        logger.info("Sending DHCP DISCOVER...")
        self.sock.sendto(discover, ('255.255.255.255', 67))
        
        # Wait for OFFER
        self.sock.settimeout(5)
        try:
            data, addr = self.sock.recvfrom(4096)
            message_type, offered_ip, server_ip = self.parse_response(data)
            
            if message_type == self.DHCPOFFER and offered_ip and server_ip:
                self.offered_ip = offered_ip
                self.server_ip = server_ip
                logger.info(f"Received DHCP OFFER - IP: {offered_ip}, Server: {server_ip}")
                
                # Send REQUEST
                request = self.create_packet(self.DHCPREQUEST, offered_ip)
                logger.info(f"Sending DHCP REQUEST for IP {offered_ip}")
                self.sock.sendto(request, ('255.255.255.255', 67))
                
                # Wait for ACK
                data, addr = self.sock.recvfrom(4096)
                message_type, ack_ip, server_ip = self.parse_response(data)
                
                if message_type == self.DHCPACK:
                    logger.info(f"Received DHCP ACK - Lease acquired!")
                    logger.info(f"Lease Time: {self.lease_time} seconds")
                    logger.info(f"Renewal Time: {self.renewal_time}")
                    logger.info(f"Rebinding Time: {self.rebinding_time}")
                    return True
                    
        except socket.timeout:
            logger.error("Timeout waiting for DHCP response")
            
        return False
        
    def renew_lease(self) -> bool:
        """Attempt to renew the current lease."""
        if not (self.offered_ip and self.server_ip):
            logger.error("No active lease to renew")
            return False
            
        logger.info(f"Attempting to renew lease for IP {self.offered_ip}")
        
        # Send REQUEST to renew
        request = self.create_packet(self.DHCPREQUEST, self.offered_ip)
        self.sock.sendto(request, ('255.255.255.255', 67))
        
        # Wait for ACK
        try:
            data, addr = self.sock.recvfrom(4096)
            message_type, ack_ip, server_ip = self.parse_response(data)
            
            if message_type == self.DHCPACK:
                logger.info(f"Lease renewed successfully! New lease time: {self.lease_time} seconds")
                return True
            elif message_type == self.DHCPNAK:
                logger.warning("Received NAK during renewal")
                return False
                
        except socket.timeout:
            logger.error("Timeout waiting for renewal response")
            
        return False
        
    def release_lease(self):
        """Release the current lease."""
        if not (self.offered_ip and self.server_ip):
            return
            
        release = self.create_packet(self.DHCPRELEASE, self.offered_ip)
        self.sock.sendto(release, (self.server_ip, 67))
        logger.info(f"Released lease for IP {self.offered_ip}")
        
    def run(self):
        """Run the client with lease renewal."""
        try:
            if not self.get_lease():
                logger.error("Failed to get initial lease")
                return
                
            # Main lease management loop
            while True:
                now = datetime.now()
                
                if now >= self.renewal_time:
                    logger.info("Renewal time reached")
                    if not self.renew_lease():
                        logger.error("Failed to renew lease")
                        break
                        
                time.sleep(1)  # Check every second
                
        except KeyboardInterrupt:
            logger.info("Shutting down client...")
            self.release_lease()
        finally:
            self.sock.close()

def main():
    # Use our static reservation MAC address
    client = DHCPClient("aa:bb:cc:dd:ee:ff", "static-test")
    client.run()

if __name__ == "__main__":
    main() 