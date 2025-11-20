import asyncio
import json
import os
import sys
from typing import Set


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

