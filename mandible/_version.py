"""Single source of truth for the Mandible version (semver).

CI reads this file to stamp the Windows version resource, the installer and the
release artifact names, and refuses to build a tag that does not match it.
"""
__version__ = "0.1.4"
