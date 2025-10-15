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
        this.setupEventListeners();
        await this.loadApiKey();
        this.updateConnectionStatus();
        this.loadServerStatus();
        this.connectWebSocket();


        setInterval(() => {
            if (!this.autoRefreshEnabled) return;

            // Always check connection status
            this.updateConnectionStatus();

            const currentTab = this.getCurrentTab();
            if (currentTab === 'dashboard') {
                this.updateActivity();
                this.updateServerStatus();
            } else if (currentTab === 'devices') {
                this.loadDevices();
            } else if (currentTab === 'logs') {
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
        setTimeout(() => loadNotificationSettings(), 1000);
    }

    setupEventListeners() {
        console.log('Setting up event listeners...');


        const tabButtons = document.querySelectorAll('.tab-btn, .nav-btn');
        console.log('Found tab buttons:', tabButtons.length);

        tabButtons.forEach((btn, index) => {
            console.log(`Setting up listener for button ${index}:`, btn.dataset.tab);
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();


                const button = e.currentTarget;
                const tabName = button.dataset.tab;

                console.log('Button clicked:', tabName);

                if (tabName) {
                    this.switchTab(tabName);
                } else {
                    console.error('No tab name found for button:', button);
                }
            });
        });

        window.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                e.target.style.display = 'none';
            }
        });


        window.addEventListener('focus', () => {
            console.log('Window gained focus, checking connection status...');
            this.updateConnectionStatus();
        });


        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                console.log('Page became visible, checking connection status...');
                this.updateConnectionStatus();
            }
        });

        // Listen for online/offline events
        window.addEventListener('online', () => {
            console.log('Network came online, checking server status...');
            this.updateConnectionStatus();
        });

        window.addEventListener('offline', () => {
            console.log('Network went offline');
            const statusElement = document.getElementById('connectionStatus');
            if (statusElement) {
                const statusPulse = statusElement.querySelector('.status-pulse');
                const statusValue = statusElement.querySelector('.connection-value');
                if (statusPulse && statusValue) {
                    statusElement.className = 'connection-status offline';
                    statusPulse.className = 'status-pulse offline';
                    statusValue.textContent = 'No Network';
                }
            }
        });
    }

    async loadApiKey() {
        try {
            const response = await fetch('/qr-payload');
            if (response.ok) {
                const data = await response.json();
                this.apiKey = data.apiKey;
                console.log('API key loaded successfully');
            } else {
                console.warn('Could not load API key, status:', response.status);
            }
        } catch (error) {
            console.warn('Could not load API key:', error);
        }
    }

    getHeaders() {
        const headers = {
            'Content-Type': 'application/json'
        };
        if (this.apiKey) {
            headers['X-API-Key'] = this.apiKey;
        }
        return headers;
    }

    getWebHeaders() {
        return {
            'Content-Type': 'application/json'
        };
    }

    async webUICall(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, {
                ...options,
                headers: {
                    ...this.getWebHeaders(),
                    ...options.headers
                },
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
                headers: {
                    ...this.getHeaders(),
                    ...options.headers
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API call failed for ${endpoint}:`, error);
            throw error;
        }
    }

    updateConnectionStatus() {
        const statusElement = document.getElementById('connectionStatus');
        if (!statusElement) {
            console.warn('Status element not found');
            return;
        }

        const statusPulse = statusElement.querySelector('.status-pulse');
        const statusValue = statusElement.querySelector('.connection-value');

        if (!statusPulse || !statusValue) {
            console.warn('Status components not found');
            return;
        }

        // Set connecting state
        statusElement.className = 'connection-status connecting';
        statusPulse.className = 'status-pulse connecting';
        statusValue.textContent = 'Checking...';

        // Create a timeout promise to detect server unavailability
        const timeoutPromise = new Promise((_, reject) => {
            setTimeout(() => reject(new Error('Connection timeout')), 5000);
        });

        // Create the fetch promise with no-cache headers
        const fetchPromise = fetch('/status', {
            method: 'GET',
            cache: 'no-cache',
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        });

        // Race between fetch and timeout
        Promise.race([fetchPromise, timeoutPromise])
            .then(response => {
                if (response && response.ok) {
                    statusElement.className = 'connection-status online';
                    statusPulse.className = 'status-pulse online';
                    statusValue.textContent = 'Online';
                    console.log('Server status: Online');
                } else {
                    throw new Error(`Server responded with status: ${response?.status || 'unknown'}`);
                }
            })
            .catch(error => {
                console.warn('Server status check failed:', error.message);
                statusElement.className = 'connection-status offline';
                statusPulse.className = 'status-pulse offline';
                statusValue.textContent = 'Offline';
            });
    }

    getCurrentTab() {
        const activeBtn = document.querySelector('.tab-btn.active, .nav-btn.active');
        return activeBtn ? activeBtn.dataset.tab : 'dashboard';
    }

    switchTab(tabName) {
        if (!tabName) {
            console.error('switchTab called with no tabName');
            return;
        }

        console.log('Switching to tab:', tabName);

        // Remove active class from all tab buttons
        document.querySelectorAll('.tab-btn, .nav-btn').forEach(btn => {
            btn.classList.remove('active');
        });

        // Add active class to the clicked tab
        const targetBtn = document.querySelector(`[data-tab="${tabName}"]`);
        if (targetBtn) {
            targetBtn.classList.add('active');
            console.log('Activated button for tab:', tabName);
        } else {
            console.error('Could not find button for tab:', tabName);
        }

        // Hide all tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });

        // Show the target tab content
        const targetContent = document.getElementById(tabName);
        if (targetContent) {
            targetContent.classList.add('active');
            console.log('Activated content for tab:', tabName);
        } else {
            console.error('Could not find content for tab:', tabName);
        }

        // Load tab-specific data
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
            case 'about':
                // Icons are already rendered, no need to replace
                break;
        }
    }

    async loadServerStatus() {
        await this.loadNetworkInfo();
        this.updateServerStatus();
        this.updateActivity();
    }

    updateActivity() {
        const uptimeElement = document.getElementById('serverUptime');
        if (uptimeElement) {
            const uptime = this.formatUptime(Date.now() - this.serverStartTime);
            uptimeElement.textContent = uptime;
        }

        const deviceCount = this.connectedDevices.length;
        const noActivity = document.getElementById('noActivity');
        const lastActivity = document.getElementById('lastDeviceActivity');

        if (deviceCount > 0 || this.lastDeviceActivity) {
            if (noActivity) noActivity.style.display = 'none';
            if (lastActivity) {
                lastActivity.style.display = 'flex';
                if (this.lastDeviceActivity) {
                    document.getElementById('lastActivityText').textContent = this.lastDeviceActivity.text;
                    document.getElementById('lastActivityTime').textContent = this.formatTime(this.lastDeviceActivity.time);
                }
            }
        } else {
            if (noActivity) noActivity.style.display = 'flex';
            if (lastActivity) lastActivity.style.display = 'none';
        }
    }

    async loadNetworkInfo() {
        try {
            const data = await this.apiCall('/qr-payload');
            this.displayNetworkInfo(data);
        } catch (error) {
            console.error('Network info error:', error);
            const basicInfo = {
                ip: window.location.hostname,
                port: window.location.port || '8000',
                protocol: window.location.protocol.replace(':', '')
            };
            this.displayNetworkInfo(basicInfo);
        }
    }

    async loadPairingInfo() {
        // This tab is mostly static instructions
    }

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
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (days > 0) return `${days}d ago`;
        if (hours > 0) return `${hours}h ago`;
        if (minutes > 0) return `${minutes}m ago`;
        return 'Just now';
    }

    displayNetworkInfo(data) {
        const hostIPElement = document.getElementById('hostIP');
        const sslStatusElement = document.getElementById('sslStatus');

        if (hostIPElement) {
            hostIPElement.textContent = data.ip || window.location.hostname;
        }
        if (sslStatusElement) {
            const hasSSL = data.certFingerprint || window.location.protocol === 'https:';
            sslStatusElement.textContent = hasSSL ? 'Valid' : 'Not configured';
            sslStatusElement.className = hasSSL ? 'status-online' : 'status-offline';
        }
    }

    async updateServerStatus() {
        const portElement = document.getElementById('serverPort');
        const versionElement = document.getElementById('serverVersion');

        if (portElement) portElement.textContent = window.location.port || '8000';
        if (versionElement) versionElement.textContent = '2.0.0';

        try {
            const response = await fetch('/status');
            if (response.ok) {
                const data = await response.json();
                this.updateConnectionStatusFromServerState(data);
            } else {
                this.updateConnectionStatus();
            }
        } catch (error) {
            console.warn('Status check failed:', error);
            this.updateConnectionStatus();
        }
    }

    updateConnectionStatusFromServerState(serverData) {
        // Update single status indicator
        const statusElement = document.getElementById('connectionStatus');
        const statusDot = statusElement.querySelector('.status-dot');
        const statusText = statusElement.querySelector('span:last-child');

        if (serverData.mobile_api_enabled) {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Online';
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = 'Offline';
        }
    }

    async loadDevices() {
        try {
            const data = await fetch('/devices');
            if (data.ok) {
                const result = await data.json();
                this.devices = result.devices || [];
                this.displayDevices();
                this.updateDeviceCount();
            } else {
                throw new Error('Failed to fetch devices');
            }
        } catch (error) {
            console.error('Device loading error:', error);
            document.getElementById('deviceList').innerHTML = '<p class="error">Failed to load devices</p>';
        }
    }

    async loadLogs() {
        try {
            const response = await fetch('/logs');
            if (response.ok) {
                const data = await response.json();
                document.getElementById('logContent').textContent = data.logs || 'No logs available';
            } else {
                throw new Error('Failed to fetch logs');
            }
        } catch (error) {
            console.error('Log loading error:', error);
            document.getElementById('logContent').textContent = 'Failed to load logs';
        }
    }

    displayDevices() {
        const deviceListElement = document.getElementById('deviceList');

        if (this.devices.length === 0) {
            deviceListElement.innerHTML = '<p>No mobile devices connected</p>';
            return;
        }

        const devicesHtml = this.devices.map(device => `
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

        deviceListElement.innerHTML = devicesHtml;
    }

    updateDeviceCount() {
        const deviceCountElement = document.getElementById('deviceCount');
        const dashboardDeviceCountElement = document.getElementById('dashboardDeviceCount');

        if (deviceCountElement) {
            deviceCountElement.textContent = this.devices.length;
        }
        if (dashboardDeviceCountElement) {
            dashboardDeviceCountElement.textContent = this.devices.length;
        }

        this.connectedDevices = this.devices;
    }

    connectWebSocket() {
        if (!this.apiKey) {
            console.warn('No API key available for WebSocket connection');
            return;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws?token=${this.apiKey}`;

        try {
            this.websocket = new WebSocket(wsUrl);

            this.websocket.onopen = () => {
                console.log('WebSocket connected');
                // WebSocket connection indicates server is online
                this.updateConnectionStatus();
            };

            this.websocket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleWebSocketMessage(data);
                } catch (error) {
                    console.error('WebSocket message parse error:', error);
                }
            };

            this.websocket.onclose = (event) => {
                console.log('WebSocket disconnected, code:', event.code, 'reason:', event.reason);

                // Update connection status to offline when WebSocket closes
                const statusElement = document.getElementById('connectionStatus');
                if (statusElement) {
                    const statusPulse = statusElement.querySelector('.status-pulse');
                    const statusValue = statusElement.querySelector('.connection-value');
                    if (statusPulse && statusValue) {
                        statusElement.className = 'connection-status offline';
                        statusPulse.className = 'status-pulse offline';
                        statusValue.textContent = 'Disconnected';
                    }
                }

                // Try to reconnect after 5 seconds
                setTimeout(() => this.connectWebSocket(), 5000);
            };

            this.websocket.onerror = (error) => {
                console.error('WebSocket error:', error);
                // Update connection status on WebSocket error
                this.updateConnectionStatus();
            };
        } catch (error) {
            console.error('WebSocket connection failed:', error);
        }
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'pairing_request':
                this.handlePairingRequest(data.data);
                break;
            case 'update':
                console.log('Update received:', data.data);
                break;
            case 'notification':
                this.showNotification(data.data);
                break;
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
            new Notification('PCLink Pairing Request', {
                body: `${requestData.device_name} wants to connect`,
                icon: '/ui/static/icon.png'
            });
        }
    }

    async showNotification(notificationData) {
        console.log('Notification:', notificationData);

        if (notificationData.title && (notificationData.title.includes('Connected') || notificationData.title.includes('Disconnected'))) {
            this.lastDeviceActivity = {
                text: notificationData.message || notificationData.title,
                time: Date.now()
            };
            this.updateActivity();
        }

        const type = notificationData.type || 'general';
        if (!this.isNotificationEnabled(type)) {
            return;
        }

        try {
            await fetch('/notifications/show', {
                method: 'POST',
                headers: this.getHeaders(),
                body: JSON.stringify({
                    title: notificationData.title || 'PCLink',
                    message: notificationData.message || notificationData.body || ''
                })
            });
        } catch (error) {
            console.warn('System notification failed, falling back to toast:', error);
        }

        this.showToast(notificationData.title, notificationData.message, type);
    }

    showToast(title, message, type = 'info', duration = 4000) {
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;


        const iconSymbol = type === 'success' ? '✅' :
            type === 'error' ? '❌' :
                type === 'warning' ? '⚠️' : 'ℹ️';

        toast.innerHTML = `
            <div class="toast-icon">
                <span class="toast-symbol">${iconSymbol}</span>
            </div>
            <div class="toast-content">
                <strong>${title}</strong>
                <p>${message}</p>
            </div>
            <button class="toast-close" onclick="window.pclinkUI.removeToast(this.parentElement)">
                <span class="close-symbol">×</span>
            </button>
        `;

        container.appendChild(toast);


        const autoRemoveTimer = setTimeout(() => {
            this.removeToast(toast);
        }, duration);

        toast.autoRemoveTimer = autoRemoveTimer;

        return toast;
    }

    removeToast(toast) {
        if (toast && toast.parentElement) {
            if (toast.autoRemoveTimer) {
                clearTimeout(toast.autoRemoveTimer);
            }

            toast.style.animation = 'slideOutRight 0.3s ease-out';
            setTimeout(() => {
                if (toast.parentElement) {
                    toast.remove();
                }
            }, 300);
        }
    }

    loadNotificationSettings() {
        const saved = localStorage.getItem('pclink_notifications');
        return saved ? JSON.parse(saved) : {
            deviceConnect: true,
            deviceDisconnect: true,
            pairingRequest: true,
            updates: true
        };
    }

    saveNotificationSettings() {
        localStorage.setItem('pclink_notifications', JSON.stringify(this.notificationSettings));
    }

    isNotificationEnabled(type) {
        const typeMap = {
            'device_connected': 'deviceConnect',
            'device_disconnected': 'deviceDisconnect',
            'pairing_request': 'pairingRequest',
            'update_available': 'updates'
        };

        const settingKey = typeMap[type] || type;
        return this.notificationSettings[settingKey] !== false;
    }

    async loadSettings() {
        try {
            const response = await fetch('/settings/load', {
                headers: this.getHeaders()
            });

            if (response.ok) {
                const settings = await response.json();

                const serverPortInput = document.getElementById('serverPortInput');
                const autoStartCheckbox = document.getElementById('autoStartCheckbox');
                const allowInsecureShell = document.getElementById('allowInsecureShell');
                const autoOpenWebUI = document.getElementById('autoOpenWebUI');

                if (serverPortInput) serverPortInput.value = window.location.port || '8000';
                if (autoStartCheckbox) autoStartCheckbox.checked = settings.auto_start || false;
                if (allowInsecureShell) allowInsecureShell.checked = settings.allow_insecure_shell || false;
                if (autoOpenWebUI) autoOpenWebUI.checked = settings.auto_open_webui !== false;
            }
        } catch (error) {
            console.error('Failed to load settings:', error);
            const serverPortInput = document.getElementById('serverPortInput');
            if (serverPortInput) serverPortInput.value = window.location.port || '8000';
        }
    }

    formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    async showQRCode() {
        try {
            const data = await this.apiCall('/qr-payload');
            const modal = document.getElementById('qrModal');
            const container = document.getElementById('qrCodeContainer');

            const qrData = JSON.stringify(data);
            container.innerHTML = `
                <div style="padding: 20px; background: white; border-radius: 8px; display: inline-block;">
                    <p style="color: black; font-family: monospace; font-size: 12px; word-break: break-all;">${qrData}</p>
                </div>
            `;

            modal.style.display = 'block';
        } catch (error) {
            alert('Failed to generate QR code');
        }
    }
}

// Global functions for QR code generation and other utilities
async function generateQRCode() {
    try {
        const data = await window.pclinkUI.apiCall('/qr-payload');
        const container = document.getElementById('qrCodeDisplay');

        const qrData = JSON.stringify(data);
        const canvas = document.createElement('canvas');

        if (typeof QRCode !== 'undefined') {
            await QRCode.toCanvas(canvas, qrData, {
                width: 256,
                margin: 2,
                color: {
                    dark: '#000000',
                    light: '#FFFFFF'
                }
            });

            container.innerHTML = `
                <div style="text-align: center;">
                    <div style="padding: 20px; background: white; border-radius: 8px; display: inline-block; margin-bottom: 15px;">
                        ${canvas.outerHTML}
                    </div>
                    <div style="background: var(--surface-color); padding: 15px; border-radius: 8px; margin-top: 10px;">
                        <h4 style="margin-bottom: 10px; color: var(--text-primary);">Connection Details</h4>
                        <p><strong>Server:</strong> ${data.ip}:${data.port}</p>
                        <p><strong>Protocol:</strong> ${data.protocol}</p>
                        <p><strong>API Key:</strong> ${data.apiKey.substring(0, 8)}...</p>
                        <p><strong>Certificate:</strong> ${data.certFingerprint ? 'Valid' : 'None'}</p>
                    </div>
                </div>
            `;
        } else {
            container.innerHTML = `
                <div style="padding: 20px; background: white; border-radius: 8px; display: inline-block; color: black;">
                    <h4 style="margin-bottom: 10px;">PCLink Connection Info</h4>
                    <p><strong>Server:</strong> ${data.ip}:${data.port}</p>
                    <p><strong>Protocol:</strong> ${data.protocol}</p>
                    <p><strong>API Key:</strong> ${data.apiKey.substring(0, 8)}...</p>
                    <p><strong>Certificate:</strong> ${data.certFingerprint ? 'Valid' : 'None'}</p>
                    <hr style="margin: 10px 0;">
                    <p style="font-size: 10px; font-family: monospace; word-break: break-all;">${qrData}</p>
                </div>
                <p style="margin-top: 10px; color: var(--text-secondary);">
                    QR Code library not loaded. Use the connection details above.
                </p>
            `;
        }
    } catch (error) {
        console.error('QR Code generation error:', error);
        document.getElementById('qrCodeDisplay').innerHTML = '<p class="error">Failed to generate QR code</p>';
    }
}

function refreshDevices() {
    window.pclinkUI.loadDevices();
}

function refreshLogs() {
    window.pclinkUI.loadLogs();
}

function toggleAutoRefresh() {
    window.pclinkUI.autoRefreshEnabled = !window.pclinkUI.autoRefreshEnabled;
    const button = document.getElementById('autoRefreshToggle');
    if (window.pclinkUI.autoRefreshEnabled) {
        button.innerHTML = '<i data-feather="pause"></i> Auto-refresh: ON';
        button.className = 'btn btn-sm';
    } else {
        button.innerHTML = '<i data-feather="play"></i> Auto-refresh: OFF';
        button.className = 'btn btn-sm btn-secondary';
    }
    // Icons are handled automatically, no need to replace
}

async function saveSettings() {
    try {
        const autoStart = document.getElementById('autoStartCheckbox').checked;
        const allowShell = document.getElementById('allowInsecureShell').checked;
        const autoOpenWebUI = document.getElementById('autoOpenWebUI').checked;

        const response = await window.pclinkUI.webUICall('/settings/save', {
            method: 'POST',
            body: JSON.stringify({
                auto_start: autoStart,
                allow_insecure_shell: allowShell,
                auto_open_webui: autoOpenWebUI
            })
        });

        if (response.ok) {
            window.pclinkUI.showToast('Settings Saved', 'Server settings updated successfully', 'success');
        } else {
            window.pclinkUI.showToast('Save Failed', 'Failed to save server settings', 'error');
        }
    } catch (error) {
        console.error('Settings save error:', error);
        window.pclinkUI.showToast('Save Failed', 'Failed to save server settings', 'error');
    }
}

function saveNotificationSettings() {
    const settings = {
        deviceConnect: document.getElementById('notifyDeviceConnect').checked,
        deviceDisconnect: document.getElementById('notifyDeviceDisconnect').checked,
        pairingRequest: document.getElementById('notifyPairingRequest').checked,
        updates: document.getElementById('notifyUpdates').checked
    };

    window.pclinkUI.notificationSettings = settings;
    window.pclinkUI.saveNotificationSettings();
    window.pclinkUI.showToast('Settings Saved', 'Notification preferences updated successfully', 'success');
}

function loadNotificationSettings() {
    const settings = window.pclinkUI.notificationSettings;
    document.getElementById('notifyDeviceConnect').checked = settings.deviceConnect;
    document.getElementById('notifyDeviceDisconnect').checked = settings.deviceDisconnect;
    document.getElementById('notifyPairingRequest').checked = settings.pairingRequest;
    document.getElementById('notifyUpdates').checked = settings.updates;
}

async function clearLogs() {
    if (confirm('Clear all logs?')) {
        try {
            const response = await fetch('/logs/clear', { method: 'POST' });
            if (response.ok) {
                document.getElementById('logContent').textContent = 'Logs cleared';
            } else {
                alert('Failed to clear logs');
            }
        } catch (error) {
            console.error('Clear logs error:', error);
            alert('Failed to clear logs');
        }
    }
}

async function revokeDevice(deviceId) {
    if (confirm('Revoke access for this device? It will need to be paired again.')) {
        try {
            alert('Device access revoked');
            window.pclinkUI.loadDevices();
        } catch (error) {
            alert('Failed to revoke device access');
        }
    }
}

async function regenerateApiKey() {
    if (confirm('Regenerate API key? All devices will need to be re-paired.')) {
        try {
            alert('API key regenerated - all devices must be re-paired');
        } catch (error) {
            alert('Failed to regenerate API key');
        }
    }
}

async function approvePairing() {
    if (!window.pclinkUI.pendingPairingRequest) {
        alert('No pending pairing request');
        return;
    }

    try {
        const response = await fetch('/pairing/approve', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': window.pclinkUI.apiKey
            },
            body: JSON.stringify({
                pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id,
                approved: true
            })
        });

        if (response.ok) {
            document.getElementById('pairingModal').style.display = 'none';
            alert('Device pairing approved');
            window.pclinkUI.loadDevices();
        } else {
            alert('Failed to approve pairing');
        }
    } catch (error) {
        console.error('Pairing approval error:', error);
        alert('Failed to approve pairing');
    }

    window.pclinkUI.pendingPairingRequest = null;
}

async function denyPairing() {
    if (!window.pclinkUI.pendingPairingRequest) {
        alert('No pending pairing request');
        return;
    }

    try {
        const response = await fetch('/pairing/deny', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': window.pclinkUI.apiKey
            },
            body: JSON.stringify({
                pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id,
                approved: false
            })
        });

        if (response.ok) {
            document.getElementById('pairingModal').style.display = 'none';
            alert('Device pairing denied');
        } else {
            alert('Failed to deny pairing');
        }
    } catch (error) {
        console.error('Pairing denial error:', error);
        alert('Failed to deny pairing');
    }

    window.pclinkUI.pendingPairingRequest = null;
}

async function removeAllDevices() {
    if (confirm('Are you sure you want to remove ALL connected devices? This will revoke access for all paired mobile devices.')) {
        try {
            const response = await window.pclinkUI.webUICall('/devices/remove-all', {
                method: 'POST'
            });

            if (response.ok) {
                alert('All devices removed successfully');
                window.pclinkUI.loadDevices();
            } else {
                alert('Failed to remove devices');
            }
        } catch (error) {
            console.error('Remove all devices error:', error);
            alert('Failed to remove devices');
        }
    }
}

async function checkForUpdates() {
    try {
        const response = await fetch('/updates/check');
        if (response.ok) {
            const data = await response.json();
            if (data.update_available) {
                showUpdateBanner(data);
            }
        }
    } catch (error) {
        console.error('Update check failed:', error);
    }
}

function showUpdateBanner(updateData) {
    const banner = document.getElementById('updateBanner');
    const versionSpan = document.getElementById('updateVersion');
    if (banner && versionSpan) {
        versionSpan.textContent = `Version ${updateData.latest_version} is now available`;
        banner.style.display = 'block';
        window.updateData = updateData;
    }
}

function downloadUpdate() {
    if (window.updateData && window.updateData.download_url) {
        window.open(window.updateData.download_url, '_blank');
        dismissUpdate();
    }
}

function dismissUpdate() {
    const banner = document.getElementById('updateBanner');
    if (banner) {
        banner.style.display = 'none';
    }
    localStorage.setItem('updateDismissed', Date.now().toString());
}

async function changePassword() {
    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmNewPassword = document.getElementById('confirmNewPassword').value;

    if (!currentPassword || !newPassword || !confirmNewPassword) {
        window.pclinkUI.showToast('Missing Fields', 'Please fill in all password fields', 'warning');
        return;
    }

    if (newPassword.length < 8) {
        window.pclinkUI.showToast('Password Too Short', 'New password must be at least 8 characters', 'error');
        return;
    }

    if (newPassword !== confirmNewPassword) {
        window.pclinkUI.showToast('Passwords Don\'t Match', 'New password and confirmation must match', 'error');
        return;
    }

    try {
        const response = await window.pclinkUI.webUICall('/auth/change-password', {
            method: 'POST',
            body: JSON.stringify({
                old_password: currentPassword,
                new_password: newPassword
            })
        });

        if (response.ok) {
            window.pclinkUI.showToast('Password Changed', 'Password updated successfully. Please login again.', 'success');
            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmNewPassword').value = '';

            setTimeout(() => {
                logout();
            }, 2000);
        } else {
            const data = await response.json();
            window.pclinkUI.showToast('Change Failed', data.detail || 'Failed to change password', 'error');
        }
    } catch (error) {
        console.error('Password change error:', error);
        window.pclinkUI.showToast('Change Failed', 'Failed to change password', 'error');
    }
}

async function logout() {
    if (confirm('Are you sure you want to logout?')) {
        try {
            await fetch('/auth/logout', { method: 'POST' });
            window.location.href = '/ui/';
        } catch (error) {
            console.error('Logout error:', error);
            window.location.href = '/ui/';
        }
    }
}

// Server Control Functions
async function startRemoteServer() {
    const button = document.getElementById('startServerBtn');
    const stopButton = document.getElementById('stopServerBtn');
    const restartButton = document.getElementById('restartServerBtn');

    // Store original button content
    const originalContent = button.innerHTML;

    try {
        // Set loading state without using CSS class that affects icons
        button.innerHTML = '<span style="display: inline-flex; align-items: center; gap: 6px;"><span class="spinner"></span>Starting...</span>';
        button.disabled = true;
        stopButton.disabled = true;
        restartButton.disabled = true;

        const response = await fetch('/server/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        if (response.ok) {
            window.pclinkUI.showToast('Server Started', 'Remote API server started successfully', 'success');
            // Update connection status after a short delay
            setTimeout(() => {
                window.pclinkUI.updateConnectionStatus();
            }, 1000);
        } else {
            const error = await response.text();
            throw new Error(error || 'Failed to start server');
        }
    } catch (error) {
        console.error('Start server failed:', error);
        window.pclinkUI.showToast('Start Failed', `Failed to start remote API server: ${error.message}`, 'error');
    } finally {
        // Restore original content (icons will be restored automatically)
        button.innerHTML = originalContent;
        button.disabled = false;
        stopButton.disabled = false;
        restartButton.disabled = false;
    }
}

async function stopRemoteServer() {
    const button = document.getElementById('stopServerBtn');
    const startButton = document.getElementById('startServerBtn');
    const restartButton = document.getElementById('restartServerBtn');

    // Store original button content
    const originalContent = button.innerHTML;

    try {
        // Set loading state without using CSS class that affects icons
        button.innerHTML = '<span style="display: inline-flex; align-items: center; gap: 6px;"><span class="spinner"></span>Stopping...</span>';
        button.disabled = true;
        startButton.disabled = true;
        restartButton.disabled = true;

        const response = await fetch('/server/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        if (response.ok) {
            window.pclinkUI.showToast('Server Stopped', 'Remote API server stopped successfully', 'success');
            // Update connection status after a short delay
            setTimeout(() => {
                window.pclinkUI.updateConnectionStatus();
            }, 1000);
        } else {
            const error = await response.text();
            throw new Error(error || 'Failed to stop server');
        }
    } catch (error) {
        console.error('Stop server failed:', error);
        window.pclinkUI.showToast('Stop Failed', `Failed to stop remote API server: ${error.message}`, 'error');
    } finally {
        // Restore original content (icons will be restored automatically)
        button.innerHTML = originalContent;
        button.disabled = false;
        startButton.disabled = false;
        restartButton.disabled = false;
    }
}

async function restartRemoteServer() {
    const button = document.getElementById('restartServerBtn');
    const startButton = document.getElementById('startServerBtn');
    const stopButton = document.getElementById('stopServerBtn');

    // Store original button content
    const originalContent = button.innerHTML;

    try {
        // Set loading state without using CSS class that affects icons
        button.innerHTML = '<span style="display: inline-flex; align-items: center; gap: 6px;"><span class="spinner"></span>Restarting...</span>';
        button.disabled = true;
        startButton.disabled = true;
        stopButton.disabled = true;

        const response = await fetch('/server/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        if (response.ok) {
            window.pclinkUI.showToast('Server Restarted', 'Remote API server restarted successfully', 'success');
            // Update connection status after a longer delay for restart
            setTimeout(() => {
                window.pclinkUI.updateConnectionStatus();
            }, 2000);
        } else {
            const error = await response.text();
            throw new Error(error || 'Failed to restart server');
        }
    } catch (error) {
        console.error('Restart server failed:', error);
        window.pclinkUI.showToast('Restart Failed', `Failed to restart remote API server: ${error.message}`, 'error');
    } finally {
        // Restore original content (icons will be restored automatically)
        button.innerHTML = originalContent;
        button.disabled = false;
        startButton.disabled = false;
        stopButton.disabled = false;
    }
}

async function shutdownServer() {
    console.log('shutdownServer function called');

    // Show confirmation dialog
    if (!confirm('Are you sure you want to shutdown PCLink server? This will close the application completely.')) {
        console.log('Shutdown cancelled by user');
        return;
    }

    console.log('User confirmed shutdown, proceeding...');

    const button = document.getElementById('shutdownServerBtn');
    const button2 = document.getElementById('shutdownServerBtn2');
    const startButton = document.getElementById('startServerBtn');
    const stopButton = document.getElementById('stopServerBtn');
    const restartButton = document.getElementById('restartServerBtn');

    // Store original button content
    const originalContent = button ? button.innerHTML : '<i data-feather="power"></i> Shutdown';

    try {
        // Set loading state
        if (button) {
            button.innerHTML = '<span style="display: inline-flex; align-items: center; gap: 6px;"><span class="spinner"></span>Shutting down...</span>';
            button.disabled = true;
        }
        if (button2) {
            button2.innerHTML = '<span style="display: inline-flex; align-items: center; gap: 6px;"><span class="spinner"></span>Shutting down...</span>';
            button2.disabled = true;
        }
        if (startButton) startButton.disabled = true;
        if (stopButton) stopButton.disabled = true;
        if (restartButton) restartButton.disabled = true;

        const response = await fetch('/server/shutdown', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        if (response.ok) {
            window.pclinkUI.showToast('Server Shutdown', 'PCLink server is shutting down...', 'info');

            // Show a message that the server is shutting down
            setTimeout(() => {
                document.body.innerHTML = `
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background: #1a1a1a; color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                        <div style="text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 20px;">⚡</div>
                            <h2 style="margin: 0 0 10px 0;">PCLink Server Shutdown</h2>
                            <p style="margin: 0; opacity: 0.7;">The server has been shut down. You can close this tab.</p>
                        </div>
                    </div>
                `;
            }, 1000);
        } else {
            const error = await response.text();
            throw new Error(error || 'Failed to shutdown server');
        }
    } catch (error) {
        console.error('Shutdown server failed:', error);
        window.pclinkUI.showToast('Shutdown Failed', `Failed to shutdown server: ${error.message}`, 'error');

        // Restore original content on error
        if (button) {
            button.innerHTML = originalContent;
            button.disabled = false;
        }
        if (button2) {
            button2.innerHTML = originalContent;
            button2.disabled = false;
        }
        if (startButton) startButton.disabled = false;
        if (stopButton) stopButton.disabled = false;
        if (restartButton) restartButton.disabled = false;
    }
}


// Make functions globally accessible
window.shutdownServer = shutdownServer;
window.startRemoteServer = startRemoteServer;
window.stopRemoteServer = stopRemoteServer;
window.restartRemoteServer = restartRemoteServer;

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing PCLink UI...');
    window.pclinkUI = new PCLinkWebUI();

    // Debug: Test tab switching after a short delay
    setTimeout(() => {
        console.log('Testing tab functionality...');
        const navButtons = document.querySelectorAll('.nav-btn');
        console.log('Found nav buttons:', navButtons.length);

        navButtons.forEach((btn, index) => {
            console.log(`Button ${index}:`, btn.dataset.tab, btn.classList.contains('active'));
        });

        const tabContents = document.querySelectorAll('.tab-content');
        console.log('Found tab contents:', tabContents.length);

        tabContents.forEach((content, index) => {
            console.log(`Content ${index}:`, content.id, content.classList.contains('active'));
        });
    }, 1000);
});


window.testTabSwitch = function (tabName) {
    console.log('Manual tab switch test to:', tabName);
    if (window.pclinkUI) {
        window.pclinkUI.switchTab(tabName);
    } else {
        console.error('PCLink UI not initialized');
    }
};