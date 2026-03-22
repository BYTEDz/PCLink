const PERMISSION_MAP = {
    files_browse: { title: "File Browser", desc: "Browse system files and view thumbnails" },
    files_download: { title: "File Download", desc: "Download files to the connected device" },
    files_upload: { title: "File Upload", desc: "Upload files from the connected device" },
    files_delete: { title: "File Deletion", desc: "Delete files and folders on the system" },
    processes: { title: "Processes Management", desc: "View and manage running system processes" },
    power: { title: "Power Control", desc: "Shutdown, restart, or lock the system" },
    info: { title: "System Status", desc: "Monitor battery and hardware status" },
    mouse: { title: "Remote Mouse", desc: "Control system cursor and clicks" },
    keyboard: { title: "Remote Type", desc: "Send keyboard inputs and shortcuts" },
    media: { title: "Media Control", desc: "Control playback and see media info" },
    volume: { title: "System Volume", desc: "Adjust master volume and mute status" },
    terminal: { title: "Terminal Access", desc: "Full shell access (High Risk)" },
    macros: { title: "Automation Macros", desc: "Execute automated task scripts" },
    extensions: { title: "Extensions", desc: "Manage and run server extensions" },
    apps: { title: "Applications", desc: "View and launch installed applications" },
    clipboard: { title: "Clipboard Sync", desc: "Read and write system clipboard" },
    screenshot: { title: "Screen Capture", desc: "Capture system screen snapshots" },
    command: { title: "Shell Command", desc: "Run detached shell commands" },
    wol: { title: "Wake-on-LAN", desc: "Check WOL status and MAC address" }
};

class PCLinkWebUI {
    constructor() {
        this.apiKey = null;
        this.apiKeyVisible = false;
        this.baseUrl = window.location.origin;
        this.devices = [];
        this.websocket = null;
        this.serverStartTime = Date.now();
        this.currentPhonePath = '/';
        this.notificationSettings = { deviceConnect: true, deviceDisconnect: true, pairingRequest: true, updates: true };
        this.phoneNavHistory = ['/'];
        this.phoneHistoryIndex = 0;
        this.phoneSearchQuery = '';
        this.phoneSortMode = 'name_asc';
        this.phoneShowHidden = false;
        this.phoneSelectedItems = new Set();
        this.phoneFileItems = [];
        this.currentPhoneDeviceId = null;
        this.autoRefreshEnabled = true;
        this.lastActivity = Date.now();
        this.init();
    }

    async init() {
        await this.loadSettings();
        const yearEl = document.getElementById('copyrightYear');
        if (yearEl) yearEl.textContent = new Date().getFullYear();
        this.setupEventListeners();
        await this.loadDevices();
        await this.loadServices();
        await this.loadDefaultPermissions();
        this.updateConnectionStatus();
        this.loadServerStatus();
        this.connectWebSocket();
        this.switchTab(this.getCurrentTab());

        setInterval(() => {
            if (!this.autoRefreshEnabled) return;
            this.updateConnectionStatus();
            const activeTab = this.getCurrentTab();
            if (activeTab === 'dashboard') { this.updateActivity(); this.updateServerStatus(); }
            else if (['devices', 'phone-files'].includes(activeTab)) { this.loadDevices(); }
            else if (activeTab === 'logs') { this.loadLogs(); }
        }, 5000);

        setInterval(() => {
            const lastDismissed = localStorage.getItem('updateDismissed');
            if (!lastDismissed || (Date.now() - parseInt(lastDismissed)) > 86400000) {
                window.checkForUpdates();
            }
        }, 1800000);

        setTimeout(() => window.checkForUpdates(), 5000);
        setTimeout(() => window.loadNotificationSettings(), 1000);
        setTimeout(() => window.renderCustomTemplates(), 500);

        if (window.feather) feather.replace();
    }

