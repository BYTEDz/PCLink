// static/js/system.js
// Server Status, Daemon Controls, Services & System Logs Manager

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

window.startRemoteServer = async () => { try { await fetch('/server/start', { method: 'POST' }); window.pclinkUI.showToast('Started', 'Remote API is starting...', 'success'); } catch (e) { } };
window.stopRemoteServer = async () => { try { await fetch('/server/stop', { method: 'POST' }); window.pclinkUI.showToast('Stopped', 'Remote API is stopping...', 'success'); } catch (e) { } };
window.restartRemoteServer = async () => { try { await fetch('/server/restart', { method: 'POST' }); window.pclinkUI.showToast('Restart', 'Rebooting service...', 'success'); } catch (e) { } };
window.shutdownServer = async () => { if (await window.confirmDialog('The server process will stop. You will lose access to this panel.', { title: 'Shutdown Server', danger: true })) await fetch('/server/shutdown', { method: 'POST' }); };

window.resetServerRequest = async function () {
    window.toggleResetModalCore(true);
};
