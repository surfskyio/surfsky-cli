# surfsky-cli

CLI for [Surfsky](https://surfsky.io), an antidetect cloud browser: scrape a
page in one command, or keep a browser session open and control it from the shell.

## Install

```sh
uv tool install surfsky-cli
```

Needs Python 3.12+. `pipx install surfsky-cli` and `pip install surfsky-cli` work too.

## Credentials

Token and base URL come from the [dashboard](https://app.surfsky.io).

```sh
export SURFSKY_API_TOKEN='your-token'
export SURFSKY_API_BASE_URL='your-base-url'
surfsky status    # account limits and proxy quota
```

PowerShell: `$env:SURFSKY_API_TOKEN = 'your-token'`. `--api-token` and `--base-url`
override the environment. Credentials are not stored; session records go to
`~/.surfsky`, or to `SURFSKY_HOME` if set.

## Scrape

```sh
surfsky scrape https://example.com --only-main-content   # markdown, no navigation or footers
surfsky scrape https://example.com -f markdown,links --json --pretty
surfsky scrape https://example.com -f screenshot -o shot.png
```

Formats: `markdown`, `html` (cleaned), `raw_html`, `links`, `screenshot`. One
format prints its content, several print JSON.

A plain `scrape URL` goes through the Scraping API: a pre-started browser behind
a residential proxy, no session to stop. `--profile`, `--keep`, `--idle-timeout`,
`--extension` and the proxy and fingerprint flags start a browser for that scrape
instead; `--keep` leaves it running and returns its session ID. `--session ID`
reads in a running browser, the current page if no URL is given.

## Sessions

```sh
surfsky session start                 # prints session: <id>
export SURFSKY_SESSION='<id>'         # or --session <id>; a unique prefix works
surfsky goto https://example.com -s
surfsky click @2 -s
surfsky get text
surfsky screenshot -o page.png
surfsky session stop
```

A session bills per minute, idle time included, until `session stop` or
`--idle-timeout` seconds without a command (default 300, max 3600).
`surfsky status` reconnects to the selected session and resets that timer.

`-s` appends a snapshot, one row per visible element, like
`[@2] link "More information..." href=https://www.iana.org/domains/example`.
`surfsky snapshot` prints one on its own. A target is `@N`, a CSS selector or
`text=words`. Each snapshot replaces the refs: take a new one after navigation
or a tab switch.

`session start` and `scrape` take `--proxy premium|shared|URL`,
`--proxy-type residential|mobile`, `--country`, `--region`, `--city` and
`--os win|mac|android`. To keep logins between sessions, run
`surfsky profile create acct --os win --country us`, then
`surfsky session start --profile ID`.

`surfsky --help` lists the rest, among them `fill`, `type`, `wait`, `tab`,
`cookies`, `eval`, `cdp` and `session devtools` for a live view URL.

## Output and exit codes

`--json`, or `SURFSKY_JSON=1`, prints `{"ok": true, ...}` on success and
`{"ok": false, "error": {...}}` with `code`, `message`, `hint` and `retryable`
on failure, both on stdout. Text errors go to stderr. `-o FILE` saves the output.

| Exit | Meaning                                      |
| ---- | -------------------------------------------- |
| 1    | error                                        |
| 2    | usage                                        |
| 3    | missing or expired session                   |
| 4    | authentication                               |
| 5    | timeout                                      |
| 6    | target not found or stale `@N`               |
| 7    | quota, plan limit, rate limit, empty balance |

## Agent skill

`surfsky skill --install` writes `.claude/skills/surfsky-cli/SKILL.md` and
`.agents/skills/surfsky-cli/SKILL.md` in the current directory. Rerun it after
upgrading the CLI. `surfsky skill` prints the same text.

## Development

```sh
uv sync --all-groups
uv run pytest -q
```

## License

MIT
