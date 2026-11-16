import os
from pathlib import Path

import aws_cdk as cdk

from infra.stack import WhyNowStack
from why_now.settings import Settings, load_settings

DEFAULT_SETTINGS = Path("settings.toml")


def build_app(settings: Settings, account: str | None) -> cdk.App:
    if not settings.aws_region:
        raise ValueError("aws_region must be set to say where to build")
    app = cdk.App()
    WhyNowStack(
        app,
        "WhyNow",
        settings=settings,
        env=cdk.Environment(account=account, region=settings.aws_region),
    )
    return app


if __name__ == "__main__":
    settings_file = DEFAULT_SETTINGS if DEFAULT_SETTINGS.is_file() else None
    build_app(load_settings(settings_file), os.environ.get("CDK_DEFAULT_ACCOUNT")).synth()
