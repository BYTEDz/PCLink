// static/js/mirror.js

// Screen Mirroring Subsystem JS
window._mirrorActive = false;

window.loadMirrorTab = async () => {
    await window.runMirrorDiagnostics();
    await window.refreshMirrorStatus();
};

window._peerConnection = null;
window._wsConnection = null;

async function startWebRTC() {
    try {
        const pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });
        window._peerConnection = pc;

        const video = document.getElementById('mirrorLiveVideo');
        pc.ontrack = (event) => {
            if (video && event.streams && event.streams[0]) {
                video.srcObject = event.streams[0];
            }
        };

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${protocol}//${window.location.host}/mirror/ws`);
        window._wsConnection = ws;

        ws.onopen = () => {
            ws.send(JSON.stringify({ type: 'REQUEST_OFFER' }));
        };

        ws.onmessage = async (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                switch (msg.type) {
                    case 'LOCAL_SDP_GENERATED':
                        await pc.setRemoteDescription(new RTCSessionDescription({
                            type: msg.sdp_type.toLowerCase(),
                            sdp: msg.sdp
                        }));
                        const answer = await pc.createAnswer();
                        await pc.setLocalDescription(answer);
                        ws.send(JSON.stringify({
                            type: 'SET_REMOTE_SDP',
                            sdp: answer.sdp,
                            sdp_type: 'answer'
                        }));
                        break;
                    case 'LOCAL_ICE_CANDIDATE':
                        await pc.addIceCandidate(new RTCIceCandidate({
                            candidate: msg.candidate,
                            sdpMLineIndex: msg.sdpMLineIndex,
                            sdpMid: msg.sdpMid
                        }));
                        break;
                }
            } catch (err) {
                console.error("WebRTC Signaling error:", err);
            }
        };

        pc.onicecandidate = (event) => {
            if (event.candidate && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'ADD_ICE_CANDIDATE',
                    candidate: event.candidate.candidate,
                    sdpMLineIndex: event.candidate.sdpMLineIndex,
                    sdpMid: event.candidate.sdpMid
                }));
            }
        };

        const staticStatus = document.getElementById('mirror_static_status');
        if (staticStatus) staticStatus.classList.add('hidden');

        const videoCanvas = document.getElementById('mirror_video_canvas');
        if (videoCanvas) videoCanvas.classList.remove('hidden');
    } catch (e) {
        console.error("Failed to start WebRTC client", e);
    }
}

function stopWebRTC() {
    if (window._peerConnection) {
        window._peerConnection.close();
        window._peerConnection = null;
    }
    if (window._wsConnection) {
        window._wsConnection.close();
        window._wsConnection = null;
    }
    const video = document.getElementById('mirrorLiveVideo');
    if (video) video.srcObject = null;

    const staticStatus = document.getElementById('mirror_static_status');
    if (staticStatus) staticStatus.classList.remove('hidden');

    const videoCanvas = document.getElementById('mirror_video_canvas');
    if (videoCanvas) videoCanvas.classList.add('hidden');
}

window.expandMirrorFullscreen = (event) => {
    if (event) event.stopPropagation();
    const video = document.getElementById('mirrorLiveVideo');
    if (video) {
        if (video.requestFullscreen) {
            video.requestFullscreen();
        } else if (video.webkitRequestFullscreen) {
            video.webkitRequestFullscreen();
        } else if (video.msRequestFullscreen) {
            video.msRequestFullscreen();
        }
    }
};

