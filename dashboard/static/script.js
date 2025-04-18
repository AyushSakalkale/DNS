// Global variables
let leasesTable = document.querySelector('.table-responsive');
let leasesTableBody = document.getElementById('leases-table-body');
let logsContainer = document.getElementById('log-container');
let lastUpdatedSpan = document.getElementById('last-updated');
let statusIndicator = document.querySelector('.status-indicator');

// Function to format timestamps
function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    return new Date(timestamp).toLocaleString();
}

// Update the last updated timestamp
function updateLastUpdated() {
    const now = new Date();
    lastUpdatedSpan.textContent = now.toLocaleTimeString();
}

// Show a notification
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);

    // Remove the notification after animation completes
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Show loading state
function showLoading(element) {
    element.style.opacity = '0.5';
    element.style.pointerEvents = 'none';
}

// Hide loading state
function hideLoading(element) {
    element.style.opacity = '1';
    element.style.pointerEvents = 'auto';
}

// Refresh leases table
async function refreshLeases(showNotifications = true) {
    showLoading(leasesTable);
    try {
        const response = await fetch('/api/leases');
        const leases = await response.json();
        
        // Clear existing table body
        leasesTableBody.innerHTML = '';
        
        // Add new rows
        leases.forEach(lease => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${lease.mac_address}</td>
                <td>${lease.ip_address}</td>
                <td>${lease.hostname || '-'}</td>
                <td>${lease.lease_start}</td>
                <td>${lease.lease_end}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="releaseLease('${lease.mac_address}')">
                        Release
                    </button>
                </td>
            `;
            leasesTableBody.appendChild(row);
        });
        
        if (showNotifications) {
            showNotification('Leases refreshed successfully', 'success');
        }
    } catch (error) {
        console.error('Error refreshing leases:', error);
        if (showNotifications) {
            showNotification('Failed to refresh leases', 'error');
        }
    } finally {
        hideLoading(leasesTable);
    }
}

// Refresh logs
async function refreshLogs() {
    showLoading(logsContainer);
    try {
        const response = await fetch('/api/logs');
        const logs = await response.json();
        
        // Clear existing logs
        logsContainer.innerHTML = '';
        
        // Add new log entries
        logs.forEach(log => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            
            // Determine log level for styling
            if (log.includes('ERROR')) {
                entry.classList.add('error');
            } else if (log.includes('WARNING')) {
                entry.classList.add('warning');
            } else if (log.includes('INFO')) {
                entry.classList.add('info');
            }
            
            entry.textContent = log;
            logsContainer.appendChild(entry);
        });
        
        // Scroll to bottom
        logsContainer.scrollTop = logsContainer.scrollHeight;
        
        showNotification('Logs refreshed successfully', 'success');
    } catch (error) {
        console.error('Error refreshing logs:', error);
        showNotification('Failed to refresh logs', 'error');
    } finally {
        hideLoading(logsContainer);
    }
}

// Release a lease
async function releaseLease(macAddress) {
    try {
        const response = await fetch('/api/release', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ mac_address: macAddress })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Check if there's a warning message
            if (data.warning) {
                showNotification(data.warning, 'warning');
            } else {
                showNotification('Lease released successfully', 'success');
            }
            refreshLeases(false); // Don't show notifications for this refresh
        } else {
            throw new Error(data.error || 'Failed to release lease');
        }
    } catch (error) {
        console.error('Error releasing lease:', error);
        showNotification(`Failed to release lease: ${error.message}`, 'error');
    }
}

// Check server status
async function checkServerStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();
        
        statusIndicator.className = `status-indicator ${status.online ? 'online' : 'offline'}`;
        
        // Update the status text
        const statusText = document.querySelector('.status-text');
        if (statusText) {
            statusText.textContent = status.online ? 'DHCP Server is running' : 'DHCP Server is offline';
        }
        
        if (!status.online) {
            showNotification('DHCP server is offline', 'warning');
        }
    } catch (error) {
        console.error('Error checking server status:', error);
        statusIndicator.className = 'status-indicator offline';
        
        // Update the status text
        const statusText = document.querySelector('.status-text');
        if (statusText) {
            statusText.textContent = 'DHCP Server status unknown';
        }
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Initial refresh
    refreshLeases(true);
    refreshLogs();
    checkServerStatus();
    updateLastUpdated();
    
    // Set up periodic updates
    setInterval(() => refreshLeases(true), 30000);
    setInterval(refreshLogs, 30000);
    setInterval(checkServerStatus, 30000);
    setInterval(updateLastUpdated, 30000);
}); 