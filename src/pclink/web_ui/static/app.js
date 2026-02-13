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
        this.currentPhonePath = '/';
        this.phoneNavHistory = ['/'];
        this.phoneHistoryIndex = 0;
        this.phoneSearchQuery = '';
        this.phoneSortMode = 'name_asc';
        this.phoneShowHidden = false;
        this.phoneSelectedItems = new Set();
        this.phoneFileItems = [];
        this.phoneIsReadOnly = false;
        this.isUploading = false;
        this.currentPhoneDeviceId = null; // Track selected device for file browsing
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
            } else if (activeTab === 'devices' || activeTab === 'phone-files') {
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
            case 'services':
                await this.loadServices();
                break;
            case 'phone-files':
                await this.loadDevices();
                await this.loadPhoneFiles(this.currentPhonePath);
                break;
        }
    }

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
                this.updatePhoneDeviceSelector();
                this.updateDeviceCount();
            }
            await this.loadPendingRequests();
        } catch (error) {
            console.error('Failed to load devices:', error);
            const deviceList = document.getElementById('deviceList');
            if (deviceList) deviceList.innerHTML = '<p class="error">Failed to load devices</p>';
        }
    }

    async loadPendingRequests() {
        try {
            console.log('Loading pending requests...');
            // Endpoint defined as @app.get("/ui/pairing/list") in api.py
            // This is relative to root, but webUICall expects path relative to baseUrl (origin)
            // If baseUrl is origin, then '/ui/pairing/list' is correct.
            const res = await this.webUICall('/ui/pairing/list');

            if (res.ok) {
                const data = await res.json();
                this.displayPendingRequests(data.requests || []);
            }
        } catch (error) {
            console.error('Failed to load pending requests:', error);
        }
    }

    displayPendingRequests(requests) {
        const container = document.getElementById('pendingRequests');
        if (!container) return;

        if (requests.length === 0) {
            container.innerHTML = '<p>No pending requests</p>';
            return;
        }

        container.innerHTML = requests.map(req => `
            <div class="device-item pending-item">
                <div class="device-info">
                    <h4>📱 ${req.device_name} <span class="badge warning" style="background:#f0ad4e;color:white;padding:2px 6px;border-radius:4px;font-size:0.8em">Pending</span></h4>
                    <div class="device-meta">
                        <span>IP: ${req.ip}</span> • 
                        <span>${req.platform}</span>
                    </div>
                </div>
                <div class="device-actions">
                    <button class="btn btn-sm btn-primary" onclick="approvePairingRequest('${req.pairing_id}')">Approve</button>
                    <button class="btn btn-sm btn-secondary" onclick="denyPairingRequest('${req.pairing_id}')">Deny</button>
                </div>
            </div>
        `).join('');
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
        if (!deviceListElement) return;

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

    updatePhoneDeviceSelector() {
        const selector = document.getElementById('phoneDeviceSelector');
        if (!selector) return;
        
        // Save current selection to restore state
        const currentSelection = this.currentPhoneDeviceId;
        
        // Reset options
        selector.innerHTML = '<option value="">Select Device...</option>';
        
        this.devices.forEach(device => {
            const option = document.createElement('option');
            option.value = device.id;
            // Show status indicator emoji?
            option.textContent = `${device.name} (${device.ip})`;
            if (device.id === currentSelection) {
                option.selected = true;
            }
            selector.appendChild(option);
        });
        
        // Auto-select first device if none selected and devices exist
        if (!this.currentPhoneDeviceId && this.devices.length > 0) {
            this.currentPhoneDeviceId = this.devices[0].id;
            selector.value = this.currentPhoneDeviceId;
        }
    }

    async handlePhoneDeviceChange(deviceId) {
        console.log('Phone device changed to:', deviceId);
        this.currentPhoneDeviceId = deviceId;
        this.currentPhonePath = '/'; // Reset path when switching devices
        await this.loadPhoneFiles('/');
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
                const config = await response.json();
                const portInput = document.getElementById('serverPortInput');
                if (portInput) portInput.value = window.location.port || '38080';

                if (config.auto_start !== undefined) {
                    const autoStartCheckbox = document.getElementById('autoStartCheckbox');
                    if (autoStartCheckbox) autoStartCheckbox.checked = config.auto_start;
                }
                
                if (config.auto_open_webui !== undefined) {
                    const autoOpenWebUI = document.getElementById('autoOpenWebUI');
                    if (autoOpenWebUI) autoOpenWebUI.checked = config.auto_open_webui;
                }

                await this.loadTransferSettings();
            }
        } catch (e) {
           
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

    async loadServices() {
        const grid = document.getElementById('servicesGrid');
        if (!grid) return;

        try {
            const response = await this.webUICall('/ui/services/');
            if (response.ok) {
                const data = await response.json();
                this.displayServices(data.services || []);
            } else {
                grid.innerHTML = '<p class="error">Failed to load services</p>';
            }
        } catch (error) {
            console.error('Failed to load services:', error);
            grid.innerHTML = '<p class="error">Error connecting to services API</p>';
        }
    }

    displayServices(services) {
        const grid = document.getElementById('servicesGrid');
        if (!grid) return;

        if (services.length === 0) {
            grid.innerHTML = '<p>No services registered</p>';
            return;
        }

        grid.innerHTML = services.map(service => `
            <div class="service-card ${!service.enabled ? 'disabled' : ''}" id="service-card-${service.id}">
                <div class="service-header">
                    <div class="service-info-main">
                        <div class="service-icon-wrapper">
                            <i data-feather="${service.icon || 'box'}"></i>
                        </div>
                        <div class="service-text-container">
                            <h4>${service.title}</h4>
                            <div class="service-description">${service.description}</div>
                        </div>
                    </div>
                    <label class="switch">
                        <input type="checkbox" ${service.enabled ? 'checked' : ''} 
                               onchange="toggleService('${service.id}', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
            </div>
        `).join('');

        // Ensure feather icons are replaced after content is added
        if (window.feather) {
            // Use a small timeout to ensure DOM is fully updated before feather.replace()
            setTimeout(() => feather.replace(), 0);
        }
    }

    async toggleService(serviceId, enabled) {
        const card = document.getElementById(`service-card-${serviceId}`);
        try {
            const response = await this.webUICall('/ui/services/toggle', {
                method: 'POST',
                body: JSON.stringify({ name: serviceId, enabled: enabled })
            });

            if (response.ok) {
                if (card) {
                    if (enabled) card.classList.remove('disabled');
                    else card.classList.add('disabled');
                }
                this.showToast('Success', `Service '${serviceId}' ${enabled ? 'enabled' : 'disabled'}`);
                
                // If extensions were toggled, it might affect other UI parts
                if (serviceId === 'extensions') {
                    this.loadSettings();
                }
            } else {
                throw new Error('Failed to toggle service');
            }
        } catch (error) {
            console.error('Toggle service failed:', error);
            this.showToast('Error', `Failed to update service status`, 'error');
            // Revert checkbox state
            this.loadServices();
        }
    }

    async loadPhoneFiles(path) {
        const listContainer = document.getElementById('phoneFileList');
        const breadcrumb = document.getElementById('phoneBreadcrumb');
        const backBtn = document.getElementById('phoneBackBtn');
        const forwardBtn = document.getElementById('phoneForwardBtn');
        
        if (breadcrumb) breadcrumb.innerHTML = `<span>Path: ${path}</span>`;
        if (backBtn) backBtn.disabled = this.phoneHistoryIndex <= 0;
        if (forwardBtn) forwardBtn.disabled = this.phoneHistoryIndex >= this.phoneNavHistory.length - 1;
        
            const cleanPath = path.startsWith('/') ? path : '/' + path;
            const container = document.getElementById('phoneFileList');
            const disabledState = container.querySelector('.service-disabled');
            
            try {
                let url = `/phone/files/.browse${cleanPath}`;
                if (this.currentPhoneDeviceId) {
                    url += `?device_id=${encodeURIComponent(this.currentPhoneDeviceId)}`;
                }
                
                const response = await fetch(url, {
                    headers: this.getHeaders()
                });
                
                if (response.ok) {
                    const data = await response.json();
                    this.phoneFileItems = data.items || [];
                    this.phoneIsReadOnly = data.readOnly || false;
                    if (disabledState) disabledState.style.display = 'none';
                    this.updatePhoneUIPermissions();
                    this.displayPhoneFiles();
                } else if (response.status === 502 || response.status === 404) {
                    // 502/404 from proxy usually means phone is offline or service is off
                    container.innerHTML = ''; // Clear previous content
                    if (disabledState) {
                        disabledState.style.display = 'block';
                        container.appendChild(disabledState);
                    } else {
                        container.innerHTML = `<p class="error">Failed to load files: ${response.statusText}</p>`;
                    }
                } else {
                    container.innerHTML = `<p class="error">Failed to load files: ${response.statusText}</p>`;
                }
            } catch (error) {
                console.error('Connection error:', error);
                if (disabledState) {
                    disabledState.style.display = 'block';
                    container.innerHTML = ''; 
                    container.appendChild(disabledState);
                } else {
                    container.innerHTML = `<p class="error">Error: ${error.message}</p>`;
                }
            }
    }

    displayPhoneFiles() {
        const listContainer = document.getElementById('phoneFileList');
        
        // 1. Filter
        let filtered = this.phoneFileItems.filter(item => {
            // Hidden filter
            if (!this.phoneShowHidden && item.name.startsWith('.')) return false;
            // Search filter
            if (this.phoneSearchQuery && !item.name.toLowerCase().includes(this.phoneSearchQuery.toLowerCase())) return false;
            return true;
        });

        // 2. Sort
        filtered.sort((a, b) => {
            // Folders always first
            if (a.isDir && !b.isDir) return -1;
            if (!a.isDir && b.isDir) return 1;

            const [field, direction] = this.phoneSortMode.split('_');
            let comparison = 0;

            switch (field) {
                case 'name':
                    comparison = a.name.localeCompare(b.name);
                    break;
                case 'size':
                    comparison = (a.size || 0) - (b.size || 0);
                    break;
                case 'date':
                    comparison = new Date(a.modified) - new Date(b.modified);
                    break;
            }

            return direction === 'asc' ? comparison : -comparison;
        });

        if (filtered.length === 0) {
            listContainer.innerHTML = '<div class="empty-state"><i data-feather="inbox"></i><p>No matching files</p></div>';
            if (window.feather) feather.replace();
            return;
        }

        listContainer.innerHTML = filtered.map(item => {
            const isSelected = this.phoneSelectedItems.has(item.path);
            return `
                <div class="file-item ${item.isDir ? 'directory' : 'file'}" onclick="handleFileItemClick(event, '${item.path}', ${item.isDir})">
                    <input type="checkbox" class="file-select-checkbox" ${isSelected ? 'checked' : ''} 
                           onclick="event.stopPropagation(); toggleItemSelection('${item.path}')">
                    <div class="file-icon">
                        <i data-feather="${item.isDir ? 'folder' : 'file'}"></i>
                    </div>
                    <div class="file-info">
                        <span class="file-name">${item.name}</span>
                        <span class="file-meta">${item.isDir ? 'Directory' : this.formatFileSize(item.size)} • ${new Date(item.modified).toLocaleString()}</span>
                    </div>
                    <div class="file-actions">
                        ${!item.isDir ? `<i data-feather="download" title="Download" onclick="event.stopPropagation(); downloadPhoneFile('${item.path}')"></i>` : `<i data-feather="chevron-right"></i>`}
                    </div>
                </div>
            `;
        }).join('');
        
        if (window.feather) feather.replace();
    }

    updatePhoneUIPermissions() {
        const uploadBtn = document.getElementById('phoneUploadBtn');
        const deleteBtn = document.getElementById('batchDeleteBtn');
        const badge = document.getElementById('phoneReadOnlyBadge');
        
        if (uploadBtn) {
            uploadBtn.style.display = this.phoneIsReadOnly ? 'none' : 'flex';
        }
        if (deleteBtn) {
            deleteBtn.style.display = this.phoneIsReadOnly ? 'none' : 'flex';
        }
        if (badge) {
            badge.style.display = this.phoneIsReadOnly ? 'inline-flex' : 'none';
        }
    }

    async uploadFile(file) {
        const container = document.getElementById('uploadProgressContainer');
        const uploadId = 'up-' + Math.random().toString(36).substr(2, 9);
        
        const itemHtml = `
            <div id="${uploadId}" class="upload-item">
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span>📤 ${file.name}</span>
                    <span class="progress-text">0%</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" style="width: 0%"></div>
                </div>
            </div>
        `;
        container.insertAdjacentHTML('afterbegin', itemHtml);

        try {
            const formData = new FormData();
            formData.append('file', file);

            const cleanBasePath = this.currentPhonePath.endsWith('/') ? this.currentPhonePath : this.currentPhonePath + '/';
            const fileName = file.name;
            const cleanFullPath = (cleanBasePath + fileName).startsWith('/') ? (cleanBasePath + fileName) : '/' + (cleanBasePath + fileName);
            
            console.log(`[Upload] Starting upload of ${file.name} to ${cleanFullPath}`);

            const xhr = new XMLHttpRequest();
            let url = `/phone/files${cleanFullPath}`;
            if (this.currentPhoneDeviceId) {
                url += `?device_id=${encodeURIComponent(this.currentPhoneDeviceId)}`;
            }
            xhr.open('PUT', url, true);
            
            // Add API key if present
            if (this.apiKey) {
                xhr.setRequestHeader('X-API-Key', this.apiKey);
            }

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    const el = document.getElementById(uploadId);
                    if (el) {
                        el.querySelector('.progress-bar-fill').style.width = percent + '%';
                        el.querySelector('.progress-text').textContent = percent + '%';
                    }
                }
            };

            const promise = new Promise((resolve, reject) => {
                xhr.onload = () => {
                    if (xhr.status >= 200 && xhr.status < 300) resolve();
                    else reject(new Error(`Upload failed: ${xhr.statusText}`));
                };
                xhr.onerror = () => reject(new Error('Network error'));
            });

            xhr.send(file); 
            await promise;

            const el = document.getElementById(uploadId);
            if (el) {
                el.style.opacity = '0.5';
                setTimeout(() => el.remove(), 2000);
            }
            this.showToast('Success', `Uploaded ${file.name}`);
        } catch (error) {
            console.error('Upload failed:', error);
            const el = document.getElementById(uploadId);
            if (el) el.style.color = 'var(--danger-color)';
            this.showToast('Error', `Failed to upload ${file.name}`, 'error');
        }
    }

    async deletePhoneItems(paths) {
        if (!confirm(`Are you sure you want to delete ${paths.length} item(s)?`)) return;

        let successCount = 0;
        for (const path of paths) {
            try {
                const cleanPath = path.startsWith('/') ? path : '/' + path;
                let url = `/phone/files${cleanPath}`;
                if (this.currentPhoneDeviceId) {
                    url += `?device_id=${encodeURIComponent(this.currentPhoneDeviceId)}`;
                }
                const response = await fetch(url, {
                    method: 'DELETE',
                    headers: this.getHeaders()
                });
                if (response.ok) successCount++;
            } catch (error) {
                console.error(`Failed to delete ${path}:`, error);
            }
        }

        if (successCount > 0) {
            this.showToast('Success', `Deleted ${successCount} item(s)`);
            this.phoneSelectedItems.clear();
            this.updateBatchActionBar();
            this.loadPhoneFiles(this.currentPhonePath);
        } else {
            this.showToast('Error', 'Deletion failed', 'error');
        }
    }

    updateBatchActionBar() {
        const bar = document.getElementById('batchActionBar');
        const count = document.getElementById('selectedCount');
        if (!bar || !count) return;

        const selectedCount = this.phoneSelectedItems.size;
        count.textContent = selectedCount;

        if (selectedCount > 0) {
            bar.classList.add('active');
        } else {
            bar.classList.remove('active');
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
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
    const settings = {
        auto_start: document.getElementById('autoStartCheckbox')?.checked,
        auto_open_webui: document.getElementById('autoOpenWebUI')?.checked
    };

    try {
        const response = await window.pclinkUI.webUICall('/settings/save', {
            method: 'POST',
            body: JSON.stringify(settings)
        });
        if (response.ok) {
            window.pclinkUI.showToast('Success', 'Settings saved successfully');
        } else {
            window.pclinkUI.showToast('Error', 'Failed to save settings', 'error');
        }
    } catch (e) {
        console.error('Failed to save settings:', e);
        window.pclinkUI.showToast('Error', 'An error occurred while saving settings', 'error');
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

async function toggleService(serviceId, enabled) {
    if (window.pclinkUI) {
        await window.pclinkUI.toggleService(serviceId, enabled);
    }
}

// Phone File Navigation
window.navigatePhone = (path) => {
    if (window.pclinkUI) {
        // Handle history
        if (path !== window.pclinkUI.currentPhonePath) {
            // Remove any forward history if we're at a branch
            window.pclinkUI.phoneNavHistory = window.pclinkUI.phoneNavHistory.slice(0, window.pclinkUI.phoneHistoryIndex + 1);
            window.pclinkUI.phoneNavHistory.push(path);
            window.pclinkUI.phoneHistoryIndex = window.pclinkUI.phoneNavHistory.length - 1;
        }
        
        window.pclinkUI.currentPhonePath = path;
        window.pclinkUI.phoneSelectedItems.clear();
        window.pclinkUI.updateBatchActionBar();
        window.pclinkUI.loadPhoneFiles(path);
    }
};

window.refreshPhoneFiles = () => {
    if (window.pclinkUI) {
        window.pclinkUI.loadPhoneFiles(window.pclinkUI.currentPhonePath);
    }
};

window.goBackPhoneFiles = () => {
    if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex > 0) {
        window.pclinkUI.phoneHistoryIndex--;
        const path = window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex];
        window.pclinkUI.currentPhonePath = path;
        window.pclinkUI.loadPhoneFiles(path);
    }
};

window.goForwardPhoneFiles = () => {
    if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex < window.pclinkUI.phoneNavHistory.length - 1) {
        window.pclinkUI.phoneHistoryIndex++;
        const path = window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex];
        window.pclinkUI.currentPhonePath = path;
        window.pclinkUI.loadPhoneFiles(path);
    }
};

