# surfsky-cli

Command-line access to [Surfsky](https://surfsky.io)'s antidetect cloud browsers.
Scrape pages, control browser sessions, and save logins in profiles.

Requires Python 3.12+ on macOS, Windows, or Linux.

## Install

```sh
uv tool install surfsky-cli
```

Or use `pipx install surfsky-cli` or `pip install surfsky-cli`.

## Set up credentials

Copy your API token and base URL from the [dashboard](https://app.surfsky.io).

**Linux (bash)**

```bash
export SURFSKY_API_TOKEN='your-token'
export SURFSKY_API_BASE_URL='your-base-url'
```

**macOS (zsh)**

```zsh
export SURFSKY_API_TOKEN='your-token'
export SURFSKY_API_BASE_URL='your-base-url'
```

**Windows (PowerShell)**

```powershell
$env:SURFSKY_API_TOKEN = 'your-token'
$env:SURFSKY_API_BASE_URL = 'your-base-url'
```

Then verify your credentials:

```sh
surfsky status
```

`--api-token` and `--base-url` override the environment variables. The CLI does
not save credentials. Session records go in `~/.surfsky`; set `SURFSKY_HOME`
to use another directory.

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
surfsky session start --proxy premium --proxy-type mobile --country us
# prints <uuid>; pass it as --session <uuid> or export SURFSKY_SESSION=<uuid> once
surfsky goto https://google.com --session <uuid>
surfsky type 'textarea[name=q]' surfsky --session <uuid>
surfsky press Enter -s --session <uuid>
surfsky get text --session <uuid>
surfsky screenshot -o results.png --session <uuid>
surfsky session stop --session <uuid>
```

`surfsky scrape <url> --keep` collapses the first two steps into one: it reads
the page, leaves the browser running, and prints the session ID.

A unique prefix of the session ID is enough, and `--session` can go anywhere
on the line.

Proxy, location and fingerprint flags are the same as for `scrape`:
`--proxy premium|shared|<url>`, `--country`, `--region`, `--city`,
`--proxy-type mobile`, and `--os win|mac|android`. Look up codes with
`surfsky proxy countries`, `surfsky proxy regions us`, and
`surfsky proxy cities us texas`; `surfsky proxy quota` shows remaining traffic.

`-s` returns a snapshot with references such as `[@11] combobox "Search"`.
Use a reference from your own output as the target of `click`, `type`, or
`fill`, for example `surfsky click @11`. CSS selectors and `text=words` also
work. Take a new snapshot after navigation or a tab switch;
each snapshot replaces the saved references.

Sessions are billed per minute, including idle time, until stopped or closed
by the idle timeout. Set the timeout with
`surfsky session start --idle-timeout <seconds>`; see `--help` for the default.
`surfsky status` reports the selected session's idle time and checks its
connection, resetting the idle timer. `surfsky session devtools` prints live
view and DevTools URLs.

To reuse cookies across sessions:
`surfsky profile create acct --country us --os win`, then
`surfsky session start --profile <uuid>`.

## Use with coding agents

Run `surfsky skill --install` to install the `surfsky-cli` skill at
`.claude/skills/surfsky-cli/SKILL.md` (Claude Code, Cursor) and
`.agents/skills/surfsky-cli/SKILL.md` (Codex, Cursor, Gemini CLI). For other agents,
`surfsky skill` prints the same instructions. The skill records the CLI version and
includes upgrade instructions. After upgrading with `uv tool install surfsky-cli@latest`,
run `surfsky skill --install` again to update it. For SDK, API, or Playwright/Puppeteer
integrations, use the umbrella skill at <https://surfsky.io/SKILL.md>.

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
uv run pytest -q
```
