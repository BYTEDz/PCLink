/**
 * PCLink Unified Extension Frontend SDK v2.0
 * Provides sandbox communication, Host Broker API access, token propagation,
 * Material 3 theme token injection, and tactile feedback across mobile and web contexts.
 */
(function (global) {
    'use strict';

    class PCLinkSDK {
        constructor() {
            this.version = '2.0.0';
            this._listeners = new Map();
            this._token = this._resolveToken();
            this._extensionId = this._resolveExtensionId();
            this._initThemeSync();
        }

        _resolveToken() {
            const urlParams = new URLSearchParams(window.location.search);
            const queryToken = urlParams.get('token') || urlParams.get('api_key') || urlParams.get('x-api-key');
            if (queryToken) return queryToken;

            const match = document.cookie.match(/(?:^|; )pclink_device_token=([^;]*)/);
            if (match && match[1]) return decodeURIComponent(match[1]);

            return null;
        }

        _resolveExtensionId() {
            const parts = window.location.pathname.split('/');
            const extIdx = parts.indexOf('extensions');
            if (extIdx !== -1 && parts[extIdx + 1]) {
                return decodeURIComponent(parts[extIdx + 1]);
            }
            return new URLSearchParams(window.location.search).get('extension_id') || 'unknown';
        }

        _applyThemeTokens(config) {
            const root = document.documentElement;
            const theme = config.theme || 'dark';

            root.setAttribute('data-theme', theme);
            root.style.setProperty('color-scheme', theme);

            const formatColor = (hex) => {
                if (!hex) return null;
                return hex.startsWith('#') ? hex : '#' + hex;
            };

            const bg = formatColor(config.background_color);
            const surface = formatColor(config.surface_color);
            const cardBg = formatColor(config.card_bg) || surface;
            const primary = formatColor(config.primary_color);
            const onPrimary = formatColor(config.on_primary_color);
            const accent = formatColor(config.accent_color);
            const text = formatColor(config.text_color);
            const textMuted = formatColor(config.text_muted_color);
            const error = formatColor(config.error_color);
            const divider = formatColor(config.divider_color);

            if (bg) {
                root.style.setProperty('--bg', bg);
                root.style.setProperty('--background', bg);
                root.style.setProperty('--background-color', bg);
            }
            if (surface) {
                root.style.setProperty('--surface', surface);
                root.style.setProperty('--surface-color', surface);
            }
            if (cardBg) {
                root.style.setProperty('--card-bg', cardBg);
            }
            if (primary) {
                root.style.setProperty('--primary', primary);
                root.style.setProperty('--primary-color', primary);
                root.style.setProperty('--primary-muted', primary + '33');
                root.style.setProperty('--primary-faint', primary + '14');
            }
            if (onPrimary) {
                root.style.setProperty('--on-primary', onPrimary);
            }
            if (accent) {
                root.style.setProperty('--accent', accent);
                root.style.setProperty('--secondary', accent);
            }
            if (text) {
                root.style.setProperty('--text', text);
                root.style.setProperty('--text-color', text);
            }
            if (textMuted) {
                root.style.setProperty('--text-muted', textMuted);
                root.style.setProperty('--text-muted-color', textMuted);
            }
            if (error) {
                root.style.setProperty('--error', error);
                root.style.setProperty('--danger', error);
            }
            if (divider) {
                root.style.setProperty('--divider', divider);
                root.style.setProperty('--card-border', `1px solid ${divider}`);
            }

            if (config.radius) {
                root.style.setProperty('--radius', `${config.radius}px`);
            }
            if (config.safe_top) {
                root.style.setProperty('--safe-area-inset-top', `${config.safe_top}px`);
            }
            if (config.safe_bottom) {
                root.style.setProperty('--safe-area-inset-bottom', `${config.safe_bottom}px`);
            }

            if (theme === 'light') {
                root.style.setProperty('--card-shadow', '0 4px 16px rgba(0, 0, 0, 0.06)');
                root.style.setProperty('--surface-hover', 'rgba(0, 0, 0, 0.04)');
            } else {
                root.style.setProperty('--card-shadow', '0 8px 24px rgba(0, 0, 0, 0.3)');
                root.style.setProperty('--surface-hover', 'rgba(255, 255, 255, 0.06)');
            }
        }

        _initThemeSync() {
            const params = new URLSearchParams(window.location.search);
            const initialConfig = {
                theme: params.get('theme') || 'dark',
                background_color: params.get('background_color'),
                surface_color: params.get('surface_color'),
                card_bg: params.get('card_bg'),
                primary_color: params.get('primary_color'),
                on_primary_color: params.get('on_primary_color'),
                accent_color: params.get('accent_color'),
                text_color: params.get('text_color'),
                text_muted_color: params.get('text_muted_color'),
                error_color: params.get('error_color'),
                divider_color: params.get('divider_color'),
                radius: params.get('radius'),
                safe_top: params.get('safe_top'),
                safe_bottom: params.get('safe_bottom')
            };

            this._applyThemeTokens(initialConfig);

            // Listen for live Flutter theme updates
            global.updateTheme = (config) => {
                this._applyThemeTokens(config);
                this.emit('theme_change', config);
            };

            window.addEventListener('message', (event) => {
                if (event.data && event.data.type === 'PCLINK_THEME_CHANGE') {
                    this._applyThemeTokens(event.data);
                    this.emit('theme_change', event.data);
                }
            });
        }

        /**
         * Host Broker invocation wrapper with authenticated token propagation.
         */
        async callBroker(domain, method, params = {}) {
            const headers = { 'Content-Type': 'application/json' };
            if (this._token) {
                headers['X-API-Key'] = this._token;
            }

            let brokerUrl = `/extensions/${encodeURIComponent(this._extensionId)}/broker/${domain}/${method}`;
            if (this._token) {
                brokerUrl += `?token=${encodeURIComponent(this._token)}`;
            }

            const response = await fetch(brokerUrl, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(params),
                credentials: 'include'
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(err.detail || `Broker Error ${response.status}`);
            }
            return response.json();
        }

        // --- Foundational Primitives ---

        system = {
            exec: async (options) => {
                return this.callBroker('system', 'exec', options);
            }
        };

        fs = {
            readText: async (path) => {
                return this.callBroker('fs', 'readText', { path });
            },
            writeText: async (path, content) => {
                return this.callBroker('fs', 'writeText', { path, content });
            },
            listDir: async (path = '.') => {
                return this.callBroker('fs', 'listDir', { path });
            }
        };

        fetch = async (url, options = {}) => {
            return this.callBroker('fetch', 'request', { url, ...options });
        };

        storage = {
            get: async (key, defaultValue = null) => {
                const res = await this.callBroker('storage', 'get', { key, default: defaultValue });
                return res !== undefined && res.value !== undefined ? res.value : defaultValue;
            },
            set: async (key, value) => {
                return this.callBroker('storage', 'set', { key, value });
            }
        };

        // --- Convenience Domains ---

        input = {
            mouseMove: async (dx, dy) => this.callBroker('input', 'mouseMove', { dx, dy }),
            mouseClick: async (button = 'left', clicks = 1) => this.callBroker('input', 'mouseClick', { button, clicks }),
            pressKey: async (keyStr, modifiers = []) => this.callBroker('input', 'pressKey', { keyStr, modifiers })
        };

        media = {
            getState: async () => this.callBroker('media', 'getState'),
            playPause: async () => this.callBroker('media', 'command', { action: 'play_pause' }),
            next: async () => this.callBroker('media', 'command', { action: 'next' }),
            previous: async () => this.callBroker('media', 'command', { action: 'previous' }),
            command: async (action) => this.callBroker('media', 'command', { action })
        };

        power = {
            shutdown: async () => this.callBroker('power', 'execute', { action: 'shutdown' }),
            reboot: async () => this.callBroker('power', 'execute', { action: 'reboot' }),
            sleep: async () => this.callBroker('power', 'execute', { action: 'sleep' }),
            lock: async () => this.callBroker('power', 'execute', { action: 'lock' })
        };

        notifications = {
            show: async (title, message, type = 'info') => {
                return this.callBroker('notifications', 'show', { title, message, type });
            }
        };

        ui = {
            haptic: (pattern = 'selection') => {
                if (window.navigator && window.navigator.vibrate) {
                    if (pattern === 'selection') window.navigator.vibrate(10);
                    else if (pattern === 'success') window.navigator.vibrate([15, 30, 15]);
                    else if (pattern === 'error') window.navigator.vibrate([50, 50, 50]);
                }
            }
        };

        // --- Event Subsystem ---

        on(eventName, handler) {
            if (!this._listeners.has(eventName)) {
                this._listeners.set(eventName, new Set());
            }
            this._listeners.get(eventName).add(handler);
        }

        off(eventName, handler) {
            if (this._listeners.has(eventName)) {
                this._listeners.get(eventName).delete(handler);
            }
        }

        emit(eventName, data = {}) {
            if (this._listeners.has(eventName)) {
                this._listeners.get(eventName).forEach(handler => {
                    try { handler(data); } catch (e) { console.error(e); }
                });
            }
        }
    }

    global.PCLink = new PCLinkSDK();
    global.pclink = global.PCLink;

})(typeof window !== 'undefined' ? window : this);
