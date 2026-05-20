// static/app.js - PCLink Web UI Entry Point

/**
 * PCLink Decoupled Architecture
 * Logic distributed across:
 * - js/core.js (Foundation & UI Utilities)
 * - js/devices.js (Device & Security Management)
 * - js/macros.js (Macro Engine & Editor)
 * - js/phone.js (File Browser & Remote Ops)
 * - js/system.js (Server Settings & Status)
 * - js/extensions.js (Extension Subsystem)
 * - js/mirror.js (Screen Mirroring Subsystem)
 */

document.addEventListener('DOMContentLoaded', () => {
    // Initialize the global UI instance
    window.pclinkUI = new PCLinkWebUI();
    window.pclinkUI.init();
});

// Post-init checks or high-level global listeners can go here
window.addEventListener('load', () => {
    // Ensure all feather icons are rendered correctly after all modules load
    if (window.feather) feather.replace();
});
