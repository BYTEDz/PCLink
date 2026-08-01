// static/js/system.js

PCLinkWebUI.prototype.loadApiKey = async function () {
    try {
        const res = await fetch('/qr-payload');
        if (res.ok) {
            const data = await res.json();
            this.apiKey = data.apiKey;
            this.updateApiKeyDisplay();
        }
    } catch (e) { }
};

PCLinkWebUI.prototype.updateApiKeyDisplay = function () {
    const el = document.getElementById('apiKeyDisplay');
    const eye = document.getElementById('apiKeyEye');
    if (!el) return;
    el.type = this.apiKeyVisible ? "text" : "password";
    el.value = this.apiKey || "••••••••••••";
    if (eye && window.feather) {
        eye.setAttribute('data-feather', this.apiKeyVisible ? 'eye-off' : 'eye');
        this.renderIcons();
    }
};

PCLinkWebUI.prototype.loadServerStatus = async function () {
    try {
        const data = await this.apiCall('/qr-payload');
        const el = document.getElementById('hostIP');
        if (el) el.textContent = data.ip || window.location.hostname;
    } catch (e) {
        const el = document.getElementById('hostIP');
        if (el) el.textContent = window.location.hostname;
    }

    // 1. Fetch system telemetry directly via HTTP
    try {
        const sysRes = await this.webUICall('/info/system');
        if (sysRes.ok) {
            const sysData = await sysRes.json();
            this.updateDashboardTelemetry(sysData);
            this.updateDashboardAdapters(sysData.network?.interfaces);
        }
    } catch (e) { }

    // 2. Fetch Disks Storage Info
    try {
        const disksRes = await this.webUICall('/info/disks');
        if (disksRes.ok) {
            const disksData = await disksRes.json();
            this.updateDashboardDisks(disksData.disks || []);
        }
    } catch (e) { }

    // 3. Fetch Paired Fleet Info
    try {
        const devRes = await this.webUICall('/ui/devices');
        if (devRes.ok) {
            const devData = await devRes.json();
            this.updateDashboardFleet(devData.devices || []);
        }
    } catch (e) { }

    // 4. Fetch Security & Auth Info
    try {
        const secRes = await fetch('/auth/status');
        if (secRes.ok) {
            const secData = await secRes.json();
            this.updateDashboardSecurity(secData);
        }
    } catch (e) { }

    // 5. Fetch Transfer Pipeline Debug Metrics
    try {
        const perfRes = await this.webUICall('/debug/performance');
        if (perfRes.ok) {
            const perfData = await perfRes.json();
            this.updateDashboardTransfers(perfData);
        }
    } catch (e) { }

    await this.updateServerStatus();
    this.updateActivity();
};

PCLinkWebUI.prototype.updateActivity = function () {
    const el = document.getElementById('serverUptime');
    if (el) el.textContent = this.formatUptime(Date.now() - this.serverStartTime);
};

PCLinkWebUI.prototype.updateServerStatus = async function () {
    const portEl = document.getElementById('serverPort');
    const verEl = document.getElementById('serverVersion');
    if (portEl) portEl.textContent = `Port: ${window.location.port || '38080'}`;
    try {
        const res = await fetch('/status');
        if (res.ok) {
            const data = await res.json();
            if (verEl && data.version) verEl.textContent = `v${data.version}`;
            if (data.start_time) this.serverStartTime = data.start_time * 1000;
        }
    } catch (e) { }
};

