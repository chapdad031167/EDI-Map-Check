"""Output-file adapters: JSON and keyed-flat formats onto one canonical model."""

from mapcheck.output.adapter import MISSING, CanonicalOutput, OutputLoadError, load_output

__all__ = ["MISSING", "CanonicalOutput", "OutputLoadError", "load_output"]