// Selection & Actions
window.toggleItemSelection = (path) => {
    if (window.pclinkUI) {
        if (window.pclinkUI.phoneSelectedItems.has(path)) {
            window.pclinkUI.phoneSelectedItems.delete(path);
        } else {
            window.pclinkUI.phoneSelectedItems.add(path);
        }
        window.pclinkUI.updateBatchActionBar();
        window.pclinkUI.displayPhoneFiles();
    }
};

window.clearSelection = () => {
    if (window.pclinkUI) {
        window.pclinkUI.phoneSelectedItems.clear();
        window.pclinkUI.updateBatchActionBar();
        window.pclinkUI.displayPhoneFiles();
    }
};

window.handleFileItemClick = (event, path, isDir) => {
    // If clicking the item with Ctrl/Meta, toggle selection
    if (event.ctrlKey || event.metaKey) {
        toggleItemSelection(path);
    } else if (isDir) {
        navigatePhone(path);
    } else {
        // Non-directory single click = toggle selection for now, or could do nothing
        toggleItemSelection(path);
    }
};

// Filtering & Sorting
window.handlePhoneSearch = (query) => {
    if (window.pclinkUI) {
        window.pclinkUI.phoneSearchQuery = query;
        window.pclinkUI.displayPhoneFiles();
    }
};

