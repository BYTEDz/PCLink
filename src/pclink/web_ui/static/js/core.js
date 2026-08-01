// static/js/core.js
const PERMISSION_MAP = {
    files_read: { title: "File Access (Read)", desc: "Browse system files and download contents" },
    files_write: { title: "File Access (Write)", desc: "Upload, rename, move, and delete files" },
    input: { title: "Remote Input & Clipboard", desc: "Control mouse cursor, keyboard input, and sync clipboard" },
    media: { title: "Media & Volume Control", desc: "Control playback and adjust master system volume" },
    apps: { title: "Applications", desc: "View and launch installed applications" },
    processes: { title: "Process Manager", desc: "View and terminate running system processes" },
    power: { title: "Power Management", desc: "Shutdown, restart, sleep, or lock system" },
    info: { title: "System Status & Telemetry", desc: "Monitor hardware usage, battery, and network status" },
    screenshot: { title: "Screen Capture", desc: "Capture primary monitor screen snapshot" },
    macros: { title: "Automation Macros", desc: "Execute multi-step automated task scripts" },
    extensions: { title: "Server Extensions", desc: "Manage and run custom server extensions" },
    desktop_streaming: { title: "Desktop Streaming", desc: "Stream live desktop video & audio feed" },
    terminal: { title: "Shell & Terminal Access", desc: "Execute shell commands and interactive terminal (High Risk)" }
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
        this.macros = [];
        this.macroActions = [];
        this._featherTimeout = null;
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

        this.renderIcons();

        setTimeout(() => {
            const loader = document.getElementById('fullScreenLoader');
            if (loader) {
                loader.style.opacity = '0';
                setTimeout(() => { loader.classList.add('hidden'); }, 500);
            }
        }, 400);
    }

    renderIcons() {
        if (window.feather) {
            if (this._featherTimeout) clearTimeout(this._featherTimeout);
            this._featherTimeout = setTimeout(() => feather.replace(), 10);
        }
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

        // Web UI Global Keyboard Navigation Shortcuts & Ctrl+K Command Palette
        document.addEventListener('keydown', (e) => {
            const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName) || document.activeElement.isContentEditable;

            // Ctrl + K or Cmd + K: Toggle Command Palette
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                window.openCommandPalette();
                return;
            }

            // Esc: Close Side Panel or Open Modals
            if (e.key === 'Escape') {
                window.closeSidePanel();
                const cmdModal = document.getElementById('commandPaletteModal');
                if (cmdModal && cmdModal.open) cmdModal.close();
                return;
            }

            // Alt + 1..9: Jump directly to tabs
            if (e.altKey && !isNaN(e.key) && parseInt(e.key) >= 1 && parseInt(e.key) <= 9) {
                e.preventDefault();
                const tabList = ['dashboard', 'devices', 'phone-files', 'desktop-streaming', 'services', 'links-management', 'extensions', 'settings', 'logs'];
                const targetTab = tabList[parseInt(e.key) - 1];
                if (targetTab) this.switchTab(targetTab);
                return;
            }

            // R: Refresh Active Tab (if not typing in input)
            if (!isInput && e.key.toLowerCase() === 'r' && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                this.loadTabData(this.getCurrentTab());
            }
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
            case 'desktop-streaming': if (window.loadDesktopStreamingTab) await window.loadDesktopStreamingTab(); break;
            case 'extensions': await this.loadExtensions(); break;
            case 'macros': await this.loadMacros(); break;
            case 'links-management': if (window.refreshLinks) await window.refreshLinks(); break;
        }
        this.renderIcons();
    }

    getHeaders() { return { 'Content-Type': 'application/json', ...(this.apiKey && { 'X-API-Key': this.apiKey }) }; }
    getWebHeaders() { return { 'Content-Type': 'application/json' }; }
    async webUICall(endpoint, options = {}) { return fetch(`${this.baseUrl}${endpoint}`, { ...options, headers: { ...this.getWebHeaders(), ...options.headers }, credentials: 'include' }); }
    async apiCall(endpoint, options = {}) {
        const r = await fetch(`${this.baseUrl}${endpoint}`, {
            ...options,
            headers: { ...this.getHeaders(), ...options.headers }
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return await r.json();
    }

    updateConnectionStatus() {
        const dot = document.querySelector('.status-dot');
        const text = document.getElementById('serverStatusText');
        if (!dot || !text) return;
        fetch('/status', { method: 'GET', cache: 'no-cache' }).then(res => {
            if (res.ok) { dot.className = 'status-dot w-2 h-2 rounded-full bg-success'; text.textContent = 'Online'; }
            else throw new Error();
        }).catch(() => { dot.className = 'status-dot w-2 h-2 rounded-full bg-error'; text.textContent = 'Offline'; });
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
        this.renderIcons();
        setTimeout(() => { toast.classList.add('hiding'); setTimeout(() => toast.remove(), 300); }, 4000);
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

    escapeHTML(str) {
        if (!str) return '';
        const p = document.createElement('p');
        p.textContent = str;
        return p.innerHTML;
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B'; const k = 1024; const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
}

// Foundation UI & Centralized Modal Helpers
window.confirmDialog = function (message, { title = 'Confirm', danger = false, requiredWord = null } = {}) {
    return new Promise(resolve => {
        const modal = document.getElementById('confirmModal');
        const titleEl = document.getElementById('confirmModalTitle');
        const msgEl = document.getElementById('confirmModalMessage');
        const iconEl = document.getElementById('confirmModalIcon');
        const okBtn = document.getElementById('confirmModalOk');
        const cancelBtn = document.getElementById('confirmModalCancel');
        const inputWrapper = document.getElementById('confirmModalInputWrapper');
        const input = document.getElementById('confirmModalInput');

        if (!modal) return resolve(false);

        titleEl.textContent = title;
        msgEl.textContent = message;
        const iconName = danger ? 'alert-triangle' : 'help-circle';
        const iconColor = danger ? 'text-error' : 'text-primary';
        iconEl.innerHTML = `<i data-feather="${iconName}" class="w-5 h-5 ${iconColor}"></i>`;
        okBtn.className = `btn btn-sm font-bold text-white ${danger ? 'btn-error' : 'btn-primary'}`;
        if (window.feather) feather.replace();

        if (requiredWord) {
            inputWrapper.classList.remove('hidden');
            input.value = "";
            okBtn.disabled = true;
            input.oninput = () => { okBtn.disabled = input.value.trim().toUpperCase() !== requiredWord.toUpperCase(); };
        } else {
            inputWrapper.classList.add('hidden');
            okBtn.disabled = false;
        }

        const cleanup = (result) => {
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
            modal.removeEventListener('cancel', onCancel);
            input.oninput = null;
            if (modal.close) modal.close();
            resolve(result);
        };
        const onOk = () => cleanup(true);
        const onCancel = () => cleanup(false);

        okBtn.addEventListener('click', onOk, { once: true });
        cancelBtn.addEventListener('click', onCancel, { once: true });
        modal.addEventListener('cancel', onCancel, { once: true });
        if (modal.showModal) modal.showModal();
        if (requiredWord) setTimeout(() => input.focus(), 100);
    });
};

// Grouped Deep Command Palette Controller Logic
window.openCommandPalette = function () {
    const modal = document.getElementById('commandPaletteModal');
    const input = document.getElementById('cmdPaletteInput');
    if (!modal) return;
    if (modal.showModal) modal.showModal();
    if (input) {
        input.value = '';
        setTimeout(() => input.focus(), 100);

        if (!input._hasNavListener) {
            input._hasNavListener = true;
            input.addEventListener('keydown', (e) => {
                const items = window._paletteFilteredItems || [];
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    if (items.length > 0) {
                        window._paletteSelectedIndex = (window._paletteSelectedIndex + 1) % items.length;
                        window.highlightPaletteSelection();
                    }
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (items.length > 0) {
                        window._paletteSelectedIndex = (window._paletteSelectedIndex - 1 + items.length) % items.length;
                        window.highlightPaletteSelection();
                    }
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    if (items.length > 0 && window._paletteSelectedIndex >= 0) {
                        window.executePaletteItem(window._paletteSelectedIndex);
                    }
                }
            });
        }
    }
    window.filterCommandPalette('');
};

window.filterCommandPalette = function (query) {
    const container = document.getElementById('cmdPaletteResults');
    if (!container) return;

    const q = (query || '').toLowerCase().trim();

    const items = [
        // Category: NAVIGATION
        { title: 'Dashboard', category: 'NAVIGATION', icon: 'home', tab: 'dashboard' },
        { title: 'Devices', category: 'NAVIGATION', icon: 'smartphone', tab: 'devices' },
        { title: 'Phone Files', category: 'NAVIGATION', icon: 'folder', tab: 'phone-files' },
        { title: 'Desktop Streaming', category: 'NAVIGATION', icon: 'monitor', tab: 'desktop-streaming' },
        { title: 'Access Control / Firewall', category: 'NAVIGATION', icon: 'shield', tab: 'services' },
        { title: 'Share Links', category: 'NAVIGATION', icon: 'link', tab: 'links-management' },
        { title: 'Extensions', category: 'NAVIGATION', icon: 'package', tab: 'extensions' },
        { title: 'Settings', category: 'NAVIGATION', icon: 'settings', tab: 'settings' },
        { title: 'System Logs', category: 'NAVIGATION', icon: 'terminal', tab: 'logs' },
        { title: 'Automation Macros', category: 'NAVIGATION', icon: 'zap', tab: 'macros' },
        { title: 'Repair Center', category: 'NAVIGATION', icon: 'tool', tab: 'repairTab' },
        { title: 'User Guide', category: 'NAVIGATION', icon: 'book-open', tab: 'guide' },
        { title: 'About PCLink', category: 'NAVIGATION', icon: 'help-circle', tab: 'about' },

        // Category: FIREWALL & ACCESS
        { title: 'Toggle File Access (Read)', category: 'FIREWALL & ACCESS', icon: 'folder', tab: 'services', targetId: '[data-perm="files_read"]' },
        { title: 'Toggle File Access (Write)', category: 'FIREWALL & ACCESS', icon: 'edit-3', tab: 'services', targetId: '[data-perm="files_write"]' },
        { title: 'Toggle Remote Input & Clipboard', category: 'FIREWALL & ACCESS', icon: 'mouse-pointer', tab: 'services', targetId: '[data-perm="input"]' },
        { title: 'Toggle Media Control', category: 'FIREWALL & ACCESS', icon: 'play-circle', tab: 'services', targetId: '[data-perm="media"]' },
        { title: 'Toggle Applications Access', category: 'FIREWALL & ACCESS', icon: 'grid', tab: 'services', targetId: '[data-perm="apps"]' },
        { title: 'Toggle Process Manager', category: 'FIREWALL & ACCESS', icon: 'activity', tab: 'services', targetId: '[data-perm="processes"]' },
        { title: 'Toggle Power Control', category: 'FIREWALL & ACCESS', icon: 'power', tab: 'services', targetId: '[data-perm="power"]' },
        { title: 'Toggle Screen Capture', category: 'FIREWALL & ACCESS', icon: 'camera', tab: 'services', targetId: '[data-perm="screenshot"]' },
        { title: 'Toggle Automation Macros', category: 'FIREWALL & ACCESS', icon: 'zap', tab: 'services', targetId: '[data-perm="macros"]' },
        { title: 'Toggle Server Extensions', category: 'FIREWALL & ACCESS', icon: 'package', tab: 'services', targetId: '[data-perm="extensions"]' },
        { title: 'Toggle Desktop Streaming', category: 'FIREWALL & ACCESS', icon: 'monitor', tab: 'services', targetId: '[data-perm="desktop_streaming"]' },
        { title: 'Toggle Terminal & Shell', category: 'FIREWALL & ACCESS', icon: 'terminal', tab: 'services', targetId: '[data-perm="terminal"]' },

        // Category: SETTINGS & CONFIG
        { title: 'Server Port Configuration', category: 'SETTINGS & CONFIG', icon: 'settings', tab: 'settings', targetId: 'serverPortInput' },
        { title: 'Start with System Autostart', category: 'SETTINGS & CONFIG', icon: 'power', tab: 'settings', targetId: 'autoStartCheckbox' },
        { title: 'Change Master Password', category: 'SETTINGS & CONFIG', icon: 'key', tab: 'settings', targetId: 'currentPassword' },
        { title: 'Change UI Theme', category: 'SETTINGS & CONFIG', icon: 'monitor', tab: 'settings', targetId: 'themeSelector' },
        { title: 'Transfer Cleanup Threshold', category: 'SETTINGS & CONFIG', icon: 'trash-2', tab: 'settings', targetId: 'cleanupThresholdInput' },
        { title: 'Notification Preferences', category: 'SETTINGS & CONFIG', icon: 'bell', tab: 'settings', targetId: 'notifyDeviceConnect' },
        { title: 'Open Host Config Location', category: 'SETTINGS & CONFIG', icon: 'folder', action: () => window.openConfigFolder() },
        { title: 'Factory Reset Server', category: 'SETTINGS & CONFIG', icon: 'refresh-ccw', action: () => window.resetServerRequest() },

        // Category: DAEMON CONTROLS
        { title: 'Start Daemon Server', category: 'DAEMON CONTROLS', icon: 'play', action: () => window.startRemoteServer() },
        { title: 'Stop Daemon Server', category: 'DAEMON CONTROLS', icon: 'pause', action: () => window.stopRemoteServer() },
        { title: 'Restart Daemon Server', category: 'DAEMON CONTROLS', icon: 'refresh-cw', action: () => window.restartRemoteServer() },
        { title: 'Shutdown Server Process', category: 'DAEMON CONTROLS', icon: 'power', action: () => window.shutdownServer() },

        // Category: ACTIONS & UTILITIES
        { title: 'Pair New Device', category: 'ACTIONS & UTILITIES', icon: 'plus-circle', action: () => window.openPairingPanel() },
        { title: 'Notification Center', category: 'ACTIONS & UTILITIES', icon: 'bell', action: () => window.openNotificationPanel() },
        { title: 'Export Diagnostics Specs (JSON)', category: 'ACTIONS & UTILITIES', icon: 'download', action: () => window.downloadSystemSpecs() },
        { title: 'Run System Diagnostics', category: 'ACTIONS & UTILITIES', icon: 'tool', tab: 'repairTab', action: () => { window.pclinkUI.switchTab('repairTab'); if(window.repairModule) window.repairModule.runDiagnostics(); } },
        { title: 'Auto-Heal Server', category: 'ACTIONS & UTILITIES', icon: 'cpu', tab: 'repairTab', action: () => { window.pclinkUI.switchTab('repairTab'); if(window.repairModule) window.repairModule.executeAutoHeal(); } },
        { title: 'Clear System Logs', category: 'ACTIONS & UTILITIES', icon: 'trash-2', action: () => window.clearLogs() },
        { title: 'Download System Logs', category: 'ACTIONS & UTILITIES', icon: 'download', action: () => window.downloadLogs() }
    ];

    const filtered = items.filter(i => !q || i.title.toLowerCase().includes(q) || i.category.toLowerCase().includes(q));

    if (filtered.length === 0) {
        container.innerHTML = `<div class="text-center py-10 opacity-40 text-xs font-bold">No commands found for "${window.pclinkUI ? window.pclinkUI.escapeHTML(q) : q}"</div>`;
        return;
    }

    // Group items by category
    const groups = {};
    filtered.forEach((item, flatIdx) => {
        if (!groups[item.category]) groups[item.category] = [];
        groups[item.category].push({ ...item, flatIdx });
    });

    const escapeFn = (str) => (window.pclinkUI ? window.pclinkUI.escapeHTML(str) : str);

    let html = '';
    for (const [catName, groupItems] of Object.entries(groups)) {
        html += `
            <div class="cmd-group space-y-1">
                <div class="px-2 pt-2 pb-1 text-[10px] font-black uppercase tracking-widest text-primary/70">${escapeFn(catName)}</div>
                <div class="space-y-1">
                    ${groupItems.map(item => `
                        <div class="cmd-item p-2.5 rounded-xl hover:bg-base-200/80 cursor-pointer flex items-center justify-between text-xs font-semibold transition-all group/item" data-flat-idx="${item.flatIdx}" onclick="window.executePaletteItem(${item.flatIdx})">
                            <div class="flex items-center gap-3 min-w-0">
                                <i data-feather="${item.icon}" class="w-4 h-4 text-base-content/60 group-hover/item:text-primary transition-colors shrink-0"></i>
                                <span class="truncate text-base-content/90 group-hover/item:text-base-content">${escapeFn(item.title)}</span>
                            </div>
                            <span class="text-[9px] opacity-30 font-mono uppercase shrink-0 group-hover/item:opacity-80 group-hover/item:text-primary">Run</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
    window._paletteFilteredItems = filtered;
    window._paletteSelectedIndex = 0;
    window.highlightPaletteSelection();

    if (window.feather) feather.replace();
};

window.highlightPaletteSelection = function () {
    const container = document.getElementById('cmdPaletteResults');
    if (!container) return;
    const items = container.querySelectorAll('.cmd-item');
    items.forEach((el) => {
        const flatIdx = parseInt(el.getAttribute('data-flat-idx'));
        if (flatIdx === window._paletteSelectedIndex) {
            el.classList.add('bg-base-200', 'border-l-2', 'border-l-primary', 'pl-3.5');
            el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
            el.classList.remove('bg-base-200', 'border-l-2', 'border-l-primary', 'pl-3.5');
        }
    });
};

window.executePaletteItem = function (idx) {
    const items = window._paletteFilteredItems || [];
    const item = items[idx];
    if (!item) return;

    const modal = document.getElementById('commandPaletteModal');
    if (modal && modal.close) modal.close();

    if (item.action) {
        item.action();
    } else if (item.tab) {
        window.pclinkUI.switchTab(item.tab);
        if (item.targetId) {
            setTimeout(() => {
                const targetEl = document.getElementById(item.targetId) || document.querySelector(item.targetId);
                if (targetEl) {
                    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    targetEl.classList.add('pclink-highlight-pulse');
                    setTimeout(() => targetEl.classList.remove('pclink-highlight-pulse'), 1800);
                    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(targetEl.tagName)) {
                        targetEl.focus();
                    }
                }
            }, 150);
        }
    }
};

window.toggleResetModalCore = function (show) {
    const modal = document.getElementById('resetModal');
    if (!modal) return;
    if (show) {
        modal.showModal ? modal.showModal() : modal.classList.add('modal-open');
        window.fetchConfigPathCore();
    } else {
        modal.close ? modal.close() : modal.classList.remove('modal-open');
    }
};
window.toggleResetModal = window.toggleResetModalCore;

window.fetchConfigPathCore = async function () {
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
};
window.fetchConfigPath = window.fetchConfigPathCore;

window.copyPathCore = function () {
    const el = document.getElementById('p_dataDir');
    if (!el) return;
    navigator.clipboard.writeText(el.innerText).then(() => {
        const originalText = el.innerText;
        el.innerText = "COPIED TO CLIPBOARD!";
        setTimeout(() => el.innerText = originalText, 2000);
    });
};
window.copyPath = window.copyPathCore;

window.openConfigFolderCore = async function () {
    try {
        const response = await fetch('/open-data-dir', { method: 'POST', credentials: 'include' });
        if (!response.ok) {
            if (response.status === 403) alert("Opening folder only works if you are on the host machine (localhost).");
            else alert("Failed to open folder.");
        }
    } catch (e) {
        alert("Error connecting to server.");
    }
};
window.openConfigFolder = window.openConfigFolderCore;

window.handleFactoryResetCore = async function (event) {
    if (event) event.preventDefault();
    const password = document.getElementById('resetPassword')?.value || '';
    const wipeAuth = document.getElementById('wipeAuthCheckbox')?.checked || false;
    const wipeExtensions = document.getElementById('wipeExtensionsCheckbox')?.checked || false;

    if (!await window.confirmDialog("FINAL WARNING: This is IRREVERSIBLE. Are you sure you want to PERMANENTLY delete server data? Type 'YES' to confirm.", { title: 'Factory Reset Security Check', danger: true, requiredWord: 'YES' })) {
        return;
    }

    const btn = document.getElementById('resetButton');
    const originalText = btn ? btn.innerText : 'Resetting...';
    if (btn) {
        btn.disabled = true;
        btn.innerText = "Resetting...";
    }

    try {
        const response = await fetch('/auth/factory-reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password, wipe_auth: wipeAuth, wipe_extensions: wipeExtensions }),
            credentials: 'include'
        });

        if (response.ok) {
            localStorage.clear();
            const overlay = document.getElementById('resetSuccessOverlay');
            if (overlay) overlay.classList.remove('hidden');
            if (window.feather) feather.replace();
            window.toggleResetModalCore(false);
        } else {
            const data = await response.json();
            if (btn) {
                btn.innerText = "Error: " + (data.detail || "Unknown error");
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerText = originalText;
                }, 3000);
            }
        }
    } catch (e) {
        localStorage.clear();
        const overlay = document.getElementById('resetSuccessOverlay');
        if (overlay) overlay.classList.remove('hidden');
        if (window.feather) feather.replace();
        window.toggleResetModalCore(false);
    }
};
window.handleFactoryReset = window.handleFactoryResetCore;

