#!/usr/bin/env python3
"""
Convert PNG tray icons to ICO format for Windows.
"""

from PIL import Image
from pathlib import Path

def main():
    # Get project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    assets_dir = project_root / "src" / "pclink" / "assets"
    
    print("Converting PNG tray icons to ICO format...")
    print("=" * 50)
    
    # Convert pclink_light.png to ICO
    light_png = assets_dir / "pclink_light.png"
    if light_png.exists():
        try:
            img = Image.open(light_png)
            ico_path = assets_dir / "pclink_light.ico"
            img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
            print(f"✓ Created: pclink_light.ico")
        except Exception as e:
            print(f"✗ Error creating pclink_light.ico: {e}")
    else:
        print(f"✗ pclink_light.png not found")
    
    # Convert pclink_dark.png to ICO
    dark_png = assets_dir / "pclink_dark.png"
    if dark_png.exists():
        try:
            img = Image.open(dark_png)
            ico_path = assets_dir / "pclink_dark.ico"
            img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
            print(f"✓ Created: pclink_dark.ico")
        except Exception as e:
            print(f"✗ Error creating pclink_dark.ico: {e}")
    else:
        print(f"✗ pclink_dark.png not found")
    
    print("=" * 50)
    print("Done!")

if __name__ == "__main__":
    main()
