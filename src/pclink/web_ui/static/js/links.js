/**
 * Links Management Logic
 * Handles fetching, copying, counting down, and revoking share links for the Web UI.
 */

let shareCountdownInterval = null;

async function refreshLinks() {
    const tableBody = document.getElementById('linksTableBody');
    if (!tableBody) return;

    try {
        const response = window.pclinkUI
            ? await window.pclinkUI.apiCall('/files/shares')
            : await fetch('/files/shares').then(r => r.json());

        const shares = response.shares || [];

        if (shares.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center py-20 opacity-50">
                        <div class="flex flex-col items-center gap-2">
                            <i data-feather="link" class="w-8 h-8 opacity-20"></i>
                            <p class="font-bold">No active share links found.</p>
                            <p class="text-xs opacity-70">Share links created from devices or the browser will appear here.</p>
                        </div>
                    </td>
                </tr>`;
            if (shareCountdownInterval) {
                clearInterval(shareCountdownInterval);
                shareCountdownInterval = null;
            }
        } else {
            tableBody.innerHTML = shares.map(share => {
                const filename = share.file_path.split('/').pop().split('\\').pop() || share.file_path;
                const created = new Date(share.created_at).toLocaleString();
                const deviceName = share.device_name || 'Web UI';

                let expiryDisplay = '';
                if (share.expires_at) {
                    expiryDisplay = `<span data-expiry="${share.expires_at}" class="badge badge-warning badge-sm font-mono font-bold">Calculating...</span>`;
                } else {
                    expiryDisplay = '<span class="badge badge-success badge-sm font-bold text-white">Permanent</span>';
                }

                return `
                    <tr class="hover">
                        <td>
                            <div class="flex items-center gap-3">
                                <div class="bg-base-300 p-2 rounded-lg text-primary">
                                    <i data-feather="file" class="w-4 h-4"></i>
                                </div>
                                <div class="max-w-[240px] md:max-w-xs truncate">
                                    <div class="font-bold text-sm truncate" title="${escapeHTML(filename)}">${escapeHTML(filename)}</div>
                                    <div class="text-[10px] opacity-40 font-mono truncate" title="${escapeHTML(share.file_path)}">${escapeHTML(share.file_path)}</div>
                                </div>
                            </div>
                        </td>
                        <td>
                            <span class="badge badge-ghost badge-sm font-mono opacity-80">${escapeHTML(deviceName)}</span>
                        </td>
                        <td class="text-xs opacity-70">${created}</td>
                        <td>${expiryDisplay}</td>
                        <td class="text-right">
                            <div class="flex justify-end gap-1">
                                <button class="btn btn-ghost btn-xs text-primary" onclick="copyShareLink('${escapeJS(share.file_path)}', '${escapeJS(share.token)}')" title="Copy download link">
                                    <i data-feather="copy" class="w-3.5 h-3.5"></i> Copy
                                </button>
                                <button class="btn btn-ghost btn-xs text-error" onclick="revokeLink('${escapeJS(share.token)}')" title="Revoke access link">
                                    <i data-feather="trash-2" class="w-3.5 h-3.5"></i> Revoke
                                </button>
                            </div>
                        </td>
                    </tr>`;
            }).join('');

            // Start countdown ticker if active shares exist with expiry times
            const hasExpirations = shares.some(s => s.expires_at);
            if (hasExpirations) {
                startShareCountdownTicker();
            } else if (shareCountdownInterval) {
                clearInterval(shareCountdownInterval);
                shareCountdownInterval = null;
            }
        }

        if (window.feather) feather.replace();
    } catch (error) {
        console.error('Failed to fetch share links:', error);
        if (window.pclinkUI) {
            window.pclinkUI.showToast('Error', 'Failed to load share links', 'error');
        }
    }
}

function startShareCountdownTicker() {
    if (shareCountdownInterval) clearInterval(shareCountdownInterval);
    updateShareCountdowns();
    shareCountdownInterval = setInterval(updateShareCountdowns, 1000);
}

function updateShareCountdowns() {
    const elements = document.querySelectorAll('[data-expiry]');
    let activeTimers = 0;

    elements.forEach(el => {
        const expiryStr = el.getAttribute('data-expiry');
        if (!expiryStr) return;

        const expiry = new Date(expiryStr).getTime();
        const now = Date.now();
        const diff = expiry - now;

        if (diff <= 0) {
            el.outerHTML = '<span class="badge badge-error badge-sm font-bold text-white">Expired</span>';
            // Auto refresh shortly after expiry to clear the row
            setTimeout(() => { refreshLinks(); }, 1500);
        } else {
            activeTimers++;
            const secs = Math.floor(diff / 1000);
            const mins = Math.floor(secs / 60);
            const hours = Math.floor(mins / 60);
            const days = Math.floor(hours / 24);

            let timeStr = "";
            if (days > 0) timeStr = `${days}d ${hours % 24}h`;
            else if (hours > 0) timeStr = `${hours}h ${mins % 60}m`;
            else if (mins > 0) timeStr = `${mins}m ${secs % 60}s`;
            else timeStr = `${secs}s`;

            el.textContent = timeStr;
        }
    });

    if (activeTimers === 0 && shareCountdownInterval) {
        clearInterval(shareCountdownInterval);
        shareCountdownInterval = null;
    }
}

async function copyShareLink(filePath, token) {
    const downloadUrl = `${window.location.origin}/files/download?path=${encodeURIComponent(filePath)}&token=${token}`;
    try {
        await navigator.clipboard.writeText(downloadUrl);
        if (window.pclinkUI) {
            window.pclinkUI.showToast('Copied', 'Download URL copied to clipboard', 'success');
        }
    } catch (err) {
        console.error('Failed to copy share link:', err);
        // Fallback for non-secure contexts
        const input = document.createElement('input');
        input.value = downloadUrl;
        document.body.appendChild(input);
        input.select();
        try {
            document.execCommand('copy');
            if (window.pclinkUI) {
                window.pclinkUI.showToast('Copied', 'Download URL copied to clipboard', 'success');
            }
        } catch (e) {
            alert('Could not copy link automatically. Please copy manually:\n' + downloadUrl);
        }
        document.body.removeChild(input);
    }
}

async function revokeLink(token) {
    const confirmed = await window.confirmDialog(
        'Are you sure you want to revoke this share link? This will make the link invalid immediately.',
        { title: 'Revoke Link', danger: true }
    );
    if (!confirmed) return;

    try {
        const response = window.pclinkUI
            ? await window.pclinkUI.apiCall(`/files/shares/${token}`, { method: 'DELETE' })
            : await fetch(`/files/shares/${token}`, { method: 'DELETE' }).then(r => r.json());

        if (response.status === 'revoked') {
            if (window.pclinkUI) {
                window.pclinkUI.showToast('Success', 'Share link revoked successfully', 'success');
            }
            await refreshLinks();
        } else {
            throw new Error('Unexpected response from server');
        }
    } catch (error) {
        console.error('Failed to revoke share link:', error);
        if (window.pclinkUI) {
            window.pclinkUI.showToast('Error', 'Failed to revoke share link', 'error');
        }
    }
}

// Helpers to escape content
function escapeHTML(str) {
    if (!str) return '';
    const p = document.createElement('p');
    p.textContent = str;
    return p.innerHTML;
}

function escapeJS(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}
