"""
RChecker - A high-performance asynchronous domain availability checker.

This package provides tools for checking domain availability using asynchronous HTTP requests
and the RDAP protocol, supporting pattern matching and wordlist modes with checkpoint/resume functionality.
"""

__version__ = "0.1.0"
__author__ = "Rain-kl"

from .main import ProgressManager, RateLimiter, Stats, WORDLIST_SOURCES, main

__all__ = ["ProgressManager", "RateLimiter", "Stats", "WORDLIST_SOURCES", "main"]