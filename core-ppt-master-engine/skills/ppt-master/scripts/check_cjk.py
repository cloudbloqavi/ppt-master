#!/usr/bin/env python3
"""CJK Character Scanner and Translator.

Provides tools to scan the repository for any Chinese characters and 
automatically translate them to English using the Gemini API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import time
from pathlib import Path

# CJK Range Regex (Chinese Characters)
CJK_RE = re.compile(r'[\u4e00-\u9fff]')

# Exclude directories commonly ignored
EXCLUDE_DIRS = {
    '.git', '.venv', 'node_modules', 'examples', '__pycache__', 
    '.system_generated', 'artifacts', 'scratch', '.idea', '.vscode'
}

# Supported extensions for scanning
SCAN_EXTENSIONS = ('.py', '.md', '.txt', '.json', '.html', '.css', '.js', '.svg')

# Default deck renaming mapping for translation
DECK_MAPPING = {
    "中国电信": "china_telecom",
    "中国电建_常规": "powerchina_standard",
    "中国电建_现代": "powerchina_modern",
    "中汽研_商务": "catarc_business",
    "中汽研_常规": "catarc_standard",
    "中汽研_现代": "catarc_modern",
    "招商银行": "cmb",
    "重庆大学": "cqu"
}

def get_gemini_key() -> str | None:
    # Try finding GEMINI_API_KEY in .env first
    env_path = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return os.environ.get("GEMINI_API_KEY")

def call_gemini_api(gemini_key: str, prompt: str, content: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    data = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"{prompt}\n\nHere is the content:\n\n{content}"
                    }
                ]
            }
        ]
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode("utf-8"))
                result_text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Strip markdown code block wrapping if returned
                if result_text.startswith("```"):
                    lines = result_text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    result_text = "\n".join(lines).strip()
                return result_text
        except urllib.error.HTTPError as e:
            if e.code == 429:
                sleep_time = attempt * 2 + 2
                print(f"Rate limited (429). Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                raise e
    raise RuntimeError("Gemini API call failed after multiple retries.")

def scan_files(search_dir: Path, target_files: list[str] | None = None) -> dict[str, list[tuple[int, str]]]:
    results = {}
    
    if target_files:
        # Check specific files
        for fpath_str in target_files:
            fpath = Path(fpath_str).resolve()
            if not fpath.exists():
                continue
            # Try to read and scan
            try:
                matches = []
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if CJK_RE.search(line):
                            matches.append((i, line.strip()))
                if matches:
                    rel_path = os.path.relpath(fpath, search_dir)
                    results[rel_path] = matches
            except Exception as e:
                print(f"Error scanning file {fpath}: {e}")
    else:
        # Walk and scan
        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                if file == "check_cjk.py":
                    continue
                if file.endswith(SCAN_EXTENSIONS):
                    fpath = Path(root) / file
                    try:
                        matches = []
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f, 1):
                                if CJK_RE.search(line):
                                    matches.append((i, line.strip()))
                        if matches:
                            rel_path = os.path.relpath(fpath, search_dir)
                            results[rel_path] = matches
                    except Exception as e:
                        print(f"Error scanning file {fpath}: {e}")
                        
    return results

def translate_file(search_dir: Path, rel_path: str, gemini_key: str):
    fpath = search_dir / rel_path
    if not fpath.exists():
        return
    
    print(f"Translating: {rel_path}...")
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            original_content = f.read()
        
        prompt = (
            "You are a translation assistant. Your task is to translate all Chinese comments, documentation, "
            "text values, and string patterns into clean, natural English.\n"
            "- If you see file name checks (like '设计规范.md' or '来源文档.md') in code strings, translate them to logical English names (like 'design_spec.md' or 'source_document.md').\n"
            "- If you see regular expression ranges matching CJK ranges (like '[\\u4e00-\\u9fff]' or '第...页'), translate the regex to support English equivalents.\n"
            "- If you see Chinese voice descriptions or voice names, translate their descriptions to English.\n"
            "- Ensure all code structure, python syntax, tag structure, HTML attributes, CSS properties, and SVG coordinates are kept exactly as they are.\n"
            "- Return ONLY the raw translated file content. Do not wrap it in markdown code blocks."
        )
        
        translated_content = call_gemini_api(gemini_key, prompt, original_content)
        
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(translated_content)
        print(f"  Successfully translated {rel_path}.")
    except Exception as exc:
        print(f"  Failed to translate {rel_path}: {exc}")

def translate_decks_and_index(search_dir: Path, gemini_key: str):
    decks_dir = search_dir / "core-ppt-master-engine" / "skills" / "ppt-master" / "templates" / "decks"
    decks_index_path = decks_dir / "decks_index.json"
    
    if decks_index_path.exists():
        try:
            with open(decks_index_path, "r", encoding="utf-8") as f:
                decks_data = json.load(f)
            
            translated_data = {}
            for key, val in decks_data.items():
                mapped_key = DECK_MAPPING.get(key, key)
                summary = val.get("summary", "")
                if CJK_RE.search(summary):
                    print(f"Translating deck summary for {key}...")
                    summary = call_gemini_api(gemini_key, "Translate the following presentation template summary into English:", summary)
                translated_data[mapped_key] = {"summary": summary}
            
            with open(decks_index_path, "w", encoding="utf-8") as f:
                json.dump(translated_data, f, indent=2, ensure_ascii=False)
            print("Successfully updated decks_index.json.")
        except Exception as exc:
            print(f"Failed to process decks_index.json: {exc}")
            
    # Rename deck directories and translate design specs
    for zh_name, en_name in DECK_MAPPING.items():
        zh_folder = decks_dir / zh_name
        en_folder = decks_dir / en_name
        
        if zh_folder.exists():
            print(f"Renaming deck folder: {zh_name} -> {en_name}...")
            if en_folder.exists() and zh_folder.name.lower() != en_folder.name.lower():
                import shutil
                shutil.rmtree(en_folder)
            os.rename(zh_folder, en_folder)
            
        spec_path = en_folder / "design_spec.md"
        if spec_path.exists():
            print(f"Translating design_spec.md for {en_name}...")
            try:
                with open(spec_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                content = content.replace(f"deck_id: {zh_name}", f"deck_id: {en_name}")
                prompt = (
                    "Translate the following design specification markdown into English. "
                    "Maintain the markdown structure and ensure no Chinese characters remain. "
                    "Return ONLY the translated markdown."
                )
                translated_spec = call_gemini_api(gemini_key, prompt, content)
                with open(spec_path, "w", encoding="utf-8") as f:
                    f.write(translated_spec)
                print(f"  Successfully translated design_spec.md for {en_name}.")
            except Exception as exc:
                print(f"  Failed to translate design_spec.md for {en_name}: {exc}")

def sync_to_wsl(search_dir: Path):
    # If in Windows and there is a WSL folder, run rsync or report synchronization action
    print("Checking for WSL synchronization path...")
    # Typically user project has an active terminal or WSL dev folder at ~/development/ai-builder-engine/
    # We can run bash/wsl rsync to sync.
    # To keep this script self-contained, we print the sync instruction or try executing rsync.
    wsl_check = os.environ.get("WSL_DISTRIBUTION_NAME") or os.path.exists("/run/WSL")
    if not wsl_check:
        print("Note: If you are running on Windows, make sure to sync these changes to your WSL environment:")
        print("  rsync -avzc --delete --exclude '.git' --exclude 'node_modules' /mnt/c/Users/aviji/repo/ai-builder-engine/ ~/development/ai-builder-engine/")

def main() -> int:
    # Set console encoding to UTF-8
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
        
    parser = argparse.ArgumentParser(description="Scan and translate Chinese characters in the repository.")
    parser.add_argument("--scan", action="store_true", default=True, help="Scan the repository for Chinese characters (default).")
    parser.add_argument("--translate", action="store_true", help="Translate Chinese characters in place.")
    parser.add_argument("--files", nargs="+", help="Only scan/translate the specified files.")
    
    # Allow overriding default parse behavior if --translate is passed
    args = parser.parse_args()
    if args.translate:
        args.scan = False
        
    search_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    
    print(f"Target repository directory: {search_dir}")
    
    if args.scan:
        print("Starting CJK scan...")
        results = scan_files(search_dir, target_files=args.files)
        if results:
            print(f"\n[ALERT] Found CJK (Chinese) characters in {len(results)} files:\n")
            for rel_path, matches in results.items():
                print(f"=== {rel_path} ===")
                for line_num, content in matches:
                    print(f"  Line {line_num}: {content}")
                print()
            print("Action required: Run with '--translate' to automatically translate these files using Gemini.")
            return 1
        else:
            print("Scan complete: Zero Chinese characters found in the repository.")
            return 0
            
    elif args.translate:
        gemini_key = get_gemini_key()
        if not gemini_key:
            print("Error: GEMINI_API_KEY is not set. Cannot run automated translations.")
            return 1
            
        print("Starting automated translation...")
        results = scan_files(search_dir, target_files=args.files)
        
        if not results:
            print("No Chinese characters found to translate.")
        else:
            for rel_path in results.keys():
                translate_file(search_dir, rel_path, gemini_key)
                
        # If running globally (not single file), also translate decks and index
        if not args.files:
            translate_decks_and_index(search_dir, gemini_key)
            
        # Verify again
        print("\nVerifying translation results...")
        re_results = scan_files(search_dir, target_files=args.files)
        if re_results:
            print(f"[WARNING] Some CJK characters could not be automatically translated:\n")
            for rel_path, matches in re_results.items():
                print(f"=== {rel_path} ===")
                for line_num, content in matches:
                    print(f"  Line {line_num}: {content}")
            return 1
        else:
            print("Verification successful: Zero Chinese characters remaining!")
            sync_to_wsl(search_dir)
            return 0

if __name__ == "__main__":
    sys.exit(main())
