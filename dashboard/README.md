# DHCP Server Dashboard

A simple web-based dashboard for monitoring and managing your DHCP server.

## Features

- View current DHCP leases
- Monitor server logs in real-time
- Release IP addresses from the UI
- Auto-refresh every 30 seconds

## Setup

1. Install the required dependencies:
   ```
   pip install -r ../requirements.txt
   ```

2. Start the dashboard:
   ```
   python app.py
   ```

3. Access the dashboard at http://localhost:5000

## Usage

- The dashboard automatically refreshes every 30 seconds
- Click the "Refresh" buttons to manually update the data
- Use the "Release" button to release an IP address for a specific MAC address

## API Endpoints

- `GET /api/leases` - Get all current DHCP leases
- `GET /api/logs` - Get the last 100 lines of server logs
- `POST /api/release` - Release an IP address (requires MAC address in request body)

## Notes

- The dashboard assumes the DHCP server is running and the database is accessible
- Make sure the DHCP server log file path is correct in `app.py`
- The dashboard is designed for local network use and should not be exposed to the internet without proper security measures 