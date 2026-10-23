# tests/test_ai_service.py
# Focused, offline tests for the local AI subsystem's validation and
# Hugging Face metadata handling. No network or llama-server process is used.

import asyncio
import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from pclink.services.ai_service import DEFAULT_CONFIG, ai_service


# ==========================================
# Input validation / path safety
# ==========================================


@pytest.mark.parametrize("tag", ["b4567", "b4567-cuda12", "0.1.2", "release_1"])
def test_engine_tag_accepts_safe_values(tag):
    assert ai_service._validate_engine_tag(tag) == tag


@pytest.mark.parametrize(
    "tag",
    ["", "   ", "../escape", "a/b", "a\\b", "-leading", "x" * 65, "bad tag"],
)
def test_engine_tag_rejects_unsafe_values(tag):
    with pytest.raises(HTTPException) as exc:
        ai_service._validate_engine_tag(tag)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "filename",
    ["model-Q4_K_M.gguf", "tiny.gguf", "UPPER.GGUF", "model.v2.gguf"],
)
def test_model_filename_accepts_plain_gguf_names(filename):
    assert ai_service._validate_model_filename(filename) == filename


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "   ",
        "..",
        ".",
        "../model.gguf",
        "folder/model.gguf",
        "folder\\model.gguf",
        "/etc/passwd",
        "model.bin",
        "model.gguf.tmp",
    ],
)
def test_model_filename_rejects_traversal_and_non_gguf(filename):
    with pytest.raises(HTTPException) as exc:
        ai_service._validate_model_filename(filename)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "repo_id",
    ["tiny-model", "org/tiny-model", "org/model.v2", "a_b/c-d"],
)
def test_hf_repo_accepts_valid_ids(repo_id):
    assert ai_service._validate_hf_repo(repo_id) == repo_id


@pytest.mark.parametrize(
    "repo_id",
    ["", "   ", "org/../model", "../model", "a/b/c", "org/mo del", "/model", "org/"],
)
def test_hf_repo_rejects_invalid_ids(repo_id):
    with pytest.raises(HTTPException) as exc:
        ai_service._validate_hf_repo(repo_id)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "https://huggingface.co/org/model/resolve/main/model.gguf",
        "https://cdn-lfs.huggingface.co/org/model/file.gguf",
        "https://hf.co/org/model",
        "https://github.com/ggml-org/llama.cpp/releases/download/b1/asset.zip",
        "https://objects.githubusercontent.com/asset.zip",
    ],
)
def test_download_url_accepts_trusted_https_hosts(url):
    assert ai_service._validate_download_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "file:///etc/passwd",
        "http://huggingface.co/org/model",
        "https://evil.example/model.gguf",
        "https://huggingface.co.evil.example/model.gguf",
        "https://127.0.0.1/model.gguf",
        "https://huggingface.co@evil.example/model.gguf",
    ],
)
def test_download_url_rejects_ssrf_and_non_https(url):
    with pytest.raises(HTTPException) as exc:
        ai_service._validate_download_url(url)
    assert exc.value.status_code == 400


# ==========================================
# Config validation
# ==========================================


def test_update_config_rejects_out_of_range_values():
    with patch.object(
        ai_service, "_read_config", return_value=dict(DEFAULT_CONFIG)
    ), patch.object(ai_service, "_write_config") as write_mock:
        with pytest.raises(HTTPException) as exc:
            ai_service.update_config({"context_size": 16})
        assert exc.value.status_code == 400
        write_mock.assert_not_called()


def test_update_config_persists_and_flags_port_restart():
    with patch.object(
        ai_service, "_read_config", side_effect=lambda: dict(DEFAULT_CONFIG)
    ), patch.object(ai_service, "_write_config") as write_mock, patch.object(
        ai_service, "is_running", return_value=True
    ):
        result = ai_service.update_config({"port": 39000, "gpu_layers": 12})

    assert result["success"] is True
    assert result["config"]["port"] == 39000
    assert result["config"]["gpu_layers"] == 12
    assert result["restart_required"] is True
    write_mock.assert_called_once()


