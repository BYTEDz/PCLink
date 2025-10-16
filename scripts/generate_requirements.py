#!/usr/bin/env python3
"""
Generate requirements.txt by scanning actual imports in the codebase.
This ensures all dependencies are captured and no missing imports.
"""
import ast
import sys
from pathlib import Path
from typing import Set, Dict, List

# Known standard library modules (Python 3.8+)
STDLIB_MODULES = {
    'os', 'sys', 'json', 'time', 'datetime', 'pathlib', 'subprocess', 'threading',
    'asyncio', 'logging', 'argparse', 'configparser', 'urllib', 'http', 'socket',
    'ssl', 'hashlib', 'base64', 'uuid', 'tempfile', 'shutil', 'glob', 're',
    'collections', 'itertools', 'functools', 'operator', 'typing', 'dataclasses',
    'enum', 'abc', 'contextlib', 'weakref', 'copy', 'pickle', 'platform',
    'signal', 'atexit', 'traceback', 'warnings', 'inspect', 'importlib',
    'pkgutil', 'zipfile', 'tarfile', 'gzip', 'io', 'struct', 'array', 'math',
    'random', 'statistics', 'decimal', 'fractions', 'cmath', 'string', 'textwrap',
    'unicodedata', 'codecs', 'locale', 'calendar', 'email', 'mimetypes',
    'html', 'xml', 'csv', 'sqlite3', 'dbm', 'zlib', 'bz2', 'lzma', 'zipapp',
    'concurrent', 'multiprocessing', 'queue', 'sched', 'select', 'selectors',
    'asynchat', 'asyncore', 'socketserver', 'xmlrpc', 'ipaddress', 'getpass',
    'getopt', 'readline', 'rlcompleter', 'cmd', 'shlex', 'pprint', 'reprlib',
    'difflib', 'heapq', 'bisect', 'graphlib', 'secrets', 'hmac', 'binascii',
    'quopri', 'uu', 'binhex', 'encodings', 'stringprep', 'unicodedata2',
    'test', 'unittest', 'doctest', 'pdb', 'profile', 'pstats', 'timeit',
    'trace', 'gc', 'dis', 'pickletools', 'formatter', 'parser', 'symbol',
    'token', 'keyword', 'tokenize', 'tabnanny', 'py_compile', 'compileall',
    'modulefinder', 'runpy', 'importlib_metadata', 'site', 'user', 'builtins'
}

# Map import names to PyPI package names
PACKAGE_MAPPING = {

    'cv2': 'opencv-python',
    'sklearn': 'scikit-learn',
    'yaml': 'PyYAML',
    'dateutil': 'python-dateutil',
    'serial': 'pyserial',
    'usb': 'pyusb',
    'bluetooth': 'pybluez',
    'win32api': 'pywin32',
    'win32con': 'pywin32',
    'win32gui': 'pywin32',
    'win32process': 'pywin32',
    'win32security': 'pywin32',
    'win32event': 'pywin32',
    'win32file': 'pywin32',
    'win32com': 'pywin32',
    'pythoncom': 'pywin32',
    'pywintypes': 'pywin32',
    'gi': 'PyGObject',
}

# Version constraints for known packages
VERSION_CONSTRAINTS = {
    'fastapi': '>=0.95.0',
    'uvicorn': '[standard]>=0.22.0',
    'psutil': '>=5.9.0',
    'cryptography': '>=41.0.0',
    'requests': '>=2.31.0',

    'pyautogui': '>=0.9.54',
    'keyboard': '>=0.13.5',
    'pyperclip': '>=1.8.2',
    'mss': '>=9.0.0',
    'pystray': '>=0.19.0',
    'websockets': '>=12.0',
    'wsproto': '>=1.2.0',
    'getmac': '>=0.9.0',
    'pynput': '>=1.7.6',
    'packaging': '>=21.0',
    'pywin32': '>=306',
    'pycaw': '>=20230330',
    'comtypes': '>=1.2.0',
    'PyGObject': '>=3.42.0',
}

# Platform-specific packages
PLATFORM_PACKAGES = {
    'pywin32': 'sys_platform == "win32"',
    'pycaw': 'sys_platform == "win32"',
    'comtypes': 'sys_platform == "win32"',
    'PyGObject': 'sys_platform == "linux"',
}

