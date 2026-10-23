# src/pclink/services/ai_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 AZHAR ZOUHIR / BYTEDz

import asyncio
import atexit
import ctypes
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import psutil
from fastapi import HTTPException, UploadFile

from ..core.constants import APP_DATA_PATH

logger = logging.getLogger(__name__)

OS_TYPE = platform.system().lower()
ARCH_RAW = platform.machine().lower()

if ARCH_RAW in ["amd64", "x86_64"]:
    ARCH_NAME = "x86_64"
elif ARCH_RAW in ["aarch64", "arm64"]:
    ARCH_NAME = "arm64"
else:
    ARCH_NAME = ARCH_RAW

if OS_TYPE == "windows":
    SERVER_BIN_NAME = "llama-server.exe"
else:
    SERVER_BIN_NAME = "llama-server"

AI_DIR = APP_DATA_PATH / "llama"
VERSIONS_DIR = AI_DIR / "versions"
MODELS_DIR = AI_DIR / "models"
ACTIVE_CONFIG_FILE = AI_DIR / "active.json"
PID_FILE = AI_DIR / "llama.pid"

# Dedicated loopback port for PCLink's llama-server.
# Do NOT reuse 11434: that is Ollama's default port, and binding/killing on it
# breaks users who already run Ollama or another local AI runtime.
DEFAULT_LLAMA_PORT = 38191

DEFAULT_CONFIG = {
    "active_version": None,
    "active_model": None,
    "gpu_layers": 99,
    "context_size": 8192,
    "idle_timeout_seconds": 600,
    "port": DEFAULT_LLAMA_PORT,
    "threads": 0,
    "parallel": 1,
    "startup_timeout_seconds": 120,
    "request_timeout_seconds": 300,
}

_SAFE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HF_REPO_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)
_SPLIT_GGUF_RE = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.IGNORECASE)
_QUANT_RE = re.compile(
    r"(IQ\d+_[A-Z0-9_]+|Q\d+_[A-Z0-9_]+|Q\d+_\d+|Q\d+|BF16|F16|F32)\.gguf$",
    re.IGNORECASE,
)

# Initial download URLs are restricted to trusted model/runtime hosts so a
# client cannot turn the downloader into an SSRF primitive (file://, metadata
# endpoints, internal services, ...). Redirects issued by these hosts (HF CDN,
# GitHub objects) are followed by urllib as usual.
_ALLOWED_DOWNLOAD_SUFFIXES = (
    "huggingface.co",
    "hf.co",
    "github.com",
    "githubusercontent.com",
)

# Curated, verified working GGUF direct resolve links (<1B and 1-3B lightweight models)
CURATED_MODELS = [
    {
        "id": "qwen-2.5-0.5b",
        "name": "Qwen 2.5 0.5B Instruct",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_bytes": 397000000,
        "size_formatted": "397 MB",
        "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "description": "Ultra-fast action controller & tool caller. Very low RAM footprint (~600MB).",
        "badge": "Recommended / Fast Action",
    },
    {
        "id": "smollm2-360m",
        "name": "SmolLM2 360M Instruct",
        "filename": "smollm2-360m-instruct-q4_k_m.gguf",
        "size_bytes": 229000000,
        "size_formatted": "229 MB",
        "url": "https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct-GGUF/resolve/main/smollm2-360m-instruct-q4_k_m.gguf",
        "description": "Ultra-compact sub-1B model by HuggingFace. Instant CPU execution.",
        "badge": "Ultra Lightweight",
    },
    {
        "id": "llama-3.2-1b",
        "name": "Llama 3.2 1B Instruct",
        "filename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "size_bytes": 792000000,
        "size_formatted": "792 MB",
        "url": "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "description": "Meta's official lightweight instruct model. Balanced reasoning and dialogue.",
        "badge": "Balanced 1B",
    },
    {
        "id": "llama-3.2-3b",
        "name": "Llama 3.2 3B Instruct",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size_bytes": 2020000000,
        "size_formatted": "1.9 GB",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "description": "Strong general intelligence, structured outputs, and complex scripting.",
        "badge": "Advanced 3B",
    },
]


def _linux_set_pdeathsig():
    """Instructs the Linux kernel to immediately send SIGTERM to llama-server if PCLink terminates."""
    try:
        # PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL(None)
        libc.prctl(1, signal.SIGTERM)
    except Exception:
        pass


