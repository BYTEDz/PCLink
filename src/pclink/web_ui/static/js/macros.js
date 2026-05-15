// static/js/macros.js
const MACRO_TRANSLATIONS = {
    duration_ms_label: "Duration (ms)",
    volume_level_label: "Volume Level (0-100)",
    command_label: "Terminal Command",
    notification_title_label: "Notification Title",
    notification_message_label: "Notification Message",
    app_package_label: "App Package ID",
    input_text_label: "Text to Type",
    file_path_label: "System File Path",
    transfer_dest_label: "Destination Folder",
    url_label: "Web URL",
    brightness_level_label: "Brightness (0-255)",
    power_action_label: "System Action",
    media_action_label: "Media Command",
    action_type_delay: "Wait / Delay",
    action_type_notification: "Send Notification",
    action_type_volume: "Adjust Volume",
    action_type_command: "Run Command",
    action_type_input_text: "Type Text",
    action_type_media: "Media Control",
    action_type_power: "Power Control",
    action_type_launch_app: "Launch Application",
    action_type_open_url: "Open Link",
    action_type_brightness: "Set Brightness",
    action_type_wol: "Wake on LAN",
    action_type_keyboard_shortcut: "Keyboard Shortcut",
    action_type_clipboard: "Sync Clipboard",
    action_type_open_file: "Open File/Folder",
    app_to_launch_label: "Application to Start",
    power_action_shutdown: "Shutdown System",
    power_action_reboot: "Reboot System",
    power_action_sleep: "Put to Sleep",
    power_action_lock: "Lock Screen",
    power_action_logout: "Log Out",
    media_action_play_pause: "Play / Pause",
    media_action_next: "Next Track",
    media_action_previous: "Previous Track",
    text_to_type_label: "Text to Enter",
    clipboard_text_label: "Text for Clipboard",
    path_label: "Path to Open",
    key_label: "Special Key",
    custom_key_label: "Custom Key / Character",
    modifiers_label: "Modifier Keys",
    modifier_ctrl: "Control (Ctrl)",
    modifier_shift: "Shift",
    modifier_alt: "Alt / Option",
    modifier_cmd: "Win / Command",
    key_char_custom: "Custom...",
    key_enter: "Enter",
    key_esc: "Escape",
    key_tab: "Tab",
    key_space: "Space",
    key_backspace: "Backspace",
    key_delete: "Delete",
    key_up: "Arrow Up",
    key_down: "Arrow Down",
    key_left: "Arrow Left",
    key_right: "Arrow Right",
    key_home: "Home",
    key_end: "End",
    key_pageup: "Page Up",
    key_pagedown: "Page Down",
    key_f1: "F1", key_f2: "F2", key_f3: "F3", key_f4: "F4", key_f5: "F5", key_f6: "F6",
    key_f7: "F7", key_f8: "F8", key_f9: "F9", key_f10: "F10", key_f11: "F11", key_f12: "F12"
};

PCLinkWebUI.prototype.loadMacros = async function() {
    try {
        const [macros, actions] = await Promise.all([
            this.apiCall('/macro/'),
            this.apiCall('/macro/available-actions')
        ]);
        this.macros = macros;
        this.macroActions = actions;
        this.renderMacros();
        const mc = document.getElementById('macroCount');
        if (mc) mc.textContent = this.macros.length;
    } catch (e) {
        console.error("Failed to load macros:", e);
    }
};

PCLinkWebUI.prototype.renderMacros = function() {
    const el = document.getElementById('macroList');
    if (!el) return;
    if (this.macros.length === 0) {
        el.innerHTML = '<div class="col-span-full py-10 text-center opacity-40 font-black uppercase text-[10px] tracking-widest bg-base-200 border border-dashed border-base-300 rounded-xl"><p>No macros defined</p></div>';
        return;
    }
    el.innerHTML = this.macros.map(m => `
        <div class="card bg-base-100 border border-base-300 shadow-sm transition-all hover:border-primary group">
            <div class="card-body p-5">
                <div class="flex items-start justify-between gap-4">
                    <div class="flex items-center gap-3 overflow-hidden">
                        <div class="bg-primary/10 text-primary p-3 rounded-xl shrink-0">
                            <i data-feather="zap" class="w-5 h-5"></i>
                        </div>
                        <div class="overflow-hidden">
                            <h4 class="font-bold text-lg leading-tight truncate">${m.name}</h4>
                            <p class="text-[10px] font-bold uppercase opacity-50 tracking-wider mt-1">${m.actions.length} Actions</p>
                        </div>
                    </div>
                    <div class="flex gap-1 shrink-0">
                        <button class="btn btn-square btn-ghost btn-sm" onclick="window.runMacro('${m.id}')" title="Run Now"><i data-feather="play" class="w-4"></i></button>
                        <button class="btn btn-square btn-ghost btn-sm" onclick="window.openMacroEditor('${m.id}')" title="Edit"><i data-feather="edit-2" class="w-4"></i></button>
                        <button class="btn btn-square btn-ghost btn-sm" onclick="window.duplicateMacro('${m.id}')" title="Duplicate"><i data-feather="copy" class="w-4"></i></button>
                        <button class="btn btn-square btn-ghost btn-sm text-error" onclick="window.deleteMacro('${m.id}')" title="Delete"><i data-feather="trash-2" class="w-4"></i></button>
                    </div>
                </div>
            </div>
        </div>`).join('');
    if (window.feather) feather.replace();
};

