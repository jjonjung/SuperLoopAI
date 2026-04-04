"""
Scaffold Agent — UE5 C++ 보일러플레이트 생성기
UnrealMasterAI의 workflow/* 템플릿 개념을 Python AI 기반으로 구현.

지원 타입: character, skill, component, manager, gamemode
프로젝트의 기존 코드를 레퍼런스로 읽어 동일한 아키텍처/스타일로 생성.
"""
import anthropic
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from utils.file_utils import collect_cpp_files, read_source_file, find_file

console = Console()

# 타입별 레퍼런스 파일 힌트 (프로젝트에서 자동 탐색)
REFERENCE_HINTS: dict[str, list[str]] = {
    "character":  ["CharacterBase", "IronMan", "SpiderMan", "DoctorStrange", "Character"],
    "skill":      ["Skill1_IronMan", "Skill1_SpiderMan", "ActionBase", "DodgeAction"],
    "component":  ["ActionComponent", "AiBrainComponent", "CBrainComponent", "CharacterActionStat"],
    "manager":    ["BattleManager", "Manager"],
    "gamemode":   ["InfinityFightersGameModeBase", "GameModeBase", "GameMode"],
}

# 타입별 생성 위치 힌트
OUTPUT_SUBDIR: dict[str, str] = {
    "character": "Private/Chatacter",
    "skill":     "Private/Skill",
    "component": "Private/Component",
    "manager":   "",
    "gamemode":  "Private",
}

OUTPUT_HEADER_SUBDIR: dict[str, str] = {
    "character": "Public/Chatacter",
    "skill":     "Public/Skill",
    "component": "Public/Component",
    "manager":   "Public",
    "gamemode":  "Public",
}


def _find_references(scaffold_type: str, max_files: int = 3) -> list[tuple[str, str]]:
    """프로젝트에서 해당 타입의 레퍼런스 파일을 찾아 (이름, 내용) 쌍으로 반환."""
    hints = REFERENCE_HINTS.get(scaffold_type, [])
    results: list[tuple[str, str]] = []

    all_files = collect_cpp_files(config.SOURCE_DIR)

    for hint in hints:
        for p in all_files:
            if hint.lower() in p.stem.lower() and p.suffix == ".h":
                # 대응하는 .cpp 도 찾기
                cpp = find_file(p.stem + ".cpp", config.SOURCE_DIR)
                try:
                    h_content   = read_source_file(p, max_chars=3000)
                    cpp_content = read_source_file(cpp, max_chars=3000) if cpp else ""
                    combined = f"// === {p.name} ===\n{h_content}"
                    if cpp_content:
                        combined += f"\n\n// === {cpp.name} ===\n{cpp_content}"
                    results.append((p.stem, combined))
                except Exception:
                    pass
                if len(results) >= max_files:
                    return results

    return results


def scaffold(scaffold_type: str, class_name: str, extra_hint: str = "") -> None:
    """
    주어진 타입과 클래스명으로 UE5 C++ 보일러플레이트를 생성하고 파일로 저장.

    Args:
        scaffold_type: character | skill | component | manager | gamemode
        class_name:    생성할 클래스의 PascalCase 이름 (접두사 A/U 제외)
        extra_hint:    추가 컨텍스트 (예: "아이언맨 스킬, 발사체 3개 생성")
    """
    if scaffold_type not in REFERENCE_HINTS:
        valid = ", ".join(REFERENCE_HINTS.keys())
        console.print(f"[red]지원하지 않는 타입:[/red] {scaffold_type}  (지원: {valid})")
        return

    console.print(Panel(
        f"[bold cyan]Scaffold[/bold cyan]: [white]{scaffold_type} → {class_name}[/white]  "
        f"[dim]{config.PROJECT_NAME}[/dim]"
        + (f"\n[dim]{extra_hint}[/dim]" if extra_hint else ""),
        border_style="cyan"
    ))

    refs = _find_references(scaffold_type)
    ref_block = "\n\n".join(f"--- 레퍼런스: {name} ---\n{content}" for name, content in refs)

    if refs:
        console.print(f"[dim]레퍼런스 파일 {len(refs)}개 로드: {', '.join(n for n, _ in refs)}[/dim]")
    else:
        console.print("[yellow]레퍼런스 파일을 찾지 못했습니다. 일반 UE5 패턴으로 생성합니다.[/yellow]")

    # 접두사 결정
    prefix_map = {"character": "A", "skill": "U", "component": "U",
                  "manager": "A", "gamemode": "A"}
    ue5_prefix  = prefix_map.get(scaffold_type, "U")
    full_name   = f"{ue5_prefix}{class_name}"
    module_name = config.SOURCE_DIR.name.upper()  # e.g. INFINITYFIGHTER

    prompt = f"""프로젝트: {config.PROJECT_NAME}
모듈: {module_name}
생성 타입: {scaffold_type}
클래스 이름: {full_name}
추가 요구사항: {extra_hint if extra_hint else "없음"}

아래 레퍼런스 코드의 아키텍처, 인클루드 패턴, 컴포넌트 구조를 그대로 따라
{full_name}의 .h 파일과 .cpp 파일을 생성해 주세요.

{ref_block if ref_block else "레퍼런스 없음 — 표준 UE5 패턴 사용"}

출력 형식:
[헤더 파일 내용]
===CPP_FILE===
[소스 파일 내용]
"""

    client = anthropic.Anthropic()
    parts: list[str] = []

    with Progress(SpinnerColumn(), TextColumn(f"[cyan]{full_name} 코드 생성 중..."), console=console) as p:
        p.add_task("", total=None)
        with client.messages.stream(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=config.scaffold_system(config.PROJECT_NAME),
            messages=[{"role": "user", "content": prompt}]
        ) as stream:
            for text in stream.text_stream:
                parts.append(text)

    full_output = "".join(parts)

    # .h / .cpp 분리
    delimiter = "===CPP_FILE==="
    if delimiter in full_output:
        h_code, cpp_code = full_output.split(delimiter, 1)
    else:
        h_code   = full_output
        cpp_code = ""

    h_code   = h_code.strip()
    cpp_code = cpp_code.strip()

    # 파일 저장
    h_subdir   = OUTPUT_HEADER_SUBDIR.get(scaffold_type, "Public")
    cpp_subdir = OUTPUT_SUBDIR.get(scaffold_type, "Private")

    h_dir   = config.SOURCE_DIR / h_subdir
    cpp_dir = config.SOURCE_DIR / cpp_subdir
    h_dir.mkdir(parents=True, exist_ok=True)
    cpp_dir.mkdir(parents=True, exist_ok=True)

    h_path   = h_dir   / f"{full_name}.h"
    cpp_path = cpp_dir / f"{full_name}.cpp"

    h_path.write_text(h_code, encoding="utf-8")
    console.print(f"\n[green]✓ 헤더 저장:[/green] {h_path}")

    if cpp_code:
        cpp_path.write_text(cpp_code, encoding="utf-8")
        console.print(f"[green]✓ 소스 저장:[/green] {cpp_path}")

    # 미리보기
    console.print()
    console.rule("[bold white] 생성된 헤더 미리보기 [/bold white]")
    preview = "\n".join(h_code.splitlines()[:40])
    console.print(Syntax(preview, "cpp", theme="monokai", line_numbers=True))
    if len(h_code.splitlines()) > 40:
        console.print(f"[dim]... ({len(h_code.splitlines())}줄 전체)[/dim]")
    console.print()
