import argparse
import asyncio
import itertools
import random
import ssl
import string
import sys
from typing import Iterable

import aiohttp

from rchecker.resource.wordlist_source import load_wordlist
from rchecker.stats import Stats
from rchecker.utils.progress import ProgressManager
from rchecker.utils.rate_limiter import RateLimiter
from rchecker.whois import check_domain


def validate_pattern(pattern: str) -> tuple[str, bool]:
    if pattern.count("*") > 1:
        raise ValueError("Only a single trailing '*' wildcard is supported")
    if "*" in pattern:
        if not pattern.endswith("*"):
            raise ValueError("'*' is only supported at the end of the pattern")
        prefix = pattern[:-1]
        wildcard = True
    else:
        prefix = pattern
        wildcard = False
    if not prefix:
        raise ValueError("Pattern prefix cannot be empty")
    prefix = prefix.lower()
    allowed = set(string.ascii_lowercase + string.digits + "-")
    if any(ch not in allowed for ch in prefix):
        raise ValueError("Pattern prefix may only contain letters, digits, or hyphens")
    return prefix, wildcard


def generate_labels(
        prefix: str, wildcard: bool, min_len: int, max_len: int, charset: str
) -> Iterable[str]:
    for length in range(min_len, max_len + 1):
        if length < len(prefix):
            continue
        suffix_len = length - len(prefix)
        if suffix_len == 0:
            yield prefix
        elif wildcard:
            for combo in itertools.product(charset, repeat=suffix_len):
                yield prefix + "".join(combo)
        elif length == len(prefix):
            yield prefix


def generate_labels_from_wordlist(
        words: list[str], min_len: int = None, max_len: int = None
) -> list[str]:
    """Generate domain labels from a wordlist, optionally filtering by length."""
    labels = []
    for word in words:
        word_len = len(word)
        # Apply length filters if specified
        if min_len is not None and word_len < min_len:
            continue
        if max_len is not None and word_len > max_len:
            continue
        labels.append(word)
    return labels


async def worker(
        queue: asyncio.Queue[str],
        session: aiohttp.ClientSession,
        limiter: RateLimiter,
        timeout: float,
        stats: Stats,
        progress_manager: ProgressManager = None,
        max_retries: int = 2,
) -> None:
    while True:
        try:
            label = await queue.get()
        except asyncio.CancelledError:
            return
        if label is None:
            queue.task_done()
            break
        fqdn = label
        await stats.update_current(fqdn)
        await limiter.wait()
        result = await check_domain(session, fqdn, timeout, max_retries)
        if result is True:
            print(f"AVAILABLE  {fqdn}")
            await stats.add_available(fqdn)
        elif result is False:
            await stats.add_registered(fqdn)
        else:
            await stats.add_error(fqdn)

        # Mark domain as checked in progress manager
        if progress_manager:
            await progress_manager.mark_checked(fqdn)

        queue.task_done()


async def run(args: argparse.Namespace) -> None:
    # Validate arguments based on mode (pattern vs wordlist)
    if args.wordlist and args.pattern:
        raise ValueError("Cannot specify both pattern and --wordlist. Choose one mode.")
    if not args.wordlist and not args.pattern:
        raise ValueError("Must specify either a pattern or --wordlist.")

    max_len = args.max
    if max_len <= 0:
        raise ValueError("--max must be positive")
    min_len = (
        args.min if args.min is not None else (max_len if not args.wordlist else 1)
    )
    if min_len <= 0:
        raise ValueError("--min must be positive")
    if min_len > max_len:
        raise ValueError("--min cannot be greater than --max")

    # Generate labels based on mode
    if args.wordlist:
        # Wordlist mode
        words = load_wordlist(args.wordlist, max_len)
        labels = generate_labels_from_wordlist(words, min_len, max_len)
        print(
            f"Loaded {len(words)} words from wordlist, {len(labels)} match length criteria",
            file=sys.stderr,
        )
    else:
        # Pattern mode (existing logic)
        prefix, wildcard = validate_pattern(args.pattern)
        if not wildcard and (min_len != len(prefix) or max_len != len(prefix)):
            raise ValueError("Pattern without '*' only supports exact length lookups")

        charset = args.charset.lower()
        if not charset:
            raise ValueError("--charset cannot be empty")
        invalid_chars = set(charset) - set(string.ascii_lowercase + string.digits + "-")
        if invalid_chars:
            raise ValueError(
                "Charset contains invalid characters for domain labels: "
                + "".join(sorted(invalid_chars))
            )

        labels = list(generate_labels(prefix, wildcard, min_len, max_len, charset))

    if not labels:
        raise ValueError("No domain labels generated with the provided arguments")

    fqdn_labels = [f"{label}.{args.tld.lower()}" for label in labels]

    # Initialize progress manager for checkpoint/resume functionality
    progress_manager = None
    original_total = len(fqdn_labels)
    if args.resume or args.progress_file:
        progress_manager = ProgressManager(args.progress_file)
        if args.resume and progress_manager.checked_domains:
            print(
                f"Resuming from checkpoint: {len(progress_manager.checked_domains)} domains already checked",
                file=sys.stderr,
            )
        # Filter out already checked domains
        fqdn_labels = progress_manager.get_unchecked_domains(fqdn_labels)

    # Shuffle domains if requested
    if args.shuffle:
        random.shuffle(fqdn_labels)
        print("Domain order shuffled randomly", file=sys.stderr)

    remaining_total = len(fqdn_labels)
    if progress_manager and progress_manager.checked_domains:
        print(
            f"Planned lookups: {remaining_total} domains (remaining), {original_total} total",
            file=sys.stderr,
        )
    else:
        print(f"Planned lookups: {remaining_total} domains", file=sys.stderr)

    limiter = RateLimiter(args.rate if args.rate > 0 else None)
    queue: asyncio.Queue[str] = asyncio.Queue()
    stats = Stats(remaining_total, not args.no_progress, args.output)
    for fqdn in fqdn_labels:
        queue.put_nowait(fqdn)
    for _ in range(args.concurrency):
        queue.put_nowait(None)

    # Create SSL context with more lenient settings
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(
        limit=args.concurrency,
        ssl=ssl_context,
        ttl_dns_cache=300,  # DNS cache for 5 minutes
        use_dns_cache=True,
        keepalive_timeout=30,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
            connector=connector,
            headers={"User-Agent": "domain-checker/0.1"},
            timeout=aiohttp.ClientTimeout(total=args.timeout),
    ) as session:
        workers = [
            asyncio.create_task(
                worker(
                    queue,
                    session,
                    limiter,
                    args.timeout,
                    stats,
                    progress_manager,
                    args.retries,
                )
            )
            for _ in range(args.concurrency)
        ]
        await queue.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    # Clean up progress file after successful completion
    if progress_manager:
        progress_manager.cleanup()
        print(
            "Progress checkpoint cleared after successful completion", file=sys.stderr
        )

    stats.close()
    print(
        "\nFinished. Available: {0}, registered: {1}, errors: {2}".format(
            stats.available, stats.registered, stats.errors
        ),
        file=sys.stderr,
    )
