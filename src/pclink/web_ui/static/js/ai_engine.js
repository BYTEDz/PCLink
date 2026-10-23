// static/js/ai_engine.js
// PCLink Local AI Subsystem (llama.cpp engine, drag-and-drop GGUF importer, Hugging Face Model Hub, and Chat Playground)

window._aiServiceRunning = false;
window._aiEngineInstalled = false;
window._aiActiveModel = null;
window._aiDownloadPollingInterval = null;
window._aiEnginePollingInterval = null;
window._aiChatHistory = [];
window._lastAiCatalogSignature = null;
window._lastAiModelsRevision = null;

// Escaping helpers: model ids, filenames, and Hugging Face metadata are
// untrusted input and must never be interpolated raw into innerHTML/onclick.
// This intentionally does not delegate to pclinkUI.escapeHTML: that helper
// relies on textContent/innerHTML and therefore leaves quotes unescaped,
// which is unsafe in attribute and inline-handler contexts.
window.aiEscape = (value) => {
    const str = value === null || value === undefined ? '' : String(value);
    return str.replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
};

// Produces an HTML-attribute-safe JSON string literal for inline handlers.
window.aiArg = (value) => window.aiEscape(JSON.stringify(String(value ?? '')));

// Tab Initialization
window.loadAiEngineTab = async () => {
    window.setupGgufDragAndDrop();
    await window.refreshAiTab();
    await window.checkActiveDownload();
    await window.checkActiveEngineDownload();
};

window.safeRenderAiIcons = () => {
    if (window.feather) {
        try {
            window.feather.replace();
        } catch (e) {
            console.warn("Feather icon render caught non-fatal issue:", e);
        }
    }
};

window.copyAiEndpoint = async () => {
    const fullUrl = `${window.location.origin}/ai/v1/chat/completions`;
    try {
        await navigator.clipboard.writeText(fullUrl);
        window.pclinkUI.showToast("Copied", "OpenAI-compatible endpoint copied to clipboard", "success");
    } catch (e) {
        window.pclinkUI.showToast("Error", "Could not copy to clipboard", "error");
    }
};

// ==========================================
// 1. Drag & Drop and File Selector Engine
// ==========================================

window.setupGgufDragAndDrop = () => {
    const dropZone = document.getElementById('aiGgufDropZone');
    const fileInput = document.getElementById('aiGgufFileInput');
    if (!dropZone || !fileInput) return;

    if (dropZone._dragSetupDone) return;
    dropZone._dragSetupDone = true;

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('border-primary', 'bg-primary/10', 'scale-[1.005]');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('border-primary', 'bg-primary/10', 'scale-[1.005]');
        }, false);
    });

    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files.length > 0) {
            window.handleGgufFileUpload(files[0]);
        }
    }, false);

    fileInput.addEventListener('change', (e) => {
        if (fileInput.files && fileInput.files.length > 0) {
            window.handleGgufFileUpload(fileInput.files[0]);
            fileInput.value = '';
        }
    }, false);
};

window.handleGgufFileUpload = (file) => {
    if (!file.name.toLowerCase().endsWith('.gguf')) {
        window.pclinkUI.showToast("Invalid File", "Only .gguf model weights are supported", "warning");
        return;
    }

    const uploadCard = document.getElementById('ai_upload_progress_card');
    const nameEl = document.getElementById('ai_upload_filename');
    const statsEl = document.getElementById('ai_upload_stats');
    const barEl = document.getElementById('ai_upload_bar');

    if (uploadCard) uploadCard.classList.remove('hidden');
    if (nameEl) nameEl.textContent = `Importing ${file.name}...`;
    if (barEl) barEl.value = 0;
    if (statsEl) statsEl.textContent = `0 MB / ${(file.size / (1024 * 1024)).toFixed(1)} MB (0%)`;

    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/ai/models/upload', true);
    xhr.withCredentials = true;

    const token = window.pclinkUI?.getToken?.() || window.localStorage?.getItem('pclink_token');
    if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            const loadedMb = (e.loaded / (1024 * 1024)).toFixed(1);
            const totalMb = (e.total / (1024 * 1024)).toFixed(1);

            if (barEl) barEl.value = percent;
            if (statsEl) statsEl.textContent = `${loadedMb} MB / ${totalMb} MB (${percent}%)`;
        }
    };

    xhr.onload = async () => {
        if (uploadCard) uploadCard.classList.add('hidden');
        if (xhr.status >= 200 && xhr.status < 300) {
            window.pclinkUI.showToast("Model Imported", `${file.name} registered in library`, "success");
            await window.refreshAiTab();
        } else {
            let errorMsg = "Upload failed";
            try {
                const res = JSON.parse(xhr.responseText);
                errorMsg = res.detail || errorMsg;
            } catch (err) { }
            window.pclinkUI.showToast("Import Failed", errorMsg, "error");
        }
    };

    xhr.onerror = () => {
        if (uploadCard) uploadCard.classList.add('hidden');
        window.pclinkUI.showToast("Error", "Network error importing model file", "error");
    };

    xhr.send(formData);
};

// ==========================================
// 2. Status & Diagnostics Refresh (Flicker-Free)
// ==========================================

