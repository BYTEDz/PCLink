// static/js/phone.js

PCLinkWebUI.prototype.updatePhoneDeviceSelector = function() {
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
};

PCLinkWebUI.prototype.handlePhoneDeviceChange = async function(deviceId) {
    this.currentPhoneDeviceId = deviceId;
    this.currentPhonePath = '/';
    await this.loadPhoneFiles('/');
};

PCLinkWebUI.prototype.loadPhoneFiles = async function(path) {
    const backBtn = document.getElementById('phoneBackBtn');
    const forwardBtn = document.getElementById('phoneForwardBtn');
    const container = document.getElementById('phoneFileList');
    const breadcrumbsContainer = document.getElementById('phoneBreadcrumbs');
    if (!container) return;

    const cleanPath = path.startsWith('/') ? path : '/' + path;

    // Render Breadcrumbs
    if (breadcrumbsContainer) {
        const parts = cleanPath.split('/').filter(p => p);
        let html = `<button class="btn btn-xs btn-ghost gap-1 px-1 opacity-50 hover:opacity-100" onclick="window.navigatePhone('/')"><i data-feather="home" class="w-3"></i></button>`;
        let currentBuild = '';
        parts.forEach((p, i) => {
            currentBuild += '/' + p;
            html += `<span class="opacity-20 text-[10px]">/</span>`;
            const isLast = i === parts.length - 1;
            html += `<button class="btn btn-xs btn-ghost px-1 text-[10px] font-black uppercase tracking-tight ${isLast ? 'text-primary opacity-100' : 'opacity-60'}" ${!isLast ? `onclick="window.navigatePhone('${currentBuild}')"` : ''}>${p}</button>`;
        });
        breadcrumbsContainer.innerHTML = html;
        if (window.feather) feather.replace();
    }

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
};

PCLinkWebUI.prototype.getFileType = function(filename) {
    if (!filename.includes('.')) return 'binary';
    const ext = filename.split('.').pop().toLowerCase();
    const types = {
        image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'],
        video: ['mp4', 'webm', 'ogg', 'mov', 'mkv'],
        audio: ['mp3', 'wav', 'ogg', 'm4a', 'flac'],
        text: ['txt', 'log', 'json', 'js', 'py', 'sh', 'md', 'xml', 'css', 'html', 'yaml', 'yml'],
        pdf: ['pdf']
    };
    for (const [type, exts] of Object.entries(types)) {
        if (exts.includes(ext)) return type;
    }
    return 'binary';
};

PCLinkWebUI.prototype.viewPhoneFile = async function(path) {
    const filename = path.split('/').pop();
    const type = this.getFileType(filename);
    const url = `/phone/files${path.startsWith('/') ? path : '/' + path}${this.currentPhoneDeviceId ? '?device_id=' + encodeURIComponent(this.currentPhoneDeviceId) : ''}`;

    const title = `<i data-feather="eye" class="text-primary w-4"></i> Viewer — ${filename}`;
    let body = '';

    if (type === 'image') {
        body = `<div class="flex flex-col gap-4">
            <div class="bg-base-200 rounded-xl overflow-hidden border border-base-300 shadow-inner min-h-[100px] flex items-center justify-center">
                <img src="${url}" class="max-w-full h-auto" onload="this.classList.remove('opacity-0')" class="opacity-0 transition-opacity" />
            </div>
            <div class="text-[10px] font-black opacity-30 uppercase tracking-[0.2em] text-center">${filename}</div>
        </div>`;
    } else if (type === 'video') {
        body = `<div class="flex flex-col gap-4">
            <video src="${url}" controls class="w-full rounded-xl border border-base-300 shadow-lg bg-black aspect-video"></video>
            <div class="text-[10px] font-black opacity-30 uppercase tracking-[0.2em] text-center">${filename}</div>
        </div>`;
    } else if (type === 'audio') {
        body = `<div class="flex flex-col gap-4 items-center py-10 bg-base-200 rounded-2xl border border-base-300">
            <div class="bg-primary/10 text-primary p-8 rounded-full mb-6 shadow-sm"><i data-feather="music" class="w-12 h-12"></i></div>
            <p class="font-bold text-sm mb-4 truncate w-full px-10 text-center">${filename}</p>
            <audio src="${url}" controls class="w-[80%]"></audio>
        </div>`;
    } else if (type === 'text') {
        window.openSidePanel(title, `<div class="flex items-center justify-center py-20"><span class="loading loading-spinner loading-lg text-primary"></span></div>`);
        try {
            const res = await fetch(url, { headers: this.getHeaders() });
            const text = await res.text();
            body = `<pre class="bg-base-300 p-4 rounded-xl text-[11px] font-mono overflow-auto max-h-[75vh] border border-base-300 whitespace-pre-wrap break-all">${this.escapeHTML(text)}</pre>`;
        } catch (e) { body = `<div class="alert alert-error font-bold uppercase text-[10px]">Failed to read file contents</div>`; }
    } else if (type === 'pdf') {
        body = `<iframe src="${url}" class="w-full h-[75vh] rounded-xl border border-base-300 bg-base-200 shadow-inner"></iframe>`;
    } else {
        body = `<div class="text-center py-24 opacity-50 bg-base-200 rounded-2xl border border-base-300 border-dashed">
            <i data-feather="file" class="w-16 h-16 mx-auto mb-6 opacity-20"></i>
            <p class="font-black uppercase tracking-widest text-[10px]">Preview Unavailable</p>
            <p class="text-[9px] normal-case mt-2 opacity-60">This file type must be downloaded to be viewed.</p>
        </div>`;
    }

    const footer = `<a href="${url}" download="${filename}" class="btn btn-sm btn-primary font-bold uppercase tracking-widest text-[10px] px-6 shadow-md"><i data-feather="download" class="w-3"></i> Download</a>`;
    window.openSidePanel(title, body, footer);
};

