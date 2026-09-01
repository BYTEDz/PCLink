// static/js/extensions.js
// Extensions Management, Governance Console, and Marketplace Subsystem

PCLinkWebUI.prototype.loadExtensions = async function () {
    const list = document.getElementById('extList');
    if (!list) return;
    list.innerHTML = '<div class="text-center py-10 opacity-50 col-span-full"><span class="loading loading-spinner"></span></div>';

    try {
        const res = await this.webUICall('/ui/extensions/');
        if (!res.ok) {
            list.innerHTML = '<div class="alert alert-error text-xs col-span-full">Failed to query extension service.</div>';
            return;
        }
        const data = await res.json();
        const enabled = data.extensions_enabled;

        const disabledAlert = document.getElementById('extGlobalDisabledAlert');
        if (disabledAlert) disabledAlert.classList.toggle('hidden', enabled);

        this.installedExtensions = data.extensions || [];

        const badge = document.getElementById('extBadgeCount');
        const installedCountEl = document.getElementById('extInstalledCount');

        if (badge) {
            if (this.installedExtensions.length > 0) {
                badge.textContent = this.installedExtensions.length;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
        if (installedCountEl) installedCountEl.textContent = this.installedExtensions.length;

        this.renderExtensions(this.installedExtensions);
    } catch (e) {
        list.innerHTML = '<div class="alert alert-error text-xs col-span-full">Connection error querying extensions.</div>';
    }
};

PCLinkWebUI.prototype.renderExtensions = function (extensions) {
    const list = document.getElementById('extList');
    if (!list) return;

    if (!extensions || extensions.length === 0) {
        list.innerHTML = `
            <div class="col-span-full py-12 text-center opacity-40 font-black uppercase text-[10px] tracking-widest bg-base-200/50 border border-dashed border-base-300 rounded-2xl">
                <p>No extensions currently installed</p>
                <p class="mt-1 normal-case text-xs font-semibold opacity-75">Browse the Marketplace tab or drag & drop a .pclink package here.</p>
            </div>
        `;
        return;
    }

    list.innerHTML = extensions.map(ext => {
        const id = ext.id;
        const isQuarantined = ext.quarantined === true;
        const isLoaded = ext.is_loaded;
        const isWorker = ext.backend?.runtime && ext.backend.runtime !== 'none';
        const iconUrl = ext.icon ? `/ui/extensions/${encodeURIComponent(id)}/icon` : null;

        const isSvg = ext.icon && ext.icon.toLowerCase().endsWith('.svg');
        const isThemeAware = ext.theme_aware_icon !== false && isSvg;

        let iconMarkup = `<i data-feather="package" class="w-5 h-5"></i>`;
        if (iconUrl) {
            if (isThemeAware) {
                iconMarkup = `<div class="w-5 h-5 bg-primary" style="-webkit-mask: url('${iconUrl}') no-repeat center / contain; mask: url('${iconUrl}') no-repeat center / contain;"></div>`;
            } else {
                iconMarkup = `<img src="${iconUrl}" class="w-5 h-5 rounded-xs object-contain" onerror="this.outerHTML='<i data-feather=\\\'package\\\' class=\\\'w-5 h-5\\\'></i>'; if(window.feather) feather.replace();" />`;
            }
        }

        const chips = [];

        if (isQuarantined) {
            const reasonLabel = ext.quarantine_reason === 'SECURITY_CONSENT_REQUIRED'
                ? 'Consent Required'
                : (ext.quarantine_reason === 'CRASH_LOOP_DETECTED'
                    ? 'Crash Loop Lock'
                    : (ext.quarantine_reason === 'OOM_LIMIT_EXCEEDED'
                        ? 'Quota Exceeded'
                        : 'Quarantined'));
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-warning/10 border border-warning/30 text-[10px] font-bold text-warning uppercase tracking-wider">
                    <i data-feather="alert-triangle" class="w-2.5 h-2.5"></i> ${reasonLabel}
                </span>
            `);
        }

        if (isLoaded && isWorker && ext.pid) {
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200 border border-base-300 text-[10px] font-mono font-medium text-base-content/80">
                    <span class="w-1.5 h-1.5 rounded-full bg-success"></span> PID ${ext.pid}
                </span>
            `);
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200 border border-base-300 text-[10px] font-mono font-medium text-base-content/80">
                    <i data-feather="cpu" class="w-2.5 h-2.5 text-primary"></i> ${ext.cpu_percent || 0}%
                </span>
            `);
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200 border border-base-300 text-[10px] font-mono font-medium text-base-content/80">
                    <i data-feather="database" class="w-2.5 h-2.5 text-secondary"></i> ${ext.memory_mb || 0} MB
                </span>
            `);
        } else if (isLoaded && !isWorker) {
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200 border border-base-300 text-[10px] font-medium text-base-content/70">
                    <i data-feather="zap" class="w-2.5 h-2.5 text-primary"></i> Broker Mode
                </span>
            `);
        }

        if (ext.crash_count > 0) {
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-error/10 border border-error/30 text-[10px] font-bold text-error">
                    <i data-feather="alert-circle" class="w-2.5 h-2.5"></i> ${ext.crash_count} ${ext.crash_count === 1 ? 'Crash' : 'Crashes'}
                </span>
            `);
        }

        const viewsCount = (ext.views || []).length;
        const widgetsCount = (ext.dashboard_widgets || []).length;
        if (viewsCount > 0) {
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200/60 border border-base-300/60 text-[10px] font-medium text-base-content/60">
                    <i data-feather="sidebar" class="w-2.5 h-2.5 opacity-50"></i> ${viewsCount} View
                </span>
            `);
        }
        if (widgetsCount > 0) {
            chips.push(`
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200/60 border border-base-300/60 text-[10px] font-medium text-base-content/60">
                    <i data-feather="grid" class="w-2.5 h-2.5 opacity-50"></i> ${widgetsCount} Widget
                </span>
            `);
        }

        return `
        <div class="card bg-base-100 border ${isQuarantined ? 'border-warning/40 bg-warning/5' : 'border-base-300'} shadow-xs transition-all hover:border-primary hover:shadow-md group">
            <div class="card-body p-4 flex flex-col justify-between h-full space-y-3">
                <div>
                    <div class="flex items-start justify-between gap-3">
                        <div class="flex items-center gap-3 min-w-0 flex-1">
                            <div class="bg-primary/10 text-primary p-2.5 rounded-xl shrink-0 flex items-center justify-center">
                                ${iconMarkup}
                            </div>
                            <div class="min-w-0 flex-1">
                                <div class="flex items-center gap-1.5 flex-wrap">
                                    <h4 class="font-bold text-xs leading-tight truncate">${this.escapeHTML(ext.name || id)}</h4>
                                    <span class="text-[9px] font-mono opacity-50">v${ext.version || '1.0.0'}</span>
                                </div>
                                <p class="text-[10px] opacity-60 line-clamp-2 mt-0.5">${this.escapeHTML(ext.description || 'No description provided.')}</p>
                            </div>
                        </div>
                        <input type="checkbox" class="toggle toggle-sm toggle-primary shrink-0" ${isLoaded ? 'checked' : ''} ${isQuarantined ? 'disabled' : ''} onchange="window.toggleExtension('${id}', this.checked, this)" title="${isLoaded ? 'Disable Extension' : 'Enable Extension'}" />
                    </div>

                    <div class="flex items-center gap-1.5 mt-3 flex-wrap">
                        ${chips.join('')}
                    </div>
                </div>

                <div class="flex items-center justify-between pt-3 border-t border-base-200 gap-2 flex-wrap">
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold" onclick="window.openExtensionGovernance('${id}')" title="Configure permissions and details">
                        <i data-feather="settings" class="w-3 h-3"></i> Inspect
                    </button>
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold" onclick="window.openExtLogs('${id}', '${this.escapeHTML(ext.name || id)}')">
                        <i data-feather="terminal" class="w-3 h-3"></i> Logs
                    </button>
                    <div class="flex-1"></div>
                    <button class="btn btn-xs btn-ghost btn-error border-base-300 font-bold" onclick="window.deleteExtension('${id}', '${this.escapeHTML(ext.name || id)}')">
                        <i data-feather="trash-2" class="w-3 h-3"></i>
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');

    this.renderIcons();
};

// Sub-Tab Switcher
window.switchExtSubTab = function (tab, btn) {
    document.querySelectorAll('[id^="extView-"]').forEach(v => v.classList.add('hidden'));
    const target = document.getElementById(`extView-${tab}`);
    if (target) target.classList.remove('hidden');

    document.querySelectorAll('[id^="extSubTab-"]').forEach(b => {
        b.classList.remove('active', 'bg-primary', 'text-white');
        b.classList.add('opacity-60');
    });
    btn.classList.add('active', 'bg-primary', 'text-white');
    btn.classList.remove('opacity-60');

    if (tab === 'store' && !window._marketplaceCatalog) {
        window.fetchMarketplaceCatalog();
    }
};

// Filter Installed List
window.filterInstalledExtensions = function () {
    const q = (document.getElementById('extSearchInput')?.value || '').toLowerCase().trim();
    const exts = window.pclinkUI?.installedExtensions || [];
    const filtered = exts.filter(e =>
        !q ||
        (e.name || '').toLowerCase().includes(q) ||
        (e.id || '').toLowerCase().includes(q) ||
        (e.category || '').toLowerCase().includes(q)
    );
    window.pclinkUI.renderExtensions(filtered);
};

// Official Marketplace Store Integration
window.fetchMarketplaceCatalog = async function () {
    const list = document.getElementById('storeList');
    if (!list) return;
    list.innerHTML = '<div class="text-center py-10 opacity-50 col-span-full"><span class="loading loading-spinner"></span></div>';

    const registryUrl = 'https://raw.githubusercontent.com/BYTEDz/pclink-extensions/main/extensions.json';

    try {
        const res = await fetch(registryUrl, { cache: 'no-store' });
        if (!res.ok) throw new Error("Could not fetch marketplace registry");
        window._marketplaceCatalog = await res.json();
        window.filterStoreExtensions();
    } catch (e) {
        list.innerHTML = `
            <div class="col-span-full py-12 text-center opacity-60 bg-base-100 border border-base-300 rounded-2xl space-y-2 p-6">
                <i data-feather="cloud-off" class="w-8 h-8 mx-auto opacity-30"></i>
                <p class="text-xs font-bold text-error">Unable to reach official extensions repository.</p>
                <p class="text-[11px] opacity-60">Check internet connectivity or install via manual package upload.</p>
            </div>
        `;
        if (window.feather) feather.replace();
    }
};

window.filterStoreExtensions = function () {
    const q = (document.getElementById('storeSearchInput')?.value || '').toLowerCase().trim();
    const cat = document.getElementById('storeCategoryFilter')?.value || 'all';
    const catalog = window._marketplaceCatalog || [];
    const installedIds = new Set((window.pclinkUI?.installedExtensions || []).map(e => e.id));

    const filtered = catalog.filter(pkg => {
        if (cat !== 'all' && pkg.category !== cat) return false;
        if (q && !(pkg.name || '').toLowerCase().includes(q) && !(pkg.description || '').toLowerCase().includes(q)) return false;
        return true;
    });

    const list = document.getElementById('storeList');
    if (!list) return;

    if (filtered.length === 0) {
        list.innerHTML = '<div class="col-span-full py-12 text-center opacity-40 font-bold text-xs uppercase tracking-widest">No extensions matching criteria</div>';
        return;
    }

    list.innerHTML = filtered.map(pkg => {
        const isInstalled = installedIds.has(pkg.id);
        const iconUrl = pkg.icon_url || null;

        return `
        <div class="card bg-base-100 border border-base-300 shadow-xs p-4 flex flex-col justify-between h-full space-y-3 hover:border-primary/50 transition-all">
            <div>
                <div class="flex items-start gap-3">
                    <div class="p-2 bg-primary/10 rounded-xl text-primary shrink-0 flex items-center justify-center">
                        ${iconUrl ? `<img src="${iconUrl}" class="w-6 h-6 object-contain" onerror="this.outerHTML='<i data-feather=\\\'package\\\' class=\\\'w-6 h-6\\\'></i>'; if(window.feather) feather.replace();"/>` : `<i data-feather="package" class="w-6 h-6"></i>`}
                    </div>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center justify-between gap-1">
                            <h4 class="font-bold text-xs leading-tight truncate">${window.pclinkUI.escapeHTML(pkg.name)}</h4>
                            <span class="text-[9px] font-mono opacity-50">v${pkg.version}</span>
                        </div>
                        <p class="text-[10px] opacity-60 line-clamp-2 mt-0.5">${window.pclinkUI.escapeHTML(pkg.description || 'No description available.')}</p>
                    </div>
                </div>

                <div class="flex items-center gap-1.5 mt-3 flex-wrap">
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-primary/10 border border-primary/20 text-[10px] font-semibold text-primary">
                        <i data-feather="tag" class="w-2.5 h-2.5"></i> ${pkg.category || 'Utility'}
                    </span>
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200 border border-base-300 text-[10px] font-mono text-base-content/70">
                        <i data-feather="hard-drive" class="w-2.5 h-2.5 opacity-50"></i> ${window.pclinkUI.formatFileSize(pkg.file_size || 0)}
                    </span>
                </div>
            </div>

            <div class="pt-3 border-t border-base-200 flex justify-between items-center gap-2">
                <span class="text-[10px] font-medium text-base-content/50 flex items-center gap-1 truncate">
                    <i data-feather="user" class="w-3 h-3 opacity-40 shrink-0"></i>
                    <span class="truncate">${window.pclinkUI.escapeHTML(pkg.author || 'BYTEDz')}</span>
                </span>
                ${isInstalled ? `
                    <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-success/15 border border-success/30 text-success text-[10px] font-bold uppercase tracking-wider shrink-0">
                        <i data-feather="check" class="w-3 h-3"></i> Installed
                    </span>
                ` : `
                    <button class="btn btn-xs btn-primary text-white font-bold gap-1 shadow-xs px-3 shrink-0" onclick="window.installFromMarketplace('${pkg.download_url}', '${pkg.sha256 || ''}')">
                        <i data-feather="download" class="w-3 h-3"></i> Install
                    </button>
                `}
            </div>
        </div>
        `;
    }).join('');

    this.renderIcons();
};

window.installFromMarketplace = async function (downloadUrl, sha256 = '') {
    if (!downloadUrl) return;
    window.pclinkUI.showToast('Installing', 'Downloading package from marketplace...', 'info');

    let endpoint = `/ui/extensions/install/url?url=${encodeURIComponent(downloadUrl)}`;
    if (sha256) {
        endpoint += `&sha256=${encodeURIComponent(sha256)}`;
    }

    try {
        const res = await window.pclinkUI.webUICall(endpoint, { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Installed', 'Package installed. Review permissions if required.', 'success');
            await window.pclinkUI.loadExtensions();
            window.filterStoreExtensions();
        } else {
            const err = await res.json().catch(() => ({}));
            window.pclinkUI.showToast('Install Failed', err.detail || 'Failed to install extension', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error downloading package', 'error');
    }
};

// Side Panel: Package Installation Drawer
window.openInstallPackagePanel = function () {
    const title = `<i data-feather="upload-cloud" class="w-4 h-4 text-primary"></i> Install Extension Package`;
    const body = `
        <div class="space-y-6 text-xs font-medium">
            <div>
                <h4 class="font-black text-sm uppercase tracking-wide">Manual Installation</h4>
                <p class="text-xs opacity-60 mt-0.5">Upload a local <span class="font-mono text-primary font-bold">.pclink</span> bundle or install via direct URL.</p>
            </div>

            <div class="border-2 border-dashed border-base-300 rounded-2xl p-8 text-center hover:border-primary hover:bg-primary/5 transition-all cursor-pointer flex flex-col items-center justify-center gap-2"
                 onclick="document.getElementById('extFileInput').click()">
                <div class="p-3 bg-base-200 rounded-full text-primary">
                    <i data-feather="box" class="w-6 h-6"></i>
                </div>
                <p class="font-bold text-base-content/80 text-xs">Click or drag <span class="text-primary font-mono font-bold">.pclink</span> bundle here</p>
                <p class="text-[10px] opacity-40 uppercase font-black tracking-widest">Maximum file size: 50 MB</p>
            </div>

            <div class="divider text-[10px] font-black uppercase opacity-30 my-2 tracking-widest">OR INSTALL FROM DIRECT URL</div>

            <div class="space-y-2">
                <label class="font-bold opacity-60 text-[11px] block">Remote Package URL (.pclink)</label>
                <div class="flex gap-2">
                    <input type="url" id="panelExtUrlInput" placeholder="https://example.com/extension.pclink" class="input input-sm input-bordered flex-1 font-mono text-xs" />
                    <button class="btn btn-sm btn-primary text-white font-bold" onclick="window.installExtFromPanelUrl()">
                        <i data-feather="download" class="w-3.5 h-3.5"></i> Fetch
                    </button>
                </div>
            </div>

            <div id="panelExtInstallProgress" class="hidden">
                <div class="flex items-center gap-3 p-3 bg-base-200/80 rounded-xl border border-base-300">
                    <span class="loading loading-spinner loading-sm text-primary"></span>
                    <span class="text-xs font-bold" id="panelExtInstallMsg">Processing package...</span>
                </div>
            </div>
        </div>
    `;

    const footer = `
        <button class="btn btn-sm btn-primary text-white font-bold uppercase text-xs px-6" onclick="window.closeSidePanel()">Done</button>
    `;

    window.openSidePanel(title, body, footer);
};

window.installExtFromPanelUrl = async function () {
    const input = document.getElementById('panelExtUrlInput');
    const url = input?.value?.trim();
    if (!url || !url.startsWith('http')) {
        window.pclinkUI.showToast('Error', 'Enter a valid http(s) URL', 'error');
        return;
    }

    const progress = document.getElementById('panelExtInstallProgress');
    const msg = document.getElementById('panelExtInstallMsg');
    if (progress) progress.classList.remove('hidden');
    if (msg) msg.textContent = 'Downloading and validating package...';

    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/install/url?url=${encodeURIComponent(url)}`, { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Installed', 'Extension package installed', 'success');
            if (input) input.value = '';
            await window.pclinkUI.loadExtensions();
            window.closeSidePanel();
        } else {
            const err = await res.json().catch(() => ({}));
            window.pclinkUI.showToast('Error', err.detail || 'Installation failed', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
    } finally {
        if (progress) progress.classList.add('hidden');
    }
};

// Side Panel: Governance & Detailed Inspection Drawer
window.openExtensionGovernance = function (extensionId) {
    const ext = (window.pclinkUI?.installedExtensions || []).find(e => e.id === extensionId);
    if (!ext) return;

    const declaredPerms = ext.declared_permissions || ext.permissions || [];
    const grantedPerms = new Set(ext.permissions || []);
    const isQuarantined = ext.quarantined === true;

    const title = `<i data-feather="package" class="w-4 h-4 text-primary"></i> Extension Governance — ${window.pclinkUI.escapeHTML(ext.name || ext.id)}`;

    const body = `
        <div class="space-y-6 text-xs">
            <div class="p-4 bg-base-200/50 rounded-2xl border border-base-300/50 space-y-2">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Package ID</span>
                    <span class="font-mono font-bold">${ext.id}</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Version</span>
                    <span class="font-mono font-bold">v${ext.version || '1.0.0'}</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Backend Runtime</span>
                    <span class="badge badge-neutral badge-xs font-mono uppercase font-bold">${ext.backend?.runtime || 'none'}</span>
                </div>
            </div>

            ${isQuarantined ? `
                <div class="alert alert-warning p-3 rounded-xl flex items-center justify-between">
                    <div>
                        <h4 class="font-black text-xs">Quarantine Lock Active</h4>
                        <p class="text-[10px] opacity-80 mt-0.5">Reason: ${ext.quarantine_reason || 'Administrative Review'}</p>
                    </div>
                    <button class="btn btn-xs btn-primary text-white font-bold" onclick="window.approveExtension('${ext.id}')">Approve & Unlock</button>
                </div>
            ` : ''}

            <div class="space-y-2">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Granular Security Permissions</span>
                    <span class="text-[10px] opacity-40 font-mono">${grantedPerms.size} / ${declaredPerms.length} Granted</span>
                </div>

                ${declaredPerms.length === 0 ? `
                    <p class="p-3 bg-base-200 rounded-xl text-center opacity-40 font-bold">No special system permissions requested.</p>
                ` : `
                    <div class="space-y-1.5">
                        ${declaredPerms.map(perm => `
                            <label class="cursor-pointer label border border-base-300 rounded-xl p-2.5 hover:bg-base-200/50 transition-colors flex items-center justify-between">
                                <span class="font-mono font-bold text-xs">${perm}</span>
                                <input type="checkbox" class="toggle toggle-xs toggle-primary" ${grantedPerms.has(perm) ? 'checked' : ''} onchange="window.updateExtensionPerm('${ext.id}', '${perm}', this.checked)" />
                            </label>
                        `).join('')}
                    </div>
                `}
            </div>

            <div class="space-y-2">
                <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Client Contributions</span>
                <div class="p-3 bg-base-200/50 rounded-xl border border-base-300/50 space-y-1 text-[11px]">
                    <div class="flex justify-between">
                        <span class="opacity-60">Client Views:</span>
                        <span class="font-bold font-mono">${(ext.views || []).length} Main Tabs</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="opacity-60">Client Widgets:</span>
                        <span class="font-bold font-mono">${(ext.dashboard_widgets || []).length} Dashboard Cards</span>
                    </div>
                    <p class="text-[9px] opacity-40 mt-1 italic">Note: Extension UI renders exclusively on connected mobile and client apps.</p>
                </div>
            </div>
        </div>
    `;

    const footer = `
        <button class="btn btn-sm btn-ghost border-base-300 font-bold text-xs" onclick="window.openExtLogs('${ext.id}', '${ext.name || ext.id}')">View Logs</button>
        <button class="btn btn-sm btn-primary text-white font-bold uppercase text-xs px-6" onclick="window.closeSidePanel()">Done</button>
    `;

    window.openSidePanel(title, body, footer);
};

window.updateExtensionPerm = async function (extensionId, permission, isGranted) {
    const ext = (window.pclinkUI?.installedExtensions || []).find(e => e.id === extensionId);
    if (!ext) return;

    const currentPerms = new Set(ext.permissions || []);
    if (isGranted) currentPerms.add(permission);
    else currentPerms.delete(permission);

    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${encodeURIComponent(extensionId)}/permissions`, {
            method: 'POST',
            body: JSON.stringify({ permissions: Array.from(currentPerms) })
        });
        if (res.ok) {
            window.pclinkUI.showToast('Permissions Updated', `Capability '${permission}' ${isGranted ? 'granted' : 'revoked'}`, 'success');
            await window.pclinkUI.loadExtensions();
        } else {
            window.pclinkUI.showToast('Error', 'Failed to update capability', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
    }
};

window.loadExtensions = () => { if (window.pclinkUI) window.pclinkUI.loadExtensions(); };

window.toggleExtension = async (id, enabled, toggleEl) => {
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${encodeURIComponent(id)}/toggle?enabled=${enabled}`, { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast(enabled ? 'Enabled' : 'Disabled', `Extension '${id}' ${enabled ? 'loaded' : 'unloaded'}`, 'success');
            await window.pclinkUI.loadExtensions();
        } else {
            toggleEl.checked = !enabled;
            window.pclinkUI.showToast('Error', 'Failed to toggle extension', 'error');
        }
    } catch (e) {
        toggleEl.checked = !enabled;
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
    }
};

window.deleteExtension = async (id, name) => {
    if (!await window.confirmDialog(`Permanently remove '${name}'? This cannot be undone.`, { title: 'Remove Extension', danger: true })) return;
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (res.ok) {
            window.pclinkUI.showToast('Removed', `Extension '${name}' deleted`, 'success');
            await window.pclinkUI.loadExtensions();
            window.closeSidePanel();
        } else {
            window.pclinkUI.showToast('Error', 'Failed to remove extension', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
    }
};

window.approveExtension = async (id) => {
    if (!await window.confirmDialog('Authorize and activate this extension on your system?', { title: 'Approve Extension', danger: false })) return;
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${encodeURIComponent(id)}/approve`, { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Approved', `Extension '${id}' unlocked and active`, 'success');
            await window.pclinkUI.loadExtensions();
            window.closeSidePanel();
        } else {
            window.pclinkUI.showToast('Error', 'Approval failed', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
    }
};

// Side Panel: Diagnostic Logs Viewer
window._currentExtLogsId = null;
window.openExtLogs = async (id, name) => {
    window._currentExtLogsId = id;
    const title = `<i data-feather="terminal" class="w-4 h-4 text-primary"></i> Logs — ${window.pclinkUI.escapeHTML(name || id)}`;
    const body = `
        <div class="space-y-4">
            <div class="flex justify-between items-center">
                <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Subprocess Execution Stream</span>
                <div class="flex gap-2">
                    <button class="btn btn-xs btn-ghost border-base-300 font-bold" onclick="window.refreshExtLogs()">
                        <i data-feather="refresh-cw" class="w-3 h-3"></i> Refresh
                    </button>
                    <button class="btn btn-xs btn-ghost btn-error border-base-300 font-bold" onclick="window.clearExtLogs()">
                        <i data-feather="trash-2" class="w-3 h-3"></i> Clear
                    </button>
                </div>
            </div>
            <div class="bg-[#0b1120] rounded-2xl p-4 font-mono text-xs border border-base-300/50 shadow-inner max-h-[70vh] overflow-y-auto">
                <pre id="panelExtLogsContent" class="text-gray-300 whitespace-pre-wrap break-all leading-relaxed">Streaming logs...</pre>
            </div>
        </div>
    `;

    const footer = `
        <button class="btn btn-sm btn-primary text-white font-bold uppercase text-xs px-6" onclick="window.closeSidePanel()">Close</button>
    `;

    window.openSidePanel(title, body, footer);
    await window.refreshExtLogs();
};

window.refreshExtLogs = async () => {
    if (!window._currentExtLogsId) return;
    const content = document.getElementById('panelExtLogsContent');
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${encodeURIComponent(window._currentExtLogsId)}/logs`);
        if (res.ok) {
            const data = await res.json();
            const logsArray = data.logs || [];
            if (content) content.textContent = logsArray.length > 0 ? logsArray.join('\n') : '--- No logs recorded ---';
        }
    } catch (e) { }
};

window.clearExtLogs = async () => {
    const id = window._currentExtLogsId;
    if (!id) return;
    try {
        await window.pclinkUI.webUICall(`/ui/extensions/${encodeURIComponent(id)}/logs`, { method: 'DELETE' });
        const content = document.getElementById('panelExtLogsContent');
        if (content) content.textContent = '--- Cleared ---';
        window.pclinkUI.showToast('Cleared', 'Extension logs purged', 'success');
    } catch (e) { }
};

// Global Tab Drag and Drop Catch Logic
window._extInstallBusy = false;
window._dragCounter = 0;

window.handleExtTabDragEnter = function (e) {
    e.preventDefault();
    window._dragCounter++;
    const overlay = document.getElementById('extDropOverlay');
    if (overlay) {
        overlay.classList.remove('opacity-0', 'scale-[0.99]');
        overlay.classList.add('opacity-100', 'scale-100');
    }
};

window.handleExtTabDragOver = function (e) {
    e.preventDefault();
};

window.handleExtTabDragLeave = function (e) {
    e.preventDefault();
    window._dragCounter--;
    if (window._dragCounter <= 0) {
        window._dragCounter = 0;
        const overlay = document.getElementById('extDropOverlay');
        if (overlay) {
            overlay.classList.remove('opacity-100', 'scale-100');
            overlay.classList.add('opacity-0', 'scale-[0.99]');
        }
    }
};

window.handleExtTabDrop = async function (e) {
    e.preventDefault();
    window._dragCounter = 0;
    const overlay = document.getElementById('extDropOverlay');
    if (overlay) {
        overlay.classList.remove('opacity-100', 'scale-100');
        overlay.classList.add('opacity-0', 'scale-[0.99]');
    }

    const file = e.dataTransfer?.files?.[0];
    if (file && file.name.toLowerCase().endsWith('.pclink')) {
        await window._doExtInstallFile(file);
    } else {
        window.pclinkUI.showToast('Invalid Package', 'Only .pclink extension packages are supported', 'error');
    }
};

window._doExtInstallFile = async (file) => {
    if (window._extInstallBusy) return;
    window._extInstallBusy = true;

    window.pclinkUI.showToast('Installing', `Unpacking and registering ${file.name}...`, 'info');

    try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch('/ui/extensions/install', { method: 'POST', body: form, credentials: 'include' });
        if (res.ok) {
            window.pclinkUI.showToast('Installed', `${file.name} installed successfully`, 'success');
            await window.pclinkUI.loadExtensions();
            const installedTab = document.getElementById('extSubTab-installed');
            if (installedTab) installedTab.click();
            window.closeSidePanel();
        } else {
            const err = await res.json().catch(() => ({}));
            window.pclinkUI.showToast('Error', err.detail || 'Installation failed', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error during install', 'error');
    } finally {
        window._extInstallBusy = false;
        const input = document.getElementById('extFileInput');
        if (input) input.value = '';
    }
};

window.handleExtFileSelect = (input) => {
    if (input.files && input.files[0]) window._doExtInstallFile(input.files[0]);
};
