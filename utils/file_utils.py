"""
File reading and project scanning utilities.
"""
from pathlib import Path
from typing import Optional


def read_source_file(path: Path, max_chars: int = 12000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"파일을 읽을 수 없습니다: {path}\n오류: {e}")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... [{len(text) - max_chars}자 생략됨]"
    return text


def collect_cpp_files(source_dir: Path) -> list[Path]:
    return sorted(p for p in source_dir.rglob("*") if p.suffix in (".h", ".cpp"))


def collect_assets(content_dir: Path) -> list[Path]:
    return sorted(content_dir.rglob("*.uasset"))


def find_file(name: str, source_dir: Path) -> Optional[Path]:
    """파일명(부분 일치)으로 소스 파일 탐색."""
    name_lower = name.lower()
    candidates = collect_cpp_files(source_dir)
    exact = [p for p in candidates if p.name.lower() == name_lower]
    if exact:
        return exact[0]
    partial = [p for p in candidates if name_lower in p.name.lower()]
    return partial[0] if partial else None


def detect_ue5_project(start: Path) -> Optional[Path]:
    """
    start 디렉토리부터 .uproject 파일을 탐색해 UE5 프로젝트 루트를 반환.
    위쪽(부모) 방향과 아래쪽(자식) 방향 모두 탐색.
    """
    current = start.resolve()

    # 1) 위쪽 탐색 (현재 디렉토리가 프로젝트 내부일 때)
    probe = current
    for _ in range(6):
        if list(probe.glob("*.uproject")):
            return probe
        if probe.parent == probe:
            break
        probe = probe.parent

    # 2) 아래쪽 탐색 (start가 레포 루트, 프로젝트가 하위 폴더일 때)
    for uproject in current.rglob("*.uproject"):
        return uproject.parent  # 첫 번째 발견된 프로젝트 루트 반환

    return None


def detect_source_dir(project_root: Path) -> Optional[Path]:
    """UE5 프로젝트 루트에서 소스 디렉토리를 자동 감지."""
    source = project_root / "Source"
    if not source.exists():
        return None
    subdirs = [d for d in source.iterdir() if d.is_dir() and not d.name.endswith("Editor")]
    return subdirs[0] if subdirs else source