PCLinkWebUI.prototype.updateDashboardTelemetry = function (sys) {
    if (!sys) return;

    // CPU
    if (sys.cpu) {
        const cpuPct = Math.round(sys.cpu.percent || 0);
        const cpuVal = document.getElementById('dashCpuVal');
        const cpuBar = document.getElementById('dashCpuBar');
        const cpuSub = document.getElementById('dashCpuSub');
        if (cpuVal) cpuVal.textContent = `${cpuPct}%`;
        if (cpuBar) cpuBar.value = cpuPct;
        if (cpuSub) {
            if (sys.cpu.physical_cores) {
                cpuSub.textContent = `${sys.cpu.physical_cores} Cores (${sys.cpu.total_cores || 0} Threads)`;
            } else if (sys.cpu.total_cores) {
                cpuSub.textContent = `${sys.cpu.total_cores} Cores`;
            }
        }
    }

    // RAM
    if (sys.ram) {
        const ramPct = Math.round(sys.ram.percent || 0);
        const ramVal = document.getElementById('dashRamVal');
        const ramBar = document.getElementById('dashRamBar');
        const ramSub = document.getElementById('dashRamSub');
        if (ramVal) ramVal.textContent = `${ramPct}%`;
        if (ramBar) ramBar.value = ramPct;
        if (ramSub) {
            ramSub.textContent = `${sys.ram.used_gb || 0} GB / ${sys.ram.total_gb || 0} GB`;
        }
    }

    // Network
    if (sys.network && sys.network.speed) {
        const netUp = document.getElementById('dashNetUp');
        const netDown = document.getElementById('dashNetDown');
        if (netUp) netUp.textContent = `${(sys.network.speed.upload_mbps || 0).toFixed(2)} Mbps`;
        if (netDown) netDown.textContent = `${(sys.network.speed.download_mbps || 0).toFixed(2)} Mbps`;
    }

    // Thermals & Battery
    const tempVal = document.getElementById('dashTempVal');
    const powerSub = document.getElementById('dashPowerSub');

    if (sys.sensors && sys.sensors.cpu_temp_celsius) {
        if (tempVal) tempVal.textContent = `${Math.round(sys.sensors.cpu_temp_celsius)} °C`;
    } else if (tempVal && (tempVal.textContent === 'N/A' || !tempVal.textContent)) {
        tempVal.textContent = 'Normal';
    }

    if (sys.battery && sys.battery.percent !== undefined) {
        if (powerSub) {
            const state = sys.battery.power_plugged ? 'Charging' : 'Battery';
            powerSub.textContent = `${sys.battery.percent}% (${state})`;
        }
    }
};

// 1. Storage & Disks Render
PCLinkWebUI.prototype.updateDashboardDisks = function (disks) {
    const container = document.getElementById('dashDisksContainer');
    if (!container) return;

    if (!disks || disks.length === 0) {
        container.innerHTML = '<div class="text-center py-6 opacity-40 text-xs font-bold">No storage volumes found</div>';
        return;
    }

    container.innerHTML = disks.map(disk => `
        <div class="p-3 bg-base-200/50 rounded-xl border border-base-300/50 space-y-1.5">
            <div class="flex justify-between items-center text-xs font-bold">
                <span class="truncate font-mono">${this.escapeHTML(disk.device)}</span>
                <span class="opacity-60 text-[10px]">${disk.used} / ${disk.total} (${disk.percent}%)</span>
            </div>
            <progress class="progress ${disk.percent > 90 ? 'progress-error' : 'progress-primary'} w-full h-1.5" value="${disk.percent}" max="100"></progress>
        </div>
    `).join('');
};

// 2. Active Connected Fleet Render
PCLinkWebUI.prototype.updateDashboardFleet = function (devices) {
    const container = document.getElementById('dashFleetContainer');
    if (!container) return;

    const activeDevices = (devices || []).filter(d => d.is_approved);

    if (activeDevices.length === 0) {
        container.innerHTML = '<div class="text-center py-6 opacity-40 text-xs font-bold">No linked devices</div>';
        return;
    }

    container.innerHTML = activeDevices.map(d => `
        <div class="p-2.5 bg-base-200/50 rounded-xl border border-base-300/50 flex items-center justify-between gap-3">
            <div class="flex items-center gap-2.5 min-w-0">
                <div class="${d.is_online ? 'bg-success/10 text-success' : 'bg-base-300 opacity-50'} p-2 rounded-lg shrink-0">
                    <i data-feather="smartphone" class="w-4 h-4"></i>
                </div>
                <div class="min-w-0">
                    <h4 class="font-bold text-xs truncate">${this.escapeHTML(d.name)}</h4>
                    <p class="text-[9px] font-mono opacity-50 truncate">${d.ip || 'N/A'}</p>
                </div>
            </div>
            <span class="badge ${d.is_online ? 'badge-success text-white' : 'badge-ghost opacity-50'} badge-xs font-bold uppercase text-[8px]">${d.is_online ? 'Online' : 'Offline'}</span>
        </div>
    `).join('');

    this.renderIcons();
};

