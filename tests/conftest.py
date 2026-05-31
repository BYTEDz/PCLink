"""Pytest configuration and fixtures."""

import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Add src to path for testing
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from pclink.api_server.api import create_api_app  # noqa: E402


@pytest.fixture
def mock_controller():
    controller = MagicMock()
    controller.port = 38080
    return controller


@pytest.fixture
def mock_devices():
    return {}


@pytest.fixture
def api_client(mock_controller, mock_devices):
    from pclink.api_server.routers import dependencies

    app = create_api_app(mock_controller, mock_devices)

    # Bypass FastAPI dependencies
    app.dependency_overrides[dependencies.verify_api_key] = lambda: True
    app.dependency_overrides[dependencies.verify_mobile_api_enabled] = lambda: True
    app.dependency_overrides[dependencies.verify_web_session] = lambda: True

    # Mock device manager for the middleware
    with patch(
        "pclink.api_server.middleware.device_manager.get_device_by_api_key"
    ) as mock_get_device:
        mock_device = MagicMock()
        mock_device.is_approved = True
        mock_device.permissions = [
            "info",
            "power",
            "volume",
            "wol",
            "files_browse",
            "files_download",
            "files_upload",
            "files_delete",
            "processes",
            "mouse",
            "keyboard",
            "media",
            "terminal",
            "macros",
            "apps",
            "utils",
            "extensions",
            "desktop_streaming",
            "command",
            "clipboard",
            "screenshot",
        ]
        mock_get_device.return_value = mock_device

        # Use a fixed API key for all requests to satisfy the middleware
        client = TestClient(app)
        client.headers.update({"X-API-Key": "test-api-key"})

        yield client
