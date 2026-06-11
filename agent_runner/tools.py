"""
Workspace Tools & Self-Test Module for PPT Master Agent Runner

Defines helper tools (read_file, write_file, list_directory, grep_search,
run_command) exposed to the agent loop and validates them in run_self_test().
"""
import subprocess
import os
from pathlib import Path


def read_file(file_path: str) -> str:
    """Read the content of a file in the workspace.

    Args:
        file_path: Absolute or relative path to the file.
    Returns:
        The content of the file or an error message.
    """
    try:
        target = Path(file_path).resolve()
        with open(target, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {file_path}: {e}"


def write_file(file_path: str, content: str) -> str:
    """Write or overwrite content to a file, creating any parent folders.

    Args:
        file_path: Absolute or relative path to the file.
        content: The text content to write.
    Returns:
        A success message or an error message.
    """
    try:
        target = Path(file_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file {file_path}: {e}"


def list_directory(directory_path: str = ".") -> str:
    """List the files and subdirectories inside a given folder.

    Args:
        directory_path: Absolute or relative path to the folder. Defaults to '.'.
    Returns:
        A list of files and directories or an error message.
    """
    try:
        target = Path(directory_path).resolve()
        if not target.exists():
            return f"Directory does not exist: {directory_path}"
        entries = []
        for entry in sorted(target.iterdir()):
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"{entry.name}{suffix}")
        return "\n".join(entries) if entries else "Directory is empty."
    except Exception as e:
        return f"Error listing directory {directory_path}: {e}"


def grep_search(query: str, directory_path: str = ".") -> str:
    """Recursively search for a text pattern in files under a directory.

    Args:
        query: The search term or pattern to look for.
        directory_path: Folder to search in. Defaults to '.'.
    Returns:
        A summary of matches or an error message.
    """
    results: list[str] = []
    try:
        root_dir = Path(directory_path).resolve()
        for file_path in root_dir.rglob("*"):
            if any(p.startswith(".") for p in file_path.parts):
                continue
            if any(part in file_path.parts for part in ("node_modules", "icons", "__pycache__", "venv", "env", "exports", "images")):
                continue
            try:
                if not file_path.is_file():
                    continue
            except Exception:
                continue
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if query in line:
                            rel = file_path.relative_to(root_dir)
                            results.append(f"{rel}:{line_num}: {line.strip()}")
                            if len(results) >= 50:
                                return "\n".join(results) + "\n... (truncated)"
            except Exception:
                pass
        return "\n".join(results) if results else "No matches found."
    except Exception as e:
        return f"Error searching for query '{query}': {e}"


def run_command(command: str, cwd: str = ".") -> dict:
    """Run a terminal or shell command in the workspace directory.

    Args:
        command: The shell command line to execute.
        cwd: Directory where the command will run. Defaults to '.'.
    Returns:
        A dictionary with stdout, stderr, and the returncode.
    """
    try:
        res = subprocess.run(
            command,
            shell=True,
            cwd=str(Path(cwd).resolve()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "stdout": res.stdout,
            "stderr": res.stderr,
            "returncode": res.returncode,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Error running command '{command}': {e}",
            "returncode": -1,
        }


def run_self_test() -> bool:
    """Run a self-test of the defined workspace tools in isolation."""
    print("=== STARTING WORKSPACE TOOLS SELF-TEST ===")
    test_file = "test_run_agent_temp.txt"
    test_content = (
        "This is a temporary test file containing the unique keyword "
        "AntigravityRunnerTest123."
    )

    # 1. write_file
    print("\n1. Testing write_file...")
    res = write_file(test_file, test_content)
    print(f"Result: {res}")
    if "Error" in res:
        print("FAIL: write_file failed")
        return False

    # 2. read_file
    print("\n2. Testing read_file...")
    read_res = read_file(test_file)
    print(f"Result: '{read_res}'")
    if read_res != test_content:
        print("FAIL: read_file content did not match written content")
        return False

    # 3. list_directory
    print("\n3. Testing list_directory...")
    list_res = list_directory(".")
    print(f"Result (truncated): '{list_res[:100]}...'")
    if test_file not in list_res:
        print("FAIL: test file not found in list_directory")
        return False

    # 4. grep_search
    print("\n4. Testing grep_search...")
    grep_res = grep_search("AntigravityRunnerTest123", ".")
    print(f"Result: '{grep_res}'")
    if test_file not in grep_res:
        print("FAIL: grep_search did not find the keyword in test file")
        return False

    # 5. run_command
    print("\n5. Testing run_command...")
    cmd = "echo Tools self-test command execution is working"
    cmd_res = run_command(cmd)
    print(f"Result: {cmd_res}")
    if cmd_res["returncode"] != 0 or "working" not in cmd_res["stdout"].lower():
        print("FAIL: run_command failed or did not return expected stdout")
        return False

    # Clean up
    print("\n6. Cleaning up test file...")
    if os.path.exists(test_file):
        os.remove(test_file)
    print("Cleanup completed.")

    print("\n=== ALL WORKSPACE TOOLS PASSED SELF-TEST ===")
    return True
