#!/usr/bin/env python3
"""
PCLink Universal Release Manager

This script consolidates the release process by:
1. Performing safety checks (clean git status).
2. Prompting for a new version number.
3. Calling the version_updater.py script.
4. Moving changelog entries from RELEASE_NOTES.md to CHANGELOG.md.
5. Committing, tagging, and pushing the new version to GitHub.
6. Creating a GitHub release (stable or beta/pre-release).
"""

import argparse
import json
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
    """Update CHANGELOG.md with content from RELEASE_NOTES.md"""
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
        release_notes_content = release_notes_file.read_text(encoding="utf-8").strip()
        
        if not release_notes_content:
            print_color("Warning: RELEASE_NOTES.md is empty.", Colors.WARNING)
            release_notes_content = "- No changes documented"
    else:
        print_color(f"Error: {release_notes_file} not found. Please create it with your release notes.", Colors.FAIL)
        sys.exit(1)

    # Find where to insert the new version (after the header, before first version entry)
    # Look for the first version entry pattern: ## [X.Y.Z]
    version_pattern = r'\n## \[\d+\.\d+\.\d+[^\]]*\]'
    match = re.search(version_pattern, content)
    
    if match:
        # Insert before the first version entry
        insert_pos = match.start()
        header_part = content[:insert_pos]
        rest_of_changelog = content[insert_pos:]
    else:
        # No existing versions, append after header
        header_part = content.rstrip()
        rest_of_changelog = ""

    # Create the new version section
    today = datetime.now().strftime("%Y-%m-%d")
    new_version_section = f"\n## [{version}] - {today}\n\n{release_notes_content}\n"
    
    # Reconstruct the changelog
    new_content = f"{header_part}{new_version_section}{rest_of_changelog}"
    
    # Write the updated changelog
    changelog_file.write_text(new_content, encoding="utf-8")
    print_color(f"✓ Updated CHANGELOG.md with version {version}.", Colors.OKGREEN)
    
    # Empty RELEASE_NOTES.md for the next version
    try:
        release_notes_file.write_text("", encoding="utf-8")
        print_color(f"✓ Emptied {release_notes_file} for next version.", Colors.OKGREEN)
    except Exception as e:
        print_color(f"Warning: Could not empty {release_notes_file}: {e}", Colors.WARNING)
    
    return release_notes_content

