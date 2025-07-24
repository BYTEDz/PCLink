#!/usr/bin/env python3
"""
Documentation Verification Script
Verifies that documentation files are properly formatted and assets are accessible.
"""

import os
import sys
from pathlib import Path

def check_file_exists(file_path: str, description: str) -> bool:
    """Check if a file exists and report the result."""
    if Path(file_path).exists():
        print(f"✓ {description}: {file_path}")
        return True
    else:
        print(f"✗ {description}: {file_path} (NOT FOUND)")
        return False

def check_svg_content(file_path: str, description: str) -> bool:
    """Check if SVG file contains proper copyright and is well-formed."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for copyright
        has_copyright = "Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz" in content
        
        # Check for proper SVG structure
        has_svg_tag = "<svg" in content and "</svg>" in content
        
        # Check for no Inkscape metadata
        has_inkscape = "inkscape:" in content or "sodipodi:" in content
        
        if has_copyright and has_svg_tag and not has_inkscape:
            print(f"✓ {description}: Properly formatted with copyright")
            return True
        else:
            issues = []
            if not has_copyright:
                issues.append("missing copyright")
            if not has_svg_tag:
                issues.append("invalid SVG structure")
            if has_inkscape:
                issues.append("contains Inkscape metadata")
            print(f"✗ {description}: Issues found - {', '.join(issues)}")
            return False
            
    except Exception as e:
        print(f"✗ {description}: Error reading file - {e}")
        return False

def main():
    """Main verification function."""
    print("PCLink Documentation Verification")
    print("=" * 40)
    
    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    all_good = True
    
    # Check main documentation files
    docs_files = [
        ("README.md", "Main README file"),
        ("CHANGELOG.md", "Changelog file"),
        ("CONTRIBUTING.md", "Contributing guidelines"),
        ("LICENSE", "License file"),
    ]
    
    print("\n📄 Documentation Files:")
    for file_path, description in docs_files:
        if not check_file_exists(file_path, description):
            all_good = False
    
    # Check assets directory and SVG files
    print("\n🎨 Asset Files:")
    assets_dir = "docs/assets"
    if not check_file_exists(assets_dir, "Assets directory"):
        all_good = False
    else:
        svg_files = [
            ("docs/assets/banner.svg", "Banner SVG"),
            ("docs/assets/pclink_icon.svg", "Icon SVG"),
        ]
        
        for file_path, description in svg_files:
            if check_file_exists(file_path, description):
                if not check_svg_content(file_path, description):
                    all_good = False
            else:
                all_good = False
    
    # Check that old SVG files are removed from root
    print("\n🧹 Cleanup Check:")
    old_files = [
        ("banner.svg", "Old banner SVG (should be removed)"),
        ("pclink_icon.svg", "Old icon SVG (should be removed)"),
    ]
    
    for file_path, description in old_files:
        if Path(file_path).exists():
            print(f"✗ {description}: Still exists in root directory")
            all_good = False
        else:
            print(f"✓ {description}: Properly removed from root")
    
    # Check README for proper asset references
    print("\n🔗 Asset References:")
    try:
        with open("README.md", 'r', encoding='utf-8') as f:
            readme_content = f.read()
        
        if "docs/assets/banner.svg" in readme_content:
            print("✓ README references banner.svg correctly")
        else:
            print("✗ README missing proper banner.svg reference")
            all_good = False
            
        if "docs/assets/pclink_icon.svg" in readme_content:
            print("✓ README references pclink_icon.svg correctly")
        else:
            print("✗ README missing proper pclink_icon.svg reference")
            all_good = False
            
    except Exception as e:
        print(f"✗ Error checking README references: {e}")
        all_good = False
    
    # Final result
    print("\n" + "=" * 40)
    if all_good:
        print("✅ All documentation checks passed!")
        return 0
    else:
        print("❌ Some documentation issues found. Please fix them.")
        return 1

if __name__ == "__main__":
    sys.exit(main())