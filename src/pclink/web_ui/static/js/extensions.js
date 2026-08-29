// static/js/extensions.js

PCLinkWebUI.prototype.loadExtensions = async function () {
    const list = document.getElementById('extList');
    if (!list) return;
    list.innerHTML = '<div class="text-center py-10 opacity-50"><span class="loading loading-spinner"></span></div>';
    try {
        const res = await this.webUICall('/ui/extensions/');
        if (!res.ok) { list.innerHTML = '<div class="alert alert-error text-xs">Failed to load extensions</div>'; return; }
        const data = await res.json();
        const enabled = data.extensions_enabled;
        const disabledAlert = document.getElementById('extGlobalDisabledAlert');
        if (disabledAlert) disabledAlert.classList.toggle('hidden', enabled);
        const badge = document.getElementById('extBadgeCount');
        if (badge) {
            const count = (data.extensions || []).length;
            if (count > 0) { badge.textContent = count; badge.classList.remove('hidden'); }
            else badge.classList.add('hidden');
        }
        this.renderExtensions(data.extensions || [], enabled);
    } catch (e) { list.innerHTML = '<div class="alert alert-error text-xs">Connection error</div>'; }
};

PCLinkWebUI.prototype.renderExtensions = function (extensions, globalEnabled) {
    const list = document.getElementById('extList');
    if (!list) return;
    if (extensions.length === 0) {
        list.innerHTML = '<div class="col-span-full py-10 text-center opacity-40 font-black uppercase text-[10px] tracking-widest bg-base-200 border border-dashed border-base-300 rounded-xl"><p>No extensions installed</p><p class="mt-2 normal-case text-[9px]">Install a .pclink package bundle above to get started</p></div>';
        return;
    }
    list.innerHTML = extensions.map(ext => {
        const id = ext.id;
        const isQuarantined = ext.quarantined === true;
        const needsConsent = isQuarantined && (ext.quarantine_reason === 'SECURITY_CONSENT_REQUIRED' || !ext.user_approved);
        const isLoaded = ext.is_loaded;
        const iconUrl = ext.icon ? `/ui/extensions/${id}/icon` : null;

        const isSvg = ext.icon && ext.icon.toLowerCase().endsWith('.svg');
        const isThemeAware = ext.theme_aware_icon !== false && isSvg;

        let iconMarkup = `<i data-feather="package" class="w-5 h-5"></i>`;
        if (iconUrl) {
            if (isThemeAware) {
                iconMarkup = `<div class="w-5 h-5 bg-primary" style="-webkit-mask: url('${iconUrl}') no-repeat center / contain; mask: url('${iconUrl}') no-repeat center / contain;"></div>`;
            } else {
                iconMarkup = `<img src="${iconUrl}" class="w-5 h-5 rounded-sm object-contain" onerror="this.outerHTML='<i data-feather=\\\'package\\\' class=\\\'w-5 h-5\\\'></i>'; if(window.feather) feather.replace();" />`;
            }
        }

        const pidBadge = isLoaded && ext.pid ? `<span class="badge badge-ghost badge-xs font-mono">PID ${ext.pid}</span>` : '';
        const cpuBadge = isLoaded && ext.cpu_percent !== undefined ? `<span class="badge badge-outline badge-xs font-mono font-bold">${ext.cpu_percent}% CPU</span>` : '';
        const memBadge = isLoaded && ext.memory_mb !== undefined ? `<span class="badge badge-outline badge-xs font-mono font-bold">${ext.memory_mb} MB</span>` : '';
        const crashBadge = ext.crash_count > 0 ? `<span class="badge badge-error badge-outline badge-xs font-bold">${ext.crash_count} Crashes</span>` : '';

        let statusBadge = '';
        if (isQuarantined) {
            const reasonLabel = ext.quarantine_reason === 'SECURITY_CONSENT_REQUIRED'
                ? 'Consent Required'
                : (ext.quarantine_reason === 'CRASH_LOOP_DETECTED'
                    ? 'Crash Loop Lock'
                    : (ext.quarantine_reason === 'OOM_LIMIT_EXCEEDED'
                        ? 'Memory Quota Exceeded'
                        : 'Quarantined'));
            statusBadge = `<span class="badge badge-warning badge-xs text-[8px] font-black uppercase tracking-wider">${reasonLabel}</span>`;
        }

        return `
        <div class="card bg-base-100 border ${isQuarantined ? 'border-warning/40 bg-warning/5' : 'border-base-300'} shadow-sm transition-all hover:border-primary group">
            <div class="card-body p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex items-center gap-3 overflow-hidden">
                        <div class="bg-primary/10 text-primary p-2.5 rounded-xl shrink-0 flex items-center justify-center">
                            ${iconMarkup}
                        </div>
                        <div class="overflow-hidden">
                            <div class="flex items-center gap-2">
                                <h4 class="font-bold text-sm leading-tight truncate">${ext.name || ext.display_name || id}</h4>
                                <span class="text-[9px] font-black uppercase opacity-40">v${ext.version || '1.0.0'}</span>
                            </div>
                            <p class="text-[10px] font-bold opacity-50 truncate mt-1">${ext.description || 'No description'}</p>
                            <div class="flex items-center gap-1.5 mt-2 flex-wrap">
                                ${statusBadge}
                                ${pidBadge} ${cpuBadge} ${memBadge} ${crashBadge}
                            </div>
                        </div>
                    </div>
                    <input type="checkbox" class="toggle toggle-sm toggle-primary shrink-0" ${isLoaded ? 'checked' : ''} ${isQuarantined ? 'disabled' : ''} onchange="window.toggleExtension('${id}', this.checked, this)" />
                </div>
                <div class="flex items-center gap-2 mt-4 pt-4 border-t border-base-200 flex-wrap">
                    <button class="btn btn-xs btn-ghost font-bold opacity-50 hover:opacity-100" onclick="window.openExtLogs('${id}', '${ext.name || id}')">
                        <i data-feather="list" class="w-3"></i> Logs
                    </button>
                    <div class="flex-1"></div>
                    ${isQuarantined ? `
                    <button class="btn btn-xs btn-warning font-bold" onclick="window.approveExtension('${id}')">
                        <i data-feather="check" class="w-3"></i> ${needsConsent ? 'Review & Enable' : 'Clear Quarantine'}
                    </button>` : ''}
                    <button class="btn btn-xs btn-ghost btn-error border-base-300 font-bold" onclick="window.deleteExtension('${id}', '${ext.name || id}')">
                        <i data-feather="trash-2" class="w-3"></i> Remove
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');
    this.renderIcons();
};

window.loadExtensions = () => { if (window.pclinkUI) window.pclinkUI.loadExtensions(); };

window.toggleExtension = async (id, enabled, toggleEl) => {
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${id}/toggle?enabled=${enabled}`, { method: 'POST' });
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
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${id}`, { method: 'DELETE' });
        if (res.ok) {
            window.pclinkUI.showToast('Removed', `Extension '${name}' deleted`, 'success');
            await window.pclinkUI.loadExtensions();
        } else { window.pclinkUI.showToast('Error', 'Failed to remove extension', 'error'); }
    } catch (e) { window.pclinkUI.showToast('Error', 'Connection error', 'error'); }
};

window.approveExtension = async (id) => {
    if (!await window.confirmDialog('Authorize and activate this extension on your system?', { title: 'Approve Extension', danger: false })) return;
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${id}/approve`, { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Approved', `Extension '${id}' enabled`, 'success');
            await window.pclinkUI.loadExtensions();
        } else { window.pclinkUI.showToast('Error', 'Enable failed', 'error'); }
    } catch (e) { window.pclinkUI.showToast('Error', 'Connection error', 'error'); }
};

