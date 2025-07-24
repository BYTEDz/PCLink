#!/usr.bin/env python3
"""
PCLink Icon Converter

This script converts the SVG icon to PNG and ICO formats required for the
application build. It uses pure Python libraries to avoid system dependencies.

Required packages:
- pillow
- svglib
- reportlab
"""

import sys
from pathlib import Path

try:
    from PIL import Image
    from reportlab.graphics import renderPM
    from svglib.svglib import svg2rlg
except ImportError:
    print("Error: Required packages not found.", file=sys.stderr)
    print("Please install them by running:", file=sys.stderr)
    print("pip install pillow svglib reportlab", file=sys.stderr)
    sys.exit(1)


def convert_svg_to_png(svg_path: Path, png_path: Path, size: int = 256):
    """Converts an SVG file to a PNG file using svglib and reportlab."""
    print(f"Converting {svg_path.name} to {png_path.name}...")
    drawing = svg2rlg(str(svg_path))

    # Calculate scale and apply it
    scale = size / max(drawing.width, drawing.height)
    drawing.width, drawing.height = drawing.width * scale, drawing.height * scale
    drawing.scale(scale, scale)

    renderPM.drawToFile(drawing, str(png_path), fmt="PNG", bg=0x00FFFFFF)
    print(f"Created {png_path}")


def convert_png_to_ico(png_path: Path, ico_path: Path):
    """Converts a PNG file to a multi-resolution ICO file."""
    print(f"Converting {png_path.name} to {ico_path.name}...")
    img = Image.open(png_path)
    icon_sizes = [
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    ]
    img.save(ico_path, format="ICO", sizes=icon_sizes)
    print(f"Created {ico_path}")


def main():
    """Finds icons and runs the conversion process."""
    # Get the project root directory (parent of scripts directory)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    assets_dir = project_root / "src" / "pclink" / "assets"
    assets_dir.mkdir(exist_ok=True)

    svg_path = assets_dir / "icon.svg"
    if not svg_path.exists():
        print(f"Warning: Source icon '{svg_path}' not found. Skipping icon conversion.", file=sys.stderr)
        return 0  # Return success to avoid failing the build
    
    # Check if PNG and ICO already exist and are newer than SVG
    png_path = assets_dir / "icon.png"
    ico_path = assets_dir / "icon.ico"
    
    if png_path.exists() and ico_path.exists():
        svg_mtime = svg_path.stat().st_mtime
        png_mtime = png_path.stat().st_mtime
        ico_mtime = ico_path.stat().st_mtime
        
        if svg_mtime < png_mtime and svg_mtime < ico_mtime:
            print("Icons are already up to date. Skipping conversion.")
            print(f"  SVG: {svg_path} (modified: {svg_mtime})")
            print(f"  PNG: {png_path} (modified: {png_mtime})")
            print(f"  ICO: {ico_path} (modified: {ico_mtime})")
            return 0

    try:
        print(f"Converting icons from {svg_path}")
        convert_svg_to_png(svg_path, png_path)
        convert_png_to_ico(png_path, ico_path)
        print("\n✅ Icon conversion completed successfully!")
        return 0
    except Exception as e:
        print(f"\n❌ An error occurred during icon conversion: {e}", file=sys.stderr)
        # Create placeholder icons if conversion fails
        try:
            if not png_path.exists():
                # Create a simple 256x256 black PNG if conversion fails
                from PIL import Image
                img = Image.new('RGB', (256, 256), color=(0, 0, 0))
                img.save(png_path)
                print(f"Created placeholder PNG at {png_path}")
            
            if not ico_path.exists():
                # Create a simple ICO from the PNG
                img = Image.open(png_path)
                img.save(ico_path, format="ICO", sizes=[(32, 32)])
                print(f"Created placeholder ICO at {ico_path}")
        except Exception as e2:
            print(f"Failed to create placeholder icons: {e2}")
        
        # Don't fail the build
        return 0


if __name__ == "__main__":
    main()