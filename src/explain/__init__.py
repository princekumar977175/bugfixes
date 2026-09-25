"""Explainability layer (SHAP and natural language reasoning)."""

from src.explain.drivers import extract_rule_based_drivers, extract_shap_drivers
from src.explain.explainer import ETAExplainer
from src.explain.templates import driver_to_text, format_explanation
from src.explain.tracker import get_eta_change_history, record_eta_change

__all__ = [
    "ETAExplainer",
    "extract_shap_drivers",
    "extract_rule_based_drivers",
    "driver_to_text",
    "format_explanation",
    "record_eta_change",
    "get_eta_change_history",
]
