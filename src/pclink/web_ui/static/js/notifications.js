// static/js/notifications.js
// Notification Center Storage, Unread Badge & Side Panel Drawer Manager

PCLinkWebUI.prototype.addNotification = function (title, message, type = 'info') {
    if (!this.notifications) this.notifications = [];

    const notif = {
        id: 'n-' + Math.random().toString(36).substr(2, 9),
        title: title,
        message: message,
        type: type,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        read: false
    };

    this.notifications.unshift(notif);
    if (this.notifications.length > 30) this.notifications.pop();

    this.updateNotificationUI();
};

PCLinkWebUI.prototype.updateNotificationUI = function () {
    const badge = document.getElementById('notificationBadgeCount');

    const unread = (this.notifications || []).filter(n => !n.read).length;
    if (badge) {
        if (unread > 0) {
            badge.textContent = unread > 99 ? '99+' : unread;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    }

    this.renderNotificationPanelList();
};

PCLinkWebUI.prototype.markNotificationsAsRead = function () {
    if (!this.notifications) return;
    this.notifications.forEach(n => n.read = true);
    this.updateNotificationUI();
};

PCLinkWebUI.prototype.renderNotificationPanelList = function () {
    const container = document.getElementById('panelNotificationList');
    if (!container) return;

    if (!this.notifications || this.notifications.length === 0) {
        container.innerHTML = `
            <div class="text-center py-20 opacity-40 font-bold uppercase tracking-widest text-xs flex flex-col items-center gap-3">
                <i data-feather="bell-off" class="w-10 h-10 stroke-1"></i>
                <p>No notifications</p>
            </div>
        `;
        this.renderIcons();
        return;
    }

    const typeIcons = {
        success: 'check-circle text-success',
        error: 'alert-circle text-error',
        warning: 'alert-triangle text-warning',
        info: 'info text-info'
    };

    container.innerHTML = this.notifications.map(n => `
        <div class="p-4 bg-base-200/50 rounded-2xl border border-base-300/50 flex items-start gap-3 transition-all hover:border-primary/50">
            <div class="p-2 rounded-xl bg-base-100 border border-base-300/50 shrink-0 mt-0.5">
                <i data-feather="${(typeIcons[n.type] || typeIcons.info).split(' ')[0]}" class="w-4 h-4 ${(typeIcons[n.type] || typeIcons.info).split(' ')[1]}"></i>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between gap-2">
                    <h4 class="font-bold text-xs leading-tight">${this.escapeHTML(n.title)}</h4>
                    <span class="text-[9px] font-mono opacity-40 shrink-0">${n.timestamp}</span>
                </div>
                <p class="text-xs opacity-70 mt-1 leading-relaxed">${this.escapeHTML(n.message)}</p>
            </div>
        </div>
    `).join('');

    this.renderIcons();
};

window.openNotificationPanel = function () {
    if (!window.pclinkUI) return;
    window.pclinkUI.markNotificationsAsRead();

    const title = `<i data-feather="bell" class="text-primary w-4"></i> Notification Center`;
    const body = `<div id="panelNotificationList" class="space-y-3"></div>`;
    const footer = `
        <button class="btn btn-sm btn-ghost font-bold text-xs" onclick="window.clearNotifications()">Clear All</button>
        <button class="btn btn-sm btn-primary text-white font-bold uppercase text-xs px-6" onclick="window.closeSidePanel()">Close</button>
    `;

    window.openSidePanel(title, body, footer);
    window.pclinkUI.renderNotificationPanelList();
};

window.clearNotifications = function () {
    if (window.pclinkUI) {
        window.pclinkUI.notifications = [];
        window.pclinkUI.updateNotificationUI();
    }
};
