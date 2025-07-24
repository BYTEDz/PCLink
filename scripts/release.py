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
    if not changelog_file.exists():
        print_color(f"Error: {changelog_file} not found in project root.", Colors.FAIL)
        sys.exit(1)

    content = changelog_file.read_text(encoding="utf-8")
    if f"## [{version}]" in content:
        print_color(f"Warning: Version {version} already in changelog. Skipping.", Colors.WARNING)
        return

    unreleased_header = "## [Unreleased]"
    if unreleased_header not in content:
        print_color(f"Error: Could not find '{unreleased_header}' section.", Colors.FAIL)
        sys.exit(1)

    parts = content.split(unreleased_header, 1)
    header_part = parts[0]
    unreleased_and_rest = parts[1]

    if "\n## [" in unreleased_and_rest:
        unreleased_content = unreleased_and_rest.split("\n## [", 1)[0].strip()
        rest_of_changelog = "\n## [" + unreleased_and_rest.split("\n## [", 1)[1]
    else:
        unreleased_content = unreleased_and_rest.strip()
        rest_of_changelog = ""

    if not unreleased_content:
        print_color("Warning: 'Unreleased' section is empty.", Colors.WARNING)

    today = datetime.now().strftime("%Y-%m-%d")
    new_version_section = f"## [{version}] - {today}\n\n{unreleased_content}"
    new_content = f"{header_part}{unreleased_header}\n\n\n{new_version_section}{rest_of_changelog}"
    
    changelog_file.write_text(new_content, encoding="utf-8")
    print_color(f"✓ Updated changelog with version {version} and reset [Unreleased] section.", Colors.OKGREEN)

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