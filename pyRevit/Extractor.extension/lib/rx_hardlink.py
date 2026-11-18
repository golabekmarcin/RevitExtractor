# -*- coding: utf-8 -*-
"""NTFS hard links for staging cloud models without copying them (on by default; H8 passed 2026-11-18).

No Revit, .NET or clr import. Compatible with pyRevit IronPython 2.7, which has no os.link:
there the link is made with kernel32.CreateHardLinkW through ctypes (no admin rights needed).
A hard link is a second name for the same file on the same volume. It never changes the
source; removing the link never touches the source's data. The caller falls back to a copy
when this raises (different drive, a file system without links, no permission).
"""
from __future__ import unicode_literals

import os

PREFERENCE_KEY = "cloud_hardlinks"
MODE_KEY = "cloud_staging"
# links = host and links as real-name hard links (default); host-only and direct are experiments:
# the Extractor gets only the host as a link, or the host's cache path itself (nothing staged).
STAGING_MODES = ("links", "host-only", "direct")


def hardlinks_enabled(preferences):
    """True unless the preferences dict says cloud_hardlinks is exactly false. A missing or
    unreadable preferences file means on: a link that cannot be made falls back to a copy."""
    return not (isinstance(preferences, dict) and preferences.get(PREFERENCE_KEY) is False)


def staging_mode(preferences):
    """The cloud_staging preference; anything else, missing or unreadable means "links"."""
    value = preferences.get(MODE_KEY) if isinstance(preferences, dict) else None
    return value if value in STAGING_MODES else "links"


def make_hard_link(source, link_path, os_link=getattr(os, "link", None), kernel32=None):
    """Create `link_path` as a hard link to the existing file `source`. Raises OSError when it
    cannot. Never overwrites: an existing `link_path` is an error."""
    if os_link is not None:
        os_link(source, link_path)
        return
    if kernel32 is None:
        import ctypes
        kernel32 = ctypes.windll.kernel32
    created = kernel32.CreateHardLinkW(link_path, source, None)
    if not created:
        import ctypes
        raise OSError(ctypes.GetLastError(), "CreateHardLinkW failed")
