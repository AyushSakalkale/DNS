#!/bin/bash

# Check if the DHCP server process is running
if pgrep -f "dhcp_server.py" > /dev/null; then
    echo "DHCP Server Status: RUNNING"
    echo "Process ID(s):"
    pgrep -f "dhcp_server.py"
else
    echo "DHCP Server Status: NOT RUNNING"
fi

# Check if the dashboard is running
if curl -s http://localhost:5173/api/status > /dev/null 2>&1; then
    echo -e "\nDashboard Status: RUNNING"
    echo "Server Status from API:"
    curl -s http://localhost:5173/api/status | python3 -m json.tool
else
    echo -e "\nDashboard Status: NOT RUNNING"
fi 