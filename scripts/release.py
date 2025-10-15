#!/usr/bin/env python3
"""
PCLink Universal Release Manager

This script consolidates the release process by:
1. Performing safety checks (clean git status).
2. Prompting for a new version number.
3. Calling the version_updater.py script.
4. Moving changelog entries from '[Unreleased]' to a new version block.
5. Committing, tagging, and pushing the new version to GitHub.
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

class Colors:
    HEADER = '\033[95m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_color(text, color):
    print(f"{color}{text}{Colors.ENDC}")

def extract_release_notes_content(raw_content):
    """Extract actual release notes content from RELEASE_NOTES.md, skipping template parts."""
    lines = raw_content.split('\n')
    content_lines = []
    skip_template_header = True
    
    for line in lines:
        # Skip template header and instructions
        if skip_template_header:
            if line.startswith('# Release Notes Template') or \
               'This file contains the release notes' in line or \
               'When you run `scripts/release.py`' in line or \
               line.strip() == '':
                continue
            # Once we hit "## What's New" or similar, start collecting
            if line.startswith('## '):
                skip_template_header = False
                # Don't include the "## What's New" header itself
                continue
        
        # Collect all content after template header
        if not skip_template_header:
            # Skip completely empty template entries (just "- " with nothing after)
            if line.strip() == '-':
                continue
            content_lines.append(line)
    
    # Clean up the result
    result = '\n'.join(content_lines).strip()
    
    # If result is empty or only contains template placeholders, return empty
    if not result or result.count('-') == result.count('\n') + 1:  # Only bullet points with no content
        return ""
    
    return result

def run_command(command, capture_output=False, allow_errors=False):
    try:
        print_color(f"\n> {' '.join(command)}", Colors.OKCYAN)
        result = subprocess.run(
            command, check=not allow_errors, text=True,
            capture_output=capture_output, encoding='utf-8'
        )
        return result
    except FileNotFoundError:
        print_color(f"Error: Command '{command[0]}' not found.", Colors.FAIL)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print_color(f"Error executing command: {' '.join(command)}", Colors.FAIL)
        print(e.stderr or e.stdout)
        sys.exit(1)

def update_changelog(version):
    print_color("\nUpdating CHANGELOG.md...", Colors.BOLD)
    changelog_file = Path("CHANGELOG.md")
    release_notes_file = Path("RELEASE_NOTES.md")
    
    if not changelog_file.exists():
        print_color(f"Error: {changelog_file} not found in project root.", Colors.FAIL)
        sys.exit(1)

    # Check if version already exists in changelog
    content = changelog_file.read_text(encoding="utf-8")
    if f"## [{version}]" in content:
        print_color(f"Warning: Version {version} already in changelog. Skipping.", Colors.WARNING)
        return

    # Get release notes content
    release_notes_content = ""
    if release_notes_file.exists():
        print_color(f"✓ Found {release_notes_file}, using it for release notes.", Colors.OKGREEN)
        raw_content = release_notes_file.read_text(encoding="utf-8").strip()
        
        # Extract only the actual release notes content
        release_notes_content = extract_release_notes_content(raw_content)
        
        if not release_notes_content:
            print_color("Warning: No actual release notes found in RELEASE_NOTES.md (only template content).", Colors.WARNING)
            release_notes_content = "- No changes documented"
    else:
        print_color(f"No {release_notes_file} found, checking [Unreleased] section...", Colors.WARNING)
        
        # Fallback to using [Unreleased] section
        unreleased_header = "## [Unreleased]"
        if unreleased_header not in content:
            print_color(f"Error: Could not find '{unreleased_header}' section and no RELEASE_NOTES.md found.", Colors.FAIL)
            sys.exit(1)

        parts = content.split(unreleased_header, 1)
        unreleased_and_rest = parts[1]

        if "\n## [" in unreleased_and_rest:
            release_notes_content = unreleased_and_rest.split("\n## [", 1)[0].strip()
        else:
            release_notes_content = unreleased_and_rest.strip()

    if not release_notes_content:
        print_color("Warning: No release notes content found.", Colors.WARNING)
        release_notes_content = "- No changes documented"

    # Find the [Unreleased] section
    unreleased_header = "## [Unreleased]"
    if unreleased_header not in content:
        print_color(f"Error: Could not find '{unreleased_header}' section in CHANGELOG.md.", Colors.FAIL)
        sys.exit(1)

    # Split the changelog content
    parts = content.split(unreleased_header, 1)
    header_part = parts[0]
    unreleased_and_rest = parts[1]

    # Find where the rest of the changelog starts (after [Unreleased] section)
    if "\n## [" in unreleased_and_rest:
        rest_of_changelog = "\n## [" + unreleased_and_rest.split("\n## [", 1)[1]
    else:
        rest_of_changelog = ""

    # Create the new version section
    today = datetime.now().strftime("%Y-%m-%d")
    new_version_section = f"## [{version}] - {today}\n\n{release_notes_content}"
    
    # Reconstruct the changelog WITHOUT the [Unreleased] section
    new_content = f"{header_part}{new_version_section}{rest_of_changelog}"
    
    # Write the updated changelog
    changelog_file.write_text(new_content, encoding="utf-8")
    print_color(f"✓ Updated changelog with version {version} and removed [Unreleased] section.", Colors.OKGREEN)
    
    # Handle RELEASE_NOTES.md after processing
    if release_notes_file.exists():
        try:
            # Create a new empty RELEASE_NOTES.md for the next version
            new_release_notes_content = """# Release Notes Template

