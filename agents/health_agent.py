"""
Health Agent — 프로젝트 종합 진단 리포트
UnrealMasterAI의 analyze/* (asset-health, blueprint-complexity, code-conventions, performance-hints) 통합.

코드/에셋/구조/성능 리스크를 한 번에 스캔해 종합 점수와 우선순위 액션 아이템 제공.
"""
import re
from collections import Counter
from pathlib import Path

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from utils.file_utils import collect_cpp_files, collect_assets, read_source_file

console = Console()

HEALTH_TOOL = {
    "name": "submit_health_report",
    "description": "UE5 프로젝트 종합 건강도 리포트를 구조화된 형식으로 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "overall_grade": {"type": "string", "enum": ["S", "A", "B", "C", "D", "F"]},
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":    {"type": "string"},
                        "score":   {"type": "integer", "minimum": 0, "maximum": 100},
                        "status":  {"type": "string", "enum": ["good", "warning", "critical"]},
                        "finding": {"type": "string"},
                        "actions": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["name", "score", "status", "finding", "actions"]
                }
            },
            "top_risks": {
                "type": "array",
                "description": "당장 처리해야 할 최우선 리스크",
                "items": {"type": "string"}
            },
            "quick_wins": {
                "type": "array",
                "description": "1시간 내 처리 가능한 즉시 개선 항목",
                "items": {"type": "string"}
            }
        },
        "required": ["overall_score", "overall_grade", "categories", "top_risks", "quick_wins"]
    }
}


# ─── 로컬 메트릭 수집 ─────────────────────────────────────────────────────────

def _collect_code_metrics(source_dir: Path) -> dict:
    """C++ 소스에서 정량적 메트릭 수집."""
    files = collect_cpp_files(source_dir)
    headers = [f for f in files if f.suffix == ".h"]
    sources = [f for f in files if f.suffix == ".cpp"]

    todo_count    = 0
    fixme_count   = 0
    tick_classes  = []
    no_comment    = []   # 주석 없는 public 함수 근처
    long_files    = []   # 300줄 이상 .cpp
    gc_risks      = []   # Tick 내 NewObject/SpawnActor
    fstring_ticks = []   # Tick 내 FString

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        lines = text.splitlines()
        total = len(lines)

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "TODO" in stripped or "todo" in stripped:
                todo_count += 1
            if "FIXME" in stripped or "fixme" in stripped:
                fixme_count += 1

        # 300줄 이상 .cpp
        if f.suffix == ".cpp" and total > 300:
            long_files.append((f.name, total))

        # Tick 사용 클래스
        if "TickComponent" in text or "Tick(float" in text:
            if "bCanEverTick = true" in text:
                tick_classes.append(f.stem)

            # Tick 함수 내 GC 압박
            in_tick = False
            for line in lines:
                if "TickComponent" in line or "::Tick(" in line:
                    in_tick = True
                if in_tick:
                    if "NewObject" in line or "SpawnActor" in line:
                        gc_risks.append(f"{f.stem}: {line.strip()[:60]}")
                    if "FString(" in line and "TEXT(" not in line:
                        fstring_ticks.append(f"{f.stem}: {line.strip()[:60]}")
                if in_tick and line.strip() == "}":
                    in_tick = False

    # 에셋 메트릭
    asset_violations = 0
    asset_total      = 0
    if config.CONTENT_DIR.exists():
        assets = collect_assets(config.CONTENT_DIR)
        asset_total = len(assets)
        for a in assets:
            stem = a.stem
            if stem and (stem[0].isdigit() or stem[0].islower() or " " in stem or "-" in stem):
                asset_violations += 1

    # Blueprint .uasset 추정 (BP_ 접두사)
    bp_count = 0
    if config.CONTENT_DIR.exists():
        bp_count = sum(1 for a in collect_assets(config.CONTENT_DIR) if a.stem.startswith("BP_"))

    return {
        "total_files":      len(files),
        "header_count":     len(headers),
        "source_count":     len(sources),
        "todo_count":       todo_count,
        "fixme_count":      fixme_count,
        "tick_classes":     tick_classes[:10],
        "gc_risks":         gc_risks[:5],
        "fstring_ticks":    fstring_ticks[:5],
        "long_files":       long_files[:5],
        "asset_total":      asset_total,
        "asset_violations": asset_violations,
        "bp_count":         bp_count,
    }


def _sample_code_snippets(source_dir: Path, n: int = 4) -> str:
    """대표 파일 샘플을 AI에게 제공할 컨텍스트로 추출."""
    files = collect_cpp_files(source_dir)
    # 헤더 중 중요해 보이는 것 우선
    priority = ["Manager", "Base", "Component", "Controller", "GameMode"]
    selected: list[Path] = []
    for hint in priority:
        for f in files:
            if hint in f.stem and f.suffix == ".h" and f not in selected:
                selected.append(f)
                if len(selected) >= n:
                    break
        if len(selected) >= n:
            break
    # 부족하면 임의 추가
    for f in files:
        if f not in selected and f.suffix == ".h":
            selected.append(f)
        if len(selected) >= n:
            break

    snippets = []
    for f in selected:
        try:
            content = read_source_file(f, max_chars=1500)
            snippets.append(f"// === {f.name} ===\n{content}")
        except Exception:
            pass
    return "\n\n".join(snippets)


# ─── 렌더링 ──────────────────────────────────────────────────────────────────