def create_github_release(version, release_notes, is_beta=False):
    """Create a GitHub release using the GitHub CLI"""
    print_color("\nCreating GitHub release...", Colors.BOLD)
    
    tag = f"v{version}"
    title = f"PCLink {version}"
    if is_beta:
        title += " (Beta)"
    
    # Check if gh CLI is available
    try:
        subprocess.run(['gh', '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print_color("Warning: GitHub CLI (gh) not found. Skipping GitHub release creation.", Colors.WARNING)
        print_color("Install it from: https://cli.github.com/", Colors.OKCYAN)
        return
    
    # Create release command
    cmd = ['gh', 'release', 'create', tag, '--title', title, '--notes', release_notes]
    
    if is_beta:
        cmd.append('--prerelease')
    else:
        cmd.append('--latest')
    
    try:
        run_command(cmd)
        print_color(f"✓ Created GitHub release: {title}", Colors.OKGREEN)
        if is_beta:
            print_color("  Marked as pre-release (beta)", Colors.OKCYAN)
        else:
            print_color("  Marked as latest stable release", Colors.OKCYAN)
    except Exception as e:
        print_color(f"Warning: Failed to create GitHub release: {e}", Colors.WARNING)
        print_color("You can create it manually on GitHub.", Colors.OKCYAN)

def main():
    parser = argparse.ArgumentParser(description="PCLink Release Manager")
    parser.add_argument("--force", action="store_true", help="Skip safety checks.")
    parser.add_argument("--version", help="Specify version number directly (e.g., 1.2.0 or 1.2.0-beta.1).")
    parser.add_argument("--beta", action="store_true", help="Mark this as a beta/pre-release.")
    args = parser.parse_args()
    
    os.chdir(Path(__file__).resolve().parent.parent)
    
    print_color("--- PCLink Universal Release Manager ---", Colors.HEADER)

    if not args.force:
        print_color("\n[1/6] Performing safety checks...", Colors.BOLD)
        if run_command(['git', 'status', '--porcelain'], capture_output=True).stdout:
            print_color("Warning: Your working directory is not clean.", Colors.WARNING)
            if input("Continue anyway? (y/n): ").lower() != 'y': sys.exit("Release cancelled.")
        else: print_color("✓ Git working directory is clean.", Colors.OKGREEN)
    
    print_color("\n[2/6] Determining version number...", Colors.BOLD)
    version = args.version
    is_beta = args.beta
    
    if not version:
        while True:
            new_version = input("Enter new version (e.g., 1.0.0 or 1.0.0-beta.1): ")
            if re.match(r"^\d+\.\d+\.\d+(-[\w.-]+)?$", new_version):
                version = new_version
                # Auto-detect beta from version string
                if '-beta' in version.lower() or '-alpha' in version.lower() or '-rc' in version.lower():
                    is_beta = True
                break
            else: print_color("Invalid format. Use Semantic Versioning (X.Y.Z or X.Y.Z-beta.1).", Colors.FAIL)
    else:
        # Auto-detect beta from version string if not explicitly set
        if not is_beta and ('-beta' in version.lower() or '-alpha' in version.lower() or '-rc' in version.lower()):
            is_beta = True
    
    tag = f"v{version}"
    release_type = "BETA" if is_beta else "STABLE"
    print_color(f"✓ Version set to {version} (tag: {tag}, type: {release_type})", Colors.OKGREEN)

    print_color("\n[3/6] Updating version in files...", Colors.BOLD)
    run_command([sys.executable, "scripts/version_updater.py", version])
    
    print_color("\n[4/6] Updating changelog...", Colors.BOLD)
    release_notes_file = Path("RELEASE_NOTES.md")
    if not release_notes_file.exists():
        print_color(f"Error: {release_notes_file} not found.", Colors.FAIL)
        print_color("Please create RELEASE_NOTES.md with your release notes.", Colors.FAIL)
        sys.exit(1)
    
    release_notes_content = update_changelog(version)

    print_color("\n[5/6] Review and Confirm...", Colors.BOLD)
    print("The script will now perform the following actions:")
    print(f"  1. Commit changes with message: {Colors.OKCYAN}Bump version to {version}{Colors.ENDC}")
    print(f"  2. Create Git tag: {Colors.OKCYAN}{tag}{Colors.ENDC}")
    print("  3. Push commit and tag to 'origin'.")
    print(f"  4. Create GitHub release ({Colors.OKCYAN}{'pre-release/beta' if is_beta else 'latest stable'}{Colors.ENDC})")

    if not args.force and input(f"\n{Colors.WARNING}Proceed? (y/n): {Colors.ENDC}").lower() != 'y':
        sys.exit("Release cancelled.")

    print_color("\n[6/6] Executing release commands...", Colors.BOLD)
    run_command(['git', 'add', '.'])
    run_command(['git', 'commit', '-m', f"Bump version to {version}"], allow_errors=True)
    run_command(['git', 'tag', '-a', tag, '-m', f"Release {version}"])
    run_command(['git', 'push', 'origin', 'HEAD'])
    run_command(['git', 'push', 'origin', tag])
    
    # Create GitHub release
    create_github_release(version, release_notes_content, is_beta)
    
    print_color("\n--- Release Process Complete! ---", Colors.HEADER)
    print_color("✓ Successfully pushed commit and tag to GitHub.", Colors.OKGREEN)
    if is_beta:
        print_color("✓ Created beta/pre-release on GitHub.", Colors.OKGREEN)
    else:
        print_color("✓ Created stable release on GitHub (marked as latest).", Colors.OKGREEN)
    print("The GitHub Actions workflow will now build and publish the official release artifacts.")

if __name__ == "__main__":
    main()