"""Source adapters that normalize each camera feed provider into one schema.

Each adapter exposes ``load(...)`` returning a list of records shaped by
``adapters.schema.record``. ``build.py`` merges them into ``cameras.json``.
"""
