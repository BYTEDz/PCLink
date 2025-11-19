# src/pclink/core/web_auth.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import hashlib
import hmac
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Optional

from . import constants

log = logging.getLogger(__name__)

# Authentication configuration
AUTH_CONFIG_FILE = constants.APP_DATA_PATH / "web_auth.json"
SESSION_TIMEOUT = 24 * 60 * 60  # 24 hours in seconds


class WebAuthManager:
    """Manages web UI authentication and sessions"""
    
    def __init__(self):
        self.auth_config = self._load_auth_config()
        self.active_sessions = {}
        self.failed_attempts = {}  # IP -> {count, last_attempt}
    
    def _load_auth_config(self) -> dict:
        """Load authentication configuration"""
        if AUTH_CONFIG_FILE.exists():
            try:
                with open(AUTH_CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log.error(f"Failed to load auth config: {e}")
        
        return {
            "setup_completed": False,
            "password_hash": None,
            "salt": None,
            "created_at": None
        }
    
    def _save_auth_config(self):
        """Save authentication configuration"""
        try:
            constants.APP_DATA_PATH.mkdir(parents=True, exist_ok=True)
            with open(AUTH_CONFIG_FILE, 'w') as f:
                json.dump(self.auth_config, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save auth config: {e}")
    
    def is_setup_completed(self) -> bool:
        """Check if initial setup is completed"""
        return self.auth_config.get("setup_completed", False)
    
    def setup_password(self, password: str) -> bool:
        """Set up initial password for web UI"""
        if self.is_setup_completed():
            log.warning("Setup already completed")
            return False
        
        if len(password) < 8:
            log.warning("Password too short")
            return False
        
        # Generate salt and hash password
        salt = secrets.token_hex(32)
        password_hash = self._hash_password(password, salt)
        
        self.auth_config.update({
            "setup_completed": True,
            "password_hash": password_hash,
            "salt": salt,
            "created_at": int(time.time())
        })
        
        self._save_auth_config()
        log.info("Web UI password setup completed")
        return True
    
    def verify_password(self, password: str) -> bool:
        """Verify password against stored hash"""
        if not self.is_setup_completed():
            return False
        
        stored_hash = self.auth_config.get("password_hash")
        salt = self.auth_config.get("salt")
        
        if not stored_hash or not salt:
            return False
        
        password_hash = self._hash_password(password, salt)
        return hmac.compare_digest(stored_hash, password_hash)
    
    def check_rate_limit(self, ip_address: str) -> bool:
        """Check if IP is rate limited. Returns True if allowed, False if blocked."""
        if not ip_address: return True
        
        current_time = time.time()
        record = self.failed_attempts.get(ip_address)
        
        if not record:
            return True
            
        # Reset count if last attempt was more than 15 minutes ago
        if current_time - record["last_attempt"] > 900:
            del self.failed_attempts[ip_address]
            return True
            
        # Block if more than 5 failed attempts
        if record["count"] >= 5:
            log.warning(f"Rate limit exceeded for IP {ip_address}")
            return False
            
        return True

    def record_failed_attempt(self, ip_address: str):
        """Record a failed login attempt"""
        if not ip_address: return
        
        current_time = time.time()
        if ip_address not in self.failed_attempts:
            self.failed_attempts[ip_address] = {"count": 1, "last_attempt": current_time}
        else:
            self.failed_attempts[ip_address]["count"] += 1
            self.failed_attempts[ip_address]["last_attempt"] = current_time

    def create_session(self, password: str, ip_address: str = None) -> Optional[str]:
        """Create a new authenticated session"""
        if not self.check_rate_limit(ip_address):
            return None

        if not self.verify_password(password):
            self.record_failed_attempt(ip_address)
            return None
        
        # Clear failed attempts on success
        if ip_address and ip_address in self.failed_attempts:
            del self.failed_attempts[ip_address]
        
        # Generate session token
        session_token = secrets.token_urlsafe(32)
        session_data = {
            "created_at": int(time.time()),
            "last_activity": int(time.time()),
            "ip_address": ip_address
        }
        
        self.active_sessions[session_token] = session_data
        log.info(f"New web UI session created for {ip_address}")
        return session_token
    
    def validate_session(self, session_token: str, ip_address: str = None) -> bool:
        """Validate an existing session"""
        if not session_token or session_token not in self.active_sessions:
            return False
        
        session_data = self.active_sessions[session_token]
        current_time = int(time.time())
        
        # Check if session has expired
        if current_time - session_data["last_activity"] > SESSION_TIMEOUT:
            self.revoke_session(session_token)
            return False
        
        # Update last activity
        session_data["last_activity"] = current_time
        if ip_address:
            session_data["ip_address"] = ip_address
        
        return True
    
    def revoke_session(self, session_token: str):
        """Revoke a session"""
        if session_token in self.active_sessions:
            del self.active_sessions[session_token]
            log.info("Web UI session revoked")
    
    def revoke_all_sessions(self):
        """Revoke all active sessions"""
        self.active_sessions.clear()
        log.info("All web UI sessions revoked")
    
    def change_password(self, old_password: str, new_password: str) -> bool:
        """Change the web UI password"""
        if not self.verify_password(old_password):
            return False
        
        if len(new_password) < 8:
            return False
        
        # Generate new salt and hash
        salt = secrets.token_hex(32)
        password_hash = self._hash_password(new_password, salt)
        
        self.auth_config.update({
            "password_hash": password_hash,
            "salt": salt
        })
        
        self._save_auth_config()
        
        # Revoke all existing sessions
        self.revoke_all_sessions()
        
        log.info("Web UI password changed")
        return True
    
    def reset_auth(self):
        """Reset authentication (for development/testing)"""
        self.auth_config = {
            "setup_completed": False,
            "password_hash": None,
            "salt": None,
            "created_at": None
        }
        self._save_auth_config()
        self.revoke_all_sessions()
        log.info("Web UI authentication reset")
    
    def _hash_password(self, password: str, salt: str) -> str:
        """Hash password with salt using PBKDF2"""
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000  # 100,000 iterations
        ).hex()
    
    def get_session_info(self) -> dict:
        """Get information about active sessions"""
        current_time = int(time.time())
        active_count = 0
        
        # Clean up expired sessions
        expired_sessions = []
        for token, data in self.active_sessions.items():
            if current_time - data["last_activity"] > SESSION_TIMEOUT:
                expired_sessions.append(token)
            else:
                active_count += 1
        
        for token in expired_sessions:
            self.revoke_session(token)
        
        return {
            "setup_completed": self.is_setup_completed(),
            "active_sessions": active_count,
            "session_timeout_hours": SESSION_TIMEOUT // 3600
        }


# Global instance
web_auth_manager = WebAuthManager()