window.runMirrorDiagnostics = async () => {
    const binaryBadge = document.getElementById('diag_req_binary');
    const displayBadge = document.getElementById('diag_req_display');
    const pipewireBadge = document.getElementById('diag_req_pipewire');
    const portalBadge = document.getElementById('diag_req_portal');
    const encodersContainer = document.getElementById('encoders_container');
    const codecNoticeText = document.getElementById('codec_notice_text');
    const codecAlertBox = document.getElementById('codec_alert_box');
    const statusBanner = document.getElementById('mirrorSystemStatusBanner');
    const statusIcon = document.getElementById('mirrorSystemStatusIcon');
    const statusTitle = document.getElementById('mirrorSystemStatusTitle');
    const statusDesc = document.getElementById('mirrorSystemStatusDesc');

    if (binaryBadge) binaryBadge.className = "badge badge-neutral gap-1 font-bold text-[10px]";
    if (binaryBadge) binaryBadge.textContent = "Analyzing...";

    try {
        const res = await window.pclinkUI.webUICall('/mirror/diagnostics');
        if (!res.ok) throw new Error();
        const data = await res.json();

        // 1. Binary Check
        if (binaryBadge) {
            if (data.binary_exists) {
                binaryBadge.className = "badge badge-success text-white gap-1 font-bold text-[10px]";
                binaryBadge.innerHTML = `<i data-feather="check" class="w-3 h-3"></i> Active`;
            } else {
                binaryBadge.className = "badge badge-error text-white gap-1 font-bold text-[10px]";
                binaryBadge.innerHTML = `<i data-feather="x" class="w-3 h-3"></i> Missing`;
            }
        }

        // 2. Display Check
        if (displayBadge) {
            displayBadge.className = "badge badge-primary text-white gap-1 font-bold text-[10px]";
            displayBadge.textContent = data.display_server || 'Unknown';
        }

        // 3. Pipewire Check
        if (pipewireBadge) {
            if (data.pipewire === 'running') {
                pipewireBadge.className = "badge badge-success text-white gap-1 font-bold text-[10px]";
                pipewireBadge.innerHTML = `<i data-feather="check" class="w-3 h-3"></i> Active`;
            } else {
                pipewireBadge.className = "badge badge-neutral gap-1 font-bold text-[10px]";
                pipewireBadge.textContent = data.pipewire || 'Not Running';
            }
        }

        // 4. Portal Check
        if (portalBadge) {
            if (data.xdg_portal === 'running') {
                portalBadge.className = "badge badge-success text-white gap-1 font-bold text-[10px]";
                portalBadge.innerHTML = `<i data-feather="check" class="w-3 h-3"></i> Active`;
            } else {
                portalBadge.className = "badge badge-neutral gap-1 font-bold text-[10px]";
                portalBadge.textContent = data.xdg_portal || 'Not Detected';
            }
        }

        // 5. Encoders Probing
        if (encodersContainer) {
            encodersContainer.innerHTML = '';
            if (data.encoders && data.encoders.length > 0) {
                data.encoders.forEach(enc => {
                    const encCard = document.createElement('div');
                    encCard.className = "flex items-center justify-between p-3 border border-base-300 rounded-xl bg-base-200/50";

                    let label = enc;
                    let desc = "Hardware Accelerated";
                    let isHardware = true;
                    let badgeClass = "badge badge-success text-white font-bold text-[10px]";

                    if (enc === 'x264') {
                        label = "x264 Encoder";
                        desc = "Software (High CPU Fallback)";
                        isHardware = false;
                        badgeClass = "badge badge-warning text-black font-bold text-[10px]";
                    } else if (enc === 'vah264') {
                        label = "VA-API H.264";
                        desc = "Intel/AMD GPU Driver";
                    } else if (enc === 'nvenc') {
                        label = "NVIDIA NVENC H.264";
                        desc = "NVIDIA GPU Driver";
                    }

                    encCard.innerHTML = `
                        <div>
                            <h4 class="font-bold text-xs">${label}</h4>
                            <p class="text-[9px] opacity-60">${desc}</p>
                        </div>
                        <span class="${badgeClass}">${isHardware ? 'GPU Accel' : 'CPU Only'}</span>
                    `;
                    encodersContainer.appendChild(encCard);
                });

                // Show notice based on hardware acceleration
                const hasGPU = data.encoders.some(e => e !== 'x264');
                if (codecAlertBox && codecNoticeText) {
                    codecAlertBox.classList.remove('hidden');
                    if (hasGPU) {
                        codecAlertBox.className = "alert border border-success/20 bg-success/10 text-success p-3 mt-4 flex text-xs font-bold";
                        codecNoticeText.innerHTML = `System supports hardware accelerated mirroring! Extremely low latency and minimal CPU usage guaranteed.`;
                    } else {
                        codecAlertBox.className = "alert border border-warning/20 bg-warning/10 text-warning p-3 mt-4 flex text-xs font-bold";
                        codecNoticeText.innerHTML = `No hardware-accelerated video encoders detected. Falling back to software encoding (x264), which may utilize high CPU when active.`;
                    }
                }
            } else {
                encodersContainer.innerHTML = `
                    <div class="text-center py-6 col-span-2 opacity-50 text-xs font-bold text-error">
                        No encoders detected. Ensure GStreamer and plugins are installed correctly.
                    </div>
                `;
            }
        }

        // 5b. Update dropdown options dynamically based on available GPU encoders
        const encoderSelect = document.getElementById('mirror_encoder');
        if (encoderSelect) {
            const options = Array.from(encoderSelect.options);
            options.forEach(opt => {
                const val = opt.value;
                if (val === 'auto' || val === 'x264') {
                    opt.hidden = false;
                    opt.disabled = false;
                } else {
                    const isSupported = data.encoders && data.encoders.includes(val);
                    opt.hidden = !isSupported;
                    opt.disabled = !isSupported;
                }
            });
            if (encoderSelect.selectedOptions[0]?.disabled || encoderSelect.selectedOptions[0]?.hidden) {
                encoderSelect.value = 'auto';
            }
        }

        // 6. Summary Status Banner
        if (statusBanner) {
            statusBanner.classList.remove('hidden');

            if (data.status === 'supported') {
                statusBanner.className = "alert border border-success/20 bg-success/5 shadow-md border-l-8 border-l-success transition-all duration-300 flex p-4";
                statusIcon.innerHTML = `<i data-feather="check-circle" class="w-6 h-6 text-success"></i>`;
                statusTitle.className = "font-black text-sm text-success";
                statusTitle.textContent = "System Fully Supported";
                statusDesc.className = "text-xs text-success/80 mt-0.5 font-medium";
                statusDesc.textContent = "Your system satisfies all requirements. FerrumCast is ready to mirror with hardware acceleration.";
            } else if (data.status === 'missing_binary') {
                statusBanner.className = "alert border border-warning/20 bg-warning/5 shadow-md border-l-8 border-l-warning transition-all duration-300 flex p-4";
                statusIcon.innerHTML = `<i data-feather="alert-triangle" class="w-6 h-6 text-warning"></i>`;
                statusTitle.className = "font-black text-sm text-warning";
                statusTitle.textContent = "Native Engine Missing";
                statusDesc.className = "text-xs text-warning/80 mt-0.5 font-medium";
                statusDesc.textContent = "The native FerrumCast binary is missing. Compile the Rust project and place the binary into src/pclink/assets/bin/ferrumcast.";
            } else if (data.status === 'wayland_missing_portal') {
                statusBanner.className = "alert border border-error/20 bg-error/5 shadow-md border-l-8 border-l-error transition-all duration-300 flex p-4";
                statusIcon.innerHTML = `<i data-feather="x-circle" class="w-6 h-6 text-error"></i>`;
                statusTitle.className = "font-black text-sm text-error";
                statusTitle.textContent = "Wayland Portal Missing";
                statusDesc.className = "text-xs text-error/80 mt-0.5 font-medium";
                statusDesc.textContent = "You are running Wayland without xdg-desktop-portal. Screen capture permissions cannot be prompted.";
            } else {
                statusBanner.className = "alert border border-info/20 bg-info/5 shadow-md border-l-8 border-l-info transition-all duration-300 flex p-4";
                statusIcon.innerHTML = `<i data-feather="info" class="w-6 h-6 text-info"></i>`;
                statusTitle.className = "font-black text-sm text-info";
                statusTitle.textContent = "Diagnostics Complete";
                statusDesc.className = "text-xs text-info/80 mt-0.5 font-medium";
                statusDesc.textContent = "Platform checks ran successfully. Review requirements list below.";
            }
        }

    } catch (e) {
        window.pclinkUI.showToast('Diagnostics Failed', 'Failed to run mirroring diagnostics check', 'error');
    }

    if (window.feather) feather.replace();
};

