diff --git a/src/pclink/api_server/api.py b/src/pclink/api_server/api.py
index a3ba2d6..64e9575 100644
--- a/src/pclink/api_server/api.py
+++ b/src/pclink/api_server/api.py
@@ -25,6 +25,7 @@ from ..web_ui.router import create_web_ui_router
 
 # --- API Router Imports ---
 from .file_browser import router as file_browser_router
+from .phone_file_router import router as phone_file_router
 
 # UPDATED: Import from the new transfers package
 from .transfer_router import upload_router, download_router, restore_sessions_startup, cleanup_stale_sessions
@@ -236,6 +237,7 @@ def create_api_app(api_key: str, controller_instance, connected_devices: Dict, a
     app.include_router(upload_router, prefix="/files/upload", tags=["Uploads"], dependencies=MOBILE_API)
     app.include_router(download_router, prefix="/files/download", tags=["Downloads"], dependencies=MOBILE_API)
     app.include_router(file_browser_router, prefix="/files", tags=["Files"], dependencies=MOBILE_API)
+    app.include_router(phone_file_router, prefix="/phone/files", tags=["Phone Files"], dependencies=MOBILE_API)
     
     app.include_router(system_router, prefix="/system", tags=["System"], dependencies=MOBILE_API)
     app.include_router(media_streaming_router, prefix="/files", tags=["Streaming"], dependencies=MOBILE_API)
diff --git a/src/pclink/web_ui/static/app.js b/src/pclink/web_ui/static/app.js
index 7b09a41..e347199 100644
--- a/src/pclink/web_ui/static/app.js
+++ b/src/pclink/web_ui/static/app.js
@@ -13,6 +13,16 @@ class PCLinkWebUI {
         this.notificationSettings = this.loadNotificationSettings();
         this.serverStartTime = Date.now();
         this.lastDeviceActivity = null;
+        this.currentPhonePath = '/';
+        this.phoneNavHistory = ['/'];
+        this.phoneHistoryIndex = 0;
+        this.phoneSearchQuery = '';
+        this.phoneSortMode = 'name_asc';
+        this.phoneShowHidden = false;
+        this.phoneSelectedItems = new Set();
+        this.phoneFileItems = [];
+        this.phoneIsReadOnly = false;
+        this.isUploading = false;
         this.init();
     }
 
@@ -176,6 +186,9 @@ class PCLinkWebUI {
             case 'services':
                 await this.loadServices();
                 break;
+            case 'phone-files':
+                await this.loadPhoneFiles(this.currentPhonePath);
+                break;
         }
     }
 
@@ -669,6 +682,258 @@ class PCLinkWebUI {
             this.loadServices();
         }
     }
