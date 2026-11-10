"""Deterministic arithmetic for bank products in Türkiye, exact to the kuruş.

The library computes; it does not quote prices or give advice. Rates, levies and conventions are
inputs, and every result says which conventions produced it.
"""

from .errors import InputError

__version__ = "0.1.0"

__all__ = ["InputError", "__version__"]
