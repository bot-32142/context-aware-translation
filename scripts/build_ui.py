#!/usr/bin/env python3
"""Build script for Context-Aware Translation UI."""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def clean_build_dirs(project_root: Path) -> None:
    """Clean previous build artifacts."""
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print(f"Cleaning {dir_path}...")
            shutil.rmtree(dir_path)


def run_pyinstaller(project_root: Path, debug: bool = False) -> int:
    """Run PyInstaller with the spec file."""
    spec_file = project_root / 'cat-ui.spec'

    if not spec_file.exists():
        print(f"Error: Spec file not found: {spec_file}")
        return 1

    cmd = ['pyinstaller', str(spec_file), '--clean']
    if debug:
        cmd.append('--debug=all')

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode


def print_build_info(project_root: Path) -> None:
    """Print information about the build."""
    system = platform.system()
    dist_dir = project_root / 'dist'

    print("\n" + "=" * 60)
    print("Build Complete!")
    print("=" * 60)
    print(f"Platform: {system} ({platform.machine()})")
    print(f"Python: {sys.version}")

    if system == 'Darwin':
        app_path = dist_dir / 'CAT-UI.app'
        if app_path.exists():
            print(f"\nmacOS App Bundle: {app_path}")
            print(f"To run: open '{app_path}'")
    elif system == 'Windows':
        exe_path = dist_dir / 'CAT-UI' / 'CAT-UI.exe'
        if exe_path.exists():
            print(f"\nWindows Executable: {exe_path}")
            print(f"To run: {exe_path}")
    else:  # Linux
        exe_path = dist_dir / 'CAT-UI' / 'CAT-UI'
        if exe_path.exists():
            print(f"\nLinux Executable: {exe_path}")
            print(f"To run: {exe_path}")

    print("\nDist directory contents:")
    if dist_dir.exists():
        for item in sorted(dist_dir.iterdir()):
            size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file()) if item.is_dir() else item.stat().st_size
            size_mb = size / (1024 * 1024)
            print(f"  {item.name}: {size_mb:.1f} MB")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Build Context-Aware Translation UI')
    parser.add_argument('--clean', action='store_true', help='Clean build directories before building')
    parser.add_argument('--debug', action='store_true', help='Build with debug enabled')
    parser.add_argument('--no-build', action='store_true', help='Only clean, do not build')
    args = parser.parse_args()

    project_root = get_project_root()
    print(f"Project root: {project_root}")
    print(f"Building for: {platform.system()} ({platform.machine()})")

    # Check for PyInstaller
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("Error: PyInstaller not installed. Install with: pip install pyinstaller")
        return 1

    if args.clean or args.no_build:
        clean_build_dirs(project_root)
        if args.no_build:
            print("Clean complete.")
            return 0

    # Run build
    result = run_pyinstaller(project_root, debug=args.debug)

    if result == 0:
        print_build_info(project_root)
    else:
        print("\nBuild failed!")

    return result


if __name__ == '__main__':
    sys.exit(main())
