import asyncio
import sys

from tqdm import tqdm


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
