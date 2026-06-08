#!/usr/bin/env python3
"""
check_dependencies.py

Parses requirements.txt files in the repository, queries the PyPI JSON API
to get the latest stable version of each library, and generates or updates
the DEPENDENCIES.md file in the project root.

Preserves EOL and custom Notes from the existing DEPENDENCIES.md if present.
Enforces that all audited markdown files use strictly relative paths.
"""

import os
import sys
import re
import urllib.request
import json
from datetime import datetime

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = SCRIPT_DIR
DEP_MD_PATH = os.path.join(ROOT_DIR, "DEPENDENCIES.md")

REQUIRE_FILES = [
    os.path.join(ROOT_DIR, "requirements.txt"),
    os.path.join(ROOT_DIR, "core-ppt-master-engine/skills/ppt-master/requirements.txt")
]

# Known EOL or deprecation data to seed if not already present in DEPENDENCIES.md
SEED_EOL_DATA = {
    "playwright": "Active",
    "flask": "Active",
    "python-pptx": "Active",
    "cairosvg": "Active",
    "pillow": "Active",
    "numpy": "NumPy 1.x EOL expected late 2026; NumPy 2.x is active.",
    "google-antigravity": "Active (Core SDK)",
    "beautifulsoup4": "Active",
    "requests": "Active",
    "google-genai": "Active",
    "svglib": "Legacy (Unmaintained, CairoSVG preferred)",
    "ebooklib": "Legacy (Mammoth/Markdownify preferred)",
    "curl-cffi": "Active",
    "edge-tts": "Active",
    "mammoth": "Active",
    "markdownify": "Active",
    "nbconvert": "Active",
    "openpyxl": "Active",
    "pymupdf": "Active",
    "python-dotenv": "Active",
    "reportlab": "Active"
}