// 3. Network Adapters & IPs Render
PCLinkWebUI.prototype.updateDashboardAdapters = function (interfaces) {
    const container = document.getElementById('dashAdaptersContainer');
    if (!container) return;

    if (!interfaces || Object.keys(interfaces).length === 0) {
        container.innerHTML = '<div class="text-center py-6 opacity-40 text-xs font-bold">No active network adapters</div>';
        return;
    }

    container.innerHTML = Object.entries(interfaces).map(([nic, info]) => `
        <div class="p-2.5 bg-base-200/50 rounded-xl border border-base-300/50 flex items-center justify-between gap-3">
            <div class="min-w-0">
                <h4 class="font-bold text-xs truncate">${this.escapeHTML(nic)}</h4>
                <p class="text-[10px] font-mono text-primary font-bold truncate">${info.ip || 'No IP'}</p>
            </div>
            <button class="btn btn-ghost btn-xs text-primary gap-1 font-bold" onclick="navigator.clipboard.writeText('${info.ip}')" title="Copy IP">
                <i data-feather="copy" class="w-3"></i> Copy
            </button>
        </div>
    `).join('');

    this.renderIcons();
};

// 4. Security & Auth Info
PCLinkWebUI.prototype.updateDashboardSecurity = function (sec) {
    const sessionsVal = document.getElementById('dashActiveSessionsVal');
    const timeoutVal = document.getElementById('dashSessionTimeoutVal');

    if (sessionsVal && sec.active_sessions !== undefined) {
        sessionsVal.textContent = sec.active_sessions;
    }
    if (timeoutVal && sec.session_timeout_hours !== undefined) {
        timeoutVal.textContent = `${sec.session_timeout_hours} hrs`;
    }
};

// 5. Active Transfers Pipeline
PCLinkWebUI.prototype.updateDashboardTransfers = function (perf) {
    const upVal = document.getElementById('dashActiveUploadsVal');
    const downVal = document.getElementById('dashActiveDownloadsVal');

    if (upVal && perf.active_uploads_memory !== undefined) {
        upVal.textContent = perf.active_uploads_memory;
    }
    if (downVal && perf.active_downloads_memory !== undefined) {
        downVal.textContent = perf.active_downloads_memory;
    }
};

// Notification Center Management (Reuses Side Panel)
PCLinkWebUI.prototype.addNotification = function (title, message, type = 'info') {
    if (!this.notifications) this.notifications = [];

    const notif = {
        id: 'n-' + Math.random().toString(36).substr(2, 9),
        title: title,
        message: message,
        type: type,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        read: false
    };

    this.notifications.unshift(notif);
    if (this.notifications.length > 30) this.notifications.pop();

    this.updateNotificationUI();
};

