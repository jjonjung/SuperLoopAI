"""
UE5 Asset Naming Convention Linter
"""
import re
import anthropic
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from utils.file_utils import collect_assets

console = Console()

SUFFIX_TO_TYPE = {
    "_Anim":         "AnimSequence",
    "_PhysicsAsset": "PhysicsAsset",
    "_Skeleton":     "Skeleton",
}
PREFIX_PATTERN = re.compile(r"^([A-Z][A-Z0-9]*_)")


def _infer_type(name: str) -> str | None:
    for suffix, atype in SUFFIX_TO_TYPE.items():
        if name.endswith(suffix):
            return atype
    checks = [
        ("BP_", "Blueprint"), ("AM_", "AnimMontage"), ("ABP_", "AnimBlueprint"),
        ("MI_", "MaterialInstance"), ("MF_", "MaterialFunction"), ("M_", "Material"),
        ("T_", "Texture"), ("SM_", "StaticMesh"), ("SK_", "SkeletalMesh"),
        ("NS_", "NiagaraSystem"), ("WBP_", "Widget"), ("DA_", "DataAsset"),
        ("SC_", "SoundCue"), ("S_", "Sound"),
    ]
    for prefix, atype in checks:
        if name.startswith(prefix):
            return atype
    return None


def _check(path: Path, content_root: Path) -> dict | None:
    stem = path.stem
    rel  = str(path.relative_to(content_root))

    if stem[0].isdigit():
        return {"path": rel, "name": stem, "issue": "숫자로 시작하는 이름",
                "severity": "error", "suggestion": "적절한 접두사 추가 필요"}

    if " " in stem or "-" in stem:
        fixed = stem.replace(" ", "_").replace("-", "_")
        return {"path": rel, "name": stem, "issue": "공백/하이픈 포함",
                "severity": "error", "suggestion": f"→ {fixed}"}

    if stem[0].islower() and not PREFIX_PATTERN.match(stem):
        return {"path": rel, "name": stem, "issue": "소문자로 시작 (PascalCase 필요)",
                "severity": "warning",
                "suggestion": f"→ {stem[0].upper() + stem[1:]} 또는 접두사 추가"}

    if not PREFIX_PATTERN.match(stem):
        inferred = _infer_type(stem)
        if inferred:
            prefix = config.ASSET_PREFIXES.get(inferred, "??_")
            return {"path": rel, "name": stem,
                    "issue": f"접두사 없음 (추정: {inferred})",
                    "severity": "warning", "suggestion": f"→ {prefix}{stem}"}
    return None


def lint_assets(content_dir: Path | None = None, max_show: int = 60) -> None:
    root = content_dir or config.CONTENT_DIR
    if not root.exists():
        console.print(f"[red]Content 디렉토리를 찾을 수 없습니다: {root}[/red]")
        return

    console.print(Panel(
        f"[bold cyan]에셋 네이밍 린트[/bold cyan]  [dim]{config.PROJECT_NAME}[/dim]\n"
        f"[dim]{root}[/dim]", border_style="cyan"
    ))

    assets = collect_assets(root)
    console.print(f"[dim]{len(assets)}개 에셋 스캔 중...[/dim]\n")

    violations = [v for a in assets if (v := _check(a, root))]
    if not violations:
        console.print("[bold green]✓ 모든 에셋이 네이밍 컨벤션을 준수합니다![/bold green]")
        return

    errors   = [v for v in violations if v["severity"] == "error"]
    warnings = [v for v in violations if v["severity"] == "warning"]

    table = Table(
        title=f"위반: {len(errors)}개 오류 / {len(warnings)}개 경고",
        border_style="red"
    )
    table.add_column("심각도", width=10)
    table.add_column("에셋명", width=35)
    table.add_column("문제",   width=22)
    table.add_column("제안",   width=35)
    for v in violations[:max_show]:
        c    = "red" if v["severity"] == "error" else "yellow"
        icon = "🔴" if v["severity"] == "error" else "🟡"
        table.add_row(
            f"{icon} [{c}]{v['severity']}[/{c}]",
            v["name"], v["issue"], v["suggestion"]
        )
    console.print(table)
    if len(violations) > max_show:
        console.print(f"[dim]... 및 {len(violations) - max_show}개 추가 위반[/dim]")

    violation_text = "\n".join(
        f"- [{v['severity']}] {v['name']}: {v['issue']} → {v['suggestion']}"
        for v in violations[:40]
    )

    console.print()
    with Progress(SpinnerColumn(), TextColumn("[cyan]AI 우선순위 분석 중..."), console=console) as p:
        p.add_task("", total=None)
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=1500,
            system=config.ASSET_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"{config.PROJECT_NAME} UE5 프로젝트 에셋 네이밍 위반 {len(violations)}건.\n\n"
                    f"```\n{violation_text}\n```\n\n"
                    "1. 최우선 수정 항목 5개\n"
                    "2. 일괄 수정(Batch Rename) 가능한 패턴\n"
                    "3. 위반 주요 원인 분석"
                )
            }]
        )

    ai_text = response.content[0].text if response.content else ""
    console.print(Panel(ai_text, title="[bold cyan]AI 우선순위 분석[/bold cyan]", border_style="cyan"))
    console.print(f"\n[dim]총 {len(violations)}건 (errors: {len(errors)}, warnings: {len(warnings)})[/dim]\n")
