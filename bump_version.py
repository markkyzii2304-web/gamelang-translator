#!/usr/bin/env python3
"""
bump_version.py — เพิ่ม version number + git tag + push
Usage:
  python bump_version.py patch   → 2.0.1 → 2.0.2
  python bump_version.py minor   → 2.0.1 → 2.1.0
  python bump_version.py major   → 2.0.1 → 3.0.0
  python bump_version.py 2.5.0   → set exact version
"""
import sys, os, subprocess

VERSION_FILE = os.path.join(os.path.dirname(__file__), "VERSION")
ISS_FILE = os.path.join(os.path.dirname(__file__), "installer", "gamelang.iss")

def read_version():
    with open(VERSION_FILE) as f:
        return f.read().strip()

def write_version(v):
    with open(VERSION_FILE, "w") as f:
        f.write(v + "\n")

def bump(current, part):
    major, minor, patch = map(int, current.split("."))
    if part == "major": return f"{major+1}.0.0"
    if part == "minor": return f"{major}.{minor+1}.0"
    if part == "patch": return f"{major}.{minor}.{patch+1}"
    # exact version
    parts = part.split(".")
    if len(parts) == 3:
        return part
    raise ValueError(f"Unknown bump type: {part}")

def update_iss(new_version):
    with open(ISS_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    import re
    content = re.sub(
        r'#define MyAppVersion\s+"[\d.]+"',
        f'#define MyAppVersion   "{new_version}"',
        content
    )
    with open(ISS_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def run(cmd):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout: print(result.stdout.strip())
    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip()}")
        sys.exit(1)

def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"
    current = read_version()
    new_ver = bump(current, part)

    print(f"Bumping version: {current} → {new_ver}")

    write_version(new_ver)
    update_iss(new_ver)

    run(f'git add VERSION installer/gamelang.iss')
    run(f'git commit -m "chore: bump version to v{new_ver}"')
    run(f'git tag v{new_ver}')
    run(f'git push origin main')
    run(f'git push origin v{new_ver}')

    print(f"\nVersion bumped to v{new_ver}")
    print(f"  GitHub Actions จะ build และสร้าง Release อัตโนมัติ")

if __name__ == "__main__":
    main()