PCLinkWebUI.prototype.updateNotificationUI = function () {
    const badge = document.getElementById('notificationBadgeCount');

    const unread = (this.notifications || []).filter(n => !n.read).length;
    if (badge) {
        if (unread > 0) {
            badge.textContent = unread > 99 ? '99+' : unread;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    }

    this.renderNotificationPanelList();
};

PCLinkWebUI.prototype.markNotificationsAsRead = function () {
    if (!this.notifications) return;
    this.notifications.forEach(n => n.read = true);
    this.updateNotificationUI();
};

PCLinkWebUI.prototype.renderNotificationPanelList = function () {
    const container = document.getElementById('panelNotificationList');
    if (!container) return;

    if (!this.notifications || this.notifications.length === 0) {
        container.innerHTML = `
            <div class="text-center py-20 opacity-40 font-bold uppercase tracking-widest text-xs flex flex-col items-center gap-3">
                <i data-feather="bell-off" class="w-10 h-10 stroke-1"></i>
                <p>No notifications</p>
            </div>
        `;
        this.renderIcons();
        return;
    }

    const typeIcons = {
        success: 'check-circle text-success',
        error: 'alert-circle text-error',
        warning: 'alert-triangle text-warning',
        info: 'info text-info'
    };

    container.innerHTML = this.notifications.map(n => `
        <div class="p-4 bg-base-200/50 rounded-2xl border border-base-300/50 flex items-start gap-3 transition-all hover:border-primary/50">
            <div class="p-2 rounded-xl bg-base-100 border border-base-300/50 shrink-0 mt-0.5">
                <i data-feather="${(typeIcons[n.type] || typeIcons.info).split(' ')[0]}" class="w-4 h-4 ${(typeIcons[n.type] || typeIcons.info).split(' ')[1]}"></i>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between gap-2">
                    <h4 class="font-bold text-xs leading-tight">${this.escapeHTML(n.title)}</h4>
                    <span class="text-[9px] font-mono opacity-40 shrink-0">${n.timestamp}</span>
                </div>
                <p class="text-xs opacity-70 mt-1 leading-relaxed">${this.escapeHTML(n.message)}</p>
            </div>
        </div>
    `).join('');

    this.renderIcons();
};

window.openNotificationPanel = function () {
    if (!window.pclinkUI) return;
    window.pclinkUI.markNotificationsAsRead();

    const title = `<i data-feather="bell" class="text-primary w-4"></i> Notification Center`;
    const body = `<div id="panelNotificationList" class="space-y-3"></div>`;
    const footer = `
        <button class="btn btn-sm btn-ghost font-bold text-xs" onclick="window.clearNotifications()">Clear All</button>
        <button class="btn btn-sm btn-primary text-white font-bold uppercase text-xs px-6" onclick="window.closeSidePanel()">Close</button>
    `;

    window.openSidePanel(title, body, footer);
    window.pclinkUI.renderNotificationPanelList();
};

window.clearNotifications = function () {
    if (window.pclinkUI) {
        window.pclinkUI.notifications = [];
        window.pclinkUI.updateNotificationUI();
    }
};

PCLinkWebUI.prototype.loadServices = async function () {
    try {
        const res = await this.webUICall('/ui/services/list');
        const container = document.getElementById('globalServicesGrid');
        if (!container) return;
        if (res.ok) {
            const data = await res.json();
            const services = data.services || {};
            container.innerHTML = Object.entries(PERMISSION_MAP).map(([key, info]) => `
                <label class="cursor-pointer label border border-base-300 rounded-lg p-4 hover:bg-base-200 transition-colors flex items-center justify-between gap-4">
                    <div class="flex flex-col text-left">
                        <span class="label-text font-black text-xs uppercase tracking-wider">${info.title}</span>
                        <span class="text-[10px] opacity-50 font-bold uppercase tracking-tighter mt-0.5">${info.desc}</span>
                    </div>
                    <input type="checkbox" class="toggle toggle-sm ${key === 'terminal' || key === 'command' ? 'toggle-error' : 'toggle-primary'}" ${services[key] ? 'checked' : ''} onchange="window.toggleService('${key}', this.checked)" />
                </label>
            `).join('');
            this.renderIcons();
        } else {
            container.innerHTML = '<div class="alert alert-error text-xs col-span-full">Failed to load services</div>';
        }
    } catch (e) { console.error("Failed to load global services:", e); }
};

PCLinkWebUI.prototype.toggleService = async function (serviceId, enabled) {
    try {
        const response = await this.webUICall('/ui/services/toggle', { method: 'POST', body: JSON.stringify({ name: serviceId, enabled: enabled }) });
        if (response.ok) {
            this.showToast('Updated', `Service '${serviceId}' toggled`, 'success');
            if (serviceId === 'extensions') this.loadSettings();
            this.loadServices();
        }
    } catch (e) {
        this.showToast('Error', 'Failed to toggle service', 'error');
        this.loadServices();
    }
};

PCLinkWebUI.prototype.loadLogs = async function () {
    const container = document.getElementById('logContainer');
    const content = document.getElementById('logContent');
    if (!container || !content) return;
    try {
        const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
        const level = document.getElementById('logLevelSelect')?.value || '';
        const search = document.getElementById('logFilter')?.value || '';

        let url = '/logs?limit=300';
        if (level) url += `&level=${encodeURIComponent(level)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        const res = await this.webUICall(url);
        if (res.ok) {
            const data = await res.json();
            this.lastLogs = data.logs || '--- clear ---';
            content.textContent = this.lastLogs;
            if (isAtBottom) container.scrollTop = container.scrollHeight;
        }
    } catch (e) { }
};

PCLinkWebUI.prototype.applyLogFilter = function () {
    if (window.pclinkUI) window.pclinkUI.loadLogs();
};

PCLinkWebUI.prototype.loadSettings = async function () {
    try {
        const res = await fetch('/settings/load', { headers: this.getHeaders() });
        if (res.ok) {
            const config = await res.json();
            const portInput = document.getElementById('serverPortInput');
            if (portInput) portInput.value = config.server_port || window.location.port || '38080';
            const currentPort = config.server_port || window.location.port || '38080';
            document.querySelectorAll('.current-port').forEach(el => el.textContent = currentPort);
            const autoStart = document.getElementById('autoStartCheckbox');
            if (autoStart && config.auto_start !== undefined) autoStart.checked = config.auto_start;
            await this.loadTransferSettings();
            if (config.notifications) {
                this.notificationSettings = {
                    deviceConnect: config.notifications.device_connect ?? true,
                    deviceDisconnect: config.notifications.device_disconnect ?? true,
                    pairingRequest: config.notifications.pairing_request ?? true,
                    updates: config.notifications.updates ?? true
                };
            }
            if (config.theme) {
                const sel = document.getElementById('themeSelector');
                if (sel) sel.value = config.theme;
                window.changeTheme(config.theme, false);
            }
            window.loadNotificationSettings();
        }
    } catch (e) { }
};

PCLinkWebUI.prototype.loadTransferSettings = async function () {
    try {
        const res = await fetch('/transfers/cleanup/status');
        if (res.ok) {
            const data = await res.json();
            const thresholdInput = document.getElementById('cleanupThresholdInput');
            if (thresholdInput) thresholdInput.value = data.threshold_days;
            const statusText = document.getElementById('cleanupStatusText');
            if (statusText) statusText.innerHTML = `Found <strong>${data.total_stale}</strong> stale items.`;
        }
    } catch (e) { }
};

PCLinkWebUI.prototype.connectWebSocket = function () {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
        this.websocket = new WebSocket(`${protocol}//${window.location.host}/ws/ui`);
        this.websocket.onopen = () => this.updateConnectionStatus();
        this.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'pairing_request') {
                if (!this.notificationSettings.pairingRequest) return;
                this.pendingPairingRequest = data.data;
                document.getElementById('requestDeviceName').textContent = data.data.device_name || '-';
                document.getElementById('requestDeviceIP').textContent = data.data.ip || '-';
                document.getElementById('requestDevicePlatform').textContent = data.data.platform || '-';
                document.getElementById('pairingModal').showModal();
                this.addNotification('Pairing Request', `${data.data.device_name || 'Device'} is requesting to pair`, 'warning');
            } else if (data.type === 'notification') {
                const title = data.data.title || "";
                if (title.includes("Connected") && !this.notificationSettings.deviceConnect) return;
                if (title.includes("Disconnected") && !this.notificationSettings.deviceDisconnect) return;
                this.showToast(data.data.title, data.data.message || data.data.body);
                this.addNotification(data.data.title, data.data.message || data.data.body, 'info');
            } else if (data.type === 'update') {
                if (data.data) {
                    if (data.data.system) this.updateDashboardTelemetry(data.data.system);
                }
            } else if (data.type === 'server_status') {
                this.updateConnectionStatus();
            }
        };
        this.websocket.onclose = () => setTimeout(() => this.connectWebSocket(), 5000);
    } catch (e) { }
};

