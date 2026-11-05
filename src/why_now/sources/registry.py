"""The job sources the project can read, by the name used in settings and saved ads.

Adding a job source means adding its adapter here, with no change to the read step.
"""

from collections.abc import Callable

from why_now.sources import JobSource
from why_now.sources.greenhouse import GreenhouseSource
from why_now.sources.lever import LeverSource
from why_now.sources.polite import PoliteClient

SOURCES: dict[str, Callable[[PoliteClient], JobSource]] = {
    GreenhouseSource.name: GreenhouseSource,
    LeverSource.name: LeverSource,
}
