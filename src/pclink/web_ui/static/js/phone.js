// static/js/phone.js

PCLinkWebUI.prototype.saveCurrentPhoneScroll = function () {
    const container = document.getElementById('phoneFileList');
    if (container && this.currentPhonePath) {
        if (!this.phoneScrollPositions) this.phoneScrollPositions = {};
        this.phoneScrollPositions[this.currentPhonePath] = container.scrollTop;
    }
};

PCLinkWebUI.prototype.restorePhoneScroll = function () {
    const container = document.getElementById('phoneFileList');
    if (!container) return;
    if (!this.phoneScrollPositions) this.phoneScrollPositions = {};
    const pos = this.phoneScrollPositions[this.currentPhonePath] || 0;
    container.scrollTop = pos;
    requestAnimationFrame(() => {
        if (container) container.scrollTop = pos;
    });
};

PCLinkWebUI.prototype.escapeAttr = function (value) {
    return this.escapeHTML(String(value == null ? '' : value))
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
};

PCLinkWebUI.prototype.encodePhonePath = function (path) {
    const clean = String(path || '/').startsWith('/') ? String(path || '/') : `/${path}`;
    return clean.split('/').map(segment => encodeURIComponent(segment)).join('/') || '/';
};

PCLinkWebUI.prototype.getPhoneUrl = function (path, endpoint = '/phone/files') {
    const encodedPath = this.encodePhonePath(path);
    let url = `${endpoint}${encodedPath}`;
    if (this.currentPhoneDeviceId) {
        url += `${url.includes('?') ? '&' : '?'}device_id=${encodeURIComponent(this.currentPhoneDeviceId)}`;
    }
    return url;
};

PCLinkWebUI.prototype.getPhoneFileUrl = function (path) {
    return this.getPhoneUrl(path);
};

PCLinkWebUI.prototype.joinPhonePath = function (base, name) {
    const cleanBase = String(base || '/').replace(/\/+$/, '');
    return `${cleanBase}/${name}`.replace(/\/+/g, '/');
};

PCLinkWebUI.prototype.updatePhoneDeviceSelector = function () {
    const selector = document.getElementById('phoneDeviceSelector');
    if (!selector) return;
    const currentSelection = this.currentPhoneDeviceId;
    selector.innerHTML = '<option value="">Select Device...</option>';

    let onlineDevice = null;

    this.devices.forEach(device => {
        const option = document.createElement('option');
        option.value = device.id;
        const statusStr = device.is_online ? 'Online' : 'Offline';
        option.textContent = `${device.name} [${statusStr}]`;

        if (device.id === currentSelection) option.selected = true;
        if (device.is_online && !onlineDevice) onlineDevice = device;

        selector.appendChild(option);
    });

    if (!this.currentPhoneDeviceId && onlineDevice) {
        this.currentPhoneDeviceId = onlineDevice.id;
        selector.value = onlineDevice.id;
    }
};

PCLinkWebUI.prototype.handlePhoneDeviceChange = async function (deviceId) {
    this.saveCurrentPhoneScroll();
    this.currentPhoneDeviceId = deviceId;
    this.currentPhonePath = '/';
    this.phoneSelectedItems.clear();
    this.phoneLastSelectedIndex = null;

    if (!deviceId) {
        this.updatePhoneSelectionUI();
        this.renderPhoneConnectPrompt();
        return;
    }

    await this.loadPhoneFiles('/');
};

PCLinkWebUI.prototype.renderPhoneConnectPrompt = function () {
    const container = document.getElementById('phoneFileList');
    if (!container) return;

    const selectedDevice = this.devices.find(d => d.id === this.currentPhoneDeviceId);
    const isOnline = selectedDevice?.is_online;

    container.innerHTML = `
        <div class="flex flex-col items-center justify-center h-full py-20 px-6 text-center">
            <div class="p-5 rounded-3xl ${isOnline ? 'bg-success/10 text-success' : 'bg-base-200 text-base-content/40'} mb-4 shadow-sm">
                <i data-feather="${isOnline ? 'smartphone' : 'wifi-off'}" class="w-12 h-12"></i>
            </div>
            <h3 class="font-black text-lg mb-1">${this.escapeHTML(selectedDevice ? selectedDevice.name : 'No Device Selected')}</h3>
            <p class="text-xs opacity-60 max-w-sm mb-6 font-medium leading-relaxed">
                ${isOnline
                    ? 'Device is online and ready. Click below to browse phone storage.'
                    : 'Select an online device or connect your phone via the PCLink companion app.'}
            </p>
            ${isOnline ? `
                <button class="btn btn-primary text-white font-bold uppercase tracking-wider text-xs px-8 shadow-lg" onclick="window.refreshPhoneFiles()">
                    <i data-feather="folder" class="w-4 h-4"></i> Browse Storage
                </button>
            ` : ''}
        </div>
    `;
    if (window.feather) feather.replace();
};

