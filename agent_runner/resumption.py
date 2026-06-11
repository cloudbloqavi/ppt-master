"""
Auto-Resumption Watchdog Module for PPT Master Agent Runner

Handles scanning of OUTPUT_ARTIFACTS_DIR for incomplete projects and
restoring/preparing them in the active workspace to resume generation.
"""
import os
import shutil
import glob
import sys
from pathlib import Path
from agent_runner.config import ARGS, logger


def find_and_restore_incomplete_project(depth: int | None = None) -> str | None:
    """Scan OUTPUT_ARTIFACTS_DIR for incomplete projects and restore the latest one.

    Returns:
        The name of the project if one was restored/found, or None if all are complete/none found.
    """
    output_dir_str = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir_str:
        logger.warning("OUTPUT_ARTIFACTS_DIR not set. Cannot run auto-resume scan.")
        return None

    output_dir = Path(output_dir_str).expanduser().resolve()
    if not output_dir.exists():
        logger.info(f"Output directory does not exist: {output_dir}. Nothing to resume.")
        return None

    # Resolve depth
    if depth is None:
        env_depth = os.environ.get("WATCHDOG_DEPTH")
        try:
            depth = int(env_depth) if env_depth else 3
        except ValueError:
            logger.warning(f"Invalid WATCHDOG_DEPTH in env: '{env_depth}'. Using 3.")
            depth = 3

    logger.info(f"Scanning output directory for incomplete runs: {output_dir} (depth: {depth})")

    # Scan directories
    projects = []
    for entry in output_dir.iterdir():
        if entry.is_dir():
            # Signature of a started project is that it contains README.md or design_spec.md
            readme = entry / "README.md"
            design_spec = entry / "design_spec.md"
            if readme.exists() or design_spec.exists():
                pptx_files = glob.glob(str(entry / "exports" / "*.pptx"))
                projects.append({
                    "name": entry.name,
                    "path": entry,
                    "mtime": entry.stat().st_mtime,
                    "has_pptx": len(pptx_files) > 0
                })

    if not projects:
        logger.info("No projects found in the output directory.")
        return None

    # Sort projects by modification time (newest first)
    projects.sort(key=lambda p: p["mtime"], reverse=True)

    # Inspect up to depth
    targets = projects[:depth]
    for project in targets:
        logger.info(f"Checking project: {project['name']} (Last modified: {project['mtime']})")
        if project["has_pptx"]:
            logger.info(f"  [COMPLETE] PPTX already present.")
        else:
            logger.info(f"  [INCOMPLETE] No PPTX found. Initiating resumption...")
            
            # Determine workspace candidates relative to the project root (parent of agent_runner/)
            project_root = Path(__file__).parent.parent.resolve()
            workspace_candidates = [
                project_root / "core-ppt-master-engine" / "projects" / project["name"],
                project_root / "projects" / project["name"]
            ]
            exists_in_workspace = any(c.exists() for c in workspace_candidates)

            if not exists_in_workspace:
                target_projects_root = project_root / "projects"
                if (project_root / "core-ppt-master-engine" / "projects").exists():
                    target_projects_root = project_root / "core-ppt-master-engine" / "projects"
                
                target_project_path = target_projects_root / project["name"]
                logger.info(f"  [RESTORE] Project folder not found in workspace. Restoring from output artifacts to {target_project_path}...")
                try:
                    shutil.copytree(project["path"], target_project_path)
                    logger.info(f"  [RESTORE] Successfully restored {project['name']} to workspace.")
                except Exception as exc:
                    logger.error(f"  [RESTORE FAILED] Could not restore {project['name']} to workspace: {exc}")
                    sys.exit(1)

            return project["name"]

    logger.info(f"All {len(targets)} scanned projects are already complete.")
    return None
