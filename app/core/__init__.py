"""Core services are imported by their callers when needed.

Keep this package lightweight: the home page only needs file associations,
so importing it must not also load PyMuPDF, worker threads or LLM services.
"""
