// PCLink Authentication JavaScript
class PCLinkAuth {
    constructor() {
        this.init();
    }

    async init() {
        await this.checkAuthStatus();
    }

    async checkAuthStatus() {
        try {
            // First check if we're already authenticated
            try {
                const sessionCheck = await fetch('/auth/check', {
                    credentials: 'include'
                });
                
                if (sessionCheck.ok) {
                    const sessionData = await sessionCheck.json();
                    if (sessionData.authenticated) {
                        // Already logged in, redirect to main UI
                        window.location.href = '/ui/';
                        return;
                    }
                }
            } catch (sessionError) {
                console.warn('Session check failed, continuing with auth flow:', sessionError);
            }
            
            // Check setup status
            const response = await fetch('/auth/status');
            
            if (response.ok) {
                const data = await response.json();
                
                if (data.setup_completed) {
                    this.showLoginForm();
                } else {
                    this.showSetupForm();
                }
            } else {
                // If auth status fails, default to login form
                console.warn('Auth status check failed, defaulting to login form');
                this.showLoginForm();
            }
        } catch (error) {
            console.error('Auth status check failed:', error);
            // Show login form as fallback
            this.showLoginForm();
            this.showError('Failed to connect to server. Showing login form.');
        }
    }

    showSetupForm() {
        console.log('Showing setup form');
        const setupForm = document.getElementById('setupForm');
        const loginForm = document.getElementById('loginForm');
        
        if (setupForm) setupForm.style.display = 'block';
        if (loginForm) loginForm.style.display = 'none';
        this.hideMessages();
    }

    showLoginForm() {
        console.log('Showing login form');
        const setupForm = document.getElementById('setupForm');
        const loginForm = document.getElementById('loginForm');
        
        if (setupForm) setupForm.style.display = 'none';
        if (loginForm) loginForm.style.display = 'block';
        this.hideMessages();
    }

    showError(message) {
        const errorDiv = document.getElementById('errorMessage');
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        document.getElementById('successMessage').style.display = 'none';
    }

    showSuccess(message) {
        const successDiv = document.getElementById('successMessage');
        successDiv.textContent = message;
        successDiv.style.display = 'block';
        document.getElementById('errorMessage').style.display = 'none';
    }

    hideMessages() {
        document.getElementById('errorMessage').style.display = 'none';
        document.getElementById('successMessage').style.display = 'none';
    }

    setLoading(buttonId, loading) {
        const button = document.getElementById(buttonId);
        if (loading) {
            button.disabled = true;
            button.innerHTML = '<span class="loading"></span>Processing...';
        } else {
            button.disabled = false;
            button.innerHTML = buttonId === 'setupButton' ? 'Set Up Password' : 'Sign In';
        }
    }

    async handleSetup(password) {
        try {
            const response = await fetch('/auth/setup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ password })
            });

            const data = await response.json();

            if (response.ok) {
                this.showSuccess('Password setup successful! You can now log in.');
                setTimeout(() => {
                    this.showLoginForm();
                }, 2000);
            } else {
                this.showError(data.detail || 'Setup failed');
            }
        } catch (error) {
            console.error('Setup error:', error);
            this.showError('Failed to setup password');
        }
    }

    async handleLogin(password) {
        try {
            const response = await fetch('/auth/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',  // Important: include cookies
                body: JSON.stringify({ password })
            });

            const data = await response.json();

            if (response.ok) {
                this.showSuccess('Login successful! Redirecting...');
                
                // Store session token if provided (backup)
                if (data.session_token) {
                    sessionStorage.setItem('pclink_session', data.session_token);
                }
                
                // Force a page reload to ensure cookies are properly set
                setTimeout(() => {
                    window.location.reload();
                }, 500);
            } else {
                this.showError(data.detail || 'Login failed');
            }
        } catch (error) {
            console.error('Login error:', error);
            this.showError('Failed to login');
        }
    }
}

// Global functions for form handling
async function handleSetup(event) {
    event.preventDefault();
    
    const password = document.getElementById('setupPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    
    if (password.length < 8) {
        window.pclinkAuth.showError('Password must be at least 8 characters long');
        return;
    }
    
    if (password !== confirmPassword) {
        window.pclinkAuth.showError('Passwords do not match');
        return;
    }
    
    window.pclinkAuth.setLoading('setupButton', true);
    await window.pclinkAuth.handleSetup(password);
    window.pclinkAuth.setLoading('setupButton', false);
}

async function handleLogin(event) {
    event.preventDefault();
    
    const password = document.getElementById('loginPassword').value;
    
    if (!password) {
        window.pclinkAuth.showError('Please enter your password');
        return;
    }
    
    window.pclinkAuth.setLoading('loginButton', true);
    await window.pclinkAuth.handleLogin(password);
    window.pclinkAuth.setLoading('loginButton', false);
}

// Initialize authentication when page loads
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing PCLink Auth');
    
    // Show login form by default in case JavaScript fails
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.style.display = 'block';
    }
    
    // Initialize auth system
    try {
        window.pclinkAuth = new PCLinkAuth();
    } catch (error) {
        console.error('Failed to initialize auth system:', error);
        // Ensure login form is visible as fallback
        if (loginForm) {
            loginForm.style.display = 'block';
        }
    }
});