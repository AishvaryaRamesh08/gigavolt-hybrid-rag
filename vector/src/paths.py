"""paths.py - project folders, resolved from this file's location (works from any working directory)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUALS = ROOT / "manuals"
RESULTS = ROOT / "results"
DATA = ROOT / "data"
INCIDENTS = DATA / "incident_reports.txt"
