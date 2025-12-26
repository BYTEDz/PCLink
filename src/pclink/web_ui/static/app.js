// PCLink Web UI JavaScript
class PCLinkWebUI {
    constructor() {
        this.apiKey = null;
        this.baseUrl = window.location.origin;
        this.currentPath = '/';
        this.processes = [];
        this.devices = [];
        this.connectedDevices = [];
        this.websocket = null;
        this.pendingPairingRequest = null;
        this.autoRefreshEnabled = true;
        this.notificationSettings = this.loadNotificationSettings();
        this.serverStartTime = Date.now();
        this.lastDeviceActivity = null;
        this.init();
    }

    async init() {
        console.log('Initializing PCLink UI...');
        this.setupEventListeners();
        await this.loadApiKey();
        await this.loadSettings();
        this.updateConnectionStatus();
        this.loadServerStatus();
        this.connectWebSocket();

        // Ensure the correct tab is active on load
        const currentTab = this.getCurrentTab();
        this.switchTab(currentTab);

        setInterval(() => {
            if (!this.autoRefreshEnabled) return;

            this.updateConnectionStatus();

            const activeTab = this.getCurrentTab();
            if (activeTab === 'dashboard') {
                this.updateActivity();
                this.updateServerStatus();
            } else if (activeTab === 'devices') {
                this.loadDevices();
            } else if (activeTab === 'logs') {
                this.loadLogs();
            }
        }, 5000);


        setInterval(() => {
            const lastDismissed = localStorage.getItem('updateDismissed');
            const now = Date.now();
            if (!lastDismissed || (now - parseInt(lastDismissed)) > 24 * 60 * 60 * 1000) {
                checkForUpdates();
            }
        }, 30 * 60 * 1000);

        setTimeout(() => checkForUpdates(), 5000);
        setTimeout(() => this.loadNotificationSettings(), 1000);
    }

