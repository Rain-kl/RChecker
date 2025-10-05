import argparse
import asyncio
import itertools
import json
import os
import random
import ssl
import string
import sys
from typing import Iterable, Set
from urllib.parse import urlparse

import aiohttp
from tqdm import tqdm

# Predefined wordlist sources
WORDLIST_SOURCES = {
    "common": {
        "url": "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt",
        "description": "Common English words (370k+ words)",
    },
    "common-small": {
        "url": "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-usa.txt",
        "description": "10,000 most common English words",
    },
    "common-tiny": {
        "url": "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-usa-no-swears.txt",
        "description": "10,000 most common English words (no profanity)",
    },
    "names": {
        "url": "https://raw.githubusercontent.com/dominictarr/random-name/master/first-names.txt",
        "description": "Common first names",
    },
    "adjectives": {
        "url": "https://raw.githubusercontent.com/hugsy/stuff/main/random-word/english-adjectives.txt",
        "description": "English adjective words",
    },
}


class ProgressManager:
    """Manages checkpoint/resume functionality"""

    def __init__(self, progress_file: str = None):
        self.progress_file = progress_file
        self.checked_domains: Set[str] = set()
        self._lock = asyncio.Lock()
        if progress_file and os.path.exists(progress_file):
            self._load_progress()

    def _load_progress(self):
        """Load progress from file"""
        try:
            with open(self.progress_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.checked_domains = set(data.get("checked_domains", []))
        except (json.JSONDecodeError, IOError) as e:
            print(
                f"Error loading progress file {self.progress_file}: {e}",
                file=sys.stderr,
            )
            self.checked_domains = set()

    async def mark_checked(self, domain: str):
        """Mark domain as checked and save progress"""
        async with self._lock:
            self.checked_domains.add(domain)
            if self.progress_file:
                await self._save_progress()

    async def _save_progress(self):
        """Save progress to file"""
        try:
            data = {"checked_domains": list(self.checked_domains)}
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(
                f"Error saving progress to {self.progress_file}: {e}", file=sys.stderr
            )

    def is_checked(self, domain: str) -> bool:
        """Check if domain has been checked"""
        return domain in self.checked_domains

    def get_unchecked_domains(self, all_domains: list) -> list:
        """Filter out already checked domains"""
        return [domain for domain in all_domains if not self.is_checked(domain)]

    def cleanup(self):
        """Clean up progress file after completion"""
        if self.progress_file and os.path.exists(self.progress_file):
            try:
                os.remove(self.progress_file)
            except IOError as e:
                print(
                    f"Error removing progress file {self.progress_file}: {e}",
                    file=sys.stderr,
                )


class RateLimiter:
    """Simple async rate limiter enforcing a global requests-per-second cap."""

    def __init__(self, rate: float | None) -> None:
        if rate is not None and rate <= 0:
            raise ValueError("Rate must be positive or omitted")
        self._interval = 1.0 / rate if rate else None
        self._lock = asyncio.Lock()
        self._next_time = 0.0

    async def wait(self) -> None:
        if self._interval is None:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            sleep_for = self._next_time - now
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
                now = loop.time()
            self._next_time = max(now, self._next_time) + self._interval


class Stats:
    def __init__(
        self, total: int = 0, show_progress: bool = True, output_file: str = None
    ) -> None:
        self.available = 0
        self.registered = 0
        self.errors = 0
        self.completed = 0
        self._lock = asyncio.Lock()
        self.show_progress = show_progress
        self.output_file = output_file
        self._file_handle = None
        if show_progress:
            self.pbar = tqdm(total=total, desc="Checking domains", unit="domain")
        else:
            self.pbar = None

        # Initialize output file if specified
        if self.output_file:
            try:
                self._file_handle = open(self.output_file, "w", encoding="utf-8")
            except IOError as e:
                print(
                    f"Error opening output file {self.output_file}: {e}",
                    file=sys.stderr,
                )
                self._file_handle = None

    async def add_available(self, domain: str = "") -> None:
        async with self._lock:
            self.available += 1
            self.completed += 1
            if domain and self._file_handle:
                try:
                    self._file_handle.write(f"{domain}\n")
                    self._file_handle.flush()  # Ensure immediate write to disk
                except IOError as e:
                    print(
                        f"Error writing domain {domain} to file: {e}", file=sys.stderr
                    )
            if self.pbar:
                self.pbar.update(1)
                self.pbar.set_postfix(
                    available=self.available,
                    registered=self.registered,
                    errors=self.errors,
                )

    async def add_registered(self, domain: str = "") -> None:
        async with self._lock:
            self.registered += 1
            self.completed += 1
            if self.pbar:
                self.pbar.update(1)
                self.pbar.set_postfix(
                    available=self.available,
                    registered=self.registered,
                    errors=self.errors,
                )

    async def add_error(self, domain: str = "") -> None:
        async with self._lock:
            self.errors += 1
            self.completed += 1
            if self.pbar:
                self.pbar.update(1)
                self.pbar.set_postfix(
                    available=self.available,
                    registered=self.registered,
                    errors=self.errors,
                )

    async def update_current(self, domain: str) -> None:
        """Update current domain being checked"""
        async with self._lock:
            if self.pbar:
                self.pbar.set_description(f"Checking {domain}")

    def close(self) -> None:
        if self.pbar:
            self.pbar.close()
        if self._file_handle:
            try:
                self._file_handle.close()
                if self.available > 0:
                    print(
                        f"Available domains saved to: {self.output_file}",
                        file=sys.stderr,
                    )
                else:
                    print("No available domains found.", file=sys.stderr)
            except IOError as e:
                print(f"Error closing output file: {e}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check domain availability for generated second-level names.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Check command (default behavior)
    check_parser = subparsers.add_parser("check", help="Check domain availability")
    check_parser.add_argument(
        "pattern",
        nargs="?",
        help="Pattern for the second-level domain (supports optional trailing '*'). Optional when using --wordlist.",
    )
    check_parser.add_argument(
        "--tld", default="com", help="Top-level domain to check, e.g. 'com'."
    )
    check_parser.add_argument(
        "--max",
        type=int,
        required=True,
        help="Maximum length of the second-level domain (inclusive).",
    )
    check_parser.add_argument(
        "--min",
        type=int,
        help="Minimum length of the second-level domain (defaults to --max).",
    )
    check_parser.add_argument(
        "--rate",
        type=float,
        default=50.0,
        help="Maximum lookups per second. Set to 0 to disable throttling.",
    )
    check_parser.add_argument(
        "--concurrency",
        type=int,
        default=15,
        help="Number of concurrent lookup workers.",
    )
    check_parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout per RDAP request in seconds.",
    )
    check_parser.add_argument(
        "--charset",
        default=string.ascii_lowercase,
        help="Characters to use for wildcard expansion (default: lowercase letters).",
    )
    check_parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of retries for failed requests (default: 2).",
    )
    check_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar display.",
    )
    check_parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file for available domains (default: available_domains.txt).",
        default="available_domains.txt",
    )
    check_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last checkpoint if progress file exists.",
    )
    check_parser.add_argument(
        "--progress-file",
        type=str,
        help="Path to progress file for checkpoint/resume (default: .dcheck_progress.json).",
        default=".dcheck_progress.json",
    )
    check_parser.add_argument(
        "--shuffle",
        action="store_true",
        help="Shuffle the order of domains to check randomly.",
    )
    check_parser.add_argument(
        "--wordlist",
        "-w",
        type=str,
        help="Path to wordlist file (one word per line). When specified, uses words from file instead of pattern expansion.",
    )

    # Download command
    download_parser = subparsers.add_parser(
        "download", help="Download wordlists from online sources"
    )
    download_parser.add_argument(
        "wordlist_name",
        help="Name of the wordlist to download. Use 'list' to see available wordlists.",
    )
    download_parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path (default: <wordlist_name>.txt).",
    )
    download_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing file if it exists.",
    )

    # Check if the first argument is a valid subcommand
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ["check", "download"]:
        args = parser.parse_args()
    else:
        # If no command is specified or first arg is not a command, assume 'check' command for backward compatibility
        # Re-parse with check as default
        parser = argparse.ArgumentParser(
            description="Check domain availability for generated second-level names.",
        )
        parser.add_argument(
            "pattern",
            nargs="?",
            help="Pattern for the second-level domain (supports optional trailing '*'). Optional when using --wordlist.",
        )
        parser.add_argument(
            "--tld", default="com", help="Top-level domain to check, e.g. 'com'."
        )
        parser.add_argument(
            "--max",
            type=int,
            required=True,
            help="Maximum length of the second-level domain (inclusive).",
        )
        parser.add_argument(
            "--min",
            type=int,
            help="Minimum length of the second-level domain (defaults to --max).",
        )
        parser.add_argument(
            "--rate",
            type=float,
            default=10.0,
            help="Maximum lookups per second. Set to 0 to disable throttling.",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=20,
            help="Number of concurrent lookup workers.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=10.0,
            help="HTTP timeout per RDAP request in seconds.",
        )
        parser.add_argument(
            "--charset",
            default=string.ascii_lowercase,
            help="Characters to use for wildcard expansion (default: lowercase letters).",
        )
        parser.add_argument(
            "--retries",
            type=int,
            default=2,
            help="Number of retries for failed requests (default: 2).",
        )
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Disable progress bar display.",
        )
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            help="Output file for available domains (default: available_domains.txt).",
            default="available_domains.txt",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume from the last checkpoint if progress file exists.",
        )
        parser.add_argument(
            "--progress-file",
            type=str,
            help="Path to progress file for checkpoint/resume (default: .dcheck_progress.json).",
            default=".dcheck_progress.json",
        )
        parser.add_argument(
            "--shuffle",
            action="store_true",
            help="Shuffle the order of domains to check randomly.",
        )
        parser.add_argument(
            "--wordlist",
            "-w",
            type=str,
            help="Path to wordlist file (one word per line). When specified, uses words from file instead of pattern expansion.",
        )
        args = parser.parse_args()
        args.command = "check"

    return args


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


