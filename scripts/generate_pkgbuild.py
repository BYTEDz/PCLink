#!/usr/bin/env python3
"""generates PKGBUILD for arch linux from project metadata."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    from pclink.core.version import version_info

    VERSION = version_info.version
    PKGVER = VERSION.replace("-", "_")
except ImportError:
    VERSION = "0.0.0"
    PKGVER = "0.0.0"

PKGBUILD_TEMPLATE = """# Maintainer: AZHAR ZOUHIR <support@bytedz.com>
# Co-maintainer: Mark Wagie <mark dot wagie at proton dot me>
pkgname=pclink
_app_id=xyz.bytedz.PCLink
pkgver={pkgver}
pkgrel=1
pkgdesc="Desktop app for secure remote PC control and management"
arch=('any')
url="https://github.com/BYTEDz/PCLink"
license=('AGPL-3.0-or-later AND LicenseRef-custom')
depends=(
  'gtk3'
  'libayatana-appindicator'
  'libnotify'
  'playerctl'
  'python-click'
  'python-cryptography'
  'python-fastapi'
  'python-getmac'
  'python-gobject'
  'python-keyboard'
  'python-mss'
  'python-multipart'
  'python-packaging'
  'python-pefile'
  'python-pillow'
  'python-psutil'
  'python-pyautogui'
  'python-pydantic'
  'python-qrcode'
  'python-requests'
  'python-websockets'
  'python-wsproto'
  'python-yaml'
  'uvicorn'
  'xdg-desktop-portal'
)
makedepends=(
  'python-build'
  'python-installer'
  'python-setuptools'
  'python-wheel'
)
optdepends=(
  'grim: Screenshot support for wlroots-based compositors'
  'python-aiofiles: Improves upload performance with async file I/O'
  'python-pynput: Fallback for input control'
  'python-evdev: Input control on Wayland'
  'python-pyperclip: Fallback for clipboard support'
  'python-pystray: Fallback for system tray'
  'spectacle: Screenshot support on KDE Plasma'
  'wl-clipboard: Clipboard support on Wayland'
)
source=("PCLink-$pkgver.tar.gz::https://github.com/BYTEDz/PCLink/archive/refs/tags/v{version}.tar.gz"
        "$pkgname.1::https://raw.githubusercontent.com/BYTEDz/PCLink/main/scripts/linux/pclink.1")
sha256sums=('{sha256}'
            'SKIP')

build() {{
  cd "PCLink-{version}"
  python -m build --wheel --no-isolation
}}

package() {{
  cd "PCLink-{version}"
  python -m installer --destdir="$pkgdir" dist/*.whl

  # Power management scripts
  install -Dm755 "scripts/linux/$pkgname-power-wrapper" -t "$pkgdir/usr/bin/"
  install -Dm755 scripts/linux/test-power-permissions -t "$pkgdir/usr/bin/"

  # Sudoers config for power management
  install -dm750 "$pkgdir/etc/sudoers.d/"
  install -m440 "scripts/linux/$pkgname-sudoers" "$pkgdir/etc/sudoers.d/$pkgname"

  # Systemd user service
  install -Dm644 "scripts/linux/$pkgname.service.template" \\
    "$pkgdir/usr/lib/systemd/user/$pkgname.service"

  # Udev rules for uinput access
  install -Dm644 scripts/linux/99-uinput.rules -t "$pkgdir/usr/lib/udev/rules.d/"

  # Desktop integration
  install -Dm644 "assets/${{pkgname}}_icon.svg" \\
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/${{_app_id}}.svg"
  install -Dm644 "${{_app_id}}.desktop" -t "$pkgdir/usr/share/applications/"

  # Man page
  install -Dm644 "$srcdir/$pkgname.1" -t "$pkgdir/usr/share/man/man1/"

  # License
  install -Dm644 LICENSE -t "$pkgdir/usr/share/licenses/$pkgname/"
}}
"""


def main():
    parser = argparse.ArgumentParser(description="Generate PKGBUILD for PCLink")
    parser.add_argument(
        "--sha256", default="SKIP", help="SHA256 hash of the source tarball"
    )
    parser.add_argument("--output", default="PKGBUILD", help="Output filename")
    args = parser.parse_args()

    content = PKGBUILD_TEMPLATE.format(
        version=VERSION, pkgver=PKGVER, sha256=args.sha256
    )

    output_path = Path(args.output)
    output_path.write_text(content, encoding="utf-8")
    print(f"[OK] Generated {args.output} for version {VERSION}")


if __name__ == "__main__":
    main()