PCLinkWebUI.prototype.displayPhoneFiles = function() {
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
};

PCLinkWebUI.prototype.updatePhoneUIPermissions = function() {
    const uploadBtn = document.getElementById('phoneUploadBtn');
    const badge = document.getElementById('phoneReadOnlyBadge');
    if (uploadBtn) uploadBtn.style.display = this.phoneIsReadOnly ? 'none' : 'flex';
    if (badge) { if (this.phoneIsReadOnly) badge.classList.remove('hidden'); else badge.classList.add('hidden'); }
};

PCLinkWebUI.prototype.uploadFile = async function(file) {
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
};

PCLinkWebUI.prototype.deletePhoneItems = async function(paths) {
    if (!await window.confirmDialog(`Permanently delete ${paths.length} item${paths.length !== 1 ? 's' : ''}? This cannot be undone.`, { title: 'Delete Files', danger: true })) return;
    for (const p of paths) { try { await fetch(`/phone/files${p.startsWith('/') ? p : '/' + p}${this.currentPhoneDeviceId ? '?device_id=' + encodeURIComponent(this.currentPhoneDeviceId) : ''}`, { method: 'DELETE', headers: this.getHeaders() }); } catch (e) { } }
    this.phoneSelectedItems.clear(); this.updateBatchActionBar(); this.loadPhoneFiles(this.currentPhonePath);
};

PCLinkWebUI.prototype.updateBatchActionBar = function() {
    const bar = document.getElementById('batchActionBar');
    const count = document.getElementById('selectedCount');
    if (!bar || !count) return;
    const selectedCount = this.phoneSelectedItems.size;
    count.textContent = selectedCount;
    if (selectedCount > 0) bar.classList.remove('translate-y-32', 'opacity-0');
    else bar.classList.add('translate-y-32', 'opacity-0');
};

// Global Phone Helpers
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
window.handleFileItemClick = (e, path, isDir) => {
    if (e.ctrlKey || e.metaKey) {
        window.toggleItemSelection(path);
    } else if (isDir) {
        window.navigatePhone(path);
    } else {
        if (window.pclinkUI) window.pclinkUI.viewPhoneFile(path);
    }
};
window.handlePhoneSearch = (q) => { if (window.pclinkUI) { window.pclinkUI.phoneSearchQuery = q; window.pclinkUI.displayPhoneFiles(); } };
window.handlePhoneSort = (m) => { if (window.pclinkUI) { window.pclinkUI.phoneSortMode = m; window.pclinkUI.displayPhoneFiles(); } };
window.handleToggleHidden = (s) => { if (window.pclinkUI) { window.pclinkUI.phoneShowHidden = s; window.pclinkUI.displayPhoneFiles(); } };
window.triggerUpload = () => document.getElementById('phoneUploadInput').click();
window.handlePhoneUpload = async (input) => { if (!input.files || input.files.length === 0) return; if (window.pclinkUI) { for (const f of input.files) await window.pclinkUI.uploadFile(f); window.refreshPhoneFiles(); input.value = ''; } };
window.deleteSelectedItems = () => { if (window.pclinkUI) { const paths = Array.from(window.pclinkUI.phoneSelectedItems); window.pclinkUI.deletePhoneItems(paths); } };
window.downloadSelectedItems = () => { if (window.pclinkUI) { Array.from(window.pclinkUI.phoneSelectedItems).forEach(p => window.downloadPhoneFile(p)); } };
window.downloadPhoneFile = (p) => { window.location.href = `/phone/files${p.startsWith('/') ? p : '/' + p}${window.pclinkUI?.currentPhoneDeviceId ? '?device_id=' + encodeURIComponent(window.pclinkUI.currentPhoneDeviceId) : ''}`; };
window.handlePhoneDeviceChange = (id) => { if (window.pclinkUI) window.pclinkUI.handlePhoneDeviceChange(id); };

window.handlePhoneDragEnter = (e) => {
    e.preventDefault();
    const overlay = document.getElementById('phoneDropOverlay');
    if (overlay) {
        overlay.classList.remove('opacity-0', 'scale-95');
        overlay.classList.add('opacity-100', 'scale-100');
    }
};

window.handlePhoneDragOver = (e) => {
    e.preventDefault();
};

window.handlePhoneDragLeave = (e) => {
    e.preventDefault();
    // Only hide if we actually leave the drop zone container
    if (e.relatedTarget && document.getElementById('phoneFileDropZone').contains(e.relatedTarget)) return;
    const overlay = document.getElementById('phoneDropOverlay');
    if (overlay) {
        overlay.classList.remove('opacity-100', 'scale-100');
        overlay.classList.add('opacity-0', 'scale-95');
    }
};

window.handlePhoneDrop = async (e) => {
    e.preventDefault();
    const overlay = document.getElementById('phoneDropOverlay');
    if (overlay) {
        overlay.classList.remove('opacity-100', 'scale-100');
        overlay.classList.add('opacity-0', 'scale-95');
    }

    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        if (window.pclinkUI) {
            for (const f of e.dataTransfer.files) await window.pclinkUI.uploadFile(f);
            window.refreshPhoneFiles();
        }
    }
};