window.refreshMirrorStatus = async () => {
    try {
        const res = await window.pclinkUI.webUICall('/mirror/status');
        if (res.ok) {
            const data = await res.json();
            window.updateMirrorUIStatus(data.active);
        }
    } catch (e) { }
};

window.updateMirrorUIStatus = (active) => {
    window._mirrorActive = active;

    const pulseDot = document.getElementById('stream_pulse_dot');
    const stateBadge = document.getElementById('mirror_state_badge');
    const liveStatus = document.getElementById('mirror_live_status');
    const liveSub = document.getElementById('mirror_live_sub');
    const toggleBtn = document.getElementById('btn_toggle_mirror');

    if (!toggleBtn) return;

    if (active) {
        if (pulseDot) pulseDot.classList.remove('hidden');
        if (stateBadge) {
            stateBadge.className = "badge badge-success text-white font-black uppercase text-[10px] tracking-wider mb-2 animate-pulse";
            stateBadge.textContent = "Streaming";
        }
        if (liveStatus) {
            liveStatus.className = "text-3xl font-black tracking-tight text-success";
            liveStatus.textContent = "ACTIVE";
        }
        if (liveSub) liveSub.textContent = "GStreamer pipeline is running natively";

        toggleBtn.className = "btn btn-error text-white font-bold w-full";
        toggleBtn.innerHTML = `<i data-feather="square" class="w-4 h-4"></i> Stop Preview`;
    } else {
        if (pulseDot) pulseDot.classList.add('hidden');
        if (stateBadge) {
            stateBadge.className = "badge badge-neutral font-black uppercase text-[10px] tracking-wider mb-2";
            stateBadge.textContent = "Inactive";
        }
        if (liveStatus) {
            liveStatus.className = "text-3xl font-black tracking-tight";
            liveStatus.textContent = "Inactive";
        }
        if (liveSub) liveSub.textContent = "No mirroring session is active";

        toggleBtn.className = "btn btn-primary text-white font-bold w-full";
        toggleBtn.innerHTML = `<i data-feather="play" class="w-4 h-4"></i> Start Web Preview`;

        // Clean up WebRTC objects when stream is killed
        stopWebRTC();
    }

    if (window.feather) feather.replace();
};

