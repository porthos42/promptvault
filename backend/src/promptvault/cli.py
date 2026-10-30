"""`promptvault` command line interface."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import click
import typer
from pydantic import ValidationError
from sqlalchemy.orm import Session

from promptvault import __version__
from promptvault.config import get_settings
from promptvault.db import make_engine, make_session_factory, run_migrations
from promptvault.schemas import PromptCreate, PromptPatch
from promptvault.services import categories as cat_svc
from promptvault.services import prompts as svc
from promptvault.services import tags as tag_svc
from promptvault.services.errors import DomainError

app = typer.Typer(help="Prompt Vault: self-hosted prompt library.", no_args_is_help=True)
category_app = typer.Typer(help="Manage categories.", no_args_is_help=True)
tag_app = typer.Typer(help="Manage tags.", no_args_is_help=True)
trash_app = typer.Typer(help="Manage soft-deleted prompts.", no_args_is_help=True)
app.add_typer(category_app, name="category")
app.add_typer(tag_app, name="tag")
app.add_typer(trash_app, name="trash")


@contextmanager
def _db() -> Iterator[Session]:
    """Session on the configured database (migrated first); commit on success."""
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(s.resolved_database_url)
    engine = make_engine(s.resolved_database_url)
    try:
        with make_session_factory(engine)() as session:
            try:
                yield session
                session.commit()
            except DomainError as exc:
                session.rollback()
                typer.secho(f"Error: {exc.detail}", fg=typer.colors.RED, err=True)
                raise typer.Exit(1) from exc
            except ValidationError as exc:
                session.rollback()
                for e in exc.errors():
                    loc = ".".join(str(x) for x in e["loc"])
                    typer.secho(f"Error: {loc}: {e['msg']}", fg=typer.colors.RED, err=True)
                raise typer.Exit(2) from exc
    finally:
        engine.dispose()


def _read_body(body: str | None, body_file: Path | None) -> str | None:
    if body is not None and body_file is not None:
        raise typer.BadParameter("Use either --body or --body-file, not both")
    if body_file is not None:
        return body_file.read_text(encoding="utf-8")
    return body


def _summary(p: Any) -> dict[str, Any]:
    return {
        "id": p.id,
        "title": p.title,
        "category": p.category.slug if p.category else None,
        "tags": sorted(t.name for t in p.tags),
        "difficulty": p.difficulty,
        "favorite": p.is_favorite,
        "updated_at": p.updated_at.isoformat(),
    }


def _detail(p: Any, version: int) -> dict[str, Any]:
    d = _summary(p)
    d.update(
        description=p.description,
        prompt_type=p.prompt_type,
        variables=p.variables,
        model_hints=p.model_hints,
        output_format=p.output_format,
        source=p.source,
        license=p.license,
        disclaimer=p.disclaimer,
        version=version,
        deleted_at=p.deleted_at.isoformat() if p.deleted_at else None,
        body=p.body,
    )
    return d


Title = Annotated[str | None, typer.Option(help="Prompt title.")]
BodyOpt = Annotated[str | None, typer.Option(help="Prompt text (supports {{variables}}).")]
BodyFile = Annotated[Path | None, typer.Option(help="Read the prompt text from a file.")]
CategoryOpt = Annotated[str | None, typer.Option("--category", "-c", help="Category slug.")]
TagsOpt = Annotated[list[str] | None, typer.Option("--tag", "-t", help="Tag (repeatable).")]
AsJson = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]


@app.command()
def add(
    title: Annotated[str, typer.Option(help="Prompt title.")],
    body: BodyOpt = None,
    body_file: BodyFile = None,
    description: Annotated[str, typer.Option()] = "",
    category: CategoryOpt = None,
    tag: TagsOpt = None,
    difficulty: Annotated[str, typer.Option()] = "beginner",
    type_: Annotated[str, typer.Option("--type")] = "template",
    as_json: AsJson = False,
) -> None:
    """Create a prompt."""
    text = _read_body(body, body_file)
    if text is None:
        text = click.edit("") or ""
    with _db() as session:
        data = PromptCreate(
            title=title,
            body=text.strip(),
            description=description,
            category=category,
            tags=tag or [],
            difficulty=difficulty,
            prompt_type=type_,
        )
        p = svc.create_prompt(session, data.model_dump())
        if as_json:
            typer.echo(json.dumps(_detail(p, 1), indent=2))
        else:
            typer.echo(f"Created {p.id}  {p.title}")


@app.command("list")
def list_(
    category: CategoryOpt = None,
    tag: TagsOpt = None,
    favorite: Annotated[bool, typer.Option("--favorite", help="Only favorites.")] = False,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
    as_json: AsJson = False,
) -> None:
    """List prompts (newest first)."""
    with _db() as session:
        f = svc.ListFilters(category=category, tags=tag or [], favorite=True if favorite else None)
        res = svc.list_prompts(session, f, limit)
        _print_results(res, as_json)


def _print_results(res: svc.ListResult, as_json: bool) -> None:
    if as_json:
        out: dict[str, Any] = {"total": res.total, "items": [_summary(p) for p in res.items]}
        if res.corrected_query:
            out["corrected_query"] = res.corrected_query
        typer.echo(json.dumps(out, indent=2))
        return
    if res.corrected_query:
        typer.echo(f"Showing results for: {res.corrected_query}")
    for p in res.items:
        cat = p.category.slug if p.category else "-"
        typer.echo(f"{p.id[:8]}  {cat:<20.20} {p.title}")
    typer.echo(f"({len(res.items)} of {res.total})")


@app.command()
def search(
    query: Annotated[str, typer.Argument(help='Words to find; "quote" an exact phrase.')],
    category: CategoryOpt = None,
    tag: TagsOpt = None,
    sort: Annotated[
        str, typer.Option(help="relevance|newest|updated|recent|popular|rating|title")
    ] = "relevance",
    limit: Annotated[int, typer.Option(min=1, max=500)] = 20,
    as_json: AsJson = False,
) -> None:
    """Full-text search (typo-tolerant), combinable with category and tag filters."""
    with _db() as session:
        f = svc.ListFilters(q=query, sort=sort, category=category, tags=tag or [])
        _print_results(svc.list_prompts(session, f, limit), as_json)


@app.command()
def show(ident: str, as_json: AsJson = False) -> None:
    """Show a prompt by id (or unique id prefix)."""
    with _db() as session:
        p = svc.resolve_prompt(session, ident)
        d = _detail(p, svc.current_version(session, p.id))
        if as_json:
            typer.echo(json.dumps(d, indent=2))
            return
        typer.echo(f"{d['title']}  [{d['id']}]  v{d['version']}")
        typer.echo(f"category: {d['category'] or '-'}   tags: {', '.join(d['tags']) or '-'}")
        if d["deleted_at"]:
            typer.echo(f"IN TRASH since {d['deleted_at']}")
        if d["description"]:
            typer.echo(f"\n{d['description']}")
        typer.echo(f"\n{d['body']}")


@app.command()
def edit(
    ident: str,
    title: Title = None,
    body: BodyOpt = None,
    body_file: BodyFile = None,
    description: Annotated[str | None, typer.Option()] = None,
    category: CategoryOpt = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Replaces all tags.")] = None,
    difficulty: Annotated[str | None, typer.Option()] = None,
    type_: Annotated[str | None, typer.Option("--type")] = None,
    favorite: Annotated[bool | None, typer.Option("--favorite/--no-favorite")] = None,
    editor: Annotated[bool, typer.Option("--editor", help="Edit the body in $EDITOR.")] = False,
) -> None:
    """Edit a prompt. Only the options you pass are changed."""
    text = _read_body(body, body_file)
    with _db() as session:
        p = svc.resolve_prompt(session, ident)
        if editor:
            text = click.edit(p.body)
            if text is None:
                typer.echo("No changes.")
                return
        changes: dict[str, Any] = {}
        for key, val in (
            ("title", title),
            ("description", description),
            ("category", category),
            ("difficulty", difficulty),
            ("prompt_type", type_),
            ("is_favorite", favorite),
            ("body", text.strip() if text is not None else None),
        ):
            if val is not None:
                changes[key] = val
        if tag is not None:
            changes["tags"] = tag
        if not changes:
            typer.echo("Nothing to change.")
            return
        patch = PromptPatch(**changes)
        svc.update_prompt(session, p, patch.model_dump(exclude_unset=True))
        typer.echo(f"Updated {p.id} (now v{svc.current_version(session, p.id)})")


@app.command()
def rm(
    ident: str,
    permanent: Annotated[bool, typer.Option("--permanent", help="Delete for good.")] = False,
) -> None:
    """Move a prompt to Trash (use --permanent to delete a trashed prompt for good)."""
    with _db() as session:
        p = svc.resolve_prompt(session, ident)
        if permanent:
            svc.delete_permanently(session, p)
            typer.echo(f"Deleted {p.id} permanently")
        else:
            svc.trash_prompt(session, p)
            typer.echo(f"Moved {p.id} to Trash")


@app.command()
def restore(ident: str) -> None:
    """Restore a prompt from Trash."""
    with _db() as session:
        p = svc.restore_prompt(session, svc.resolve_prompt(session, ident))
        typer.echo(f"Restored {p.id}  {p.title}")


@trash_app.command("list")
def trash_list() -> None:
    """List prompts in Trash."""
    with _db() as session:
        res = svc.list_prompts(session, svc.ListFilters(trash=True), 500)
        for p in res.items:
            typer.echo(f"{p.id[:8]}  {p.deleted_at:%Y-%m-%d}  {p.title}")
        typer.echo(f"({res.total} in Trash)")


@trash_app.command("purge")
def trash_purge(
    older_than_days: Annotated[int | None, typer.Option(min=0)] = None,
) -> None:
    """Permanently delete everything in Trash (optionally only items older than N days)."""
    with _db() as session:
        typer.echo(f"Purged {svc.purge_trash(session, older_than_days)} prompt(s)")


@category_app.command("list")
def category_list() -> None:
    """List categories with prompt counts."""
    with _db() as session:
        for c, n in cat_svc.list_categories(session):
            typer.echo(f"{c.slug:<28} {n:>4}  {c.name}")


@category_app.command("add")
def category_add(
    name: str,
    slug: Annotated[str | None, typer.Option()] = None,
    parent: Annotated[str | None, typer.Option(help="Parent slug.")] = None,
    icon: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Create a category."""
    with _db() as session:
        c = cat_svc.create_category(
            session, {"name": name, "slug": slug, "parent": parent, "icon": icon}
        )
        typer.echo(f"Created category {c.slug}")


@category_app.command("rm")
def category_rm(slug: str) -> None:
    """Delete a category (its prompts become uncategorised)."""
    with _db() as session:
        cat_svc.delete_category(session, cat_svc.get_by_slug(session, slug))
        typer.echo(f"Deleted category {slug}")


@tag_app.command("list")
def tag_list() -> None:
    """List tags with counts."""
    with _db() as session:
        for name, n in tag_svc.list_tags(session):
            typer.echo(f"{name:<28} {n:>4}")


@tag_app.command("rename")
def tag_rename(old: str, new: str) -> None:
    """Rename a tag (merges if the new name exists)."""
    with _db() as session:
        typer.echo(f"Renamed to {tag_svc.rename(session, old, new)}")


@tag_app.command("rm")
def tag_rm(name: str) -> None:
    """Delete a tag from all prompts."""
    with _db() as session:
        tag_svc.delete(session, name)
        typer.echo(f"Deleted tag {name}")


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
