// static/js/devices.js

PCLinkWebUI.prototype.loadDevices = async function() {
    try {
        const res = await this.webUICall('/ui/devices');
        if (res.ok) {
            const data = await res.json();
            this.devices = data.devices || [];
            this.displayDevices();
            this.updatePhoneDeviceSelector();
            const dc = document.getElementById('deviceCount');
            if (dc) dc.textContent = this.devices.length;
            const ddc = document.getElementById('dashboardDeviceCount');
            if (ddc) ddc.textContent = this.devices.length;
        }
        await this.loadPendingRequests();
    } catch (e) {
        const el = document.getElementById('deviceList');
        if (el) el.innerHTML = '<div class="alert alert-error col-span-full">Failed to load devices</div>';
    }
};

PCLinkWebUI.prototype.displayDevices = function() {
    const el = document.getElementById('deviceList');
    if (!el) return;
    if (this.devices.length === 0) {
        el.innerHTML = '<div class="col-span-full py-10 text-center opacity-40 font-black uppercase text-[10px] tracking-widest bg-base-200 border border-dashed border-base-300 rounded-xl"><p>No mobile devices linked</p></div>';
        return;
    }
    el.innerHTML = this.devices.map(device => {
        const perms = Array.isArray(device.permissions) ? device.permissions : (device.permissions || "").split(',').filter(p => p.trim());
        const permCount = perms.length;
        const isApproved = device.is_approved !== false;
        const isOnline = device.is_online === true;

        const badgeClass = isApproved ? 'badge-ghost opacity-70' : 'badge-warning font-black';
        const badgeText = isApproved ? `${permCount} Perms` : 'Discovery Mode';

        const statusDot = isOnline
            ? '<span class="relative flex h-1.5 w-1.5"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75"></span><span class="relative inline-flex rounded-full h-1.5 w-1.5 bg-success"></span></span>'
            : '<span class="h-1.5 w-1.5 rounded-full bg-base-300"></span>';

        return `
        <div class="card bg-base-100 border ${isApproved ? 'border-base-300' : 'border-warning/30 bg-warning/5'} shadow-sm transition-all hover:border-primary">
            <div class="card-body p-5 flex-row items-center justify-between gap-2 overflow-hidden">
                <div class="flex items-center gap-4 overflow-hidden">
                    <div class="relative">
                        <div class="${isApproved ? (isOnline ? 'bg-success/10 text-success' : 'bg-primary/10 text-primary') : 'bg-warning/20 text-warning-content'} p-3 rounded-xl shrink-0">
                            <i data-feather="${isApproved ? 'smartphone' : 'radio'}" class="w-5 h-5"></i>
                        </div>
                        ${isApproved ? `<div class="absolute -top-1 -right-1 bg-base-100 p-0.5 rounded-full">${statusDot}</div>` : ''}
                    </div>
                    <div class="overflow-hidden">
                        <div class="flex items-center gap-2">
                            <h4 class="font-bold text-lg leading-tight truncate">${device.name}</h4>
                            ${isApproved ? `<span class="text-[9px] font-black uppercase ${isOnline ? 'text-success' : 'opacity-30'}">${isOnline ? 'Online' : 'Offline'}</span>` : ''}
                        </div>
                        <div class="flex items-center gap-2 mt-1">
                            <span class="text-[10px] font-bold uppercase opacity-50 tracking-wider truncate">${device.ip}</span>
                            <span class="badge badge-xs ${badgeClass}">${badgeText}</span>
                        </div>
                    </div>
                </div>
                <div class="flex gap-1 shrink-0">
                    ${isApproved ? `
                        <button class="btn btn-square btn-ghost btn-sm" onclick="openPermissions('${device.id}')" title="Manage Permissions"><i data-feather="shield" class="w-4"></i></button>
                        <button class="btn btn-square btn-ghost btn-sm text-error" onclick="banDevice('${device.id}')" title="Ban Hardware ID"><i data-feather="user-x" class="w-4"></i></button>
                        <button class="btn btn-square btn-ghost btn-sm text-error" onclick="revokeDevice('${device.id}')" title="Revoke Session"><i data-feather="trash-2" class="w-4"></i></button>
                    ` : `
                        <div class="tooltip tooltip-left" data-tip="Device seen on network but not paired">
                            <i data-feather="info" class="w-4 opacity-40 mr-2"></i>
                        </div>
                    `}
                </div>
            </div>
        </div>`;
    }).join('');
    if (window.feather) feather.replace();
};

