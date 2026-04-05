#!/usr/bin/env python3
"""
GameAITool - UE5 Game Development AI Assistant
어떤 UE5 프로젝트에서도 사용 가능한 AI 개발 자동화 CLI 툴.

Global option:
  --project PATH   UE5 프로젝트 루트 지정 (기본: 현재 디렉토리 또는 자동 감지)

Commands:
  review    UE5 C++ 코드 AI 리뷰
  optimize  플랫폼별 성능 최적화 분석
  qa        QA 시나리오 자동 생성
  lint      에셋 네이밍 컨벤션 린트
  doc       헤더 파일 문서 자동 생성
  workflow  코드 리뷰 + 최적화 + QA + 문서 통합 파이프라인
"""
import sys
import io
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import click
from rich.console import Console
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent))

import config
from utils.file_utils import detect_ue5_project, detect_source_dir, find_file

console = Console()


def _init_project(project_path: str | None) -> None:
    """
    프로젝트 경로를 확정하고 config 모듈에 전역 변수로 주입.

    경로 결정 우선순위:
      1. --project로 직접 .uproject가 있는 디렉토리 지정
      2. --project로 레포 루트 지정 → 내부 .uproject 자동 탐색
      3. 현재 디렉토리부터 상/하 방향으로 .uproject 탐색
      4. 탐색 실패 시 현재 디렉토리 사용
    """
    start = Path(project_path).resolve() if project_path else Path.cwd()

    # .uproject가 바로 있으면 그 디렉토리가 UE5 루트
    if list(start.glob("*.uproject")):
        root = start
    else:
        detected = detect_ue5_project(start)
        root = detected if detected else start

    config.PROJECT_DIR  = root
    config.CONTENT_DIR  = root / "Content"
    config.PROJECT_NAME = root.name

    src = detect_source_dir(root)
    config.SOURCE_DIR   = src if src else root / "Source"


# ─── CLI group ───────────────────────────────────────────────────────────────
@click.group()
@click.version_option("1.0.0", prog_name="gameaitool")
@click.option("--project", "-P", default=None, metavar="PATH",
              help="UE5 프로젝트 루트 경로 (기본: 자동 감지)")
@click.pass_context
def cli(ctx: click.Context, project: str | None):
    """GameAITool — UE5 프로젝트 AI 개발 자동화 툴"""
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    _init_project(project)

    console.print(Panel(
        f"[bold cyan]GameAITool[/bold cyan]  "
        f"[white]{config.PROJECT_NAME}[/white]\n"
        f"[dim]{config.PROJECT_DIR}[/dim]\n"
        f"[dim]Source: {config.SOURCE_DIR}[/dim]",
        border_style="cyan"
    ))


def _resolve_file(file: str | None, path: str | None) -> Path | None:
    if path:
        return Path(path).resolve()
    if file:
        found = find_file(file, config.SOURCE_DIR)
        if not found:
            console.print(f"[red]파일을 찾을 수 없습니다:[/red] {file}")
            console.print(f"[dim]SOURCE_DIR: {config.SOURCE_DIR}[/dim]")
        return found
    console.print("[red]파일명 또는 --path 옵션이 필요합니다.[/red]")
    return None


# ─── review ──────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("file", required=False)
@click.option("--path", "-p", type=click.Path(), default=None)
def review(file, path):
    """UE5 C++ 파일 AI 코드 리뷰.

    \b
    Examples:
      gameaitool review BattleManager.cpp
      gameaitool --project ../MyGame review PlayerCharacter.cpp
    """
    from agents.code_reviewer import review_file
    target = _resolve_file(file, path)
    if target:
        review_file(target)


# ─── optimize ────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("file", required=False)
@click.option("--path", "-p", type=click.Path(), default=None)
@click.option("--target", "-t",
              type=click.Choice(["mobile", "pc", "console", "all"], case_sensitive=False),
              default="all", show_default=True)
def optimize(file, path, target):
    """UE5 C++ 파일 플랫폼별 성능 최적화 분석.

    \b
    Examples:
      gameaitool optimize AiBrainComponent.cpp --target mobile
      gameaitool --project ../MyGame optimize CharacterBase.cpp --target pc
    """
    from agents.optimizer import analyze_optimization
    fp = _resolve_file(file, path)
    if fp:
        analyze_optimization(fp, target)


# ─── qa ──────────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("topic")
@click.option("--file", "-f", type=click.Path(), default=None,
              help="관련 소스 파일 (선택)")
def qa(topic, file):
    """기능별 QA 시나리오 자동 생성.

    \b
    Examples:
      gameaitool qa "킬/데스 집계 시스템"
      gameaitool qa "캐릭터 스킬" --file CharacterBase.h
      gameaitool --project ../MyGame qa "인벤토리 기능"
    """
    from agents.qa_agent import generate_qa
    source_path = None
    if file:
        p = Path(file)
        source_path = p if p.is_absolute() and p.exists() else find_file(file, config.SOURCE_DIR)
    generate_qa(topic, source_path)


# ─── lint ────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--dir", "-d", type=click.Path(), default=None,
              help="검사 대상 디렉토리 (기본: 프로젝트 Content)")