PCLinkWebUI.prototype.loadPhoneFiles = async function (path) {
    const backBtn = document.getElementById('phoneBackBtn');
    const forwardBtn = document.getElementById('phoneForwardBtn');
    const upBtn = document.getElementById('phoneUpBtn');
    const container = document.getElementById('phoneFileList');
    const breadcrumbsContainer = document.getElementById('phoneBreadcrumbs');
    if (!container) return;

    if (!this.currentPhoneDeviceId) {
        this.renderPhoneConnectPrompt();
        return;
    }

    const cleanPath = path.startsWith('/') ? path : '/' + path;

    if (breadcrumbsContainer) {
        const parts = cleanPath.split('/').filter(p => p);
        const breadcrumbPaths = ['/'];
        let currentBuild = '';
        let html = `<button class="btn btn-xs btn-ghost gap-1 px-1 opacity-50 hover:opacity-100" onclick="window.navigatePhone('/')"><i data-feather="home" class="w-3"></i></button>`;
        parts.forEach((p, i) => {
            currentBuild += '/' + p;
            breadcrumbPaths.push(currentBuild);
            html += `<span class="opacity-20 text-[10px]">/</span>`;
            const isLast = i === parts.length - 1;
            html += `<button class="btn btn-xs btn-ghost px-1 text-[10px] font-black uppercase tracking-tight ${isLast ? 'text-primary opacity-100' : 'opacity-60'}" ${!isLast ? `onclick="window.navigatePhoneBreadcrumb(${i + 1})"` : ''}>${this.escapeHTML(p)}</button>`;
        });
        breadcrumbsContainer.innerHTML = html;
        this.phoneBreadcrumbPaths = breadcrumbPaths;
        if (window.feather) feather.replace();
    }

    if (backBtn) backBtn.disabled = this.phoneHistoryIndex <= 0;
    if (forwardBtn) forwardBtn.disabled = this.phoneHistoryIndex >= this.phoneNavHistory.length - 1;
    if (upBtn) upBtn.disabled = cleanPath === '/';

    const requestToken = (this.phoneLoadToken || 0) + 1;
    this.phoneLoadToken = requestToken;

    try {
        const url = `/phone/files/.browse${this.encodePhonePath(cleanPath)}${this.currentPhoneDeviceId ? `?device_id=${encodeURIComponent(this.currentPhoneDeviceId)}` : ''}`;
        const res = await fetch(url, { headers: this.getHeaders() });
        if (requestToken !== this.phoneLoadToken) return; // A newer navigation won.

        if (res.ok) {
            const data = await res.json();
            this.phoneFileItems = data.items || [];
            this.phoneIsReadOnly = data.readOnly || false;
            this.phoneLastSelectedIndex = null;
            this.updatePhoneUIPermissions();
            this.displayPhoneFiles();
        } else {
            const targetDev = this.devices.find(d => d.id === this.currentPhoneDeviceId);
            container.innerHTML = `
                <div class="flex flex-col items-center justify-center h-full py-16 px-6 text-center">
                    <div class="p-4 rounded-2xl bg-warning/10 text-warning mb-3">
                        <i data-feather="alert-triangle" class="w-8 h-8"></i>
                    </div>
                    <h4 class="font-bold text-sm mb-1">WebDAV Service Unreachable</h4>
                    <p class="text-xs opacity-60 max-w-sm mb-4">Could not establish connection to WebDAV server on <strong>${this.escapeHTML(targetDev ? targetDev.name : 'Phone')}</strong>. Ensure WebDAV server is active in the companion app.</p>
                    <button class="btn btn-sm btn-ghost border-base-300 font-bold" onclick="window.refreshPhoneFiles()">
                        <i data-feather="refresh-cw" class="w-3.5 h-3.5"></i> Retry Connection
                    </button>
                </div>`;
            if (window.feather) feather.replace();
        }
    } catch (e) {
        if (requestToken !== this.phoneLoadToken) return;
        container.innerHTML = `<div class="alert alert-error m-4 text-xs">Error: ${this.escapeHTML(e.message)}</div>`;
    }
};