+
+    async loadPhoneFiles(path) {
+        const listContainer = document.getElementById('phoneFileList');
+        const breadcrumb = document.getElementById('phoneBreadcrumb');
+        const backBtn = document.getElementById('phoneBackBtn');
+        const forwardBtn = document.getElementById('phoneForwardBtn');
+        
+        if (breadcrumb) breadcrumb.innerHTML = `<span>Path: ${path}</span>`;
+        if (backBtn) backBtn.disabled = this.phoneHistoryIndex <= 0;
+        if (forwardBtn) forwardBtn.disabled = this.phoneHistoryIndex >= this.phoneNavHistory.length - 1;
+        
+            const cleanPath = path.startsWith('/') ? path : '/' + path;
+            const container = document.getElementById('phoneFileList');
+            const disabledState = container.querySelector('.service-disabled');
+            
+            try {
+                const response = await fetch(`/phone/files/.browse${cleanPath}`, {
+                    headers: this.getHeaders()
+                });
+                
+                if (response.ok) {
+                    const data = await response.json();
+                    this.phoneFileItems = data.items || [];
+                    this.phoneIsReadOnly = data.readOnly || false;
+                    if (disabledState) disabledState.style.display = 'none';
+                    this.updatePhoneUIPermissions();
+                    this.displayPhoneFiles();
+                } else if (response.status === 502 || response.status === 404) {
+                    // 502/404 from proxy usually means phone is offline or service is off
+                    container.innerHTML = ''; // Clear previous content
+                    if (disabledState) {
+                        disabledState.style.display = 'block';
+                        container.appendChild(disabledState);
+                    } else {
+                        container.innerHTML = `<p class="error">Failed to load files: ${response.statusText}</p>`;
+                    }
+                } else {
+                    container.innerHTML = `<p class="error">Failed to load files: ${response.statusText}</p>`;
+                }
+            } catch (error) {
+                console.error('Connection error:', error);
+                if (disabledState) {
+                    disabledState.style.display = 'block';
+                    container.innerHTML = ''; 
+                    container.appendChild(disabledState);
+                } else {
+                    container.innerHTML = `<p class="error">Error: ${error.message}</p>`;
+                }
+            }
+    }
+
+    displayPhoneFiles() {
+        const listContainer = document.getElementById('phoneFileList');
+        
+        // 1. Filter
+        let filtered = this.phoneFileItems.filter(item => {
+            // Hidden filter
+            if (!this.phoneShowHidden && item.name.startsWith('.')) return false;
+            // Search filter
+            if (this.phoneSearchQuery && !item.name.toLowerCase().includes(this.phoneSearchQuery.toLowerCase())) return false;
+            return true;
+        });
+
+        // 2. Sort
+        filtered.sort((a, b) => {
+            // Folders always first
+            if (a.isDir && !b.isDir) return -1;
+            if (!a.isDir && b.isDir) return 1;
+
+            const [field, direction] = this.phoneSortMode.split('_');
+            let comparison = 0;
+
+            switch (field) {
+                case 'name':
+                    comparison = a.name.localeCompare(b.name);
+                    break;
+                case 'size':
+                    comparison = (a.size || 0) - (b.size || 0);
+                    break;
+                case 'date':
+                    comparison = new Date(a.modified) - new Date(b.modified);
+                    break;
+            }
+
+            return direction === 'asc' ? comparison : -comparison;
+        });
+
+        if (filtered.length === 0) {
+            listContainer.innerHTML = '<div class="empty-state"><i data-feather="inbox"></i><p>No matching files</p></div>';
+            if (window.feather) feather.replace();
+            return;
+        }
+
+        listContainer.innerHTML = filtered.map(item => {
+            const isSelected = this.phoneSelectedItems.has(item.path);
+            return `
+                <div class="file-item ${item.isDir ? 'directory' : 'file'}" onclick="handleFileItemClick(event, '${item.path}', ${item.isDir})">
+                    <input type="checkbox" class="file-select-checkbox" ${isSelected ? 'checked' : ''} 
+                           onclick="event.stopPropagation(); toggleItemSelection('${item.path}')">
+                    <div class="file-icon">
+                        <i data-feather="${item.isDir ? 'folder' : 'file'}"></i>
+                    </div>
+                    <div class="file-info">
+                        <span class="file-name">${item.name}</span>
+                        <span class="file-meta">${item.isDir ? 'Directory' : this.formatFileSize(item.size)} • ${new Date(item.modified).toLocaleString()}</span>
+                    </div>
+                    <div class="file-actions">
+                        ${!item.isDir ? `<i data-feather="download" title="Download" onclick="event.stopPropagation(); downloadPhoneFile('${item.path}')"></i>` : `<i data-feather="chevron-right"></i>`}
+                    </div>
+                </div>
+            `;
+        }).join('');
+        
+        if (window.feather) feather.replace();
+    }
+
+    updatePhoneUIPermissions() {
+        const uploadBtn = document.getElementById('phoneUploadBtn');
+        const deleteBtn = document.getElementById('batchDeleteBtn');
+        const badge = document.getElementById('phoneReadOnlyBadge');
+        
+        if (uploadBtn) {
+            uploadBtn.style.display = this.phoneIsReadOnly ? 'none' : 'flex';
+        }
+        if (deleteBtn) {
+            deleteBtn.style.display = this.phoneIsReadOnly ? 'none' : 'flex';
+        }
+        if (badge) {
+            badge.style.display = this.phoneIsReadOnly ? 'inline-flex' : 'none';
+        }
+    }
+
+    async uploadFile(file) {
+        const container = document.getElementById('uploadProgressContainer');
+        const uploadId = 'up-' + Math.random().toString(36).substr(2, 9);
+        
+        const itemHtml = `
+            <div id="${uploadId}" class="upload-item">
+                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
+                    <span>📤 ${file.name}</span>
+                    <span class="progress-text">0%</span>
+                </div>
+                <div class="progress-bar-bg">
+                    <div class="progress-bar-fill" style="width: 0%"></div>
+                </div>
+            </div>
+        `;
+        container.insertAdjacentHTML('afterbegin', itemHtml);
+
+        try {
+            const formData = new FormData();
+            formData.append('file', file);
+
+            const cleanBasePath = this.currentPhonePath.endsWith('/') ? this.currentPhonePath : this.currentPhonePath + '/';
+            const fileName = file.name;
+            const cleanFullPath = (cleanBasePath + fileName).startsWith('/') ? (cleanBasePath + fileName) : '/' + (cleanBasePath + fileName);
+            
+            console.log(`[Upload] Starting upload of ${file.name} to ${cleanFullPath}`);
+
+            const xhr = new XMLHttpRequest();
+            xhr.open('PUT', `/phone/files${cleanFullPath}`, true);
+            
+            // Add API key if present
+            if (this.apiKey) {
+                xhr.setRequestHeader('X-API-Key', this.apiKey);
+            }
+
+            xhr.upload.onprogress = (e) => {
+                if (e.lengthComputable) {
+                    const percent = Math.round((e.loaded / e.total) * 100);
+                    const el = document.getElementById(uploadId);
+                    if (el) {
+                        el.querySelector('.progress-bar-fill').style.width = percent + '%';
+                        el.querySelector('.progress-text').textContent = percent + '%';
+                    }
+                }
+            };
+
+            const promise = new Promise((resolve, reject) => {
+                xhr.onload = () => {
+                    if (xhr.status >= 200 && xhr.status < 300) resolve();
+                    else reject(new Error(`Upload failed: ${xhr.statusText}`));
+                };
+                xhr.onerror = () => reject(new Error('Network error'));
+            });
+
+            xhr.send(file); 
+            await promise;
+
+            const el = document.getElementById(uploadId);
+            if (el) {
+                el.style.opacity = '0.5';
+                setTimeout(() => el.remove(), 2000);
+            }
+            this.showToast('Success', `Uploaded ${file.name}`);
+        } catch (error) {
+            console.error('Upload failed:', error);
+            const el = document.getElementById(uploadId);
+            if (el) el.style.color = 'var(--danger-color)';
+            this.showToast('Error', `Failed to upload ${file.name}`, 'error');
+        }
+    }
+
+    async deletePhoneItems(paths) {
+        if (!confirm(`Are you sure you want to delete ${paths.length} item(s)?`)) return;
+
+        let successCount = 0;
+        for (const path of paths) {
+            try {
+                const cleanPath = path.startsWith('/') ? path : '/' + path;
+                const response = await fetch(`/phone/files${cleanPath}`, {
+                    method: 'DELETE',
+                    headers: this.getHeaders()
+                });
+                if (response.ok) successCount++;
+            } catch (error) {
+                console.error(`Failed to delete ${path}:`, error);
+            }
+        }
+
+        if (successCount > 0) {
+            this.showToast('Success', `Deleted ${successCount} item(s)`);
+            this.phoneSelectedItems.clear();
+            this.updateBatchActionBar();
+            this.loadPhoneFiles(this.currentPhonePath);
+        } else {
+            this.showToast('Error', 'Deletion failed', 'error');
+        }
+    }
+
+    updateBatchActionBar() {
+        const bar = document.getElementById('batchActionBar');
+        const count = document.getElementById('selectedCount');
+        if (!bar || !count) return;
+
+        const selectedCount = this.phoneSelectedItems.size;
+        count.textContent = selectedCount;
+
+        if (selectedCount > 0) {
+            bar.classList.add('active');
+        } else {
+            bar.classList.remove('active');
+        }
+    }
+
+    formatFileSize(bytes) {
+        if (bytes === 0) return '0 B';
+        const k = 1024;
+        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
+        const i = Math.floor(Math.log(bytes) / Math.log(k));
+        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
+    }
 }
 
 // Global functions for HTML onclick attributes
