"""
Refactor Agent — 심볼 리네임 + 전체 참조 영향 분석
UnrealMasterAI의 refactor/rename-chain 개념을 Python AI 기반으로 구현.

1. 프로젝트 전체 .h/.cpp에서 old_name 참조를 grep
2. 참조 종류 분류 (정의, include, 사용부, macro, forward decl)
3. AI가 파일별 정확한 수정 계획 생성
4. 선택적으로 실제 파일 수정 적용 (--apply 플래그)
"""
import re
import anthropic
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

import config
from utils.file_utils import collect_cpp_files, read_source_file

console = Console()

# 참조 종류 분류 정규식
REF_PATTERNS: dict[str, re.Pattern] = {
    "정의":          re.compile(r"\bclass\s+\w*API\w*\s+{old}\b|\bstruct\s+{old}\b|\benum\s+class\s+{old}\b"),
    "include":       re.compile(r'#include\s+["\<][^">\n]*{old}[^">\n]*["\>]'),
    "UCLASS/USTRUCT":re.compile(r"U(?:CLASS|STRUCT|ENUM|INTERFACE)\s*\([^)]*\)\s*\n\s*(?:class|struct|enum)\s+\w*\s+{old}"),
    "forward decl":  re.compile(r"\bclass\s+{old}\s*;|\bstruct\s+{old}\s*;"),
    "사용":          re.compile(r"\b{old}\b"),
}

REFACTOR_TOOL = {
    "name": "submit_refactor_plan",
    "description": "UE5 심볼 리네임 리팩터링 계획을 구조화된 형식으로 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
            "ue5_warnings": {
                "type": "array",
                "description": "UE5 특유의 주의사항 (Blueprint redirector, CDO 이슈 등)",
                "items": {"type": "string"}
            },
            "file_changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file":        {"type": "string"},
                        "change_type": {"type": "string",
                                        "enum": ["rename_file", "update_content", "both"]},
                        "new_filename":{"type": "string"},
                        "replacements":{
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "old": {"type": "string"},
                                    "new": {"type": "string"},
                                    "reason": {"type": "string"}
                                },
                                "required": ["old", "new", "reason"]
                            }
                        }
                    },
                    "required": ["file", "change_type", "replacements"]
                }
            },
            "manual_steps": {
                "type": "array",
                "description": "에디터에서 수동으로 해야 할 작업 (Blueprint 등)",
                "items": {"type": "string"}
            }
        },
        "required": ["summary", "risk_level", "ue5_warnings", "file_changes", "manual_steps"]
    }
}


def _grep_references(old_name: str) -> dict[str, list[tuple[str, int, str]]]:
    """
    모든 소스 파일에서 old_name을 검색.
    반환: {파일경로: [(참조종류, 라인번호, 라인내용), ...]}
    """
    results: dict[str, list[tuple[str, int, str]]] = {}
    files = collect_cpp_files(config.SOURCE_DIR)

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        file_refs: list[tuple[str, int, str]] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            if old_name not in line:
                continue
            ref_type = "사용"
            for rtype, pat in REF_PATTERNS.items():
                if rtype == "사용":
                    continue
                compiled = re.compile(pat.pattern.replace("{old}", re.escape(old_name)))
                if compiled.search(line):
                    ref_type = rtype
                    break
            file_refs.append((ref_type, lineno, line.rstrip()))

        if file_refs:
            results[str(f.relative_to(config.SOURCE_DIR))] = file_refs

    return results


def _apply_changes(file_changes: list[dict]) -> None:
    """plan의 file_changes를 실제로 파일에 적용."""
    for change in file_changes:
        rel_path = change["file"]
        abs_path = config.SOURCE_DIR / rel_path
        if not abs_path.exists():
            console.print(f"[yellow]스킵 (파일 없음):[/yellow] {rel_path}")
            continue

        text = abs_path.read_text(encoding="utf-8", errors="replace")
        original = text
        for rep in change.get("replacements", []):
            text = text.replace(rep["old"], rep["new"])

        if text != original:
            abs_path.write_text(text, encoding="utf-8")
            console.print(f"  [green]✓[/green] {rel_path}")

        if change.get("change_type") in ("rename_file", "both") and change.get("new_filename"):
            new_path = abs_path.parent / change["new_filename"]
            abs_path.rename(new_path)
            console.print(f"  [green]→[/green] {rel_path}  →  {change['new_filename']}")


