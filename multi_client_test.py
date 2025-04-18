#!/usr/bin/env python3

import socket
import struct
import random
import time
import logging
import threading
import queue
from typing import Optional, Tuple, Dict
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

# Configure logging with rotation
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
    handlers=[
        RotatingFileHandler(
            'dhcp_client.log',
            maxBytes=1024*1024,  # 1MB
            backupCount=5
        ),
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

class SharedSocket:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        self.sock.bind(('0.0.0.0', 68))
        self.sock.settimeout(0.1)  # Short timeout for polling
        
        self.running = True
        self.response_queues: Dict[int, queue.Queue] = {}
        self.lock = threading.Lock()
        
        # Start receiver thread
        self.receiver_thread = threading.Thread(target=self._receive_responses, daemon=True)
        self.receiver_thread.start()
        
    def register_client(self, transaction_id: int) -> queue.Queue:
        """Register a client to receive responses."""
        with self.lock:
            q = queue.Queue()
            self.response_queues[transaction_id] = q
            return q
            
    def unregister_client(self, transaction_id: int) -> None:
        """Unregister a client."""
        with self.lock:
            if transaction_id in self.response_queues:
                del self.response_queues[transaction_id]
                
    def _receive_responses(self) -> None:
        """Background thread to receive and distribute responses."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                if len(data) >= 8:  # Minimum size for transaction ID
                    transaction_id = struct.unpack('!I', data[4:8])[0]
                    with self.lock:
                        if transaction_id in self.response_queues:
                            self.response_queues[transaction_id].put((data, addr))
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Error receiving response: {e}")
                
    def send(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Send data through the shared socket."""
        self.sock.sendto(data, addr)
        
    def close(self) -> None:
        """Close the shared socket."""
        self.running = False
        self.receiver_thread.join(timeout=1)
        self.sock.close()

class DHCPClient:
    # DHCP Message Types
    DHCPDISCOVER = 1
    DHCPOFFER = 2
    DHCPREQUEST = 3
    DHCPDECLINE = 4
    DHCPACK = 5
    DHCPNAK = 6
    DHCPRELEASE = 7

    def __init__(self, client_id: int, hostname: Optional[str] = None):
        self.client_id = client_id
        self.client_mac = bytes([random.randint(0, 255) for _ in range(6)])
        self.transaction_id = random.randint(0, 0xFFFFFFFF)
        self.server_ip = None
        self.offered_ip = None
        self.lease_time = None
        self.subnet_mask = None
        self.router = None
        self.hostname = hostname or f"client-{client_id}"
        self.lease_start = None
        self.renewal_time = None
        self.rebinding_time = None
        
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
        
        # Hostname
        if self.hostname:
            hostname_bytes = self.hostname.encode('utf-8')
            options.extend([12, len(hostname_bytes)])
            options.extend(hostname_bytes)
        
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
        
        logger.debug(f"Client {self.client_id}: Created DHCP packet type {message_type}: {(packet + options).hex()}")
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
                    # Calculate renewal and rebinding times
                    self.lease_start = datetime.now()
                    self.renewal_time = self.lease_start + timedelta(seconds=self.lease_time * 0.5)
                    self.rebinding_time = self.lease_start + timedelta(seconds=self.lease_time * 0.8)
                elif options[i] == 1:  # Subnet Mask
                    self.subnet_mask = socket.inet_ntoa(options[i + 2:i + 6])
                elif options[i] == 3:  # Router
                    self.router = socket.inet_ntoa(options[i + 2:i + 6])
                i += options[i + 1] + 2
                
            return message_type, offered_ip, server_ip
        except Exception as e:
            logger.error(f"Client {self.client_id}: Error parsing DHCP response: {e}")
            return 0, None, None
            
    def release_ip(self, shared_socket: SharedSocket) -> None:
        """Release the leased IP address."""
        if not (self.offered_ip and self.server_ip):
            logger.warning(f"Client {self.client_id}: No IP lease to release")
            return
            
        release_packet = self.create_packet(self.DHCPRELEASE, self.offered_ip)
        try:
            shared_socket.send(release_packet, (self.server_ip, 67))
            logger.info(f"Client {self.client_id}: Sent DHCP RELEASE for IP {self.offered_ip}")
        except Exception as e:
            logger.error(f"Client {self.client_id}: Error sending DHCP RELEASE: {e}")

    def renew_lease(self, shared_socket: SharedSocket) -> bool:
        """Attempt to renew the current lease."""
        if not (self.offered_ip and self.server_ip):
            logger.warning(f"Client {self.client_id}: No active lease to renew")
            return False
            
        logger.info(f"Client {self.client_id}: Attempting to renew lease for IP {self.offered_ip}")
        
        # Create REQUEST packet
        request_packet = self.create_packet(self.DHCPREQUEST, self.offered_ip)
        
        # Send REQUEST
        shared_socket.send(request_packet, ('255.255.255.255', 67))
        
        # Wait for ACK
        try:
            data, addr = shared_socket.response_queues[self.transaction_id].get(timeout=5)
            message_type, ack_ip, server_ip = self.parse_response(data)
            
            if message_type == self.DHCPACK:
                logger.info(f"Client {self.client_id}: Successfully renewed lease for IP {ack_ip}")
                return True
            elif message_type == self.DHCPNAK:
                logger.warning(f"Client {self.client_id}: Received NAK during renewal")
                return False
            else:
                logger.error(f"Client {self.client_id}: Unexpected message type during renewal: {message_type}")
                return False
                
        except queue.Empty:
            logger.error(f"Client {self.client_id}: Timeout waiting for renewal response")
            return False

def client_thread(client_id: int, shared_socket: SharedSocket):
    """Thread function for each DHCP client."""
    client = DHCPClient(client_id, f"client-{client_id}")
    
    try:
        # Register for responses
        response_queue = shared_socket.register_client(client.transaction_id)
        
        # Step 1: Send DISCOVER
        discover_packet = client.create_packet(client.DHCPDISCOVER)
        logger.info(f"Client {client_id}: Sending DHCP DISCOVER with transaction ID: {client.transaction_id}")
        logger.info(f"Client {client_id}: MAC: {':'.join(f'{b:02x}' for b in client.client_mac)}")
        
        # Implement retry mechanism with exponential backoff
        max_retries = 3
        retry_count = 0
        retry_delay = 1  # Start with 1 second delay
        
        while retry_count < max_retries:
            shared_socket.send(discover_packet, ('255.255.255.255', 67))
            
            try:
                data, addr = response_queue.get(timeout=5)
                logger.info(f"Client {client_id}: Received response from {addr}")
                
                message_type, offered_ip, server_ip = client.parse_response(data)
                if message_type == client.DHCPOFFER and offered_ip and server_ip:
                    client.offered_ip = offered_ip
                    client.server_ip = server_ip
                    logger.info(f"Client {client_id}: Received DHCP OFFER - IP: {offered_ip}, Server: {server_ip}")
                    break
                else:
                    logger.warning(f"Client {client_id}: Invalid OFFER received")
                    
            except queue.Empty:
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning(f"Client {client_id}: Timeout waiting for OFFER, retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Client {client_id}: Failed to receive OFFER after {max_retries} attempts")
                    return
        
        # Step 2: Send REQUEST
        request_packet = client.create_packet(client.DHCPREQUEST, client.offered_ip)
        logger.info(f"Client {client_id}: Sending DHCP REQUEST for IP {client.offered_ip}")
        
        # Reset retry parameters for REQUEST
        retry_count = 0
        retry_delay = 1
        
        while retry_count < max_retries:
            shared_socket.send(request_packet, ('255.255.255.255', 67))
            
            try:
                data, addr = response_queue.get(timeout=5)
                message_type, ack_ip, server_ip = client.parse_response(data)
                
                if message_type == client.DHCPACK:
                    logger.info(f"Client {client_id}: Received DHCP ACK - Lease acquired!")
                    logger.info(f"Client {client_id}: IP Address: {client.offered_ip}")
                    logger.info(f"Client {client_id}: Subnet Mask: {client.subnet_mask}")
                    logger.info(f"Client {client_id}: Router: {client.router}")
                    logger.info(f"Client {client_id}: Lease Time: {client.lease_time} seconds")
                    break
                elif message_type == client.DHCPNAK:
                    logger.error(f"Client {client_id}: Received DHCP NAK - Request rejected")
                    return
                else:
                    logger.warning(f"Client {client_id}: Invalid ACK received")
                    
            except queue.Empty:
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning(f"Client {client_id}: Timeout waiting for ACK, retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"Client {client_id}: Failed to receive ACK after {max_retries} attempts")
                    return
        
        # Step 3: Lease renewal loop
        while True:
            if client.renewal_time and datetime.now() >= client.renewal_time:
                logger.info(f"Client {client_id}: Lease renewal time reached")
                if not client.renew_lease(shared_socket):
                    logger.error(f"Client {client_id}: Failed to renew lease, attempting to get new lease")
                    break
                client.renewal_time = datetime.now() + timedelta(seconds=client.lease_time * 0.5)
            
            time.sleep(1)  # Check every second
            
    finally:
        shared_socket.unregister_client(client.transaction_id)

def main():
    # Create shared socket
    shared_socket = SharedSocket()
    
    try:
        # Number of clients to simulate
        num_clients = 5
        
        # Create and start client threads
        threads = []
        for i in range(num_clients):
            thread = threading.Thread(
                target=client_thread,
                args=(i, shared_socket),
                name=f"client_thread_{i}"
            )
            thread.start()
            threads.append(thread)
            time.sleep(0.1)  # Small delay between client starts
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
            
    finally:
        shared_socket.close()

if __name__ == "__main__":
    main() 