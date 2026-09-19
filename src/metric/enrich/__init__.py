"""Enrichment: how an agent meets a situation, and what that varies.

Importing this package registers the materialisers that ship with it, so a corpus can
name 'voice' without knowing which module defines it.
"""

from metric.enrich import voice as _voice  # noqa: F401  - registers "voice"
