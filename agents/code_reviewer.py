"""
UE5 C++ Code Reviewer Agent
"""
import anthropic
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from utils.file_utils import read_source_file

console = Console()

REVIEW_TOOL = {
    "name": "submit_code_review",
    "description": "UE5 C++ 코드 리뷰 결과를 구조화된 형식으로 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity":    {"type": "string", "enum": ["critical", "warning", "info"]},
                        "line_hint":   {"type": "string"},
                        "description": {"type": "string"},
                        "suggestion":  {"type": "string"}
                    },
                    "required": ["severity", "line_hint", "description", "suggestion"]
                }
            },
            "ue5_compliance": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "notes": {"type": "string"}
                },
                "required": ["score", "notes"]
            },
            "performance_notes": {"type": "string"},
            "positive_aspects": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["summary", "issues", "ue5_compliance", "performance_notes", "positive_aspects"]
    }
}


def review_file(file_path: Path) -> None:
    if not file_path.exists():
        console.print(f"[red]오류:[/red] 파일을 찾을 수 없습니다: {file_path}")
        return

    code = read_source_file(file_path)
    console.print(Panel(
        f"[bold cyan]코드 리뷰[/bold cyan]: [white]{file_path.name}[/white]  "
        f"[dim]{config.PROJECT_NAME}[/dim]\n"
        f"[dim]{len(code.splitlines())}줄 | {len(code):,}자[/dim]",
        border_style="cyan"
    ))

    client = anthropic.Anthropic()
    with Progress(SpinnerColumn(), TextColumn("[cyan]Claude가 분석 중..."), console=console) as p:
        p.add_task("", total=None)
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=config.code_review_system(config.PROJECT_NAME),
            tools=[REVIEW_TOOL],
            tool_choice={"type": "tool", "name": "submit_code_review"},
            messages=[{
                "role": "user",
                "content": f"다음 UE5 C++ 파일을 리뷰해 주세요.\n\n파일: `{file_path.name}`\n\n```cpp\n{code}\n```"
            }]
        )

    result = next(
        (b.input for b in response.content if b.type == "tool_use" and b.name == "submit_code_review"),
        None
    )
    if not result:
        console.print("[red]응답 파싱 실패[/red]")
        return

    _render(result, file_path.name)


def _render(r: dict, filename: str) -> None:
    sev_color = {"critical": "red", "warning": "yellow", "info": "blue"}
    sev_icon  = {"critical": "🔴", "warning": "🟡", "info": "🔵"}

    score = r["ue5_compliance"]["score"]
    sc    = "green" if score >= 80 else ("yellow" if score >= 60 else "red")

    console.print()
    console.rule(f"[bold white] 리뷰 결과: {filename} [/bold white]")

    console.print(Panel(r["summary"], title="[bold]요약[/bold]", border_style="white"))
    console.print(Panel(
        f"[{sc}]UE5 준수도: {score}/100[/{sc}]\n{r['ue5_compliance']['notes']}",
        title="[bold]UE5 컴플라이언스[/bold]", border_style=sc
    ))

    if r["issues"]:
        console.print(f"\n[bold]발견된 문제점[/bold] ({len(r['issues'])}건)")
        for iss in r["issues"]:
            c = sev_color[iss["severity"]]
            console.print(Panel(
                f"[dim]{iss['line_hint']}[/dim]\n\n"
                f"[bold]문제:[/bold] {iss['description']}\n\n"
                f"[bold green]제안:[/bold green] {iss['suggestion']}",
                title=f"{sev_icon[iss['severity']]} [{c}]{iss['severity'].upper()}[/{c}]",
                border_style=c
            ))
    else:
        console.print("\n[green]발견된 문제점 없음[/green]")

    if r["positive_aspects"]:
        console.print("\n[bold green]잘된 점[/bold green]")
        for pos in r["positive_aspects"]:
            console.print(f"  [green]✓[/green] {pos}")

    if r["performance_notes"]:
        console.print(f"\n[bold yellow]성능 노트[/bold yellow]\n{r['performance_notes']}")
    console.print()