    setupEventListeners() {
        document.querySelectorAll('.sidebar-nav').forEach(nav => {
            nav.addEventListener('click', (e) => {
                const btn = e.target.closest('.nav-item');
                if (btn) this.switchTab(btn.dataset.tab);
            });
        });

        ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart'].forEach(type => {
            document.addEventListener(type, () => { this.lastActivity = Date.now(); }, { passive: true });
        });

        setInterval(async () => {
            if (Date.now() - this.lastActivity > 900000) { // 15 Minutes
                await fetch('/auth/logout', { method: 'POST' });
                window.location.reload();
            }
        }, 60000);

        window.addEventListener('focus', () => this.updateConnectionStatus());
        document.addEventListener('visibilitychange', () => { if (!document.hidden) this.updateConnectionStatus(); });
        window.addEventListener('online', () => this.updateConnectionStatus());
    }

    getCurrentTab() {
        const activeBtn = document.querySelector('.nav-item.active');
        return activeBtn ? activeBtn.dataset.tab : 'dashboard';
    }

    switchTab(tabName) {
        if (!tabName) return;
        document.querySelectorAll('.nav-item').forEach(btn => {
            if (btn.dataset.tab === tabName) {
                btn.classList.add('active', 'btn-primary');
                btn.classList.remove('btn-ghost', 'opacity-70');
            } else {
                btn.classList.remove('active', 'btn-primary');
                btn.classList.add('btn-ghost');
                if (['guide', 'about'].includes(btn.dataset.tab)) btn.classList.add('opacity-70');
            }
        });

        document.querySelectorAll('.tab-content').forEach(content => {
            if (content.id === tabName) content.classList.add('active');
            else content.classList.remove('active');
        });
        this.loadTabData(tabName);
    }

    async loadTabData(tabName) {
        switch (tabName) {
            case 'dashboard': await this.loadServerStatus(); break;
            case 'devices': await this.loadDevices(); break;
            case 'settings': await this.loadSettings(); break;
            case 'logs': await this.loadLogs(); break;
            case 'services': await this.loadServices(); await this.loadBlacklist(); break;
            case 'phone-files': await this.loadDevices(); await this.loadPhoneFiles(this.currentPhonePath); break;
        }
        if (window.feather) feather.replace();
    }

    async loadApiKey() {
        try {
            const res = await fetch('/qr-payload');
            if (res.ok) {
                const data = await res.json();
                this.apiKey = data.apiKey;
                this.updateApiKeyDisplay();
            }
        } catch (e) { }
    }

    updateApiKeyDisplay() {
        const el = document.getElementById('apiKeyDisplay');
        const eye = document.getElementById('apiKeyEye');
        if (!el) return;
        el.type = this.apiKeyVisible ? "text" : "password";
        el.value = this.apiKey || "••••••••••••";
        if (eye && window.feather) {
            eye.setAttribute('data-feather', this.apiKeyVisible ? 'eye-off' : 'eye');
            feather.replace();
        }
    }

    getHeaders() { return { 'Content-Type': 'application/json', ...(this.apiKey && { 'X-API-Key': this.apiKey }) }; }
    getWebHeaders() { return { 'Content-Type': 'application/json' }; }
    async webUICall(endpoint, options = {}) { return fetch(`${this.baseUrl}${endpoint}`, { ...options, headers: { ...this.getWebHeaders(), ...options.headers }, credentials: 'include' }); }
    async apiCall(endpoint, options = {}) { const r = await fetch(`${this.baseUrl}${endpoint}`, { ...options, headers: { ...this.getHeaders(), ...options.headers } }); if (!r.ok) throw new Error(`HTTP ${r.status}`); return await r.json(); }

    updateConnectionStatus() {
        const dot = document.querySelector('.status-dot');
        const text = document.getElementById('serverStatusText');
        if (!dot || !text) return;
        fetch('/status', { method: 'GET', cache: 'no-cache' }).then(res => {
            if (res.ok) { dot.className = 'status-dot w-2 h-2 rounded-full bg-success'; text.textContent = 'Online'; }
            else throw new Error();
        }).catch(() => { dot.className = 'status-dot w-2 h-2 rounded-full bg-error'; text.textContent = 'Offline'; });
    }

    async loadServerStatus() {
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
    }

    updateActivity() {
        const el = document.getElementById('serverUptime');
        if (el) el.textContent = this.formatUptime(Date.now() - this.serverStartTime);
    }

    async updateServerStatus() {
        const portEl = document.getElementById('serverPort');
        const verEl = document.getElementById('serverVersion');
        if (portEl) portEl.textContent = `Port: ${window.location.port || '38080'}`;
        try {
            const res = await fetch('/status');
            if (res.ok) {
                const data = await res.json();
                if (verEl && data.version) verEl.textContent = `v${data.version}`;
            }
        } catch (e) { }
    }

    async loadDevices() {
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
    }

    displayDevices() {
        const el = document.getElementById('deviceList');
        if (!el) return;
        if (this.devices.length === 0) {
            el.innerHTML = '<div class="col-span-full py-10 text-center opacity-40 font-black uppercase text-[10px] tracking-widest bg-base-200 border border-dashed border-base-300 rounded-xl"><p>No mobile devices linked</p></div>';
            return;
        }
        el.innerHTML = this.devices.map(device => {
            const perms = Array.isArray(device.permissions) ? device.permissions : (device.permissions || "").split(',').filter(p => p.trim());
            const permCount = perms.length;

            return `
            <div class="card bg-base-100 border border-base-300 shadow-sm transition-all hover:border-primary">
                <div class="card-body p-5 flex-row items-center justify-between gap-2 overflow-hidden">
                    <div class="flex items-center gap-4 overflow-hidden">
                        <div class="bg-primary/10 text-primary p-3 rounded-xl shrink-0"><i data-feather="smartphone" class="w-5 h-5"></i></div>
                        <div class="overflow-hidden">
                            <h4 class="font-bold text-lg leading-tight truncate">${device.name}</h4>
                            <div class="flex items-center gap-2 mt-1">
                                <span class="text-[10px] font-bold uppercase opacity-50 tracking-wider truncate">${device.ip}</span>
                                <span class="badge badge-xs badge-ghost opacity-70">${permCount} Perms</span>
                            </div>
                        </div>
                    </div>
                    <div class="flex gap-1 shrink-0">
                        <button class="btn btn-square btn-ghost btn-sm" onclick="openPermissions('${device.id}')" title="Manage Permissions"><i data-feather="shield" class="w-4"></i></button>
                        <button class="btn btn-square btn-ghost btn-sm text-error" onclick="banDevice('${device.id}')" title="Ban Hardware ID"><i data-feather="user-x" class="w-4"></i></button>
                        <button class="btn btn-square btn-ghost btn-sm text-error" onclick="revokeDevice('${device.id}')" title="Revoke Session"><i data-feather="trash-2" class="w-4"></i></button>
                    </div>
                </div>
            </div>`;
        }).join('');
        if (window.feather) feather.replace();
    }

    async loadPendingRequests() {
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
    }

    async loadServices() {
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
        } catch (e) {
            console.error("Failed to load global services:", e);
        }
    }

    async loadBlacklist() {
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
    }

    displayBlacklist(blacklist) {
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
    }

    async banDevice(deviceId) {
        if (!confirm('Ban this device hardware? It will be disconnected and cannot re-pair.')) return;
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
    }

    async unbanHardware(hardwareId) {
        if (!confirm(`Unban hardware ID ${hardwareId}?`)) return;
        try {
            const res = await this.webUICall(`/ui/devices/unban?hardware_id=${hardwareId}`, { method: 'POST' });
            if (res.ok) {
                this.showToast('Unbanned', 'Hardware ID removed from blacklist', 'success');
                this.loadBlacklist();
            }
        } catch (e) {
            this.showToast('Error', 'Failed to unban hardware', 'error');
        }
    }

    async loadDefaultPermissions() {
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
    }

    async toggleService(serviceId, enabled) {
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
    }

    updatePhoneDeviceSelector() {
        const selector = document.getElementById('phoneDeviceSelector');
        if (!selector) return;
        const currentSelection = this.currentPhoneDeviceId;
        selector.innerHTML = '<option value="">Select Device...</option>';
        this.devices.forEach(device => {
            const option = document.createElement('option');
            option.value = device.id;
            option.textContent = `${device.name} (${device.ip})`;
            if (device.id === currentSelection) option.selected = true;
            selector.appendChild(option);
        });
        if (!this.currentPhoneDeviceId && this.devices.length > 0) {
            this.currentPhoneDeviceId = this.devices[0].id;
            selector.value = this.currentPhoneDeviceId;
        }
    }

    async handlePhoneDeviceChange(deviceId) {
        this.currentPhoneDeviceId = deviceId;
        this.currentPhonePath = '/';
        await this.loadPhoneFiles('/');
    }

    async loadPhoneFiles(path) {
        const breadcrumb = document.getElementById('phoneBreadcrumb');
        const backBtn = document.getElementById('phoneBackBtn');
        const forwardBtn = document.getElementById('phoneForwardBtn');
        const container = document.getElementById('phoneFileList');
        if (!container) return;

        const cleanPath = path.startsWith('/') ? path : '/' + path;
        if (breadcrumb) breadcrumb.textContent = `Path: ${cleanPath}`;
        if (backBtn) backBtn.disabled = this.phoneHistoryIndex <= 0;
        if (forwardBtn) forwardBtn.disabled = this.phoneHistoryIndex >= this.phoneNavHistory.length - 1;

        try {
            let url = `/phone/files/.browse${cleanPath}`;
            if (this.currentPhoneDeviceId) url += `?device_id=${encodeURIComponent(this.currentPhoneDeviceId)}`;
            const res = await fetch(url, { headers: this.getHeaders() });
            if (res.ok) {
                const data = await res.json();
                this.phoneFileItems = data.items || [];
                this.phoneIsReadOnly = data.readOnly || false;
                this.updatePhoneUIPermissions();
                this.displayPhoneFiles();
            } else {
                container.innerHTML = `<div class="alert alert-warning m-4 text-xs font-bold uppercase">WebDAV connection failed on phone</div>`;
            }
        } catch (e) {
            container.innerHTML = `<div class="alert alert-error m-4 text-xs">Error: ${e.message}</div>`;
        }
    }

    displayPhoneFiles() {
        const listContainer = document.getElementById('phoneFileList');
        if (!listContainer) return;
        let filtered = this.phoneFileItems.filter(item => {
            if (!this.phoneShowHidden && item.name.startsWith('.')) return false;
            if (this.phoneSearchQuery && !item.name.toLowerCase().includes(this.phoneSearchQuery.toLowerCase())) return false;
            return true;
        });
        filtered.sort((a, b) => {
            if (a.isDir && !b.isDir) return -1;
            if (!a.isDir && b.isDir) return 1;
            const [field, direction] = this.phoneSortMode.split('_');
            let comparison = 0;
            if (field === 'name') comparison = a.name.localeCompare(b.name);
            if (field === 'size') comparison = (a.size || 0) - (b.size || 0);
            if (field === 'date') comparison = new Date(a.modified) - new Date(b.modified);
            return direction === 'asc' ? comparison : -comparison;
        });
        if (filtered.length === 0) {
            listContainer.innerHTML = '<div class="py-16 text-center opacity-40 font-bold uppercase tracking-widest text-xs">No matching files found</div>';
            if (window.feather) feather.replace();
            return;
        }
        listContainer.innerHTML = filtered.map(item => {
            const isSelected = this.phoneSelectedItems.has(item.path);
            return `
                <div class="flex items-center p-3 border-b border-base-300 hover:bg-base-200 cursor-pointer group transition-colors ${isSelected ? 'bg-primary/10 border-l-2 border-l-primary shadow-inner' : 'border-l-2 border-l-transparent'}" onclick="handleFileItemClick(event, '${item.path}', ${item.isDir})">
                    <input type="checkbox" class="checkbox checkbox-sm checkbox-primary mr-4 shrink-0" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleItemSelection('${item.path}')">
                    <div class="mr-4 shrink-0 ${item.isDir ? 'text-primary' : 'text-base-content/40'}"><i data-feather="${item.isDir ? 'folder' : 'file'}" class="w-5 h-5"></i></div>
                    <div class="flex-1 overflow-hidden pr-2">
                        <p class="text-sm font-bold truncate group-hover:text-primary transition-colors">${item.name}</p>
                        <p class="text-[10px] font-bold uppercase opacity-50 tracking-wider truncate">${item.isDir ? 'Directory' : this.formatFileSize(item.size)} &bull; ${new Date(item.modified).toLocaleDateString()}</p>
                    </div>
                    <div class="opacity-30 group-hover:opacity-100 transition-opacity shrink-0">
                        ${!item.isDir ? `<button class="btn btn-ghost btn-xs btn-circle text-primary" onclick="event.stopPropagation(); downloadPhoneFile('${item.path}')"><i data-feather="download" class="w-4 h-4"></i></button>` : `<i data-feather="chevron-right" class="w-4 h-4"></i>`}
                    </div>
                </div>`;
        }).join('');
        if (window.feather) feather.replace();
    }

    updatePhoneUIPermissions() {
        const uploadBtn = document.getElementById('phoneUploadBtn');
        const badge = document.getElementById('phoneReadOnlyBadge');
        if (uploadBtn) uploadBtn.style.display = this.phoneIsReadOnly ? 'none' : 'flex';
        if (badge) { if (this.phoneIsReadOnly) badge.classList.remove('hidden'); else badge.classList.add('hidden'); }
    }

    async uploadFile(file) {
        const container = document.getElementById('uploadProgressContainer');
        const uploadId = 'up-' + Math.random().toString(36).substr(2, 9);
        container.insertAdjacentHTML('afterbegin', `<div id="${uploadId}" class="p-3 bg-base-200 border border-base-300 rounded-lg shadow-sm mb-2"><div class="flex justify-between items-center text-xs font-bold mb-2"><span class="truncate pr-4 font-black uppercase tracking-tight">${file.name}</span><span class="progress-text text-primary">0%</span></div><progress class="progress progress-primary w-full h-1.5" value="0" max="100"></progress></div>`);
        try {
            const cleanBasePath = this.currentPhonePath.endsWith('/') ? this.currentPhonePath : this.currentPhonePath + '/';
            const xhr = new XMLHttpRequest();
            xhr.open('PUT', `/phone/files${cleanBasePath}${file.name}${this.currentPhoneDeviceId ? '?device_id=' + encodeURIComponent(this.currentPhoneDeviceId) : ''}`, true);
            if (this.apiKey) xhr.setRequestHeader('X-API-Key', this.apiKey);
            xhr.upload.onprogress = (e) => { if (e.lengthComputable) { const pct = Math.round((e.loaded / e.total) * 100); const el = document.getElementById(uploadId); if (el) { el.querySelector('.progress').value = pct; el.querySelector('.progress-text').textContent = pct + '%'; } } };
            const promise = new Promise((res, rej) => { xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? res() : rej(); xhr.onerror = rej; });
            xhr.send(file); await promise;
            const el = document.getElementById(uploadId);
            if (el) { el.classList.add('bg-success/10'); setTimeout(() => el.remove(), 2000); }
            this.showToast('Upload Finished', `File: ${file.name}`, 'success');
        } catch (e) { this.showToast('Error', 'Upload failed check network', 'error'); }
    }

    async deletePhoneItems(paths) {
        if (!confirm(`Delete ${paths.length} items permanently?`)) return;
        for (const p of paths) { try { await fetch(`/phone/files${p.startsWith('/') ? p : '/' + p}${this.currentPhoneDeviceId ? '?device_id=' + encodeURIComponent(this.currentPhoneDeviceId) : ''}`, { method: 'DELETE', headers: this.getHeaders() }); } catch (e) { } }
        this.phoneSelectedItems.clear(); this.updateBatchActionBar(); this.loadPhoneFiles(this.currentPhonePath);
    }

    updateBatchActionBar() {
        const bar = document.getElementById('batchActionBar');
        const count = document.getElementById('selectedCount');
        if (!bar || !count) return;
        const selectedCount = this.phoneSelectedItems.size;
        count.textContent = selectedCount;
        if (selectedCount > 0) bar.classList.remove('translate-y-32', 'opacity-0');
        else bar.classList.add('translate-y-32', 'opacity-0');
    }

    async loadLogs() {
        const container = document.getElementById('logContainer');
        const content = document.getElementById('logContent');
        if (!container || !content) return;
        try {
            const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
            const res = await this.webUICall('/logs');
            if (res.ok) { const data = await res.json(); content.textContent = data.logs || '--- clear ---'; if (isAtBottom) container.scrollTop = container.scrollHeight; }
        } catch (e) { }
    }

    showToast(title, message, type = 'info') {
        const toast = document.createElement('div');
        const iconMap = { 'success': 'check-circle', 'error': 'alert-circle', 'info': 'info' };
        const colorMap = { 'success': 'alert-success border-success text-success-content', 'error': 'alert-error border-error text-error-content', 'info': 'alert-info border-info text-info-content' };
        toast.className = `alert ${colorMap[type] || 'alert-info'} shadow-xl flex items-center p-3 animate-slide-in toast-msg border-none font-bold`;
        toast.innerHTML = `<i data-feather="${iconMap[type]}"></i><div><h3 class="text-sm leading-tight">${title}</h3><p class="text-[10px] opacity-70">${message}</p></div>`;
        let container = document.getElementById('toast-container');
        if (!container) { container = document.createElement('div'); container.id = 'toast-container'; document.body.appendChild(container); }
        container.appendChild(toast);
        if (window.feather) feather.replace();
        setTimeout(() => { toast.classList.add('hiding'); setTimeout(() => toast.remove(), 300); }, 4000);
    }

    loadNotificationSettings() {
        // Now loaded via loadSettings() from server
        return this.notificationSettings;
    }

    saveNotificationSettings() { /* Handled via window.saveNotificationSettings */ }

    async loadSettings() {
        try {
            const res = await fetch('/settings/load', { headers: this.getHeaders() });
            if (res.ok) {
                const config = await res.json();
                const portInput = document.getElementById('serverPortInput');
                if (portInput) portInput.value = config.server_port || window.location.port || '38080';

                // Update all port placeholders in the UI (Guide tab)
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
                    window.changeTheme(config.theme, false); // false = don't save back to server during load
                }
                window.loadNotificationSettings();
            }
        } catch (e) { }
    }

    async loadTransferSettings() {
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
    }

    connectWebSocket() {
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

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B'; const k = 1024; const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
}

