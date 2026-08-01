// static/js/dashboard.js
// Dashboard Telemetry, Storage, Fleet, Adapters & Specs Export

PCLinkWebUI.prototype.updateDashboardTelemetry = function (sys) {
    if (!sys) return;

    if (!this._lastThresholdAlert) {
        this._lastThresholdAlert = { cpu: 0, ram: 0, temp: 0 };
    }
    const now = Date.now();

    // CPU
    if (sys.cpu) {
        const cpuPct = Math.round(sys.cpu.percent || 0);
        const cpuVal = document.getElementById('dashCpuVal');
        const cpuBar = document.getElementById('dashCpuBar');
        const cpuSub = document.getElementById('dashCpuSub');
        if (cpuVal) cpuVal.textContent = `${cpuPct}%`;
        if (cpuBar) cpuBar.value = cpuPct;
        if (cpuSub) {
            if (sys.cpu.physical_cores) {
                cpuSub.textContent = `${sys.cpu.physical_cores} Cores (${sys.cpu.total_cores || 0} Threads)`;
            } else if (sys.cpu.total_cores) {
                cpuSub.textContent = `${sys.cpu.total_cores} Cores`;
            }
        }

        // Automatic Resource Threshold Warning: CPU > 90%
        if (cpuPct > 90 && (now - this._lastThresholdAlert.cpu > 120000)) {
            this.addNotification('High CPU Usage Alert', `CPU load reached ${cpuPct}%`, 'warning');
            this._lastThresholdAlert.cpu = now;
        }
    }

    // RAM
    if (sys.ram) {
        const ramPct = Math.round(sys.ram.percent || 0);
        const ramVal = document.getElementById('dashRamVal');
        const ramBar = document.getElementById('dashRamBar');
        const ramSub = document.getElementById('dashRamSub');
        if (ramVal) ramVal.textContent = `${ramPct}%`;
        if (ramBar) ramBar.value = ramPct;
        if (ramSub) {
            ramSub.textContent = `${sys.ram.used_gb || 0} GB / ${sys.ram.total_gb || 0} GB`;
        }

        // Automatic Resource Threshold Warning: RAM > 95%
        if (ramPct > 95 && (now - this._lastThresholdAlert.ram > 120000)) {
            this.addNotification('Critical RAM Usage Alert', `Memory utilization reached ${ramPct}%`, 'error');
            this._lastThresholdAlert.ram = now;
        }
    }

    // Network
    if (sys.network && sys.network.speed) {
        const netUp = document.getElementById('dashNetUp');
        const netDown = document.getElementById('dashNetDown');
        if (netUp) netUp.textContent = `${(sys.network.speed.upload_mbps || 0).toFixed(2)} Mbps`;
        if (netDown) netDown.textContent = `${(sys.network.speed.download_mbps || 0).toFixed(2)} Mbps`;
    }

    // Thermals & Battery
    const tempVal = document.getElementById('dashTempVal');
    const powerSub = document.getElementById('dashPowerSub');

    if (sys.sensors && sys.sensors.cpu_temp_celsius) {
        const cTemp = Math.round(sys.sensors.cpu_temp_celsius);
        if (tempVal) tempVal.textContent = `${cTemp} °C`;

        // Automatic Resource Threshold Warning: Temp > 85°C
        if (cTemp > 85 && (now - this._lastThresholdAlert.temp > 120000)) {
            this.addNotification('High Thermal Alert', `CPU temperature reached ${cTemp}°C`, 'warning');
            this._lastThresholdAlert.temp = now;
        }
    } else if (tempVal && (tempVal.textContent === 'N/A' || !tempVal.textContent)) {
        tempVal.textContent = 'Normal';
    }

    if (sys.battery && sys.battery.percent !== undefined) {
        if (powerSub) {
            const state = sys.battery.power_plugged ? 'Charging' : 'Battery';
            powerSub.textContent = `${sys.battery.percent}% (${state})`;
        }
    }
};

