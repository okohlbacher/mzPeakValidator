"""mzPeakValidator — a language-independent-by-design validator for the HUPO-PSI mzPeak format.

Public API (re-exported from .core):
    run(archive_path, profile=None, profiles_root=PROFILES_ROOT, quick=False) -> dict
    main()                      # CLI entry point (console script: mzpeak-validate)
    Archive, Profile, Report, resolve_profile, PRIMITIVES, CATALOG_VERSION, PROFILES_ROOT
"""
from .core import (run, main, Archive, Profile, Report, resolve_profile,
                   PRIMITIVES, CATALOG_VERSION, PROFILES_ROOT)

__all__ = ["run", "main", "Archive", "Profile", "Report", "resolve_profile",
           "PRIMITIVES", "CATALOG_VERSION", "PROFILES_ROOT", "__version__"]
try:
    from importlib.metadata import version as _v
    __version__ = _v("mzpeak-validator")
except Exception:
    __version__ = "0.9.14"