window.toggleMirrorSession = async (event) => {
    if (event) event.stopPropagation();
    if (window._mirrorActive) {
        // Stop stream
        try {
            const res = await window.pclinkUI.webUICall('/mirror/stop', { method: 'POST' });
            if (res.ok) {
                window.pclinkUI.showToast('Stream Stopped', 'Mirroring pipeline terminated successfully', 'success');
                window.updateMirrorUIStatus(false);
            } else {
                window.pclinkUI.showToast('Error', 'Failed to stop mirroring pipeline', 'error');
            }
        } catch (e) {
            window.pclinkUI.showToast('Error', 'Failed to communicate with server', 'error');
        }
    } else {
        // Start stream
        const resVal = document.getElementById('mirror_res').value;
        const fpsVal = document.getElementById('mirror_fps').value;
        const encoder = document.getElementById('mirror_encoder').value;
        const bitrate = parseInt(document.getElementById('mirror_bitrate').value);

        let width = null;
        let height = null;
        if (resVal !== 'passthrough') {
            const [w, h] = resVal.split('x');
            width = parseInt(w);
            height = parseInt(h);
        }

        const fps = fpsVal === 'passthrough' ? null : parseInt(fpsVal);

        const body = {
            outputMode: 'webrtc',
            udpHost: null,
            encoder: encoder,
            bitrate: bitrate,
            width: width,
            height: height,
            fps: fps
        };

        try {
            window.pclinkUI.showToast('Starting Stream', 'Initializing GStreamer engine...', 'info');
            const res = await window.pclinkUI.webUICall('/mirror/start', {
                method: 'POST',
                body: JSON.stringify(body)
            });

            if (res.ok) {
                window.pclinkUI.showToast('Stream Active', 'Local WebRTC Preview Active', 'success');
                window.updateMirrorUIStatus(true);
                await startWebRTC();
            } else {
                const data = await res.json();
                window.pclinkUI.showToast('Failed to Start', data.detail || 'Internal pipeline initialization failure', 'error');
            }
        } catch (e) {
            window.pclinkUI.showToast('Error', 'Connection error starting pipeline', 'error');
        }
    }
};

window.resetMirrorPortalSession = async () => {
    try {
        window.pclinkUI.showToast('Clearing Session', 'Requesting portal token reset...', 'info');
        const res = await window.pclinkUI.webUICall('/mirror/reset-portal', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                window.pclinkUI.showToast('Session Reset', 'Screen share restore token cleared. Next preview will prompt for screen choice.', 'success');
            } else {
                window.pclinkUI.showToast('No Token', 'No active cached portal session token to clear.', 'warning');
            }
        } else {
            window.pclinkUI.showToast('Error', 'Failed to clear session token', 'error');
        }
    } catch (e) {
        window.pclinkUI.showToast('Error', 'Failed to communicate with portal subsystem', 'error');
    }
};
