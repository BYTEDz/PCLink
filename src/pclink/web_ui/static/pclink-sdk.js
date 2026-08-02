/**
 * PCLink Unified Extension Frontend SDK v1.0
 * Provides extension UIs with unified access to Theme Sync, API wrappers,
 * Notifications, Dialogs, Event Listener, and Clipboard utilities.
 */
(function (global) {
    'use strict';

    class PCLinkSDK {
        constructor() {
            this.version = '1.0.0';
            this._listeners = new Map();
            this._initSDK();
        }

        _initSDK() {
            console.log(`[PCLink SDK v${this.version}] Initialized for extension UI.`);
        }

        /**
         * Make an authenticated REST API request to the PCLink host server.
         * @param {string} endpoint - API path (e.g. '/system/info' or '/files/browse')
         * @param {Object} options - Fetch options (method, headers, body)
         */
        async request(endpoint, options = {}) {
            const cleanPath = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
            const headers = options.headers || {};

            if (!headers['Content-Type'] && options.body && typeof options.body === 'object') {
                headers['Content-Type'] = 'application/json';
                options.body = JSON.stringify(options.body);
            }

            const config = {
                method: options.method || 'GET',
                headers: headers,
                body: options.body,
                credentials: 'include'
            };

            const response = await fetch(cleanPath, config);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(errorData.detail || `HTTP Error ${response.status}`);
            }
            return response.json();
        }

        /**
         * Trigger a host desktop / web UI toast notification.
         * @param {string} title
         * @param {string} message
         * @param {string} type - 'info' | 'success' | 'warning' | 'error'
         */
        async notify(title, message, type = 'info') {
            try {
                return await this.request('/ui/notifications/show', {
                    method: 'POST',
                    body: { title, message, type }
                });
            } catch (e) {
                console.warn('[PCLink SDK] Notification error:', e);
            }
        }

        /**
         * Listen to system/extension events broadcast from the host.
         * @param {string} eventName
         * @param {Function} handler
         */
        on(eventName, handler) {
            if (!this._listeners.has(eventName)) {
                this._listeners.set(eventName, new Set());
            }
            this._listeners.get(eventName).add(handler);
        }

        /**
         * Remove an event listener.
         * @param {string} eventName
         * @param {Function} handler
         */
        off(eventName, handler) {
            if (this._listeners.has(eventName)) {
                this._listeners.get(eventName).delete(handler);
            }
        }

        /**
         * Emit an event locally or to the extension event bus.
         * @param {string} eventName
         * @param {Object} data
         */
        emit(eventName, data = {}) {
            if (this._listeners.has(eventName)) {
                this._listeners.get(eventName).forEach(handler => {
                    try {
                        handler(data);
                    } catch (e) {
                        console.error(`[PCLink SDK] Error in event listener for '${eventName}':`, e);
                    }
                });
            }
        }
    }

    global.PCLink = new PCLinkSDK();

})(typeof window !== 'undefined' ? window : this);
