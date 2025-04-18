import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

class DHCPDatabase:
    def __init__(self, db_path: str = 'dhcp.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create leases table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leases (
                    mac_address TEXT PRIMARY KEY,
                    ip_address TEXT NOT NULL,
                    hostname TEXT,
                    lease_start TIMESTAMP NOT NULL,
                    lease_end TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL
                )
            ''')
            
            # Create static reservations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS static_reservations (
                    mac_address TEXT PRIMARY KEY,
                    ip_address TEXT NOT NULL,
                    hostname TEXT,
                    description TEXT
                )
            ''')
            
            conn.commit()

    def add_lease(self, mac_address: str, ip_address: str, lease_time: int, hostname: Optional[str] = None):
        """Add or update a DHCP lease."""
        now = datetime.now()
        lease_end = now.timestamp() + lease_time
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO leases 
                (mac_address, ip_address, hostname, lease_start, lease_end, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (mac_address, ip_address, hostname, now.timestamp(), lease_end, now.timestamp()))
            conn.commit()

    def get_lease(self, mac_address: str) -> Optional[Dict]:
        """Get active lease for a MAC address."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT mac_address, ip_address, hostname, lease_start, lease_end, last_seen
                FROM leases
                WHERE mac_address = ? AND lease_end > ?
            ''', (mac_address, datetime.now().timestamp()))
            
            row = cursor.fetchone()
            if row:
                return {
                    'mac_address': row[0],
                    'ip_address': row[1],
                    'hostname': row[2],
                    'lease_start': datetime.fromtimestamp(row[3]),
                    'lease_end': datetime.fromtimestamp(row[4]),
                    'last_seen': datetime.fromtimestamp(row[5])
                }
            return None

    def add_static_reservation(self, mac_address: str, ip_address: str, 
                             hostname: Optional[str] = None, description: Optional[str] = None):
        """Add a static IP reservation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO static_reservations 
                (mac_address, ip_address, hostname, description)
                VALUES (?, ?, ?, ?)
            ''', (mac_address, ip_address, hostname, description))
            conn.commit()

    def get_static_reservation(self, mac_address: str) -> Optional[Dict]:
        """Get static IP reservation for a MAC address."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT mac_address, ip_address, hostname, description
                FROM static_reservations
                WHERE mac_address = ?
            ''', (mac_address,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'mac_address': row[0],
                    'ip_address': row[1],
                    'hostname': row[2],
                    'description': row[3]
                }
            return None

    def get_all_leases(self) -> List[Dict]:
        """Get all active leases."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT mac_address, ip_address, hostname, lease_start, lease_end, last_seen
                FROM leases
                WHERE lease_end > ?
            ''', (datetime.now().timestamp(),))
            
            return [{
                'mac_address': row[0],
                'ip_address': row[1],
                'hostname': row[2],
                'lease_start': datetime.fromtimestamp(row[3]),
                'lease_end': datetime.fromtimestamp(row[4]),
                'last_seen': datetime.fromtimestamp(row[5])
            } for row in cursor.fetchall()]

    def cleanup_expired_leases(self):
        """Remove expired leases from the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM leases
                WHERE lease_end <= ?
            ''', (datetime.now().timestamp(),))
            conn.commit() 