class ImportVisitor(ast.NodeVisitor):
    """AST visitor to extract import statements."""
    
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
    """Extract imports from a Python file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        visitor = ImportVisitor()
        visitor.visit(tree)
        return visitor.imports
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}")
        return set()

def scan_project_imports(src_dir: Path) -> Set[str]:
    """Scan all Python files in the project for imports."""
    all_imports = set()
    
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        imports = extract_imports_from_file(py_file)
        all_imports.update(imports)
    
    return all_imports

def filter_third_party_packages(imports: Set[str]) -> Set[str]:
    """Filter out standard library modules and local imports."""
    third_party = set()
    
    # Known local modules to exclude
    local_modules = {
        'pclink', 'scripts', 'api_server', 'core', 'web_ui', 'headless',
        'config', 'constants', 'device_manager', 'exceptions', 'file_browser',
        'info_router', 'input_router', 'main', 'media_router', 'process_manager',
        'web_auth', 'PIL',
        'services', 'state', 'system_router', 'terminal', 'utils', 'utils_router',
        'version'
    }
    
    # Platform-specific standard library modules
    platform_stdlib = {
        'ctypes', 'fcntl', 'grp', 'pty', 'pwd', 'winreg', 'winsdk', 'win32ui',
        'webbrowser'
    }
    
    for imp in imports:
        # Skip standard library modules
        if imp in STDLIB_MODULES or imp in platform_stdlib:
            continue
            
        # Skip local project imports
        if imp in local_modules:
            continue
            
        # Skip relative imports
        if imp.startswith('.'):
            continue
            
        third_party.add(imp)
    
    return third_party

def map_to_package_names(imports: Set[str]) -> Dict[str, str]:
    """Map import names to PyPI package names."""
    packages = {}
    
    for imp in imports:
        package_name = PACKAGE_MAPPING.get(imp, imp)
        packages[package_name] = imp
    
    return packages

def generate_requirements(packages: Dict[str, str]) -> List[str]:
    """Generate requirements.txt content."""
    requirements = []
    
    # Add header
    requirements.extend([
        "# filename: requirements.txt",
        "# PCLink Dependencies - Auto-generated",
        "# Generated by scripts/generate_requirements.py",
        "",
    ])
    
    # Group packages by category
    core_api = []
    system_control = []

    security_networking = []
    cross_platform = []
    platform_specific = []
    
    for package, import_name in sorted(packages.items()):
        version = VERSION_CONSTRAINTS.get(package, "")
        platform_marker = PLATFORM_PACKAGES.get(package, "")
        
        req_line = package + version
        if platform_marker:
            req_line += f"; {platform_marker}"
        
        # Categorize packages
        if package in ['fastapi', 'uvicorn', 'websockets', 'wsproto']:
            core_api.append(req_line)
        elif package in ['psutil', 'pyperclip', 'mss', 'keyboard', 'pyautogui', 'pynput']:
            system_control.append(req_line)

        elif package in ['cryptography', 'requests', 'getmac']:
            security_networking.append(req_line)
        elif package in ['pystray']:
            cross_platform.append(req_line)
        elif platform_marker:
            platform_specific.append(req_line)
        else:
            # Uncategorized - add to system control
            system_control.append(req_line)
    
    # Add missing packages that might not be directly imported but are needed
    missing_packages = {
        'websockets': '>=12.0',
        'wsproto': '>=1.2.0', 

        'pyautogui': '>=0.9.54'
    }
    
    for pkg, version in missing_packages.items():
        if pkg not in [p.split('>=')[0].split('[')[0] for p in core_api + system_control + security_networking]:
            if pkg in ['websockets', 'wsproto']:
                core_api.append(f"{pkg}{version}")

            elif pkg in ['pyautogui']:
                system_control.append(f"{pkg}{version}")
    
    # Add categorized requirements
    if core_api:
        requirements.extend(["# Core API and Web Server"] + sorted(core_api) + [""])
    
    if system_control:
        requirements.extend(["# System Information and Control"] + sorted(system_control) + [""])
    

    
    if security_networking:
        requirements.extend(["# Security and Networking"] + sorted(security_networking) + [""])
    
    if cross_platform:
        requirements.extend(["# Cross-platform System Tray"] + sorted(cross_platform) + [""])
    
    if platform_specific:
        requirements.extend(["# Platform-specific dependencies"] + sorted(platform_specific) + [""])
    
    return requirements

def main():
    """Main function to generate requirements.txt."""
    root_dir = Path(__file__).parent.parent
    src_dir = root_dir / "src"
    requirements_file = root_dir / "requirements.txt"
    
    print("Scanning project for imports...")
    
    # Extract all imports
    all_imports = scan_project_imports(src_dir)
    print(f"Found {len(all_imports)} total imports")
    
    # Filter to third-party packages
    third_party = filter_third_party_packages(all_imports)
    print(f"Found {len(third_party)} third-party packages: {sorted(third_party)}")
    
    # Map to package names
    packages = map_to_package_names(third_party)
    print(f"Mapped to {len(packages)} PyPI packages: {sorted(packages.keys())}")
    
    # Generate requirements
    requirements_content = generate_requirements(packages)
    
    # Write to file
    with open(requirements_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(requirements_content))
    
    print(f"Generated {requirements_file}")
    print("\nGenerated requirements.txt:")
    print("=" * 50)
    for line in requirements_content:
        print(line)

if __name__ == "__main__":
    main()