# ==========================================
# GGUF magic verification
# ==========================================


def test_validate_gguf_magic_accepts_real_header(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF\x03\x00\x00\x00")
    ai_service._validate_gguf_magic(model)


def test_validate_gguf_magic_rejects_other_files(tmp_path):
    fake = tmp_path / "not-a-model.gguf"
    fake.write_bytes(b"<!DOCTYPE html>")
    with pytest.raises(ValueError):
        ai_service._validate_gguf_magic(fake)


# ==========================================
# Hugging Face tree parsing
# ==========================================


class _FakeResponse:
    def __init__(self, payload):
        self.status = 200
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_hf_files_filters_shards_and_projectors(monkeypatch):
    tree = [
        {"path": "model-Q8_0.gguf", "size": 8 * 1024**3},
        {"path": "model-Q4_K_M.gguf", "size": 4 * 1024**3},
        {"path": "model-00001-of-00002.gguf", "size": 5 * 1024**3},
        {"path": "mmproj-model-f16.gguf", "size": 100 * 1024**2},
        {"path": "README.md", "size": 100},
    ]

    def fake_urlopen(request, timeout=0):
        return _FakeResponse(tree)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "pclink.services.ai_service.psutil.virtual_memory",
        lambda: SimpleNamespace(available=6 * 1024**3),
    )
    ai_service._hf_cache.clear()

    result = asyncio.run(
        ai_service.get_huggingface_model_files("pclink-test/tiny-model")
    )

    filenames = [f["filename"] for f in result["files"]]
    assert filenames == ["model-Q4_K_M.gguf", "model-Q8_0.gguf"]
    assert result["files"][0]["is_recommended"] is True
    assert result["files"][1]["fits_in_ram"] is False
    assert result["has_projector"] is True
    assert result["has_split_files"] is True
    assert result["branch"] == "main"
    assert result["files"][0]["download_url"] == (
        "https://huggingface.co/pclink-test/tiny-model/resolve/main/model-Q4_K_M.gguf"
    )


# ==========================================
# HTTP wiring (client app / Web UI)
# ==========================================


def test_ai_status_route_is_registered(api_client):
    payload = {
        "engine_state": "stopped",
        "engine_installed": True,
        "active_model": None,
        "port": 38191,
        "config": {},
    }
    with patch.object(ai_service, "get_status", new=AsyncMock(return_value=payload)):
        response = api_client.get("/ai/status")
    assert response.status_code == 200
    assert response.json()["engine_state"] == "stopped"


