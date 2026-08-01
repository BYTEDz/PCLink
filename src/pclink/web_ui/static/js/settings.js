// static/js/settings.js
// Server Settings, Admin Password Changes, Preferences & Cleanup

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
