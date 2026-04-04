"""
Guardian module package marker.

Keep this package lightweight so the supervisor can import submodules in
parallel threads without recursive wildcard-import deadlocks.
"""

__all__: list[str] = []
