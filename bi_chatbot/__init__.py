"""BI-Chatbot-Prototyp: interaktive Erstellung von BI-Auswertungen im Dialog."""
from .state import AnalysisContext, Series
from .schema import Interpretation

__all__ = ["AnalysisContext", "Series", "Interpretation"]
__version__ = "0.1.0"