// global window helpers
window.closeDrawer = function () { const d = document.getElementById('main-drawer'); if (d) d.checked = false; };
window.toggleApiKeyVisibility = function () { if (window.pclinkUI) { window.pclinkUI.apiKeyVisible = !window.pclinkUI.apiKeyVisible; window.pclinkUI.updateApiKeyDisplay(); } };
window.copyApiKey = async function () { if (window.pclinkUI && window.pclinkUI.apiKey) { await navigator.clipboard.writeText(window.pclinkUI.apiKey); window.pclinkUI.showToast('Copied', 'Access key added to clipboard', 'success'); } };
window.switchSubTab = function (id, btn) {
    document.querySelectorAll('.subtab-content').forEach(c => c.classList.add('hidden'));
    const target = document.getElementById(`subtab-${id}`);
    if (target) target.classList.remove('hidden');

    document.querySelectorAll('.sub-tab').forEach(b => {
        b.classList.remove('active', 'bg-primary', 'text-white');
        b.classList.add('opacity-50');
    });
    btn.classList.add('active', 'bg-primary', 'text-white');
    btn.classList.remove('opacity-50');
};
window.copyCommand = async function (el) { const c = el.querySelector('code'); if (c) { await navigator.clipboard.writeText(c.textContent); window.pclinkUI.showToast('Copied', 'Command added to clipboard'); } };

