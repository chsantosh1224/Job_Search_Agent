"""CLI.

    python main.py run               # Exa discovery -> board expansion -> liveness -> export
    python main.py run --skip-exa    # re-check known boards + stored jobs only (no Exa cost)
    python main.py export            # rewrite output/jobs.csv + jobs.json from the database
    python main.py add-board URL     # seed a company board by any of its job/board URLs
    python main.py ui                # web UI at http://127.0.0.1:8765
"""

import asyncio
import logging

import typer
from dotenv import load_dotenv

import ats
from export import export as export_jobs
from pipeline import run_pipeline
from settings import HERE, load_config
from store import Store

app = typer.Typer(add_completion=False, no_args_is_help=True)
CONFIG = typer.Option(str(HERE / "config.yaml"))


def _print_event(e: dict) -> None:
    if e["type"] == "stage" and e["state"] != "start":
        extra = {k: v for k, v in e.items() if k not in ("type", "stage", "state")}
        typer.echo(f"{e['stage']:>9}: {e['state']} {extra or ''}")


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v")):
    load_dotenv(HERE / ".env")
    load_dotenv()
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@app.command()
def run(
    skip_exa: bool = typer.Option(False, help="Skip Exa; only re-check known boards and jobs."),
    playwright: bool = typer.Option(True, help="Use Playwright for JS-rendered pages if installed."),
    include_unknown: bool = typer.Option(False, help="Also export jobs whose liveness is unknown."),
    config: str = CONFIG,
):
    """Discover, expand, check liveness, export."""
    try:
        summary = asyncio.run(run_pipeline(
            load_config(config), skip_exa=skip_exa, playwright=playwright,
            include_unknown=include_unknown, emit=_print_event,
        ))
    except RuntimeError as e:
        raise typer.BadParameter(str(e))
    typer.echo(f"Exported {summary['exported']} jobs -> {summary['csv']} , {summary['json']}")


@app.command()
def export(include_unknown: bool = typer.Option(False), config: str = CONFIG):
    """Re-export jobs.csv / jobs.json from the database."""
    cfg = load_config(config)
    store = Store(cfg.path(cfg.db_path))
    n, csv_path, json_path = export_jobs(store, cfg.path(cfg.out_dir), include_unknown)
    store.close()
    typer.echo(f"Exported {n} jobs -> {csv_path} , {json_path}")


@app.command("add-board")
def add_board(url: str, config: str = CONFIG):
    """Register a company board (any Greenhouse/Lever/Ashby/SmartRecruiters/Workday URL)."""
    board = ats.detect_board(url)
    if not board:
        raise typer.BadParameter(f"not a recognised ATS URL: {url}")
    cfg = load_config(config)
    store = Store(cfg.path(cfg.db_path))
    store.add_company(board)
    store.close()
    typer.echo(f"Added {board.ats}/{board.board_id}")


@app.command()
def ui(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
    config: str = CONFIG,
):
    """Start the web UI."""
    import uvicorn

    from server import create_app

    typer.echo(f"Job Link Finder UI -> http://{host}:{port}")
    uvicorn.run(create_app(config), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