window.handlePhoneSort = (mode) => {
    if (window.pclinkUI) {
        window.pclinkUI.phoneSortMode = mode;
        window.pclinkUI.displayPhoneFiles();
    }
};

window.handleToggleHidden = (show) => {
    if (window.pclinkUI) {
        window.pclinkUI.phoneShowHidden = show;
        window.pclinkUI.displayPhoneFiles();
    }
};

// Upload & Delete
window.triggerUpload = () => {
    document.getElementById('phoneUploadInput').click();
};

window.handlePhoneUpload = async (input) => {
    if (!input.files || input.files.length === 0) return;
    if (window.pclinkUI) {
        for (const file of input.files) {
            await window.pclinkUI.uploadFile(file);
        }
        window.refreshPhoneFiles();
        input.value = ''; // Reset input
    }
};

window.deleteSelectedItems = () => {
    if (window.pclinkUI) {
        const paths = Array.from(window.pclinkUI.phoneSelectedItems);
        window.pclinkUI.deletePhoneItems(paths);
    }
};

window.downloadSelectedItems = () => {
    if (window.pclinkUI) {
        const paths = Array.from(window.pclinkUI.phoneSelectedItems);
        // Sequential download (browsers handle this by triggering multiple saves or pops)
        paths.forEach(path => {
            const cleanPath = path.startsWith('/') ? path : '/' + path;
            const link = document.createElement('a');
            let url = `/phone/files${cleanPath}`;
            if (window.pclinkUI?.currentPhoneDeviceId) {
                url += `?device_id=${encodeURIComponent(window.pclinkUI.currentPhoneDeviceId)}`;
            }
            link.href = url;
            link.download = path.split('/').pop();
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        });
    }
};