window.loadTheme = function () {
    const saved = localStorage.getItem('pclink_theme') || 'system';
    const sel = document.getElementById('themeSelector');
    if (sel) sel.value = saved;
    window.changeTheme(saved);
};

window.changeTheme = async function (theme, saveToServer = true) {
    if (theme === 'system') {
        const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
    localStorage.setItem('pclink_theme', theme);

    if (saveToServer && window.pclinkUI) {
        try {
            await fetch('/settings/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: theme })
            });
        } catch (e) { }
    }
};

window.openPermissions = async function (deviceId) {
    const device = window.pclinkUI.devices.find(d => d.id === deviceId);
    if (!device) return;

    const list = document.getElementById('permList');
    const perms = (device.permissions || "").split(',').map(s => s.trim());

    // Available permission nodes
    list.innerHTML = Object.entries(PERMISSION_MAP).map(([key, info]) => `
        <label class="cursor-pointer label border border-base-300 rounded-lg p-3 hover:bg-base-200 transition-colors flex items-center justify-between gap-3">
            <div class="flex flex-col text-left">
                <span class="label-text font-black text-xs uppercase tracking-tight">${info.title}</span>
                <span class="text-[9px] opacity-50 font-bold uppercase tracking-tighter mt-0.5">${info.desc}</span>
            </div>
            <input type="checkbox" class="toggle toggle-sm toggle-primary" data-perm="${key}" ${perms.includes(key) ? 'checked' : ''} onchange="window.updateDevicePerm('${deviceId}', '${key}', this.checked)" />
        </label>
    `).join('');

    document.getElementById('permissionsModal').showModal();
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

window.deleteTemplate = function (name) {
    if (!confirm(`Delete template '${name}'?`)) return;
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
        window.pclinkUI.loadDevices(); // Refresh list to update badges
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

        if (res.ok) {
            window.pclinkUI.showToast('Success', 'Default policy updated', 'success');
        } else {
            throw new Error("Failed to save policy");
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to update policy', 'error');
    }
};

window.generateQRCode = async () => {
    try {
        const data = await window.pclinkUI.apiCall('/qr-payload');
        const container = document.getElementById('qrCodeDisplay');
        container.innerHTML = `<div id="qrCodeContainer"></div>`;
        if (typeof QRCode !== 'undefined') new QRCode(document.getElementById('qrCodeContainer'), { text: JSON.stringify(data), width: 200, height: 200 });
    } catch (e) { }
};
window.regenerateQRCode = () => window.generateQRCode();
window.refreshDevices = () => window.pclinkUI.loadDevices();
window.refreshLogs = () => window.pclinkUI.loadLogs();
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
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection failed', 'error');
    }
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