// Global Macro Helpers
window.loadMacros = () => window.pclinkUI?.loadMacros();

window.openMacroEditor = function (macroId = null) {
    const macro = macroId ? window.pclinkUI.macros.find(m => m.id === macroId) : null;
    const title = `<i data-feather="zap" class="text-primary w-4"></i> ${macro ? 'Edit Macro' : 'New Macro'}`;
    const body = `
        <div class="space-y-6">
            <input type="hidden" id="macroIdInput" value="${macroId || ''}" />
            <div class="form-control">
                <label class="label font-black uppercase text-[10px] opacity-40 p-1">Macro Name</label>
                <input type="text" id="macroNameInput" placeholder="e.g. Work Setup" class="input input-bordered w-full font-bold" value="${macro ? macro.name : ''}" />
            </div>
            <div class="space-y-3">
                <div class="flex justify-between items-center">
                    <label class="label font-black uppercase text-[10px] opacity-40 p-1">Actions Chain</label>
                    <button class="btn btn-xs btn-primary text-white font-bold" onclick="window.addMacroActionRow()">
                        <i data-feather="plus" class="w-3"></i> Add Action
                    </button>
                </div>
                <div id="macroActionsContainer" class="space-y-3 min-h-[100px] border-2 border-dashed border-base-300 rounded-xl p-4">
                    <!-- Action rows will be injected here -->
                </div>
            </div>
        </div>
    `;
    const footer = `
        <button class="btn btn-sm btn-ghost font-bold" onclick="window.closeSidePanel()">Cancel</button>
        <button class="btn btn-sm btn-primary text-white font-bold px-8" onclick="window.saveMacro()">Save Macro</button>
    `;
    window.openSidePanel(title, body, footer);
    if (macro) {
        macro.actions.forEach(action => window.addMacroActionRow(action));
    } else {
        window.addMacroActionRow();
    }
};

window.addMacroActionRow = function (action = null) {
    const container = document.getElementById('macroActionsContainer');
    const rowId = 'action-' + Math.random().toString(36).substr(2, 9);
    const actions = window.pclinkUI.macroActions;
    const row = document.createElement('div');
    row.className = 'action-row bg-base-100 p-3 rounded-lg border border-base-300 flex flex-col gap-3 shadow-sm relative group/row transition-all';
    row.id = rowId;
    row.draggable = true;

    row.addEventListener('dragstart', (e) => {
        row.classList.add('opacity-50', 'border-primary', 'bg-primary/5');
        e.dataTransfer.setData('text/plain', rowId);
        window.draggingRow = row;
    });

    row.addEventListener('dragend', () => {
        row.classList.remove('opacity-50', 'border-primary', 'bg-primary/5');
        window.draggingRow = null;
        document.querySelectorAll('.action-row').forEach(r => r.classList.remove('border-t-4', 'border-t-primary'));
    });

    row.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (!window.draggingRow || window.draggingRow === row) return;
        const rect = row.getBoundingClientRect();
        const midpoint = rect.top + rect.height / 2;
        if (e.clientY < midpoint) {
            container.insertBefore(window.draggingRow, row);
        } else {
            container.insertBefore(window.draggingRow, row.nextSibling);
        }
    });

    const typeOptions = actions.map(a => `<option value="${a.type}" ${action && action.type === a.type ? 'selected' : ''}>${MACRO_TRANSLATIONS[a.name_key] || a.type}</option>`).join('');

    row.innerHTML = `
        <div class="flex items-center gap-3">
            <div class="drag-handle cursor-move opacity-30 group-hover/row:opacity-100"><i data-feather="more-vertical" class="w-4"></i></div>
            <select class="select select-bordered select-sm flex-1 font-bold action-type-select" onchange="window.updateMacroActionFields('${rowId}', this.value)">
                ${typeOptions}
            </select>
            <button class="btn btn-square btn-ghost btn-xs text-error" onclick="this.closest('.action-row').remove()"><i data-feather="x" class="w-3"></i></button>
        </div>
        <div class="action-fields grid grid-cols-1 sm:grid-cols-2 gap-3 pl-7">
            <!-- Fields injected here -->
        </div>
    `;

    container.appendChild(row);
    window.updateMacroActionFields(rowId, action ? action.type : actions[0]?.type, action?.payload);
    if (window.feather) feather.replace();
};

