# PCLink API Documentation

This directory contains auto-generated API documentation for PCLink.

## Generating Documentation

To generate the API documentation, run:

```bash
# Install documentation dependencies
pip install sphinx sphinx-rtd-theme

# Generate documentation
sphinx-build -b html docs/api docs/api/_build
```

## API Overview

PCLink provides a REST API for remote control and file management.

### Authentication

All API requests require an API key, which should be passed in the `x-api-key` header.

### Endpoints

- `/api/v1/devices` - List connected devices
- `/api/v1/files` - File browser API
- `/api/v1/terminal` - Terminal API
- `/api/v1/process` - Process management API