PCLinkWebUI.prototype.getFileType = function (filename) {
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

PCLinkWebUI.prototype.viewPhoneFile = async function (path) {
    const filename = path.split('/').pop();
    const type = this.getFileType(filename);
    const url = this.getPhoneFileUrl(path);
    const safeName = this.escapeHTML(filename);

    const title = `<i data-feather="eye" class="text-primary w-4"></i> Viewer — ${safeName}`;
    let body = '';

    if (type === 'image') {
        body = `<div class="flex flex-col gap-4">
            <div class="bg-base-200 rounded-xl overflow-hidden border border-base-300 shadow-inner min-h-[100px] flex items-center justify-center">
                <img src="${url}" class="max-w-full h-auto opacity-0 transition-opacity" onload="this.classList.remove('opacity-0')" />
            </div>
            <div class="text-[10px] font-black opacity-30 uppercase tracking-[0.2em] text-center">${safeName}</div>
        </div>`;
    } else if (type === 'video') {
        body = `<div class="flex flex-col gap-4">
            <video src="${url}" controls class="w-full rounded-xl border border-base-300 shadow-lg bg-black aspect-video"></video>
            <div class="text-[10px] font-black opacity-30 uppercase tracking-[0.2em] text-center">${safeName}</div>
        </div>`;
    } else if (type === 'audio') {
        body = `<div class="flex flex-col gap-4 items-center py-10 bg-base-200 rounded-2xl border border-base-300">
            <div class="bg-primary/10 text-primary p-8 rounded-full mb-6 shadow-sm"><i data-feather="music" class="w-12 h-12"></i></div>
            <p class="font-bold text-sm mb-4 truncate w-full px-10 text-center">${safeName}</p>
            <audio src="${url}" controls class="w-[80%]"></audio>
        </div>`;
    } else if (type === 'text') {
        window.openSidePanel(title, `<div class="flex items-center justify-center py-20"><span class="loading loading-spinner loading-lg text-primary"></span></div>`);
        try {
            const res = await fetch(url, { headers: this.getHeaders() });
            const text = await res.text();
            body = `<pre class="bg-base-300 p-4 rounded-xl text-[11px] font-mono overflow-auto max-h-[75vh] border border-base-300 whitespace-pre-wrap break-all">${this.escapeHTML(text)}</pre>`;
        } catch (e) {
            body = `<div class="alert alert-error font-bold uppercase text-[10px]">Failed to read file contents</div>`;
        }
    } else if (type === 'pdf') {
        body = `<iframe src="${url}" class="w-full h-[75vh] rounded-xl border border-base-300 bg-base-200 shadow-inner"></iframe>`;
    } else {
        body = `<div class="text-center py-24 opacity-50 bg-base-200 rounded-2xl border border-base-300 border-dashed">
            <i data-feather="file" class="w-16 h-16 mx-auto mb-6 opacity-20"></i>
            <p class="font-black uppercase tracking-widest text-[10px]">Preview Unavailable</p>
            <p class="text-[9px] normal-case mt-2 opacity-60">Download this file to view it.</p>
        </div>`;
    }

    const footer = `<a href="${url}" download="${this.escapeAttr(filename)}" class="btn btn-sm btn-primary font-bold uppercase tracking-widest text-[10px] px-6 shadow-md"><i data-feather="download" class="w-3"></i> Download</a>`;
    window.openSidePanel(title, body, footer);
};

PCLinkWebUI.prototype.displayPhoneFiles = function () {
    const listContainer = document.getElementById('phoneFileList');
    if (!listContainer) return;

    const filtered = this.phoneFileItems.filter(item => {
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

    this.phoneVisibleItems = filtered;

    if (filtered.length === 0) {
        listContainer.innerHTML = '<div class="py-16 text-center opacity-40 font-bold uppercase tracking-widest text-xs">No matching files found</div>';
        this.updatePhoneSelectionUI();
        if (window.feather) feather.replace();
        this.restorePhoneScroll();
        return;
    }

    listContainer.innerHTML = filtered.map((item, index) => {
        const isSelected = this.phoneSelectedItems.has(item.path);
        const safeName = this.escapeHTML(item.name);
        const meta = item.isDir
            ? 'Directory'
            : `${this.formatFileSize(item.size)} &bull; ${new Date(item.modified).toLocaleDateString()}`;
        return `
            <div class="flex items-center p-3 border-b border-base-300 hover:bg-base-200 cursor-pointer group transition-colors ${isSelected ? 'bg-primary/10 border-l-2 border-l-primary shadow-inner' : 'border-l-2 border-l-transparent'}" onclick="handleFileItemClick(event, ${index})">
                <input type="checkbox" class="checkbox checkbox-sm checkbox-primary mr-3 shrink-0" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleItemSelectionByIndex(${index}, event)" aria-label="Select ${this.escapeAttr(item.name)}">
                <div class="mr-3 shrink-0 ${item.isDir ? 'text-primary' : 'text-base-content/40'}"><i data-feather="${item.isDir ? 'folder' : 'file'}" class="w-5 h-5"></i></div>
                <div class="flex-1 overflow-hidden pr-2">
                    <p class="text-sm font-bold truncate group-hover:text-primary transition-colors">${safeName}</p>
                    <p class="text-[10px] font-bold uppercase opacity-50 tracking-wider truncate">${meta}</p>
                </div>
                <div class="opacity-60 group-hover:opacity-100 focus-within:opacity-100 transition-opacity shrink-0 flex items-center gap-0.5">
                    ${!item.isDir ? `<button class="btn btn-ghost btn-xs btn-circle text-primary" title="Download" onclick="event.stopPropagation(); downloadPhoneFileByIndex(${index})"><i data-feather="download" class="w-4 h-4"></i></button>` : ''}
                    ${!this.phoneIsReadOnly ? `
                        <button class="btn btn-ghost btn-xs btn-circle phone-write-action" title="Rename" onclick="event.stopPropagation(); renamePhoneItemByIndex(${index})"><i data-feather="edit-2" class="w-3.5 h-3.5"></i></button>
                        <button class="btn btn-ghost btn-xs btn-circle text-error phone-write-action" title="Delete" onclick="event.stopPropagation(); deletePhoneItemByIndex(${index})"><i data-feather="trash-2" class="w-3.5 h-3.5"></i></button>
                    ` : ''}
                    ${item.isDir ? `<i data-feather="chevron-right" class="w-4 h-4"></i>` : ''}
                </div>
            </div>`;
    }).join('');

    this.updatePhoneSelectionUI();
    if (window.feather) feather.replace();
    this.restorePhoneScroll();
};

PCLinkWebUI.prototype.updatePhoneSelectionUI = function () {
    const visible = this.phoneVisibleItems || [];
    const selectedVisible = visible.filter(item => this.phoneSelectedItems.has(item.path)).length;
    const selectedTotal = this.phoneSelectedItems.size;
    const selectAll = document.getElementById('phoneSelectAll');

    if (selectAll) {
        selectAll.disabled = visible.length === 0;
        selectAll.checked = visible.length > 0 && selectedVisible === visible.length;
        selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
    }

    const info = document.getElementById('phoneSelectionInfo');
    if (info) {
        info.textContent = selectedTotal > 0
            ? `${selectedTotal} selected${selectedVisible !== selectedTotal ? ` (${selectedVisible} visible)` : ''}`
            : '0 selected';
        info.classList.toggle('text-primary', selectedTotal > 0);
        info.classList.toggle('opacity-40', selectedTotal === 0);
    }

    const count = document.getElementById('phoneItemCount');
    if (count) count.textContent = `${visible.length} item${visible.length === 1 ? '' : 's'}`;

    this.updateBatchActionBar();
};

PCLinkWebUI.prototype.updatePhoneUIPermissions = function () {
    const uploadBtn = document.getElementById('phoneUploadBtn');
    const badge = document.getElementById('phoneReadOnlyBadge');
    if (uploadBtn) uploadBtn.style.display = this.phoneIsReadOnly ? 'none' : 'flex';
    if (badge) { if (this.phoneIsReadOnly) badge.classList.remove('hidden'); else badge.classList.add('hidden'); }
    document.querySelectorAll('.phone-write-action').forEach(el => {
        el.classList.toggle('hidden', !!this.phoneIsReadOnly);
    });
};

PCLinkWebUI.prototype.uploadFile = async function (file) {
    if (this.phoneIsReadOnly) {
        this.showToast('Read-only storage', 'Uploads are disabled for this device.', 'error');
        return;
    }
    const container = document.getElementById('uploadProgressContainer');
    const uploadId = 'up-' + Math.random().toString(36).substr(2, 9);
    if (!container) return;
    container.insertAdjacentHTML('afterbegin', `<div id="${uploadId}" class="p-3 bg-base-200 border border-base-300 rounded-lg shadow-sm mb-2"><div class="flex justify-between items-center text-xs font-bold mb-2"><span class="truncate pr-4 font-black uppercase tracking-tight">${this.escapeHTML(file.name)}</span><span class="progress-text text-primary">0%</span></div><progress class="progress progress-primary w-full h-1.5" value="0" max="100"></progress></div>`);
    try {
        const cleanBasePath = this.currentPhonePath.endsWith('/') ? this.currentPhonePath : this.currentPhonePath + '/';
        const uploadPath = `${cleanBasePath}${file.name}`;
        const xhr = new XMLHttpRequest();
        xhr.open('PUT', this.getPhoneUrl(uploadPath), true);
        if (this.apiKey) xhr.setRequestHeader('X-API-Key', this.apiKey);
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                const el = document.getElementById(uploadId);
                if (el) {
                    el.querySelector('.progress').value = pct;
                    el.querySelector('.progress-text').textContent = pct + '%';
                }
            }
        };
        const promise = new Promise((res, rej) => {
            xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? res() : rej(new Error(`HTTP ${xhr.status}`));
            xhr.onerror = () => rej(new Error('Network error'));
        });
        xhr.send(file);
        await promise;
        const el = document.getElementById(uploadId);
        if (el) { el.classList.add('bg-success/10'); setTimeout(() => el.remove(), 2000); }
        this.showToast('Upload Finished', `File: ${file.name}`, 'success');
    } catch (e) {
        const el = document.getElementById(uploadId);
        if (el) { el.classList.add('bg-error/10'); setTimeout(() => el.remove(), 4000); }
        this.showToast('Upload Failed', `${file.name}: ${e.message}`, 'error');
    }
};

PCLinkWebUI.prototype.deletePhoneItems = async function (paths) {
    if (!paths || paths.length === 0) return;
    if (this.phoneIsReadOnly) {
        this.showToast('Read-only storage', 'Deleting files is disabled for this device.', 'error');
        return;
    }
    if (!await window.confirmDialog(`Permanently delete ${paths.length} item${paths.length !== 1 ? 's' : ''}? This cannot be undone.`, { title: 'Delete Files', danger: true })) return;

    let failures = 0;
    const results = await Promise.allSettled(paths.map(path =>
        fetch(this.getPhoneUrl(path), { method: 'DELETE', headers: this.getHeaders() })
    ));
    for (const result of results) {
        if (result.status === 'rejected' || !result.value.ok) failures++;
    }

    this.phoneSelectedItems.clear();
    this.phoneLastSelectedIndex = null;
    await this.loadPhoneFiles(this.currentPhonePath);
    if (failures > 0) this.showToast('Delete incomplete', `${failures} item(s) could not be deleted.`, 'error');
    else this.showToast('Deleted', `${paths.length} item${paths.length !== 1 ? 's' : ''} removed.`, 'success');
};

PCLinkWebUI.prototype.createPhoneFolder = async function () {
    if (this.phoneIsReadOnly) {
        this.showToast('Read-only storage', 'Creating folders is disabled for this device.', 'error');
        return;
    }
    const name = window.prompt('New folder name:');
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === '.' || trimmed === '..' || /[\/\\]/.test(trimmed)) {
        this.showToast('Invalid name', 'Folder names cannot contain slashes.', 'error');
        return;
    }

    const folderPath = this.joinPhonePath(this.currentPhonePath, trimmed);
    try {
        const res = await fetch(this.getPhoneUrl(folderPath), { method: 'MKCOL', headers: this.getHeaders() });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        this.showToast('Folder created', trimmed, 'success');
        await this.loadPhoneFiles(this.currentPhonePath);
    } catch (e) {
        this.showToast('Could not create folder', e.message, 'error');
    }
};

