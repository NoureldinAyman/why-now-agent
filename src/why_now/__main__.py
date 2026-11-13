"""`python -m why_now` runs the `why-now` command. The web page starts runs this way, so they
use the same Python as the page."""

from why_now.cli import app

app()
