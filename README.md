# Domain Checker

Async CLI to explore domain availability via RDAP.

```bash
uv run rchecker.py --tld com --max 6 byte*
```

Key options:
- `--rate` caps lookups per second (default 5).
- `--concurrency` sets concurrent workers (default 10).
- `--charset` customises wildcard alphabet (default lowercase letters).
- `--min` lets you widen the length range when needed.

Available domains stream to stdout; progress and totals go to stderr.
