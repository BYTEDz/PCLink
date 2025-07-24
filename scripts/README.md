# PCLink Scripts

This directory contains utility scripts for managing the PCLink project.

## Release Management

### `release.py`

The Universal Release Manager script that handles the entire release process:

- Updates version information in all relevant files
- Updates the CHANGELOG.md with release notes
- Creates Git commits and tags
- Pushes changes to GitHub
- Triggers GitHub Actions for automated builds

**Usage:**
```bash
# Interactive mode - prompts for version
python scripts/release.py

# Specify version directly
python scripts/release.py --version 1.2.3

# Force release (skip safety checks)
python scripts/release.py --force
```

**Features:**
- Automatic version updates across all project files
- Changelog management with date stamping
- Git tag creation and pushing
- Integration with GitHub Actions for automated builds
- Safety checks for clean working directory

## Build System

### `build.py`

Builds the PCLink application into distributable packages:

- Creates standalone executables using PyInstaller or Nuitka
- Packages the application with all dependencies
- Supports debug and release builds

**Usage:**
```bash
# Standard build
python scripts/build.py

# Debug build with console output
python scripts/build.py --debug

# Clean build (removes previous artifacts)
python scripts/build.py --no-clean

# Use specific builder
python scripts/build.py --builder nuitka
```

**Build Options:**
- `--debug`: Include debug information and console output
- `--no-clean`: Skip cleaning previous build artifacts
- `--builder`: Choose between `pyinstaller` (default) or `nuitka`
- `--no-onefile`: Build as directory instead of single executable

## Development Tools

### `version_updater.py`

Updates version strings across all project files:

- Updates `src/pclink/core/version.py`
- Updates `pyproject.toml`
- Maintains version consistency

**Usage:**
```bash
python scripts/version_updater.py 1.2.3
```

### `verify_docs.py`

Verifies documentation integrity and asset organization:

- Checks all documentation files exist
- Validates SVG assets have proper copyright
- Ensures old files are cleaned up
- Verifies asset references in README

**Usage:**
```bash
python scripts/verify_docs.py
```

**Checks:**
- Documentation files (README.md, CHANGELOG.md, etc.)
- Asset files in `docs/assets/` directory
- SVG copyright and metadata cleanup
- Proper asset references in documentation
- Cleanup of old files from project root

## File Organization

```
scripts/
├── build.py              # Build system
├── release.py            # Release management
├── version_updater.py    # Version string updates
├── verify_docs.py        # Documentation verification
└── README.md            # This file
```

## Integration with GitHub Actions

The scripts are designed to work seamlessly with GitHub Actions:

1. **Local Development**: Use `build.py` for testing builds
2. **Release Process**: Use `release.py` to create releases
3. **Automated Builds**: GitHub Actions automatically builds all platforms
4. **Documentation**: Use `verify_docs.py` to ensure docs are properly formatted

## Dependencies

All scripts use only Python standard library and project dependencies. No additional tools required for basic functionality.

**Note**: PyInstaller spec files are automatically generated in the `build/` directory to avoid cluttering the project root and triggering Git tracking.

## Asset Management

### `convert_icons.py`

Converts the SVG icon to PNG and ICO formats required for the application build:

- Generates icon.png and icon.ico from icon.svg
- Creates multi-resolution ICO file for Windows

**Usage:**
```bash
python scripts/convert_icons.py
```

## Legacy Scripts

### `version_updater.py`

**Note:** This script is now integrated into `release.py` and is kept for backward compatibility.

Updates version information in source files:

- Updates version in `src/pclink/core/version.py`
- Updates version in `pyproject.toml`
- Updates CHANGELOG.md

**Usage:**
```bash
python scripts/version_updater.py 1.2.3
```

## Development Scripts

### `run_pclink.py` (in project root)

A convenience script for running PCLink directly from the source code:

- Adds the src directory to the Python path
- Imports and runs the main function from pclink

**Usage:**
```bash
python run_pclink.py
```