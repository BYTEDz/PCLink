"""Security utilities for PCLink"""

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .exceptions import SecurityError

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter for API endpoints"""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}

    def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed for client"""
        now = time.time()

        # Clean old requests
        if client_id in self.requests:
            self.requests[client_id] = [
                req_time
                for req_time in self.requests[client_id]
                if now - req_time < self.window_seconds
            ]
        else:
            self.requests[client_id] = []

        # Check rate limit
        if len(self.requests[client_id]) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for client {client_id}")
            return False

        # Add current request
        self.requests[client_id].append(now)
        return True


class TokenManager:
    """JWT-like token management for enhanced security"""

    def __init__(self, secret_key: str):
        self.secret_key = secret_key.encode()

    def generate_token(self, payload: Dict[str, Any], expires_in: int = 3600) -> str:
        """Generate a secure token"""
        try:
            # Add expiration
            payload["exp"] = int(time.time()) + expires_in
            payload["iat"] = int(time.time())

            # Create token data
            token_data = str(payload).encode()

            # Generate signature
            signature = hmac.new(
                self.secret_key, token_data, hashlib.sha256
            ).hexdigest()

            # Combine data and signature
            token = f"{token_data.hex()}.{signature}"

            logger.debug("Token generated successfully")
            return token

        except Exception as e:
            logger.error(f"Failed to generate token: {e}")
            raise SecurityError(f"Token generation failed: {e}")

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode token"""
        try:
            if not token or "." not in token:
                return None

            token_data_hex, signature = token.rsplit(".", 1)
            token_data = bytes.fromhex(token_data_hex)

            # Verify signature
            expected_signature = hmac.new(
                self.secret_key, token_data, hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                logger.warning("Token signature verification failed")
                return None

            # Decode payload
            payload = eval(token_data.decode())  # Note: In production, use json.loads

            # Check expiration
            if payload.get("exp", 0) < time.time():
                logger.warning("Token has expired")
                return None

            return payload

        except Exception as e:
            logger.warning(f"Token verification failed: {e}")
            return None


class SecurityAuditor:
    """Security event auditing"""

    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        self.events = []

    def log_event(self, event_type: str, client_ip: str, details: Dict[str, Any]):
        """Log security event"""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": event_type,
            "client_ip": client_ip,
            "details": details,
        }

        self.events.append(event)

        # Log to file if configured
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    f.write(f"{event}\n")
            except Exception as e:
                logger.error(f"Failed to write security log: {e}")

        # Log critical events
        if event_type in ["auth_failure", "rate_limit_exceeded", "suspicious_activity"]:
            logger.warning(f"Security event: {event_type} from {client_ip}")

    def get_recent_events(self, hours: int = 24) -> list:
        """Get recent security events"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        return [
            event
            for event in self.events
            if datetime.fromisoformat(event["timestamp"]) > cutoff
        ]


def generate_secure_key(length: int = 32) -> str:
    """Generate cryptographically secure random key"""
    return secrets.token_urlsafe(length)


def hash_password(password: str, salt: Optional[str] = None) -> tuple:
    """Hash password with salt"""
    if salt is None:
        salt = secrets.token_hex(16)

    # Use PBKDF2 for password hashing
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return key.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify password against hash"""
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return hmac.compare_digest(key.hex(), hashed)


# Global instances
rate_limiter = RateLimiter()
security_auditor = SecurityAuditor()
