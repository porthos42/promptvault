"""`promptvault` command line interface."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import typer

from promptvault import __version__
from promptvault.config import get_settings
from promptvault.db import run_migrations

app = typer.Typer(help="Prompt Vault: self-hosted prompt library.", no_args_is_help=True)


@app.command()
def serve(
    host: str = typer.Option(None, help="Bind address (default: loopback only)."),
    port: int = typer.Option(None, help="Port (default 8080)."),
    reload: bool = typer.Option(False, help="Auto-reload (development)."),
) -> None:
    """Run the web app and API."""
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "promptvault.main:app_factory",
        factory=True,
        host=host or s.host,
        port=port or s.port,
        log_level=s.log_level,
        reload=reload,
    )


@app.command()
def init() -> None:
    """Create the data dir and database, and run migrations."""
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(s.resolved_database_url)
    typer.echo(f"Database ready: {s.resolved_database_url}")


@app.command()
def doctor() -> None:
    """Check paths, database and SQLite FTS5 support."""
    s = get_settings()
    ok = True
    typer.echo(f"version      : {__version__}")
    typer.echo(f"data dir     : {s.data_dir} ({'exists' if s.data_dir.exists() else 'missing'})")
    typer.echo(f"database url : {s.resolved_database_url}")
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        typer.echo("sqlite FTS5  : ok")
    except sqlite3.Error as exc:
        ok = False
        typer.echo(f"sqlite FTS5  : MISSING ({exc})")
    static = Path(__file__).parent / "static" / "index.html"
    typer.echo(f"web UI build : {'bundled' if static.exists() else 'not built (API only)'}")
    raise typer.Exit(0 if ok else 1)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)