PCLinkWebUI.prototype.loadPendingRequests = async function() {
    try {
        const res = await this.webUICall('/ui/pairing/list');
        if (res.ok) {
            const data = await res.json();
            const container = document.getElementById('pendingRequests');
            if (!container) return;
            const requests = data.requests || [];
            if (requests.length === 0) {
                container.innerHTML = '<p class="opacity-50 text-sm font-bold">No pending access requests</p>';
                return;
            }
            container.innerHTML = requests.map(req => `
                <div class="alert bg-warning/10 border border-warning/20 flex-col sm:flex-row justify-between shadow-sm gap-4 items-start sm:items-center">
                    <div class="flex items-center gap-3">
                        <i data-feather="user-plus" class="text-warning"></i>
                        <div>
                            <h4 class="font-bold text-sm leading-tight tracking-tight">${req.device_name}</h4>
                            <p class="text-[10px] opacity-60">IP: ${req.ip} &bull; ${req.platform}</p>
                        </div>
                    </div>
                    <div class="flex gap-2 w-full sm:w-auto font-black">
                        <button class="btn btn-sm btn-primary flex-1 sm:flex-none text-white shadow-md uppercase text-[10px]" onclick="approvePairingRequest('${req.pairing_id}')">Approve</button>
                        <button class="btn btn-sm btn-ghost flex-1 sm:flex-none uppercase text-[10px]" onclick="denyPairingRequest('${req.pairing_id}')">Deny</button>
                    </div>
                </div>
            `).join('');
            if (window.feather) feather.replace();
        }
    } catch (error) { }
};

PCLinkWebUI.prototype.loadBlacklist = async function() {
    const container = document.getElementById('blacklistContainer');
    if (!container) return;
    try {
        const res = await this.webUICall('/ui/devices/blacklist');
        if (res.ok) {
            const data = await res.json();
            this.displayBlacklist(data.blacklist || []);
        } else {
            container.innerHTML = '<p class="opacity-50 text-xs font-bold py-4 text-center">Failed to load blacklist</p>';
        }
    } catch (e) {
        container.innerHTML = '<div class="alert alert-error text-xs">Connection error</div>';
    }
};

PCLinkWebUI.prototype.displayBlacklist = function(blacklist) {
    const container = document.getElementById('blacklistContainer');
    if (!container) return;
    if (blacklist.length === 0) {
        container.innerHTML = '<p class="opacity-50 text-xs font-bold py-4 text-center">Blacklist is empty</p>';
        return;
    }
    container.innerHTML = blacklist.map(item => `
        <div class="flex items-center justify-between p-3 bg-base-200 rounded-lg border border-base-300">
            <div class="overflow-hidden">
                <p class="text-xs font-mono font-black truncate">${item.hardware_id}</p>
                <p class="text-[9px] opacity-50 uppercase font-bold">Banned on: ${new Date(item.banned_at).toLocaleDateString()}</p>
            </div>
            <button class="btn btn-xs btn-ghost text-success font-black" onclick="window.unbanHardware('${item.hardware_id}')">Unban</button>
        </div>
    `).join('');
    if (window.feather) feather.replace();
};

PCLinkWebUI.prototype.banDevice = async function(deviceId) {
    if (!await window.confirmDialog('Ban this device? It will be disconnected and cannot re-pair.', { title: 'Ban Hardware ID', danger: true })) return;
    try {
        const res = await this.webUICall(`/ui/devices/ban?device_id=${deviceId}`, { method: 'POST' });
        if (res.ok) {
            this.showToast('Banned', 'Hardware ID added to blacklist', 'success');
            this.loadDevices();
            this.loadBlacklist();
        }
    } catch (e) {
        this.showToast('Error', 'Failed to ban device', 'error');
    }
};

PCLinkWebUI.prototype.unbanHardware = async function(hardwareId) {
    if (!await window.confirmDialog(`Unban hardware ID: ${hardwareId}?`, { title: 'Unban Hardware' })) return;
    try {
        const res = await this.webUICall(`/ui/devices/unban?hardware_id=${hardwareId}`, { method: 'POST' });
        if (res.ok) {
            this.showToast('Unbanned', 'Hardware ID removed from blacklist', 'success');
            this.loadBlacklist();
        }
    } catch (e) {
        this.showToast('Error', 'Failed to unban hardware', 'error');
    }
};

