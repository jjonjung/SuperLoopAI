"""
Documentation Generator Agent — streams Markdown from C++ headers.
"""
import anthropic
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from utils.file_utils import read_source_file

console = Console()


def generate_doc(header_path: Path, output_path: Path | None = None) -> None:
    if not header_path.exists():
        console.print(f"[red]오류:[/red] 헤더 파일을 찾을 수 없습니다: {header_path}")
        return

    code = read_source_file(header_path)
    console.print(Panel(
        f"[bold cyan]문서 생성[/bold cyan]: [white]{header_path.name}[/white]  "
        f"[dim]{config.PROJECT_NAME}[/dim]",
        border_style="cyan"
    ))

    client = anthropic.Anthropic()
    parts = []

    with Progress(SpinnerColumn(), TextColumn("[cyan]문서 생성 중..."), console=console) as p:
        p.add_task("", total=None)
        with client.messages.stream(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=config.doc_system(config.PROJECT_NAME),
            messages=[{
                "role": "user",
                "content": (
                    f"다음 UE5 C++ 헤더 파일의 개발자 문서를 Markdown으로 작성해 주세요.\n\n"
                    f"프로젝트: {config.PROJECT_NAME}\n"
                    f"파일: `{header_path.name}`\n\n```cpp\n{code}\n```\n\n"
                    "구조: # 클래스명, ## 개요, ## 상속 구조, ## 주요 기능, "
                    "## UPROPERTY / UFUNCTION 목록 (표), ## 사용 예시, ## 주의사항"
                )
            }]
        ) as stream:
            for text in stream.text_stream:
                parts.append(text)

    doc_md = "".join(parts)

    console.print()
    console.rule(f"[bold white] {header_path.name} 문서 [/bold white]")
    console.print(Markdown(doc_md))

    if output_path is None:
        output_path = header_path.parent / (header_path.stem + "_doc.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc_md, encoding="utf-8")
    console.print(f"\n[green]✓ 저장됨:[/green] {output_path}\n")