window.openSidePanel = function (title, body, footer = '') {
    const panel = document.getElementById('sidePanel');
    const backdrop = document.getElementById('sidePanelBackdrop');
    const titleEl = document.getElementById('sidePanelTitle');
    const bodyEl = document.getElementById('sidePanelBody');
    const footerEl = document.getElementById('sidePanelFooter');

    if (!panel || !bodyEl) return;

    panel.classList.remove('fullscreen');
    const expandBtn = document.getElementById('sidePanelExpandBtn');
    if (expandBtn) expandBtn.innerHTML = '<i data-feather="maximize-2" class="w-3 h-3"></i>';

    titleEl.innerHTML = title || 'Details';
    bodyEl.innerHTML = body;
    if (footerEl) {
        footerEl.innerHTML = footer;
        footerEl.classList.toggle('hidden', !footer);
    }

    panel.classList.add('open');
    if (backdrop) backdrop.classList.remove('hidden');
    if (backdrop) backdrop.classList.add('open');
    if (window.feather) feather.replace();
};

window.closeSidePanel = function () {
    const panel = document.getElementById('sidePanel');
    const backdrop = document.getElementById('sidePanelBackdrop');
    if (panel) {
        panel.classList.remove('open');
        panel.classList.remove('fullscreen');
    }
    if (backdrop) {
        backdrop.classList.remove('open');
        setTimeout(() => {
            if (!panel.classList.contains('open')) {
                backdrop.classList.add('hidden');
                const b = document.getElementById('sidePanelBody');
                const f = document.getElementById('sidePanelFooter');
                if (b) b.innerHTML = '';
                if (f) f.innerHTML = '';
            }
        }, 300);
    }
};

