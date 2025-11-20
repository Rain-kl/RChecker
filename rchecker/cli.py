#!/usr/bin/env python3
"""
Command-line interface for RChecker domain availability checker.
"""
import argparse
import asyncio
import string
import sys

from rchecker.main import  run
from rchecker.resource.wordlist_source import download_wordlist


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


def cli_main():
    """Entry point for the command-line interface."""
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
    cli_main()
