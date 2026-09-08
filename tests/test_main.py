from click.testing import CliRunner

from surfsky_cli import __version__
from surfsky_cli.main import cli


def test_version_flag():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"surfsky, version {__version__}"