@click.option("--max", "max_show", default=60, show_default=True)
def lint(dir, max_show):
    """UE5 에셋 네이밍 컨벤션 린트 (Epic Games 표준).

    \b
    Examples:
      gameaitool lint
      gameaitool --project ../MyGame lint
      gameaitool lint --dir Content/Characters
    """
    from agents.asset_linter import lint_assets
    lint_assets(Path(dir) if dir else None, max_show)


# ─── doc ─────────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("header")
@click.option("--out", "-o", type=click.Path(), default=None)
def doc(header, out):
    """C++ 헤더 파일 → 한국어 개발자 문서 자동 생성.

    \b
    Examples:
      gameaitool doc BattleManager.h
      gameaitool --project ../MyGame doc PlayerController.h --out docs/PlayerController.md
    """
    from agents.doc_agent import generate_doc
    p = Path(header)
    if not p.is_absolute():
        found = find_file(header, config.SOURCE_DIR)
        p = found if found else config.SOURCE_DIR / header
    generate_doc(p, Path(out) if out else None)


# ─── workflow ────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("file")
@click.option("--target", "-t",
              type=click.Choice(["mobile", "pc", "console", "all"], case_sensitive=False),
              default="all", show_default=True)
def workflow(file, target):
    """코드 리뷰 + 최적화 + QA + 문서화 통합 파이프라인.

    \b
    Examples:
      gameaitool workflow BattleManager
      gameaitool --project ../MyGame workflow PlayerCharacter --target mobile
    """
    from agents.code_reviewer import review_file
    from agents.optimizer    import analyze_optimization
    from agents.qa_agent     import generate_qa
    from agents.doc_agent    import generate_doc

    cpp = find_file(file + ".cpp", config.SOURCE_DIR) or find_file(file, config.SOURCE_DIR)
    h   = find_file(file + ".h",   config.SOURCE_DIR) or find_file(file, config.SOURCE_DIR)

    if not cpp and not h:
        console.print(f"[red]'{file}' 소스 파일을 찾을 수 없습니다.[/red]")
        raise SystemExit(1)

    console.print(Panel(
        f"[bold white]통합 워크플로우[/bold white]  "
        f"[dim]{file} | {config.PROJECT_NAME} | {target.upper()}[/dim]\n\n"
        "[cyan]Step 1[/cyan] 코드 리뷰\n"
        "[cyan]Step 2[/cyan] 최적화 분석\n"
        "[cyan]Step 3[/cyan] QA 시나리오\n"
        "[cyan]Step 4[/cyan] 개발자 문서",
        border_style="white"
    ))

    src = cpp or h

    console.rule("[bold cyan] Step 1 / 4 : 코드 리뷰 [/bold cyan]")
    review_file(src)

    console.rule("[bold cyan] Step 2 / 4 : 최적화 분석 [/bold cyan]")
    analyze_optimization(src, target)

    console.rule("[bold cyan] Step 3 / 4 : QA 시나리오 [/bold cyan]")
    generate_qa(f"{Path(file).stem} 기능", src)

    if h:
        console.rule("[bold cyan] Step 4 / 4 : 문서 생성 [/bold cyan]")
        out_dir = config.PROJECT_DIR / "docs" / "ai_generated"
        generate_doc(h, out_dir / (Path(file).stem + ".md"))

    console.print(Panel(
        "[bold green]✓ 워크플로우 완료[/bold green]",
        border_style="green"
    ))


# ─── scaffold ────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("scaffold_type",
                metavar="TYPE",
                type=click.Choice(["character", "skill", "component", "manager", "gamemode"],
                                  case_sensitive=False))
@click.argument("class_name", metavar="NAME")
@click.option("--hint", "-h", default="", help="추가 요구사항 (예: '발사체 3개 생성, 재장전 쿨타임 포함')")
def scaffold(scaffold_type, class_name, hint):
    """프로젝트 패턴 기반 UE5 C++ 보일러플레이트 생성.

    \b
    TYPE: character | skill | component | manager | gamemode
    NAME: 생성할 클래스명 (PascalCase, A/U 접두사 제외)

    \b
    Examples:
      gameaitool scaffold character SpiderMan2
      gameaitool scaffold skill IceBlast --hint "발사체 3발, 쿨타임 5초"
      gameaitool scaffold component HealthRegen
      gameaitool --project ../MyGame scaffold character Warrior
    """
    from agents.scaffold_agent import scaffold as do_scaffold
    do_scaffold(scaffold_type, class_name, hint)


# ─── refactor ────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("old_name")
@click.argument("new_name")
@click.option("--apply", is_flag=True, default=False,
              help="분석 후 실제 파일에 변경 적용 (기본: 분석만)")
def refactor(old_name, new_name, apply):
    """심볼 리네임 전체 참조 분석 + AI 리팩터링 계획 생성.

    \b
    Examples:
      gameaitool refactor BattleManager BattleCoordinator
      gameaitool refactor OnCharacterKilled OnCharacterDied --apply
      gameaitool --project ../MyGame refactor OldClass NewClass
    """
    from agents.refactor_agent import analyze_refactor
    analyze_refactor(old_name, new_name, apply)


# ─── health ───────────────────────────────────────────────────────────────────
@cli.command()
def health():
    """프로젝트 종합 건강도 진단 (코드 + 에셋 + 성능 + 아키텍처).

    \b
    Examples:
      gameaitool health
      gameaitool --project ../MyGame health
    """
    from agents.health_agent import run_health_check
    run_health_check()


if __name__ == "__main__":
    cli()