def analyze_refactor(old_name: str, new_name: str, apply: bool = False) -> None:
    """심볼 리네임 영향 분석 + AI 리팩터링 계획 생성."""
    console.print(Panel(
        f"[bold cyan]리팩터링 분석[/bold cyan]  [dim]{config.PROJECT_NAME}[/dim]\n"
        f"[white]{old_name}[/white]  →  [green]{new_name}[/green]",
        border_style="cyan"
    ))

    with Progress(SpinnerColumn(), TextColumn("[cyan]참조 스캔 중..."), console=console) as p:
        p.add_task("", total=None)
        refs = _grep_references(old_name)

    if not refs:
        console.print(f"[yellow]'{old_name}' 참조를 찾지 못했습니다.[/yellow]")
        return

    # 참조 요약 테이블
    total_refs = sum(len(v) for v in refs.values())
    table = Table(title=f"참조 발견: {len(refs)}개 파일 / {total_refs}건", border_style="cyan")
    table.add_column("파일",      width=40)
    table.add_column("참조 수",   width=8)
    table.add_column("종류",      width=30)
    for fpath, file_refs in refs.items():
        types = ", ".join(sorted({r[0] for r in file_refs}))
        table.add_row(fpath, str(len(file_refs)), types)
    console.print(table)

    # AI에 넘길 컨텍스트: 파일별 참조 라인
    ref_context = ""
    for fpath, file_refs in list(refs.items())[:15]:  # 최대 15개 파일
        ref_context += f"\n### {fpath}\n"
        for rtype, lineno, line in file_refs[:10]:
            ref_context += f"  L{lineno} [{rtype}]: {line}\n"

    client = anthropic.Anthropic()
    with Progress(SpinnerColumn(), TextColumn("[cyan]AI 리팩터링 계획 생성 중..."), console=console) as p:
        p.add_task("", total=None)
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=config.refactor_system(config.PROJECT_NAME),
            tools=[REFACTOR_TOOL],
            tool_choice={"type": "tool", "name": "submit_refactor_plan"},
            messages=[{
                "role": "user",
                "content": (
                    f"프로젝트: {config.PROJECT_NAME}\n"
                    f"리네임: `{old_name}` → `{new_name}`\n\n"
                    f"발견된 참조:\n{ref_context}\n\n"
                    "각 파일에서 정확히 어떤 텍스트를 어떻게 바꿔야 하는지,\n"
                    "UE5 특유의 주의사항(redirector, Blueprint 등)과 함께 계획을 제출해 주세요."
                )
            }]
        )

    plan = next(
        (b.input for b in response.content
         if b.type == "tool_use" and b.name == "submit_refactor_plan"),
        None
    )
    if not plan:
        console.print("[red]계획 파싱 실패[/red]")
        return

    _render_plan(plan, old_name, new_name)

    # apply 여부
    if apply and plan.get("file_changes"):
        console.print()
        if Confirm.ask(f"[yellow]실제로 {len(plan['file_changes'])}개 파일에 변경을 적용할까요?[/yellow]"):
            console.print("\n[bold]변경 적용 중...[/bold]")
            _apply_changes(plan["file_changes"])
            console.print("\n[bold green]✓ 적용 완료[/bold green]")
        else:
            console.print("[dim]적용 취소됨[/dim]")
    elif not apply:
        console.print(
            "\n[dim]실제 적용하려면 --apply 플래그를 추가하세요.[/dim]"
        )


def _render_plan(plan: dict, old_name: str, new_name: str) -> None:
    risk_color = {"low": "green", "medium": "yellow", "high": "red"}
    rc = risk_color.get(plan["risk_level"], "white")

    console.print()
    console.rule("[bold white] 리팩터링 계획 [/bold white]")

    console.print(Panel(
        f"[{rc}]위험도: {plan['risk_level'].upper()}[/{rc}]\n\n{plan['summary']}",
        title="[bold]요약[/bold]", border_style=rc
    ))

    if plan.get("ue5_warnings"):
        console.print("\n[bold yellow]UE5 주의사항[/bold yellow]")
        for w in plan["ue5_warnings"]:
            console.print(f"  [yellow]⚠[/yellow] {w}")

    changes = plan.get("file_changes", [])
    if changes:
        table = Table(title=f"변경 파일 {len(changes)}개", border_style="cyan", show_lines=True)
        table.add_column("파일",        width=38)
        table.add_column("변경 타입",   width=14)
        table.add_column("치환 건수",   width=8)
        table.add_column("새 파일명",   width=26)
        for ch in changes:
            table.add_row(
                ch["file"],
                ch["change_type"],
                str(len(ch.get("replacements", []))),
                ch.get("new_filename", "-")
            )
        console.print(table)

        # 상세 치환 내용
        console.print("\n[bold]치환 상세[/bold]")
        for ch in changes:
            reps = ch.get("replacements", [])
            if not reps:
                continue
            console.print(f"\n[cyan]{ch['file']}[/cyan]")
            for rep in reps:
                console.print(
                    f"  [red]-[/red] {rep['old']}\n"
                    f"  [green]+[/green] {rep['new']}\n"
                    f"  [dim]  → {rep['reason']}[/dim]"
                )

    if plan.get("manual_steps"):
        console.print("\n[bold red]수동 처리 필요 (에디터)[/bold red]")
        for i, step in enumerate(plan["manual_steps"], 1):
            console.print(f"  [red]{i}.[/red] {step}")
    console.print()
