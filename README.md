# surfsky-cli

The CLI for [Surfsky](https://surfsky.io), an advanced antidetect cloud browser
built to bypass complex browser challenges. Scrape pages, automate browser
sessions, and save logins in profiles. Requires Python 3.12+; runs on macOS,
Windows, and Linux.

## Install

```sh
uv tool install surfsky-cli
```

Or use `pipx install surfsky-cli` or `pip install surfsky-cli`.

## Set up credentials

Copy your API token and base URL from the [dashboard](https://app.surfsky.io).
In bash or zsh:

```sh
export SURFSKY_API_TOKEN='your-token'
export SURFSKY_API_BASE_URL='your-base-url'
surfsky status                     # account limits and proxy quota
```

In PowerShell, use `$env:SURFSKY_API_TOKEN = 'your-token'` and
`$env:SURFSKY_API_BASE_URL = 'your-base-url'`.

`--api-token` and `--base-url` override the environment. The CLI does not save
credentials. Session records are stored in `~/.surfsky` (`SURFSKY_HOME` overrides it).

## Scrape a page

```sh
surfsky scrape https://example.com                         # markdown
surfsky scrape https://example.com --only-main-content     # omit navigation, footers, forms
surfsky scrape https://example.com -f markdown,links --json --pretty
surfsky scrape https://example.com -f screenshot -o shot.png
surfsky scrape https://example.com --country us --proxy premium --os mac
```

Formats: `markdown` (default), `html` (cleaned), `raw_html` (unmodified),
`links`, and `screenshot`. One format returns content; multiple formats return
JSON. In text mode, `-f screenshot -o file.png` saves PNG bytes; screenshot
output is otherwise base64.

By default, `scrape` starts a browser and closes it when finished. Use `--keep`
to leave it running and return its ID, or `--profile <uuid>` to use a saved
profile. `--session <uuid>` (or `SURFSKY_SESSION`) reuses the active tab and
navigates it to the URL. Omit the URL to read the current page.

## Automate a browser

```sh
surfsky session start                        # copy the returned session ID
export SURFSKY_SESSION='returned-session-id'
surfsky goto https://example.com -s
surfsky click 'text=More information' -s
surfsky get text
surfsky screenshot -o page.png
surfsky session stop                         # ends billing
```

Pass `--session <uuid>` instead of setting `SURFSKY_SESSION` if you use several
browsers. Sessions must have a local record; IDs can be shortened to a unique prefix.

`-s` returns a snapshot with references such as `[@12] link "More information"`.
Use the reference from your output with `surfsky click @12`. CSS selectors and
`text=words` also work. Take a new snapshot after navigation or a tab switch;
each snapshot replaces the saved references.

Sessions bill per minute until stopped or idle, idle minutes included.
`surfsky session start --idle-timeout` sets how many idle seconds end a
session; see its `--help` for the default. Raise it only when needed.
`surfsky status` reports the selected session's idle time and checks its
connection, resetting the idle timer. `surfsky session devtools` prints live
view and DevTools URLs.

To reuse cookies across sessions:
`surfsky profile create acct --country us --os win`, then
`surfsky session start --profile <uuid>`.

## Use with coding agents

Run `surfsky skill --install` to add a Claude Code skill at
`.claude/skills/surfsky/SKILL.md`. For other agents, `surfsky skill` prints the
same instructions. The skill names the CLI version that wrote it and tells the
agent to upgrade (`uv tool install surfsky-cli@latest`) and run
`surfsky skill --install` again when the CLI is newer.

- Use `--json` or `SURFSKY_JSON=1`. Success includes `ok: true`; errors include
  `ok: false` and an `error` object with `code`, `message`, `hint`, and `retryable`.
  JSON errors go to stdout; text errors go to stderr.
- `-o <file>` saves output; `--pretty` indents JSON. For `screenshot`, `-o`
  saves the PNG and `--json` returns its path and size.
- Exit codes: 0 success, 1 error, 2 usage, 3 missing or expired session,
  4 authentication, 5 timeout, 6 not found or stale reference, 7 quota or plan limit.

## Development

```sh
uv sync --all-groups
uv run ruff check . && uv run ty check && uv run pytest
SURFSKY_LIVE_TESTS=1 uv run pytest tests/test_live.py   # requires credentials; starts billed browsers
```