window.updateMacroActionFields = function (rowId, actionType, values = {}) {
    const row = document.getElementById(rowId);
    if (!row) return;
    const fieldsContainer = row.querySelector('.action-fields');
    const actionDef = window.pclinkUI.macroActions.find(a => a.type === actionType);
    if (!actionDef) return;

    fieldsContainer.innerHTML = actionDef.parameters.map(p => {
        const val = values[p.name] !== undefined ? values[p.name] : (p.default_value !== undefined ? p.default_value : '');
        let inputHtml = '';
        const requiredAttr = p.required ? 'required' : '';

        if (p.type === 'select') {
            const optionsHtml = p.options.map(opt => `<option value="${opt.value}" ${val === opt.value ? 'selected' : ''}>${MACRO_TRANSLATIONS[opt.name_key] || opt.name_key || opt.value}</option>`).join('');
            inputHtml = `<select name="${p.name}" class="select select-bordered select-sm w-full font-bold" ${requiredAttr}>${optionsHtml}</select>`;
        } else if (p.type === 'int' || p.name.includes('duration') || p.name.includes('level')) {
            inputHtml = `<input type="number" name="${p.name}" value="${val}" class="input input-bordered input-sm w-full font-bold" ${requiredAttr} />`;
        } else {
            inputHtml = `<input type="text" name="${p.name}" value="${val}" placeholder="${MACRO_TRANSLATIONS[p.label_key] || p.label_key || p.name}..." class="input input-bordered input-sm w-full font-bold" ${requiredAttr} />`;
        }

        return `
            <div class="form-control">
                <label class="label p-1">
                    <span class="label-text text-[9px] font-black uppercase opacity-40">${MACRO_TRANSLATIONS[p.label_key] || p.label_key || p.name} ${p.required ? '<span class="text-error">*</span>' : ''}</span>
                </label>
                ${inputHtml}
            </div>
        `;
    }).join('');
};

window.saveMacro = async function () {
    const id = document.getElementById('macroIdInput').value;
    const name = document.getElementById('macroNameInput').value;
    const rows = document.querySelectorAll('.action-row');
    if (!name) return window.pclinkUI.showToast('Error', 'Macro name is required', 'error');
    const actions = [];
    let valid = true;
    rows.forEach(row => {
        const type = row.querySelector('.action-type-select').value;
        const inputs = row.querySelectorAll('.action-fields input, .action-fields select');
        const payload = {};
        inputs.forEach(input => {
            if (input.hasAttribute('required') && !input.value) {
                valid = false;
                input.classList.add('select-error', 'input-error');
            } else {
                input.classList.remove('select-error', 'input-error');
            }
            const val = input.type === 'number' ? parseInt(input.value) : input.value;
            payload[input.name] = val;
        });
        actions.push({ type, payload });
    });
    if (!valid) return window.pclinkUI.showToast('Error', 'Please fill in all required fields', 'error');
    try {
        const res = await window.pclinkUI.apiCall('/macro/', {
            method: 'POST',
            body: JSON.stringify({ id, name, actions })
        });
        window.closeSidePanel();
        window.pclinkUI.showToast('Saved', `Macro '${name}' updated`, 'success');
        window.pclinkUI.loadMacros();
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to save macro', 'error');
    }
};

window.deleteMacro = async function (id) {
    const macro = window.pclinkUI.macros.find(m => m.id === id);
    if (!macro) return;
    if (!await window.confirmDialog(`Delete macro '${macro.name}'?`, { title: 'Delete Macro', danger: true })) return;
    try {
        await window.pclinkUI.apiCall(`/macro/${id}`, { method: 'DELETE' });
        window.pclinkUI.showToast('Deleted', 'Macro removed', 'success');
        window.pclinkUI.loadMacros();
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to delete macro', 'error');
    }
};

window.runMacro = async function (id) {
    try {
        await window.pclinkUI.apiCall(`/macro/${id}/run`, { method: 'POST' });
        window.pclinkUI.showToast('Running', 'Macro execution started', 'success');
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Execution failed', 'error');
    }
};

window.duplicateMacro = async function (id) {
    try {
        await window.pclinkUI.apiCall(`/macro/${id}/duplicate`, { method: 'POST' });
        window.pclinkUI.showToast('Duplicated', 'Macro copy created', 'success');
        window.pclinkUI.loadMacros();
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to duplicate', 'error');
    }
};
