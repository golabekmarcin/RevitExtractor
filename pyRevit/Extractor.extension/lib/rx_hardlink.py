# -*- coding: utf-8 -*-
"""NTFS hard links for staging cloud models without copying them (experimental, opt-in).

No Revit, .NET or clr import. Compatible with pyRevit IronPython 2.7, which has no os.link:
there the link is made with kernel32.CreateHardLinkW through ctypes (no admin rights needed).
A hard link is a second name for the same file on the same volume. It never changes the
source; removing the link never touches the source's data. The caller falls back to a copy
when this raises (different drive, a file system without links, no permission).
"""
from __future__ import unicode_literals

import os

PREFERENCE_KEY = "cloud_hardlinks"


def hardlinks_enabled(preferences):
    """True only when the preferences dict says cloud_hardlinks is exactly true."""
    return isinstance(preferences, dict) and preferences.get(PREFERENCE_KEY) is True


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
