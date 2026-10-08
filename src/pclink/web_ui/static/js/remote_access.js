// static/js/remote_access.js
// Modern Master-Switch Remote Access Manager & Guide Coordinator

window._remoteAccessData = null;
window._remoteTransitionTimer = null;
window._remotePollTimer = null;
window._isTestingEdgeConnectivity = false;

window.loadRemoteAccessTab = async function (isSilent = false) {
    const headline = document.getElementById('remoteStateHeadline');
    const dot = document.getElementById('remoteStateIndicatorDot');
    const hint = document.getElementById('remoteActionHint');
    const powerIcon = document.getElementById('remoteMasterPowerIcon');
    const masterBtn = document.getElementById('remoteMasterBtn');
    const glow = document.getElementById('remoteButtonGlow');
    const pingContainer = document.getElementById('remoteEdgePingContainer');
    const revokedPill = document.getElementById('remoteRevokedPill');
    const unlinkContainer = document.getElementById('remoteUnlinkContainer');

    try {
        const res = await window.pclinkUI.webUICall('/ui/relay/status');
        if (!res.ok) throw new Error('Status query failed');

        const data = await res.json();
        window._remoteAccessData = data;

        if (data.setup_progress) {
            window.updateTunnelSetupProgressUI(data.setup_progress);
        }

        // 1. REVOKED / EXPIRED STATE (Subscription ended, token invalidated)
        if (data.is_revoked || data.tunnel_status === 'revoked') {
            if (headline) headline.textContent = 'Remote Access Expired';
            if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-error shrink-0';
            if (hint) hint.textContent = 'Subscription ended • Re-link required on local Wi-Fi';
            if (pingContainer) pingContainer.classList.add('hidden');

            if (revokedPill) revokedPill.classList.remove('hidden');
            if (unlinkContainer) unlinkContainer.classList.add('hidden');

            if (masterBtn) {
                masterBtn.className = 'relative w-32 h-32 rounded-full border-4 border-error/50 bg-error/10 flex flex-col items-center justify-center shadow-lg transition-all duration-300 cursor-pointer active:scale-95';
            }
            if (powerIcon) {
                powerIcon.className = 'w-12 h-12 text-error';
            }
            if (glow) {
                glow.className = 'absolute w-40 h-40 rounded-full bg-error/20 blur-xl opacity-100';
            }
            return;
        }

        if (revokedPill) revokedPill.classList.add('hidden');

        // 2. CONNECTED & RUNNING (Tunnel active, edge connection verified)
        if (data.running && data.hostname && data.has_token) {
            if (headline) headline.textContent = 'Remote Access Active';
            if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-success shrink-0 animate-pulse';
            if (hint) hint.textContent = 'Click to Pause / Turn Off';
            if (pingContainer) pingContainer.classList.remove('hidden');

            if (unlinkContainer) unlinkContainer.classList.remove('hidden');

            if (masterBtn) {
                masterBtn.className = 'relative w-32 h-32 rounded-full border-4 border-success bg-success/10 hover:bg-success/20 flex flex-col items-center justify-center shadow-lg shadow-success/20 transition-all duration-300 active:scale-95 cursor-pointer';
            }
            if (powerIcon) {
                powerIcon.className = 'w-12 h-12 text-success';
            }
            if (glow) {
                glow.className = 'absolute w-40 h-40 rounded-full bg-success/25 blur-2xl opacity-100 animate-pulse';
            }

            // Periodically ping edge latency while active
            window.testRemoteAccessEdgeConnectivity();
        }
        // 3. ENGINE ACTIVE BUT UNLINKED (Binary ready, waiting for token delivery from mobile app)
        else if (!data.has_token) {
            if (headline) headline.textContent = 'Engine Ready • Waiting for Mobile Link';
            if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-warning shrink-0 animate-pulse';
            if (hint) hint.textContent = 'Open PCLink App on local Wi-Fi to Link';
            if (pingContainer) pingContainer.classList.add('hidden');

            if (unlinkContainer) unlinkContainer.classList.add('hidden');

            if (masterBtn) {
                masterBtn.className = 'relative w-32 h-32 rounded-full border-4 border-warning/60 bg-warning/10 hover:bg-warning/15 flex flex-col items-center justify-center shadow-lg transition-all duration-300 active:scale-95 cursor-pointer';
            }
            if (powerIcon) {
                powerIcon.className = 'w-12 h-12 text-warning';
            }
            if (glow) {
                glow.className = 'absolute w-40 h-40 rounded-full bg-warning/20 blur-xl opacity-70';
            }
        }
        // 4. TRANSITIONING / CONNECTING
        else if (data.enabled) {
            if (headline) headline.textContent = 'Connecting to Secure Relay...';
            if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-warning shrink-0 animate-pulse';
            if (hint) hint.textContent = 'Establishing secure bridge...';
            if (pingContainer) pingContainer.classList.add('hidden');

            if (unlinkContainer) unlinkContainer.classList.add('hidden');

            if (masterBtn) {
                masterBtn.className = 'relative w-32 h-32 rounded-full border-4 border-warning bg-warning/10 flex flex-col items-center justify-center shadow-lg transition-all duration-300 animate-pulse';
            }
            if (powerIcon) {
                powerIcon.className = 'w-12 h-12 text-warning';
            }
            if (glow) {
                glow.className = 'absolute w-40 h-40 rounded-full bg-warning/30 blur-2xl opacity-100 animate-ping';
            }
        }
        // 5. PAUSED / MANUALLY TURNED OFF (Token exists, but user paused daemon)
        else {
            if (headline) headline.textContent = 'Remote Access Paused';
            if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-base-300 shrink-0';
            if (hint) hint.textContent = 'Click to Resume / Turn On';
            if (pingContainer) pingContainer.classList.add('hidden');

            if (unlinkContainer) unlinkContainer.classList.remove('hidden');

            if (masterBtn) {
                masterBtn.className = 'relative w-32 h-32 rounded-full border-4 border-base-300 bg-base-200/80 hover:bg-base-200 hover:border-base-content/20 flex flex-col items-center justify-center shadow-md transition-all duration-300 active:scale-95 cursor-pointer';
            }
            if (powerIcon) {
                powerIcon.className = 'w-12 h-12 text-base-content/40 hover:text-base-content/60';
            }
            if (glow) {
                glow.className = 'absolute w-40 h-40 rounded-full opacity-0';
            }
        }
    } catch (e) {
        if (headline) headline.textContent = 'Daemon Unreachable';
    }

    if (window.feather) {
        try {
            feather.replace();
        } catch (_) {}
    }
};

