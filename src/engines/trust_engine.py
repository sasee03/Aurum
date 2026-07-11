"""Trust Scoring Engine.

Upgrades the simple verdict logic to a numerical trust score with LLM-generated narrative.
"""

from __future__ import annotations

from typing import Iterable, Dict, Any
from ..contracts import (
    CheckResult, FAIL, IMPACTED, WARN, PASS, SKIPPED, NOT_TRUSTED, WARNING, TRUSTED
)

class TrustScoringEngine:
    def __init__(self):
        # Deterministic weights for scoring
        self.weights = {
            FAIL: -50,
            IMPACTED: -10,
            WARN: -5,
            PASS: 0,
            SKIPPED: 0
        }
        self.base_score = 100

    def compute_score(self, check_results: Iterable) -> int:
        """Calculate a deterministic 0-100 score based on check severities."""
        score = self.base_score
        for r in check_results:
            if isinstance(r, str):
                status = r
            else:
                status = r.status if hasattr(r, 'status') else r.get("status", PASS)
            score += self.weights.get(status, 0)
        
        return max(0, min(100, score))

    def compute_verdict_from_score(self, score: int) -> tuple[str, str]:
        """Map the numerical score back to the frozen contract string."""
        if score < 70:
            return NOT_TRUSTED, "HIGH"
        elif score < 100:
            return WARNING, "MEDIUM"
        else:
            return TRUSTED, "LOW"

    def generate_trust_narrative(
        self,
        score: int,
        business_impact: dict,
        root_cause: dict,
        *,
        timeout_seconds: float = 180,
    ) -> str:
        """Use Ollama LLM to explain the trust score to a business stakeholder."""
        import requests
        import json
        
        prompt = (
            "You are a Data Trust Executive. The data pipeline has completed its validation.\n"
            f"Trust Score: {score}/100\n"
            f"Business Impact: {json.dumps(business_impact)}\n"
            f"Root Cause: {json.dumps(root_cause)}\n\n"
            "Write a very brief (2-3 sentences) executive summary explaining why the data "
            "earned this score and if it is safe to use. Do not use technical jargon."
        )
        
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False
                },
                timeout=timeout_seconds
            )
            response.raise_for_status()
            return response.json().get("response", "Could not generate narrative.")
        except Exception as e:
            return f"Narrative Generation Failed: {str(e)}"