def _render_report(r: dict, metrics: dict) -> None:
    grade_color = {"S": "bold green", "A": "green", "B": "cyan",
                   "C": "yellow", "D": "red", "F": "bold red"}
    status_color = {"good": "green", "warning": "yellow", "critical": "red"}
    status_icon  = {"good": "✓", "warning": "⚠", "critical": "✗"}

    score = r["overall_score"]
    grade = r["overall_grade"]
    gc    = grade_color.get(grade, "white")
    sc    = "green" if score >= 80 else ("yellow" if score >= 60 else "red")

    console.print()
    console.rule("[bold white] 프로젝트 건강도 리포트 [/bold white]")

    # 종합 점수
    console.print(Panel(
        f"[{sc}]종합 점수: {score}/100[/{sc}]   [{gc}]등급: {grade}[/{gc}]\n\n"
        f"[dim]파일: {metrics['total_files']}개 | "
        f"TODO/FIXME: {metrics['todo_count']+metrics['fixme_count']}건 | "
        f"에셋: {metrics['asset_total']}개 (위반: {metrics['asset_violations']}건) | "
        f"BP: {metrics['bp_count']}개[/dim]",
        title="[bold]종합 평가[/bold]", border_style=sc
    ))

    # 카테고리 테이블
    cats = r.get("categories", [])
    if cats:
        table = Table(title="카테고리별 점수", border_style="cyan")
        table.add_column("카테고리",  width=20)
        table.add_column("점수",      width=8)
        table.add_column("상태",      width=10)
        table.add_column("핵심 발견", width=46)
        for cat in cats:
            st = cat["status"]
            sc2 = status_color.get(st, "white")
            table.add_row(
                cat["name"],
                f"[{sc2}]{cat['score']}/100[/{sc2}]",
                f"[{sc2}]{status_icon[st]} {st}[/{sc2}]",
                cat["finding"][:80]
            )
        console.print(table)

    # 카테고리 상세
    console.print("\n[bold]카테고리 상세 및 액션 아이템[/bold]\n")
    for cat in cats:
        st    = cat["status"]
        color = status_color.get(st, "white")
        actions_text = "\n".join(f"  • {a}" for a in cat.get("actions", []))
        console.print(Panel(
            f"{cat['finding']}\n\n[bold]액션:[/bold]\n{actions_text}",
            title=f"[{color}]{status_icon[st]} {cat['name']} ({cat['score']}/100)[/{color}]",
            border_style=color
        ))

    # Top Risks
    if r.get("top_risks"):
        console.print("\n[bold red]즉시 처리 필요 (Top Risks)[/bold red]")
        for i, risk in enumerate(r["top_risks"], 1):
            console.print(f"  [red]{i}.[/red] {risk}")

    # Quick Wins
    if r.get("quick_wins"):
        console.print("\n[bold green]Quick Win (1시간 내 개선 가능)[/bold green]")
        for i, win in enumerate(r["quick_wins"], 1):
            console.print(f"  [green]{i}.[/green] {win}")
    console.print()


# ─── 진입점 ──────────────────────────────────────────────────────────────────

def run_health_check() -> None:
    """프로젝트 종합 건강도 검사를 실행하고 리포트를 출력."""
    console.print(Panel(
        f"[bold cyan]프로젝트 건강도 진단[/bold cyan]  [dim]{config.PROJECT_NAME}[/dim]\n"
        f"[dim]{config.SOURCE_DIR}[/dim]",
        border_style="cyan"
    ))

    with Progress(SpinnerColumn(), TextColumn("[cyan]메트릭 수집 중..."), console=console) as p:
        p.add_task("", total=None)
        metrics = _collect_code_metrics(config.SOURCE_DIR)
        snippets = _sample_code_snippets(config.SOURCE_DIR)

    # 메트릭 요약 문자열
    metrics_summary = f"""
프로젝트: {config.PROJECT_NAME}

[코드 메트릭]
- 전체 파일: {metrics['total_files']}개 (헤더: {metrics['header_count']}, 소스: {metrics['source_count']})
- TODO: {metrics['todo_count']}건 / FIXME: {metrics['fixme_count']}건
- Tick 사용 클래스: {len(metrics['tick_classes'])}개 — {', '.join(metrics['tick_classes'][:5])}
- Tick 내 GC 위험: {len(metrics['gc_risks'])}건
- Tick 내 FString: {len(metrics['fstring_ticks'])}건
- 300줄 이상 .cpp: {len(metrics['long_files'])}개 — {', '.join(f"{n}({l}줄)" for n,l in metrics['long_files'][:3])}

[에셋 메트릭]
- 전체 에셋: {metrics['asset_total']}개
- 네이밍 위반: {metrics['asset_violations']}건
- Blueprint 에셋(BP_): {metrics['bp_count']}개

[샘플 코드]
{snippets[:4000]}
""".strip()

    with Progress(SpinnerColumn(), TextColumn("[cyan]AI 건강도 분석 중..."), console=console) as p:
        p.add_task("", total=None)
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=config.health_system(config.PROJECT_NAME),
            tools=[HEALTH_TOOL],
            tool_choice={"type": "tool", "name": "submit_health_report"},
            messages=[{
                "role": "user",
                "content": (
                    f"아래 UE5 프로젝트 메트릭을 바탕으로 종합 건강도 리포트를 작성해 주세요.\n\n"
                    f"{metrics_summary}"
                )
            }]
        )

    result = next(
        (b.input for b in response.content
         if b.type == "tool_use" and b.name == "submit_health_report"),
        None
    )
    if not result:
        console.print("[red]응답 파싱 실패[/red]")
        return

    _render_report(result, metrics)