window.refreshAiTab = async () => {
    // Avoid pointless network traffic while the browser tab is in the background.
    if (document.hidden) return;

    const statusBanner = document.getElementById('aiEngineStatusBanner');
    const statusIcon = document.getElementById('aiEngineStatusIcon');
    const statusTitle = document.getElementById('aiEngineStatusTitle');
    const statusDesc = document.getElementById('aiEngineStatusDesc');
    const engineBadge = document.getElementById('ai_engine_badge');
    const heroModelBadge = document.getElementById('ai_hero_model_badge');
    const heroModelName = document.getElementById('ai_hero_model_name');
    const heroBuildTag = document.getElementById('ai_hero_build_tag');
    const activeBuildTag = document.getElementById('ai_active_build_tag');
    const processStatus = document.getElementById('ai_process_status');
    const activeModelName = document.getElementById('ai_active_model_name');
    const missingPrompt = document.getElementById('ai_engine_missing_prompt');
    const toggleBtn = document.getElementById('btn_toggle_ai_service');

    try {
        const res = await window.pclinkUI.webUICall('/ai/status');
        if (!res.ok) throw new Error("Failed to fetch AI subsystem status");
        const data = await res.json();

        const state = data.engine_state || (data.is_running ? 'ready' : 'stopped');
        const port = data.port || 38191;
        const cfg = data.config || {};
        window._aiServiceRunning = state === 'ready';
        window._aiEngineInstalled = data.engine_installed;
        window._aiActiveModel = data.active_model;
        window._aiPort = port;

        // Keep tunnelled/remote users honest: the backend GUI only exists on
        // the host's loopback interface.
        const backendUrl = `http://127.0.0.1:${port}`;
        const backendLink = document.getElementById('ai_direct_backend_link');
        const backendOpen = document.getElementById('ai_direct_backend_open');
        if (backendLink) {
            backendLink.href = backendUrl;
            backendLink.textContent = backendUrl;
        }
        if (backendOpen) backendOpen.href = backendUrl;

        const contextEl = document.getElementById('ai_context_size');
        if (contextEl) {
            const ctx = Number(cfg.context_size);
            contextEl.textContent = ctx > 0
                ? `${ctx.toLocaleString()} tokens`
                : 'Default';
        }
        const gpuEl = document.getElementById('ai_gpu_offload');
        if (gpuEl) {
            const layers = Number(cfg.gpu_layers);
            gpuEl.textContent = layers === 0 ? 'CPU only' : `${layers} layers`;
        }
        const idleEl = document.getElementById('ai_idle_timeout');
        const idleGuardText = document.getElementById('ai_idle_guard_text');
        const idleSeconds = Number(cfg.idle_timeout_seconds);
        const idleLabel = idleSeconds > 0
            ? (idleSeconds >= 60 ? `${Math.round(idleSeconds / 60)}m idle timeout` : `${idleSeconds}s idle timeout`)
            : 'Disabled';
        if (idleEl) idleEl.textContent = idleLabel;
        if (idleGuardText) {
            idleGuardText.textContent = idleSeconds > 0
                ? `Model weights automatically unload after ${idleSeconds >= 60 ? Math.round(idleSeconds / 60) + 'm' : idleSeconds + 's'} of inactivity to release VRAM.`
                : 'Automatic idle unloading is disabled; the model stays resident until stopped.';
        }

        if (state === 'starting' || state === 'loading') {
            if (!window._aiStatusFastPolling) {
                window._aiStatusFastPolling = setInterval(() => {
                    window.refreshAiTab();
                }, 1200);
            }
        } else if (window._aiStatusFastPolling) {
            clearInterval(window._aiStatusFastPolling);
            window._aiStatusFastPolling = null;
        }

        // 1. Header Engine Badge
        if (engineBadge) {
            if (state === 'ready') {
                engineBadge.className = "badge badge-success text-white font-mono font-bold text-[10px]";
                engineBadge.textContent = `RUNNING (:${port})`;
            } else if (state === 'starting' || state === 'loading') {
                const percent = data.loading_progress
                    ? ` (${Math.round(data.loading_progress)}%)`
                    : '';
                engineBadge.className = "badge badge-warning text-white font-mono font-bold text-[10px] animate-pulse";
                engineBadge.textContent = `LOADING${percent}`;
            } else if (state === 'error') {
                engineBadge.className = "badge badge-error text-white font-mono font-bold text-[10px]";
                engineBadge.textContent = "ENGINE ERROR";
            } else if (data.engine_installed) {
                engineBadge.className = "badge badge-primary text-white font-mono font-bold text-[10px]";
                engineBadge.textContent = "ENGINE READY";
            } else {
                engineBadge.className = "badge badge-error text-white font-mono font-bold text-[10px]";
                engineBadge.textContent = "ENGINE MISSING";
            }
        }

        // 2. Hero Model & Build Tags
        if (heroModelBadge && heroModelName) {
            const currentModel = data.loading_model || data.active_model;
            if (currentModel) {
                heroModelName.textContent = currentModel;
                heroModelBadge.title = `Model: ${currentModel}`;
                heroModelBadge.classList.remove('hidden');
            } else {
                heroModelBadge.classList.add('hidden');
            }
        }
        if (heroBuildTag) {
            heroBuildTag.textContent = data.active_engine_tag || "None";
        }

        // 3. Specifications Card
        if (activeBuildTag) activeBuildTag.textContent = data.active_engine_tag || "None";
        if (processStatus) {
            if (state === 'ready') {
                processStatus.className = "badge badge-success text-white text-[10px] font-semibold";
                processStatus.textContent = `Ready (:${port})`;
            } else if (state === 'starting' || state === 'loading') {
                processStatus.className = "badge badge-warning text-white text-[10px] font-semibold";
                processStatus.textContent = data.loading_message || "Loading Model...";
            } else if (state === 'error') {
                processStatus.className = "badge badge-error text-white text-[10px] font-semibold";
                processStatus.textContent = "Startup Error";
            } else {
                processStatus.className = "badge badge-neutral text-[10px] font-semibold";
                processStatus.textContent = "Stopped (Idle)";
            }
        }
        if (activeModelName) {
            activeModelName.textContent = data.loading_model || data.active_model || "None selected";
            activeModelName.title = activeModelName.textContent;
        }

        // 4. Start/Stop Service Button (Preserving exact w-36 width & centered alignment)
        if (toggleBtn) {
            if (state === 'ready') {
                toggleBtn.className = "btn btn-sm btn-error text-white font-semibold text-xs gap-1.5 shadow-xs w-36 justify-center";
                toggleBtn.innerHTML = `<i data-feather="square" class="w-4 h-4"></i> Stop Runner`;
                toggleBtn.disabled = false;
            } else if (state === 'starting' || state === 'loading') {
                toggleBtn.className = "btn btn-sm btn-warning text-white font-semibold text-xs gap-1.5 shadow-xs w-36 justify-center";
                toggleBtn.innerHTML = `<span class="loading loading-spinner loading-xs"></span> Loading...`;
                toggleBtn.disabled = true;
            } else {
                toggleBtn.className = "btn btn-sm btn-outline btn-primary font-semibold text-xs gap-1.5 shadow-xs w-36 justify-center";
                toggleBtn.innerHTML = `<i data-feather="power" class="w-4 h-4"></i> Start Runner`;
                toggleBtn.disabled = !data.engine_installed || !data.model_installed;
            }
        }

        // 5. Missing Engine Notice
        if (missingPrompt) {
            missingPrompt.classList.toggle('hidden', data.engine_installed);
        }

        // 6. Header Banner Accent (Never mutating base layout classes to avoid layout shifting)
        if (statusBanner) {
            statusBanner.classList.toggle('border-l-4', true);
            statusBanner.classList.toggle('border-l-success', state === 'ready');
            statusBanner.classList.toggle(
                'border-l-warning',
                state === 'starting' || state === 'loading' || !data.engine_installed
            );
            statusBanner.classList.toggle('border-l-error', state === 'error');
            statusBanner.classList.toggle(
                'border-l-primary',
                state === 'stopped' && data.engine_installed
            );

            if (state === 'ready') {
                if (statusIcon) statusIcon.innerHTML = `<i data-feather="check-circle" class="w-5 h-5 text-success"></i>`;
                if (statusTitle) statusTitle.textContent = "Local AI Engine Ready";
                if (statusDesc) statusDesc.textContent = `Serving ${data.active_model} on port ${data.port}. Auto-idle monitoring enabled.`;
            } else if (state === 'starting' || state === 'loading') {
                if (statusIcon) statusIcon.innerHTML = `<span class="loading loading-spinner loading-sm text-warning"></span>`;
                if (statusTitle) statusTitle.textContent = `Loading ${data.loading_model || data.active_model || 'model'}...`;
                if (statusDesc) statusDesc.textContent = data.loading_message || "Transferring weights to memory and allocating context...";
            } else if (state === 'error') {
                if (statusIcon) statusIcon.innerHTML = `<i data-feather="alert-octagon" class="w-5 h-5 text-error"></i>`;
                if (statusTitle) statusTitle.textContent = "Runner Initialization Error";
                if (statusDesc) statusDesc.textContent = data.error_message || "Process terminated. Check server logs or VRAM allocation.";
            } else if (data.engine_installed) {
                if (statusIcon) statusIcon.innerHTML = `<i data-feather="cpu" class="w-5 h-5 text-primary"></i>`;
                if (statusTitle) statusTitle.textContent = "Local AI Engine Ready";
                if (statusDesc) statusDesc.textContent = "llama.cpp runtime installed. Ready for local inference requests.";
            } else {
                if (statusIcon) statusIcon.innerHTML = `<i data-feather="alert-triangle" class="w-5 h-5 text-warning"></i>`;
                if (statusTitle) statusTitle.textContent = "Runtime Engine Required";
                if (statusDesc) statusDesc.textContent = "Download the llama.cpp engine binary to enable local model execution.";
            }
        }

        // Load GGUF model catalog only when the server-side revision changed.
        await window.loadAiModelsCatalog(data.models_revision);

    } catch (e) {
        // Poll failures are expected during restarts; do not spam the user.
        const now = Date.now();
        if (!window._aiLastErrorToast || now - window._aiLastErrorToast > 30000) {
            window._aiLastErrorToast = now;
            window.pclinkUI.showToast("Error", "Failed to retrieve local AI engine status", "error");
        }
    }

    window.safeRenderAiIcons();
};

// ==========================================
// 3. Installed Models Library (Smart Diffing)
// ==========================================

window._extractQuantizationTag = (filename) => {
    const match = filename.match(/[-_.]([qQiIfFbB][0-9a-zA-Z_]+)\.gguf$/i);
    return match ? match[1].toUpperCase() : null;
};

