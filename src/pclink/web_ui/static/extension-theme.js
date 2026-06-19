/**
 * PCLink Extension Theme Sync SDK
 * Handles synchronization between Mobile App theme and Extension Web UI.
 */
(function () {
    const urlParams = new URLSearchParams(window.location.search);

    // Helper to get color with #
    const getC = (key) => {
        const val = urlParams.get(key);
        return val ? (val.startsWith('#') ? val : '#' + val) : null;
    };

    const theme = urlParams.get('theme') || 'dark';
    const radius = urlParams.get('radius') || '12';
    const fontScale = urlParams.get('font_scale') || '1';
    const elevation = urlParams.get('elevation') || '2';
    const density = urlParams.get('density') || '0';
    const safeTop = urlParams.get('safe_top') || '0';
    const safeBottom = urlParams.get('safe_bottom') || '0';

    const colors = {
        '--bg': getC('background_color'),
        '--bg-color': getC('background_color'),
        '--background': getC('background_color'),
        '--surface': getC('surface_color'),
        '--card-bg': getC('surface_color'),
        '--primary': getC('primary_color'),
        '--accent': getC('accent_color'),
        '--text': getC('text_color'),
        '--text-muted': getC('text_muted_color'),
        '--danger': getC('error_color'),
        '--error': getC('error_color'),
        '--divider': getC('divider_color'),
        '--radius': radius + 'px',
        '--font-scale': fontScale,
        '--elevation': elevation + 'px',
        '--density-scale': (1 + (parseFloat(density) * 0.1)).toString(),
        '--safe-top': safeTop + 'px',
        '--safe-bottom': safeBottom + 'px',
    };

    // Apply colors and radius to root
    for (const [prop, val] of Object.entries(colors)) {
        if (val) document.documentElement.style.setProperty(prop, val);
    }

    // Helper: Calculate contrast color (Black or White)
    function getContrastColor(hexColor) {
        if (!hexColor) return '#ffffff';
        const hex = hexColor.replace('#', '');
        const r = parseInt(hex.substr(0, 2), 16);
        const g = parseInt(hex.substr(2, 2), 16);
        const b = parseInt(hex.substr(4, 2), 16);
        const yiq = ((r * 299) + (g * 587) + (b * 114)) / 1000;
        return (yiq >= 128) ? '#000000' : '#ffffff';
    }

    // Set contrast colors
    const primary = getC('primary_color');
    if (primary) {
        document.documentElement.style.setProperty('--on-primary', getContrastColor(primary));
        document.documentElement.style.setProperty('--primary-muted', primary + '22'); // 13% opacity
        document.documentElement.style.setProperty('--primary-faint', primary + '11'); // 6% opacity
    }

    const background = getC('background_color');
    if (background) {
        document.documentElement.style.setProperty('--on-background', getContrastColor(background));
    }

    // Semantic defaults (Success/Warning)
    document.documentElement.style.setProperty('--success', '#4CAF50');
    document.documentElement.style.setProperty('--warning', '#FFC107');

    // Set theme-specific defaults (Shadows, Borders, and Contrast)
    const elVal = parseFloat(elevation) || 2;
    const shadowY = elVal * 2;
    const shadowBlur = elVal * 4;

    if (theme === 'light') {
        document.documentElement.style.setProperty('--card-shadow', `0 ${shadowY}px ${shadowBlur}px rgba(0, 0, 0, 0.08)`);
        document.documentElement.style.setProperty('--card-border', '1px solid rgba(0, 0, 0, 0.08)');
        document.documentElement.style.setProperty('--hover-overlay', 'rgba(0, 0, 0, 0.04)');
    } else {
        document.documentElement.style.setProperty('--card-shadow', `0 ${shadowY}px ${shadowBlur}px rgba(0, 0, 0, 0.3)`);
        document.documentElement.style.setProperty('--card-border', '1px solid rgba(255, 255, 255, 0.08)');
        document.documentElement.style.setProperty('--hover-overlay', 'rgba(255, 255, 255, 0.06)');
    }

    // Inject Base Native-like CSS
    const style = document.createElement('style');
    style.innerHTML = `
        :root {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
            color-scheme: ${theme};
        }
        body {
            background-color: var(--bg);
            color: var(--text);
            font-size: calc(16px * var(--font-scale, 1));
            margin: 0;
            padding-top: var(--safe-top);
            padding-bottom: var(--safe-bottom);
            overflow-x: hidden;
        }
        button, .btn {
            border-radius: var(--radius);
            font-weight: 600;
            transition: all 0.2s ease;
            cursor: pointer;
            border: none;
        }
        button:active {
            transform: scale(0.96);
        }
        .card {
            background-color: var(--surface);
            border-radius: var(--radius);
            border: var(--card-border);
            box-shadow: var(--card-shadow);
        }
        .pclink-back-btn {
            position: fixed;
            top: calc(var(--safe-top) + 12px);
            left: 16px;
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: var(--surface);
            color: var(--text);
            border: var(--card-border);
            box-shadow: var(--card-shadow);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 1000;
            transition: all 0.2s ease;
            font-size: 18px;
            user-select: none;
        }
        .pclink-back-btn:active {
            transform: scale(0.9);
            background: var(--bg);
        }
        .pclink-dialog-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            padding: 20px;
            font-family: inherit;
        }
        .pclink-dialog {
            background: var(--surface);
            color: var(--text);
            border-radius: var(--radius);
            border: var(--card-border);
            box-shadow: var(--card-shadow);
            max-width: 400px;
            width: 100%;
            padding: 24px;
            animation: pclink-dialog-in 0.2s ease-out;
        }
        @keyframes pclink-dialog-in {
            from { opacity: 0; transform: scale(0.95); }
            to { opacity: 1; transform: scale(1); }
        }
        .pclink-dialog-title {
            font-weight: 700;
            font-size: calc(16px * var(--font-scale, 1));
            margin-bottom: 12px;
        }
        .pclink-dialog-body {
            font-size: calc(14px * var(--font-scale, 1));
            opacity: 0.9;
            margin-bottom: 24px;
            line-height: 1.5;
        }
        .pclink-dialog-footer {
            display: flex;
            justify-content: flex-end;
            gap: 12px;
        }
        .pclink-dialog-btn {
            padding: 8px 16px;
            font-size: calc(14px * var(--font-scale, 1));
            border-radius: var(--radius);
            cursor: pointer;
            font-weight: 600;
            border: none;
            transition: opacity 0.2s;
        }
        .pclink-dialog-btn-primary {
            background: var(--primary);
            color: var(--on-primary);
        }
        .pclink-dialog-btn-secondary {
            background: transparent;
            color: var(--text);
            border: 1px solid var(--card-border);
        }
        .pclink-dialog-input {
            width: 100%;
            padding: 10px;
            margin-bottom: 20px;
            border-radius: var(--radius);
            border: 1px solid var(--card-border);
            background: var(--bg);
            color: var(--text);
            font-family: inherit;
            font-size: inherit;
        }
    `;
    document.head.appendChild(style);

    console.log('PCLink Theme Sync SDK v2.1 Active:', { theme, radius, fontScale, elevation, density, safeTop, safeBottom });

    // Custom Dialog System Implementation
    const DialogManager = {
        createOverlay() {
            const overlay = document.createElement('div');
            overlay.className = 'pclink-dialog-overlay';
            overlay.innerHTML = `
                <div class="pclink-dialog">
                    <div id="pclink-dialog-title" class="pclink-dialog-title"></div>
                    <div id="pclink-dialog-body" class="pclink-dialog-body"></div>
                    <div id="pclink-dialog-input-container"></div>
                    <div id="pclink-dialog-footer" class="pclink-dialog-footer"></div>
                </div>
            `;
            document.body.appendChild(overlay);
            return overlay;
        },

        async show({ title, message, type = 'alert', defaultValue = '' }) {
            const overlay = this.createOverlay();
            const titleEl = overlay.querySelector('#pclink-dialog-title');
            const bodyEl = overlay.querySelector('#pclink-dialog-body');
            const inputContainer = overlay.querySelector('#pclink-dialog-input-container');
            const footer = overlay.querySelector('#pclink-dialog-footer');

            titleEl.textContent = title;
            bodyEl.textContent = message;
            inputContainer.innerHTML = '';
            footer.innerHTML = '';

            let resolvePromise;
            const promise = new Promise(resolve => { resolvePromise = resolve; });

            let input = null;
            if (type === 'prompt') {
                input = document.createElement('input');
                input.className = 'pclink-dialog-input';
                input.value = defaultValue;
                inputContainer.appendChild(input);
            }

            const createBtn = (text, className, callback) => {
                const btn = document.createElement('button');
                btn.className = `pclink-dialog-btn ${className}`;
                btn.textContent = text;
                btn.onclick = () => {
                    const result = type === 'prompt' ? (input ? input.value : null) : callback();
                    overlay.remove();
                    resolvePromise(result);
                };
                return btn;
            };

            if (type === 'confirm' || type === 'prompt') {
                footer.appendChild(createBtn('Cancel', 'pclink-dialog-btn-secondary', () => false));
            }

            footer.appendChild(createBtn('OK', 'pclink-dialog-btn-primary', () => true));

            return promise;
        }
    };

    // Overwrite native browser dialogs
    window.alert = function(message) {
        DialogManager.show({
            title: 'Notification',
            message: message,
            type: 'alert'
        });
        return undefined;
    };

    window.confirm = async function(message) {
        return await DialogManager.show({
            title: 'Confirmation',
            message: message,
            type: 'confirm'
        });
    };

    window.prompt = async function(message, defaultValue = '') {
        return await DialogManager.show({
            title: 'Input Required',
            message: message,
            type: 'prompt',
            defaultValue: defaultValue
        });
    };
    // Back Navigation Management
    window.pclink = {
        onBackRequest: () => true,
    };

    const BackButtonManager = {
        init() {
            this.btn = document.createElement('div');
            this.btn.className = 'pclink-back-btn';
            this.btn.innerHTML = '←';
            this.btn.style.display = 'none';
            this.btn.onclick = () => {
                if (window.pclink.onBackRequest()) {
                    window.history.back();
                }
            };
            document.body.appendChild(this.btn);

            window.addEventListener('popstate', () => this.updateVisibility());
            this.updateVisibility();
        },
        updateVisibility() {
            // Show button only if there is history to go back to
            this.btn.style.display = window.history.length > 1 ? 'flex' : 'none';
        }
    };

    BackButtonManager.init();
})();
