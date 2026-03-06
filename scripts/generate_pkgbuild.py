#!/usr/bin/env python3
import sys
from pathlib import Path

# Add src to path for version info
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

try:
    from pclink.core.version import version_info
    VERSION = version_info.version
    # PKGBUILD version cannot have hyphens, must use underscores for Arch
    PKGVER = VERSION.replace('-', '_')
except ImportError:
    VERSION = "0.0.0"
    PKGVER = "0.0.0"

PKGBUILD_TEMPLATE = """# Maintainer: AZHAR ZOUHIR <support@bytedz.com>
pkgname=pclink
pkgver={pkgver}
pkgrel=1
pkgdesc="Cross-platform desktop app for secure remote PC control and management"
arch=('any')
url="https://github.com/BYTEDz/PCLink"
license=('AGPL3')
depends=(
    'python>=3.8'
    'python-fastapi'
    'python-uvicorn'
    'python-websockets'
    'python-wsproto'
    'python-psutil'
    'python-pyperclip'
    'python-mss'
    'python-keyboard'
    'python-requests'
    'python-cryptography'
    'python-getmac'
    'python-pyautogui'
    'python-pynput'
    'python-packaging'
    'python-yaml'
    'python-click'
    'python-qrcode'
    'python-aiofiles'
    'python-pillow'
    'python-pystray'
    'python-multipart'
    'python-evdev'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
    'python-wheel'
)
source=("https://github.com/BYTEDz/PCLink/archive/refs/tags/v{version}.tar.gz")
sha256sums=('{sha256}')

build() {{
    cd "PCLink-{version}"
    python -m build --wheel --no-isolation
}}

package() {{
    cd "PCLink-{version}"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Install systemd service template
    install -Dm644 scripts/linux/pclink.service.template "$pkgdir/usr/lib/systemd/user/pclink.service"
    
    # Install uinput rules
    install -Dm644 scripts/linux/99-uinput.rules "$pkgdir/usr/lib/udev/rules.d/99-uinput.rules"
}}
"""

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate PKGBUILD for PCLink")
    parser.add_argument("--sha256", default="SKIP", help="SHA256 hash of the source tarball")
    parser.add_argument("--output", default="PKGBUILD", help="Output filename")
    args = parser.parse_args()

    content = PKGBUILD_TEMPLATE.format(
        version=VERSION,
        pkgver=PKGVER,
        sha256=args.sha256
    )

    output_path = Path(args.output)
    output_path.write_text(content, encoding='utf-8')
    print(f"[OK] Generated {args.output} for version {VERSION}")

if __name__ == "__main__":
    main()