// 1-Click System Specs Export (JSON Download)
window.downloadSystemSpecs = async function () {
    try {
        window.pclinkUI.showToast('Exporting', 'Collecting diagnostic specs...', 'info');
        const res = await window.pclinkUI.webUICall('/info/system');
        if (!res.ok) throw new Error("Failed to fetch specs");

        const specs = await res.json();
        const jsonStr = JSON.stringify(specs, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `pclink-diagnostics-specs-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
        a.click();
        URL.revokeObjectURL(url);

        window.pclinkUI.showToast('Downloaded', 'System specs exported successfully', 'success');
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to export specs: ' + e.message, 'error');
    }
};

// Storage & Disks Render
PCLinkWebUI.prototype.updateDashboardDisks = function (disks) {
    const container = document.getElementById('dashDisksContainer');
    if (!container) return;

    if (!disks || disks.length === 0) {
        container.innerHTML = '<div class="text-center py-6 opacity-40 text-xs font-bold">No storage volumes found</div>';
        return;
    }

    container.innerHTML = disks.map(disk => `
        <div class="p-3 bg-base-200/50 rounded-xl border border-base-300/50 space-y-1.5">
            <div class="flex justify-between items-center text-xs font-bold">
                <span class="truncate font-mono">${this.escapeHTML(disk.device)}</span>
                <span class="opacity-60 text-[10px]">${disk.used} / ${disk.total} (${disk.percent}%)</span>
            </div>
            <progress class="progress ${disk.percent > 90 ? 'progress-error' : 'progress-primary'} w-full h-1.5" value="${disk.percent}" max="100"></progress>
        </div>
    `).join('');
};

// Active Connected Fleet Render
PCLinkWebUI.prototype.updateDashboardFleet = function (devices) {
    const container = document.getElementById('dashFleetContainer');
    if (!container) return;

    const activeDevices = (devices || []).filter(d => d.is_approved);

    if (activeDevices.length === 0) {
        container.innerHTML = '<div class="text-center py-6 opacity-40 text-xs font-bold">No linked devices</div>';
        return;
    }

    container.innerHTML = activeDevices.map(d => `
        <div class="p-2.5 bg-base-200/50 rounded-xl border border-base-300/50 flex items-center justify-between gap-3">
            <div class="flex items-center gap-2.5 min-w-0">
                <div class="${d.is_online ? 'bg-success/10 text-success' : 'bg-base-300 opacity-50'} p-2 rounded-lg shrink-0">
                    <i data-feather="smartphone" class="w-4 h-4"></i>
                </div>
                <div class="min-w-0">
                    <h4 class="font-bold text-xs truncate">${this.escapeHTML(d.name)}</h4>
                    <p class="text-[9px] font-mono opacity-50 truncate">${d.ip || 'N/A'}</p>
                </div>
            </div>
            <span class="badge ${d.is_online ? 'badge-success text-white' : 'badge-ghost opacity-50'} badge-xs font-bold uppercase text-[8px]">${d.is_online ? 'Online' : 'Offline'}</span>
        </div>
    `).join('');

    this.renderIcons();
};

// Network Adapters & IPs Render
PCLinkWebUI.prototype.updateDashboardAdapters = function (interfaces) {
    const container = document.getElementById('dashAdaptersContainer');
    if (!container) return;

    if (!interfaces || Object.keys(interfaces).length === 0) {
        container.innerHTML = '<div class="text-center py-6 opacity-40 text-xs font-bold">No active network adapters</div>';
        return;
    }

    container.innerHTML = Object.entries(interfaces).map(([nic, info]) => `
        <div class="p-2.5 bg-base-200/50 rounded-xl border border-base-300/50 flex items-center justify-between gap-3">
            <div class="min-w-0">
                <h4 class="font-bold text-xs truncate">${this.escapeHTML(nic)}</h4>
                <p class="text-[10px] font-mono text-primary font-bold truncate">${info.ip || 'No IP'}</p>
            </div>
            <button class="btn btn-ghost btn-xs text-primary gap-1 font-bold" onclick="navigator.clipboard.writeText('${info.ip}')" title="Copy IP">
                <i data-feather="copy" class="w-3"></i> Copy
            </button>
        </div>
    `).join('');

    this.renderIcons();
};

// Security & Auth Info
PCLinkWebUI.prototype.updateDashboardSecurity = function (sec) {
    const sessionsVal = document.getElementById('dashActiveSessionsVal');
    const timeoutVal = document.getElementById('dashSessionTimeoutVal');

    if (sessionsVal && sec.active_sessions !== undefined) {
        sessionsVal.textContent = sec.active_sessions;
    }
    if (timeoutVal && sec.session_timeout_hours !== undefined) {
        timeoutVal.textContent = `${sec.session_timeout_hours} hrs`;
    }
};

// Active Transfers Pipeline
PCLinkWebUI.prototype.updateDashboardTransfers = function (perf) {
    const upVal = document.getElementById('dashActiveUploadsVal');
    const downVal = document.getElementById('dashActiveDownloadsVal');

    if (upVal && perf.active_uploads_memory !== undefined) {
        upVal.textContent = perf.active_uploads_memory;
    }
    if (downVal && perf.active_downloads_memory !== undefined) {
        downVal.textContent = perf.active_downloads_memory;
    }
};