def load_wordlist(wordlist_path: str, max_len: int = None) -> list[str]:
    """Load words from a wordlist file, optionally filtering by maximum length."""
    if not os.path.exists(wordlist_path):
        raise ValueError(f"Wordlist file not found: {wordlist_path}")

    words = []
    allowed = set(string.ascii_lowercase + string.digits + "-")

    try:
        with open(wordlist_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                word = line.strip().lower()
                if not word:  # Skip empty lines
                    continue

                # Validate word contains only allowed characters
                if any(ch not in allowed for ch in word):
                    print(
                        f"Warning: Skipping invalid word '{word}' at line {line_num} "
                        f"(contains invalid characters for domain labels)",
                        file=sys.stderr,
                    )
                    continue

                # Filter by maximum length if specified
                if max_len is not None and len(word) > max_len:
                    continue

                words.append(word)

    except UnicodeDecodeError as e:
        raise ValueError(f"Error reading wordlist file (encoding issue): {e}")
    except IOError as e:
        raise ValueError(f"Error reading wordlist file: {e}")

    if not words:
        raise ValueError("No valid words found in wordlist file")

    return words


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


def list_available_wordlists() -> None:
    """Display available wordlists."""
    print("Available wordlists:")
    print("=" * 50)
    for name, info in WORDLIST_SOURCES.items():
        print(f"  {name:<15} - {info['description']}")


async def download_wordlist(
    name: str, output_path: str = None, force: bool = False
) -> str:
    """Download a wordlist from a predefined source."""
    if name == "list":
        list_available_wordlists()
        return None

    if name not in WORDLIST_SOURCES:
        available = ", ".join(WORDLIST_SOURCES.keys())
        raise ValueError(f"Unknown wordlist '{name}'. Available: {available}")

    source = WORDLIST_SOURCES[name]
    url = source["url"]

    # Determine output filename
    if output_path is None:
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if not filename or filename == "/":
            filename = f"{name}.txt"
        output_path = filename

    # Check if file exists
    if os.path.exists(output_path) and not force:
        raise ValueError(
            f"File '{output_path}' already exists. Use --force to overwrite."
        )

    print(f"Downloading {name} wordlist from {url}")
    print(f"Output: {output_path}")

    # Create SSL context with more lenient settings for downloads
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_context)

    try:
        async with aiohttp.ClientSession(
            connector=connector,
            headers={"User-Agent": "domain-checker/0.1"},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise ValueError(
                        f"Failed to download wordlist: HTTP {response.status}"
                    )

                # Get content length for progress bar
                content_length = response.headers.get("Content-Length")
                total_size = int(content_length) if content_length else None

                # Create progress bar
                pbar = tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    desc=f"Downloading {name}",
                )

                # Download and save file
                with open(output_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
                        pbar.update(len(chunk))

                pbar.close()

    except aiohttp.ClientError as e:
        raise ValueError(f"Network error downloading wordlist: {e}")
    except IOError as e:
        raise ValueError(f"Error saving wordlist file: {e}")

    # Validate the downloaded file
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            lines = sum(1 for _ in f)
        print(f"Successfully downloaded {lines:,} words to {output_path}")
    except UnicodeDecodeError:
        print(f"Warning: Downloaded file may contain non-UTF-8 content")
    except IOError:
        print(f"Warning: Could not validate downloaded file")

    return output_path


async def check_domain(
    session: aiohttp.ClientSession, fqdn: str, timeout: float, max_retries: int = 2
) -> bool | None:
    url = f"https://rdap.org/domain/{fqdn}"

    for attempt in range(max_retries + 1):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status == 404:
                    return True
                if resp.status == 200:
                    return False
                body = await resp.text()
                print(
                    f"Unexpected RDAP response {resp.status} for {fqdn}: {body[:200]}",
                    file=sys.stderr,
                )
                return None
        except asyncio.TimeoutError:
            if attempt == max_retries:
                print(
                    f"Timeout querying {fqdn} after {max_retries + 1} attempts",
                    file=sys.stderr,
                )
        except ssl.SSLError as exc:
            if attempt == max_retries:
                print(
                    f"SSL error for {fqdn} after {max_retries + 1} attempts: {exc}",
                    file=sys.stderr,
                )
            else:
                # Small delay before retry for SSL errors
                await asyncio.sleep(0.5 * (attempt + 1))
        except aiohttp.ClientError as exc:
            if attempt == max_retries:
                print(
                    f"Request error for {fqdn} after {max_retries + 1} attempts: {exc}",
                    file=sys.stderr,
                )
            else:
                # Small delay before retry
                await asyncio.sleep(0.3 * (attempt + 1))
        except Exception as exc:
            if attempt == max_retries:
                print(f"Unexpected error for {fqdn}: {exc}", file=sys.stderr)

    return None


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


def main() -> None:
    args = parse_args()
    try:
        if args.command == "download":
            asyncio.run(download_wordlist(args.wordlist_name, args.output, args.force))
        else:  # check command (default)
            asyncio.run(run(args))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
