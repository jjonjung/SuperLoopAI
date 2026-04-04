"""
UE5 Platform Optimization Analyzer Agent
"""
import anthropic
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from utils.file_utils import read_source_file

console = Console()

OPTIMIZE_TOOL = {
    "name": "submit_optimization_report",
    "description": "UE5 C++ 최적화 분석 결과를 구조화된 형식으로 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary":       {"type": "string"},
            "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["Tick", "GC/Memory", "Rendering", "Physics",
                                     "Cast/Find", "String", "Threading", "Profiling"]
                        },
                        "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                        "platform": {"type": "string", "enum": ["mobile", "pc", "console", "all"]},
                        "location": {"type": "string"},
                        "problem":  {"type": "string"},
                        "fix":      {"type": "string"},
                        "impact":   {"type": "string"}
                    },
                    "required": ["category", "severity", "platform", "location", "problem", "fix", "impact"]
                }
            },
            "platform_notes": {
                "type": "object",
                "properties": {
                    "mobile":  {"type": "string"},
                    "pc":      {"type": "string"},
                    "console": {"type": "string"}
                }
            },
            "quick_wins": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["summary", "overall_score", "issues", "platform_notes", "quick_wins"]
    }
}


def analyze_optimization(file_path: Path, target: str = "all") -> None:
    if not file_path.exists():
        console.print(f"[red]오류:[/red] 파일을 찾을 수 없습니다: {file_path}")
        return

    code = read_source_file(file_path)
    platform_label = target.upper() if target != "all" else "ALL PLATFORMS"

    console.print(Panel(
        f"[bold cyan]최적화 분석[/bold cyan]: [white]{file_path.name}[/white]  "
        f"[dim]{config.PROJECT_NAME}[/dim]\n"
        f"[dim]플랫폼: [yellow]{platform_label}[/yellow] | {len(code.splitlines())}줄[/dim]",
        border_style="cyan"
    ))

    platform_instr = (
        f"분석 플랫폼: **{target}** 에 집중해서 분석해 주세요."
        if target != "all"
        else "Mobile / PC / Console 세 플랫폼 모두 분석해 주세요."
    )

    client = anthropic.Anthropic()
    with Progress(SpinnerColumn(), TextColumn("[cyan]최적화 분석 중..."), console=console) as p:
        p.add_task("", total=None)
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=config.optimizer_system(config.PROJECT_NAME),
            tools=[OPTIMIZE_TOOL],
            tool_choice={"type": "tool", "name": "submit_optimization_report"},
            messages=[{
                "role": "user",
                "content": (
                    f"다음 UE5 C++ 파일의 성능 최적화를 분석해 주세요.\n"
                    f"{platform_instr}\n\n"
                    f"파일: `{file_path.name}`\n\n```cpp\n{code}\n```"
                )
            }]
        )

    result = next(
        (b.input for b in response.content
         if b.type == "tool_use" and b.name == "submit_optimization_report"),
        None
    )
    if not result:
        console.print("[red]응답 파싱 실패[/red]")
        return

    _render(result, file_path.name, target)


def _render(r: dict, filename: str, target: str) -> None:
    sev_color  = {"critical": "red", "warning": "yellow", "info": "blue"}
    sev_icon   = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
    cat_icon   = {
        "Tick": "⏱", "GC/Memory": "🗑", "Rendering": "🎨", "Physics": "⚙",
        "Cast/Find": "🔍", "String": "📝", "Threading": "🧵", "Profiling": "📊"
    }
    plat_color = {"mobile": "green", "pc": "blue", "console": "magenta", "all": "white"}

    score = r["overall_score"]
    sc    = "green" if score >= 80 else ("yellow" if score >= 60 else "red")

    console.print()
    console.rule(f"[bold white] 최적화 분석: {filename} [/bold white]")
    console.print(Panel(
        f"[{sc}]최적화 점수: {score}/100[/{sc}]\n\n{r['summary']}",
        title="[bold]종합 평가[/bold]", border_style=sc
    ))

    issues = r.get("issues", [])
    if issues:
        table = Table(title=f"발견된 이슈 {len(issues)}건", border_style="cyan", show_lines=True)
        table.add_column("카테고리", width=12)
        table.add_column("심각도",   width=10)
        table.add_column("플랫폼",   width=9)
        table.add_column("위치",     width=22)
        table.add_column("문제",     width=36)
        for iss in issues:
            sev  = iss["severity"]
            plat = iss["platform"]
            table.add_row(
                f"{cat_icon.get(iss['category'], '')} {iss['category']}",
                f"[{sev_color[sev]}]{sev_icon[sev]} {sev}[/{sev_color[sev]}]",
                f"[{plat_color.get(plat,'white')}]{plat}[/{plat_color.get(plat,'white')}]",
                iss["location"],
                iss["problem"][:60]
            )
        console.print(table)

        console.print("\n[bold]상세 분석[/bold]\n")
        for iss in issues:
            c  = sev_color[iss["severity"]]
            pc = plat_color.get(iss["platform"], "white")
            console.print(Panel(
                f"[dim]위치: {iss['location']}  |  플랫폼: [{pc}]{iss['platform']}[/{pc}][/dim]\n\n"
                f"[bold red]문제:[/bold red] {iss['problem']}\n\n"
                f"[bold green]수정:[/bold green]\n{iss['fix']}\n\n"
                f"[bold yellow]예상 효과:[/bold yellow] {iss['impact']}",
                title=f"{sev_icon[iss['severity']]} [{c}]{iss['category']} — {iss['severity'].upper()}[/{c}]",
                border_style=c
            ))

    notes = r.get("platform_notes", {})
    if any(notes.values()):
        console.print("\n[bold]플랫폼별 노트[/bold]\n")
        for plat, note in notes.items():
            if note:
                pc = plat_color.get(plat, "white")
                console.print(Panel(note, title=f"[{pc}]{plat.upper()}[/{pc}]", border_style=pc))

    if r.get("quick_wins"):
        console.print("\n[bold green]Quick Win (즉시 적용 가능)[/bold green]")
        for i, w in enumerate(r["quick_wins"], 1):
            console.print(f"  [green]{i}.[/green] {w}")
    console.print()