window.toggleService = async (id, enabled) => { if (window.pclinkUI) await window.pclinkUI.toggleService(id, enabled); };

window.navigatePhone = (p) => {
    if (window.pclinkUI) {
        if (p !== window.pclinkUI.currentPhonePath) {
            window.pclinkUI.phoneNavHistory = window.pclinkUI.phoneNavHistory.slice(0, window.pclinkUI.phoneHistoryIndex + 1);
            window.pclinkUI.phoneNavHistory.push(p);
            window.pclinkUI.phoneHistoryIndex = window.pclinkUI.phoneNavHistory.length - 1;
        }
        window.pclinkUI.currentPhonePath = p;
        window.pclinkUI.phoneSelectedItems.clear(); window.pclinkUI.updateBatchActionBar();
        window.pclinkUI.loadPhoneFiles(p);
    }
};
window.refreshPhoneFiles = () => { if (window.pclinkUI) window.pclinkUI.loadPhoneFiles(window.pclinkUI.currentPhonePath); };
window.goBackPhoneFiles = () => { if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex > 0) { window.pclinkUI.phoneHistoryIndex--; window.navigatePhone(window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex]); } };
window.goForwardPhoneFiles = () => { if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex < window.pclinkUI.phoneNavHistory.length - 1) { window.pclinkUI.phoneHistoryIndex++; window.navigatePhone(window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex]); } };
window.toggleItemSelection = (p) => { if (window.pclinkUI) { window.pclinkUI.phoneSelectedItems.has(p) ? window.pclinkUI.phoneSelectedItems.delete(p) : window.pclinkUI.phoneSelectedItems.add(p); window.pclinkUI.updateBatchActionBar(); window.pclinkUI.displayPhoneFiles(); } };
window.clearSelection = () => { if (window.pclinkUI) { window.pclinkUI.phoneSelectedItems.clear(); window.pclinkUI.updateBatchActionBar(); window.pclinkUI.displayPhoneFiles(); } };
window.handleFileItemClick = (e, path, isDir) => { if (e.ctrlKey || e.metaKey) window.toggleItemSelection(path); else if (isDir) window.navigatePhone(path); else window.toggleItemSelection(path); };
window.handlePhoneSearch = (q) => { if (window.pclinkUI) { window.pclinkUI.phoneSearchQuery = q; window.pclinkUI.displayPhoneFiles(); } };
window.handlePhoneSort = (m) => { if (window.pclinkUI) { window.pclinkUI.phoneSortMode = m; window.pclinkUI.displayPhoneFiles(); } };
window.handleToggleHidden = (s) => { if (window.pclinkUI) { window.pclinkUI.phoneShowHidden = s; window.pclinkUI.displayPhoneFiles(); } };
window.triggerUpload = () => document.getElementById('phoneUploadInput').click();
window.handlePhoneUpload = async (input) => { if (!input.files || input.files.length === 0) return; if (window.pclinkUI) { for (const f of input.files) await window.pclinkUI.uploadFile(f); window.refreshPhoneFiles(); input.value = ''; } };
window.deleteSelectedItems = () => { if (window.pclinkUI) { const paths = Array.from(window.pclinkUI.phoneSelectedItems); window.pclinkUI.deletePhoneItems(paths); } };
window.downloadSelectedItems = () => { if (window.pclinkUI) { Array.from(window.pclinkUI.phoneSelectedItems).forEach(p => window.downloadPhoneFile(p)); } };
window.downloadPhoneFile = (p) => { window.location.href = `/phone/files${p.startsWith('/') ? p : '/' + p}${window.pclinkUI?.currentPhoneDeviceId ? '?device_id=' + encodeURIComponent(window.pclinkUI.currentPhoneDeviceId) : ''}`; };
window.handlePhoneDeviceChange = (id) => { if (window.pclinkUI) window.pclinkUI.handlePhoneDeviceChange(id); };

