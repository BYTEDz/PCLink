/**
 * src/pclink/web_ui/static/js/repair.js
 * Frontend logic for Repair Center, Self-Healing, and Root Cause Analysis
 */

const repairModule = {
    init: function () {
        this.hasRun = false;

        const repairBtn = document.querySelector('[data-tab="repairTab"]') || document.querySelector('[data-tab="repair"]');
        if (repairBtn) {
            repairBtn.addEventListener('click', () => {
                if (!this.hasRun) {
                    this.runDiagnostics();
                    this.hasRun = true;
                }
            });
        }
    },

    runDiagnostics: async function () {
        const container = document.getElementById('repairContent');
        const loader = document.getElementById('repairLoading');

        if (!container) return;

        container.innerHTML = '';
        if (loader) {
            loader.classList.remove('hidden');
            loader.classList.add('flex');
        }

        try {
            const [diagRes, causeRes] = await Promise.all([
                window.pclinkUI.webUICall('/ui/repair/diagnose'),
                window.pclinkUI.webUICall('/ui/repair/causes')
            ]);

            if (!diagRes.ok) throw new Error("Failed to fetch diagnostics");
            const data = await diagRes.json();
            const causeData = causeRes.ok ? await causeRes.json() : null;

            this.renderDiagnostics(data, causeData);
        } catch (e) {
            if (container) container.innerHTML = `<div class="alert alert-error font-bold text-xs">Failed to run diagnostics: ${e.message}</div>`;
            window.pclinkUI.showToast('Diagnostics Error', e.message, 'error');
        } finally {
            if (loader) {
                loader.classList.add('hidden');
                loader.classList.remove('flex');
            }
        }
    },

    renderDiagnostics: function (data, causeData) {
        const container = document.getElementById('repairContent');
        if (!container) return;
        container.innerHTML = '';

        // Render Self-Healing Banner if causes detected
        if (causeData && causeData.detected_causes && causeData.detected_causes.length > 0) {
            let causeListHtml = causeData.detected_causes.map(c => `
                <div class="p-3 bg-base-200/50 rounded-lg border border-warning/20 my-1">
                    <p class="font-bold text-xs text-warning flex items-center gap-1"><i data-feather="alert-triangle" class="w-3 h-3"></i> ${c.title}</p>
                    <p class="text-[11px] opacity-70 mt-0.5">${c.description}</p>
                    <p class="text-[10px] text-primary mt-1 font-semibold">Tip: ${c.recommendation}</p>
                </div>
            `).join('');

            container.innerHTML += `
                <div class="p-4 bg-warning/10 border border-warning/30 rounded-xl mb-4">
                    <div class="flex items-center justify-between mb-2">
                        <h3 class="font-black text-sm text-warning uppercase tracking-wider flex items-center gap-2">
                            <i data-feather="cpu" class="w-4 h-4"></i> Root-Cause Analyzer Detected Issues (${causeData.detected_causes.length})
                        </h3>
                        <button class="btn btn-xs btn-warning text-black font-bold uppercase" onclick="repairModule.executeAutoHeal()">Auto-Heal Now</button>
                    </div>
                    ${causeListHtml}
                </div>
            `;
        } else {
            container.innerHTML += `
                <div class="p-3 bg-success/10 border border-success/20 rounded-xl mb-4 flex items-center justify-between">
                    <span class="text-xs font-bold text-success flex items-center gap-2">
                        <i data-feather="check-circle" class="w-4 h-4"></i> Server Health Watchdog: System Operating Normally
                    </span>
                    <button class="btn btn-xs btn-outline btn-success font-bold uppercase text-[9px]" onclick="repairModule.executeAutoHeal()">Run Auto-Heal</button>
                </div>
            `;
        }

        const components = [
            { id: 'port', title: 'Port Availability', icon: 'server', data: data.port },
            { id: 'firewall', title: 'Firewall Rules', icon: 'shield', data: data.firewall },
            { id: 'db', title: 'Database Integrity', icon: 'database', data: data.db },
            { id: 'config', title: 'Configuration File', icon: 'settings', data: data.config }
        ];

        components.forEach(comp => {
            const statusColor = comp.data.status === 'ok' ? 'text-success' : (comp.data.status === 'warning' ? 'text-warning' : 'text-error');
            const statusBg = comp.data.status === 'ok' ? 'bg-success/10 border-success/20' : (comp.data.status === 'warning' ? 'bg-warning/10 border-warning/20' : 'bg-error/10 border-error/20');
            const icon = comp.data.status === 'ok' ? 'check-circle' : 'alert-circle';

            let fixButton = '';
            if (comp.data.status !== 'ok') {
                fixButton = `<button class="btn btn-sm btn-outline ${comp.data.status === 'warning' ? 'btn-warning' : 'btn-error'}" onclick="repairModule.promptFix('${comp.id}')">Fix Issue</button>`;
            }

            container.innerHTML += `
                <div class="flex items-center justify-between p-4 border rounded-box ${statusBg}">
                    <div class="flex items-center gap-4">
                        <div class="${statusColor}">
                            <i data-feather="${comp.icon}" class="w-8 h-8 opacity-50"></i>
                        </div>
                        <div>
                            <h3 class="font-bold text-lg flex items-center gap-2 ${statusColor}">
                                <i data-feather="${icon}" class="w-4 h-4"></i>
                                ${comp.title}
                            </h3>
                            <p class="text-sm opacity-70">${comp.data.message}</p>
                        </div>
                    </div>
                    <div>
                        ${fixButton}
                    </div>
                </div>
            `;
        });

        if (window.feather) feather.replace();
    },

    executeAutoHeal: async function () {
        window.pclinkUI.showToast('Auto-Heal', 'Running auto-heal sequence...', 'info');
        try {
            const res = await window.pclinkUI.webUICall('/ui/repair/auto-heal', { method: 'POST' });
            const data = await res.json();
            if (res.ok && data.status === 'ok') {
                window.pclinkUI.showToast('Resolved', data.message, 'success');
                this.runDiagnostics();
            } else {
                window.pclinkUI.showToast('Error', data.message || 'Auto-heal failed', 'error');
            }
        } catch (e) {
            window.pclinkUI.showToast('Error', 'Auto-heal failed: ' + e.message, 'error');
        }
    },

    promptFix: function (issueId) {
        if (issueId === 'port') {
            const modal = document.getElementById('portConflictModal');
            if (modal) modal.showModal();
        } else if (issueId === 'firewall' && navigator.userAgent.toLowerCase().includes('linux')) {
            this.executeFix(issueId);
        } else {
            this.executeFix(issueId);
        }
    },

    submitPortFix: function(action) {
        const modal = document.getElementById('portConflictModal');
        if (modal) modal.close();
        this.executeFix('port', { action: action });
    },

    submitFirewallFix: function(e) {
        e.preventDefault();
        const pwdInput = document.getElementById('linuxSudoPassword');
        const pwd = pwdInput ? pwdInput.value : '';
        const modal = document.getElementById('linuxFirewallModal');
        if (modal) modal.close();
        this.executeFix('firewall', { password: pwd });
    },

    executeFix: async function (issueId, payload = {}) {
        window.pclinkUI.showToast('Repair', `Attempting to fix ${issueId}...`, 'info');

        try {
            const res = await window.pclinkUI.webUICall(`/ui/repair/run/${issueId}`, {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (issueId === 'firewall' && data.status === 'warning' && data.message.includes('sudo') && !payload.password) {
                const modal = document.getElementById('linuxFirewallModal');
                if (modal) modal.showModal();
                return;
            }

            if (res.ok && data.status === 'ok') {
                window.pclinkUI.showToast('Success', data.message, 'success');
            } else {
                window.pclinkUI.showToast('Fix Failed', data.message, 'error');
            }

            this.runDiagnostics();

        } catch (e) {
            window.pclinkUI.showToast('Error', `Fix failed: ${e.message}`, 'error');
        }
    },

    forceRepair: async function() {
        const confirmed = await window.confirmDialog(
            "This will permanently delete your database, paired devices, configuration, and transfer history.\n\nAre you sure you want to proceed?",
            { title: 'Factory Reset Warning', danger: true }
        );

        if (!confirmed) return;

        window.pclinkUI.showToast('Force Repair', "Starting force repair...", "info");
        try {
            const res = await window.pclinkUI.webUICall('/ui/repair/force', { method: 'POST' });
            const data = await res.json();

            if (res.ok && data.status === 'ok') {
                window.pclinkUI.showToast('Success', data.message, 'success');
                setTimeout(() => window.location.reload(), 1500);
            } else {
                window.pclinkUI.showToast('Error', `Force repair failed: ${data.message}`, 'error');
            }
        } catch (e) {
            window.pclinkUI.showToast('Error', `Force repair failed: ${e.message}`, 'error');
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    repairModule.init();
});