// Global System Helpers
window.toggleService = async (id, enabled) => { if (window.pclinkUI) await window.pclinkUI.toggleService(id, enabled); };
window.loadLogs = async () => { if (window.pclinkUI) await window.pclinkUI.loadLogs(); };

window.logout = async () => { if (await window.confirmDialog('End your current session and return to login?', { title: 'Logout' })) { await fetch('/auth/logout', { method: 'POST' }); window.location.reload(); } };
window.regenerateApiKey = async () => { if (await window.confirmDialog('Regenerate the access key? All connected clients will disconnect.', { title: 'Regenerate Key', danger: true })) { await window.pclinkUI.webUICall('/ui/auth/regenerate-key', { method: 'POST' }); window.location.reload(); } };

window.checkForUpdates = async () => {
    try {
        const res = await fetch('/updates/check');
        if (res.ok) {
            const data = await res.json();
            if (data.update_available) {
                window.updateData = data;
                const b = document.getElementById('updateBanner');
                if (b) {
                    b.classList.remove('hidden');
                    document.getElementById('updateVersion').textContent = `v${data.latest_version} available`;
                    const notes = document.getElementById('updateReleaseNotes');
                    if (notes && data.release_notes) notes.textContent = data.release_notes;
                }
                if (window.pclinkUI) {
                    window.pclinkUI.addNotification('Update Available', `PCLink v${data.latest_version} is available`, 'info');
                }
            }
        }
    } catch (e) { }
};
window.dismissUpdate = () => { const b = document.getElementById('updateBanner'); if (b) b.classList.add('hidden'); localStorage.setItem('updateDismissed', Date.now().toString()); };
window.downloadUpdate = () => { if (window.updateData?.download_url) { window.open(window.updateData.download_url, '_blank'); window.dismissUpdate(); } };

