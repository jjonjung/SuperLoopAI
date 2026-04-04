"""
QA Scenario Generator Agent
"""
import anthropic
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from utils.file_utils import read_source_file

console = Console()

QA_TOOL = {
    "name": "submit_qa_scenarios",
    "description": "게임 QA 시나리오 목록을 구조화된 형식으로 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "feature_area": {"type": "string"},
            "scenarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":            {"type": "string"},
                        "title":         {"type": "string"},
                        "category":      {
                            "type": "string",
                            "enum": ["기능", "엣지케이스", "성능", "UI", "네트워크", "충돌"]
                        },
                        "priority":      {"type": "string", "enum": ["High", "Medium", "Low"]},
                        "preconditions": {"type": "array", "items": {"type": "string"}},
                        "steps":         {"type": "array", "items": {"type": "string"}},
                        "expected":      {"type": "string"},
                        "notes":         {"type": "string"}
                    },
                    "required": ["id", "title", "category", "priority", "preconditions", "steps", "expected"]
                }
            },
            "risk_areas": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["feature_area", "scenarios", "risk_areas"]
    }
}


def generate_qa(topic: str, source_file: Path | None = None) -> None:
    client = anthropic.Anthropic()

    code_context = ""
    if source_file and source_file.exists():
        code_context = f"\n\n관련 코드:\n```cpp\n{read_source_file(source_file)}\n```"

    console.print(Panel(
        f"[bold cyan]QA 시나리오 생성[/bold cyan]: [white]{topic}[/white]  "
        f"[dim]{config.PROJECT_NAME}[/dim]"
        + (f"\n[dim]코드 컨텍스트: {source_file.name}[/dim]" if source_file else ""),
        border_style="cyan"
    ))

    with Progress(SpinnerColumn(), TextColumn("[cyan]시나리오 생성 중..."), console=console) as p:
        p.add_task("", total=None)
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=config.qa_system(config.PROJECT_NAME),
            tools=[QA_TOOL],
            tool_choice={"type": "tool", "name": "submit_qa_scenarios"},
            messages=[{
                "role": "user",
                "content": (
                    f"다음 기능에 대한 QA 시나리오를 생성해 주세요.\n\n"
                    f"프로젝트: **{config.PROJECT_NAME}**\n"
                    f"기능 영역: **{topic}**{code_context}\n\n"
                    "High 우선순위 3개, Medium 3개, Low 2개 이상 포함해 주세요."
                )
            }]
        )

    result = next(
        (b.input for b in response.content if b.type == "tool_use" and b.name == "submit_qa_scenarios"),
        None
    )
    if not result:
        console.print("[red]응답 파싱 실패[/red]")
        return
    _render(result)


def _render(data: dict) -> None:
    priority_color = {"High": "red", "Medium": "yellow", "Low": "green"}
    category_icon  = {"기능": "⚙️", "엣지케이스": "⚠️", "성능": "⚡", "UI": "🖥️", "네트워크": "🌐", "충돌": "💥"}

    scenarios = data["scenarios"]
    console.print()
    console.rule(f"[bold white] QA 시나리오: {data['feature_area']} [/bold white]")

    table = Table(title=f"전체 {len(scenarios)}개 시나리오", border_style="cyan")
    table.add_column("ID",      style="dim", width=8)
    table.add_column("제목",    width=30)
    table.add_column("카테고리", width=10)
    table.add_column("우선순위", width=8)
    for s in scenarios:
        pc = priority_color.get(s["priority"], "white")
        table.add_row(
            s["id"], s["title"],
            f"{category_icon.get(s['category'], '')} {s['category']}",
            f"[{pc}]{s['priority']}[/{pc}]"
        )
    console.print(table)

    console.print("\n[bold]상세 시나리오[/bold]\n")
    for s in scenarios:
        pc   = priority_color.get(s["priority"], "white")
        pre  = "\n".join(f"  - {x}" for x in s["preconditions"])
        steps = "\n".join(f"  {i+1}. {x}" for i, x in enumerate(s["steps"]))
        notes = f"\n\n[dim]노트: {s['notes']}[/dim]" if s.get("notes") else ""
        console.print(Panel(
            f"[bold]사전 조건:[/bold]\n{pre}\n\n[bold]절차:[/bold]\n{steps}\n\n"
            f"[bold]기대 결과:[/bold] {s['expected']}{notes}",
            title=f"[{pc}]{s['id']}[/{pc}] {s['title']}", border_style=pc
        ))

    if data.get("risk_areas"):
        console.print("\n[bold red]리스크 영역[/bold red]")
        for risk in data["risk_areas"]:
            console.print(f"  [red]⚠[/red] {risk}")
    console.print()
