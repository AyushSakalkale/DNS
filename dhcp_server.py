#!/usr/bin/env python3

import socket
import struct
import logging
import time
import ipaddress
import threading
from typing import Tuple, Optional, Dict
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from dhcp_db import DHCPDatabase

# Configure logging with rotation
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
    handlers=[
        RotatingFileHandler(
            'dhcp_server.log',
            maxBytes=1024*1024,  # 1MB
            backupCount=5
        ),
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class DHCPLease:
    ip_address: str
    mac_address: str
    lease_time: int  # in seconds
    start_time: datetime
    
    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.start_time + timedelta(seconds=self.lease_time)

class DHCPServer:
    # DHCP Message Types
    DHCPDISCOVER = 1
    DHCPOFFER = 2
    DHCPREQUEST = 3
    DHCPDECLINE = 4
    DHCPACK = 5
    DHCPNAK = 6
    DHCPRELEASE = 7
    
    def __init__(self, interface: str = '0.0.0.0', port: int = 67):
        self.interface = interface
        self.port = port
        self.socket = None
        self.server_ip = '192.168.1.1'
        
        # IP Pool Configuration
        self.network = "192.168.1.0/24"
        self.excluded_ips = {
            "192.168.1.0",   # Network address
            "192.168.1.1",   # Server IP
            "192.168.1.255"  # Broadcast address
        }
        self.lease_time = 3600  # 1 hour
        
        # Initialize database
        self.db = DHCPDatabase()
        
        # Add thread synchronization
        self.lock = threading.Lock()
        
        # DHCP Options
        self.dhcp_options = {
            1: socket.inet_aton('255.255.255.0'),  # Subnet mask
            3: socket.inet_aton('192.168.1.1'),   # Router
            6: socket.inet_aton('8.8.8.8'),       # DNS server
            42: socket.inet_aton('8.8.8.8'),      # NTP server
            51: struct.pack('!I', self.lease_time) # Lease time
        }
        
    def _get_available_ip(self, client_mac: str) -> Optional[str]:
        """Get an available IP address for a client."""
        with self.lock:
            # First check for static reservation
            static_res = self.db.get_static_reservation(client_mac)
            if static_res:
                logger.info(f"Using static IP reservation for {client_mac}: {static_res['ip_address']}")
                return static_res['ip_address']
            
            # Then check for existing lease
            existing_lease = self.db.get_lease(client_mac)
            if existing_lease:
                logger.info(f"Renewing existing lease for {client_mac}: {existing_lease['ip_address']}")
                return existing_lease['ip_address']
            
            # Clean up expired leases
            self.db.cleanup_expired_leases()
            
            # Get all active leases
            active_leases = {lease['ip_address'] for lease in self.db.get_all_leases()}
            
            # Find first available IP
            network = ipaddress.ip_network(self.network)
            for ip in network.hosts():
                ip_str = str(ip)
                if ip_str not in self.excluded_ips and ip_str not in active_leases:
                    return ip_str
            
            logger.error("No IP addresses available in the pool")
            return None

    def create_socket(self) -> None:
        """Create and configure the UDP socket."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # Set socket buffer size
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            
            # Bind to all interfaces
            self.socket.bind(('0.0.0.0', self.port))
            logger.info(f"DHCP Server listening on {self.interface}:{self.port}")
            logger.debug("Socket bound successfully")
        except Exception as e:
            logger.error(f"Failed to create socket: {e}")
            raise

    def parse_dhcp_packet(self, data: bytes) -> Tuple[int, bytes, bytes, Optional[str]]:
        """Parse DHCP packet and return message type, client MAC, transaction ID, and hostname."""
        try:
            logger.debug(f"Received packet of length: {len(data)} bytes")
            logger.debug(f"Raw packet data: {data.hex()}")
            
            message_type = 0
            client_mac = data[28:34]
            transaction_id = data[4:8]
            hostname = None
            
            # Parse options to find message type and hostname
            options = data[240:]
            logger.debug(f"DHCP options: {options.hex()}")
            
            i = 0
            while i < len(options):
                if options[i] == 53:  # DHCP Message Type option
                    message_type = options[i + 2]
                    logger.debug(f"Found DHCP message type: {message_type}")
                elif options[i] == 12:  # Hostname option
                    hostname = options[i+2:i+2+options[i+1]].decode('utf-8', errors='ignore')
                    logger.debug(f"Found hostname: {hostname}")
                if options[i] == 255:  # End option
                    break
                i += options[i + 1] + 2
                
            return message_type, client_mac, transaction_id, hostname
        except Exception as e:
            logger.error(f"Error parsing DHCP packet: {e}")
            return 0, b'', b'', None

    def create_dhcp_packet(self, message_type: int, client_mac: bytes, transaction_id: bytes, 
                          your_ip: str, requested_ip: Optional[str] = None) -> bytes:
        """Create a DHCP packet (OFFER or ACK)."""
        try:
            logger.debug(f"Creating DHCP packet type {message_type} for client MAC: {':'.join(f'{b:02x}' for b in client_mac)}")
            logger.debug(f"Transaction ID: {transaction_id.hex()}")
            
            # Basic DHCP packet structure
            packet = bytearray(240)
            
            # Set message type and hardware info
            packet[0] = 2  # Boot Reply
            packet[1] = 1  # Ethernet
            packet[2] = 6  # Hardware address length
            packet[3] = 0  # Hops
            
            # Transaction ID
            packet[4:8] = transaction_id
            
            # Your IP address
            your_ip_bytes = socket.inet_aton(your_ip)
            packet[16:20] = your_ip_bytes
            logger.debug(f"Offering IP address: {your_ip} ({your_ip_bytes.hex()})")
            
            # Server IP address
            server_ip_bytes = socket.inet_aton(self.server_ip)
            packet[20:24] = server_ip_bytes
            logger.debug(f"Server IP: {self.server_ip} ({server_ip_bytes.hex()})")
            
            # Client MAC address
            packet[28:34] = client_mac
            
            # Magic cookie
            packet[236:240] = struct.pack('!I', 0x63825363)
            
            # Add DHCP options
            options = bytearray()
            
            # Message type
            options.extend([53, 1, message_type])
            
            # Server identifier
            options.extend([54, 4])
            options.extend(server_ip_bytes)
            
            # Add all configured DHCP options
            for opt_code, opt_value in self.dhcp_options.items():
                options.extend([opt_code, len(opt_value)])
                options.extend(opt_value)
            
            # End option
            options.append(255)
            
            final_packet = packet + options
            logger.debug(f"Created DHCP packet: {final_packet.hex()}")
            return final_packet
            
        except Exception as e:
            logger.error(f"Error creating DHCP packet: {e}")
            return b''

    def handle_discover(self, client_mac: bytes, transaction_id: bytes, hostname: Optional[str] = None) -> None:
        """Handle DHCP DISCOVER message."""
        mac_str = ':'.join(f'{b:02x}' for b in client_mac)
        logger.info(f"Handling DISCOVER from {mac_str}")
        
        # Get an IP address for the client
        ip_to_offer = self._get_available_ip(mac_str)
        if not ip_to_offer:
            logger.error("No IP addresses available in the pool")
            return
            
        # Create and send DHCP OFFER
        offer = self.create_dhcp_packet(self.DHCPOFFER, client_mac, transaction_id, ip_to_offer)
        if offer:
            logger.debug("Sending DHCP OFFER packet...")
            try:
                self.socket.sendto(offer, ('255.255.255.255', 68))
                logger.info(f"Sent DHCP OFFER with IP {ip_to_offer}")
            except Exception as e:
                logger.error(f"Error sending DHCP OFFER: {e}")

    def handle_request(self, client_mac: bytes, transaction_id: bytes, hostname: Optional[str] = None) -> None:
        """Handle DHCP REQUEST message."""
        mac_str = ':'.join(f'{b:02x}' for b in client_mac)
        logger.info(f"Handling REQUEST from {mac_str}")
        
        # Get an IP address for the client
        ip_to_assign = self._get_available_ip(mac_str)
        if not ip_to_assign:
            logger.error("No IP addresses available in the pool")
            return
            
        # Create lease in database
        self.db.add_lease(mac_str, ip_to_assign, self.lease_time, hostname)
        
        # Create and send DHCP ACK
        ack = self.create_dhcp_packet(self.DHCPACK, client_mac, transaction_id, ip_to_assign)
        if ack:
            logger.debug("Sending DHCP ACK packet...")
            try:
                self.socket.sendto(ack, ('255.255.255.255', 68))
                logger.info(f"Sent DHCP ACK with IP {ip_to_assign}")
            except Exception as e:
                logger.error(f"Error sending DHCP ACK: {e}")

    def handle_client(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Handle a single client request in a separate thread."""
        try:
            message_type, client_mac, transaction_id, hostname = self.parse_dhcp_packet(data)
            mac_str = ':'.join(f'{b:02x}' for b in client_mac)
            
            if message_type == self.DHCPDISCOVER:
                self.handle_discover(client_mac, transaction_id, hostname)
            elif message_type == self.DHCPREQUEST:
                self.handle_request(client_mac, transaction_id, hostname)
            elif message_type == self.DHCPRELEASE:
                logger.info(f"Received RELEASE from {mac_str}")
                # The lease will expire naturally
            else:
                logger.warning(f"Received unexpected DHCP message type: {message_type}")
                
        except Exception as e:
            logger.error(f"Error handling client request: {e}")

    def run(self) -> None:
        """Main server loop."""
        try:
            self.create_socket()
            logger.info("Server initialized and ready to receive requests")
            
            while True:
                try:
                    logger.debug("Waiting for incoming DHCP packets...")
                    data, addr = self.socket.recvfrom(4096)  # Increased buffer size
                    logger.info(f"Received packet from {addr}")
                    
                    # Create a new thread to handle each client request
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(data, addr),
                        daemon=True
                    )
                    client_thread.start()
                    
                except Exception as e:
                    logger.error(f"Error processing packet: {e}")
                    continue
                    
        except KeyboardInterrupt:
            logger.info("Shutting down DHCP server...")
        finally:
            if self.socket:
                self.socket.close()
                logger.info("Socket closed")

if __name__ == "__main__":
    server = DHCPServer()
    server.run() 