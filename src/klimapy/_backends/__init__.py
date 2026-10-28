"""Required Rust engine bridge; depends only on NumPy and the standard library."""

from .rust import backend_info

__all__ = ["backend_info"]
