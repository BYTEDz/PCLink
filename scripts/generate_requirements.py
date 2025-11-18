#!/usr/bin/env python3
"""
Generates a requirements.txt file by statically analyzing project imports.
"""
import ast
from pathlib import Path
from typing import Dict, List, Set

# Known standard library modules to be ignored during the scan.
# This set is based on Python 3.8+ standard library.
STDLIB_MODULES = {
    'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio',
    'asyncore', 'atexit', 'audioop', 'base64', 'bdb', 'binascii', 'binhex',
    'bisect', 'builtins', 'bz2', 'calendar', 'cgi', 'cgitb', 'chunk', 'cmath',
    'cmd', 'code', 'codecs', 'codeop', 'collections', 'colorsys', 'compileall',
    'concurrent', 'configparser', 'contextlib', 'contextvars', 'copy',
    'copyreg', 'csv', 'ctypes', 'dataclasses', 'datetime', 'dbm', 'decimal',
    'difflib', 'dis', 'distutils', 'doctest', 'email', 'encodings', 'enum',
    'errno', 'faulthandler', 'fcntl', 'filecmp', 'fileinput', 'fnmatch',
    'formatter', 'fractions', 'ftplib', 'functools', 'gc', 'getopt', 'getpass',
    'gettext', 'glob', 'graphlib', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac',
    'html', 'http', 'idlelib', 'imaplib', 'imghdr', 'imp', 'importlib',
    'inspect', 'io', 'ipaddress', 'itertools', 'json', 'keyword', 'linecache',
    'locale', 'logging', 'lzma', 'mailbox', 'mailcap', 'marshal', 'math',
    'mimetypes', 'mmap', 'modulefinder', 'multiprocessing', 'netrc', 'nntplib',
    'numbers', 'operator', 'optparse', 'os', 'pathlib', 'pdb', 'pickle',
    'pickletools', 'pipes', 'pkgutil', 'platform', 'plistlib', 'poplib',
    'posix', 'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile',
    'pyclbr', 'pydoc', 'queue', 'quopri', 'random', 're', 'readline', 'reprlib',
    'resource', 'rlcompleter', 'runpy', 'sched', 'secrets', 'select',
    'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtpd',
    'smtplib', 'sndhdr', 'socket', 'socketserver', 'sqlite3', 'ssl',
    'stat', 'statistics', 'string', 'stringprep', 'struct', 'subprocess',
    'sunau', 'symbol', 'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny',
    'tarfile', 'telnetlib', 'tempfile', 'termios', 'textwrap', 'threading',
    'time', 'timeit', 'tkinter', 'token', 'tokenize', 'trace', 'traceback',
    'tracemalloc', 'tty', 'turtle', 'turtledemo', 'types', 'typing',
    'unicodedata', 'unittest', 'urllib', 'uu', 'uuid', 'venv', 'warnings',
    'wave', 'weakref', 'webbrowser', 'wsgiref', 'xdrlib', 'xml', 'xmlrpc',
    'zipapp', 'zipfile', 'zipimport', 'zlib'
}


# Maps non-standard import names to their corresponding PyPI package names.
PACKAGE_MAPPING = {
    'PIL': 'Pillow',
    'gi': 'PyGObject',
    'win32api': 'pywin32',
    'win32con': 'pywin32',
    'win32gui': 'pywin32',
    'win32process': 'pywin32',
    'win32security': 'pywin32',
    'win32event': 'pywin32',
    'win32file': 'pywin32',
    'win32com': 'pywin32',
    'pythoncom': 'pywin32',
}

# Defines version constraints for specific packages.
VERSION_CONSTRAINTS = {
    'fastapi': '>=0.95.0',
    'uvicorn': '[standard]>=0.22.0',
    'websockets': '>=12.0',
    'wsproto': '>=1.2.0',
    'Pillow': '>=9.0.0',
    'keyboard': '>=0.13.5',
    'mss': '>=9.0.0',
    'packaging': '>=21.0',
    'psutil': '>=5.9.0',
    'pyautogui': '>=0.9.54',
    'pynput': '>=1.7.6',
    'pyperclip': '>=1.8.2',
    'cryptography': '>=41.0.0',
    'getmac': '>=0.9.0',
    'requests': '>=2.31.0',
    'pystray': '>=0.19.0',
    'qrcode': '>=7.3',
    'pywin32': '>=306',
    'pycaw': '>=20230330',
    'comtypes': '>=1.2.0',
    'PyGObject': '>=3.42.0',
}

# Defines platform-specific markers for packages.
PLATFORM_PACKAGES = {
    'pywin32': 'sys_platform == "win32"',
    'pycaw': 'sys_platform == "win32"',
    'comtypes': 'sys_platform == "win32"',
    'PyGObject': 'sys_platform == "linux"',
}


