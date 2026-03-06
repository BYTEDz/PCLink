# Maintainer: AZHAR ZOUHIR <support@bytedz.com>
pkgname=pclink
pkgver=3.5.0
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
source=("https://github.com/BYTEDz/PCLink/archive/refs/tags/v${pkgver}.tar.gz")
sha256sums=('SKIP') # User should update this with the real hash when releasing

build() {
    cd "PCLink-${pkgver}"
    python -m build --wheel --no-isolation
}

package() {
    cd "PCLink-${pkgver}"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Install systemd service template
    install -Dm644 scripts/linux/pclink.service.template "$pkgdir/usr/lib/systemd/user/pclink.service"
    
    # Install uinput rules
    install -Dm644 scripts/linux/99-uinput.rules "$pkgdir/usr/lib/udev/rules.d/99-uinput.rules"
}