window.startRemoteServer = async () => { try { await fetch('/server/start', { method: 'POST' }); window.pclinkUI.showToast('Started', 'Remote API is starting...', 'success'); } catch (e) { } };
window.stopRemoteServer = async () => { try { await fetch('/server/stop', { method: 'POST' }); window.pclinkUI.showToast('Stopped', 'Remote API is stopping...', 'success'); } catch (e) { } };
window.restartRemoteServer = async () => { try { await fetch('/server/restart', { method: 'POST' }); window.pclinkUI.showToast('Restart', 'Rebooting service...', 'success'); } catch (e) { } };
window.shutdownServer = async () => { if (confirm('Shutdown server?')) await fetch('/server/shutdown', { method: 'POST' }); };
window.logout = async () => { if (confirm('Logout?')) { await fetch('/auth/logout', { method: 'POST' }); window.location.reload(); } };
window.removeAllDevices = async () => { if (confirm('Remove ALL devices?')) { await window.pclinkUI.webUICall('/ui/devices/remove-all', { method: 'POST' }); window.pclinkUI.loadDevices(); } };
window.banDevice = async (id) => { if (window.pclinkUI) await window.pclinkUI.banDevice(id); };
window.unbanHardware = async (hwid) => { if (window.pclinkUI) await window.pclinkUI.unbanHardware(hwid); };
window.loadBlacklist = async () => { if (window.pclinkUI) await window.pclinkUI.loadBlacklist(); };
window.revokeDevice = async (id) => { if (confirm('Revoke access?')) { await window.pclinkUI.webUICall(`/ui/devices/revoke?device_id=${id}`, { method: 'POST' }); window.pclinkUI.loadDevices(); } };
window.regenerateApiKey = async () => { if (confirm('Regen access key? Clients will disconnect.')) { await window.pclinkUI.webUICall('/ui/auth/regenerate-key', { method: 'POST' }); window.location.reload(); } };
window.approvePairingRequest = (id) => { if (window.pclinkUI.websocket?.readyState === WebSocket.OPEN) { window.pclinkUI.websocket.send(JSON.stringify({ type: 'approve_pair', pairing_id: id })); setTimeout(() => window.pclinkUI.loadPendingRequests(), 500); } };
window.denyPairingRequest = (id) => { if (window.pclinkUI.websocket?.readyState === WebSocket.OPEN) { window.pclinkUI.websocket.send(JSON.stringify({ type: 'deny_pair', pairing_id: id })); setTimeout(() => window.pclinkUI.loadPendingRequests(), 500); } };
window.approvePairing = async () => { if (!window.pclinkUI?.pendingPairingRequest) return; await window.pclinkUI.webUICall('/ui/pairing/approve', { method: 'POST', body: JSON.stringify({ pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id, approved: true }) }); document.getElementById('pairingModal').close(); window.pclinkUI.loadDevices(); };
window.denyPairing = async () => { if (!window.pclinkUI?.pendingPairingRequest) return; await window.pclinkUI.webUICall('/ui/pairing/deny', { method: 'POST', body: JSON.stringify({ pairing_id: window.pclinkUI.pendingPairingRequest.pairing_id, approved: false }) }); document.getElementById('pairingModal').close(); };
window.clearLogs = async () => { if (confirm('Purge history?')) { await fetch('/logs/clear', { method: 'POST' }); const c = document.getElementById('logContent'); if (c) c.textContent = '--- cleared ---'; } };

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

document.addEventListener('DOMContentLoaded', () => { window.pclinkUI = new PCLinkWebUI(); });
