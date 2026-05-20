// static/js/core.js
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
        this.macros = [];
        this.macroActions = [];
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

        setTimeout(() => {
            const loader = document.getElementById('fullScreenLoader');
            if (loader) {
                loader.style.opacity = '0';
                setTimeout(() => { if (loader) loader.classList.add('hidden'); }, 500);
            }
        }, 400);
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
            case 'mirror': if (window.loadMirrorTab) await window.loadMirrorTab(); break;
            case 'extensions': await this.loadExtensions(); break;
            case 'macros': await this.loadMacros(); break;
        }
        if (window.feather) feather.replace();
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

// Foundation UI Helpers
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
            modal.close();
            resolve(result);
        };
        const onOk = () => cleanup(true);
        const onCancel = () => cleanup(false);

        okBtn.addEventListener('click', onOk, { once: true });
        cancelBtn.addEventListener('click', onCancel, { once: true });
        modal.addEventListener('cancel', onCancel, { once: true });
        modal.showModal();
        if (requiredWord) setTimeout(() => input.focus(), 100);
    });
};

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
