// static/js/extensions.js
// Extensions Management, Governance Console, and Marketplace Subsystem

const EXT_CAPABILITY_MAP = {
    'system.exec': { title: 'Execute System Commands', desc: 'Run shell commands and system binaries' },
    'fs.read': { title: 'Read Filesystem', desc: 'Read files in application storage and host disk' },
    'fs.write': { title: 'Write Filesystem', desc: 'Create, modify, and delete files on disk' },
    'fs.all': { title: 'Unrestricted Filesystem', desc: 'Full read and write access across all storage volumes' },
    'net.fetch': { title: 'Network Access', desc: 'Make outbound HTTP and API network requests' },
    'storage.local': { title: 'Isolated Local Storage', desc: 'Store private extension state and preferences' },
    'input.inject': { title: 'Virtual Input Injection', desc: 'Simulate mouse movements, clicks, and keystrokes' },
    'media.control': { title: 'Media & Volume Control', desc: 'Control playback state and adjust master volume' },
    'media.read': { title: 'Media State Inspection', desc: 'Inspect active media track metadata and timeline' },
    'power.control': { title: 'System Power Management', desc: 'Execute shutdown, restart, sleep, and session locks' },
    'notifications': { title: 'Push Notifications', desc: 'Dispatch desktop toasts and mobile notifications' }
};

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
        const isConsentRequired = isQuarantined && ext.quarantine_reason === 'SECURITY_CONSENT_REQUIRED';
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
                iconMarkup = `<img src="${iconUrl}" class="w-5 h-5 rounded-xs object-contain" onerror="this.outerHTML='<i data-feather=\\\'package\\\' class=\\\'w-5 h-5\\\'></i>'; if(window.feather){try{feather.replace();}catch(e){}}" />`;
            }
        }

        const chips = [];

        if (isQuarantined) {
            const reasonLabel = isConsentRequired
                ? 'Consent Required'
                : (ext.quarantine_reason === 'CRASH_LOOP_DETECTED'
                    ? 'Crash Loop Lock'
                    : (ext.quarantine_reason === 'OOM_LIMIT_EXCEEDED'
                        ? 'Quota Exceeded'
                        : 'Quarantined'));
            chips.push(`
                <button onclick="window.openExtensionGovernance('${id}')" title="Click to review and approve extension capabilities" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-warning/10 border border-warning/30 text-[10px] font-bold text-warning uppercase tracking-wider hover:bg-warning/20 transition-all cursor-pointer">
                    <i data-feather="alert-triangle" class="w-2.5 h-2.5"></i> ${reasonLabel}
                </button>
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

        const actionButtons = [];

        if (isConsentRequired) {
            actionButtons.push(`
                <button class="btn btn-xs btn-primary text-white font-bold gap-1 shadow-xs" onclick="window.openExtensionGovernance('${id}')" title="Review permissions and activate extension">
                    <i data-feather="check-circle" class="w-3 h-3"></i> Review & Approve
                </button>
            `);
        } else if (isQuarantined) {
            actionButtons.push(`
                <button class="btn btn-xs btn-warning text-warning-content font-bold gap-1 shadow-xs" onclick="window.approveExtension('${id}')" title="Unlock quarantined extension">
                    <i data-feather="unlock" class="w-3 h-3"></i> Unlock
                </button>
            `);
        } else {
            actionButtons.push(`
                <button class="btn btn-xs btn-ghost border-base-300 font-bold" onclick="window.openExtensionGovernance('${id}')" title="Configure permissions and details">
                    <i data-feather="settings" class="w-3 h-3"></i> Inspect
                </button>
            `);
        }

        actionButtons.push(`
            <button class="btn btn-xs btn-ghost border-base-300 font-bold" onclick="window.openExtLogs('${id}', '${this.escapeHTML(ext.name || id)}')">
                <i data-feather="terminal" class="w-3 h-3"></i> Logs
            </button>
        `);

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
                        <div class="shrink-0" ${isQuarantined ? `onclick="window.openExtensionGovernance('${id}')" title="Review permissions to enable"` : ''}>
                            <input type="checkbox" class="toggle toggle-sm toggle-primary ${isQuarantined ? 'opacity-50 cursor-pointer' : ''}" ${isLoaded ? 'checked' : ''} ${isQuarantined ? 'disabled' : ''} onchange="window.toggleExtension('${id}', this.checked, this)" title="${isLoaded ? 'Disable Extension' : 'Enable Extension'}" />
                        </div>
                    </div>

                    ${isConsentRequired ? `
                        <div class="p-2.5 bg-primary/10 border border-primary/25 rounded-xl flex items-center justify-between gap-2 mt-3 cursor-pointer hover:bg-primary/15 transition-colors" onclick="window.openExtensionGovernance('${id}')">
                            <div class="flex items-center gap-2 text-[11px] font-bold text-primary min-w-0">
                                <i data-feather="shield" class="w-3.5 h-3.5 shrink-0"></i>
                                <span class="truncate">Review permissions to activate</span>
                            </div>
                            <span class="btn btn-xs btn-primary text-white font-black text-[9px] uppercase tracking-wider px-2 h-6 min-h-0 shrink-0 shadow-xs">Approve</span>
                        </div>
                    ` : ''}

                    <div class="flex items-center gap-1.5 mt-3 flex-wrap">
                        ${chips.join('')}
                    </div>
                </div>

                <div class="flex items-center justify-between pt-3 border-t border-base-200 gap-2 flex-wrap">
                    ${actionButtons.join('')}
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
    if (window.pclinkUI) {
        window.pclinkUI.renderExtensions(filtered);
    }
};

// Official Marketplace Store Integration
window.fetchMarketplaceCatalog = async function () {
    const list = document.getElementById('storeList');
    if (!list) return;
    list.innerHTML = '<div class="text-center py-10 opacity-50 col-span-full"><span class="loading loading-spinner"></span></div>';

    try {
        let catalog = null;

        try {
            const res = await window.pclinkUI.webUICall('/ui/extensions/marketplace');
            if (res.ok) {
                const data = await res.json();
                catalog = data.extensions || data;
            }
        } catch (serverErr) {
            console.warn('Server proxy unavailable, attempting client direct fetch:', serverErr);
        }

        if (!catalog || !Array.isArray(catalog) || catalog.length === 0) {
            const cdnUrls = [
                'https://cdn.jsdelivr.net/gh/BYTEDz/pclink-extensions@main/extensions.json',
                'https://fastly.jsdelivr.net/gh/BYTEDz/pclink-extensions@main/extensions.json',
                'https://raw.githubusercontent.com/BYTEDz/pclink-extensions/main/extensions.json'
            ];

            for (const url of cdnUrls) {
                try {
                    const res = await fetch(url, { cache: 'no-store' });
                    if (res.ok) {
                        catalog = await res.json();
                        if (Array.isArray(catalog) && catalog.length > 0) break;
                    }
                } catch (cdnErr) {
                    continue;
                }
            }
        }

        if (!catalog || !Array.isArray(catalog)) {
            throw new Error("Could not fetch marketplace registry from any provider");
        }

        window._marketplaceCatalog = catalog;
        window.filterStoreExtensions();
    } catch (e) {
        console.error('Marketplace catalog fetch failed:', e);
        list.innerHTML = `
            <div class="col-span-full py-12 text-center opacity-60 bg-base-100 border border-base-300 rounded-2xl space-y-2 p-6">
                <i data-feather="cloud-off" class="w-8 h-8 mx-auto opacity-30"></i>
                <p class="text-xs font-bold text-error">Unable to reach official extensions repository.</p>
                <p class="text-[11px] opacity-60">Check internet connectivity or install via manual package upload.</p>
            </div>
        `;
        if (window.feather) {
            try { feather.replace(); } catch (err) {}
        }
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
        const isSvg = iconUrl && iconUrl.toLowerCase().endsWith('.svg');
        const isThemeAware = pkg.theme_aware_icon !== false && isSvg;

        let iconMarkup = `<i data-feather="package" class="w-6 h-6"></i>`;
        if (iconUrl) {
            if (isThemeAware) {
                iconMarkup = `<div class="w-6 h-6 bg-primary" style="-webkit-mask: url('${iconUrl}') no-repeat center / contain; mask: url('${iconUrl}') no-repeat center / contain;"></div>`;
            } else {
                iconMarkup = `<img src="${iconUrl}" class="w-6 h-6 object-contain" onerror="this.outerHTML='<i data-feather=\\\'package\\\' class=\\\'w-6 h-6\\\'></i>'; if(window.feather){try{feather.replace();}catch(e){}}"/>`;
            }
        }

        return `
        <div class="card bg-base-100 border border-base-300 shadow-xs p-4 flex flex-col justify-between h-full space-y-3 hover:border-primary/50 transition-all">
            <div>
                <div class="flex items-start gap-3">
                    <div class="p-2 bg-primary/10 rounded-xl text-primary shrink-0 flex items-center justify-center">
                        ${iconMarkup}
                    </div>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center justify-between gap-1">
                            <h4 class="font-bold text-xs leading-tight truncate">${window.pclinkUI ? window.pclinkUI.escapeHTML(pkg.name) : pkg.name}</h4>
                            <span class="text-[9px] font-mono opacity-50">v${pkg.version}</span>
                        </div>
                        <p class="text-[10px] opacity-60 line-clamp-2 mt-0.5">${window.pclinkUI ? window.pclinkUI.escapeHTML(pkg.description || 'No description available.') : (pkg.description || '')}</p>
                    </div>
                </div>

                <div class="flex items-center gap-1.5 mt-3 flex-wrap">
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-primary/10 border border-primary/20 text-[10px] font-semibold text-primary">
                        <i data-feather="tag" class="w-2.5 h-2.5"></i> ${pkg.category || 'Utility'}
                    </span>
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-base-200 border border-base-300 text-[10px] font-mono text-base-content/70">
                        <i data-feather="hard-drive" class="w-2.5 h-2.5 opacity-50"></i> ${window.pclinkUI ? window.pclinkUI.formatFileSize(pkg.file_size || 0) : pkg.file_size}
                    </span>
                </div>
            </div>

            <div class="pt-3 border-t border-base-200 flex justify-between items-center gap-2">
                <span class="text-[10px] font-medium text-base-content/50 flex items-center gap-1 truncate">
                    <i data-feather="user" class="w-3 h-3 opacity-40 shrink-0"></i>
                    <span class="truncate">${window.pclinkUI ? window.pclinkUI.escapeHTML(pkg.author || 'BYTEDz') : (pkg.author || 'BYTEDz')}</span>
                </span>
                ${isInstalled ? `
                    <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-success/15 border border-success/30 text-success text-[10px] font-bold uppercase tracking-wider shrink-0">
                        <i data-feather="check" class="w-3 h-3"></i> Installed
                    </span>
                ` : `
                    <button class="btn btn-xs btn-primary text-white font-bold gap-1 shadow-xs px-3 shrink-0" onclick="window.confirmAndStartInstall('${pkg.id}')">
                        <i data-feather="download" class="w-3 h-3"></i> Install
                    </button>
                `}
            </div>
        </div>
        `;
    }).join('');

    if (window.pclinkUI) {
        window.pclinkUI.renderIcons();
    } else if (window.feather) {
        try { feather.replace(); } catch (err) {}
    }
};

// Pre-Installation Verification & Security Consent Dialog
window.confirmAndStartInstall = async function (extensionId) {
    const pkg = (window._marketplaceCatalog || []).find(p => p.id === extensionId);
    if (!pkg) return;

    const declaredPerms = pkg.declared_permissions || pkg.permissions || [];
    const hasDangerous = declaredPerms.some(p => ['system.exec', 'fs.write', 'fs.all', 'input.inject', 'power.control'].includes(p));

    let confirmMsg = `Install '${pkg.name}' (v${pkg.version}) created by ${pkg.author || 'BYTEDz'}?`;
    if (declaredPerms.length > 0) {
        confirmMsg += `\n\nRequested Security Capabilities:\n• ${declaredPerms.join('\n• ')}`;
    }

    const confirmed = await window.confirmDialog(confirmMsg, {
        title: `Install ${pkg.name}`,
        danger: hasDangerous
    });

    if (confirmed) {
        window.startInteractiveInstall(extensionId);
    }
};

// Interactive Installation Telemetry Modal
window.startInteractiveInstall = function (extensionId) {
    const pkg = (window._marketplaceCatalog || []).find(p => p.id === extensionId);
    if (!pkg) return;

    const iconUrl = pkg.icon_url || null;
    const isSvg = iconUrl && iconUrl.toLowerCase().endsWith('.svg');
    const isThemeAware = pkg.theme_aware_icon !== false && isSvg;

    let iconMarkup = `<i data-feather="package" class="w-6 h-6"></i>`;
    if (iconUrl) {
        if (isThemeAware) {
            iconMarkup = `<div class="w-6 h-6 bg-primary" style="-webkit-mask: url('${iconUrl}') no-repeat center / contain; mask: url('${iconUrl}') no-repeat center / contain;"></div>`;
        } else {
            iconMarkup = `<img src="${iconUrl}" class="w-6 h-6 object-contain" />`;
        }
    }

    const declaredPerms = pkg.declared_permissions || pkg.permissions || [];

    const title = `<i data-feather="download" class="w-4 h-4 text-primary"></i> Install Package`;
    const body = `
        <div class="space-y-5 text-xs font-medium" id="interactiveInstallerBody">
            <div class="p-4 bg-base-200/60 rounded-2xl border border-base-300 flex items-center gap-3.5">
                <div class="p-3 bg-primary/10 rounded-xl text-primary shrink-0 flex items-center justify-center">
                    ${iconMarkup}
                </div>
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                        <h4 class="font-black text-sm tracking-tight truncate text-base-content">${window.pclinkUI ? window.pclinkUI.escapeHTML(pkg.name) : pkg.name}</h4>
                        <span class="text-[10px] font-mono opacity-50 font-bold">v${pkg.version}</span>
                    </div>
                    <p class="text-[11px] opacity-60 mt-0.5 truncate">${window.pclinkUI ? window.pclinkUI.escapeHTML(pkg.author || 'BYTEDz') : (pkg.author || 'BYTEDz')} • ${pkg.category || 'Utility'}</p>
                </div>
            </div>

            <div class="p-4 bg-base-100 rounded-2xl border border-base-300 space-y-3">
                <div class="flex items-center justify-between">
                    <span id="installStageText" class="font-bold text-xs text-base-content flex items-center gap-2">
                        <span class="loading loading-spinner loading-xs text-primary" id="installSpinner"></span>
                        <span id="installStageLabel">Connecting to repository...</span>
                    </span>
                    <span id="installPercentText" class="font-mono font-black text-xs text-primary">0%</span>
                </div>

                <progress id="installProgressBar" class="progress progress-primary w-full h-2 rounded-full transition-all duration-300" value="0" max="100"></progress>

                <div class="flex justify-between items-center text-[10px] font-mono opacity-50 pt-0.5">
                    <span id="installByteCount">0 KB / ${window.pclinkUI ? window.pclinkUI.formatFileSize(pkg.file_size || 0) : pkg.file_size}</span>
                    <span id="installSpeedLabel">Validating...</span>
                </div>
            </div>

            <div class="space-y-2">
                <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Requested Security Permissions</span>
                <div class="p-3 bg-base-200/50 rounded-xl border border-base-300/50 space-y-1.5 max-h-36 overflow-y-auto">
                    ${declaredPerms.length === 0 ? `
                        <p class="text-[11px] opacity-50 font-medium">No special permissions requested.</p>
                    ` : declaredPerms.map(p => `
                        <div class="flex items-center gap-2 text-[11px] font-mono font-semibold text-base-content/80">
                            <i data-feather="shield" class="w-3 h-3 text-primary shrink-0"></i>
                            <span>${p}</span>
                        </div>
                    `).join('')}
                </div>
            </div>

            <div id="installErrorContainer" class="alert alert-error p-3 text-xs font-bold rounded-xl hidden">
                <i data-feather="alert-triangle" class="w-4 h-4 shrink-0"></i>
                <span id="installErrorMsg">Installation failed</span>
            </div>
        </div>
    `;

    const footer = `
        <button id="installCancelBtn" class="btn btn-sm btn-ghost font-bold text-xs" onclick="window.closeSidePanel()">Cancel</button>
        <button id="installReviewBtn" class="btn btn-sm btn-primary text-white font-bold uppercase text-xs px-5 hidden shadow-sm gap-1" onclick="window.openExtensionGovernance('${pkg.id}')"><i data-feather="shield" class="w-3.5 h-3.5"></i> Review & Approve</button>
        <button id="installDoneBtn" class="btn btn-sm btn-ghost border-base-300 font-bold uppercase text-xs px-5 hidden" onclick="window.closeSidePanel()">Done</button>
    `;

    window.openSidePanel(title, body, footer);
    window._executeTrackedInstall(pkg);
};

window._executeTrackedInstall = async function (pkg) {
    const stageLabel = document.getElementById('installStageLabel');
    const percentText = document.getElementById('installPercentText');
    const progressBar = document.getElementById('installProgressBar');
    const byteCount = document.getElementById('installByteCount');
    const speedLabel = document.getElementById('installSpeedLabel');
    const spinner = document.getElementById('installSpinner');
    const errorContainer = document.getElementById('installErrorContainer');
    const errorMsg = document.getElementById('installErrorMsg');
    const cancelBtn = document.getElementById('installCancelBtn');
    const reviewBtn = document.getElementById('installReviewBtn');
    const doneBtn = document.getElementById('installDoneBtn');

    let endpoint = `/ui/extensions/install/url?url=${encodeURIComponent(pkg.download_url)}`;
    if (pkg.sha256) {
        endpoint += `&sha256=${encodeURIComponent(pkg.sha256)}`;
    }

    try {
        if (stageLabel) stageLabel.textContent = "Initiating server package worker...";
        const startRes = await window.pclinkUI.webUICall(endpoint, { method: 'POST' });
        if (!startRes.ok) {
            const err = await startRes.json().catch(() => ({}));
            throw new Error(err.detail || "Failed to start installation worker");
        }

        const { task_id } = await startRes.json();

        const pollInterval = setInterval(async () => {
            try {
                const statusRes = await window.pclinkUI.webUICall(`/ui/extensions/install/status/${encodeURIComponent(task_id)}`);
                if (!statusRes.ok) return;

                const state = await statusRes.json();
                const pct = state.progress || 0;

                if (progressBar) progressBar.value = pct;
                if (percentText) percentText.textContent = `${pct}%`;
                if (stageLabel) stageLabel.textContent = state.stage || state.status;

                if (byteCount && state.downloaded_bytes) {
                    const downloadedStr = window.pclinkUI.formatFileSize(state.downloaded_bytes);
                    const totalStr = state.total_bytes ? window.pclinkUI.formatFileSize(state.total_bytes) : '...';
                    byteCount.textContent = `${downloadedStr} / ${totalStr}`;
                }

                if (speedLabel) {
                    speedLabel.textContent = (state.status || 'processing').toUpperCase();
                }

                if (state.status === 'completed') {
                    clearInterval(pollInterval);
                    if (progressBar) {
                        progressBar.value = 100;
                        progressBar.className = "progress progress-success w-full h-2 rounded-full";
                    }
                    if (percentText) {
                        percentText.textContent = "100%";
                        percentText.className = "font-mono font-black text-xs text-success";
                    }
                    if (stageLabel) stageLabel.innerHTML = `<i data-feather="check-circle" class="w-4 h-4 text-success inline"></i> Package Installed Successfully`;
                    if (spinner) spinner.classList.add('hidden');
                    if (cancelBtn) cancelBtn.classList.add('hidden');
                    if (reviewBtn) reviewBtn.classList.remove('hidden');
                    if (doneBtn) doneBtn.classList.remove('hidden');

                    window.pclinkUI.showToast('Installed', `${pkg.name} installed successfully`, 'success');

                    try {
                        await window.pclinkUI.loadExtensions();
                        window.filterStoreExtensions();
                    } catch (renderErr) {
                        console.debug("Post-install UI sync warning:", renderErr);
                    }

                    if (window.feather) {
                        try { feather.replace(); } catch (err) {}
                    }
                } else if (state.status === 'failed') {
                    clearInterval(pollInterval);
                    throw new Error(state.error || "Installation aborted by host");
                }
            } catch (pollErr) {
                clearInterval(pollInterval);
                if (spinner) spinner.classList.add('hidden');
                if (errorContainer && errorMsg) {
                    errorMsg.textContent = pollErr.message;
                    errorContainer.classList.remove('hidden');
                }
                if (stageLabel) stageLabel.textContent = "Installation halted";
                if (progressBar) progressBar.className = "progress progress-error w-full h-2 rounded-full";
                if (window.feather) {
                    try { feather.replace(); } catch (err) {}
                }
            }
        }, 250);

    } catch (e) {
        if (spinner) spinner.classList.add('hidden');
        if (errorContainer && errorMsg) {
            errorMsg.textContent = e.message;
            errorContainer.classList.remove('hidden');
        }
        if (stageLabel) stageLabel.textContent = "Installation failed";
        if (progressBar) progressBar.className = "progress progress-error w-full h-2 rounded-full";
        if (window.feather) {
            try { feather.replace(); } catch (err) {}
        }
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

    const pseudoPkg = {
        id: `url-${Date.now()}`,
        name: url.split('/').pop() || 'Remote Package',
        version: '1.0.0',
        author: 'Remote URL',
        category: 'Custom',
        download_url: url,
        file_size: 0,
        declared_permissions: []
    };

    window.startInteractiveInstall(pseudoPkg.id);
    window._executeTrackedInstall(pseudoPkg);
};

// Side Panel: Governance & Detailed Inspection Drawer
window.openExtensionGovernance = function (extensionId) {
    const ext = (window.pclinkUI?.installedExtensions || []).find(e => e.id === extensionId);
    if (!ext) return;

    const declaredPerms = ext.declared_permissions || ext.permissions || [];
    const grantedPerms = new Set(ext.permissions || []);
    const isQuarantined = ext.quarantined === true;
    const isConsentRequired = isQuarantined && ext.quarantine_reason === 'SECURITY_CONSENT_REQUIRED';

    const title = `<i data-feather="package" class="w-4 h-4 text-primary"></i> Extension Governance — ${window.pclinkUI.escapeHTML(ext.name || ext.id)}`;

    let bannerHtml = '';
    if (isConsentRequired) {
        bannerHtml = `
            <div class="p-4 bg-primary/10 border-2 border-primary/30 rounded-2xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
                <div class="space-y-0.5 min-w-0">
                    <h4 class="font-black text-xs text-primary flex items-center gap-1.5">
                        <i data-feather="shield" class="w-4 h-4 shrink-0"></i> Administrative Approval Required
                    </h4>
                    <p class="text-[11px] opacity-75 leading-relaxed">This extension requires explicit authorization before it can execute background tasks.</p>
                </div>
                <button class="btn btn-sm btn-primary text-white font-black tracking-wider uppercase text-xs shadow-md px-4 shrink-0 w-full sm:w-auto" onclick="window.approveExtension('${ext.id}')">
                    <i data-feather="check-circle" class="w-3.5 h-3.5"></i> Approve & Activate
                </button>
            </div>
        `;
    } else if (isQuarantined) {
        bannerHtml = `
            <div class="p-4 bg-warning/10 border-2 border-warning/30 rounded-2xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
                <div class="space-y-0.5 min-w-0">
                    <h4 class="font-black text-xs text-warning flex items-center gap-1.5">
                        <i data-feather="alert-triangle" class="w-4 h-4 shrink-0"></i> Quarantine Lock Active
                    </h4>
                    <p class="text-[11px] opacity-75">Reason: ${ext.quarantine_reason || 'Administrative Review'}</p>
                </div>
                <button class="btn btn-sm btn-warning text-warning-content font-black tracking-wider uppercase text-xs shadow-md px-4 shrink-0 w-full sm:w-auto" onclick="window.approveExtension('${ext.id}')">
                    <i data-feather="unlock" class="w-3.5 h-3.5"></i> Unlock & Activate
                </button>
            </div>
        `;
    }

    const body = `
        <div class="space-y-5 text-xs font-medium">
            <div class="p-4 bg-base-200/50 rounded-2xl border border-base-300/50 space-y-2.5">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Package Identifier</span>
                    <span class="font-mono font-bold text-base-content/90">${ext.id}</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Package Version</span>
                    <span class="font-mono font-bold text-base-content/90">v${ext.version || '1.0.0'}</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Worker Runtime</span>
                    <span class="badge badge-neutral badge-xs font-mono uppercase font-bold tracking-wider">${ext.backend?.runtime || 'none'}</span>
                </div>
            </div>

            ${bannerHtml}

            <div class="space-y-2.5">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Granular Security Capabilities</span>
                    <span class="text-[10px] opacity-60 font-mono font-bold">${grantedPerms.size} / ${declaredPerms.length} Granted</span>
                </div>

                ${declaredPerms.length === 0 ? `
                    <div class="p-4 bg-base-200/40 border border-base-300 rounded-2xl text-center opacity-50 font-bold">
                        No special system capabilities requested.
                    </div>
                ` : `
                    <div class="space-y-2">
                        ${declaredPerms.map(perm => {
                            const meta = EXT_CAPABILITY_MAP[perm] || { title: perm, desc: 'Extension declared capability' };
                            const isGranted = grantedPerms.has(perm);
                            return `
                                <label class="cursor-pointer label border border-base-300 rounded-2xl p-3.5 hover:bg-base-200/50 transition-all flex items-center justify-between gap-3 bg-base-100 shadow-xs">
                                    <div class="flex flex-col text-left min-w-0 pr-2">
                                        <div class="flex items-center gap-1.5 flex-wrap">
                                            <span class="font-black text-xs text-base-content leading-tight">${meta.title}</span>
                                            <span class="badge badge-ghost font-mono text-[9px] px-1 py-0 h-4 min-h-0">${perm}</span>
                                        </div>
                                        <span class="text-[10px] opacity-60 mt-0.5 leading-snug">${meta.desc}</span>
                                    </div>
                                    <input type="checkbox" class="toggle toggle-sm toggle-primary shrink-0" ${isGranted ? 'checked' : ''} onchange="window.updateExtensionPerm('${ext.id}', '${perm}', this.checked)" />
                                </label>
                            `;
                        }).join('')}
                    </div>
                `}
            </div>

            <div class="space-y-2">
                <span class="text-[10px] font-black uppercase opacity-40 tracking-wider">Client Contributions</span>
                <div class="p-3.5 bg-base-200/50 rounded-2xl border border-base-300/50 space-y-1.5 text-[11px]">
                    <div class="flex justify-between">
                        <span class="opacity-60">Client Views:</span>
                        <span class="font-bold font-mono">${(ext.views || []).length} Main Tabs</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="opacity-60">Dashboard Cards:</span>
                        <span class="font-bold font-mono">${(ext.dashboard_widgets || []).length} Dashboard Widgets</span>
                    </div>
                    <p class="text-[9px] opacity-40 mt-1 italic">Extension interfaces render natively inside connected mobile companion apps and dashboards.</p>
                </div>
            </div>
        </div>
    `;

    let footer = '';
    if (isConsentRequired || isQuarantined) {
        footer = `
            <button class="btn btn-sm btn-ghost border-base-300 font-bold text-xs" onclick="window.openExtLogs('${ext.id}', '${ext.name || ext.id}')">Logs</button>
            <button class="btn btn-sm btn-ghost font-bold text-xs" onclick="window.closeSidePanel()">Cancel</button>
            <button class="btn btn-sm btn-primary text-white font-black uppercase text-xs px-5 shadow-sm" onclick="window.approveExtension('${ext.id}')">
                <i data-feather="check-circle" class="w-3.5 h-3.5"></i> Approve & Activate
            </button>
        `;
    } else {
        footer = `
            <button class="btn btn-sm btn-ghost border-base-300 font-bold text-xs" onclick="window.openExtLogs('${ext.id}', '${ext.name || ext.id}')">View Logs</button>
            <button class="btn btn-sm btn-primary text-white font-bold uppercase text-xs px-6" onclick="window.closeSidePanel()">Done</button>
        `;
    }

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
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${encodeURIComponent(id)}/approve`, { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Approved', `Extension '${id}' activated`, 'success');
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