window.downloadPhoneFile = (path) => {
    // Generate an absolute URL for download
    let url = `/phone/files${path.startsWith('/') ? path : '/' + path}`;
    if (window.pclinkUI?.currentPhoneDeviceId) {
        url += `?device_id=${encodeURIComponent(window.pclinkUI.currentPhoneDeviceId)}`;
    }
    window.location.href = url;
};

window.handlePhoneDeviceChange = (deviceId) => {
    if (window.pclinkUI) {
        window.pclinkUI.handlePhoneDeviceChange(deviceId);
    }
};

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
window.removeAllDevices = async () => {
    if (confirm('Are you sure you want to remove ALL devices? This cannot be undone.')) {
        try {
            await window.pclinkUI.webUICall('/devices/remove-all', { method: 'POST' });
            window.pclinkUI.loadDevices();
            window.pclinkUI.showToast('Success', 'All devices removed');
        } catch (e) {
            window.pclinkUI.showToast('Error', 'Failed to remove devices');
        }
    }
};

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

window.approvePairingRequest = (pairingId) => {
    if (window.pclinkUI.websocket && window.pclinkUI.websocket.readyState === WebSocket.OPEN) {
        window.pclinkUI.websocket.send(JSON.stringify({
            type: 'approve_pair',
            pairing_id: pairingId
        }));
        // Optimistically remove from UI
        setTimeout(() => window.pclinkUI.loadPendingRequests(), 500);
    } else {
        window.pclinkUI.showToast('Error', 'WebSocket not connected', 'error');
    }
};

