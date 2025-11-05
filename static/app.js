// Global state
let currentLogDevice = null;
let logRefreshInterval = null;

// Load devices on page load
document.addEventListener('DOMContentLoaded', () => {
    loadDevices();

    // Refresh devices every 3 seconds
    setInterval(loadDevices, 3000);

    // Setup add device form
    document.getElementById('addDeviceForm').addEventListener('submit', handleAddDevice);
    document.getElementById('addDeviceBtn').addEventListener('click', openAddDeviceModal);
});

// Load and display devices
async function loadDevices() {
    try {
        const response = await fetch('/api/devices');
        const devices = await response.json();

        const container = document.getElementById('devicesContainer');

        if (devices.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <h2>No Devices Yet</h2>
                    <p>Click "Add Device" to get started</p>
                </div>
            `;
            return;
        }

        container.innerHTML = devices.map(device => createDeviceCard(device)).join('');
    } catch (error) {
        console.error('Failed to load devices:', error);
    }
}

// Create device card HTML
function createDeviceCard(device) {
    const statusClass = device.status;
    const statusText = device.status.charAt(0).toUpperCase() + device.status.slice(1);
    const isStopped = device.status === 'stopped';
    const isRunningOrStarting = device.status === 'running' || device.status === 'starting';

    return `
        <div class="device-card">
            <div class="device-header">
                <span class="status-dot ${statusClass}"></span>
                <span class="device-name">${device.name}</span>
            </div>
            <div class="device-info">
                <div><strong>UDID:</strong> ${device.udid.substring(0, 16)}...</div>
                <div><strong>Port:</strong> ${device.appium_port}</div>
                <div><strong>Status:</strong> ${statusText}</div>
            </div>
            <div class="device-actions">
                ${isRunningOrStarting ?
                    `<button class="btn btn-danger" onclick="stopDevice(${device.index})">⏹ Stop</button>` :
                    `<button class="btn btn-success" onclick="startDevice(${device.index})">▶ Start</button>`
                }
                <button class="btn btn-secondary" onclick="openLogs(${device.index}, '${device.name}')">📋 Logs</button>
                ${isStopped ?
                    `<button class="btn btn-danger btn-sm" onclick="deleteDevice(${device.index}, '${device.name}')">🗑️</button>` :
                    ''
                }
            </div>
        </div>
    `;
}

// Start device
async function startDevice(deviceIndex) {
    try {
        const response = await fetch(`/api/device/${deviceIndex}/start`, {
            method: 'POST'
        });

        const result = await response.json();

        if (result.success) {
            console.log('Device started successfully');
            loadDevices();
        } else {
            console.error('Failed to start device:', result.error);
        }
    } catch (error) {
        console.error('Error starting device:', error.message);
    }
}

// Stop device
async function stopDevice(deviceIndex) {
    if (!confirm('Are you sure you want to stop this device?')) {
        return;
    }

    try {
        const response = await fetch(`/api/device/${deviceIndex}/stop`, {
            method: 'POST'
        });

        const result = await response.json();

        if (result.success) {
            console.log('Device stopped successfully');
            loadDevices();
        } else {
            console.error('Failed to stop device');
        }
    } catch (error) {
        console.error('Error stopping device:', error.message);
    }
}

// Delete device
async function deleteDevice(deviceIndex, deviceName) {
    if (!confirm(`Are you sure you want to delete ${deviceName}? This cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/device/${deviceIndex}/delete`, {
            method: 'POST'
        });

        const result = await response.json();

        if (result.success) {
            console.log('Device deleted successfully');
            loadDevices();
        } else {
            console.error('Failed to delete device:', result.error);
        }
    } catch (error) {
        console.error('Error deleting device:', error.message);
    }
}

// Open logs modal
function openLogs(deviceIndex, deviceName) {
    currentLogDevice = deviceIndex;
    document.getElementById('logModalTitle').innerHTML = `🔴 Live Logs: ${deviceName} <small style="color: #22c55e; font-size: 12px; margin-left: 10px;">● LIVE</small>`;
    document.getElementById('logModal').classList.add('active');

    // Load logs immediately
    refreshLogs();

    // Auto-refresh logs every 1 second for real-time feel
    logRefreshInterval = setInterval(refreshLogs, 1000);
}

// Close logs modal
function closeLogModal() {
    document.getElementById('logModal').classList.remove('active');
    currentLogDevice = null;

    if (logRefreshInterval) {
        clearInterval(logRefreshInterval);
        logRefreshInterval = null;
    }
}

// Refresh logs
async function refreshLogs() {
    if (currentLogDevice === null) return;

    try {
        const response = await fetch(`/api/device/${currentLogDevice}/logs`);
        const result = await response.json();

        const logContent = document.getElementById('logContent');
        const wasAtBottom = logContent.scrollHeight - logContent.scrollTop <= logContent.clientHeight + 50;

        logContent.textContent = result.logs || 'No logs available';

        // Auto-scroll if user is at/near bottom or auto-scroll is enabled
        if (document.getElementById('autoScroll').checked || wasAtBottom) {
            logContent.scrollTop = logContent.scrollHeight;
        }
    } catch (error) {
        console.error('Failed to load logs:', error);
    }
}

// Clear log display
function clearLogDisplay() {
    document.getElementById('logContent').textContent = 'Logs cleared. Refresh to reload.';
}

// Open add device modal
function openAddDeviceModal() {
    document.getElementById('addDeviceModal').classList.add('active');
    document.getElementById('deviceName').value = '';
    document.getElementById('deviceUdid').value = '';
}

// Close add device modal
function closeAddDeviceModal() {
    document.getElementById('addDeviceModal').classList.remove('active');
}

// Handle add device form submission
async function handleAddDevice(e) {
    e.preventDefault();

    const name = document.getElementById('deviceName').value.trim();
    const udid = document.getElementById('deviceUdid').value.trim();

    if (!name || !udid) {
        console.warn('Please fill in all fields');
        return;
    }

    try {
        const response = await fetch('/api/device/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name, udid })
        });

        const result = await response.json();

        if (result.success) {
            closeAddDeviceModal();
            loadDevices();
            console.log('Device added successfully!');
        } else {
            console.error('Failed to add device:', result.error);
        }
    } catch (error) {
        console.error('Error adding device:', error.message);
    }
}

// Close modals when clicking outside
window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.classList.remove('active');

        if (event.target.id === 'logModal') {
            closeLogModal();
        }
    }
}
