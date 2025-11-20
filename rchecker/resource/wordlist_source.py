import os
import ssl
import string
import sys
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


def list_available_wordlists() -> None:
    """Display available wordlists."""
    print("Available wordlists:")
    print("=" * 50)
    for name, info in WORDLIST_SOURCES.items():
        print(f"  {name:<15} - {info['description']}")


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
