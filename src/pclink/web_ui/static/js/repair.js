/**
 * src/pclink/web_ui/static/js/repair.js
 * Frontend logic for Repair Center
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
            const res = await fetch('/ui/repair/diagnose');
            if (!res.ok) throw new Error("Failed to fetch diagnostics");
            const data = await res.json();

            this.renderDiagnostics(data);
        } catch (e) {
            if (container) container.innerHTML = `<div class="alert alert-error">Failed to run diagnostics: ${e.message}</div>`;
        } finally {
            if (loader) {
                loader.classList.add('hidden');
                loader.classList.remove('flex');
            }
        }
    },

    renderDiagnostics: function (data) {
        const container = document.getElementById('repairContent');
        if (!container) return;
        container.innerHTML = '';

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
        if (typeof showToast === 'function') showToast(`Attempting to fix ${issueId}...`, 'info');

        try {
            const res = await fetch(`/ui/repair/run/${issueId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (issueId === 'firewall' && data.status === 'warning' && data.message.includes('sudo') && !payload.password) {
                const modal = document.getElementById('linuxFirewallModal');
                if (modal) modal.showModal();
                return;
            }

            if (data.status === 'ok') {
                if (typeof showToast === 'function') showToast(data.message, 'success');
            } else {
                if (typeof showToast === 'function') showToast(data.message, 'error');
            }

            this.runDiagnostics();

        } catch (e) {
            if (typeof showToast === 'function') showToast(`Fix failed: ${e.message}`, 'error');
        }
    },

    forceRepair: async function() {
        if (!confirm("⚠️ WARNING: This will factory reset PCLink!\n\nThis will permanently delete your database, paired devices, configuration, and transfer history.\n\nAre you sure you want to proceed?")) {
            return;
        }

        if (typeof showToast === 'function') showToast("Starting force repair...", "info");
        try {
            const res = await fetch('/ui/repair/force', { method: 'POST' });
            const data = await res.json();

            if (data.status === 'ok') {
                if (typeof showToast === 'function') showToast(data.message, 'success');
                setTimeout(() => window.location.reload(), 1500);
            } else {
                if (typeof showToast === 'function') showToast(`Force repair failed: ${data.message}`, 'error');
            }
        } catch (e) {
            if (typeof showToast === 'function') showToast(`Force repair failed: ${e.message}`, 'error');
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    repairModule.init();
});
