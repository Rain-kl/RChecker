import asyncio
import ssl
import sys

import aiohttp


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
