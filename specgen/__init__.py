"""specgen — SpecsIntact .SEC parsing, round-trip, and decision-manifest tools.

Phase 0 of the UFGS Spec Section Generator: prove we can read a UFGS master
section losslessly, enumerate every decision point it contains (brackets,
blanks, tailoring options, submittals, references), and re-emit a
byte-identical file.
"""

__version__ = "0.1.0"