window._currentExtLogsId = null;
window.openExtLogs = async (id, name) => {
    window._currentExtLogsId = id;
    const modal = document.getElementById('extLogsModal');
    const content = document.getElementById('extLogsContent');
    if (!modal) return;
    const titleEl = document.getElementById('extLogsModalTitle');
    if (titleEl) titleEl.textContent = `${name} — Logs`;
    if (content) content.textContent = 'Loading...';
    modal.showModal();
    await window.refreshExtLogs();
};

window.refreshExtLogs = async () => {
    if (!window._currentExtLogsId) return;
    const content = document.getElementById('extLogsContent');
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${window._currentExtLogsId}/logs`);
        if (res.ok) { const data = await res.json(); if (content) content.textContent = data.logs || '--- empty ---'; }
    } catch (e) { }
};

window.clearExtLogs = async () => {
    const id = window._currentExtLogsId;
    if (!id) return;
    try {
        await window.pclinkUI.webUICall(`/ui/extensions/${id}/logs`, { method: 'DELETE' });
        const content = document.getElementById('extLogsContent');
        if (content) content.textContent = '--- cleared ---';
        window.pclinkUI.showToast('Cleared', 'Extension logs purged', 'success');
    } catch (e) { }
};

window._extInstallBusy = false;
window._doExtInstallFile = async (file) => {
    if (window._extInstallBusy) return;
    window._extInstallBusy = true;
    const progress = document.getElementById('extInstallProgress');
    const msg = document.getElementById('extInstallMsg');
    const zone = document.getElementById('extDropZone');
    if (progress) progress.classList.remove('hidden');
    if (msg) msg.textContent = `Installing ${file.name}...`;
    if (zone) zone.classList.add('opacity-50', 'pointer-events-none');
    try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch('/ui/extensions/install', { method: 'POST', body: form, credentials: 'include' });
        if (res.ok) {
            window.pclinkUI.showToast('Installed', `${file.name} has been installed`, 'success');
            await window.pclinkUI.loadExtensions();
        } else {
            const err = await res.json().catch(() => ({}));
            window.pclinkUI.showToast('Error', err.detail || 'Install failed', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error during install', 'error');
    } finally {
        window._extInstallBusy = false;
        if (progress) progress.classList.add('hidden');
        if (zone) zone.classList.remove('opacity-50', 'pointer-events-none');
        const input = document.getElementById('extFileInput');
        if (input) input.value = '';
    }
};

window.handleExtFileSelect = (input) => {
    if (input.files && input.files[0]) window._doExtInstallFile(input.files[0]);
};

window.handleExtDrop = (event) => {
    event.preventDefault();
    const zone = document.getElementById('extDropZone');
    if (zone) zone.classList.remove('border-primary', 'bg-primary/5');
    const file = event.dataTransfer?.files?.[0];
    if (file && file.name.toLowerCase().endsWith('.pclink')) {
        window._doExtInstallFile(file);
    } else {
        window.pclinkUI.showToast('Invalid Package', 'Only .pclink packages are supported', 'error');
    }
};

window.installExtFromUrl = async () => {
    const input = document.getElementById('extUrlInput');
    const url = input?.value?.trim();
    if (!url || !url.startsWith('http')) {
        window.pclinkUI.showToast('Error', 'Enter a valid http(s) URL', 'error');
        return;
    }
    if (window._extInstallBusy) return;
    window._extInstallBusy = true;
    const progress = document.getElementById('extInstallProgress');
    const msg = document.getElementById('extInstallMsg');
    if (progress) progress.classList.remove('hidden');
    if (msg) msg.textContent = 'Downloading and installing...';
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/install/url?url=${encodeURIComponent(url)}`, { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Installed', 'Extension installed from URL', 'success');
            if (input) input.value = '';
            await window.pclinkUI.loadExtensions();
        } else {
            const err = await res.json().catch(() => ({}));
            window.pclinkUI.showToast('Error', err.detail || 'Install failed', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
    } finally {
        window._extInstallBusy = false;
        if (progress) progress.classList.add('hidden');
    }
};
