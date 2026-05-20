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
        list.innerHTML = '<div class="col-span-full py-10 text-center opacity-40 font-black uppercase text-[10px] tracking-widest bg-base-200 border border-dashed border-base-300 rounded-xl"><p>No extensions installed</p><p class="mt-2 normal-case text-[9px]">Install a .zip bundle above to get started</p></div>';
        return;
    }
    list.innerHTML = extensions.map(ext => {
        const id = ext.id;
        const needsConsent = ext.has_dangerous_perms && !ext.user_approved;
        const isLoaded = ext.is_loaded;
        const iconUrl = ext.icon ? `/ui/extensions/${id}/icon` : null;
        return `
        <div class="card bg-base-100 border border-base-300 shadow-sm transition-all hover:border-primary group">
            <div class="card-body p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex items-center gap-3 overflow-hidden">
                        <div class="bg-primary/10 text-primary p-2.5 rounded-xl shrink-0 flex items-center justify-center">
                            ${iconUrl ? `<img src="${iconUrl}" class="w-5 h-5 rounded-sm object-contain" onerror="this.outerHTML='<i data-feather=\\\'package\\\' class=\\\'w-5 h-5\\\'></i>'; if(window.feather) feather.replace();" />` : `<i data-feather="package" class="w-5 h-5"></i>`}
                        </div>
                        <div class="overflow-hidden">
                            <div class="flex items-center gap-2">
                                <h4 class="font-bold text-sm leading-tight truncate">${ext.display_name || id}</h4>
                                <span class="text-[9px] font-black uppercase opacity-40">v${ext.version || '0.0.1'}</span>
                            </div>
                            <p class="text-[10px] font-bold opacity-50 truncate mt-1">${ext.description || 'No description'}</p>
                        </div>
                    </div>
                    <input type="checkbox" class="toggle toggle-sm toggle-primary" ${isLoaded ? 'checked' : ''} ${needsConsent ? 'disabled' : ''} onchange="window.toggleExtension('${id}', this.checked, this)" />
                </div>
                <div class="flex items-center gap-2 mt-4 pt-4 border-t border-base-200">
                    <button class="btn btn-xs btn-ghost font-bold opacity-50 hover:opacity-100" onclick="window.openExtLogs('${id}', '${ext.display_name || id}')">
                        <i data-feather="list" class="w-3"></i> Logs
                    </button>
                    <div class="flex-1"></div>
                    ${needsConsent && !isLoaded ? `
                    <button class="btn btn-xs btn-warning font-bold" onclick="window.approveExtension('${id}')">
                        <i data-feather="check" class="w-3"></i> Approve & Enable
                    </button>` : ''}
                    <button class="btn btn-xs btn-ghost btn-error border-base-300 font-bold" onclick="window.deleteExtension('${id}', '${ext.display_name || id}')">
                        <i data-feather="trash-2" class="w-3"></i> Remove
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');
    if (window.feather) feather.replace();
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
    if (!await window.confirmDialog('This extension requests high-risk permissions. Only approve if you trust the source.', { title: 'Approve Dangerous Extension', danger: true })) return;
    try {
        const res = await window.pclinkUI.webUICall(`/ui/extensions/${id}/toggle?enabled=true`, { method: 'POST' });
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
    const title = document.getElementById('confirmModalTitle');
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
    if (file && file.name.endsWith('.zip')) window._doExtInstallFile(file);
    else window.pclinkUI.showToast('Invalid', 'Only .zip bundles are supported', 'error');
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