class ImportVisitor(ast.NodeVisitor):
    """AST visitor to extract top-level import names."""
    
    def __init__(self):
        self.imports: Set[str] = set()
        
    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name.split('.')[0])
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.add(node.module.split('.')[0])
        self.generic_visit(node)


def extract_imports_from_file(file_path: Path) -> Set[str]:
    """Parses a Python file and extracts all unique top-level imports."""
    try:
        content = file_path.read_text(encoding='utf-8')
        tree = ast.parse(content)
        visitor = ImportVisitor()
        visitor.visit(tree)
        return visitor.imports
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}")
        return set()


def scan_project_imports(src_dir: Path) -> Set[str]:
    """Scans all Python files in the project directory for imports."""
    all_imports = set()
    for py_file in src_dir.rglob("*.py"):
        imports = extract_imports_from_file(py_file)
        all_imports.update(imports)
    return all_imports


def filter_third_party_packages(imports: Set[str]) -> Set[str]:
    """Filters a set of imports to exclude standard library and local modules."""
    third_party = set()
    local_modules = {'pclink', 'scripts'}
    
    for imp in imports:
        if imp in STDLIB_MODULES or imp in local_modules or imp.startswith('.'):
            continue
        third_party.add(imp)
    return third_party


def map_to_package_names(imports: Set[str]) -> Dict[str, str]:
    """Maps a set of import names to their canonical PyPI package names."""
    packages = {}
    for imp in imports:
        package_name = PACKAGE_MAPPING.get(imp, imp)
        packages[package_name] = imp
    return packages


def generate_requirements(packages: Dict[str, str]) -> List[str]:
    """Formats the final list of packages into requirements.txt content."""
    requirements = [
        "# PCLink Dependencies - Auto-generated",
        "# Generated by scripts/generate_requirements.py",
        "",
    ]
    
    core_api = []
    image_processing = []
    system_control = []
    security_networking = []
    cross_platform = []
    cli_utils = []
    platform_specific = []
    
    # This dictionary handles dependencies that are not directly imported
    # but are required, such as extras or transitive dependencies.
    missing_packages = {
        'aiofiles': '>=23.0.0', # Optional performance for FastAPI uploads
    }
    for pkg, version in missing_packages.items():
        packages.setdefault(pkg, 'implicit')

    for package, import_name in sorted(packages.items()):
        version = VERSION_CONSTRAINTS.get(package, "")
        platform_marker = PLATFORM_PACKAGES.get(package, "")
        
        req_line = f"{package}{version}"
        if platform_marker:
            req_line += f"; {platform_marker}"
        
        # Categorize packages based on their primary function.
        if package in ['fastapi', 'uvicorn', 'websockets', 'wsproto', 'aiofiles']:
            core_api.append(req_line)
        elif package in ['Pillow']:
            image_processing.append(req_line)
        elif package in ['psutil', 'pyperclip', 'mss', 'keyboard', 'pyautogui', 'pynput', 'pydantic', 'packaging']:
            system_control.append(req_line)
        elif package in ['cryptography', 'requests', 'getmac']:
            security_networking.append(req_line)
        elif package in ['pystray']:
            cross_platform.append(req_line)
        elif package in ['qrcode', 'click']:
            cli_utils.append(req_line)
        elif platform_marker:
            platform_specific.append(req_line)
        else:
            # Add any uncategorized packages to a general group.
            system_control.append(req_line)
    
    # Assemble the final requirements file content.
    if core_api:
        requirements.extend(["# Core API and Web Server"] + sorted(core_api) + [""])
    if image_processing:
        requirements.extend(["# Image Processing"] + sorted(image_processing) + [""])
    if system_control:
        requirements.extend(["# System Information and Control"] + sorted(system_control) + [""])
    if security_networking:
        requirements.extend(["# Security and Networking"] + sorted(security_networking) + [""])
    if cli_utils:
        requirements.extend(["# CLI and Utilities"] + sorted(cli_utils) + [""])
    if cross_platform:
        requirements.extend(["# Cross-platform System Tray"] + sorted(cross_platform) + [""])
    if platform_specific:
        requirements.extend(["# Platform-specific dependencies"] + sorted(platform_specific) + [""])
    
    return requirements


def main():
    """Scans the project, resolves dependencies, and writes requirements.txt."""
    root_dir = Path(__file__).parent.parent
    src_dir = root_dir / "src"
    requirements_file = root_dir / "requirements.txt"
    
    print("Scanning project for third-party imports...")
    all_imports = scan_project_imports(src_dir)
    third_party_imports = filter_third_party_packages(all_imports)
    packages = map_to_package_names(third_party_imports)
    
    print(f"Found {len(packages)} packages: {sorted(packages.keys())}")
    
    requirements_content = generate_requirements(packages)
    
    requirements_file.write_text('\n'.join(requirements_content))
    
    print(f"\nSuccessfully generated {requirements_file}")
    print("=" * 50)
    print('\n'.join(requirements_content))
    print("=" * 50)


if __name__ == "__main__":
    main()