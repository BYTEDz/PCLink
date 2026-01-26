# Security Policy

## Supported Versions

**Only the latest version of PCLink receives security updates and bug fixes.**

As a solo developer project, I focus all maintenance efforts on the current release. When a new version is published, previous versions are no longer supported. This is standard practice for many open-source projects and ensures the best use of development resources.

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| Older   | :x:                |

**If you're running an older version, please update immediately to receive security patches and improvements.**

## Security Features

PCLink implements multiple security layers to protect your system:

- **HTTPS Communication**: All API traffic uses TLS encryption with self-signed certificates
- **API Key Authentication**: UUID-based authentication for all client connections
- **Device Pairing**: QR code-based secure device pairing process
- **Local Network Focus**: Designed for trusted local network environments
- **Input Validation**: Comprehensive validation and sanitization of all inputs
- **Process Isolation**: Sandboxed execution of system commands

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in PCLink, please report it responsibly:

**Contact**: support@bytedz.com

### What to Include

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact assessment
- Suggested fix (if available)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Assessment**: Within 1 week
- **Patch Development**: Within 2-4 weeks (depending on severity)
- **Public Disclosure**: After patch is released and users have time to update

### Security Best Practices

When using PCLink:

1. **Network Security**: Use PCLink only on trusted networks
2. **API Key Protection**: Keep your API key secure and regenerate if compromised
3. **Firewall Configuration**: Ensure proper firewall rules are in place
4. **Regular Updates**: Keep PCLink updated to the latest version
5. **Access Control**: Limit physical and network access to your PC

## Known Limitations

- Self-signed certificates will trigger browser warnings (expected behavior)
- Local network exposure requires proper network security
- Terminal access provides full shell capabilities (use with caution)

## Security Updates

Security patches are released as soon as possible after verification. Check the [CHANGELOG](CHANGELOG.md) for security-related updates.

**Stay Protected**: PCLink includes an auto-update feature that notifies you when new versions are available. We strongly encourage enabling automatic updates or checking regularly for the latest release to ensure you have the most recent security patches and improvements.