window.loadAiModelsCatalog = async (revision = null) => {
    const installedContainer = document.getElementById('ai_installed_models_container');
    const badgeEl = document.getElementById('ai_installed_count_badge');

    if (!installedContainer) return;

    // Status responses carry a models_revision, so avoid a second request
    // every 5 seconds when nothing changed on disk.
    if (
        revision !== null &&
        revision === window._lastAiModelsRevision &&
        window._lastAiCatalogSignature
    ) {
        return;
    }

    try {
        const res = await window.pclinkUI.webUICall('/ai/models/catalog');
        if (!res.ok) throw new Error();
        const data = await res.json();

        const installedList = data.installed || [];
        window._lastAiModelsRevision = data.models_revision || revision || null;

        if (badgeEl) {
            badgeEl.textContent = `${installedList.length} Models`;
        }

        // Check if catalog data has changed to prevent DOM flickering
        const catalogSignature = `${data.active_model}|${window._aiEngineInstalled}|` +
            installedList.map(m => `${m.filename}:${m.size_bytes}:${m.is_active}`).join(';');

        if (window._lastAiCatalogSignature === catalogSignature) {
            return; // No layout update needed
        }
        window._lastAiCatalogSignature = catalogSignature;

        installedContainer.innerHTML = '';
        if (installedList.length === 0) {
            installedContainer.innerHTML = `
                <div class="text-center py-8 px-4 border border-dashed border-base-300 rounded-xl bg-base-200/20 text-xs opacity-60">
                    No models in library yet. Drop a <span class="font-mono text-primary">.gguf</span> model above or click <strong>Model Hub</strong> to download one.
                </div>
            `;
            return;
        }

        // Separate active model (pinned to top) from other installed weights
        const activeModel = installedList.find(m => m.is_active || m.filename === data.active_model);
        const inactiveModels = installedList.filter(m => !(m.is_active || m.filename === data.active_model));

        // 1. Pinned Active Model Hero Card
        if (activeModel) {
            const activeCard = document.createElement('div');
            const quantTag = window._extractQuantizationTag(activeModel.filename);
            const safeName = window.aiEscape(activeModel.filename);
            const safePath = window.aiEscape(activeModel.path || 'Loaded in local engine');

            activeCard.className = "flex flex-col sm:flex-row items-start sm:items-center justify-between p-3.5 border border-primary/40 border-l-4 border-l-primary bg-primary/[0.04] rounded-xl shadow-xs transition-all gap-3";
            activeCard.innerHTML = `
                <div class="space-y-1 min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="badge badge-primary badge-outline text-[9px] font-mono font-bold px-1.5 h-4 min-h-0 uppercase">Active Runner</span>
                        <h5 class="font-bold text-xs font-mono truncate max-w-[280px] text-primary" title="${safeName}">
                            ${safeName}
                        </h5>
                        ${quantTag ? `<span class="badge badge-sm badge-outline font-mono text-[9px] px-1.5 h-4 min-h-0 font-bold">${window.aiEscape(quantTag)}</span>` : ''}
                        <span class="badge badge-sm badge-neutral font-mono text-[9px] px-1.5 h-4 min-h-0 font-semibold">${window.aiEscape(activeModel.size_formatted)}</span>
                        ${activeModel.is_symlink ? `<span class="badge badge-sm badge-ghost text-[9px] px-1.5 h-4 min-h-0">Symlinked</span>` : ''}
                    </div>
                    <p class="text-[10px] opacity-60 font-mono truncate max-w-[340px]" title="${safePath}">
                        ${safePath}
                    </p>
                </div>
                <div class="shrink-0 flex items-center gap-2">
                    <button class="btn btn-xs btn-primary text-white font-semibold gap-1" onclick="window.openAiChatModal()" title="Evaluate in chat">
                        <i data-feather="message-square" class="w-3.5 h-3.5"></i> Chat
                    </button>
                    <button class="btn btn-xs btn-ghost text-error/80 hover:text-error p-1 h-6 min-h-0" title="Delete model" onclick="window.deleteAiModel(${window.aiArg(activeModel.filename)})">
                        <i data-feather="trash-2" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            `;
            installedContainer.appendChild(activeCard);
        }

        // 2. Inactive Model Weights List
        inactiveModels.forEach(m => {
            const card = document.createElement('div');
            const quantTag = window._extractQuantizationTag(m.filename);
            const safeName = window.aiEscape(m.filename);
            const safePath = window.aiEscape(m.path || 'Local storage');

            card.className = "flex flex-col sm:flex-row items-start sm:items-center justify-between p-3.5 border border-base-300 bg-base-200/30 hover:bg-base-200/60 rounded-xl transition-all gap-3";

            let actionArea = '';
            if (!window._aiEngineInstalled) {
                actionArea = `<button class="btn btn-xs btn-neutral opacity-50 font-semibold" disabled>Engine Required</button>`;
            } else {
                actionArea = `
                    <div class="flex items-center gap-1.5">
                        <button class="btn btn-xs btn-outline btn-primary font-semibold gap-1" onclick="window.selectAiModel(${window.aiArg(m.filename)})">
                            <i data-feather="check" class="w-3 h-3"></i> Activate
                        </button>
                        <button class="btn btn-xs btn-ghost text-error/80 hover:text-error p-1 h-6 min-h-0" title="Delete model" onclick="window.deleteAiModel(${window.aiArg(m.filename)})">
                            <i data-feather="trash-2" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                `;
            }

            card.innerHTML = `
                <div class="space-y-1 min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                        <h5 class="font-bold text-xs font-mono truncate max-w-[280px] text-base-content/90" title="${safeName}">
                            ${safeName}
                        </h5>
                        ${quantTag ? `<span class="badge badge-sm badge-outline font-mono text-[9px] px-1.5 h-4 min-h-0 font-bold">${window.aiEscape(quantTag)}</span>` : ''}
                        <span class="badge badge-sm badge-neutral font-mono text-[9px] px-1.5 h-4 min-h-0 font-semibold">${window.aiEscape(m.size_formatted)}</span>
                        ${m.is_symlink ? `<span class="badge badge-sm badge-ghost text-[9px] px-1.5 h-4 min-h-0">Symlinked</span>` : ''}
                    </div>
                    <p class="text-[10px] opacity-60 font-mono truncate max-w-[340px]" title="${safePath}">
                        ${safePath}
                    </p>
                </div>
                <div class="shrink-0 flex items-center">
                    ${actionArea}
                </div>
            `;
            installedContainer.appendChild(card);
        });

    } catch (e) {
        installedContainer.innerHTML = `<div class="text-center py-4 text-xs text-error font-semibold">Failed to load local models.</div>`;
    }

    window.safeRenderAiIcons();
};