window.saveNotificationSettings = async () => {
    if (!window.pclinkUI) return;
    const settings = {
        deviceConnect: document.getElementById('notifyDeviceConnect')?.checked,
        deviceDisconnect: document.getElementById('notifyDeviceDisconnect')?.checked,
        pairingRequest: document.getElementById('notifyPairingRequest')?.checked,
        updates: document.getElementById('notifyUpdates')?.checked
    };
    window.pclinkUI.notificationSettings = settings;
    try {
        const res = await window.pclinkUI.webUICall('/settings/save', {
            method: 'POST',
            body: JSON.stringify({
                notifications: {
                    device_connect: settings.deviceConnect,
                    device_disconnect: settings.deviceDisconnect,
                    pairing_request: settings.pairingRequest,
                    updates: settings.updates
                }
            })
        });
        if (res.ok) window.pclinkUI.showToast('Saved', 'Preferences updated', 'success');
    } catch (e) { window.pclinkUI.showToast('Error', 'Failed to save', 'error'); }
};
window.loadNotificationSettings = () => {
    const s = window.pclinkUI?.notificationSettings || {};
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.checked = v; };
    set('notifyDeviceConnect', s.deviceConnect); set('notifyDeviceDisconnect', s.deviceDisconnect);
    set('notifyPairingRequest', s.pairingRequest); set('notifyUpdates', s.updates);
};

window.refreshDevices = () => window.pclinkUI.loadDevices();
window.refreshLogs = () => window.pclinkUI.loadLogs();
window.filterLogs = () => { if (window.pclinkUI) window.pclinkUI.applyLogFilter(); };

window.copyLogs = async () => {
    const content = document.getElementById('logContent')?.textContent;
    if (!content) return;
    try {
        await navigator.clipboard.writeText(content);
        if (window.pclinkUI) window.pclinkUI.showToast('Copied', 'Logs copied to clipboard', 'success');
    } catch (e) {
        if (window.pclinkUI) window.pclinkUI.showToast('Error', 'Failed to copy logs', 'error');
    }
};

window.downloadLogs = () => {
    const content = document.getElementById('logContent')?.textContent;
    if (!content) return;
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pclink-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
    a.click();
    URL.revokeObjectURL(url);
};

