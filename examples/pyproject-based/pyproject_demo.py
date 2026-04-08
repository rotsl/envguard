"""Modern demo application using rich, typer, and pydantic."""
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from pydantic import BaseModel, Field

app = typer.Typer(name="pyproject-demo", help="A modern pyproject-only demo for envguard testing.")
console = Console()


class DemoConfig(BaseModel):
    """Configuration model for the demo application."""
    name: str = Field(default="pyproject-demo", description="Application name")
    version: str = Field(default="0.2.0", description="Application version")
    debug: bool = Field(default=False, description="Enable debug mode")
    max_retries: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")


@app.command()
def info():
    """Display project information."""
    config = DemoConfig()

    console.print(f"\n[bold blue]{config.name}[/bold blue] v{config.version}")
    console.print("[dim]A modern pyproject-only project for envguard testing[/dim]\n")

    table = Table(title="Dependencies")
    table.add_column("Package", style="cyan")
    table.add_column("Installed", style="green")
    table.add_column("Status", style="bold")

    dependencies = [("rich", True), ("typer", True), ("pydantic", True)]
    for pkg, installed in dependencies:
        status = "[green]OK[/green]" if installed else "[red]MISSING[/red]"
        table.add_row(pkg, "Yes" if installed else "No", status)

    console.print(table)


@app.command()
def validate(name: Optional[str] = typer.Option(None, "--name", "-n", help="Custom name")):
    """Validate a configuration using pydantic."""
    try:
        config = DemoConfig(name=name) if name else DemoConfig()
        console.print("[green]Configuration is valid![/green]")
        console.print(config.model_dump_json(indent=2))
    except Exception as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def version():
    """Print the version number."""
    console.print("pyproject-demo version 0.2.0")


if __name__ == "__main__":
    app()