    setupEventListeners() {
        console.log('Setting up event listeners...');

        // Event Delegation for Sidebar Navigation
        const sidebarNav = document.querySelector('.sidebar-nav');
        if (sidebarNav) {
            sidebarNav.addEventListener('click', (e) => {
                // Find the closest clicked element with class 'nav-item'
                const btn = e.target.closest('.nav-item');
                if (!btn) return; // Clicked outside a button

                e.preventDefault();
                const tabName = btn.dataset.tab;

                console.log('Sidebar navigation clicked:', tabName);

                if (tabName) {
                    this.switchTab(tabName);
                }
            });
        } else {
            console.error('Sidebar navigation container (.sidebar-nav) not found!');
        }

        // Close modal on outside click
        window.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                e.target.style.display = 'none';
            }
        });

        window.addEventListener('focus', () => {
            this.updateConnectionStatus();
        });

        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.updateConnectionStatus();
            }
        });

        window.addEventListener('online', () => {
            this.updateConnectionStatus();
        });

        window.addEventListener('offline', () => {
            const statusBadge = document.getElementById('serverStatusBadge');
            const statusText = document.getElementById('serverStatusText');
            const statusDot = statusBadge?.querySelector('.status-dot');
            if (statusDot && statusText) {
                statusDot.className = 'status-dot offline';
                statusText.textContent = 'No Network';
            }
        });
    }

    getCurrentTab() {
        // Returns the data-tab of the element with 'active' class, defaults to dashboard
        const activeBtn = document.querySelector('.nav-item.active');
        return activeBtn ? activeBtn.dataset.tab : 'dashboard';
    }

    switchTab(tabName) {
        if (!tabName) return;

        console.log('Switching to tab:', tabName);

        // 1. Update Navigation Buttons
        const navItems = document.querySelectorAll('.nav-item');
        navItems.forEach(btn => {
            if (btn.dataset.tab === tabName) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // 2. Update Tab Content Visibility
        const tabContents = document.querySelectorAll('.tab-content');
        let contentFound = false;

        tabContents.forEach(content => {
            if (content.id === tabName) {
                content.classList.add('active');
                contentFound = true;
            } else {
                content.classList.remove('active');
            }
        });

        if (!contentFound) {
            console.warn(`No content container found for tab: #${tabName}`);
        }

        // 3. Load Data for the tab
        this.loadTabData(tabName);
    }

    async loadTabData(tabName) {
        switch (tabName) {
            case 'dashboard':
                await this.loadServerStatus();
                break;
            case 'devices':
                await this.loadDevices();
                break;
            case 'pairing':
                await this.loadPairingInfo();
                break;
            case 'settings':
                await this.loadSettings();
                break;
            case 'logs':
                await this.loadLogs();
                break;
        }
    }

    // ... Rest of the helper methods (API calls, status updates, etc.) remain the same ...
    // Copying them here to ensure the file is complete

    async loadApiKey() {
        try {
            const response = await fetch('/qr-payload');
            if (response.ok) {
                const data = await response.json();
                this.apiKey = data.apiKey;
            }
        } catch (error) {
            console.warn('Could not load API key:', error);
        }
    }

    getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        if (this.apiKey) headers['X-API-Key'] = this.apiKey;
        return headers;
    }

    getWebHeaders() {
        return { 'Content-Type': 'application/json' };
    }

    async webUICall(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, {
                ...options,
                headers: { ...this.getWebHeaders(), ...options.headers },
                credentials: 'include'
            });
            return response;
        } catch (error) {
            console.error(`Web UI API call failed: ${endpoint}`, error);
            throw error;
        }
    }

    async apiCall(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, {
                ...options,
                headers: { ...this.getHeaders(), ...options.headers }
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error(`API call failed for ${endpoint}:`, error);
            throw error;
        }
    }

    updateConnectionStatus() {
        const statusBadge = document.getElementById('serverStatusBadge');
        const statusText = document.getElementById('serverStatusText');
        const statusDot = statusBadge?.querySelector('.status-dot');

        if (!statusBadge || !statusText || !statusDot) return;

        const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 5000));
        const fetchPromise = fetch('/status', { method: 'GET', cache: 'no-cache' });

        Promise.race([fetchPromise, timeoutPromise])
            .then(response => {
                if (response && response.ok) {
                    statusDot.className = 'status-dot online';
                    statusText.textContent = 'Online';
                } else {
                    throw new Error('Server error');
                }
            })
            .catch(error => {
                statusDot.className = 'status-dot offline';
                statusText.textContent = 'Offline';
            });
    }

    async loadServerStatus() {
        await this.loadNetworkInfo();
        await this.updateServerStatus();
        this.updateActivity();
    }

    updateActivity() {
        const uptimeElement = document.getElementById('serverUptime');
        if (uptimeElement) {
            const uptime = this.formatUptime(Date.now() - this.serverStartTime);
            uptimeElement.textContent = uptime;
        }
    }

    async loadNetworkInfo() {
        try {
            const data = await this.apiCall('/qr-payload');
            this.displayNetworkInfo(data);
        } catch (error) {
            const basicInfo = {
                ip: window.location.hostname,
                port: window.location.port || '38080',
                protocol: window.location.protocol.replace(':', '')
            };
            this.displayNetworkInfo(basicInfo);
        }
    }

    async loadPairingInfo() { }

    formatUptime(milliseconds) {
        const seconds = Math.floor(milliseconds / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (days > 0) return `${days}d ${hours % 24}h`;
        if (hours > 0) return `${hours}h ${minutes % 60}m`;
        if (minutes > 0) return `${minutes}m`;
        return 'Just now';
    }

    formatTime(timestamp) {
        const now = Date.now();
        const diff = now - timestamp;
        const minutes = Math.floor(diff / 60000);
        if (minutes < 1) return 'Just now';
        return `${minutes}m ago`;
    }


    displayNetworkInfo(data) {
        const hostIPElement = document.getElementById('hostIP');
        if (hostIPElement) hostIPElement.textContent = data.ip || window.location.hostname;
    }

    async updateServerStatus() {
        const portElement = document.getElementById('serverPort');
        const versionElement = document.getElementById('serverVersion');
        if (portElement) portElement.textContent = window.location.port || '38080';

        try {
            const response = await fetch('/status');
            if (response.ok) {
                const data = await response.json();
                if (versionElement && data.version) versionElement.textContent = data.version;
                this.updateConnectionStatusFromServerState(data);
            }
        } catch (e) { }
    }


    updateConnectionStatusFromServerState(serverData) {
        const statusBadge = document.getElementById('serverStatusBadge');
        const statusText = document.getElementById('serverStatusText');
        const statusDot = statusBadge?.querySelector('.status-dot');

        if (statusBadge && statusText && statusDot) {
            if (serverData.mobile_api_enabled) {
                statusDot.className = 'status-dot online';
                statusText.textContent = 'Online';
            } else {
                statusDot.className = 'status-dot offline';
                statusText.textContent = 'Offline';
            }
        }
    }

    async loadDevices() {
        try {
            const response = await this.webUICall('/devices');
            if (response.ok) {
                const result = await response.json();
                this.devices = result.devices || [];
                this.displayDevices();
                this.updateDeviceCount();
            }
        } catch (error) {
            console.error('Failed to load devices:', error);
            const deviceList = document.getElementById('deviceList');
            if (deviceList) deviceList.innerHTML = '<p class="error">Failed to load devices</p>';
        }
    }

    async loadLogs() {
        try {
            const logContainer = document.getElementById('logContainer');
            const isAtBottom = logContainer && (logContainer.scrollHeight - logContainer.scrollTop <= logContainer.clientHeight + 50);

            const response = await this.webUICall('/logs');
            if (response.ok) {
                const data = await response.json();
                const logContent = document.getElementById('logContent');
                if (logContent) {
                    logContent.textContent = data.logs || 'No logs available';

                    // Auto-scroll to bottom if user was already at the bottom
                    if (isAtBottom && logContainer) {
                        logContainer.scrollTop = logContainer.scrollHeight;
                    }
                }
            }
        } catch (error) {
            console.error('Failed to load logs:', error);
            const logContent = document.getElementById('logContent');
            if (logContent) logContent.textContent = 'Failed to load logs';
        }
    }

    displayDevices() {
        const deviceListElement = document.getElementById('deviceList');
        if (this.devices.length === 0) {
            deviceListElement.innerHTML = '<p>No mobile devices connected</p>';
            return;
        }

        deviceListElement.innerHTML = this.devices.map(device => `
            <div class="device-item">
                <div class="device-info">
                    <h4>📱 ${device.name}</h4>
                    <div class="device-meta">
                        <span>IP: ${device.ip}</span> • 
                        <span>Platform: ${device.platform || 'Unknown'}</span> • 
                        <span>Last seen: ${device.last_seen}</span>
                    </div>
                </div>
                <button class="btn btn-sm btn-secondary" onclick="revokeDevice('${device.id}')">Revoke Access</button>
            </div>
        `).join('');
    }

    updateDeviceCount() {
        const deviceCountElement = document.getElementById('deviceCount');
        const dashboardDeviceCountElement = document.getElementById('dashboardDeviceCount');
        if (deviceCountElement) deviceCountElement.textContent = this.devices.length;
        if (dashboardDeviceCountElement) dashboardDeviceCountElement.textContent = this.devices.length;
        this.connectedDevices = this.devices;
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/ui`;

        try {
            this.websocket = new WebSocket(wsUrl);
            this.websocket.onopen = () => this.updateConnectionStatus();
            this.websocket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleWebSocketMessage(data);
                } catch (e) { }
            };
            this.websocket.onclose = () => setTimeout(() => this.connectWebSocket(), 5000);
        } catch (e) { }
    }

    handleWebSocketMessage(data) {
        if (data.type === 'pairing_request') this.handlePairingRequest(data.data);
        else if (data.type === 'notification') this.showNotification(data.data);
        else if (data.type === 'server_status') {
            const isOnline = ['running', 'starting', 'restarting'].includes(data.status);
            this.updateConnectionStatusFromServerState({ mobile_api_enabled: isOnline });
        }
    }

    handlePairingRequest(requestData) {
        this.pendingPairingRequest = requestData;
        const modal = document.getElementById('pairingModal');
        document.getElementById('requestDeviceName').textContent = requestData.device_name || 'Unknown Device';
        document.getElementById('requestDeviceIP').textContent = requestData.ip || 'Unknown';
        document.getElementById('requestDevicePlatform').textContent = requestData.platform || 'Unknown';
        modal.style.display = 'block';

        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('PCLink Pairing Request', { body: 'New device wants to connect' });
        }
    }

    async showNotification(notificationData) {
        // Notification logic here
        this.showToast(notificationData.title, notificationData.message || notificationData.body);
    }

    showToast(title, message, type = 'info', duration = 4000) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        const iconMap = {
            'success': 'check-circle',
            'error': 'alert-circle',
            'info': 'info'
        };

        toast.innerHTML = `
            <i data-feather="${iconMap[type] || 'info'}" class="toast-icon"></i>
            <div class="toast-message"><strong>${title}</strong><br>${message}</div>
            <button class="toast-close" onclick="this.parentElement.classList.add('hiding'); setTimeout(() => this.parentElement.remove(), 300);">×</button>
        `;

        document.body.appendChild(toast);

        // Replace feather icons
        if (window.feather) feather.replace();

        setTimeout(() => {
            toast.classList.add('hiding');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    loadNotificationSettings() {
        const saved = localStorage.getItem('pclink_notifications');
        return saved ? JSON.parse(saved) : { deviceConnect: true, deviceDisconnect: true, pairingRequest: true, updates: true };
    }

    saveNotificationSettings() {
        localStorage.setItem('pclink_notifications', JSON.stringify(this.notificationSettings));
    }

    async loadSettings() {
        try {
            const response = await fetch('/settings/load', { headers: this.getHeaders() });
            if (response.ok) {
                const settings = await response.json();
                const portInput = document.getElementById('serverPortInput');
                if (portInput) portInput.value = window.location.port || '38080';

                const autoStart = document.getElementById('autoStartCheckbox');
                if (autoStart) autoStart.checked = settings.auto_start || false;

                const allowTerminal = document.getElementById('allowTerminalAccess');
                if (allowTerminal) {
                    allowTerminal.checked = settings.allow_terminal_access !== false; // Default to true
                }
                const autoOpen = document.getElementById('autoOpenWebUI');
                if (autoOpen) autoOpen.checked = settings.auto_open_webui !== false;

                await this.loadTransferSettings();
            }
        } catch (e) {
            // If settings fail to load, keep logs visible by default
        }
    }

    updateTerminalVisibility(isAllowed) {
        const terminalBtn = document.querySelector('.nav-item[data-tab="logs"]');
        if (terminalBtn) terminalBtn.style.display = isAllowed ? '' : 'none';
    }

    async loadTransferSettings() {
        try {
            const response = await fetch('/transfers/cleanup/status');
            if (response.ok) {
                const data = await response.json();
                const thresholdInput = document.getElementById('cleanupThresholdInput');
                if (thresholdInput) thresholdInput.value = data.threshold_days;

                const statusText = document.getElementById('cleanupStatusText');
                if (statusText) {
                    statusText.innerHTML = `Found <strong>${data.total_stale}</strong> stale items (${data.stale_uploads} uploads, ${data.stale_downloads} downloads).`;
                }
            }
        } catch (e) {
            console.error('Failed to load transfer settings:', e);
        }
    }
}

// Global functions for HTML onclick attributes
async function generateQRCode() {
    try {
        const data = await window.pclinkUI.apiCall('/qr-payload');
        const container = document.getElementById('qrCodeDisplay');
        const qrData = JSON.stringify(data);

        container.innerHTML = `<div id="qrCodeContainer" style="padding: 15px; background: white; border-radius: 8px; display: inline-block;"></div>`;

        if (typeof QRCode !== 'undefined') {
            new QRCode(document.getElementById('qrCodeContainer'), {
                text: qrData,
                width: 256,
                height: 256
            });
        }
    } catch (e) {
        console.error('QR Gen Error', e);
    }
}

async function regenerateQRCode() {
    generateQRCode();
}

function refreshDevices() { window.pclinkUI.loadDevices(); }
function refreshLogs() { window.pclinkUI.loadLogs(); }
function toggleAutoRefresh() {
    window.pclinkUI.autoRefreshEnabled = !window.pclinkUI.autoRefreshEnabled;
    const btn = document.getElementById('autoRefreshToggle');
    if (btn) {
        const statusText = window.pclinkUI.autoRefreshEnabled ? 'ON' : 'OFF';
        const iconName = window.pclinkUI.autoRefreshEnabled ? 'pause' : 'play';
        btn.innerHTML = `<i data-feather="${iconName}"></i> Auto-refresh: ${statusText}`;
        if (window.feather) feather.replace();
    }
}

async function saveSettings() {
    // Basic save settings implementation
    const autoStart = document.getElementById('autoStartCheckbox').checked;
    const allowTerminal = document.getElementById('allowTerminalAccess').checked;
    const autoOpen = document.getElementById('autoOpenWebUI').checked;

    try {
        await window.pclinkUI.webUICall('/settings/save', {
            method: 'POST',
            body: JSON.stringify({
                auto_start: autoStart,
                allow_terminal_access: allowTerminal,
                auto_open_webui: autoOpen
            })
        });
        window.pclinkUI.showToast('Success', 'Settings saved');
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to save settings', 'error');
    }
}

async function saveTransferSettings() {
    const threshold = parseInt(document.getElementById('cleanupThresholdInput').value);
    if (isNaN(threshold) || threshold < 0) {
        window.pclinkUI.showToast('Error', 'Invalid threshold value', 'error');
        return;
    }

    try {
        const response = await fetch('/transfers/cleanup/config', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ threshold: threshold })
        });
        if (response.ok) {
            window.pclinkUI.showToast('Success', 'Cleanup threshold updated');
            window.pclinkUI.loadTransferSettings();
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to save transfer settings', 'error');
    }
}

async function executeCleanup() {
    try {
        const response = await fetch('/transfers/cleanup/execute', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            const total = data.cleaned.uploads + data.cleaned.downloads;
            window.pclinkUI.showToast('Success', `Cleaned up ${total} stale items`, 'success');
            window.pclinkUI.loadTransferSettings();
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to execute cleanup', 'error');
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    window.pclinkUI = new PCLinkWebUI();
});

// Helper for Copy
window.copyCommand = async function (element) {
    const code = element.querySelector('code');
    if (code) {
        try {
            await navigator.clipboard.writeText(code.textContent);
            element.classList.add('copied');
            setTimeout(() => element.classList.remove('copied'), 1000);
        } catch (e) { }
    }
};

// Global Server Control Stubs
window.startRemoteServer = async () => {
    try {
        const response = await fetch('/server/start', { method: 'POST' });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(errorData.detail || 'Failed to start server');
        }
        window.pclinkUI.showToast('Success', 'Server starting...', 'success');
        setTimeout(() => window.pclinkUI.updateConnectionStatus(), 1000);
    } catch (e) {
        console.error('Start server error:', e);
        window.pclinkUI.showToast('Error', e.message || 'Failed to start', 'error');
    }
};

window.stopRemoteServer = async () => {
    try {
        const response = await fetch('/server/stop', { method: 'POST' });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(errorData.detail || 'Failed to stop server');
        }
        window.pclinkUI.showToast('Success', 'Server stopping...', 'success');
        setTimeout(() => window.pclinkUI.updateConnectionStatus(), 1000);
    } catch (e) {
        console.error('Stop server error:', e);
        window.pclinkUI.showToast('Error', e.message || 'Failed to stop', 'error');
    }
};

window.restartRemoteServer = async () => {
    try {
        const response = await fetch('/server/restart', { method: 'POST' });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(errorData.detail || 'Failed to restart server');
        }
        window.pclinkUI.showToast('Success', 'Server restarting...', 'success');
        setTimeout(() => window.pclinkUI.updateConnectionStatus(), 3000);
    } catch (e) {
        console.error('Restart server error:', e);
        window.pclinkUI.showToast('Error', e.message || 'Failed to restart', 'error');
    }
};

window.shutdownServer = async () => {
    if (confirm('Shutdown server?')) {
        try {
            await fetch('/server/shutdown', { method: 'POST' });
            document.body.innerHTML = '<h1 style="color:white;text-align:center;margin-top:20%">Server Shutdown</h1>';
        } catch (e) { }
    }
};

window.logout = async () => {
    if (confirm('Logout?')) {
        await fetch('/auth/logout', { method: 'POST' });
        window.location.reload();
    }
};

// Additional global helper functions
window.revokeDevice = async (deviceId) => {
    if (confirm('Revoke access for this device?')) {
        try {
            await window.pclinkUI.webUICall(`/devices/revoke?device_id=${deviceId}`, { method: 'POST' });
            window.pclinkUI.loadDevices();
            window.pclinkUI.showToast('Success', 'Device access revoked');
        } catch (e) {
            window.pclinkUI.showToast('Error', 'Failed to revoke device access');
        }
    }
};

window.regenerateApiKey = async () => {
    if (confirm('Regenerate API key? All existing clients will be disconnected.')) {
        try {
            await window.pclinkUI.webUICall('/auth/regenerate-key', { method: 'POST' });
            window.location.reload();
        } catch (e) {
            window.pclinkUI.showToast('Error', 'Failed to regenerate API key');
        }
    }
};

window.checkForUpdates = async () => {
    try {
        const response = await fetch('/updates/check');
        if (response.ok) {
            const data = await response.json();
            if (data.update_available) {
                const banner = document.getElementById('updateBanner');
                if (banner) {
                    banner.style.display = 'block';
                    document.getElementById('updateVersion').textContent = `Version ${data.latest_version} is now available`;
                }
            }
        }
    } catch (e) {
        console.log('Update check failed:', e);
    }
};

window.dismissUpdate = () => {
    const banner = document.getElementById('updateBanner');
    if (banner) banner.style.display = 'none';
    localStorage.setItem('updateDismissed', Date.now().toString());
};

window.downloadUpdate = () => {
    if (window.updateData?.download_url) {
        window.open(window.updateData.download_url, '_blank');
        dismissUpdate();
    }
};

window.toggleReleaseNotes = () => {
    const notes = document.getElementById('updateReleaseNotes');
    if (notes) notes.style.display = notes.style.display === 'none' ? 'block' : 'none';
};

window.loadNotificationSettings = () => {
    const settings = window.pclinkUI?.notificationSettings || {};
    const setChecked = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.checked = val;
    };
    setChecked('notifyDeviceConnect', settings.deviceConnect);
    setChecked('notifyDeviceDisconnect', settings.deviceDisconnect);
    setChecked('notifyPairingRequest', settings.pairingRequest);
    setChecked('notifyUpdates', settings.updates);
};

window.approvePairing = async () => {
    if (!window.pclinkUI?.pendingPairingRequest) return;
    try {
        await fetch('/pairing/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id,
                approved: true
            })
        });
        document.getElementById('pairingModal').style.display = 'none';
        window.pclinkUI.loadDevices();
        window.pclinkUI.showToast('Success', 'Device paired successfully');
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to approve pairing');
    }
};

window.denyPairing = async () => {
    if (!window.pclinkUI?.pendingPairingRequest) return;
    try {
        await fetch('/pairing/deny', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id,
                approved: false
            })
        });
        document.getElementById('pairingModal').style.display = 'none';
        window.pclinkUI.showToast('Info', 'Pairing request denied');
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to deny pairing');
    }
};

window.clearLogs = async () => {
    if (confirm('Clear all logs?')) {
        try {
            await fetch('/logs/clear', { method: 'POST' });
            document.getElementById('logContent').textContent = 'Logs cleared';
            window.pclinkUI.showToast('Success', 'Logs cleared');
        } catch (e) {
            window.pclinkUI.showToast('Error', 'Failed to clear logs');
        }
    }
};