window.clearLogs = async () => {
    if (!await window.confirmDialog('Are you sure you want to clear system logs?', { title: 'Clear Logs', danger: true })) return;
    try {
        const res = await window.pclinkUI.webUICall('/logs/clear', { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Cleared', 'System logs cleared', 'success');
            await window.pclinkUI.loadLogs();
        } else {
            window.pclinkUI.showToast('Error', 'Failed to clear logs', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
    }
};
window.toggleAutoRefresh = () => {
    if (window.pclinkUI) {
        window.pclinkUI.autoRefreshEnabled = !window.pclinkUI.autoRefreshEnabled;
        const btn = document.getElementById('autoRefreshToggle');
        if (btn) btn.innerHTML = `<i data-feather="${window.pclinkUI.autoRefreshEnabled ? 'pause' : 'play'}" class="w-4 h-4"></i> <span class="hidden sm:inline">Auto</span>`;
        if (window.feather) feather.replace();
    }
};

window.saveSettings = async () => {
    const body = {
        auto_start: document.getElementById('autoStartCheckbox')?.checked,
        server_port: parseInt(document.getElementById('serverPortInput')?.value || 38080)
    };
    try {
        const res = await window.pclinkUI.webUICall('/settings/save', { method: 'POST', body: JSON.stringify(body) });
        if (res.ok) window.pclinkUI.showToast('Saved', 'Configuration updated', 'success');
    } catch (e) { }
};

window.changePassword = async () => {
    const cur = document.getElementById('currentPassword');
    const n1 = document.getElementById('newPassword');
    const n2 = document.getElementById('confirmNewPassword');
    if (!cur.value || !n1.value) return window.pclinkUI.showToast('Error', 'Missing fields', 'error');
    if (n1.value !== n2.value) return window.pclinkUI.showToast('Error', 'Passwords do not match', 'error');
    if (n1.value.length < 8) return window.pclinkUI.showToast('Error', 'Min 8 characters required', 'error');
    try {
        const res = await window.pclinkUI.webUICall('/auth/change-password', {
            method: 'POST',
            body: JSON.stringify({ old_password: cur.value, new_password: n1.value })
        });
        if (res.ok) {
            window.pclinkUI.showToast('Success', 'Password updated', 'success');
            cur.value = ''; n1.value = ''; n2.value = '';
        } else {
            const data = await res.json();
            window.pclinkUI.showToast('Error', data.detail || 'Failed to change password', 'error');
        }
    } catch (e) { window.pclinkUI.showToast('Error', 'Connection failed', 'error'); }
};

window.saveTransferSettings = async () => {
    const threshold = parseInt(document.getElementById('cleanupThresholdInput').value);
    if (isNaN(threshold) || threshold < 0) return window.pclinkUI.showToast('Error', 'Invalid day count', 'error');
    try {
        const res = await fetch('/transfers/cleanup/config', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ threshold }) });
        if (res.ok) { window.pclinkUI.showToast('Saved', 'Threshold value updated', 'success'); window.pclinkUI.loadTransferSettings(); }
    } catch (e) { }
};

window.executeCleanup = async () => {
    try {
        const res = await fetch('/transfers/cleanup/execute', { method: 'POST' });
        if (res.ok) { const data = await res.json(); window.pclinkUI.showToast('Done', `Cleaned ${data.cleaned.uploads + data.cleaned.downloads} sessions`, 'success'); window.pclinkUI.loadTransferSettings(); }
    } catch (e) { }
};

window.startRemoteServer = async () => { try { await fetch('/server/start', { method: 'POST' }); window.pclinkUI.showToast('Started', 'Remote API is starting...', 'success'); } catch (e) { } };
window.stopRemoteServer = async () => { try { await fetch('/server/stop', { method: 'POST' }); window.pclinkUI.showToast('Stopped', 'Remote API is stopping...', 'success'); } catch (e) { } };
window.restartRemoteServer = async () => { try { await fetch('/server/restart', { method: 'POST' }); window.pclinkUI.showToast('Restart', 'Rebooting service...', 'success'); } catch (e) { } };
window.shutdownServer = async () => { if (await window.confirmDialog('The server process will stop. You will lose access to this panel.', { title: 'Shutdown Server', danger: true })) await fetch('/server/shutdown', { method: 'POST' }); };

window.resetServerRequest = async function () {
    window.toggleResetModalCore(true);
};