This file contains the release notes for the next version. When you run `scripts/release.py`, the content below will be moved to `CHANGELOG.md` under the new version section.

## What's New

### ✅ Added
- 

### 🔄 Changed
- 

### 🐛 Fixed
- 

### ❌ Removed
- 

### 🔒 Security
- 
"""
            release_notes_file.write_text(new_release_notes_content, encoding="utf-8")
            print_color(f"✓ Reset {release_notes_file} with template for next version.", Colors.OKGREEN)
        except Exception as e:
            print_color(f"Warning: Could not reset {release_notes_file}: {e}", Colors.WARNING)

def main():
    parser = argparse.ArgumentParser(description="PCLink Release Manager")
    parser.add_argument("--force", action="store_true", help="Skip safety checks.")
    parser.add_argument("--version", help="Specify version number directly.")
    args = parser.parse_args()
    
    os.chdir(Path(__file__).resolve().parent.parent)
    
    print_color("--- PCLink Universal Release Manager ---", Colors.HEADER)

    if not args.force:
        print_color("\n[1/5] Performing safety checks...", Colors.BOLD)
        if run_command(['git', 'status', '--porcelain'], capture_output=True).stdout:
            print_color("Warning: Your working directory is not clean.", Colors.WARNING)
            if input("Continue anyway? (y/n): ").lower() != 'y': sys.exit("Release cancelled.")
        else: print_color("✓ Git working directory is clean.", Colors.OKGREEN)
    
    print_color("\n[2/5] Determining version number...", Colors.BOLD)
    version = args.version
    if not version:
        while True:
            new_version = input("Enter new version (e.g., 1.0.0): ")
            if re.match(r"^\d+\.\d+\.\d+(-[\w.-]+)?$", new_version):
                version = new_version
                break
            else: print_color("Invalid format. Use Semantic Versioning (X.Y.Z).", Colors.FAIL)
    
    tag = f"v{version}"
    print_color(f"✓ Version set to {version} (tag will be {tag}).", Colors.OKGREEN)

    print_color("\n[3/5] Updating version in files...", Colors.BOLD)
    run_command([sys.executable, "scripts/version_updater.py", version])
    
    print_color("\n[4/5] Updating changelog...", Colors.BOLD)
    release_notes_file = Path("RELEASE_NOTES.md")
    if release_notes_file.exists():
        print_color("✓ Found RELEASE_NOTES.md - will use it for this release.", Colors.OKGREEN)
        print_color("  After release, RELEASE_NOTES.md will be reset with template for next version.", Colors.OKCYAN)
    else:
        print_color("ℹ  No RELEASE_NOTES.md found - will use [Unreleased] section from CHANGELOG.md.", Colors.WARNING)
        print_color("  A new RELEASE_NOTES.md template will be created for future releases.", Colors.OKCYAN)
    
    update_changelog(version)

    print_color("\n[5/5] Review and Confirm...", Colors.BOLD)
    print("The script will now perform the following actions:")
    print(f"  1. Commit changes with message: {Colors.OKCYAN}Bump version to {version}{Colors.ENDC}")
    print(f"  2. Create Git tag: {Colors.OKCYAN}{tag}{Colors.ENDC}")
    print("  3. Push commit and tag to 'origin'.")

    if not args.force and input(f"\n{Colors.WARNING}Proceed? (y/n): {Colors.ENDC}").lower() != 'y':
        sys.exit("Release cancelled.")

    print_color("\nExecuting release commands...", Colors.BOLD)
    run_command(['git', 'add', '.'])
    run_command(['git', 'commit', '-m', f"Bump version to {version}"], allow_errors=True)
    run_command(['git', 'tag', '-a', tag, '-m', f"Release {version}"])
    run_command(['git', 'push', 'origin', 'HEAD'])
    run_command(['git', 'push', 'origin', tag])
    
    print_color("\n--- Release Process Complete! ---", Colors.HEADER)
    print_color("✓ Successfully pushed commit and tag to GitHub.", Colors.OKGREEN)
    print("The GitHub Actions workflow will now build and publish the official release artifacts.")

if __name__ == "__main__":
    main()