window.denyPairingRequest = (pairingId) => {
    if (window.pclinkUI.websocket && window.pclinkUI.websocket.readyState === WebSocket.OPEN) {
        window.pclinkUI.websocket.send(JSON.stringify({
            type: 'deny_pair',
            pairing_id: pairingId
        }));
        setTimeout(() => window.pclinkUI.loadPendingRequests(), 500);
    } else {
        window.pclinkUI.showToast('Error', 'WebSocket not connected', 'error');
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
                window.updateData = data;
                const banner = document.getElementById('updateBanner');
                if (banner) {
                    banner.style.display = 'block';
                    document.getElementById('updateVersion').textContent = `Version ${data.latest_version} is now available`;
                    const notesEl = document.getElementById('updateReleaseNotes');
                    if (notesEl && data.release_notes) {
                        notesEl.textContent = data.release_notes;
                    }
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
window.updateNotificationSettings = () => {
    if (!window.pclinkUI) return;
    window.pclinkUI.notificationSettings = {
        deviceConnect: document.getElementById('notifyDeviceConnect').checked,
        deviceDisconnect: document.getElementById('notifyDeviceDisconnect').checked,
        pairingRequest: document.getElementById('notifyPairingRequest').checked,
        updates: document.getElementById('notifyUpdates').checked
    };
    window.pclinkUI.saveNotificationSettings();
    window.pclinkUI.showToast('Success', 'Notification settings updated');
};