window.openAiModelsFolder = async () => {
    try {
        const res = await window.pclinkUI.webUICall('/ai/models/open-folder', { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast("Folder Opened", "Models directory opened in file manager", "success");
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Error", err.detail || "Could not open folder on host", "error");
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed to communicate with host", "error");
    }
};

window.downloadAiModel = async (modelId, customUrl = null, customName = null) => {
    try {
        window.pclinkUI.showToast("Connecting", "Initiating model download...", "info");
        const res = await window.pclinkUI.webUICall('/ai/models/download', {
            method: 'POST',
            body: JSON.stringify({
                model_id: modelId,
                url: customUrl,
                filename: customName
            })
        });

        if (res.ok) {
            window.startDownloadPolling();
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Download Failed", err.detail || "Could not start download", "error");
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Connection error requesting model download", "error");
    }
};

window.startDownloadPolling = () => {
    const card = document.getElementById('ai_download_progress_card');
    if (card) card.classList.remove('hidden');

    if (window._aiDownloadPollingInterval) clearInterval(window._aiDownloadPollingInterval);

    window._aiDownloadPollingInterval = setInterval(async () => {
        try {
            const res = await window.pclinkUI.webUICall('/ai/models/download-progress');
            if (!res.ok) return;
            const data = await res.json();

            const fn = document.getElementById('ai_dl_filename');
            const stats = document.getElementById('ai_dl_stats');
            const bar = document.getElementById('ai_dl_bar');

            if (data.status === 'downloading') {
                if (fn) fn.textContent = `Downloading ${data.filename}...`;
                const dlMb = (data.bytes_downloaded / (1024 * 1024)).toFixed(1);
                const totalMb = (data.total_bytes / (1024 * 1024)).toFixed(1);
                const speed = data.speed_bps > 0
                    ? ` · ${(data.speed_bps / (1024 * 1024)).toFixed(1)} MB/s`
                    : '';
                const remaining = (data.speed_bps > 0 && data.total_bytes > data.bytes_downloaded)
                    ? ` · ${Math.max(1, Math.round((data.total_bytes - data.bytes_downloaded) / data.speed_bps))}s left`
                    : '';
                if (stats) stats.textContent = `${dlMb} MB / ${totalMb} MB (${data.percent}%)${speed}${remaining}`;
                if (bar) bar.value = data.percent;
            } else if (data.status === 'completed') {
                clearInterval(window._aiDownloadPollingInterval);
                if (card) card.classList.add('hidden');
                window.pclinkUI.showToast("Download Complete", `${data.filename} is ready for inference`, "success");
                window._lastAiCatalogSignature = null;
                window._lastAiModelsRevision = null;
                await window.refreshAiTab();
            } else if (data.status === 'failed') {
                clearInterval(window._aiDownloadPollingInterval);
                if (card) card.classList.add('hidden');
                window.pclinkUI.showToast("Download Failed", data.error || "Model download failed", "error");
                await window.refreshAiTab();
            } else if (data.status === 'cancelled') {
                clearInterval(window._aiDownloadPollingInterval);
                if (card) card.classList.add('hidden');
                window.pclinkUI.showToast("Cancelled", "Model download cancelled", "info");
                await window.refreshAiTab();
            }
        } catch (e) { }
    }, 1000);
};

window.checkActiveDownload = async () => {
    try {
        const res = await window.pclinkUI.webUICall('/ai/models/download-progress');
        if (res.ok) {
            const data = await res.json();
            if (data.status === 'downloading') {
                window.startDownloadPolling();
            }
        }
    } catch (e) { }
};

window.cancelAiModelDownload = async () => {
    try {
        await window.pclinkUI.webUICall('/ai/models/download/cancel', { method: 'POST' });
    } catch (e) { }
};

window.selectAiModel = async (filename) => {
    try {
        window.pclinkUI.showToast("Switching Model", `Loading ${filename} into memory...`, "info");
        const res = await window.pclinkUI.webUICall('/ai/models/select', {
            method: 'POST',
            body: JSON.stringify({ filename, start_engine: true })
        });
        if (res.ok) {
            window._lastAiCatalogSignature = null;
            window._lastAiModelsRevision = null;
            await window.refreshAiTab();
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Error", err.detail || "Failed to select model", "error");
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed to switch active model", "error");
    }
};

window.deleteAiModel = async (filename) => {
    if (!confirm(`Delete GGUF model ${filename}? This will release disk space on the host.`)) return;
    try {
        const res = await window.pclinkUI.webUICall(`/ai/models/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            window.pclinkUI.showToast("Deleted", `Removed ${filename}`, "info");
            window._lastAiCatalogSignature = null;
            window._lastAiModelsRevision = null;
            await window.refreshAiTab();
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Delete Failed", err.detail || "Failed to delete file", "error");
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed to delete model file", "error");
    }
};

window.promptCustomGgufDownload = () => {
    const url = prompt("Enter direct Hugging Face GGUF download URL:");
    if (!url || !url.trim()) return;
    const name = prompt("Target filename (e.g. Model-Q4_K_M.gguf):");
    window.downloadAiModel(null, url.trim(), name ? name.trim() : null);
};

// ==========================================
// 4. Hugging Face Model Hub (Curated + Search)
// ==========================================

window.openHfExplorerModal = async () => {
    const title = `<i data-feather="globe" class="w-4 h-4 text-primary"></i> Hugging Face Model Hub`;
    const body = `
        <div class="space-y-3">
            <div class="tabs tabs-boxed bg-base-200 p-1 mb-2">
                <a class="tab tab-active font-semibold text-xs" id="hfTabCurated" onclick="window.switchHfModalTab('curated')">
                    <i data-feather="star" class="w-3.5 h-3.5 mr-1.5"></i> Curated Starter Weights
                </a>
                <a class="tab font-semibold text-xs" id="hfTabSearch" onclick="window.switchHfModalTab('search')">
                    <i data-feather="search" class="w-3.5 h-3.5 mr-1.5"></i> Search Hub
                </a>
            </div>

            <!-- Tab 1: Recommended Starters -->
            <div id="hfSectionCurated" class="space-y-2">
                <p class="text-[11px] opacity-70 mb-2">
                    Verified lightweight instruction models tailored for local device execution and structured outputs.
                </p>
                <div id="hfCuratedList" class="space-y-2 max-h-[440px] overflow-y-auto pr-1">
                    <div class="text-center py-6 opacity-40 text-xs">Loading recommendations...</div>
                </div>
            </div>

            <!-- Tab 2: Live Hub Search & Quants Inspector -->
            <div id="hfSectionSearch" class="space-y-3 hidden">
                <div class="flex gap-2">
                    <input type="text" id="hfSearchInput" class="input input-sm input-bordered w-full text-xs font-mono"
                           placeholder="Search models (e.g. qwen, llama, smollm)..."
                           onkeydown="if(event.key==='Enter') window.triggerHfSearch()">
                    <button class="btn btn-sm btn-primary text-white font-semibold" onclick="window.triggerHfSearch()">
                        <i data-feather="search" class="w-3.5 h-3.5"></i> Search
                    </button>
                </div>

                <div class="flex items-center gap-1.5 flex-wrap">
                    <span class="text-[10px] opacity-60 font-semibold uppercase mr-1">Presets:</span>
                    <button class="btn btn-xs btn-outline btn-neutral" onclick="window.applyHfFilter('smollm gguf')">SmolLM2 (&lt;1B)</button>
                    <button class="btn btn-xs btn-outline btn-neutral" onclick="window.applyHfFilter('qwen 0.5b gguf')">Qwen 0.5B</button>
                    <button class="btn btn-xs btn-outline btn-neutral" onclick="window.applyHfFilter('llama 3.2 1b gguf')">Llama 1B</button>
                    <button class="btn btn-xs btn-outline btn-neutral" onclick="window.applyHfFilter('granite gguf')">IBM Granite</button>
                </div>

                <div id="hfSearchResultsList" class="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                    <div class="text-center py-6 opacity-50 text-xs">Select a preset or search for repositories above.</div>
                </div>

                <div id="hfQuantView" class="hidden space-y-3">
                    <div class="flex items-center justify-between border-b border-base-300 pb-2">
                        <button class="btn btn-xs btn-ghost gap-1 text-primary font-semibold" onclick="window.backToHfSearch()">
                            <i data-feather="arrow-left" class="w-3.5 h-3.5"></i> Back to search
                        </button>
                        <span id="hfSelectedModelName" class="font-mono text-xs font-bold truncate max-w-[200px]"></span>
                    </div>
                    <p class="text-[11px] opacity-70">
                        Select target quantization format. <strong class="text-primary font-mono">Q4_K_M</strong> offers optimal perplexity and speed.
                    </p>
                    <div id="hfQuantsList" class="space-y-2 max-h-[340px] overflow-y-auto pr-1"></div>
                </div>
            </div>
        </div>
    `;

    const footer = `
        <button class="btn btn-xs btn-neutral ml-auto" onclick="window.closeSidePanel()">Close</button>
    `;

    window.openSidePanel(title, body, footer);
    await window.loadHfCuratedList();
    window.safeRenderAiIcons();
};

window.switchHfModalTab = (tab) => {
    const tabCur = document.getElementById('hfTabCurated');
    const tabSea = document.getElementById('hfTabSearch');
    const secCur = document.getElementById('hfSectionCurated');
    const secSea = document.getElementById('hfSectionSearch');

    if (!tabCur || !tabSea || !secCur || !secSea) return;

    if (tab === 'curated') {
        tabCur.classList.add('tab-active');
        tabSea.classList.remove('tab-active');
        secCur.classList.remove('hidden');
        secSea.classList.add('hidden');
    } else {
        tabSea.classList.add('tab-active');
        tabCur.classList.remove('tab-active');
        secSea.classList.remove('hidden');
        secCur.classList.add('hidden');
        window.triggerHfSearch();
    }
    window.safeRenderAiIcons();
};

window.loadHfCuratedList = async () => {
    const listEl = document.getElementById('hfCuratedList');
    if (!listEl) return;

    try {
        const res = await window.pclinkUI.webUICall('/ai/models/catalog');
        if (!res.ok) throw new Error();
        const data = await res.json();
        const curated = data.curated || [];
        const installedFilenames = new Set((data.installed || []).map(m => m.filename));

        listEl.innerHTML = '';
        curated.forEach(cm => {
            const isInstalled = installedFilenames.has(cm.filename);
            const card = document.createElement('div');
            card.className = "border border-base-300 rounded-xl p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 bg-base-100 hover:bg-base-200/50 transition-colors";

            let actionBtn = '';
            if (isInstalled) {
                actionBtn = `<span class="badge badge-neutral text-[10px] font-semibold">Installed</span>`;
            } else {
                actionBtn = `
                    <button class="btn btn-xs btn-primary text-white font-semibold gap-1" onclick="window.downloadAiModel(${window.aiArg(cm.id)}); window.closeSidePanel();">
                        <i data-feather="download" class="w-3 h-3"></i> Get (${window.aiEscape(cm.size_formatted)})
                    </button>
                `;
            }

            card.innerHTML = `
                <div class="space-y-0.5">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="font-bold text-xs text-primary">${window.aiEscape(cm.name)}</span>
                        ${cm.badge ? `<span class="badge badge-primary badge-outline text-[9px] font-bold px-1.5 h-4 min-h-0">${window.aiEscape(cm.badge)}</span>` : ''}
                    </div>
                    <p class="text-[11px] opacity-70">${window.aiEscape(cm.description || "")}</p>
                </div>
                <div class="shrink-0">${actionBtn}</div>
            `;
            listEl.appendChild(card);
        });

    } catch (e) {
        listEl.innerHTML = `<div class="text-center py-4 text-xs text-error">Failed loading starter models.</div>`;
    }

    window.safeRenderAiIcons();
};

window.applyHfFilter = (query) => {
    const input = document.getElementById('hfSearchInput');
    if (input) input.value = query;
    window.triggerHfSearch();
};

window.triggerHfSearch = async () => {
    const input = document.getElementById('hfSearchInput');
    const query = input ? input.value.trim() : '';
    const listEl = document.getElementById('hfSearchResultsList');
    if (!listEl) return;

    window.backToHfSearch();

    listEl.innerHTML = `
        <div class="text-center py-8 opacity-50 text-xs">
            <span class="loading loading-spinner loading-xs mr-2"></span> Querying Hugging Face Hub...
        </div>
    `;

    try {
        const endpoint = query ? `/ai/models/hf/search?q=${encodeURIComponent(query)}` : '/ai/models/hf/search';
        const res = await window.pclinkUI.webUICall(endpoint);
        if (!res.ok) throw new Error();
        const models = await res.json();

        listEl.innerHTML = '';
        if (!models || models.length === 0) {
            listEl.innerHTML = `<div class="text-center py-8 text-xs opacity-50">No GGUF models matched your query.</div>`;
            return;
        }

        models.forEach(m => {
            const card = document.createElement('div');
            card.className = "border border-base-300 rounded-xl p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 bg-base-100 hover:bg-base-200/50 transition-colors";
            card.innerHTML = `
                <div class="space-y-0.5">
                    <div class="flex items-center gap-1.5 flex-wrap">
                        <span class="font-bold text-xs text-primary">${window.aiEscape(m.name)}</span>
                        <span class="badge badge-neutral text-[9px] font-mono px-1.5 h-4 min-h-0">${window.aiEscape(m.author)}</span>
                    </div>
                    <div class="flex items-center gap-3 text-[10px] opacity-60 font-mono">
                        <span><i data-feather="download" class="w-3 h-3 inline"></i> ${Number(m.downloads || 0).toLocaleString()}</span>
                        <span><i data-feather="heart" class="w-3 h-3 inline"></i> ${Number(m.likes || 0).toLocaleString()}</span>
                    </div>
                </div>
                <div class="shrink-0">
                    <button class="btn btn-xs btn-outline btn-primary font-semibold gap-1" onclick="window.inspectHfModel(${window.aiArg(m.id)})">
                        <i data-feather="layers" class="w-3 h-3"></i> Inspect Quants
                    </button>
                </div>
            `;
            listEl.appendChild(card);
        });

    } catch (e) {
        listEl.innerHTML = `<div class="text-center py-6 text-xs text-error font-semibold">Failed to search Hugging Face models.</div>`;
    }

    window.safeRenderAiIcons();
};

window.inspectHfModel = async (modelId) => {
    const searchList = document.getElementById('hfSearchResultsList');
    const quantView = document.getElementById('hfQuantView');
    const titleEl = document.getElementById('hfSelectedModelName');
    const quantsList = document.getElementById('hfQuantsList');

    if (searchList) searchList.classList.add('hidden');
    if (quantView) quantView.classList.remove('hidden');
    if (titleEl) titleEl.textContent = modelId;

    if (quantsList) {
        quantsList.innerHTML = `
            <div class="text-center py-8 opacity-50 text-xs">
                <span class="loading loading-spinner loading-xs mr-2"></span> Inspecting repository file tree...
            </div>
        `;
    }

    try {
        const res = await window.pclinkUI.webUICall(`/ai/models/hf/files?model_id=${encodeURIComponent(modelId)}`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        const files = Array.isArray(data) ? data : (data.files || []);
        const suggestions = data.suggested_repos || [];

        if (!quantsList) return;
        quantsList.innerHTML = '';

        if (!files || files.length === 0) {
            let suggestionsHtml = '';
            if (suggestions && suggestions.length > 0) {
                suggestionsHtml = `
                    <div class="mt-4 pt-3 border-t border-base-300 text-left">
                        <p class="font-bold text-xs text-primary mb-2">Quantized GGUF repositories for this model:</p>
                        <div class="space-y-1.5">
                            ${suggestions.map(s => `
                                <div class="flex items-center justify-between p-2 rounded-lg bg-base-200 text-xs">
                                    <span class="font-mono text-[11px] truncate max-w-[210px]">${window.aiEscape(s)}</span>
                                    <button class="btn btn-xs btn-primary text-white font-semibold" onclick="window.inspectHfModel(${window.aiArg(s)})">
                                        View Quants
                                    </button>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;
            }

            quantsList.innerHTML = `
                <div class="p-4 bg-base-200/50 rounded-xl text-center">
                    <p class="text-xs opacity-70">This repository contains raw weights instead of compiled GGUF files.</p>
                    ${suggestionsHtml}
                </div>
            `;
            window.safeRenderAiIcons();
            return;
        }

        files.forEach(f => {
            const card = document.createElement('div');
            card.className = "border border-base-300 rounded-lg p-2.5 flex items-center justify-between gap-2 bg-base-100";

            card.innerHTML = `
                <div>
                    <div class="flex items-center gap-1.5">
                        <span class="font-bold text-xs font-mono">${window.aiEscape(f.quant)}</span>
                        ${f.is_recommended ? `<span class="badge badge-success text-white text-[9px] font-bold px-1.5 h-4 min-h-0">Recommended</span>` : ''}
                    </div>
                    <p class="text-[10px] opacity-60 font-mono truncate max-w-[220px]">${window.aiEscape(f.filename)}</p>
                </div>
                <div class="shrink-0 flex items-center gap-2">
                    <span class="text-xs font-mono font-bold">${window.aiEscape(f.size_formatted)}</span>
                    <button class="btn btn-xs btn-primary text-white font-semibold gap-1"
                            onclick="window.startHfModelDownload(${window.aiArg(f.download_url)}, ${window.aiArg(f.filename)})">
                        <i data-feather="download" class="w-3 h-3"></i> Get
                    </button>
                </div>
            `;
            quantsList.appendChild(card);
        });

    } catch (e) {
        if (quantsList) {
            quantsList.innerHTML = `<div class="text-center py-6 text-xs text-error font-semibold">Failed to load repository files.</div>`;
        }
    }

    window.safeRenderAiIcons();
};

window.backToHfSearch = () => {
    const searchList = document.getElementById('hfSearchResultsList');
    const quantView = document.getElementById('hfQuantView');
    if (searchList) searchList.classList.remove('hidden');
    if (quantView) quantView.classList.add('hidden');
    window.safeRenderAiIcons();
};

window.startHfModelDownload = async (url, filename) => {
    window.closeSidePanel();
    await window.downloadAiModel(null, url, filename);
};

// ==========================================
// 5. Test Chat Playground (Streaming Tokens)
// ==========================================

window.openAiChatModal = () => {
    const activeModel = window.aiEscape(window._aiActiveModel || "No model loaded");
    const title = `<i data-feather="message-square" class="w-4 h-4 text-primary"></i> Chat Evaluation Playground`;

    const body = `
        <div class="flex flex-col h-[520px]">
            <!-- Top Chat Header -->
            <div class="flex items-center justify-between p-2.5 bg-base-200/60 border border-base-300 rounded-xl mb-2 text-xs">
                <div class="flex items-center gap-2 min-w-0">
                    <span class="font-semibold opacity-70">Active Model:</span>
                    <span class="font-mono font-bold text-primary truncate max-w-[200px]" title="${activeModel}">${activeModel}</span>
                </div>
                <button class="btn btn-xs btn-ghost text-error/80 hover:text-error font-semibold" onclick="window.clearAiChat()">Clear</button>
            </div>

            <!-- Messages Stream Container -->
            <div id="aiChatMessages" class="flex-1 overflow-y-auto space-y-3 p-3 border border-base-300 rounded-xl bg-base-200/20 text-xs">
                ${window._aiChatHistory.length === 0 ? `
                    <div class="text-center py-16 opacity-50 text-xs space-y-1">
                        <i data-feather="message-square" class="w-8 h-8 mx-auto mb-1 text-primary/60"></i>
                        <p class="font-semibold text-base-content/80">Model Ready for Inference</p>
                        <p class="text-[11px] opacity-70">Send a prompt below to evaluate token generation.</p>
                    </div>
                ` : ''}
            </div>

            <!-- Chat Prompt Input Area -->
            <div class="pt-3">
                <div class="flex gap-2">
                    <textarea id="aiChatInput" rows="2" class="textarea textarea-bordered textarea-sm w-full text-xs leading-relaxed"
                              placeholder="Enter evaluation prompt..."
                              onkeydown="if(event.key==='Enter' && !event.shiftKey){ event.preventDefault(); window.sendAiChatMessage(); }"></textarea>
                    <button id="aiChatSendBtn" class="btn btn-primary text-white font-semibold h-auto px-4" onclick="window.sendAiChatMessage()">
                        <i data-feather="send" class="w-4 h-4"></i>
                    </button>
                </div>
                <div class="flex justify-between items-center mt-1 px-1 text-[10px] opacity-60">
                    <span>Press <strong>Enter</strong> to evaluate, <strong>Shift+Enter</strong> for newline</span>
                    <span class="font-mono">Authenticated :${window._aiPort || 38191}</span>
                </div>
            </div>
        </div>
    `;

    const footer = `
        <button class="btn btn-xs btn-neutral ml-auto" onclick="window.closeSidePanel()">Close</button>
    `;

    window.openSidePanel(title, body, footer);
    window.renderAiChatMessages();
    window.safeRenderAiIcons();

    setTimeout(() => {
        const inp = document.getElementById('aiChatInput');
        if (inp) inp.focus();
    }, 150);
};

window.renderAiChatMessages = () => {
    const box = document.getElementById('aiChatMessages');
    if (!box || window._aiChatHistory.length === 0) return;

    box.innerHTML = '';
    window._aiChatHistory.forEach(m => {
        const isUser = m.role === 'user';
        const msgDiv = document.createElement('div');
        msgDiv.className = isUser ? "flex justify-end" : "flex justify-start";

        const bubble = document.createElement('div');
        bubble.className = isUser
            ? "bg-primary text-white p-3 rounded-2xl rounded-tr-xs max-w-[85%] whitespace-pre-wrap leading-relaxed shadow-xs"
            : "bg-base-200 border border-base-300 p-3 rounded-2xl rounded-tl-xs max-w-[85%] whitespace-pre-wrap leading-relaxed shadow-xs";

        bubble.textContent = m.content;
        msgDiv.appendChild(bubble);
        box.appendChild(msgDiv);
    });

    box.scrollTop = box.scrollHeight;
};

window.clearAiChat = () => {
    window._aiChatHistory = [];
    const box = document.getElementById('aiChatMessages');
    if (box) {
        box.innerHTML = `
            <div class="text-center py-16 opacity-50 text-xs space-y-1">
                <i data-feather="message-square" class="w-8 h-8 mx-auto mb-1 text-primary/60"></i>
                <p class="font-semibold text-base-content/80">Model Ready for Inference</p>
                <p class="text-[11px] opacity-70">Send a prompt below to evaluate token generation.</p>
            </div>
        `;
    }
    window.safeRenderAiIcons();
};

window.sendAiChatMessage = async () => {
    const input = document.getElementById('aiChatInput');
    const sendBtn = document.getElementById('aiChatSendBtn');
    const box = document.getElementById('aiChatMessages');
    if (!input || !sendBtn || !box) return;

    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    input.disabled = true;
    sendBtn.disabled = true;

    window._aiChatHistory.push({ role: 'user', content: text });
    window.renderAiChatMessages();

    const assistantMsg = { role: 'assistant', content: '' };
    window._aiChatHistory.push(assistantMsg);

    const msgDiv = document.createElement('div');
    msgDiv.className = "flex justify-start";
    const bubble = document.createElement('div');
    bubble.className = "bg-base-200 border border-base-300 p-3 rounded-2xl rounded-tl-xs max-w-[85%] whitespace-pre-wrap leading-relaxed shadow-xs";
    bubble.innerHTML = `<span class="loading loading-dots loading-xs text-primary"></span>`;
    msgDiv.appendChild(bubble);
    box.appendChild(msgDiv);
    box.scrollTop = box.scrollHeight;

    try {
        const token = window.pclinkUI?.getToken?.() || window.localStorage?.getItem('pclink_token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const payload = {
            // Keep context bounded so long playground sessions stay within the
            // model's window instead of failing with an overflow error.
            messages: window._aiChatHistory.slice(0, -1).slice(-20),
            stream: true,
            max_tokens: 1024,
        };

        const res = await fetch('/ai/v1/chat/completions', {
            method: 'POST',
            headers,
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.text();
            throw new Error(err || `HTTP ${res.status}`);
        }

        bubble.textContent = '';
        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let fullContent = '';
        let buffer = '';
        let finished = false;

        const handleSseLine = (line) => {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) return;
            const dataStr = trimmed.slice(5).trim();
            if (!dataStr) return;
            if (dataStr === '[DONE]') {
                finished = true;
                return;
            }
            try {
                const parsed = JSON.parse(dataStr);
                if (parsed.error) {
                    throw new Error(parsed.error.message || String(parsed.error));
                }
                const delta = parsed.choices?.[0]?.delta?.content || '';
                if (delta) {
                    fullContent += delta;
                    bubble.textContent = fullContent;
                    box.scrollTop = box.scrollHeight;
                }
            } catch (e) {
                // Ignore malformed keep-alive frames, but surface real API errors.
                if (e instanceof SyntaxError) return;
                throw e;
            }
        };

        while (!finished) {
            const { done, value } = await reader.read();
            if (done) break;

            // SSE frames can be split across network chunks: keep the trailing
            // partial line buffered until the next read completes it.
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                handleSseLine(line);
                if (finished) break;
            }
        }

        buffer += decoder.decode();
        if (!finished && buffer.trim()) handleSseLine(buffer);

        assistantMsg.content = fullContent || "(No response tokens generated)";
        if (!fullContent) bubble.textContent = assistantMsg.content;

    } catch (e) {
        bubble.className = "bg-error/10 border border-error/30 text-error p-3 rounded-2xl max-w-[85%] text-xs leading-relaxed";
        bubble.textContent = `Inference Error: ${e.message || "Failed to generate tokens"}`;
        assistantMsg.content = bubble.textContent;
    } finally {
        input.disabled = false;
        sendBtn.disabled = false;
        input.focus();
    }
};

// ==========================================
// 6. Service Subprocess Lifecycle
// ==========================================

window.toggleAiService = async () => {
    const isRunning = window._aiServiceRunning;
    const endpoint = isRunning ? '/ai/service/stop' : '/ai/service/start';
    const actionLabel = isRunning ? 'Stopping' : 'Starting';

    try {
        window.pclinkUI.showToast(actionLabel, `${actionLabel} local runtime...`, "info");
        const res = await window.pclinkUI.webUICall(endpoint, { method: 'POST' });
        if (res.ok) {
            const port = window._aiPort || 38191;
            window.pclinkUI.showToast("Success", isRunning ? "AI engine stopped (RAM/VRAM released)" : `AI runner active on :${port}`, "success");
            window._lastAiCatalogSignature = null;
            window._lastAiModelsRevision = null;
            await window.refreshAiTab();
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Failed", err.detail || "Could not toggle AI runtime", "error");
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Communication failure toggling AI runner", "error");
    }
};

// ==========================================
// 6b. Runtime Settings (context, GPU, port)
// ==========================================

window.openAiSettingsModal = async () => {
    let cfg = {};
    try {
        const res = await window.pclinkUI.webUICall('/ai/config');
        if (!res.ok) throw new Error();
        cfg = await res.json();
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed to load AI runtime configuration", "error");
        return;
    }

    const num = (key, fallback) => {
        const parsed = Number(cfg[key]);
        return Number.isFinite(parsed) ? parsed : fallback;
    };

    const field = (id, label, value, min, max, step, help) => `
        <label class="form-control w-full">
            <div class="label py-1">
                <span class="label-text text-xs font-semibold">${label}</span>
            </div>
            <input id="${id}" type="number" class="input input-sm input-bordered font-mono text-xs w-full"
                   value="${value}" min="${min}" max="${max}" step="${step}">
            <div class="label py-1">
                <span class="label-text-alt text-[10px] opacity-60 leading-tight">${help}</span>
            </div>
        </label>
    `;

    const title = `<i data-feather="sliders" class="w-4 h-4 text-primary"></i> AI Runtime Settings`;
    const body = `
        <div class="space-y-3">
            <p class="text-[11px] opacity-70">
                Tune llama.cpp resource usage. Values are validated and saved atomically; changes
                to the port require stopping and starting the runner.
            </p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1">
                ${field('aiCfgContextSize', 'Context size (tokens)', num('context_size', 8192), 512, 131072, 512, 'Prompt + response window per request.')}
                ${field('aiCfgGpuLayers', 'GPU offload layers', num('gpu_layers', 99), 0, 999, 1, '0 = CPU only, 99 = offload all layers.')}
                ${field('aiCfgIdleTimeout', 'Idle unload (seconds)', num('idle_timeout_seconds', 600), 0, 86400, 30, '0 disables automatic VRAM/RAM release.')}
                ${field('aiCfgPort', 'Server port', num('port', 38191), 1024, 65535, 1, 'Loopback port used by llama-server.')}
                ${field('aiCfgThreads', 'CPU threads', num('threads', 0), 0, 256, 1, '0 = let llama.cpp choose automatically.')}
                ${field('aiCfgParallel', 'Parallel requests', num('parallel', 1), 1, 16, 1, 'Concurrent generations; multiplies KV cache.')}
                ${field('aiCfgStartupTimeout', 'Startup timeout (s)', num('startup_timeout_seconds', 120), 10, 600, 10, 'Max wait while loading model weights.')}
                ${field('aiCfgRequestTimeout', 'Request timeout (s)', num('request_timeout_seconds', 300), 30, 3600, 30, 'Max wait for a single completion.')}
            </div>
            <div id="aiSettingsHint" class="text-[11px] font-semibold text-warning hidden"></div>
        </div>
    `;

    const footer = `
        <button class="btn btn-xs btn-neutral ml-auto" onclick="window.closeSidePanel()">Cancel</button>
        <button id="aiSettingsSaveBtn" class="btn btn-xs btn-primary text-white font-semibold" onclick="window.saveAiSettings()">
            <i data-feather="save" class="w-3.5 h-3.5"></i> Save Settings
        </button>
    `;

    window.openSidePanel(title, body, footer);
    window.safeRenderAiIcons();
};

window.saveAiSettings = async () => {
    const btn = document.getElementById('aiSettingsSaveBtn');
    const hint = document.getElementById('aiSettingsHint');
    const readInt = (id) => {
        const el = document.getElementById(id);
        return el ? Number.parseInt(el.value, 10) : NaN;
    };

    const payload = {
        context_size: readInt('aiCfgContextSize'),
        gpu_layers: readInt('aiCfgGpuLayers'),
        idle_timeout_seconds: readInt('aiCfgIdleTimeout'),
        port: readInt('aiCfgPort'),
        threads: readInt('aiCfgThreads'),
        parallel: readInt('aiCfgParallel'),
        startup_timeout_seconds: readInt('aiCfgStartupTimeout'),
        request_timeout_seconds: readInt('aiCfgRequestTimeout'),
    };

    const invalid = Object.entries(payload).find(([, v]) => !Number.isFinite(v));
    if (invalid) {
        window.pclinkUI.showToast("Invalid Value", "All settings must be whole numbers.", "warning");
        return;
    }

    if (btn) btn.disabled = true;
    try {
        const res = await window.pclinkUI.webUICall('/ai/config', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            let detail = "Failed to save AI runtime settings";
            try {
                const err = await res.json();
                detail = err.detail || detail;
            } catch (e) { }
            window.pclinkUI.showToast("Save Failed", detail, "error");
            return;
        }
        const data = await res.json();
        window._lastAiCatalogSignature = null;
        window._lastAiModelsRevision = null;
        if (data.restart_required) {
            if (hint) {
                hint.textContent = "Port changed. Stop and start the runner to apply it.";
                hint.classList.remove('hidden');
            }
            window.pclinkUI.showToast("Saved", "Settings saved. Restart the runner to apply the new port.", "warning");
        } else {
            window.pclinkUI.showToast("Saved", "AI runtime settings updated", "success");
            window.closeSidePanel();
        }
        await window.refreshAiTab();
    } catch (e) {
        window.pclinkUI.showToast("Error", "Communication failure saving AI settings", "error");
    } finally {
        if (btn) btn.disabled = false;
    }
};

// ==========================================
// 7. Multi-Version Engine Manager
// ==========================================

window.openLlamaVersionModal = async () => {
    const title = `<i data-feather="cpu" class="w-4 h-4 text-primary"></i> llama.cpp Engine Manager`;
    const body = `
        <div class="tabs tabs-boxed mb-3 bg-base-200 p-1">
            <a class="tab tab-active font-semibold text-xs" id="llamaTabInstalled" onclick="window.switchLlamaModalTab('installed')">
                <i data-feather="hard-drive" class="w-3.5 h-3.5 mr-1.5"></i> Installed Builds
            </a>
            <a class="tab font-semibold text-xs" id="llamaTabReleases" onclick="window.switchLlamaModalTab('releases')">
                <i data-feather="github" class="w-3.5 h-3.5 mr-1.5"></i> GitHub Releases
            </a>
        </div>

        <div id="llamaEngineDlProgressCard" class="card bg-base-200 p-3 mb-3 border border-primary/30 hidden">
            <div class="flex items-center justify-between mb-1.5">
                <div class="flex items-center gap-2">
                    <span class="loading loading-spinner loading-xs text-primary"></span>
                    <span id="llamaEngineDlMsg" class="font-mono text-xs font-bold text-primary">Downloading engine build...</span>
                </div>
                <span id="llamaEngineDlStats" class="text-[10px] opacity-70 font-mono">0 MB / 0 MB (0%)</span>
            </div>
            <progress id="llamaEngineDlBar" class="progress progress-primary w-full h-1.5" value="0" max="100"></progress>
        </div>

        <div id="llamaSectionInstalled" class="space-y-3">
            <p class="text-[11px] opacity-70">Precompiled llama-server executable builds available on this PC.</p>
            <div id="llamaInstalledList" class="divide-y divide-base-300 max-h-96 overflow-y-auto pr-1">
                <div class="text-center py-6 opacity-40 text-xs">
                    <span class="loading loading-spinner loading-xs mr-2"></span> Inspecting builds...
                </div>
            </div>
        </div>

        <div id="llamaSectionReleases" class="space-y-3 hidden">
            <p class="text-[11px] opacity-70">Official precompiled binaries from ggml-org/llama.cpp.</p>
            <div id="llamaReleasesList" class="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                <div class="text-center py-6 opacity-40 text-xs">
                    <span class="loading loading-spinner loading-xs mr-2"></span> Fetching releases...
                </div>
            </div>
        </div>
    `;

    const footer = `
        <div id="llamaModalStatusText" class="text-xs font-bold text-info flex items-center gap-1.5 hidden">
            <span class="loading loading-spinner loading-xs"></span> <span id="llamaModalStatusMsg">Processing...</span>
        </div>
        <button class="btn btn-xs btn-neutral ml-auto" onclick="window.closeSidePanel()">Close</button>
    `;

    window.openSidePanel(title, body, footer);
    await window.loadLlamaVersionsData();
    await window.checkActiveEngineDownload();
};

window.switchLlamaModalTab = (tab) => {
    const tabInst = document.getElementById('llamaTabInstalled');
    const tabRel = document.getElementById('llamaTabReleases');
    const secInst = document.getElementById('llamaSectionInstalled');
    const secRel = document.getElementById('llamaSectionReleases');

    if (!tabInst || !tabRel || !secInst || !secRel) return;

    if (tab === 'installed') {
        tabInst.classList.add('tab-active');
        tabRel.classList.remove('tab-active');
        secInst.classList.remove('hidden');
        secRel.classList.add('hidden');
    } else {
        tabRel.classList.add('tab-active');
        tabInst.classList.remove('tab-active');
        secRel.classList.remove('hidden');
        secInst.classList.add('hidden');
    }
    window.safeRenderAiIcons();
};

window.loadLlamaVersionsData = async () => {
    const instList = document.getElementById('llamaInstalledList');
    const relList = document.getElementById('llamaReleasesList');

    try {
        const res = await window.pclinkUI.webUICall('/ai/engine/versions');
        if (!res.ok) throw new Error();
        const data = await res.json();

        if (instList) {
            instList.innerHTML = '';
            if (data.installed && data.installed.length > 0) {
                data.installed.forEach(v => {
                    const item = document.createElement('div');
                    item.className = "flex justify-between items-center py-2.5 px-1";

                    const activeBadge = v.is_active
                        ? `<span class="badge badge-success text-white text-[10px] font-semibold">Active</span>`
                        : `<button class="btn btn-xs btn-outline btn-primary text-[10px] font-semibold" onclick="window.selectLlamaVersion(${window.aiArg(v.tag)})">Use Build</button>`;

                    const deleteBtn = !v.is_active
                        ? `<button class="btn btn-xs btn-ghost text-error/80 hover:text-error p-1 h-6 min-h-0" title="Delete build" onclick="window.deleteLlamaVersion(${window.aiArg(v.tag)})"><i data-feather="trash-2" class="w-3.5 h-3.5"></i></button>`
                        : '';

                    item.innerHTML = `
                        <div class="flex items-center gap-2.5">
                            <div class="p-1.5 bg-base-200 rounded-md">
                                <i data-feather="cpu" class="w-4 h-4 text-primary"></i>
                            </div>
                            <div>
                                <h5 class="font-bold text-xs">${window.aiEscape(v.display_name)}</h5>
                                <p class="text-[10px] opacity-60 font-mono">${(Number(v.size_bytes || 0) / (1024 * 1024)).toFixed(1)} MB</p>
                            </div>
                        </div>
                        <div class="flex items-center gap-2">
                            ${activeBadge}
                            ${deleteBtn}
                        </div>
                    `;
                    instList.appendChild(item);
                });
            } else {
                instList.innerHTML = `<div class="text-center py-4 text-xs opacity-50">No installed builds detected. Click GitHub Releases to install one.</div>`;
            }
        }

        if (relList) {
            relList.innerHTML = '';
            if (data.releases && data.releases.length > 0) {
                data.releases.forEach((r, idx) => {
                    const isInstalled = (data.installed || []).some(i => i.tag === r.tag_name);
                    const isActive = (data.installed || []).some(i => i.tag === r.tag_name && i.is_active);

                    const card = document.createElement('div');
                    card.className = "border border-base-300 rounded-lg p-3 flex justify-between items-center bg-base-100";

                    let actionBtn = '';
                    if (isActive) {
                        actionBtn = `<span class="badge badge-success text-white text-[10px] font-semibold">Active</span>`;
                    } else if (isInstalled) {
                        actionBtn = `<button class="btn btn-xs btn-outline btn-primary font-semibold" onclick="window.selectLlamaVersion(${window.aiArg(r.tag_name)})">Use Build</button>`;
                    } else if (r.download_url) {
                        actionBtn = `<button id="llama-dl-btn-${idx}" class="btn btn-xs btn-success text-white font-semibold" onclick="window.downloadLlamaVersion(${window.aiArg(r.tag_name)}, ${window.aiArg(r.download_url)}, ${window.aiArg('llama-dl-btn-' + idx)})">Install</button>`;
                    } else {
                        actionBtn = `<span class="text-[10px] opacity-40">No build asset</span>`;
                    }

                    card.innerHTML = `
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="font-bold text-xs text-primary font-mono">${window.aiEscape(r.tag_name)}</span>
                                ${r.prerelease ? `<span class="badge badge-warning text-[9px] font-semibold">Pre-release</span>` : ''}
                            </div>
                            <p class="text-[10px] opacity-60">${r.published_at ? window.aiEscape(new Date(r.published_at).toLocaleDateString()) : ''}</p>
                        </div>
                        <div>${actionBtn}</div>
                    `;
                    relList.appendChild(card);
                });
            } else {
                relList.innerHTML = `<div class="text-center py-4 text-xs opacity-50">No release history found.</div>`;
            }
        }

    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed to load llama.cpp version info", "error");
    }

    window.safeRenderAiIcons();
};

window.autoInstallRecommendedLlamaEngine = async () => {
    try {
        window.pclinkUI.showToast("Querying", "Looking up latest llama.cpp release...", "info");
        const res = await window.pclinkUI.webUICall('/ai/engine/versions');
        if (!res.ok) throw new Error();
        const data = await res.json();
        const latest = (data.releases || []).find(r => r.download_url);
        if (!latest) {
            window.pclinkUI.showToast("Error", "No compatible precompiled build found in releases", "error");
            return;
        }
        await window.downloadLlamaVersion(latest.tag_name, latest.download_url);
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed to auto-install recommended engine", "error");
    }
};

window.downloadLlamaVersion = async (tag, url, btnId = null) => {
    const btn = btnId ? document.getElementById(btnId) : null;
    const origHtml = btn ? btn.innerHTML : null;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="loading loading-spinner loading-xs mr-1"></span> Preparing`;
    }

    try {
        const res = await window.pclinkUI.webUICall('/ai/engine/download', {
            method: 'POST',
            body: JSON.stringify({ tag, download_url: url })
        });
        if (res.ok) {
            window.startEngineDownloadPolling(btn, origHtml);
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Installation Failed", err.detail || "Download failed", "error");
            if (btn && origHtml) {
                btn.disabled = false;
                btn.innerHTML = origHtml;
            }
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed downloading engine build", "error");
        if (btn && origHtml) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
};

window.startEngineDownloadPolling = (btn = null, origHtml = null) => {
    const progressCard = document.getElementById('llamaEngineDlProgressCard');
    const msgEl = document.getElementById('llamaEngineDlMsg');
    const statsEl = document.getElementById('llamaEngineDlStats');
    const barEl = document.getElementById('llamaEngineDlBar');

    if (progressCard) progressCard.classList.remove('hidden');

    if (window._aiEnginePollingInterval) clearInterval(window._aiEnginePollingInterval);

    window._aiEnginePollingInterval = setInterval(async () => {
        try {
            const res = await window.pclinkUI.webUICall('/ai/engine/download-progress');
            if (!res.ok) return;
            const data = await res.json();

            if (data.status === 'downloading') {
                if (data.stage === 'extracting') {
                    if (msgEl) msgEl.textContent = `Extracting & verifying libraries for ${data.tag}...`;
                    if (statsEl) statsEl.textContent = "Please wait...";
                    if (barEl) barEl.removeAttribute('value');
                } else {
                    if (msgEl) msgEl.textContent = `Downloading llama-server ${data.tag}...`;
                    const dlMb = (data.bytes_downloaded / (1024 * 1024)).toFixed(1);
                    const totalMb = (data.total_bytes / (1024 * 1024)).toFixed(1);
                    if (statsEl) statsEl.textContent = `${dlMb} MB / ${totalMb} MB (${data.percent}%)`;
                    if (barEl) {
                        barEl.value = data.percent;
                        barEl.max = 100;
                    }
                }
            } else if (data.status === 'completed') {
                clearInterval(window._aiEnginePollingInterval);
                if (progressCard) progressCard.classList.add('hidden');
                window.pclinkUI.showToast("Installed", `llama-server ${data.tag} installed and activated`, "success");
                await window.loadLlamaVersionsData();
                await window.refreshAiTab();
                window.switchLlamaModalTab('installed');
            } else if (data.status === 'failed') {
                clearInterval(window._aiEnginePollingInterval);
                if (progressCard) progressCard.classList.add('hidden');
                window.pclinkUI.showToast("Failed", data.error || "Engine download failed", "error");
                if (btn && origHtml) {
                    btn.disabled = false;
                    btn.innerHTML = origHtml;
                }
            }
        } catch (e) { }
    }, 500);
};

window.checkActiveEngineDownload = async () => {
    try {
        const res = await window.pclinkUI.webUICall('/ai/engine/download-progress');
        if (res.ok) {
            const data = await res.json();
            if (data.status === 'downloading') {
                window.startEngineDownloadPolling();
            }
        }
    } catch (e) { }
};

window.selectLlamaVersion = async (tag) => {
    try {
        window.setLlamaModalStatus(`Switching active build to ${tag}...`);
        const res = await window.pclinkUI.webUICall('/ai/engine/select', {
            method: 'POST',
            body: JSON.stringify({ tag })
        });
        if (res.ok) {
            window.pclinkUI.showToast("Engine Active", `Active build set to ${tag}`, "success");
            await window.loadLlamaVersionsData();
            await window.refreshAiTab();
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Error", err.detail || "Failed to switch build", "error");
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed switching active engine build", "error");
    } finally {
        window.setLlamaModalStatus(null);
    }
};

window.deleteLlamaVersion = async (tag) => {
    if (!confirm(`Delete cached engine build ${tag}?`)) return;
    try {
        const res = await window.pclinkUI.webUICall(`/ai/engine/versions/${encodeURIComponent(tag)}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            window.pclinkUI.showToast("Deleted", `Removed ${tag}`, "info");
            await window.loadLlamaVersionsData();
            await window.refreshAiTab();
        } else {
            const err = await res.json();
            window.pclinkUI.showToast("Error", err.detail || "Failed to delete build", "error");
        }
    } catch (e) {
        window.pclinkUI.showToast("Error", "Failed deleting engine build", "error");
    } finally {
        window.setLlamaModalStatus(null);
    }
};

window.setLlamaModalStatus = (msg) => {
    const statusBox = document.getElementById('llamaModalStatusText');
    const statusMsg = document.getElementById('llamaModalStatusMsg');
    if (!statusBox) return;
    if (msg) {
        if (statusMsg) statusMsg.textContent = msg;
        statusBox.classList.remove('hidden');
        statusBox.style.display = 'flex';
    } else {
        if (statusMsg) statusMsg.textContent = '';
        statusBox.classList.add('hidden');
        statusBox.style.display = 'none';
    }
};
