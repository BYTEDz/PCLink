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
                console.warn('Auth status check failed, defaulting to login form');
                this.showLoginForm();
            }
        } catch (error) {
            console.error('Auth status check failed:', error);
            this.showLoginForm();
            this.showError('Failed to connect to server. Showing login form.');
        }
    }

    showSetupForm() {
        const setupForm = document.getElementById('setupForm');
        const loginForm = document.getElementById('loginForm');
        
        if (setupForm) setupForm.style.display = 'block';
        if (loginForm) loginForm.style.display = 'none';
        this.hideMessages();
    }

    showLoginForm() {
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
        if (!button) return;

        const originalText = buttonId === 'setupButton' ? 'Set Up Password' : 'Sign In';

        if (loading) {
            button.disabled = true;
            button.innerHTML = `<span class="loading"></span><span class="button-text">Processing...</span>`;
        } else {
            button.disabled = false;
            button.innerHTML = `<span class="button-text">${originalText}</span>`;
            button.style.background = ''; // Reset background color
        }
    }

    async handleSetup(password) {
        try {
            const response = await fetch('/auth/setup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password })
            });

            const data = await response.json();
            const setupButton = document.getElementById('setupButton');
            const authCard = document.querySelector('.auth-card');

            if (response.ok) {
                this.hideMessages();
                
                // Show success state on button
                setupButton.innerHTML = '<span>✔</span> <span class="button-text">Success!</span>';
                setupButton.style.background = 'var(--success-color)';

                // Animate out the setup card
                setTimeout(() => {
                    if (authCard) authCard.classList.add('transition-out');
                }, 800); // Wait to show success message

                // Switch to login form after animation
                setTimeout(() => {
                    this.showLoginForm();
                    document.getElementById('loginPassword').focus();
                    if (authCard) {
                        // Reset card for login view
                        authCard.classList.remove('transition-out');
                    }
                }, 1200); // 800ms + 400ms animation time

            } else {
                this.showError(data.detail || 'Setup failed');
                this.setLoading('setupButton', false); // Reset button on failure
            }
        } catch (error) {
            console.error('Setup error:', error);
            this.showError('Failed to setup password');
            this.setLoading('setupButton', false);
        }
    }

    async handleLogin(password) {
        try {
            const response = await fetch('/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ password })
            });

            const data = await response.json();

            if (response.ok) {
                this.showSuccess('Login successful! Redirecting...');
                setTimeout(() => {
                    window.location.reload();
                }, 500);
            } else {
                this.showError(data.detail || 'Login failed');
                this.setLoading('loginButton', false);
            }
        } catch (error) {
            console.error('Login error:', error);
            this.showError('Failed to login');
            this.setLoading('loginButton', false);
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
    // Note: setLoading(false) is now handled inside the class method on failure/success
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
}

// Initialize authentication when page loads
document.addEventListener('DOMContentLoaded', () => {
    try {
        window.pclinkAuth = new PCLinkAuth();
    } catch (error) {
        console.error('Failed to initialize auth system:', error);
        document.getElementById('loginForm').style.display = 'block';
        document.getElementById('setupForm').style.display = 'none';
    }
});