PCLinkWebUI.prototype.loadDefaultPermissions = async function() {
    try {
        const res = await this.webUICall('/ui/devices/settings/defaults/permissions');
        if (res.ok) {
            const data = await res.json();
            const container = document.getElementById('defaultPermsGrid');
            if (!container) return;

            const perms = data.permissions || [];
            container.innerHTML = Object.entries(PERMISSION_MAP).map(([key, info]) => `
                <label class="cursor-pointer label border border-base-300 rounded-lg p-3 hover:bg-base-200 transition-colors flex items-center justify-between gap-3">
                    <div class="flex flex-col text-left">
                        <span class="label-text font-black text-xs uppercase tracking-tight">${info.title}</span>
                        <span class="text-[9px] opacity-50 font-bold uppercase tracking-tighter mt-0.5">${info.desc}</span>
                </div>
                <input type="checkbox" class="toggle toggle-sm toggle-primary" data-perm="${key}" ${perms.includes(key) ? 'checked' : ''} />
            </label>
            `).join('');
        }
    } catch (e) {
        console.error("Failed to load default permissions:", e);
    }
};

// Global Device Helpers
window.approvePairingRequest = (id) => { if (window.pclinkUI.websocket?.readyState === WebSocket.OPEN) { window.pclinkUI.websocket.send(JSON.stringify({ type: 'approve_pair', pairing_id: id })); setTimeout(() => window.pclinkUI.loadPendingRequests(), 500); } };
window.denyPairingRequest = (id) => { if (window.pclinkUI.websocket?.readyState === WebSocket.OPEN) { window.pclinkUI.websocket.send(JSON.stringify({ type: 'deny_pair', pairing_id: id })); setTimeout(() => window.pclinkUI.loadPendingRequests(), 500); } };
window.approvePairing = async () => { if (!window.pclinkUI?.pendingPairingRequest) return; await window.pclinkUI.webUICall('/ui/pairing/approve', { method: 'POST', body: JSON.stringify({ pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id, approved: true }) }); document.getElementById('pairingModal').close(); window.pclinkUI.loadDevices(); };
window.denyPairing = async () => { if (!window.pclinkUI?.pendingPairingRequest) return; await window.pclinkUI.webUICall('/ui/pairing/deny', { method: 'POST', body: JSON.stringify({ pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id, approved: false }) }); document.getElementById('pairingModal').close(); };
window.banDevice = async (id) => { if (window.pclinkUI) await window.pclinkUI.banDevice(id); };
window.unbanHardware = async (hwid) => { if (window.pclinkUI) await window.pclinkUI.unbanHardware(hwid); };
window.loadBlacklist = async () => { if (window.pclinkUI) await window.pclinkUI.loadBlacklist(); };
window.revokeDevice = async (id) => { if (await window.confirmDialog('Revoke this device session? It will be disconnected immediately.', { title: 'Revoke Access', danger: true })) { await window.pclinkUI.webUICall(`/ui/devices/revoke?device_id=${id}`, { method: 'POST' }); window.pclinkUI.loadDevices(); } };
window.removeAllDevices = async () => { if (await window.confirmDialog('Remove ALL paired devices? They will need to re-pair to reconnect.', { title: 'Clear Fleet', danger: true })) { await window.pclinkUI.webUICall('/ui/devices/remove-all', { method: 'POST' }); window.pclinkUI.loadDevices(); } };