def _assign_windows_job_kill_on_close(proc):
    """Binds llama-server.exe to a Windows Job Object configured to terminate child processes on exit."""
    if OS_TYPE != "windows" or not proc:
        return
    try:
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryLimit", ctypes.c_size_t),
                ("PeakJobMemoryLimit", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        job = kernel32.CreateJobObjectW(None, None)
        if job:
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            kernel32.SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            kernel32.AssignProcessToJobObject(job, proc._handle)
    except Exception as e:
        logger.warning(f"Could not bind Windows Job Object: {e}")


class AiService:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._active_port: Optional[int] = None
        self._last_request_time: float = 0.0
        self._idle_monitor_task: Optional[asyncio.Task] = None
        self._releases_cache: Optional[List[dict]] = None
        self._releases_cache_time: float = 0.0
        self._engine_state: str = "stopped"
        self._loading_model: Optional[str] = None
        self._loading_message: Optional[str] = None
        self._loading_progress: Optional[float] = None
        self._last_error: Optional[str] = None
        self._stderr_lines: List[str] = []
        self._stderr_has_oom: bool = False
        self._initialized: bool = False

        # Serializes start/stop/select so concurrent client requests cannot
        # spawn two llama-server processes or race on the active model.
        self._start_lock = asyncio.Lock()
        self._tasks: set = set()
        self._health_cache: Tuple[float, str] = (0.0, "down")
        self._hf_cache: Dict[str, Tuple[float, object]] = {}

        # Model download state
        self._downloading_model: bool = False
        self._cancel_model_download: bool = False
        self._model_download_status: Dict = {
            "status": "idle",
            "filename": None,
            "bytes_downloaded": 0,
            "total_bytes": 0,
            "percent": 0.0,
            "speed_bps": 0.0,
            "error": None,
        }

        # Engine download state
        self._downloading_engine: bool = False
        self._engine_download_status: Dict = {
            "status": "idle",
            "tag": None,
            "stage": "idle",
            "bytes_downloaded": 0,
            "total_bytes": 0,
            "percent": 0.0,
            "error": None,
        }

        try:
            AI_DIR.mkdir(parents=True, exist_ok=True)
            VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Importing the API must never fail because the data directory is
            # temporarily unwritable; individual operations surface the error.
            logger.warning("Could not create AI data directories", exc_info=True)

        # Register exit hook for clean interpreter shutdowns
        atexit.register(self.sync_stop)

    async def initialize(self) -> None:
        """One-time startup work, deliberately not done at import time.

        Importing a router must never kill processes or block startup.
        """
        if self._initialized:
            return
        self._initialized = True
        await asyncio.to_thread(self._cleanup_stale_pid)
        await asyncio.to_thread(self._cleanup_stale_downloads)

    # ==========================================
    # 1. Config, Validation & Paths
    # ==========================================

    def _read_config(self) -> dict:
        cfg = dict(DEFAULT_CONFIG)
        if ACTIVE_CONFIG_FILE.exists():
            try:
                with open(ACTIVE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
            except Exception as e:
                logger.warning(f"Failed to read AI config: {e}")
        return cfg

    def _write_config(self, cfg: dict):
        tmp = ACTIVE_CONFIG_FILE.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp, ACTIVE_CONFIG_FILE)
        except Exception as e:
            logger.error(f"Failed to write AI config: {e}")
            tmp.unlink(missing_ok=True)

    def get_config(self) -> dict:
        return self._read_config()

    def update_config(self, updates: dict) -> dict:
        """Validates and applies tunables without requiring a server restart."""
        if not isinstance(updates, dict):
            raise HTTPException(status_code=400, detail="A JSON object is required.")

        validators = {
            "gpu_layers": (int, 0, 999),
            "context_size": (int, 512, 131072),
            "idle_timeout_seconds": (int, 0, 86400),
            "port": (int, 1024, 65535),
            "threads": (int, 0, 256),
            "parallel": (int, 1, 16),
            "startup_timeout_seconds": (int, 10, 600),
            "request_timeout_seconds": (int, 30, 3600),
        }
        cfg = self._read_config()
        for key, (kind, minimum, maximum) in validators.items():
            if key not in updates:
                continue
            try:
                value = kind(updates[key])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail=f"{key} must be an integer."
                )
            if not minimum <= value <= maximum:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be between {minimum} and {maximum}.",
                )
            cfg[key] = value

        old_port = self.get_port()
        self._write_config(cfg)
        restart_required = cfg.get("port") != old_port and self.is_running()
        return {
            "success": True,
            "config": cfg,
            "restart_required": restart_required,
        }

    def get_port(self) -> int:
        try:
            port = int(self._read_config().get("port", DEFAULT_LLAMA_PORT))
        except (TypeError, ValueError):
            port = DEFAULT_LLAMA_PORT
        return port if 1024 <= port <= 65535 else DEFAULT_LLAMA_PORT

    def get_running_port(self) -> int:
        """Port of the live process, falling back to the configured port.

        A port configured while an engine is running must not redirect proxy
        traffic to a port nothing is listening on; the new port takes effect
        the next time the engine starts.
        """
        if self.process is not None and self.process.poll() is None:
            if self._active_port:
                return self._active_port
        return self.get_port()

    @staticmethod
    def _validate_engine_tag(tag: str) -> str:
        if not isinstance(tag, str) or not _SAFE_TAG_RE.fullmatch(tag.strip()):
            raise HTTPException(status_code=400, detail="Invalid engine version tag.")
        return tag.strip()

    def _validate_model_filename(self, filename: str) -> str:
        if not isinstance(filename, str):
            raise HTTPException(status_code=400, detail="Invalid model filename.")
        name = filename.strip()
        if (
            not name
            or name in (".", "..")
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or not name.lower().endswith(".gguf")
        ):
            raise HTTPException(status_code=400, detail="Invalid model filename.")
        return name

    @staticmethod
    def _validate_hf_repo(model_id: str) -> str:
        if not isinstance(model_id, str):
            raise HTTPException(status_code=400, detail="Invalid Hugging Face repo id.")
        clean_id = model_id.strip()
        if (
            not clean_id
            or not _HF_REPO_RE.fullmatch(clean_id)
            or any(part in (".", "..") for part in clean_id.split("/"))
        ):
            raise HTTPException(status_code=400, detail="Invalid Hugging Face repo id.")
        return clean_id

    @staticmethod
    def _validate_download_url(url: str) -> str:
        if not isinstance(url, str):
            raise HTTPException(status_code=400, detail="Invalid download URL.")
        clean = url.strip()
        parsed = urllib.parse.urlparse(clean)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            raise HTTPException(
                status_code=400,
                detail="Only HTTPS download URLs are allowed.",
            )
        if not any(
            host == suffix or host.endswith("." + suffix)
            for suffix in _ALLOWED_DOWNLOAD_SUFFIXES
        ):
            raise HTTPException(
                status_code=400,
                detail="Downloads are restricted to Hugging Face and GitHub hosts.",
            )
        return clean

    @staticmethod
    def _hf_headers() -> dict:
        headers = {"User-Agent": "PCLink-Server"}
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _spawn(self, coro) -> asyncio.Task:
        """create_task + keep a strong reference for the task's lifetime."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def get_active_engine_tag(self) -> Optional[str]:
        tag = self._read_config().get("active_version")
        try:
            return self._validate_engine_tag(tag) if tag else None
        except HTTPException:
            return None

    def get_active_engine_path(self) -> Optional[Path]:
        tag = self.get_active_engine_tag()
        if not tag:
            installed = self._scan_installed_engine_versions_sync()
            if installed:
                tag = installed[0]["tag"]
                cfg = self._read_config()
                cfg["active_version"] = tag
                self._write_config(cfg)

        if tag:
            target_dir = VERSIONS_DIR / tag
            bin_path = target_dir / SERVER_BIN_NAME
            if bin_path.exists():
                return bin_path

            matches = list(target_dir.rglob(SERVER_BIN_NAME))
            if matches:
                return matches[0]

        sys_bin = shutil.which(SERVER_BIN_NAME)
        if sys_bin:
            return Path(sys_bin)

        return None

    def get_active_model_name(self) -> Optional[str]:
        cfg = self._read_config()
        model_name = cfg.get("active_model")
        if isinstance(model_name, str) and model_name:
            try:
                name = self._validate_model_filename(model_name)
                if (MODELS_DIR / name).exists():
                    return name
            except HTTPException:
                pass
        for f in sorted(MODELS_DIR.iterdir()):
            if f.is_file() and f.name.lower().endswith(".gguf"):
                cfg["active_model"] = f.name
                self._write_config(cfg)
                return f.name
        return None

    def _system_profile(self) -> dict:
        vm = psutil.virtual_memory()
        return {
            "total_ram_bytes": vm.total,
            "available_ram_bytes": vm.available,
            "cpu_count": psutil.cpu_count(logical=True) or 1,
        }

    def get_active_model_path(self) -> Optional[Path]:
        name = self.get_active_model_name()
        if name:
            p = MODELS_DIR / name
            if p.exists():
                return p
        return None

    # ==========================================
    # 2. Engine Version Management (llama.cpp)
    # ==========================================

    def _scan_installed_engine_versions_sync(self) -> List[dict]:
        versions = []
        active_tag = self.get_active_engine_tag()

        if VERSIONS_DIR.exists():
            for item in sorted(VERSIONS_DIR.iterdir()):
                if not item.is_dir() or item.name.startswith("."):
                    continue
                try:
                    self._validate_engine_tag(item.name)
                except HTTPException:
                    continue

                bin_file = item / SERVER_BIN_NAME
                if not bin_file.exists():
                    matches = list(item.rglob(SERVER_BIN_NAME))
                    if matches:
                        bin_file = matches[0]

                if bin_file.exists():
                    size = bin_file.stat().st_size
                    ver_str = item.name
                    info_file = item / "info.json"
                    if info_file.exists():
                        try:
                            with open(info_file, "r", encoding="utf-8") as f:
                                ver_str = json.load(f).get("version_string", item.name)
                        except Exception:
                            pass

                    versions.append(
                        {
                            "tag": item.name,
                            "display_name": f"llama.cpp {item.name}",
                            "version_string": ver_str,
                            "is_active": (item.name == active_tag),
                            "size_bytes": size,
                            "path": str(bin_file),
                        }
                    )
        return versions

    async def get_installed_engine_versions(self) -> List[dict]:
        return await asyncio.to_thread(self._scan_installed_engine_versions_sync)

    @staticmethod
    def _pick_engine_asset(assets: List[dict]) -> Optional[str]:
        """Picks a matching llama.cpp build for this OS/CPU architecture.

        Prefers Vulkan (works on most modern GPUs) then generic CPU builds.
        CUDA/ROCm/SYCL/OpenVINO builds are excluded because they require
        toolchains/runtimes that are not guaranteed to exist on the host.
        """
        os_tokens = {
            "linux": ("ubuntu", "linux"),
            "windows": ("win",),
            "darwin": ("macos",),
        }.get(OS_TYPE, ())
        arch_tokens = {
            "x86_64": ("x64", "amd64"),
            "arm64": ("arm64", "aarch64"),
        }.get(ARCH_NAME, (ARCH_NAME,))

        candidates = []
        for asset in assets:
            name = asset.get("name", "")
            low = name.lower()
            url = asset.get("browser_download_url")
            if not url or not low.startswith("llama-"):
                continue
            if not (low.endswith(".zip") or low.endswith(".tar.gz")):
                continue
            if "cudart" in low:
                continue
            if os_tokens and not any(token in low for token in os_tokens):
                continue
            if arch_tokens and not any(token in low for token in arch_tokens):
                continue
            if any(bad in low for bad in ("cuda", "rocm", "sycl", "openvino")):
                continue

            score = 0
            if "vulkan" in low:
                score += 30
            if "cpu" in low:
                score += 20
            if not any(extra in low for extra in ("vulkan", "cpu")):
                score += 5
            candidates.append((score, len(low), url))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][2]

    async def fetch_github_releases(self) -> List[dict]:
        now = time.time()
        if self._releases_cache and (now - self._releases_cache_time < 600):
            return self._releases_cache

        url = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=12"
        headers = {
            "User-Agent": "PCLink-Server",
            "Accept": "application/vnd.github+json",
        }
        github_token = os.environ.get("GITHUB_TOKEN")
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        req = urllib.request.Request(url, headers=headers)
        loop = asyncio.get_running_loop()

        def _fetch():
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
            return []

        try:
            raw_releases = await loop.run_in_executor(None, _fetch)
            parsed = []
            for r in raw_releases:
                tag = r.get("tag_name")
                parsed.append(
                    {
                        "tag_name": tag,
                        "name": r.get("name") or tag,
                        "published_at": r.get("published_at"),
                        "download_url": self._pick_engine_asset(r.get("assets", [])),
                        "prerelease": r.get("prerelease", False),
                    }
                )

            self._releases_cache = parsed
            self._releases_cache_time = now
            return parsed
        except Exception as e:
            logger.error(f"Failed fetching llama.cpp releases: {e}")
            return self._releases_cache or []

    async def start_engine_download(
        self, tag: str, download_url: Optional[str] = None
    ) -> dict:
        tag = self._validate_engine_tag(tag)
        if self._downloading_engine:
            raise HTTPException(
                status_code=409, detail="Engine download is already in progress."
            )
        if (VERSIONS_DIR / tag).exists():
            raise HTTPException(
                status_code=409, detail=f"Engine version {tag} is already installed."
            )

        if download_url:
            download_url = self._validate_download_url(download_url)
        else:
            releases = await self.fetch_github_releases()
            release = next((r for r in releases if r["tag_name"] == tag), None)
            download_url = release.get("download_url") if release else None

        if not download_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not find a compatible precompiled build for "
                    f"{OS_TYPE}_{ARCH_NAME} in release {tag}"
                ),
            )

        self._downloading_engine = True
        self._engine_download_status = {
            "status": "downloading",
            "tag": tag,
            "stage": "downloading",
            "bytes_downloaded": 0,
            "total_bytes": 0,
            "percent": 0.0,
            "error": None,
        }

        self._spawn(self._run_engine_download(tag, download_url))
        return {"success": True, "tag": tag, "status": "downloading"}

    @staticmethod
    def _safe_extract_zip(archive: Path, destination: Path) -> None:
        base = destination.resolve()
        with zipfile.ZipFile(archive, "r") as z:
            for member in z.infolist():
                target = (destination / member.filename).resolve()
                if target != base and base not in target.parents:
                    raise ValueError(
                        f"Unsafe path in engine archive: {member.filename}"
                    )
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:  # symlink
                    raise ValueError(
                        f"Symlink not allowed in engine archive: {member.filename}"
                    )
            z.extractall(destination)

    @staticmethod
    def _safe_extract_tar(archive: Path, destination: Path) -> None:
        base = destination.resolve()
        with tarfile.open(archive, "r:*") as t:
            for member in t.getmembers():
                target = (destination / member.name).resolve()
                if target != base and base not in target.parents:
                    raise ValueError(f"Unsafe path in engine archive: {member.name}")
                if member.issym() or member.islnk():
                    raise ValueError(
                        f"Links not allowed in engine archive: {member.name}"
                    )
            try:
                t.extractall(destination, filter="data")
            except TypeError:
                t.extractall(destination)

    async def _run_engine_download(self, tag: str, download_url: str):
        staging_dir = VERSIONS_DIR / f".{tag}.staging"
        target_dir = VERSIONS_DIR / tag
        tmp_archive = staging_dir / "download.tmp"
        loop = asyncio.get_running_loop()

        def _do_download():
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            staging_dir.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(
                download_url, headers={"User-Agent": "PCLink-Server"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total_size = int(resp.headers.get("Content-Length", 0) or 0)
                if total_size:
                    free = shutil.disk_usage(VERSIONS_DIR).free
                    if free < total_size * 2 + 200 * 1024 * 1024:
                        raise RuntimeError(
                            "Not enough free disk space to install this engine."
                        )
                self._engine_download_status["total_bytes"] = total_size

                downloaded = 0
                with open(tmp_archive, "wb") as out:
                    while True:
                        chunk = resp.read(512 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        self._engine_download_status["bytes_downloaded"] = downloaded
                        if total_size > 0:
                            self._engine_download_status["percent"] = round(
                                (downloaded / total_size) * 100, 1
                            )

        def _do_extract_all():
            self._engine_download_status["stage"] = "extracting"
            self._engine_download_status["percent"] = 100.0

            if zipfile.is_zipfile(tmp_archive):
                self._safe_extract_zip(tmp_archive, staging_dir)
            elif tarfile.is_tarfile(tmp_archive):
                self._safe_extract_tar(tmp_archive, staging_dir)
            else:
                raise RuntimeError("Downloaded engine archive is not a zip/tar file.")

            tmp_archive.unlink(missing_ok=True)

            target_bin = staging_dir / SERVER_BIN_NAME
            if not target_bin.exists():
                matches = list(staging_dir.rglob(SERVER_BIN_NAME))
                if matches:
                    target_bin = matches[0]

            if not target_bin.exists():
                raise RuntimeError(
                    f"Extracted archive did not contain {SERVER_BIN_NAME}"
                )

            if OS_TYPE != "windows":
                for item in staging_dir.rglob("*"):
                    if item.is_file():
                        try:
                            item.chmod(0o755)
                        except OSError:
                            pass

            with open(staging_dir / "info.json", "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "tag_name": tag,
                        "version_string": tag,
                        "download_url": download_url,
                    },
                    f,
                    indent=2,
                )

        try:
            logger.info(f"Downloading llama.cpp {tag} from {download_url}...")
            await loop.run_in_executor(None, _do_download)
            logger.info(f"Extracting all assets for llama.cpp {tag}...")
            await loop.run_in_executor(None, _do_extract_all)

            if target_dir.exists():
                raise RuntimeError(f"Engine version {tag} was installed concurrently.")
            staging_dir.rename(target_dir)
            self.select_active_engine_version(tag)
            self._engine_download_status["status"] = "completed"
            self._engine_download_status["stage"] = "completed"
        except Exception as e:
            logger.error(f"Failed downloading engine {tag}: {e}")
            shutil.rmtree(staging_dir, ignore_errors=True)
            self._engine_download_status["status"] = "failed"
            self._engine_download_status["error"] = str(e)
        finally:
            self._downloading_engine = False

    def get_engine_download_progress(self) -> dict:
        return self._engine_download_status

    def _engine_binary_for_tag(self, tag: str) -> Optional[Path]:
        target_dir = VERSIONS_DIR / tag
        if not target_dir.is_dir():
            return None
        bin_path = target_dir / SERVER_BIN_NAME
        if not bin_path.exists():
            matches = list(target_dir.rglob(SERVER_BIN_NAME))
            if matches:
                bin_path = matches[0]
        if not bin_path.exists():
            return None
        try:
            if VERSIONS_DIR.resolve() not in bin_path.resolve().parents:
                return None
        except OSError:
            return None
        return bin_path

    def select_active_engine_version(self, tag: str) -> dict:
        tag = self._validate_engine_tag(tag)
        if not self._engine_binary_for_tag(tag):
            raise HTTPException(
                status_code=404, detail=f"Engine version {tag} not found."
            )

        cfg = self._read_config()
        cfg["active_version"] = tag
        self._write_config(cfg)
        self._health_cache = (0.0, "down")
        return {"success": True, "active_version": tag}

    def delete_engine_version(self, tag: str) -> dict:
        tag = self._validate_engine_tag(tag)
        if self.is_running() and self.get_active_engine_tag() == tag:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete active running engine build.",
            )

        target = VERSIONS_DIR / tag
        try:
            if VERSIONS_DIR.resolve() not in target.resolve().parents:
                raise HTTPException(status_code=400, detail="Invalid version path.")
        except OSError:
            raise HTTPException(status_code=400, detail="Invalid version path.")

        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            return {"success": True, "deleted": tag}
        raise HTTPException(status_code=404, detail=f"Version {tag} not found.")

    # ==========================================
    # 3. Model Management & Hugging Face Explorer
    # ==========================================

    def _cache_get(self, key: str, ttl: float):
        entry = self._hf_cache.get(key)
        if entry and (time.time() - entry[0]) < ttl:
            return entry[1]
        return None

    def _cache_set(self, key: str, value):
        # Bound the cache so long-running servers do not grow without limit.
        if len(self._hf_cache) >= 64:
            oldest = min(self._hf_cache, key=lambda k: self._hf_cache[k][0])
            self._hf_cache.pop(oldest, None)
        self._hf_cache[key] = (time.time(), value)

    async def get_models_catalog(self) -> dict:
        installed_models = await asyncio.to_thread(self._get_installed_models_sync)
        installed_by_name = {m["filename"]: m for m in installed_models}
        curated_names = {cm["filename"] for cm in CURATED_MODELS}

        catalog = []
        for cm in CURATED_MODELS:
            installed_entry = installed_by_name.get(cm["filename"])
            catalog.append(
                {
                    **cm,
                    "is_installed": installed_entry is not None,
                    "is_active": bool(installed_entry and installed_entry["is_active"]),
                }
            )

        custom_installed = [
            m for m in installed_models if m["filename"] not in curated_names
        ]

        return {
            "installed": installed_models,
            "curated": catalog,
            "custom": custom_installed,
            "active_model": self.get_active_model_name(),
            "models_revision": self._models_revision(installed_models),
            "system": self._system_profile(),
        }

    @staticmethod
    def _models_revision(installed_models: List[dict]) -> str:
        raw = "|".join(
            f"{m['filename']}:{m['size_bytes']}:{m['is_active']}"
            for m in sorted(installed_models, key=lambda x: x["filename"])
        )
        return str(hash(raw))

    async def search_huggingface_models(
        self, query: Optional[str] = None, limit: int = 25, sort: str = "downloads"
    ) -> List[dict]:
        """Search the Hugging Face Hub for GGUF repositories.

        Results are cached briefly and filtered to actual GGUF repos. Gated
        repos are surfaced with ``is_gated`` so the UI can explain why a
        download needs an HF token instead of silently failing.
        """
        limit = max(1, min(int(limit), 50))
        sort = sort if sort in ("downloads", "likes", "lastModified") else "downloads"
        clean_q = (query or "").strip()
        cache_key = f"search:{sort}:{limit}:{clean_q.lower()}"
        cached = self._cache_get(cache_key, 600)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()

        def _fetch():
            params = {
                "filter": "gguf",
                "sort": sort,
                "direction": "-1",
                "limit": str(limit),
            }
            if clean_q:
                params["search"] = clean_q

            url = "https://huggingface.co/api/models?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers=self._hf_headers())
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status != 200:
                    return []
                data = json.loads(resp.read().decode("utf-8"))

            results = []
            for m in data:
                mid = m.get("id", "")
                tags = m.get("tags", [])
                if "gguf" not in tags and "gguf" not in mid.lower():
                    continue

                parts = mid.split("/")
                author = parts[0] if len(parts) > 1 else "community"
                name = parts[1] if len(parts) > 1 else mid
                safetensors = m.get("safetensors") or {}
                param_count = (
                    safetensors.get("total") if isinstance(safetensors, dict) else None
                )
                results.append(
                    {
                        "id": mid,
                        "name": name,
                        "author": author,
                        "downloads": m.get("downloads", 0) or 0,
                        "likes": m.get("likes", 0) or 0,
                        "pipeline_tag": m.get("pipeline_tag", "text-generation"),
                        "is_gated": bool(m.get("gated")),
                        "params": param_count,
                        "last_modified": m.get("lastModified"),
                    }
                )
            return results

        try:
            results = await loop.run_in_executor(None, _fetch)
            self._cache_set(cache_key, results)
            return results
        except urllib.error.HTTPError as e:
            logger.warning(f"HuggingFace search returned HTTP {e.code}")
            return []
        except Exception as e:
            logger.error(f"Failed to search HuggingFace models: {e}")
            return []

    async def get_huggingface_model_files(self, model_id: str) -> dict:
        """Inspects repository GGUF files via the Hugging Face Tree API.

        Handles branch fallback, split shards, multimodal projectors, gated
        repos, and recommends a quantization that fits available host RAM.
        """
        clean_id = self._validate_hf_repo(model_id)
        cache_key = f"files:{clean_id.lower()}"
        cached = self._cache_get(cache_key, 600)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()

        def _get_json(url: str, timeout: float):
            req = urllib.request.Request(url, headers=self._hf_headers())
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
            return None

        def _fetch():
            branch = "main"
            items = None
            try:
                items = _get_json(
                    f"https://huggingface.co/api/models/{clean_id}/tree/main?recursive=true",
                    12,
                )
            except Exception:
                pass
            if items is None:
                branch = "master"
                try:
                    items = _get_json(
                        f"https://huggingface.co/api/models/{clean_id}/tree/master?recursive=true",
                        12,
                    )
                except Exception:
                    pass

            entries: List[Tuple[str, int]] = []
            if isinstance(items, list):
                for item in items:
                    fn = item.get("path", "") or ""
                    if fn.lower().endswith(".gguf") and not fn.lower().endswith(".tmp"):
                        entries.append((fn, int(item.get("size") or 0)))

            # Fallback for repos whose tree API is unavailable (e.g. gated).
            if not entries:
                try:
                    info = _get_json(
                        f"https://huggingface.co/api/models/{clean_id}", 10
                    )
                    if isinstance(info, dict):
                        for sibling in info.get("siblings", []):
                            fn = sibling.get("rfilename", "") or ""
                            if fn.lower().endswith(".gguf"):
                                entries.append((fn, 0))
                except Exception:
                    pass

            available_ram = psutil.virtual_memory().available
            ram_budget = max(0, available_ram - 1024 * 1024 * 1024)
            ggufs = []
            has_projector = False
            has_split_files = False

            for fn, size in entries:
                basename = fn.split("/")[-1]
                low_name = basename.lower()
                if "mmproj" in low_name or "projector" in low_name:
                    has_projector = True
                    continue
                if _SPLIT_GGUF_RE.search(fn):
                    has_split_files = True
                    continue

                match = _QUANT_RE.search(basename)
                quant_type = match.group(1).upper() if match else "GGUF"
                fits_in_ram = bool(size and size <= ram_budget)
                preferred = quant_type in (
                    "Q4_K_M",
                    "Q5_K_M",
                    "Q4_0",
                    "Q5_0",
                    "IQ4_XS",
                    "Q4_K_S",
                )
                size_fmt = (
                    f"{(size / (1024**3)):.2f} GB"
                    if size >= 1024**3
                    else f"{(size / (1024**2)):.1f} MB"
                    if size
                    else "Unknown size"
                )
                ggufs.append(
                    {
                        "filename": basename,
                        "path": fn,
                        "size_bytes": size,
                        "size_formatted": size_fmt,
                        "quant": quant_type,
                        "fits_in_ram": fits_in_ram,
                        "is_recommended": preferred and fits_in_ram,
                        "download_url": (
                            f"https://huggingface.co/{clean_id}/resolve/{branch}/"
                            f"{urllib.parse.quote(fn, safe='/')}"
                        ),
                    }
                )

            rank = {
                "Q4_K_M": 0,
                "Q5_K_M": 1,
                "Q4_K_S": 2,
                "Q4_0": 3,
                "Q5_0": 4,
                "IQ4_XS": 5,
                "Q6_K": 6,
                "Q8_0": 7,
            }
            ggufs.sort(
                key=lambda x: (
                    not x["is_recommended"],
                    not x["fits_in_ram"],
                    rank.get(x["quant"], 99),
                    x["size_bytes"] or 1,
                )
            )

            suggested_repos = []
            if not ggufs:
                search_params = {
                    "filter": "gguf",
                    "search": clean_id.split("/")[-1],
                    "limit": "8",
                }
                try:
                    data = _get_json(
                        "https://huggingface.co/api/models?"
                        + urllib.parse.urlencode(search_params),
                        10,
                    )
                    for m in data or []:
                        mid_s = m.get("id")
                        if mid_s and mid_s != clean_id:
                            suggested_repos.append(mid_s)
                except Exception:
                    pass

            note = None
            if has_split_files and not ggufs:
                note = (
                    "This repository only contains split GGUF shards. "
                    "PCLink currently needs a single-file GGUF."
                )
            elif has_projector:
                note = (
                    "Multimodal projector files were ignored; only the language "
                    "model weights are listed."
                )

            return {
                "model_id": clean_id,
                "branch": branch,
                "files": ggufs,
                "suggested_repos": suggested_repos,
                "has_projector": has_projector,
                "has_split_files": has_split_files,
                "available_ram_bytes": available_ram,
                "note": note,
            }

        try:
            result = await loop.run_in_executor(None, _fetch)
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Failed to retrieve HF model files for {model_id}: {e}")
            return {
                "model_id": clean_id,
                "files": [],
                "suggested_repos": [],
                "error": str(e),
            }

    async def open_models_directory(self) -> dict:
        try:
            from ..core.utils import open_directory

            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            success = open_directory(MODELS_DIR)
            return {"success": success, "path": str(MODELS_DIR)}
        except Exception as e:
            logger.error(f"Failed to open models directory: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @staticmethod
    def _validate_gguf_magic(path: Path) -> None:
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic != b"GGUF":
            raise ValueError(
                "Downloaded file is not a valid GGUF model (bad magic bytes)."
            )

    async def import_local_model(self, file_path: str, symlink: bool = True) -> dict:
        if not isinstance(file_path, str) or not file_path.strip():
            raise HTTPException(status_code=400, detail="A file path is required.")
        source = Path(file_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

        if not source.name.lower().endswith(".gguf"):
            raise HTTPException(
                status_code=400, detail="Only .gguf files can be imported."
            )
        filename = self._validate_model_filename(source.name)
        try:
            self._validate_gguf_magic(source)
        except (OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

        target = MODELS_DIR / filename
        if target.exists():
            if target.resolve() == source:
                await self.select_active_model(filename, start_engine=False)
                return {
                    "success": True,
                    "filename": filename,
                    "message": "Model already linked",
                }
            raise HTTPException(
                status_code=409,
                detail=f"A model named {filename} already exists in the library.",
            )

        def _link_or_copy() -> bool:
            try:
                if symlink:
                    os.symlink(source, target)
                    return True
                shutil.copy2(source, target)
                return False
            except OSError as e:
                logger.warning(f"Symlink failed, falling back to copy: {e}")
                shutil.copy2(source, target)
                return False

        is_linked = await asyncio.to_thread(_link_or_copy)

        if not self.get_active_model_name():
            await self.select_active_model(filename, start_engine=False)

        size = target.stat().st_size
        return {
            "success": True,
            "filename": filename,
            "size_bytes": size,
            "is_symlink": is_linked,
        }

    async def save_uploaded_model(self, upload_file: UploadFile) -> dict:
        raw_name = Path(upload_file.filename or "").name
        filename = self._validate_model_filename(raw_name)
        target = MODELS_DIR / filename
        tmp = MODELS_DIR / f"{filename}.upload_tmp"

        if target.exists():
            raise HTTPException(
                status_code=409,
                detail=f"A model named {filename} already exists in the library.",
            )

        try:
            with open(tmp, "wb") as out:
                while chunk := await upload_file.read(1024 * 1024):
                    out.write(chunk)
            await asyncio.to_thread(self._validate_gguf_magic, tmp)
            os.replace(tmp, target)

            if not self.get_active_model_name():
                await self.select_active_model(filename, start_engine=False)

            return {
                "success": True,
                "filename": filename,
                "size_bytes": target.stat().st_size,
            }
        except HTTPException:
            tmp.unlink(missing_ok=True)
            raise
        except Exception as e:
            tmp.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    async def start_model_download(
        self,
        model_id: Optional[str] = None,
        custom_url: Optional[str] = None,
        custom_name: Optional[str] = None,
    ) -> dict:
        if self._downloading_model:
            raise HTTPException(
                status_code=409,
                detail="Another model download is already in progress.",
            )

        url = None
        filename = None

        if model_id:
            match = next((m for m in CURATED_MODELS if m["id"] == model_id), None)
            if not match:
                raise HTTPException(
                    status_code=404, detail=f"Unknown curated model id: {model_id}"
                )
            url = match["url"]
            filename = match["filename"]

        if custom_url:
            url = self._validate_download_url(custom_url)
            candidate = custom_name.strip() if isinstance(custom_name, str) else ""
            if not candidate:
                candidate = urllib.parse.unquote(
                    Path(urllib.parse.urlparse(url).path).name
                )
            if not candidate.lower().endswith(".gguf"):
                candidate += ".gguf"
            filename = self._validate_model_filename(candidate)

        if not url or not filename:
            raise HTTPException(
                status_code=400, detail="Invalid model URL or identifier."
            )

        target = MODELS_DIR / filename
        if target.exists():
            raise HTTPException(
                status_code=409,
                detail=f"A model named {filename} already exists in the library.",
            )

        self._downloading_model = True
        self._cancel_model_download = False
        self._model_download_status = {
            "status": "downloading",
            "filename": filename,
            "bytes_downloaded": 0,
            "total_bytes": 0,
            "percent": 0.0,
            "speed_bps": 0.0,
            "error": None,
        }

        self._spawn(self._run_model_download(url, filename))
        return {"success": True, "filename": filename, "status": "downloading"}

    async def _run_model_download(self, url: str, filename: str):
        target_path = MODELS_DIR / filename
        tmp_path = MODELS_DIR / f"{filename}.tmp"
        loop = asyncio.get_running_loop()
        parsed = urllib.parse.urlparse(url)
        hf_host = (parsed.hostname or "").lower()

        def _download():
            resume_from = tmp_path.stat().st_size if tmp_path.exists() else 0
            headers = (
                self._hf_headers()
                if hf_host == "huggingface.co" or hf_host.endswith(".huggingface.co")
                else {"User-Agent": "PCLink-Server"}
            )
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                range_ok = resp.status == 206 and resume_from > 0
                if range_ok:
                    content_range = resp.headers.get("Content-Range", "")
                    match = re.match(r"bytes\s+(\d+)-", content_range)
                    if not match or int(match.group(1)) != resume_from:
                        raise RuntimeError(
                            "Server returned an invalid resume range; retry the download."
                        )
                content_length = int(resp.headers.get("Content-Length", 0) or 0)
                total_size = (
                    (content_length + resume_from) if range_ok else content_length
                )
                self._model_download_status["total_bytes"] = total_size

                if total_size > 0:
                    free = shutil.disk_usage(MODELS_DIR).free
                    needed = max(0, total_size - resume_from) + 100 * 1024 * 1024
                    if free < needed:
                        raise RuntimeError(
                            "Not enough free disk space to download this model."
                        )

                mode = "ab" if range_ok else "wb"
                downloaded = resume_from if range_ok else 0
                started = time.monotonic()
                with open(tmp_path, mode) as out:
                    while True:
                        if self._cancel_model_download:
                            break
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(time.monotonic() - started, 0.001)
                        session_bytes = downloaded - (resume_from if range_ok else 0)
                        self._model_download_status["bytes_downloaded"] = downloaded
                        self._model_download_status["speed_bps"] = round(
                            session_bytes / elapsed, 1
                        )
                        if total_size > 0:
                            self._model_download_status["percent"] = round(
                                min(downloaded / total_size * 100, 100.0), 1
                            )

        try:
            await loop.run_in_executor(None, _download)

            if self._cancel_model_download:
                tmp_path.unlink(missing_ok=True)
                self._model_download_status["status"] = "cancelled"
                self._model_download_status["speed_bps"] = 0.0
            else:
                await asyncio.to_thread(self._validate_gguf_magic, tmp_path)
                if target_path.exists():
                    raise RuntimeError(
                        f"A model named {filename} was added while downloading."
                    )
                os.replace(tmp_path, target_path)
                self._model_download_status["status"] = "completed"
                self._model_download_status["percent"] = 100.0
                self._model_download_status["speed_bps"] = 0.0

                if not self.get_active_model_name():
                    await self.select_active_model(filename, start_engine=False)
        except Exception as e:
            logger.error(f"Model download failed for {filename}: {e}")
            if tmp_path.exists():
                # Keep a partial file for resume, unless it is clearly not a
                # GGUF stream (e.g. an HTML error page was saved).
                try:
                    with open(tmp_path, "rb") as f:
                        head = f.read(4)
                    if head and head != b"GGUF":
                        tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._model_download_status["status"] = "failed"
            self._model_download_status["speed_bps"] = 0.0
            self._model_download_status["error"] = str(e)
        finally:
            self._downloading_model = False

    def get_download_progress(self) -> dict:
        return self._model_download_status

    def cancel_model_download(self) -> dict:
        if self._downloading_model:
            self._cancel_model_download = True
            return {"success": True, "message": "Download cancelling"}
        return {"success": False, "message": "No active download"}

    async def select_active_model(
        self, filename: str, start_engine: bool = True
    ) -> dict:
        filename = self._validate_model_filename(filename)
        target = MODELS_DIR / filename
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Model {filename} not found.")

        cfg = self._read_config()
        already_active = cfg.get("active_model") == filename
        was_running = await asyncio.to_thread(self.is_running)
        cfg["active_model"] = filename
        self._write_config(cfg)

        if was_running and not already_active:
            await self.stop_server()
        if (start_engine or was_running) and not (already_active and was_running):
            self._spawn(self._start_server_in_background())

        return {
            "success": True,
            "active_model": filename,
            "engine_state": (
                "starting"
                if (start_engine or was_running)
                and not (already_active and was_running)
                else "ready"
                if was_running
                else "stopped"
            ),
        }

    async def _start_server_in_background(self):
        try:
            await self.start_server()
        except HTTPException as e:
            self._engine_state = "error"
            self._last_error = str(e.detail)
            logger.error("Failed to start selected AI model: %s", e.detail)
        except Exception as e:
            self._engine_state = "error"
            self._last_error = str(e)
            logger.exception("Failed to start selected AI model")

    async def delete_model(self, filename: str) -> dict:
        filename = self._validate_model_filename(filename)
        target = MODELS_DIR / filename
        try:
            if MODELS_DIR.resolve() not in target.resolve().parents:
                raise HTTPException(status_code=400, detail="Invalid model path.")
        except OSError:
            raise HTTPException(status_code=400, detail="Invalid model path.")

        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Model {filename} not found.")

        if (
            await asyncio.to_thread(self.is_running)
            and self.get_active_model_name() == filename
        ):
            await self.stop_server()

        target.unlink(missing_ok=True)

        cfg = self._read_config()
        if cfg.get("active_model") == filename:
            cfg["active_model"] = None
            self._write_config(cfg)

        return {"success": True, "deleted": filename}

    # ==========================================
    # 4. Engine Process Lifecycle (llama-server) & Death Ties
    # ==========================================

    def _is_port_in_use(self, port: Optional[int] = None) -> bool:
        """Checks whether the configured loopback port is occupied."""
        port = port or self.get_port()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def _get_installed_models_sync(self) -> List[dict]:
        """Safely scans installed GGUF models, handling broken symlinks or locked files."""
        active_model = self.get_active_model_name()
        installed = []
        if MODELS_DIR.exists():
            for f in sorted(MODELS_DIR.iterdir()):
                try:
                    if not f.is_file() or not f.name.lower().endswith(".gguf"):
                        continue
                    size = f.stat().st_size
                    installed.append(
                        {
                            "name": f.name,
                            "filename": f.name,
                            "size_bytes": size,
                            "size_formatted": f"{(size / (1024 * 1024 * 1024)):.2f} GB"
                            if size >= 1024 * 1024 * 1024
                            else f"{(size / (1024 * 1024)):.1f} MB",
                            "is_installed": True,
                            "is_active": (f.name == active_model),
                            "path": str(f),
                            "is_symlink": f.is_symlink(),
                        }
                    )
                except (OSError, FileNotFoundError, PermissionError) as e:
                    logger.warning(f"Skipping inaccessible model file {f.name}: {e}")
        return installed

    async def get_status(self) -> dict:
        """Returns AI subsystem status, including engine startup progress."""
        try:
            engine_path = self.get_active_engine_path()
            installed_models = await asyncio.to_thread(self._get_installed_models_sync)
            # Health probing is blocking; keep it off the event loop.
            engine_state = await asyncio.to_thread(self.get_engine_state)
            cfg = self._read_config()

            return {
                "engine_installed": engine_path is not None and engine_path.exists(),
                "active_engine_tag": self.get_active_engine_tag(),
                "engine_path": str(engine_path) if engine_path else None,
                "model_installed": len(installed_models) > 0,
                "active_model": self.get_active_model_name(),
                "is_running": engine_state == "ready",
                "engine_state": engine_state,
                "loading_model": self._loading_model
                if engine_state in ("starting", "loading")
                else None,
                "loading_message": self._loading_message
                if engine_state in ("starting", "loading")
                else None,
                "loading_progress": self._loading_progress
                if engine_state in ("starting", "loading")
                else 100.0
                if engine_state == "ready"
                else 0.0,
                "error_message": self._last_error if engine_state == "error" else None,
                "port": self.get_running_port(),
                "config": {
                    "gpu_layers": cfg.get("gpu_layers"),
                    "context_size": cfg.get("context_size"),
                    "idle_timeout_seconds": cfg.get("idle_timeout_seconds"),
                    "threads": cfg.get("threads"),
                    "parallel": cfg.get("parallel"),
                },
                "system": self._system_profile(),
                "models_revision": self._models_revision(installed_models),
                "installed_models_count": len(installed_models),
            }
        except Exception as e:
            logger.exception(f"Unhandled error in get_status: {e}")
            self._engine_state = "error"
            self._last_error = str(e)
            return {
                "engine_installed": False,
                "active_engine_tag": None,
                "engine_path": None,
                "model_installed": False,
                "active_model": None,
                "is_running": False,
                "engine_state": "error",
                "loading_model": None,
                "loading_message": None,
                "loading_progress": 0.0,
                "port": self.get_running_port(),
                "config": {},
                "system": self._system_profile(),
                "models_revision": "0",
                "installed_models_count": 0,
                "error_message": str(e),
            }

    def get_engine_state(self) -> str:
        if self.process is not None:
            exit_code = self.process.poll()
            if exit_code is not None:
                self.process = None
                self._active_port = None
                self._engine_state = "error"
                if not self._last_error:
                    self._last_error = f"Engine exited unexpectedly (code {exit_code})"
                return "error"
            if self._engine_state in ("starting", "loading", "ready"):
                return self._engine_state

        if self._is_port_in_use():
            healthy, state = self._probe_llama_health()
            if healthy:
                self._engine_state = "ready"
                return "ready"
            if state == "loading":
                self._engine_state = "loading"
                return "loading"
            # Port is occupied by something that is not our healthy engine.
            if self._engine_state not in ("starting", "loading"):
                self._engine_state = "stopped"
            return self._engine_state

        if self._engine_state == "error":
            return "error"
        self._engine_state = "stopped"
        return "stopped"

    def _probe_llama_health(
        self, port: Optional[int] = None, use_cache: bool = True
    ) -> Tuple[bool, str]:
        port = port or self.get_running_port()
        now = time.monotonic()
        if use_cache and (now - self._health_cache[0]) < 1.0:
            state = self._health_cache[1]
            return state == "ready", state

        state = "down"
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/health",
                headers={"User-Agent": "PCLink-Server"},
            )
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    state = "ready"
                elif resp.status == 503:
                    state = "loading"
        except urllib.error.HTTPError as e:
            if e.code == 503:
                state = "loading"
        except Exception:
            logger.debug("Could not probe llama-server health", exc_info=True)

        self._health_cache = (time.monotonic(), state)
        return state == "ready", state

    def _start_stderr_drain(self, proc: subprocess.Popen):
        if proc.stderr is None:
            return

        def read_stderr():
            try:
                for raw_line in iter(proc.stderr.readline, b""):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or self.process is not proc:
                        continue

                    self._stderr_lines.append(line)
                    if len(self._stderr_lines) > 60:
                        del self._stderr_lines[:-60]

                    if "load_tensors:" in line or "llm_load_tensors:" in line:
                        self._engine_state = "loading"
                        layers = re.search(
                            r"offloaded\s+(\d+)/(\d+)\s+layers",
                            line,
                            re.IGNORECASE,
                        )
                        if layers:
                            current, total = map(int, layers.groups())
                            if total > 0:
                                self._loading_progress = round(
                                    current / total * 90.0, 1
                                )
                            self._loading_message = (
                                f"Offloading layers to GPU ({current}/{total})..."
                            )
                        else:
                            self._loading_message = line.split(":", 1)[-1].strip()[:90]
                    elif (
                        "server is listening on" in line.lower()
                        or "http server listening" in line.lower()
                    ):
                        self._engine_state = "ready"
                        self._loading_message = "Engine ready"
                        self._loading_progress = 100.0
                    elif "error" in line.lower() and self._engine_state != "ready":
                        self._last_error = line

                    low = line.lower()
                    if any(
                        token in low
                        for token in (
                            "out of memory",
                            "failed to allocate",
                            "cudamalloc",
                            "vkallocatememory",
                            "erroroutofdevicememory",
                        )
                    ):
                        self._stderr_has_oom = True
            except Exception:
                logger.exception("Error while reading llama-server stderr")

        threading.Thread(target=read_stderr, daemon=True).start()

    def _verify_llama_health(self, port: Optional[int] = None) -> bool:
        """Checks if llama-server is healthy and answering on the port."""
        healthy, state = self._probe_llama_health(port, use_cache=False)
        return healthy or state == "loading"

    def _cleanup_stale_pid(self):
        """Terminates only the engine process PCLink itself recorded.

        Never kill processes by executable name: users may run their own
        llama.cpp / LM Studio / Ollama instances and those must not be touched.
        """
        if not PID_FILE.exists():
            return
        try:
            pid = int(PID_FILE.read_text().strip())
        except (OSError, ValueError):
            PID_FILE.unlink(missing_ok=True)
            return

        try:
            if pid == os.getpid():
                return
            proc = psutil.Process(pid)
            if Path(proc.exe() or "").name != SERVER_BIN_NAME:
                return
            exe_path = Path(proc.exe()).resolve()
            is_ours = VERSIONS_DIR.resolve() in exe_path.parents
            if not is_ours:
                sys_bin = shutil.which(SERVER_BIN_NAME)
                is_ours = bool(sys_bin) and Path(sys_bin).resolve() == exe_path
            if not is_ours:
                logger.warning(
                    "Refusing to kill untracked llama-server process PID %s", pid
                )
                return
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except psutil.TimeoutExpired:
                proc.kill()
        except psutil.NoSuchProcess:
            pass
        except Exception:
            logger.debug("Could not clean up stale AI PID %s", pid, exc_info=True)
        finally:
            PID_FILE.unlink(missing_ok=True)
            self._health_cache = (0.0, "down")

    def _cleanup_stale_downloads(self):
        """Removes abandoned partial downloads left behind by a previous crash.

        Recent ``.tmp`` files are kept so a download can resume after a crash;
        only genuinely stale ones are discarded to reclaim disk space.
        """
        try:
            for path in MODELS_DIR.glob("*.upload_tmp"):
                if path.is_file():
                    path.unlink(missing_ok=True)
            cutoff = time.time() - 24 * 60 * 60
            for path in MODELS_DIR.glob("*.tmp"):
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
            for path in VERSIONS_DIR.glob(".*.staging"):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
        except OSError:
            logger.debug("Failed cleaning stale AI downloads", exc_info=True)

    def is_running(self) -> bool:
        if self.process is not None:
            exit_code = self.process.poll()
            if exit_code is None:
                return True
            self.process = None
            self._active_port = None
            self._engine_state = "error"
            if not self._last_error:
                self._last_error = f"Engine exited unexpectedly (code {exit_code})"

        if self._is_port_in_use():
            healthy, state = self._probe_llama_health()
            return healthy or state == "loading"
        return False

    def sync_stop(self):
        """Synchronous cleanup called on interpreter shutdown or atexit."""
        process = self.process
        self.process = None
        self._active_port = None
        if process:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        self._cleanup_stale_pid()

    def _engine_env(self, bin_path: Path) -> dict:
        """Configures environment paths so llama-server can locate its shared libraries."""
        env = os.environ.copy()
        bin_dir = str(bin_path.parent)

        if OS_TYPE == "windows":
            curr_path = env.get("PATH", "")
            if bin_dir not in curr_path:
                env["PATH"] = bin_dir + os.pathsep + curr_path
        else:
            curr_ld = env.get("LD_LIBRARY_PATH", "")
            search_dirs = [bin_dir]
            for sub in bin_path.parent.iterdir():
                if sub.is_dir():
                    search_dirs.append(str(sub))
            joined = os.pathsep.join(search_dirs)
            env["LD_LIBRARY_PATH"] = f"{joined}:{curr_ld}" if curr_ld else joined

        return env

    async def start_server(self) -> dict:
        async with self._start_lock:
            return await self._start_server_locked()

    async def _start_server_locked(self) -> dict:
        engine_path = self.get_active_engine_path()
        if not engine_path or not engine_path.exists():
            self._engine_state = "error"
            self._last_error = "llama.cpp engine binary is not installed."
            raise HTTPException(status_code=400, detail=self._last_error)

        model_path = self.get_active_model_path()
        if not model_path or not model_path.exists():
            self._engine_state = "error"
            self._last_error = "No active GGUF model installed or selected."
            raise HTTPException(status_code=400, detail=self._last_error)

        if self.process is not None and self.process.poll() is None:
            state = self.get_engine_state()
            return {
                "success": True,
                "running": state == "ready",
                "model": model_path.name,
                "state": state,
            }

        port = self.get_port()
        # Never kill whatever owns the port. If it is a foreign runtime (for
        # example Ollama or a user-started llama.cpp), fail with an actionable
        # error instead of silently proxying to the wrong model.
        if self._is_port_in_use(port):
            healthy, _ = self._probe_llama_health(port, use_cache=False)
            self._engine_state = "error"
            if healthy:
                self._last_error = (
                    f"Port {port} is already used by another llama-server instance. "
                    "Stop it or choose a different port in AI settings."
                )
            else:
                self._last_error = (
                    f"Port {port} is already in use by another application. "
                    "Choose a different port in AI settings."
                )
            raise HTTPException(status_code=409, detail=self._last_error)

        self._engine_state = "starting"
        self._loading_model = model_path.name
        self._loading_message = "Initializing engine and allocating buffers..."
        self._loading_progress = 5.0
        self._last_error = None
        self._stderr_lines = []
        self._stderr_has_oom = False

        cfg = self._read_config()
        gpu_layers = int(cfg.get("gpu_layers", 99))
        ctx_size = int(cfg.get("context_size", 8192))
        threads = int(cfg.get("threads", 0) or 0)
        parallel = int(cfg.get("parallel", 1) or 1)
        startup_timeout = int(cfg.get("startup_timeout_seconds", 120) or 120)

        args = [
            str(engine_path),
            "-m",
            str(model_path),
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
            "--ctx-size",
            str(ctx_size),
            "-ngl",
            str(gpu_layers),
            "--jinja",
        ]
        if threads > 0:
            args.extend(["--threads", str(threads)])
        if parallel > 1:
            args.extend(["--parallel", str(parallel)])

        logger.info(f"Starting local AI engine: {' '.join(args)}")

        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
            "env": self._engine_env(engine_path),
        }

        # Linux: OS kernel sends SIGTERM to llama-server if PCLink terminates
        if OS_TYPE == "linux":
            kwargs["preexec_fn"] = _linux_set_pdeathsig
        elif OS_TYPE == "windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self.process = subprocess.Popen(args, **kwargs)
        except OSError as e:
            self.process = None
            self._engine_state = "error"
            self._last_error = f"Failed to launch llama-server: {e}"
            logger.exception("Failed to launch llama-server")
            raise HTTPException(status_code=500, detail=self._last_error) from e

        process = self.process
        self._active_port = port
        self._last_request_time = time.time()
        self._start_stderr_drain(process)

        # Windows: Bind child process to Job Object with KILL_ON_JOB_CLOSE
        if OS_TYPE == "windows":
            _assign_windows_job_kill_on_close(process)

        try:
            PID_FILE.write_text(str(process.pid), encoding="utf-8")
        except OSError:
            logger.exception("Failed to write llama-server PID file")

        if not self._idle_monitor_task or self._idle_monitor_task.done():
            self._idle_monitor_task = self._spawn(self._idle_watcher())

        max_checks = max(1, int(startup_timeout / 0.5))
        for _ in range(max_checks):
            await asyncio.sleep(0.5)
            if self.process is not process:
                return {
                    "success": True,
                    "running": False,
                    "model": model_path.name,
                    "state": self._engine_state,
                }
            exit_code = process.poll()
            if exit_code is not None:
                self.process = None
                self._active_port = None
                self._engine_state = "error"
                PID_FILE.unlink(missing_ok=True)
                err_details = "\n".join(self._stderr_lines[-5:])
                hint = ""
                if self._stderr_has_oom:
                    hint = (
                        "\nHint: GPU allocation failed. Lower GPU offload layers "
                        "or set them to 0 for CPU-only inference."
                    )
                self._last_error = (
                    "Engine failed to start: "
                    f"{err_details or f'Exit code {exit_code}'}{hint}"
                )
                raise HTTPException(status_code=500, detail=self._last_error)

            healthy, health_state = self._probe_llama_health(port, use_cache=False)
            if healthy:
                self._engine_state = "ready"
                self._loading_message = "Engine ready"
                self._loading_progress = 100.0
                return {
                    "success": True,
                    "running": True,
                    "model": model_path.name,
                    "state": "ready",
                }
            if health_state == "loading":
                self._engine_state = "loading"

        self._loading_message = "Model is still loading. Check status for progress."
        return {
            "success": True,
            "running": False,
            "model": model_path.name,
            "state": self._engine_state,
        }

    async def stop_server(self) -> dict:
        async with self._start_lock:
            return await self._stop_server_locked()

    async def _stop_server_locked(self) -> dict:
        self._engine_state = "stopped"
        self._loading_model = None
        self._loading_message = None
        self._loading_progress = None
        self._last_error = None
        self._health_cache = (0.0, "down")

        process = self.process
        self.process = None
        self._active_port = None
        if process:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except Exception:
                    logger.exception("Failed to force-stop llama-server")
            except OSError:
                logger.exception("Failed to stop llama-server")

        PID_FILE.unlink(missing_ok=True)

        logger.info("Local AI engine stopped (RAM/VRAM freed).")
        return {"success": True, "running": False, "state": "stopped"}

    async def shutdown(self):
        """Called from the FastAPI lifespan on application shutdown."""
        try:
            if self.is_running() or self.process is not None:
                await self.stop_server()
            else:
                await asyncio.to_thread(self._cleanup_stale_pid)
        except Exception:
            logger.exception("Failed to shut down local AI engine")

    async def ensure_running(self):
        """Ensures the local server is running and resets the idle timer."""
        self._last_request_time = time.time()
        state = await asyncio.to_thread(self.get_engine_state)

        if state == "ready":
            return

        if state in ("starting", "loading"):
            cfg = self._read_config()
            timeout = int(cfg.get("startup_timeout_seconds", 120) or 120)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                state = await asyncio.to_thread(self.get_engine_state)
                if state == "ready":
                    self._last_request_time = time.time()
                    return
                if state in ("stopped", "error"):
                    break
            if state != "ready":
                raise HTTPException(
                    status_code=503,
                    detail=(
                        self._last_error
                        or "The local model is still loading. Retry shortly."
                    ),
                )
            return

        if state == "error":
            raise HTTPException(
                status_code=503,
                detail=self._last_error or "Local AI engine is in an error state.",
            )

        result = await self.start_server()
        if result.get("state") != "ready":
            raise HTTPException(
                status_code=503,
                detail=(
                    self._last_error
                    or "The local model is still loading. Retry shortly."
                ),
            )

    async def _idle_watcher(self):
        """Periodically checks if the model has been idle for > timeout and unloads it."""
        while True:
            await asyncio.sleep(30)
            state = await asyncio.to_thread(self.get_engine_state)
            if state in ("stopped", "error"):
                break
            if state in ("starting", "loading"):
                continue
            cfg = self._read_config()
            timeout = int(cfg.get("idle_timeout_seconds", 600) or 0)
            if timeout <= 0:
                continue
            if time.time() - self._last_request_time > timeout:
                logger.info(
                    "Local AI engine idle for > %ss. Stopping to free RAM/VRAM.",
                    timeout,
                )
                await self.stop_server()
                break

    # ==========================================
    # 5. Reverse Proxy for OpenAI Endpoints
    # ==========================================

    def list_openai_models(self) -> dict:
        """OpenAI-compatible model discovery without waking a cold engine.

        Only report a real installed weight. Returning a placeholder id when
        no model exists makes mobile clients offer a model that cannot be
        selected, so an empty list is the honest answer in that case.
        """
        model = self.get_active_model_name()
        data = []
        if model:
            data.append(
                {
                    "id": model,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "pclink",
                }
            )
        return {"object": "list", "data": data}

    @staticmethod
    def _llama_error_detail(raw: str) -> str:
        """Extract a human-readable message from a llama-server error body."""
        raw = (raw or "").strip()
        if not raw:
            return "The local AI engine rejected the request."

        try:
            parsed = json.loads(raw)
        except Exception:
            return raw[:2000]

        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            if isinstance(error, str) and error.strip():
                return error.strip()
            for key in ("message", "detail"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return raw[:2000]

    @staticmethod
    def _is_vision_input_unsupported(message: str) -> bool:
        """True when the loaded model rejected image parts for lack of vision."""
        text = (message or "").lower()
        return (
            "image input is not supported" in text
            or "image input not supported" in text
            or "does not support image" in text
            or "does not support vision" in text
            or ("mmproj" in text and "not" in text)
        )

    @staticmethod
    def _strip_vision_parts(body: dict) -> Tuple[dict, int]:
        """Return a copy of an OpenAI request without image parts.

        Text-only GGUF models still need the attachment metadata so they can
        call the client's ``upload`` tool. Replacing an image part with a short
        notice keeps that metadata while avoiding an unsupported multimodal
        request.
        """
        messages = body.get("messages")
        if not isinstance(messages, list):
            return body, 0

        removed_total = 0
        new_messages = []
        for message in messages:
            if not isinstance(message, dict):
                new_messages.append(message)
                continue
            content = message.get("content")
            if not isinstance(content, list):
                new_messages.append(message)
                continue

            kept_parts = []
            removed_here = 0
            for part in content:
                if isinstance(part, dict) and part.get("type") in (
                    "image",
                    "image_url",
                    "input_image",
                ):
                    removed_here += 1
                    continue
                kept_parts.append(part)

            if removed_here == 0:
                new_messages.append(message)
                continue

            removed_total += removed_here
            kept_parts.append(
                {
                    "type": "text",
                    "text": (
                        f"[PCLink: {removed_here} image attachment(s) omitted because "
                        "the selected local model does not support image input. The "
                        "attachment metadata and IDs above remain available for file "
                        "upload actions.]"
                    ),
                }
            )
            new_message = dict(message)
            new_message["content"] = kept_parts
            new_messages.append(new_message)

        if removed_total == 0:
            return body, 0

        stripped = dict(body)
        stripped["messages"] = new_messages
        return stripped, removed_total

    def _open_llama_chat(self, body: dict, timeout: int, accept: str):
        """Open a llama-server chat response, retrying text-only models.

        This runs in a worker thread. Opening the stream here (rather than
        inside the StreamingResponse generator) means upstream failures still
        reach the client as a proper JSON HTTP error instead of a bare 500.
        """
        port = self.get_running_port()
        url = f"http://127.0.0.1:{port}/v1/chat/completions"

        def _request(payload: dict):
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": accept},
                method="POST",
            )
            return urllib.request.urlopen(request, timeout=timeout)

        try:
            return _request(body), body
        except urllib.error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="ignore")
            exc.close()
            detail = self._llama_error_detail(raw_error)

            retry_body, removed = None, 0
            if self._is_vision_input_unsupported(detail):
                retry_body, removed = self._strip_vision_parts(body)

            if retry_body is not None and removed:
                logger.info(
                    "Local model does not support image input; retrying "
                    "without %s image part(s).",
                    removed,
                )
                try:
                    return _request(retry_body), retry_body
                except urllib.error.HTTPError as retry_exc:
                    retry_raw = retry_exc.read().decode("utf-8", errors="ignore")
                    retry_exc.close()
                    retry_detail = self._llama_error_detail(retry_raw)
                    logger.error(
                        "llama-server retry without images failed HTTP %s: %s",
                        retry_exc.code,
                        retry_detail,
                    )
                    raise HTTPException(status_code=retry_exc.code, detail=retry_detail)
                except Exception as retry_exc:
                    logger.error(
                        "Failed to open llama-server text-only stream: %s",
                        retry_exc,
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=(f"Could not reach the local AI engine. {retry_exc}"),
                    )

            logger.error("llama-server returned HTTP %s: %s", exc.code, detail)
            raise HTTPException(status_code=exc.code, detail=detail)
        except Exception as exc:
            logger.error("Failed to communicate with llama-server: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach the local AI engine. {exc}",
            )

    async def proxy_sync_chat(self, body: dict) -> dict:
        self._last_request_time = time.time()
        timeout = int(self._read_config().get("request_timeout_seconds", 300))
        loop = asyncio.get_running_loop()
        response, _ = await loop.run_in_executor(
            None, self._open_llama_chat, body, timeout, "application/json"
        )

        def _read_response():
            try:
                return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                logger.error("Invalid response from llama-server: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="The local AI engine returned an invalid response.",
                )
            finally:
                response.close()

        result = await loop.run_in_executor(None, _read_response)
        self._last_request_time = time.time()
        return result

    async def proxy_stream_chat(self, body: dict) -> AsyncGenerator[bytes, None]:
        self._last_request_time = time.time()
        timeout = int(self._read_config().get("request_timeout_seconds", 300))
        loop = asyncio.get_running_loop()
        response, _ = await loop.run_in_executor(
            None, self._open_llama_chat, body, timeout, "text/event-stream"
        )

        async def _iter_response():
            try:
                while True:
                    line = await loop.run_in_executor(None, response.readline)
                    if not line:
                        break
                    self._last_request_time = time.time()
                    yield line
            finally:
                response.close()

        return _iter_response()


ai_service = AiService()