PCLinkWebUI.prototype.renamePhoneItem = async function (path, currentName, isDir) {
    if (this.phoneIsReadOnly) {
        this.showToast('Read-only storage', 'Renaming is disabled for this device.', 'error');
        return;
    }
    const newName = window.prompt('Rename item:', currentName);
    if (newName === null) return;
    const trimmed = newName.trim();
    if (!trimmed || trimmed === currentName) return;
    if (trimmed === '.' || trimmed === '..' || /[\/\\]/.test(trimmed)) {
        this.showToast('Invalid name', 'Names cannot contain slashes.', 'error');
        return;
    }

    const cleanPath = path.replace(/\/+$/, '');
    const parent = cleanPath.slice(0, cleanPath.lastIndexOf('/'));
    const destination = `${parent || ''}/${trimmed}${isDir ? '/' : ''}`;
    try {
        const res = await fetch(this.getPhoneUrl(path), {
            method: 'MOVE',
            headers: {
                ...this.getHeaders(),
                Destination: this.encodePhonePath(destination),
                Overwrite: 'F'
            }
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        this.showToast('Renamed', `${currentName} → ${trimmed}`, 'success');
        await this.loadPhoneFiles(this.currentPhonePath);
    } catch (e) {
        this.showToast('Rename failed', e.message, 'error');
    }
};

PCLinkWebUI.prototype.downloadPhoneFile = function (path) {
    const filename = path.split('/').pop() || 'download';
    const link = document.createElement('a');
    link.href = this.getPhoneFileUrl(path);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
};

PCLinkWebUI.prototype.downloadPhoneSelection = function (paths) {
    if (!paths || paths.length === 0) return;
    const selectedItems = this.phoneFileItems.filter(item => paths.includes(item.path));
    const filesOnly = selectedItems.length === paths.length && selectedItems.every(item => !item.isDir);

    if (paths.length === 1 && filesOnly) {
        this.downloadPhoneFile(paths[0]);
        return;
    }
    if (selectedItems.length > 500) {
        this.showToast('Too many items', 'Select at most 500 items per download.', 'error');
        return;
    }

    const params = new URLSearchParams();
    selectedItems.forEach(item => {
        params.append('paths', item.isDir ? `${item.path.replace(/\/+$/, '')}/` : item.path);
    });
    if (this.currentPhoneDeviceId) params.set('device_id', this.currentPhoneDeviceId);

    const folderName = (this.currentPhonePath.split('/').filter(Boolean).pop() || 'phone-files').replace(/[^\w.\- ]+/g, '_');
    params.set('name', folderName);
    this.showToast('Preparing ZIP', `Packaging ${params.getAll('paths').length} item(s) from the phone...`, 'info');

    // Use a POST form inside a hidden iframe so large selections never hit URL
    // length limits and the current page stays untouched.
    let frame = document.getElementById('phoneZipDownloadFrame');
    if (!frame) {
        frame = document.createElement('iframe');
        frame.id = 'phoneZipDownloadFrame';
        frame.name = 'phoneZipDownloadFrame';
        frame.style.display = 'none';
        document.body.appendChild(frame);
    }
    frame.onload = () => {
        try {
            const text = frame.contentDocument?.body?.innerText?.trim();
            if (text && text.startsWith('{')) {
                const data = JSON.parse(text);
                if (data.detail) this.showToast('Download failed', data.detail, 'error');
            }
        } catch (e) { /* attachment response, nothing to inspect */ }
    };

    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/phone/files/.zip-download';
    form.target = 'phoneZipDownloadFrame';
    form.style.display = 'none';
    params.forEach((value, key) => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = key;
        input.value = value;
        form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
    form.remove();
};

PCLinkWebUI.prototype.updateBatchActionBar = function () {
    const bar = document.getElementById('batchActionBar');
    const count = document.getElementById('selectedCount');
    if (!bar || !count) return;
    const selectedCount = this.phoneSelectedItems.size;
    count.textContent = selectedCount;
    const sizeEl = document.getElementById('selectedSize');
    if (sizeEl) {
        const selectedItems = this.phoneFileItems.filter(item => this.phoneSelectedItems.has(item.path));
        const totalSize = selectedItems.reduce((sum, item) => sum + (!item.isDir ? (item.size || 0) : 0), 0);
        sizeEl.textContent = totalSize > 0 ? `• ${this.formatFileSize(totalSize)}` : '';
    }
    if (selectedCount > 0) bar.classList.remove('translate-y-32', 'opacity-0');
    else bar.classList.add('translate-y-32', 'opacity-0');
};

PCLinkWebUI.prototype.applyPhoneSelectionRange = function (fromIndex, toIndex, select) {
    const visible = this.phoneVisibleItems || [];
    const start = Math.min(fromIndex, toIndex);
    const end = Math.max(fromIndex, toIndex);
    for (let i = start; i <= end && i < visible.length; i++) {
        if (select) this.phoneSelectedItems.add(visible[i].path);
        else this.phoneSelectedItems.delete(visible[i].path);
    }
};

PCLinkWebUI.prototype.togglePhoneSelectAll = function (checked) {
    const visible = this.phoneVisibleItems || [];
    const shouldSelect = typeof checked === 'boolean'
        ? checked
        : !(visible.length > 0 && visible.every(item => this.phoneSelectedItems.has(item.path)));

    visible.forEach(item => {
        if (shouldSelect) this.phoneSelectedItems.add(item.path);
        else this.phoneSelectedItems.delete(item.path);
    });
    this.phoneLastSelectedIndex = null;
    this.saveCurrentPhoneScroll();
    this.displayPhoneFiles();
};

PCLinkWebUI.prototype.invertPhoneSelection = function () {
    (this.phoneVisibleItems || []).forEach(item => {
        if (this.phoneSelectedItems.has(item.path)) this.phoneSelectedItems.delete(item.path);
        else this.phoneSelectedItems.add(item.path);
    });
    this.phoneLastSelectedIndex = null;
    this.saveCurrentPhoneScroll();
    this.displayPhoneFiles();
};

PCLinkWebUI.prototype.goUpPhone = function () {
    const clean = this.currentPhonePath.replace(/\/+$/, '');
    if (!clean) return;
    const parent = clean.slice(0, clean.lastIndexOf('/')) || '/';
    window.navigatePhone(parent);
};

PCLinkWebUI.prototype.applyPhonePreferences = function () {
    try {
        const savedSort = localStorage.getItem('pclink.phoneSort');
        if (savedSort) this.phoneSortMode = savedSort;
        const savedHidden = localStorage.getItem('pclink.phoneHidden');
        if (savedHidden !== null) this.phoneShowHidden = savedHidden === 'true';
    } catch (e) { /* storage may be unavailable */ }

    const sortEl = document.getElementById('phoneFileSort');
    if (sortEl) sortEl.value = this.phoneSortMode;
    const hiddenEl = document.getElementById('showHiddenFiles');
    if (hiddenEl) hiddenEl.checked = this.phoneShowHidden;
};

PCLinkWebUI.prototype.setupPhoneKeyboardShortcuts = function () {
    if (this._phoneShortcutsBound) return;
    this._phoneShortcutsBound = true;
    document.addEventListener('keydown', (e) => {
        const tab = document.getElementById('phone-files');
        if (!tab || !tab.classList.contains('active')) return;

        const activeEl = document.activeElement;
        const isInput = activeEl && (['INPUT', 'TEXTAREA', 'SELECT'].includes(activeEl.tagName) || activeEl.isContentEditable);
        const sidePanelOpen = document.getElementById('sidePanel')?.classList.contains('open');
        const modalOpen = !!document.querySelector('dialog[open]');
        if (isInput || sidePanelOpen || modalOpen) return;

        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
            e.preventDefault();
            this.togglePhoneSelectAll(true);
            return;
        }

        if (e.key === 'Escape') {
            if (this.phoneSelectedItems.size > 0) {
                e.preventDefault();
                window.clearSelection();
            }
            return;
        }

        if (e.key === 'Delete' && this.phoneSelectedItems.size > 0) {
            e.preventDefault();
            window.deleteSelectedItems();
            return;
        }

        if (e.key === 'F2' && this.phoneSelectedItems.size === 1) {
            e.preventDefault();
            const path = Array.from(this.phoneSelectedItems)[0];
            const item = this.phoneFileItems.find(f => f.path === path);
            if (item) this.renamePhoneItem(item.path, item.name, item.isDir);
            return;
        }

        if (e.key === 'Backspace' || (e.altKey && e.key === 'ArrowUp')) {
            e.preventDefault();
            this.goUpPhone();
        }
    });
};

// Global Phone Helpers
window.navigatePhone = (p) => {
    if (window.pclinkUI) {
        window.pclinkUI.saveCurrentPhoneScroll();
        if (p !== window.pclinkUI.currentPhonePath) {
            window.pclinkUI.phoneNavHistory = window.pclinkUI.phoneNavHistory.slice(0, window.pclinkUI.phoneHistoryIndex + 1);
            window.pclinkUI.phoneNavHistory.push(p);
            window.pclinkUI.phoneHistoryIndex = window.pclinkUI.phoneNavHistory.length - 1;
        }
        window.pclinkUI.currentPhonePath = p;
        window.pclinkUI.phoneSelectedItems.clear();
        window.pclinkUI.phoneLastSelectedIndex = null;
        window.pclinkUI.updatePhoneSelectionUI();
        window.pclinkUI.loadPhoneFiles(p);
    }
};

window.navigatePhoneBreadcrumb = (index) => {
    if (!window.pclinkUI) return;
    const target = (window.pclinkUI.phoneBreadcrumbPaths || ['/'])[index];
    if (target) window.navigatePhone(target);
};

window.refreshPhoneFiles = () => {
    if (!window.pclinkUI) return;
    window.pclinkUI.saveCurrentPhoneScroll();
    window.pclinkUI.loadPhoneFiles(window.pclinkUI.currentPhonePath);
};
window.goUpPhoneFiles = () => { if (window.pclinkUI) window.pclinkUI.goUpPhone(); };
window.goBackPhoneFiles = () => { if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex > 0) { window.pclinkUI.saveCurrentPhoneScroll(); window.pclinkUI.phoneHistoryIndex--; window.navigatePhone(window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex]); } };
window.goForwardPhoneFiles = () => { if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex < window.pclinkUI.phoneNavHistory.length - 1) { window.pclinkUI.saveCurrentPhoneScroll(); window.pclinkUI.phoneHistoryIndex++; window.navigatePhone(window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex]); } };
window.toggleItemSelection = (p) => {
    if (!window.pclinkUI) return;
    if (window.pclinkUI.phoneSelectedItems.has(p)) window.pclinkUI.phoneSelectedItems.delete(p);
    else window.pclinkUI.phoneSelectedItems.add(p);
    window.pclinkUI.saveCurrentPhoneScroll();
    window.pclinkUI.displayPhoneFiles();
};
window.toggleItemSelectionByIndex = (index, event) => {
    if (!window.pclinkUI) return;
    const ui = window.pclinkUI;
    const item = ui.phoneVisibleItems?.[index];
    if (!item) return;
    const shouldSelect = !ui.phoneSelectedItems.has(item.path);

    if (event && event.shiftKey && ui.phoneLastSelectedIndex !== null) {
        ui.applyPhoneSelectionRange(ui.phoneLastSelectedIndex, index, shouldSelect);
    } else if (shouldSelect) {
        ui.phoneSelectedItems.add(item.path);
    } else {
        ui.phoneSelectedItems.delete(item.path);
    }

    ui.phoneLastSelectedIndex = index;
    ui.saveCurrentPhoneScroll();
    ui.displayPhoneFiles();
};
window.toggleSelectAll = (checked) => { if (window.pclinkUI) window.pclinkUI.togglePhoneSelectAll(checked); };
window.invertPhoneSelection = () => { if (window.pclinkUI) window.pclinkUI.invertPhoneSelection(); };
window.clearSelection = () => {
    if (!window.pclinkUI) return;
    window.pclinkUI.phoneSelectedItems.clear();
    window.pclinkUI.phoneLastSelectedIndex = null;
    window.pclinkUI.saveCurrentPhoneScroll();
    window.pclinkUI.displayPhoneFiles();
};
window.handleFileItemClick = (e, index) => {
    const ui = window.pclinkUI;
    if (!ui) return;
    const item = ui.phoneVisibleItems?.[index];
    if (!item) return;

    if (e.ctrlKey || e.metaKey) {
        window.toggleItemSelectionByIndex(index, e);
        return;
    }

    if (e.shiftKey && ui.phoneLastSelectedIndex !== null) {
        window.toggleItemSelectionByIndex(index, e);
        return;
    }

    if (item.isDir) {
        window.navigatePhone(item.path);
    } else {
        ui.viewPhoneFile(item.path);
    }
};
window.handlePhoneSearch = (q) => { if (window.pclinkUI) { window.pclinkUI.phoneSearchQuery = q; window.pclinkUI.phoneLastSelectedIndex = null; window.pclinkUI.displayPhoneFiles(); } };
window.handlePhoneSort = (m) => {
    if (!window.pclinkUI) return;
    window.pclinkUI.phoneSortMode = m;
    window.pclinkUI.phoneLastSelectedIndex = null;
    try { localStorage.setItem('pclink.phoneSort', m); } catch (e) { }
    window.pclinkUI.displayPhoneFiles();
};
window.handleToggleHidden = (s) => {
    if (!window.pclinkUI) return;
    window.pclinkUI.phoneShowHidden = s;
    window.pclinkUI.phoneLastSelectedIndex = null;
    try { localStorage.setItem('pclink.phoneHidden', String(s)); } catch (e) { }
    window.pclinkUI.displayPhoneFiles();
};
window.triggerUpload = () => document.getElementById('phoneUploadInput').click();
window.handlePhoneUpload = async (input) => {
    if (!input.files || input.files.length === 0 || !window.pclinkUI) return;
    for (const f of input.files) await window.pclinkUI.uploadFile(f);
    window.refreshPhoneFiles();
    input.value = '';
};
window.deleteSelectedItems = () => {
    if (!window.pclinkUI) return;
    const paths = Array.from(window.pclinkUI.phoneSelectedItems);
    window.pclinkUI.deletePhoneItems(paths);
};
window.deletePhoneItemByIndex = (index) => {
    const item = window.pclinkUI?.phoneVisibleItems?.[index];
    if (item) window.pclinkUI.deletePhoneItems([item.path]);
};
window.downloadSelectedItems = () => {
    if (!window.pclinkUI) return;
    window.pclinkUI.downloadPhoneSelection(Array.from(window.pclinkUI.phoneSelectedItems));
};
window.downloadPhoneFile = (p) => { if (window.pclinkUI) window.pclinkUI.downloadPhoneFile(p); };
window.downloadPhoneFileByIndex = (index) => {
    const item = window.pclinkUI?.phoneVisibleItems?.[index];
    if (item) window.pclinkUI.downloadPhoneFile(item.path);
};
window.renamePhoneItemByIndex = (index) => {
    const item = window.pclinkUI?.phoneVisibleItems?.[index];
    if (item) window.pclinkUI.renamePhoneItem(item.path, item.name, item.isDir);
};
window.createPhoneFolder = () => { if (window.pclinkUI) window.pclinkUI.createPhoneFolder(); };
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
            if (window.pclinkUI.phoneIsReadOnly) {
                window.pclinkUI.showToast('Read-only storage', 'Uploads are disabled for this device.', 'error');
                return;
            }
            for (const f of e.dataTransfer.files) await window.pclinkUI.uploadFile(f);
            window.refreshPhoneFiles();
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        if (!window.pclinkUI) return;
        window.pclinkUI.applyPhonePreferences();
        window.pclinkUI.setupPhoneKeyboardShortcuts();
    }, 0);
});
