/**
 * PCLink Unified Extension Frontend SDK v2.1
 * Provides sandbox communication, Host Broker API access, Zero-Trust Hardware E2EE
 * bridge routing, mutation fetch interception, token propagation, Material 3 theme
 * token injection, dynamic widget height reporting, and themed dialog interception.
 */
(function (global) {
    'use strict';

    class PCLinkSDK {
        constructor() {
            this.version = '2.1.0';
            this._listeners = new Map();
            this._pendingBridgeRequests = new Map();
            this._token = this._resolveToken();
            this._extensionId = this._resolveExtensionId();
            this._initBridgeResponseHandler();
            this._initFetchInterceptor();
            this._initThemeSync();
            this._initWidgetAutoResizer();
            this._initCustomDialogs();
        }

        _initBridgeResponseHandler() {
            global._onPCLinkBridgeResponse = (reqId, success, result, error) => {
                const pending = this._pendingBridgeRequests.get(reqId);
                if (pending) {
                    this._pendingBridgeRequests.delete(reqId);
                    if (success) {
                        pending.resolve(result);
                    } else {
                        pending.reject(new Error(error || 'Bridge request failed'));
                    }
                }
            };
        }

        _initFetchInterceptor() {
            if (!window.PCLinkBridge || typeof window.PCLinkBridge.postMessage !== 'function') {
                return;
            }

            const originalFetch = window.fetch;
            const self = this;

            window.fetch = async function (resource, init = {}) {
                let url = typeof resource === 'string' ? resource : (resource && resource.url ? resource.url : '');
                const method = (init.method || 'GET').toUpperCase();

                // Intercept mutation HTTP requests (POST, PUT, PATCH, DELETE) targeting extension endpoints
                const isMutation = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
                const isExtensionEndpoint =
                    url.startsWith('./') ||
                    url.startsWith('../') ||
                    url.includes('/extensions/') ||
                    (!url.startsWith('http://') && !url.startsWith('https://'));

                if (isMutation && isExtensionEndpoint) {
                    // Resolve clean absolute path for FastAPI router dispatch
                    let cleanPath = url;
                    if (cleanPath.startsWith('./')) {
                        const currentBasePath = window.location.pathname.replace(/\/ui\/?$/, '').replace(/\/widget\/[^\/]+\/?$/, '');
                        cleanPath = currentBasePath + '/' + cleanPath.slice(2);
                    } else if (cleanPath.startsWith('../')) {
                        const currentBasePath = window.location.pathname.replace(/\/ui\/?$/, '').replace(/\/widget\/[^\/]+\/?$/, '');
                        cleanPath = currentBasePath + '/' + cleanPath;
                    } else if (!cleanPath.startsWith('/')) {
                        const currentBasePath = window.location.pathname.replace(/\/ui\/?$/, '').replace(/\/widget\/[^\/]+\/?$/, '');
                        cleanPath = currentBasePath + '/' + cleanPath;
                    }

                    return new Promise((resolve, reject) => {
                        const reqId = 'fetch_' + Math.random().toString(36).substring(2, 10) + '_' + Date.now();
                        self._pendingBridgeRequests.set(reqId, {
                            resolve: (data) => {
                                const bodyString = typeof data === 'string' ? data : JSON.stringify(data);
                                resolve(new Response(bodyString, {
                                    status: 200,
                                    statusText: 'OK',
                                    headers: { 'Content-Type': 'application/json' }
                                }));
                            },
                            reject: (err) => {
                                reject(err);
                            }
                        });

                        // Timeout safeguard after 30 seconds
                        setTimeout(() => {
                            if (self._pendingBridgeRequests.has(reqId)) {
                                self._pendingBridgeRequests.delete(reqId);
                                reject(new Error('Extension mutation timed out via PCLink Bridge'));
                            }
                        }, 30000);

                        let parsedBody = null;
                        if (init.body) {
                            try {
                                parsedBody = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
                            } catch (_) {
                                parsedBody = init.body;
                            }
                        }

                        window.PCLinkBridge.postMessage(JSON.stringify({
                            reqId: reqId,
                            type: 'http',
                            path: cleanPath,
                            method: method,
                            body: parsedBody
                        }));
                    });
                }

                return originalFetch.apply(this, arguments);
            };
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

        _initWidgetAutoResizer() {
            const isWidget = window.location.pathname.includes('/widget/') || window.location.search.includes('widget=true');
            if (!isWidget) return;

            const reportExactHeight = () => {
                const body = document.body;
                const doc = document.documentElement;
                if (!body) return;

                const rectHeight = body.getBoundingClientRect().height;
                const scrollHeight = Math.max(body.scrollHeight, doc ? doc.scrollHeight : 0);
                const offsetHeight = Math.max(body.offsetHeight, doc ? doc.offsetHeight : 0);

                let targetHeight = rectHeight > 20 ? rectHeight : Math.min(scrollHeight, offsetHeight);

                if (targetHeight > 0 && window.PCLinkWidget) {
                    window.PCLinkWidget.postMessage('height:' + Math.ceil(targetHeight));
                    window.PCLinkWidget.postMessage('loaded');
                }
            };

            window.addEventListener('DOMContentLoaded', () => {
                reportExactHeight();

                if (window.ResizeObserver && document.body) {
                    new ResizeObserver(() => reportExactHeight()).observe(document.body);
                }

                const observer = new MutationObserver(() => reportExactHeight());
                observer.observe(document.documentElement, { attributes: true, childList: true, subtree: true });

                if (document.fonts && document.fonts.ready) {
                    document.fonts.ready.then(reportExactHeight);
                }

                window.addEventListener('load', reportExactHeight);
                window.addEventListener('resize', reportExactHeight);

                setTimeout(reportExactHeight, 150);
                setTimeout(reportExactHeight, 500);
            });

            global.pclinkReportHeight = reportExactHeight;
        }

        _initCustomDialogs() {
            if (document.getElementById('pclink-sdk-dialog-style')) return;

            const style = document.createElement('style');
            style.id = 'pclink-sdk-dialog-style';
            style.textContent = `
                .pclink-dialog-overlay {
                    position: fixed;
                    inset: 0;
                    background: rgba(0, 0, 0, 0.65);
                    backdrop-filter: blur(4px);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 100000;
                    padding: 16px;
                    opacity: 0;
                    transition: opacity 0.15s ease-out;
                }
                .pclink-dialog-overlay.active {
                    opacity: 1;
                }
                .pclink-dialog-card {
                    background: var(--surface, #1e1f22);
                    border: var(--card-border, 1px solid rgba(255, 255, 255, 0.08));
                    box-shadow: var(--card-shadow, 0 8px 24px rgba(0, 0, 0, 0.35));
                    border-radius: var(--radius, 16px);
                    color: var(--text, #f8fafc);
                    width: 100%;
                    max-width: 380px;
                    padding: 20px;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                    transform: scale(0.95);
                    transition: transform 0.15s cubic-bezier(0.2, 0, 0, 1);
                }
                .pclink-dialog-overlay.active .pclink-dialog-card {
                    transform: scale(1);
                }
                .pclink-dialog-title {
                    font-size: 0.95rem;
                    font-weight: 800;
                    margin: 0;
                }
                .pclink-dialog-body {
                    font-size: 0.82rem;
                    line-height: 1.45;
                    color: var(--text-muted, rgba(248, 250, 252, 0.65));
                    word-break: break-word;
                }
                .pclink-dialog-input {
                    background: var(--surface-hover, rgba(255, 255, 255, 0.08));
                    border: var(--card-border, 1px solid rgba(255, 255, 255, 0.08));
                    color: var(--text, #f8fafc);
                    padding: 10px 12px;
                    border-radius: calc(var(--radius, 16px) * 0.6);
                    font-size: 0.85rem;
                    outline: none;
                    width: 100%;
                }
                .pclink-dialog-input:focus {
                    border-color: var(--primary, #3b82f6);
                }
                .pclink-dialog-actions {
                    display: flex;
                    justify-content: flex-end;
                    gap: 8px;
                    margin-top: 4px;
                }
                .pclink-dialog-btn {
                    padding: 8px 16px;
                    font-size: 0.8rem;
                    font-weight: 700;
                    border-radius: calc(var(--radius, 16px) * 0.6);
                    cursor: pointer;
                    border: var(--card-border, 1px solid rgba(255, 255, 255, 0.08));
                    background: var(--surface-hover, rgba(255, 255, 255, 0.08));
                    color: var(--text, #f8fafc);
                    user-select: none;
                }
                .pclink-dialog-btn:active {
                    transform: scale(0.97);
                }
                .pclink-dialog-btn-primary {
                    background: var(--primary, #3b82f6);
                    color: var(--on-primary, #ffffff);
                    border-color: var(--primary, #3b82f6);
                }
            `;
            document.head.appendChild(style);

            const showDialog = ({ title = '', message = '', type = 'alert', defaultValue = '' }) => {
                return new Promise((resolve) => {
                    const overlay = document.createElement('div');
                    overlay.className = 'pclink-dialog-overlay';

                    const defaultTitles = {
                        alert: 'Notification',
                        confirm: 'Confirmation',
                        prompt: 'Input Required'
                    };

                    const card = document.createElement('div');
                    card.className = 'pclink-dialog-card';

                    const heading = document.createElement('h3');
                    heading.className = 'pclink-dialog-title';
                    heading.textContent = title || defaultTitles[type] || '';

                    const bodyText = document.createElement('div');
                    bodyText.className = 'pclink-dialog-body';
                    bodyText.textContent = message;

                    card.appendChild(heading);
                    card.appendChild(bodyText);

                    let input = null;
                    if (type === 'prompt') {
                        input = document.createElement('input');
                        input.type = 'text';
                        input.className = 'pclink-dialog-input';
                        input.value = defaultValue;
                        card.appendChild(input);
                    }

                    const actions = document.createElement('div');
                    actions.className = 'pclink-dialog-actions';

                    const closeWith = (val) => {
                        overlay.classList.remove('active');
                        setTimeout(() => {
                            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                            resolve(val);
                        }, 150);
                    };

                    if (type === 'confirm' || type === 'prompt') {
                        const cancelBtn = document.createElement('button');
                        cancelBtn.className = 'pclink-dialog-btn';
                        cancelBtn.textContent = 'Cancel';
                        cancelBtn.onclick = () => closeWith(type === 'prompt' ? null : false);
                        actions.appendChild(cancelBtn);
                    }

                    const okBtn = document.createElement('button');
                    okBtn.className = 'pclink-dialog-btn pclink-dialog-btn-primary';
                    okBtn.textContent = 'OK';
                    okBtn.onclick = () => closeWith(type === 'prompt' ? (input ? input.value : '') : true);
                    actions.appendChild(okBtn);

                    card.appendChild(actions);
                    overlay.appendChild(card);
                    document.body.appendChild(overlay);

                    requestAnimationFrame(() => overlay.classList.add('active'));

                    if (input) {
                        setTimeout(() => input.focus(), 50);
                        input.onkeydown = (e) => {
                            if (e.key === 'Enter') okBtn.click();
                            if (e.key === 'Escape') closeWith(null);
                        };
                    } else {
                        okBtn.focus();
                    }
                });
            };

            this._dialog = showDialog;

            global.alert = (msg) => {
                if (this.ui && this.ui.haptic) this.ui.haptic('selection');
                return showDialog({ type: 'alert', message: String(msg) });
            };

            global.confirm = (msg) => {
                if (this.ui && this.ui.haptic) this.ui.haptic('selection');
                return showDialog({ type: 'confirm', message: String(msg) });
            };

            global.prompt = (msg, defaultText = '') => {
                if (this.ui && this.ui.haptic) this.ui.haptic('selection');
                return showDialog({ type: 'prompt', message: String(msg), defaultValue: defaultText });
            };
        }

        async callBroker(domain, method, params = {}) {
            // Priority 1: Zero-Trust Flutter JS-Bridge (Native Hardware AES-256-GCM E2EE)
            if (window.PCLinkBridge && typeof window.PCLinkBridge.postMessage === 'function') {
                return new Promise((resolve, reject) => {
                    const reqId = 'req_' + Math.random().toString(36).substring(2, 10) + '_' + Date.now();
                    this._pendingBridgeRequests.set(reqId, { resolve, reject });

                    setTimeout(() => {
                        if (this._pendingBridgeRequests.has(reqId)) {
                            this._pendingBridgeRequests.delete(reqId);
                            reject(new Error('Broker call timed out via PCLink Bridge'));
                        }
                    }, 30000);

                    window.PCLinkBridge.postMessage(JSON.stringify({
                        reqId: reqId,
                        type: 'broker',
                        extensionId: this._extensionId,
                        domain: domain,
                        method: method,
                        params: params
                    }));
                });
            }

            // Priority 2: Direct HTTP fetch (Desktop browser / Local Web UI)
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
            },
            alert: (message, title) => this._dialog({ type: 'alert', message: String(message), title }),
            confirm: (message, title) => this._dialog({ type: 'confirm', message: String(message), title }),
            prompt: (message, defaultValue, title) => this._dialog({ type: 'prompt', message: String(message), defaultValue, title })
        };

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