window.loadRelayTab = window.loadRemoteAccessTab;

window.handleMasterButtonClick = function () {
    if (!window._remoteAccessData) return;

    if (window._remoteAccessData.is_revoked || window._remoteAccessData.tunnel_status === 'revoked') {
        window.unlinkRemoteAccess(true);
        return;
    }

    if (!window._remoteAccessData.has_token) {
        const guideEl = document.getElementById('remoteSetupGuideCard');
        if (guideEl) {
            guideEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            guideEl.classList.add('pclink-highlight-pulse');
            setTimeout(() => guideEl.classList.remove('pclink-highlight-pulse'), 1500);
        }
        window.openPairingPanel();
        return;
    }

    window.toggleRemoteAccessState();
};

window.toggleRemoteAccessState = async function () {
    const isCurrentlyRunning = window._remoteAccessData && window._remoteAccessData.enabled;
    const newState = !isCurrentlyRunning;

    const hint = document.getElementById('remoteActionHint');
    if (hint) hint.textContent = newState ? 'Connecting...' : 'Disconnecting...';

    try {
        const res = await window.pclinkUI.webUICall('/ui/relay/toggle', {
            method: 'POST',
            body: JSON.stringify({ enabled: newState })
        });
        if (res.ok) {
            window.pollRemoteAccessTransition(newState);
        } else {
            window.pclinkUI.showToast('Error', 'Failed to toggle remote access', 'error');
            window.loadRemoteAccessTab();
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Connection error', 'error');
        window.loadRemoteAccessTab();
    }
};

window.pollRemoteAccessTransition = function (targetState, maxAttempts = 12) {
    if (window._remoteTransitionTimer) {
        clearInterval(window._remoteTransitionTimer);
    }

    let attempts = 0;
    window._remoteTransitionTimer = setInterval(async () => {
        attempts++;
        await window.loadRemoteAccessTab(true);

        const isRunning = window._remoteAccessData && window._remoteAccessData.running;
        const reachedTarget = targetState ? isRunning : !isRunning;

        if (reachedTarget || attempts >= maxAttempts) {
            clearInterval(window._remoteTransitionTimer);
            window._remoteTransitionTimer = null;
            if (targetState && isRunning) {
                window.testRemoteAccessEdgeConnectivity();
            }
        }
    }, 1000);
};

window.unlinkRemoteAccess = async function (skipConfirmation = false) {
    if (!skipConfirmation) {
        const confirmed = await window.confirmDialog(
            'Disconnect this computer from remote access? This will remove tunnel credentials. Re-linking must be performed while connected to local Wi-Fi.',
            { title: 'Disconnect Remote Access', danger: true }
        );
        if (!confirmed) return;
    }

    try {
        window.pclinkUI.showToast('Remote Access', 'Disconnecting...', 'info');
        const res = await window.pclinkUI.webUICall('/ui/relay/unlink', { method: 'POST' });
        if (res.ok) {
            window.pclinkUI.showToast('Success', 'Remote access disconnected', 'success');
            await window.loadRemoteAccessTab();
        } else {
            window.pclinkUI.showToast('Error', 'Failed to disconnect', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to communicate with server', 'error');
    }
};

window.testRemoteAccessEdgeConnectivity = async function (maxRetries = 2) {
    const badge = document.getElementById('remoteEdgePingBadge');
    if (!badge || !window._remoteAccessData || !window._remoteAccessData.hostname) return;
    if (window._isTestingEdgeConnectivity) return;
    window._isTestingEdgeConnectivity = true;

    try {
        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                const res = await window.pclinkUI.webUICall('/ui/relay/ping');
                if (res.ok) {
                    const data = await res.json();
                    if (data.status === 'online') {
                        badge.className = 'badge badge-success text-white badge-xs font-mono font-bold tracking-wider';
                        badge.textContent = data.latency_ms !== null ? `${data.latency_ms} ms` : 'Active';
                        return;
                    } else if (data.status === 'paused') {
                        badge.className = 'badge badge-warning text-white badge-xs font-mono font-bold tracking-wider';
                        badge.textContent = 'Paused';
                        return;
                    } else if (data.status === 'unlinked') {
                        badge.className = 'badge badge-error text-white badge-xs font-mono font-bold tracking-wider';
                        badge.textContent = 'Expired';
                        if (window._remoteAccessData) {
                            window._remoteAccessData.is_revoked = true;
                            window._remoteAccessData.tunnel_status = 'revoked';
                        }
                        return;
                    }
                }
            } catch (_) {}

            if (attempt < maxRetries) {
                await new Promise(r => setTimeout(r, 1000));
            }
        }

        // Only display Offline if the daemon itself is not running
        if (window._remoteAccessData && window._remoteAccessData.running) {
            badge.className = 'badge badge-success text-white badge-xs font-mono font-bold tracking-wider';
            badge.textContent = 'Active';
        } else {
            badge.className = 'badge badge-ghost badge-xs font-mono font-bold tracking-wider opacity-60';
            badge.textContent = 'Offline';
        }
    } finally {
        window._isTestingEdgeConnectivity = false;
    }
};


window.updateTunnelSetupProgressUI = function (data) {
    const banner = document.getElementById('remoteEngineSetupProgressBanner');
    const stageTitle = document.getElementById('remoteEngineStageTitle');
    const progressSub = document.getElementById('remoteEngineProgressSub');
    const progressBar = document.getElementById('remoteEngineProgressBar');
    const percentBadge = document.getElementById('remoteEnginePercentBadge');

    if (!banner || !data) return;

    if (data.status === 'downloading') {
        banner.classList.remove('hidden');
        if (stageTitle) stageTitle.textContent = data.stage || 'Downloading Secure Tunnel Engine...';
        if (progressBar) progressBar.value = data.progress || 0;
        if (percentBadge) percentBadge.textContent = `${data.progress || 0}%`;
        if (progressSub) {
            const mbDownloaded = (data.downloaded_bytes / (1024 * 1024)).toFixed(1);
            const mbTotal = (data.total_bytes / (1024 * 1024)).toFixed(1);
            progressSub.textContent = data.total_bytes > 0
                ? `${mbDownloaded} MB of ${mbTotal} MB downloaded`
                : 'Downloading package...';
        }
    } else if (data.status === 'ready') {
        if (progressBar) progressBar.value = 100;
        if (percentBadge) percentBadge.textContent = '100%';
        if (stageTitle) stageTitle.textContent = 'Engine Ready';
        setTimeout(() => banner.classList.add('hidden'), 2000);
    } else if (data.status === 'failed') {
        if (stageTitle) stageTitle.textContent = 'Engine Setup Failed';
        if (progressSub) progressSub.textContent = data.error || 'Check network connection.';
    } else {
        banner.classList.add('hidden');
    }
};

(function initRemoteAccessAutoPoll() {
    if (window._remotePollTimer) clearInterval(window._remotePollTimer);
    window._remotePollTimer = setInterval(async () => {
        const remoteTab = document.getElementById('remote-access') || document.getElementById('relay');
        if (remoteTab && remoteTab.classList.contains('active') && !window._remoteTransitionTimer) {
            await window.loadRemoteAccessTab(false);
        }
    }, 5000);
})();
