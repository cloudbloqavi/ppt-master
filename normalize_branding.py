#!/usr/bin/env python3
"""
Presentation Builder - Branding & Nomenclature Normalization Utility

Automatically scans the repository for human-readable occurrences of "PPT Master"
and maps them to "Presentation Builder" to maintain repository-wide branding consistency,
while safely preserving file paths, CLI parameters, and directory variables.
"""
import os
import re
import subprocess
import sys

# Case-preserving replacements for human-facing naming
REPLACEMENTS = [
    (r"\bPPT Master\b", "Presentation Builder"),
    (r"\bPPT MASTER\b", "PRESENTATION BUILDER"),
    (r"\bppt master\b", "presentation builder"),
    (r"\bPpt Master\b", "Presentation Builder"),
    (r"\bPPT-Master\b", "Presentation-Builder"),
    (r"\bPpt-Master\b", "Presentation-Builder"),
    (r"\bPPT_Master\b", "Presentation_Builder"),
    (r"\bPpt_Master\b", "Presentation_Builder")
]

def get_matching_files():
    """Locate all repository tracked files containing 'PPT Master' case-insensitively using git grep."""
    try:
        res = subprocess.run(
            ["git", "grep", "-l", "-i", "PPT Master"],
            capture_output=True,
            text=True,
            check=True
        )
        return [f.strip() for f in res.stdout.splitlines() if f.strip()]
    except subprocess.CalledProcessError:
        # git grep exits with status 1 if no matches are found
        return []

def safe_replace(content):
    """Apply case-matched normalization replacements."""
    new_content = content
    for pattern, repl in REPLACEMENTS:
        new_content = re.sub(pattern, repl, new_content)
    return new_content

def main():
    print("=== Presentation Builder Branding Normalizer ===")
    files = get_matching_files()
    if not files:
        print("No occurrences of 'PPT Master' found. Repository branding is fully in sync!")
        return 0

    modified_count = 0
    for file_path in files:
        if not os.path.exists(file_path):
            continue
            
        # Skip binary files or specific outputs if any
        if any(file_path.endswith(ext) for ext in [".pptx", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"]):
            continue
            
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            new_content = safe_replace(content)
            
            if content != new_content:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"  • Normalized: {file_path}")
                modified_count += 1
        except Exception as err:
            print(f"  • Error processing {file_path}: {err}", file=sys.stderr)

    print(f"Completed! Normalized {modified_count} file(s).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
