"""The `why-now` command.

Each area keeps its commands in its own module in this package, registering them
with `@app.command()` on the `app` below. Every module here is loaded automatically,
so adding a command, or a whole area, only touches that area's file.
"""

import importlib
import pkgutil

import typer

app = typer.Typer(help="Read job ads, judge companies against a profile, and write briefs.")


@app.callback()
def main() -> None:
    """Read job ads, judge companies against a profile, and write briefs."""


for _module in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module.name}")
