# surfsky-cli

CLI for [Surfsky](https://surfsky.io), an antidetect cloud browser.

Requires Python 3.12+ on macOS, Windows or Linux.

## Install

```sh
uv tool install surfsky-cli
```

Or install with `pipx install surfsky-cli` or `pip install surfsky-cli`.

## Credentials

Get your API token and base URL from the [dashboard](https://app.surfsky.io).

macOS / Linux:

```sh
export SURFSKY_API_TOKEN='your-token'
export SURFSKY_API_BASE_URL='your-base-url'
```

Windows (PowerShell):

```powershell
$env:SURFSKY_API_TOKEN = 'your-token'
$env:SURFSKY_API_BASE_URL = 'your-base-url'
```

Verify with `surfsky status`. Flags `--api-token` and `--base-url` override
the environment. Credentials are not stored. Session records go in
`~/.surfsky`; set `SURFSKY_HOME` to change the directory.

## Scrape

```sh
surfsky scrape https://example.com                         # Markdown
surfsky scrape https://example.com --only-main-content     # omit navigation, footers, forms
surfsky scrape https://example.com -f markdown,links --json --pretty
surfsky scrape https://example.com -f screenshot -o shot.png
surfsky scrape https://example.com --proxy premium --country us --os mac
```

Formats: `markdown` (default), `html`, `raw_html`, `links`, `screenshot`.
One format returns content; multiple formats return JSON. `html` is cleaned;
`raw_html` is unchanged. Scrape screenshots are base64 unless saved with `-o`
in text mode.

By default, `scrape` closes its browser when finished. `--keep` leaves it
running and returns its ID. `--profile ID` uses a saved profile.
`--session ID` reuses the active tab; omit the URL to read its current page.

## Browser sessions

```sh
surfsky session start --proxy premium --proxy-type mobile --country us
export SURFSKY_SESSION='returned-session-id'
surfsky goto https://google.com
surfsky type 'textarea[name=q]' surfsky
surfsky press Enter -s
surfsky get text
surfsky screenshot -o results.png
surfsky session stop
```

Replace `returned-session-id` with the ID from `session start`. On PowerShell,
use `$env:SURFSKY_SESSION = 'returned-session-id'`. You can also pass
`--session ID` on each command; unique ID prefixes work.

Sessions bill per minute, including idle time, until stopped or the idle
timeout expires. Set `--idle-timeout SECONDS` when starting a session.
`surfsky status` checks the selected session's connection and resets its idle
timer. `surfsky session devtools` prints live view and DevTools URLs.

`-s` returns a snapshot with `@N` references for `click`, `type` and `fill`.
CSS selectors and `text=words` also work. Take a new snapshot after navigation
or a tab switch; each snapshot replaces the references.

Sessions and scrapes accept `--proxy premium|shared|URL`, `--proxy-type mobile`,
`--country`, `--region`, `--city`, and `--os win|mac|android`.
See `surfsky proxy --help` for location lists and quota commands.

To save logins, create a profile with `surfsky profile create acct --country us --os win`,
then use its ID with `surfsky session start --profile ID`.

## Agents and scripts

`surfsky skill --install` writes agent instructions to
`.claude/skills/surfsky-cli/SKILL.md` and `.agents/skills/surfsky-cli/SKILL.md`.
Rerun it after upgrading the CLI. `surfsky skill` prints the instructions.

- `--json` or `SURFSKY_JSON=1`: success returns `ok: true`; errors return
  `ok: false` with `code`, `message`, `hint` and `retryable` under `error`.
  JSON errors go to stdout; text errors go to stderr.
- `-o FILE` saves output; `--pretty` indents JSON. For `screenshot`, `-o`
  saves PNG and `--json` returns its path and size.
- Exit codes: 0 success, 1 error, 2 usage, 3 missing or expired session,
  4 authentication, 5 timeout, 6 not found or stale reference, 7 quota or plan limit.

## Development

```sh
uv sync --all-groups
uv run pytest -q
```
