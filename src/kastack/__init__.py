"""Kastack: a local, deterministic message-processing pipeline.

Pipeline modules:
  - classifier:  Part 1 - message classification into six categories
  - extractor:   Part 2 - task and event extraction
  - sensitive:   Part 3 - sensitive-information detection and masking
"""

__version__ = "1.0.0"