window.openPermissions = async function (deviceId) {
    const device = window.pclinkUI.devices.find(d => d.id === deviceId);
    if (!device) return;
    const title = `<i data-feather="shield" class="text-primary w-4"></i> Access Control — ${device.name}`;
    const body = `
        <div class="space-y-6">
            <div class="bg-base-200/50 p-4 rounded-xl border border-base-300/50">
                <span class="text-[10px] font-black uppercase opacity-40 mb-3 block tracking-widest">Quick Templates</span>
                <div class="flex flex-wrap gap-2">
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold hover:btn-primary" onclick="window.applyPermissionTemplate('Admin', 'permList')">Admin</button>
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold hover:btn-primary" onclick="window.applyPermissionTemplate('Viewer', 'permList')">Viewer</button>
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold hover:btn-primary" onclick="window.applyPermissionTemplate('Media', 'permList')">Media</button>
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold hover:btn-primary" onclick="window.applyPermissionTemplate('Remote', 'permList')">Remote</button>
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold hover:btn-error" onclick="window.applyPermissionTemplate('None', 'permList')">None</button>
                </div>
            </div>
            <div id="permList" class="grid grid-cols-1 gap-2">
                ${Object.entries(PERMISSION_MAP).map(([key, info]) => {
                    const perms = (device.permissions || "").split(',').map(s => s.trim());
                    return `
                        <label class="cursor-pointer label border border-base-300 rounded-lg p-3 hover:bg-base-200 transition-colors flex items-center justify-between gap-3">
                            <div class="flex flex-col text-left">
                                <span class="label-text font-black text-xs uppercase tracking-tight">${info.title}</span>
                                <span class="text-[9px] opacity-50 font-bold uppercase tracking-tighter mt-0.5">${info.desc}</span>
                            </div>
                            <input type="checkbox" class="toggle toggle-sm toggle-primary" data-perm="${key}" ${perms.includes(key) ? 'checked' : ''} onchange="window.updateDevicePerm('${deviceId}', '${key}', this.checked)" />
                        </label>
                    `;
                }).join('')}
            </div>
        </div>
    `;
    const footer = `
        <button class="btn btn-sm btn-ghost font-bold text-xs opacity-40 hover:opacity-100" onclick="window.saveCurrentAsTemplate('permList')">Save as Template</button>
        <button class="btn btn-sm btn-primary px-6 font-bold uppercase text-xs" onclick="window.closeSidePanel()">Done</button>
    `;
    window.openSidePanel(title, body, footer);
};

window.applyPermissionTemplate = function (tplName, containerId) {
    const defaultTemplates = {
        'Admin': ['files_browse', 'files_download', 'files_upload', 'files_delete', 'processes', 'power', 'info', 'mouse', 'keyboard', 'media', 'volume', 'terminal', 'macros', 'extensions', 'apps', 'clipboard', 'screenshot', 'command', 'wol'],
        'Viewer': ['files_browse', 'info', 'apps'],
        'Media': ['media', 'volume', 'info', 'apps'],
        'Remote': ['mouse', 'keyboard', 'screenshot', 'info', 'volume'],
        'None': []
    };
    const customTemplates = JSON.parse(localStorage.getItem('pclink_custom_templates') || '{}');
    const tpl = defaultTemplates[tplName] || customTemplates[tplName] || [];
    const container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        const pid = cb.getAttribute('data-perm');
        const state = tpl.includes(pid);
        if (cb.checked !== state) {
            cb.checked = state;
            if (cb.getAttribute('onchange')) cb.dispatchEvent(new Event('change'));
        }
    });
};

window.saveCurrentAsTemplate = function (containerId) {
    const name = prompt("Enter Template Name:");
    if (!name) return;
    const container = document.getElementById(containerId);
    const checked = Array.from(container.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.getAttribute('data-perm'));
    const custom = JSON.parse(localStorage.getItem('pclink_custom_templates') || '{}');
    custom[name] = checked;
    localStorage.setItem('pclink_custom_templates', JSON.stringify(custom));
    window.renderCustomTemplates();
    window.pclinkUI.showToast('Saved', `Template '${name}' stored`, 'success');
};

window.renderCustomTemplates = function () {
    const custom = JSON.parse(localStorage.getItem('pclink_custom_templates') || '{}');
    const containers = ['customPermTemplates', 'customPolicyTemplates'];
    containers.forEach(cid => {
        const el = document.getElementById(cid);
        if (!el) return;
        const targetGrid = cid === 'customPermTemplates' ? 'permList' : 'defaultPermsGrid';
        el.innerHTML = Object.keys(custom).map(name => `
            <div class="flex items-center gap-1 animate-in fade-in slide-in-from-left-2 duration-300">
                <button class="btn btn-xs btn-primary font-bold text-xs" onclick="applyPermissionTemplate('${name}', '${targetGrid}')">${name}</button>
                <button class="btn btn-xs btn-ghost btn-square text-error w-6 h-6 min-h-0" onclick="window.deleteTemplate('${name}')"><i data-feather="x" class="w-3"></i></button>
            </div>
        `).join('');
    });
    if (window.feather) feather.replace();
};

window.deleteTemplate = async function (name) {
    if (!await window.confirmDialog(`Delete template '${name}'?`, { title: 'Delete Template', danger: true })) return;
    const custom = JSON.parse(localStorage.getItem('pclink_custom_templates') || '{}');
    delete custom[name];
    localStorage.setItem('pclink_custom_templates', JSON.stringify(custom));
    window.renderCustomTemplates();
};

