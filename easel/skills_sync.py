"""Compare and copy repository-owned skill files without touching workspace memories."""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from easel.openclaw_workspace import workspace_dir

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ('skills/builtin', 'skills/shared')
WORKSPACE_LINKS = {'easel-profiles': 'profiles', 'outputs': 'outputs'}
WINDOWS = os.name == 'nt'
_IGNORED_DIRS = {'__pycache__', '.git', '.venv', 'node_modules', '.pytest_cache'}


def agent_workspace() -> Path:
    return workspace_dir(refresh=True)


def _files(root: Path):
    # Python 3.10 的 is_symlink() 不识别 Windows junction；解析后的目录
    # 必须仍是原目录，避免从技能源中的联接读取外部文件或进入循环。
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError('仓库源目录包含链接，无法安全校验')
    for entry in sorted(root.iterdir()):
        if entry.name in _IGNORED_DIRS or entry.name == '.DS_Store' or entry.suffix in {'.pyc', '.pyo'}:
            continue
        if entry.is_symlink():
            raise ValueError('仓库源文件包含链接，无法安全校验')
        if entry.is_dir():
            yield from _files(entry)
        elif entry.is_file():
            yield entry


def _digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.digest()


def _same_file(source: Path, destination: Path) -> bool:
    try:
        return source.samefile(destination)
    except OSError:
        return False


def _managed_files(ws: Path):
    boundary = ws.resolve()
    if boundary == PROJECT_ROOT.resolve():
        raise ValueError('workspace 不能是项目根目录')
    for relative in SOURCE_DIRS:
        source = (PROJECT_ROOT / relative).resolve()
        if boundary == source or source in boundary.parents:
            raise ValueError('workspace 不能位于技能源目录内部')
    for relative, name in zip(SOURCE_DIRS, ('skills', 'shared')):
        source_root = PROJECT_ROOT.resolve() / relative
        if not source_root.is_dir():
            raise ValueError('仓库技能源目录不存在')
        for source in _files(source_root):
            destination = ws / name / source.relative_to(source_root)
            if not _same_file(source, destination) and boundary not in destination.resolve().parents:
                raise ValueError('workspace 技能目标链接到了其他目录，请先核对路径')
            yield source, destination


def _matches(source: Path, destination: Path) -> bool:
    return _same_file(source, destination) or (
        destination.is_file() and source.stat().st_size == destination.stat().st_size
        and _digest(source) == _digest(destination))


def skills_sync_state(ws: Path | None = None) -> tuple[bool, str]:
    try:
        ws = agent_workspace() if ws is None else ws
        skills = ws / 'skills'
        if not skills.is_dir() or not any(skills.iterdir()):
            return False, f'agent 实际读取的 workspace 是 {ws}，其中 skills/ 为空或不存在'
        count = 0
        for source, destination in _managed_files(ws):
            count += 1
            if not _matches(source, destination):
                relative = source.relative_to(PROJECT_ROOT.resolve())
                reason = '内容不同' if destination.is_file() else '副本缺失'
                return False, (f'workspace 是 {ws}；仓库文件 {relative} {reason}：改了但没同步；'
                               '请运行 python scripts/sync_if_stale.py')
        if not count:
            return False, '仓库技能源为空，无法确认同步状态'
        return True, f'workspace 是 {ws}，{count} 个现有仓库文件已是最新；额外本机文件保留，不保证既有会话缓存已重载'
    except (OSError, ValueError, RuntimeError):
        return False, f'无法完整校验 workspace {ws} 的技能文件或路径，未确认同步'


def sync_needed() -> bool:
    return not skills_sync_state()[0]


def synchronize_skills(ws: Path | None = None) -> int:
    """Atomically replace only existing source paths; keep all user extras and memories."""
    ws = agent_workspace() if ws is None else ws
    files = list(_managed_files(ws))  # Validate every destination before writing any file.
    copied = 0
    for source, destination in files:
        if _matches(source, destination):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.easel-sync-', delete=False) as file:
                temporary = Path(file.name)
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            copied += 1
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return copied


def ensure_workspace_links(ws: Path | None = None) -> list[str]:
    """Create missing Windows junctions; never delete or replace an existing copy/link."""
    if not WINDOWS:
        return []
    ws = agent_workspace() if ws is None else ws
    problems = []
    for name, relative in WORKSPACE_LINKS.items():
        link, target = ws / name, PROJECT_ROOT / relative
        if not target.is_dir() or _same_file(link, target):
            continue
        if os.path.lexists(link):
            problems.append(f'{name} 已有目录或链接与项目源不同，已保留，请人工核对后处理')
            continue
        executable = shutil.which('powershell') or shutil.which('pwsh')
        if not executable:
            problems.append(f'{name} 缺少 PowerShell，无法建立目录联接')
            continue
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        script = "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path " + quote(link) + ' -Value ' + quote(target) + ' | Out-Null'
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        try:
            result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            if result.returncode != 0 or not _same_file(link, target):
                problems.append(f'{name} 无法建立目录联接，既有目录未改动')
        except (OSError, subprocess.SubprocessError):
            problems.append(f'{name} 无法建立目录联接，既有目录未改动')
    return problems