window.toggleSidePanelFullscreen = function () {
    const panel = document.getElementById('sidePanel');
    const btn = document.getElementById('sidePanelExpandBtn');
    if (!panel) return;
    const isFullscreen = panel.classList.toggle('fullscreen');
    if (btn) btn.innerHTML = isFullscreen ? '<i data-feather="minimize-2" class="w-3 h-3"></i>' : '<i data-feather="maximize-2" class="w-3 h-3"></i>';
    if (window.feather) feather.replace();
};

window.toggleApiKeyVisibility = function () { if (window.pclinkUI) { window.pclinkUI.apiKeyVisible = !window.pclinkUI.apiKeyVisible; window.pclinkUI.updateApiKeyDisplay(); } };
window.copyApiKey = async function () { if (window.pclinkUI && window.pclinkUI.apiKey) { await navigator.clipboard.writeText(window.pclinkUI.apiKey); window.pclinkUI.showToast('Copied', 'Access key added to clipboard', 'success'); } };

window.changeTheme = async function (theme, saveToServer = true) {
    if (theme === 'system') {
        const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
    localStorage.setItem('pclink_theme', theme);
    if (saveToServer && window.pclinkUI) {
        try { await fetch('/settings/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme: theme }) }); } catch (e) { }
    }
};

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

window.closeDrawer = function () { const d = document.getElementById('main-drawer'); if (d) d.checked = false; };