def parse_requirements():
    dependencies = {}
    package_pattern = re.compile(r"^([a-zA-Z0-9_\-]+)\s*(>=|==|<=|>|<)?\s*([0-9a-zA-Z\.\-]+)?")

    for req_file in REQUIRE_FILES:
        if not os.path.exists(req_file):
            print(f"[WARN] Requirements file not found: {req_file}")
            continue
        
        with open(req_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-r"):
                    continue
                
                # Strip inline comments
                if " #" in line:
                    line = line.split(" #")[0].strip()

                match = package_pattern.match(line)
                if match:
                    pkg_name = match.group(1).lower().replace("_", "-")
                    op = match.group(2) or ""
                    ver = match.group(3) or ""
                    specifier = f"{op}{ver}" if op and ver else "Any"
                    
                    # Update or set version specifier (prioritize more specific specifiers if duplicate)
                    if pkg_name not in dependencies or dependencies[pkg_name] == "Any":
                        dependencies[pkg_name] = specifier
                        
    return dependencies

def fetch_pypi_version(package_name):
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Dependency-Checker/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["info"]["version"]
    except Exception as e:
        print(f"[WARN] Failed to fetch version for {package_name}: {e}")
        return "Unknown"

def parse_version_tuple(version_str):
    try:
        # Extract digits
        parts = re.findall(r"\d+", version_str)
        return tuple(int(x) for x in parts)
    except Exception:
        return (0,)

def is_update_recommended(current_spec, latest_version):
    if latest_version == "Unknown" or current_spec == "Any":
        return "No"
    
    # Strip operators from current spec to get version number
    curr_ver_str = re.sub(r"[>=<!~]", "", current_spec).strip()
    curr_tuple = parse_version_tuple(curr_ver_str)
    latest_tuple = parse_version_tuple(latest_version)
    
    # Recommend update if latest version has a higher major or minor version
    if latest_tuple > curr_tuple:
        return "Yes"
    return "No"

def read_existing_dependencies():
    existing_data = {}
    if not os.path.exists(DEP_MD_PATH):
        return existing_data

    try:
        with open(DEP_MD_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        row_pattern = re.compile(r"^\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|")
        
        for line in lines:
            match = row_pattern.match(line)
            if match:
                dep_name = match.group(1).strip().lower().replace("_", "-")
                if dep_name == "dependency" or dep_name.startswith("---") or dep_name.startswith(":") or dep_name.startswith("---"):
                    continue
                
                dep_name = dep_name.replace("`", "")
                
                eol = match.group(4).strip()
                notes = match.group(7).strip()
                
                existing_data[dep_name] = {
                    "eol": eol,
                    "notes": notes
                }
    except Exception as e:
        print(f"[WARN] Error parsing existing DEPENDENCIES.md: {e}")
        
    return existing_data

def check_absolute_paths():
    print("[INFO] Checking for absolute paths in repository markdown files...")
    files_to_check = [
        os.path.join(ROOT_DIR, "AGENTS.md"),
        os.path.join(ROOT_DIR, "README.md"),
        os.path.join(ROOT_DIR, "DEPENDENCIES.md"),
        os.path.join(ROOT_DIR, "core-ppt-master-engine/skills/ppt-master/SKILL.md")
    ]
    
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    absolute_patterns = [
        re.compile(r"^file:///"),
        re.compile(r"^[a-zA-Z]:[\\/]"),
        re.compile(r"^/mnt/"),
        re.compile(r"^/home/"),
        re.compile(r"^/Users/")
    ]
    
    found_errors = False
    for filepath in files_to_check:
        if not os.path.exists(filepath):
            continue
        
        with open(filepath, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                matches = link_pattern.findall(line)
                for text, url in matches:
                    url = url.strip()
                    is_absolute = any(pat.match(url) for pat in absolute_patterns)
                    if is_absolute:
                        print(f"[ERROR] Absolute path detected in {os.path.basename(filepath)}:{idx}")
                        print(f"        Link: [{text}]({url})")
                        found_errors = True
                        
    if found_errors:
        print("[FAIL] Absolute path validation failed. Please use relative paths instead.")
        return False
    print("[SUCCESS] All audited markdown links are relative.")
    return True

def format_status_with_emoji(status_text):
    # Remove emojis like 🔴, ⚠️, 🟢 and surrounding whitespace/spaces from the beginning
    cleaned = re.sub(r'^[🔴⚠️🟢\s]+', '', status_text).strip()
    if not cleaned:
        cleaned = "Active"
    lower_cleaned = cleaned.lower()
    
    # Determine if it's critical, warning, or active
    if any(word in lower_cleaned for word in ["legacy", "unmaintained", "deprecated", "expired", "replace", "obsolete"]):
        return f"🔴 {cleaned}"
    elif any(word in lower_cleaned for word in ["eol", "warn", "impending", "transition", "soon"]):
        return f"⚠️ {cleaned}"
    else:
        return f"🟢 {cleaned}"

def generate_dependencies_md():
    print("[INFO] Auditing dependencies...")
    reqs = parse_requirements()
    existing = read_existing_dependencies()
    today = datetime.now().strftime("%Y-%m-%d")
    
    rows = []
    for pkg in sorted(reqs.keys()):
        current_spec = reqs[pkg]
        latest_ver = fetch_pypi_version(pkg)
        
        eol = "Active"
        notes = "-"
        if pkg in existing:
            eol = existing[pkg]["eol"]
            notes = existing[pkg]["notes"]
            # If the parsed existing EOL is just a generic "Active", check if SEED_EOL_DATA has a more specific status
            cleaned_existing_eol = re.sub(r'^[🔴⚠️🟢\s]+', '', eol).strip().lower()
            if cleaned_existing_eol in ("active", "") and pkg in SEED_EOL_DATA:
                eol = SEED_EOL_DATA[pkg]
        elif pkg in SEED_EOL_DATA:
            eol = SEED_EOL_DATA[pkg]
            
        eol_formatted = format_status_with_emoji(eol)
        action = is_update_recommended(current_spec, latest_ver)
        
        pkg_formatted = f"`{pkg}`"
        current_formatted = f"`{current_spec}`"
        latest_formatted = f"`{latest_ver}`" if latest_ver != "Unknown" else "Unknown"
        action_formatted = f"**{action}**" if action == "Yes" else "No"
        
        rows.append(f"| {pkg_formatted} | {current_formatted} | {latest_formatted} | {eol_formatted} | {action_formatted} | {today} | {notes} |")

    content = f"""# Project Dependency Status & EOL Tracking

This file tracks the third-party libraries used across this project, their current requirements, latest stable versions, End-of-Life (EOL) status, and recommended update actions.

> [!NOTE]
> This file is maintained automatically and manually via the agentic framework. 
> To update version numbers and analyze deprecations, run the check script:
> ```bash
> python3 check_dependencies.py
> ```

## Dependency Audit Table

| Dependency | Current Version | Latest Version | EOL / Deprecation Status | Action Required (Yes/No) | Last Audited | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
    for row in rows:
        content += row + "\n"
        
    content += """
## Agentic Audit Guidelines

When an AI agent is asked to review or update dependencies:
1. **Execute the Script**: Run `python3 check_dependencies.py` to refresh all PyPI version listings.
2. **Search EOL Statuses**: For packages marked with EOL warnings or major version differences, use Google Search to verify deprecation timelines and compatibility risks (e.g. NumPy 2.0 migration boundaries).
3. **Recommend Actions**: Update the **Action Required** column to `Yes` or `No` and document the rationale in the **Notes** column.
4. **Update Requirements**: If an update action is approved, edit the corresponding `requirements.txt` file and verify compatibility in WSL.
"""
    
    with open(DEP_MD_PATH, "w", encoding="utf-8") as f:
        f.write(content)
        
    print(f"[SUCCESS] Updated {DEP_MD_PATH}")

def main():
    generate_dependencies_md()
    if not check_absolute_paths():
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