window.updateDevicePerm = async function (deviceId, perm, enabled) {
    try {
        await window.pclinkUI.webUICall(`/ui/devices/${deviceId}/permissions`, {
            method: 'POST',
            body: JSON.stringify({ permission: perm, enabled: enabled })
        });
        window.pclinkUI.loadDevices();
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to update permission', 'error');
    }
};

window.saveDefaultPermissions = async function () {
    try {
        const checkboxes = document.querySelectorAll('#defaultPermsGrid input[type="checkbox"]');
        const perms = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.getAttribute('data-perm'));
        const res = await window.pclinkUI.webUICall('/ui/devices/settings/defaults/permissions', {
            method: 'POST',
            body: JSON.stringify({ permissions: perms })
        });
        if (res.ok) window.pclinkUI.showToast('Success', 'Default policy updated', 'success');
    } catch (e) { window.pclinkUI.showToast('Error', 'Failed to update policy', 'error'); }
};

window.openPairingPanel = async function() {
    const title = `<i data-feather="plus" class="text-primary w-4"></i> Pair New Device`;
    const body = `
        <div class="flex flex-col items-center text-center space-y-6">
            <div class="bg-base-200/50 p-6 rounded-2xl border border-base-300/50 w-full">
                <p class="text-sm opacity-70 mb-6">Scan this QR code with the PCLink mobile app to link your device.</p>
                <div id="sidePanelQRCode" class="bg-white p-4 rounded-xl inline-block shadow-lg mx-auto overflow-hidden">
                    <div class="w-[220px] h-[220px] flex items-center justify-center">
                        <span class="loading loading-spinner text-primary"></span>
                    </div>
                </div>
                <div class="mt-6 flex justify-center gap-2">
                    <button class="btn btn-sm btn-ghost border-base-300 font-bold" onclick="window.refreshPairingQR()"><i data-feather="refresh-cw" class="w-3"></i> Refresh Code</button>
                </div>
            </div>

            <div class="bg-base-100 p-6 rounded-2xl border border-base-300 w-full text-left">
                <h4 class="font-black uppercase text-[10px] opacity-40 tracking-[0.2em] mb-4">Quick Setup Guide</h4>
                <ul class="space-y-4">
                    <li class="flex gap-4 items-start">
                        <span class="bg-primary/10 text-primary w-6 h-6 rounded-lg flex items-center justify-center shrink-0 font-black text-xs">1</span>
                        <p class="text-xs opacity-70 leading-relaxed">Install <strong>PCLink Companion</strong> on your Android/iOS device.</p>
                    </li>
                    <li class="flex gap-4 items-start">
                        <span class="bg-primary/10 text-primary w-6 h-6 rounded-lg flex items-center justify-center shrink-0 font-black text-xs">2</span>
                        <p class="text-xs opacity-70 leading-relaxed">Open the app and select <strong>"Add Computer"</strong>.</p>
                    </li>
                    <li class="flex gap-4 items-start">
                        <span class="bg-primary/10 text-primary w-6 h-6 rounded-lg flex items-center justify-center shrink-0 font-black text-xs">3</span>
                        <p class="text-xs opacity-70 leading-relaxed">Scan the code above and <strong>Approve</strong> the request here.</p>
                    </li>
                </ul>
            </div>
        </div>
    `;
    const footer = `<button class="btn btn-sm btn-primary w-full font-bold uppercase tracking-widest text-[10px]" onclick="window.closeSidePanel()">Done</button>`;

    window.openSidePanel(title, body, footer);
    // Give DOM a moment to render the container
    setTimeout(() => window.refreshPairingQR(), 150);
};

window.refreshPairingQR = async function() {
    const container = document.getElementById('sidePanelQRCode');
    if (!container) return;
    try {
        const data = await window.pclinkUI.apiCall('/qr-payload');
        container.innerHTML = '';
        if (typeof QRCode !== 'undefined') {
            new QRCode(container, {
                text: JSON.stringify(data),
                width: 220,
                height: 220,
                colorDark : "#000000",
                colorLight : "#ffffff",
                correctLevel : QRCode.CorrectLevel.H
            });
        }
    } catch (e) {
        container.innerHTML = '<div class="alert alert-error text-[10px]">QR Generation Failed</div>';
    }
};
