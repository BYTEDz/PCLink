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
        feather.replace();
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
            if (window.feather) feather.replace();
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
        const res = await this.webUICall('/logs');
        if (res.ok) { const data = await res.json(); content.textContent = data.logs || '--- clear ---'; if (isAtBottom) container.scrollTop = container.scrollHeight; }
    } catch (e) { }
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
            } else if (data.type === 'notification') {
                const title = data.data.title || "";
                if (title.includes("Connected") && !this.notificationSettings.deviceConnect) return;
                if (title.includes("Disconnected") && !this.notificationSettings.deviceDisconnect) return;
                this.showToast(data.data.title, data.data.message || data.data.body);
            }
            else if (data.type === 'server_status') { this.updateConnectionStatus(); }
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

// clear system logs functon
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

window.toggleResetModal = function (show) {
    const modal = document.getElementById('resetModal');
    if (!modal) return;
    if (show) {
        modal.showModal ? modal.showModal() : modal.classList.add('modal-open');
        fetchConfigPath();
    } else {
        modal.close ? modal.close() : modal.classList.remove('modal-open');
    }
};

async function fetchConfigPath() {
    try {
        const response = await fetch('/auth/status');
        if (response.ok) {
            const data = await response.json();
            const el = document.getElementById('p_dataDir');
            if (el) el.innerText = data.data_path || "~/.config/pclink";
        }
    } catch (e) {
        const el = document.getElementById('p_dataDir');
        if (el) el.innerText = "Check ~/.config/pclink";
    }
}

window.openConfigFolder = async function () {
    try {
        const response = await fetch('/open-data-dir', { method: 'POST', credentials: 'include' });
        if (!response.ok) {
            if (response.status === 403) alert("Opening folder only works if you are on the host machine (localhost).");
            else alert("Failed to open folder (404/500).");
        }
    } catch (e) {
        alert("Error connecting to server.");
    }
};

window.resetServerRequest = async function () {
    window.toggleResetModal(true);
};

window.handleFactoryReset = async function (event) {
    event.preventDefault();
    const password = document.getElementById('resetPassword').value;
    const wipeAuth = document.getElementById('wipeAuthCheckbox').checked;
    const wipeExtensions = document.getElementById('wipeExtensionsCheckbox')?.checked || false;

    if (!await window.confirmDialog("FINAL WARNING: This will PERMANENTLY delete server data. Type 'YES' to confirm you understand the risks.", { title: 'Factory Reset Security Check', danger: true, requiredWord: 'YES' })) {
        return;
    }

    const btn = document.getElementById('resetButton');
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "RESETTING...";

    try {
        const response = await fetch('/auth/factory-reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password, wipe_auth: wipeAuth, wipe_extensions: wipeExtensions }),
            credentials: 'include'
        });

        if (response.ok) {
            localStorage.clear();
            document.getElementById('resetSuccessOverlay').classList.remove('hidden');
            if (window.feather) feather.replace();
            if (window.toggleResetModal) window.toggleResetModal(false);
        } else {
            const data = await response.json();
            alert("Reset failed: " + (data.detail || "Unknown error"));
            btn.disabled = false;
            btn.innerText = originalText;
        }
    } catch (e) {
        localStorage.clear();
        document.getElementById('resetSuccessOverlay').classList.remove('hidden');
        if (window.feather) feather.replace();
        if (window.toggleResetModal) window.toggleResetModal(false);
    }
};
