#!/usr/bin/env python3
"""
PCLink Pairing Diagnostic Tool
This script helps diagnose pairing connection issues.
"""

import json
import logging
import socket
import sys
from pathlib import Path

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pclink.core import constants
from pclink.core.utils import get_cert_fingerprint, load_config_value
from pclink.core.validators import validate_api_key

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

def check_certificate():
    """Check certificate status and fingerprint."""
    print("\n=== Certificate Check ===")
    
    cert_file = constants.CERT_FILE
    key_file = constants.KEY_FILE
    
    print(f"Certificate file: {cert_file}")
    print(f"Key file: {key_file}")
    
    if not cert_file.exists():
        print("❌ Certificate file does not exist")
        return False
    
    if not key_file.exists():
        print("❌ Key file does not exist")
        return False
    
    print("✅ Certificate and key files exist")
    
    # Check certificate validity
    try:
        cert_data = cert_file.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        
        print(f"Certificate subject: {cert.subject}")
        print(f"Certificate issuer: {cert.issuer}")
        print(f"Valid from: {cert.not_valid_before}")
        print(f"Valid until: {cert.not_valid_after}")
        
        # Check if certificate is expired
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        # Handle both naive and timezone-aware datetime objects
        not_before = cert.not_valid_before_utc if hasattr(cert, 'not_valid_before_utc') else cert.not_valid_before
        not_after = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after
        
        # Make naive datetimes timezone-aware
        if not_before.tzinfo is None:
            not_before = not_before.replace(tzinfo=timezone.utc)
        if not_after.tzinfo is None:
            not_after = not_after.replace(tzinfo=timezone.utc)
        
        if now < not_before:
            print("⚠️  Certificate is not yet valid")
        elif now > not_after:
            print("❌ Certificate has expired")
        else:
            print("✅ Certificate is currently valid")
        
        # Get fingerprint
        fingerprint = get_cert_fingerprint(cert_file)
        if fingerprint:
            print(f"✅ Certificate fingerprint: {fingerprint}")
            return True
        else:
            print("❌ Failed to calculate certificate fingerprint")
            return False
            
    except Exception as e:
        print(f"❌ Error reading certificate: {e}")
        return False

def check_api_key():
    """Check API key configuration."""
    print("\n=== API Key Check ===")
    
    try:
        raw_key = load_config_value(constants.API_KEY_FILE, default=None)
        if not raw_key:
            print("❌ No API key found")
            return None
        
        print(f"Raw API key: {raw_key[:8]}...")
        
        validated_key = validate_api_key(raw_key)
        print(f"✅ API key is valid: {validated_key[:8]}...")
        return validated_key
        
    except Exception as e:
        print(f"❌ API key validation failed: {e}")
        return None

def check_server_connectivity(api_key, port=8000):
    """Check if server is running and accessible."""
    print(f"\n=== Server Connectivity Check (Port {port}) ===")
    
    if not api_key:
        print("❌ Cannot test server without valid API key")
        return False
    
    # Test HTTP first
    try:
        url = f"http://127.0.0.1:{port}/"
        response = requests.get(url, timeout=5)
        print(f"✅ HTTP server is responding: {response.status_code}")
        http_works = True
    except Exception as e:
        print(f"❌ HTTP server not accessible: {e}")
        http_works = False
    
    # Test HTTPS
    try:
        url = f"https://127.0.0.1:{port}/"
        response = requests.get(url, verify=False, timeout=5)
        print(f"✅ HTTPS server is responding: {response.status_code}")
        https_works = True
    except Exception as e:
        print(f"❌ HTTPS server not accessible: {e}")
        https_works = False
    
    return http_works or https_works

def test_qr_payload_endpoint(api_key, port=8000, use_https=True):
    """Test the QR payload endpoint specifically."""
    print(f"\n=== QR Payload Endpoint Test ===")
    
    if not api_key:
        print("❌ Cannot test without valid API key")
        return False
    
    protocol = "https" if use_https else "http"
    url = f"{protocol}://127.0.0.1:{port}/qr-payload"
    headers = {"x-api-key": api_key}
    
    try:
        print(f"Testing: {url}")
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ QR payload endpoint is working")
            print(f"Protocol: {data.get('protocol')}")
            print(f"IP: {data.get('ip')}")
            print(f"Port: {data.get('port')}")
            print(f"API Key: {data.get('apiKey', '')[:8]}...")
            print(f"Cert Fingerprint: {data.get('certFingerprint', 'None')}")
            return True
        else:
            print(f"❌ QR payload endpoint failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing QR payload endpoint: {e}")
        return False

def test_pairing_endpoint(api_key, port=8000, use_https=True):
    """Test the pairing request endpoint."""
    print(f"\n=== Pairing Endpoint Test ===")
    
    if not api_key:
        print("❌ Cannot test without valid API key")
        return False
    
    protocol = "https" if use_https else "http"
    url = f"{protocol}://127.0.0.1:{port}/pairing/request"
    
    payload = {"device_name": "Diagnostic Test Device"}
    
    try:
        print(f"Testing: {url}")
        print("⚠️  This will trigger a pairing dialog if the server is running")
        print("You have 5 seconds to cancel if you don't want this...")
        
        import time
        time.sleep(5)
        
        response = requests.post(url, json=payload, verify=False, timeout=10)
        
        if response.status_code == 408:
            print("✅ Pairing endpoint is working (timed out waiting for user response)")
            return True
        elif response.status_code == 403:
            print("✅ Pairing endpoint is working (user denied request)")
            return True
        elif response.status_code == 200:
            print("✅ Pairing endpoint is working (user accepted request)")
            data = response.json()
            print(f"Returned API key: {data.get('api_key', '')[:8]}...")
            print(f"Cert fingerprint: {data.get('cert_fingerprint', 'None')}")
            return True
        else:
            print(f"❌ Pairing endpoint failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing pairing endpoint: {e}")
        return False

def main():
    """Run all diagnostic checks."""
    print("PCLink Pairing Diagnostic Tool")
    print("=" * 40)
    
    # Check certificate
    cert_ok = check_certificate()
    
    # Check API key
    api_key = check_api_key()
    
    # Get port
    try:
        port = int(load_config_value(constants.PORT_FILE, str(constants.DEFAULT_PORT)))
        print(f"\nConfigured port: {port}")
    except Exception as e:
        print(f"❌ Error reading port configuration: {e}")
        port = constants.DEFAULT_PORT
    
    # Check server connectivity
    server_ok = check_server_connectivity(api_key, port)
    
    if server_ok and api_key:
        # Test endpoints
        print("\nTesting with HTTPS...")
        test_qr_payload_endpoint(api_key, port, use_https=True)
        
        print("\nTesting with HTTP...")
        test_qr_payload_endpoint(api_key, port, use_https=False)
        
        # Optionally test pairing (commented out by default)
        # test_pairing_endpoint(api_key, port, use_https=True)
    
    print("\n=== Summary ===")
    print(f"Certificate: {'✅' if cert_ok else '❌'}")
    print(f"API Key: {'✅' if api_key else '❌'}")
    print(f"Server: {'✅' if server_ok else '❌'}")
    
    if not (cert_ok and api_key and server_ok):
        print("\n⚠️  Issues found. Please check the PCLink server configuration and ensure it's running.")
        return 1
    else:
        print("\n✅ All basic checks passed!")
        return 0

if __name__ == "__main__":
    sys.exit(main())