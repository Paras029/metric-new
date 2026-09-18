"""Admission: what a candidate has to survive to become a triple."""

from metric.admit.gate import Admission, admit
from metric.admit.grounding import Location, locate, normalised

__all__ = ["Admission", "Location", "admit", "locate", "normalised"]
