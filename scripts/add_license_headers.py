import os

LICENSE_HEADER = """# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""

def add_header(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Skip files that already have the header (checking first line is usually enough)
    if "SPDX-License-Identifier: AGPL-3.0-or-later" in content:
        return

    # Keep hashbangs at the top (e.g. #!/usr/bin/env python3)
    if content.startswith("#!"):
        lines = content.splitlines(keepends=True)
        new_content = lines[0] + LICENSE_HEADER + "".join(lines[1:])
    else:
        new_content = LICENSE_HEADER + content

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Added header to: {file_path}")

def main():
    root_dir = "src"  # Only modify source files
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".py"):
                add_header(os.path.join(root, file))

if __name__ == "__main__":
    main()