@@ -774,6 +1039,147 @@ async function toggleService(serviceId, enabled) {
     }
 }
 
+// Phone File Navigation
+window.navigatePhone = (path) => {
+    if (window.pclinkUI) {
+        // Handle history
+        if (path !== window.pclinkUI.currentPhonePath) {
+            // Remove any forward history if we're at a branch
+            window.pclinkUI.phoneNavHistory = window.pclinkUI.phoneNavHistory.slice(0, window.pclinkUI.phoneHistoryIndex + 1);
+            window.pclinkUI.phoneNavHistory.push(path);
+            window.pclinkUI.phoneHistoryIndex = window.pclinkUI.phoneNavHistory.length - 1;
+        }
+        
+        window.pclinkUI.currentPhonePath = path;
+        window.pclinkUI.phoneSelectedItems.clear();
+        window.pclinkUI.updateBatchActionBar();
+        window.pclinkUI.loadPhoneFiles(path);
+    }
+};
+
+window.refreshPhoneFiles = () => {
+    if (window.pclinkUI) {
+        window.pclinkUI.loadPhoneFiles(window.pclinkUI.currentPhonePath);
+    }
+};
+
+window.goBackPhoneFiles = () => {
+    if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex > 0) {
+        window.pclinkUI.phoneHistoryIndex--;
+        const path = window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex];
+        window.pclinkUI.currentPhonePath = path;
+        window.pclinkUI.loadPhoneFiles(path);
+    }
+};
+
+window.goForwardPhoneFiles = () => {
+    if (window.pclinkUI && window.pclinkUI.phoneHistoryIndex < window.pclinkUI.phoneNavHistory.length - 1) {
+        window.pclinkUI.phoneHistoryIndex++;
+        const path = window.pclinkUI.phoneNavHistory[window.pclinkUI.phoneHistoryIndex];
+        window.pclinkUI.currentPhonePath = path;
+        window.pclinkUI.loadPhoneFiles(path);
+    }
+};
+
+// Selection & Actions
+window.toggleItemSelection = (path) => {
+    if (window.pclinkUI) {
+        if (window.pclinkUI.phoneSelectedItems.has(path)) {
+            window.pclinkUI.phoneSelectedItems.delete(path);
+        } else {
+            window.pclinkUI.phoneSelectedItems.add(path);
+        }
+        window.pclinkUI.updateBatchActionBar();
+        window.pclinkUI.displayPhoneFiles();
+    }
+};
+
+window.clearSelection = () => {
+    if (window.pclinkUI) {
+        window.pclinkUI.phoneSelectedItems.clear();
+        window.pclinkUI.updateBatchActionBar();
+        window.pclinkUI.displayPhoneFiles();
+    }
+};
+
+window.handleFileItemClick = (event, path, isDir) => {
+    // If clicking the item with Ctrl/Meta, toggle selection
+    if (event.ctrlKey || event.metaKey) {
+        toggleItemSelection(path);
+    } else if (isDir) {
+        navigatePhone(path);
+    } else {
+        // Non-directory single click = toggle selection for now, or could do nothing
+        toggleItemSelection(path);
+    }
+};
+
+// Filtering & Sorting
+window.handlePhoneSearch = (query) => {
+    if (window.pclinkUI) {
+        window.pclinkUI.phoneSearchQuery = query;
+        window.pclinkUI.displayPhoneFiles();
+    }
+};
+
+window.handlePhoneSort = (mode) => {
+    if (window.pclinkUI) {
+        window.pclinkUI.phoneSortMode = mode;
+        window.pclinkUI.displayPhoneFiles();
+    }
+};
+
+window.handleToggleHidden = (show) => {
+    if (window.pclinkUI) {
+        window.pclinkUI.phoneShowHidden = show;
+        window.pclinkUI.displayPhoneFiles();
+    }
+};
+
+// Upload & Delete
+window.triggerUpload = () => {
+    document.getElementById('phoneUploadInput').click();
+};
+
+window.handlePhoneUpload = async (input) => {
+    if (!input.files || input.files.length === 0) return;
+    if (window.pclinkUI) {
+        for (const file of input.files) {
+            await window.pclinkUI.uploadFile(file);
+        }
+        window.refreshPhoneFiles();
+        input.value = ''; // Reset input
+    }
+};
+
+window.deleteSelectedItems = () => {
+    if (window.pclinkUI) {
+        const paths = Array.from(window.pclinkUI.phoneSelectedItems);
+        window.pclinkUI.deletePhoneItems(paths);
+    }
+};
+
+window.downloadSelectedItems = () => {
+    if (window.pclinkUI) {
+        const paths = Array.from(window.pclinkUI.phoneSelectedItems);
+        // Sequential download (browsers handle this by triggering multiple saves or pops)
+        paths.forEach(path => {
+            const cleanPath = path.startsWith('/') ? path : '/' + path;
+            const link = document.createElement('a');
+            link.href = `/phone/files${cleanPath}`;
+            link.download = path.split('/').pop();
+            document.body.appendChild(link);
+            link.click();
+            document.body.removeChild(link);
+        });
+    }
+};
+
+window.downloadPhoneFile = (path) => {
+    // Generate an absolute URL for download
+    window.location.href = `/phone/files${path.startsWith('/') ? path : '/' + path}`;
+};
+
 // Initialization
 document.addEventListener('DOMContentLoaded', () => {
     window.pclinkUI = new PCLinkWebUI();
diff --git a/src/pclink/web_ui/static/index.html b/src/pclink/web_ui/static/index.html
index 6a1c62d..ecd92d1 100644
--- a/src/pclink/web_ui/static/index.html
+++ b/src/pclink/web_ui/static/index.html
@@ -60,6 +60,10 @@
             <i data-feather="link"></i>
             <span>Pairing</span>
           </button>
+          <button class="nav-item" data-tab="phone-files">
+            <i data-feather="folder"></i>
+            <span>Phone Files</span>
+          </button>
           <button class="nav-item" data-tab="services">
             <i data-feather="grid"></i>
             <span>Services</span>
@@ -501,10 +505,112 @@
           </div>
         </div>
 
+        <div class="tab-content" id="phone-files">
+          <div class="card">
+            <div class="file-browser-header">
+              <h3>
+                <i data-feather="smartphone"></i>
+                <span>Phone File Explorer</span>
+                <span id="phoneReadOnlyBadge" class="status-badge warning" style="display: none;">
+                  <i data-feather="lock"></i> Read-Only
+                </span>
+              </h3>
+              <div class="file-browser-actions">
+                <button
+                  class="btn btn-sm"
+                  onclick="goBackPhoneFiles()"
+                  id="phoneBackBtn"
+                  disabled
+                  title="Back"
+                >
+                  <i data-feather="arrow-left"></i>
+                </button>
+                <button
+                  class="btn btn-sm"
+                  onclick="goForwardPhoneFiles()"
+                  id="phoneForwardBtn"
+                  disabled
+                  title="Forward"
+                >
+                  <i data-feather="arrow-right"></i>
+                </button>
+                <button class="btn btn-sm" onclick="refreshPhoneFiles()" title="Refresh">
+                  <i data-feather="refresh-cw"></i>
+                </button>
+                <button class="btn btn-sm btn-primary" id="phoneUploadBtn" onclick="triggerUpload()" title="Upload Files">
+                  <i data-feather="upload"></i>
+                  <span>Upload</span>
+                </button>
+                <input type="file" id="phoneUploadInput" class="hidden-file-input" multiple onchange="handlePhoneUpload(this)">
+              </div>
+            </div>
+
+            <div class="file-browser-controls">
+              <div class="search-wrapper">
+                <i data-feather="search"></i>
+                <input type="text" id="phoneFileSearch" class="search-input" placeholder="Search files..." oninput="handlePhoneSearch(this.value)">
+              </div>
+              <div class="filter-controls">
+                <select id="phoneFileSort" class="sort-select" onchange="handlePhoneSort(this.value)">
+                  <option value="name_asc">Name (A-Z)</option>
+                  <option value="name_desc">Name (Z-A)</option>
+                  <option value="size_asc">Size (Smallest)</option>
+                  <option value="size_desc">Size (Largest)</option>
+                  <option value="date_desc">Last Modified (Newest)</option>
+                  <option value="date_asc">Last Modified (Oldest)</option>
+                </select>
+                <label class="toggle-hidden-btn">
+                  <input type="checkbox" id="showHiddenFiles" onchange="handleToggleHidden(this.checked)">
+                  <span>Hidden</span>
+                </label>
+              </div>
+            </div>
+
+            <div class="breadcrumb" id="phoneBreadcrumb">
+              <span>Path: /</span>
+            </div>
+
+            <div id="uploadProgressContainer" class="upload-progress-container"></div>
+
+            <div id="phoneFileList" class="file-list-container">
+              <div class="empty-state service-disabled" style="display: none;">
+                <i data-feather="alert-triangle" class="warning-icon"></i>
+                <h4>WebDAV Service Disabled</h4>
+                <p>Please enable <strong>Direct File Access</strong> in PCLink Advanced Settings on your phone to browse files.</p>
+                <button class="btn btn-primary" onclick="refreshPhoneFiles()">
+                  <i data-feather="refresh-cw"></i> Retry Connection
+                </button>
+              </div>
+              <p>Loading files...</p>
+            </div>
+          </div>
+        </div>
+
+        <!-- Batch Action Bar (Hidden by default) -->
+        <div id="batchActionBar" class="batch-action-bar">
+          <div class="selection-info">
+            <span id="selectedCount">0</span> items selected
+          </div>
+          <div class="batch-actions">
+            <button class="btn btn-sm btn-danger" id="batchDeleteBtn" onclick="deleteSelectedItems()">
+              <i data-feather="trash-2"></i> Delete
+            </button>
+            <button class="btn btn-sm btn-primary" onclick="downloadSelectedItems()">
+              <i data-feather="download"></i> Download
+            </button>
+            <button class="btn btn-sm btn-secondary" onclick="clearSelection()">
+              Cancel
+            </button>
+          </div>
+        </div>
+
         <div class="tab-content" id="services">
           <div class="card">
             <h3><i data-feather="grid"></i> Services Center</h3>
-            <p>Granularly enable or disable specific API features for security and customization.</p>
+            <p>
+              Granularly enable or disable specific API features for security
+              and customization.
+            </p>
             <div id="servicesGrid" class="services-grid">
               <div class="loading-state">
                 <i data-feather="loader" class="spinner"></i>
diff --git a/src/pclink/web_ui/static/style.css b/src/pclink/web_ui/static/style.css
index b232a58..a72579d 100644
--- a/src/pclink/web_ui/static/style.css
+++ b/src/pclink/web_ui/static/style.css
@@ -151,7 +151,8 @@ body {
   border-left-color: var(--primary-color);
 }
 
-.nav-item i {
+.nav-item i,
+.nav-item svg {
   width: 18px;
   height: 18px;
 }
@@ -248,7 +249,8 @@ body {
   border-color: var(--primary-color);
 }
 
-.action-btn i {
+.action-btn i,
+.action-btn svg {
   width: 16px;
   height: 16px;
 }
@@ -259,16 +261,33 @@ body {
 }
 
 /* Status Badge in Header */
-.header-actions .status-badge {
-  display: flex;
+.status-badge {
+  display: inline-flex;
   align-items: center;
-  gap: 8px;
-  padding: 8px 16px;
+  justify-content: center;
+  gap: 6px;
+  padding: 4px 12px;
   background: var(--bg-color);
   border-radius: 8px;
   border: 1px solid var(--border-color);
-  font-weight: 500;
-  font-size: 0.9rem;
+  font-weight: 600;
+  font-size: 0.8rem;
+  line-height: 1;
+  vertical-align: middle;
+}
+
+.status-badge.warning {
+  background: rgba(245, 158, 11, 0.1);
+  border-color: var(--warning-color);
+  color: var(--warning-color);
+}
+
+.status-badge i,
+.status-badge svg {
+  width: 14px;
+  height: 14px;
+  margin: 0;
+  color: inherit !important;
 }
 
 /* Status Dot */
@@ -363,7 +382,8 @@ body {
   flex-shrink: 0;
 }
 
-.metric-icon i {
+.metric-icon i,
+.metric-icon svg {
   width: 20px;
   height: 20px;
   color: var(--primary-color);
@@ -402,7 +422,8 @@ body {
   gap: 10px;
 }
 
-.card h3 i {
+.card h3 i,
+.card h3 svg {
   width: 22px;
   height: 22px;
   color: var(--primary-color);
@@ -479,7 +500,8 @@ body {
   font-size: 1rem;
 }
 
-.btn i {
+.btn i,
+.btn svg {
   width: 16px;
   height: 16px;
 }
@@ -1620,3 +1642,301 @@ input:checked + .slider:before {
   color: var(--text-secondary);
   gap: 15px;
 }
+
+/* Phone File Explorer Styles */
+.file-browser-header {
+  display: flex;
+  justify-content: space-between;
+  align-items: center;
+  margin-bottom: 20px;
+}
+
+.file-browser-actions {
+  display: flex;
+  gap: 12px;
+}
+
+.breadcrumb {
+  padding: 12px 16px;
+  background: var(--bg-color);
+  border-radius: 8px;
+  margin-bottom: 20px;
+  font-family: monospace;
+  font-size: 0.9rem;
+  color: var(--text-secondary);
+  border: 1px solid var(--border-color);
+}
+
+.file-list-container {
+  max-height: 600px;
+  overflow-y: auto;
+  background: var(--bg-color);
+  border-radius: 10px;
+  border: 1px solid var(--border-color);
+}
+
+.file-item {
+  display: flex;
+  align-items: center;
+  padding: 16px 20px;
+  border-bottom: 1px solid var(--border-color);
+  cursor: pointer;
+  transition: all 0.2s ease;
+}
+
+.file-item:last-child {
+  border-bottom: none;
+}
+
+.file-item:hover {
+  background: var(--surface-hover);
+  transform: translateX(4px);
+}
+
+.file-icon {
+  width: 40px;
+  height: 40px;
+  background: var(--surface-color);
+  border-radius: 8px;
+  display: flex;
+  align-items: center;
+  justify-content: center;
+  margin-right: 16px;
+  flex-shrink: 0;
+}
+
+.file-item.directory .file-icon i {
+  color: var(--primary-color);
+}
+
+.file-item.file .file-icon i {
+  color: var(--secondary-color);
+}
+
+.file-info {
+  flex: 1;
+  display: flex;
+  flex-direction: column;
+  gap: 2px;
+}
+
+.file-name {
+  font-weight: 600;
+  font-size: 1rem;
+  color: var(--text-primary);
+}
+
+.file-meta {
+  font-size: 0.85rem;
+  color: var(--text-secondary);
+}
+
+.file-actions {
+  color: var(--text-secondary);
+  opacity: 0.3;
+  transition: all 0.2s;
+}
+
+.file-item:hover .file-actions {
+  opacity: 1;
+  color: var(--primary-color);
+}
+
+/* Enhanced File Browser Controls */
+.file-browser-controls {
+  display: flex;
+  flex-wrap: wrap;
+  gap: 12px;
+  align-items: center;
+  margin-bottom: 16px;
+  padding: 12px;
+  background: var(--bg-color);
+  border-radius: 8px;
+  border: 1px solid var(--border-color);
+}
+
+.search-wrapper {
+  flex: 1;
+  min-width: 200px;
+  position: relative;
+}
+
+.search-wrapper i,
+.search-wrapper svg {
+  position: absolute;
+  left: 12px;
+  top: 50%;
+  transform: translateY(-50%);
+  color: var(--secondary-color);
+  width: 16px;
+  height: 16px;
+  pointer-events: none;
+}
+
+.search-input {
+  width: 100%;
+  padding: 10px 12px 10px 36px;
+  background: var(--surface-color);
+  border: 1px solid var(--border-color);
+  border-radius: 6px;
+  color: var(--text-primary);
+  font-size: 0.9rem;
+  height: 40px;
+}
+
+.search-input:focus {
+  outline: none;
+  border-color: var(--primary-color);
+  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2);
+}
+
+.filter-controls {
+  display: flex;
+  gap: 8px;
+  align-items: center;
+}
+
+.sort-select {
+  padding: 0 12px;
+  background: var(--surface-color);
+  border: 1px solid var(--border-color);
+  border-radius: 6px;
+  color: var(--text-primary);
+  font-size: 0.85rem;
+  cursor: pointer;
+  height: 40px;
+}
+
+.toggle-hidden-btn {
+  display: flex;
+  align-items: center;
+  gap: 6px;
+  font-size: 0.85rem;
+  color: var(--text-secondary);
+  cursor: pointer;
+  user-select: none;
+}
+
+.toggle-hidden-btn input {
+  cursor: pointer;
+}
+
+/* Multiselect Checkbox */
+.file-select-checkbox {
+  width: 20px;
+  height: 20px;
+  margin-right: 16px;
+  cursor: pointer;
+  accent-color: var(--primary-color);
+}
+
+/* Batch Action Bar */
+.batch-action-bar {
+  position: fixed;
+  bottom: 32px;
+  left: 50%;
+  transform: translateX(-50%) translateY(100px);
+  background: var(--surface-color);
+  border: 1px solid var(--primary-color);
+  border-radius: 999px;
+  padding: 12px 24px;
+  display: flex;
+  align-items: center;
+  gap: 20px;
+  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
+  z-index: 1100;
+  transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
+}
+
+.batch-action-bar.active {
+  transform: translateX(-50%) translateY(0);
+}
+
+.selection-info {
+  font-size: 0.9rem;
+  font-weight: 600;
+  color: var(--text-primary);
+  padding-right: 16px;
+  border-right: 1px solid var(--border-color);
+}
+
+.batch-actions {
+  display: flex;
+  gap: 12px;
+}
+
+/* Upload styles */
+.hidden-file-input {
+  display: none;
+}
+
+.upload-progress-container {
+  margin-top: 12px;
+}
+
+.upload-item {
+  padding: 8px;
+  background: var(--bg-color);
+  border-radius: 6px;
+  margin-bottom: 8px;
+  font-size: 0.85rem;
+}
+
+.progress-bar-bg {
+  height: 4px;
+  background: var(--surface-hover);
+  border-radius: 2px;
+  margin-top: 4px;
+  overflow: hidden;
+}
+
+.progress-bar-fill {
+  height: 100%;
+  background: var(--success-color);
+  width: 0%;
+  transition: width 0.3s ease;
+}
+
+.empty-state {
+  padding: 60px 20px;
+  text-align: center;
+  color: var(--text-secondary);
+  display: flex;
+  flex-direction: column;
+  align-items: center;
+  gap: 16px;
+}
+
+.empty-state i {
+  width: 48px;
+  height: 48px;
+  opacity: 0.3;
+}
+.empty-state.service-disabled {
+  padding: 40px 20px;
+  text-align: center;
+  background: rgba(30, 41, 59, 0.5);
+  border: 1px dashed var(--border-color);
+  border-radius: 12px;
+}
+
+.empty-state.service-disabled i.warning-icon {
+  width: 48px;
+  height: 48px;
+  color: var(--warning-color);
+  margin-bottom: 16px;
+}
+
+.empty-state.service-disabled h4 {
+  margin-bottom: 8px;
+  font-size: 1.1rem;
+}
+
+.empty-state.service-disabled p {
+  color: var(--text-secondary);
+  margin-bottom: 24px;
+  font-size: 0.95rem;
+  max-width: 300px;
+  margin-left: auto;
+  margin-right: auto;
+}