def test_ai_openai_model_discovery_route(api_client):
    with patch.object(
        ai_service, "get_active_model_name", return_value="tiny-Q4_K_M.gguf"
    ):
        response = api_client.get("/ai/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "tiny-Q4_K_M.gguf"
    assert body["data"][0]["owned_by"] == "pclink"


def test_ai_openai_model_discovery_is_empty_without_weights(api_client):
    with patch.object(ai_service, "get_active_model_name", return_value=None):
        response = api_client.get("/ai/v1/models")
    assert response.status_code == 200
    assert response.json() == {"object": "list", "data": []}


def test_ai_chat_route_rejects_empty_messages(api_client):
    response = api_client.post("/ai/v1/chat/completions", json={"messages": []})
    assert response.status_code == 400


def _llama_error(status_code: int, message: str) -> urllib.error.HTTPError:
    payload = json.dumps(
        {
            "error": {
                "code": status_code,
                "message": message,
                "type": "server_error",
            }
        }
    ).encode("utf-8")
    return urllib.error.HTTPError(
        "http://127.0.0.1:38191/v1/chat/completions",
        status_code,
        "error",
        {},
        io.BytesIO(payload),
    )


def test_llama_error_detail_extracts_message():
    raw = json.dumps(
        {
            "error": {
                "code": 500,
                "message": "image input is not supported",
                "type": "server_error",
            }
        }
    )
    assert ai_service._llama_error_detail(raw) == "image input is not supported"


def test_strip_vision_parts_preserves_upload_metadata():
    body = {
        "model": "tiny",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "upload this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                    },
                ],
            }
        ],
    }

    stripped, removed = ai_service._strip_vision_parts(body)

    assert removed == 1
    assert stripped is not body
    assert body["messages"][0]["content"][1]["type"] == "image_url"
    content = stripped["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "upload this"}
    assert all(part["type"] != "image_url" for part in content)
    assert "omitted" in content[-1]["text"]


def test_strip_vision_parts_noop_for_text_only_request():
    body = {"messages": [{"role": "user", "content": "hello"}]}
    stripped, removed = ai_service._strip_vision_parts(body)
    assert stripped is body
    assert removed == 0


def test_open_llama_chat_retries_without_images_for_text_model():
    body = {
        "model": "tiny",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "upload this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                    },
                ],
            }
        ],
    }
    success = SimpleNamespace(readline=lambda: b"", close=lambda: None)
    vision_error = _llama_error(
        500,
        "image input is not supported - hint: you may need to provide the mmproj",
    )

    with patch.object(ai_service, "get_running_port", return_value=38191), patch(
        "pclink.services.ai_service.urllib.request.urlopen",
        side_effect=[vision_error, success],
    ) as urlopen_mock:
        response, used_body = ai_service._open_llama_chat(
            body, timeout=5, accept="text/event-stream"
        )

    assert response is success
    assert urlopen_mock.call_count == 2
    retry_payload = json.loads(
        urlopen_mock.call_args_list[1].args[0].data.decode("utf-8")
    )
    retry_content = retry_payload["messages"][0]["content"]
    assert retry_content[0] == {"type": "text", "text": "upload this"}
    assert all(part["type"] != "image_url" for part in retry_content)
    assert used_body["messages"][0]["content"] == retry_content


def test_open_llama_chat_does_not_retry_unrelated_errors():
    body = {"messages": [{"role": "user", "content": "hello"}]}
    with patch.object(ai_service, "get_running_port", return_value=38191), patch(
        "pclink.services.ai_service.urllib.request.urlopen",
        side_effect=[_llama_error(500, "model crashed")],
    ) as urlopen_mock:
        with pytest.raises(HTTPException) as exc:
            ai_service._open_llama_chat(body, timeout=5, accept="text/event-stream")

    assert exc.value.status_code == 500
    assert exc.value.detail == "model crashed"
    assert urlopen_mock.call_count == 1


def test_ai_stream_route_preserves_upstream_error_detail(api_client):
    error = HTTPException(
        status_code=422,
        detail="Local model rejected the image input.",
    )
    with patch.object(ai_service, "ensure_running", new=AsyncMock()), patch.object(
        ai_service,
        "proxy_stream_chat",
        new=AsyncMock(side_effect=error),
    ):
        response = api_client.post(
            "/ai/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Local model rejected the image input."


def test_ai_stream_route_returns_upstream_stream(api_client):
    async def fake_stream(_body):
        async def chunks():
            yield b'data: {"choices":[]}\n\n'

        return chunks()

    with patch.object(ai_service, "ensure_running", new=AsyncMock()), patch.object(
        ai_service, "proxy_stream_chat", new=fake_stream
    ):
        response = api_client.post(
            "/ai/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert response.content == b'data: {"choices":[]}\n\n'


def test_ai_config_route_applies_and_validates(api_client):
    base = dict(DEFAULT_CONFIG)
    with patch.object(
        ai_service, "_read_config", side_effect=lambda: dict(base)
    ), patch.object(ai_service, "_write_config"), patch.object(
        ai_service, "is_running", return_value=False
    ):
        response = api_client.post(
            "/ai/config", json={"context_size": 4096, "gpu_layers": 0}
        )
        assert response.status_code == 200
        assert response.json()["config"]["context_size"] == 4096

        invalid = api_client.post("/ai/config", json={"port": 70000})
        assert invalid.status_code == 400
