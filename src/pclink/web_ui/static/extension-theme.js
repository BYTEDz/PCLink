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
    if (theme === 'light') {
        document.documentElement.style.setProperty('--card-shadow', '0 2px 8px rgba(0, 0, 0, 0.05)');
        document.documentElement.style.setProperty('--card-border', '1px solid rgba(0, 0, 0, 0.08)');
        document.documentElement.style.setProperty('--hover-overlay', 'rgba(0, 0, 0, 0.04)');
    } else {
        document.documentElement.style.setProperty('--card-shadow', '0 8px 24px rgba(0, 0, 0, 0.2)');
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
            margin: 0;
            padding: 0;
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
    `;
    document.head.appendChild(style);

    console.log('PCLink Theme Sync SDK v2.0 Active:', theme, 'Radius:', radius);
})();
