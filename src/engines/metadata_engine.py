"""Universal Metadata Engine.

Provides a unified interface for data quality rules, schemas, and configurations.
It serves as the deterministic source of truth for the rule library.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from ..table_specs import TABLE_SPECS

class UniversalMetadataEngine:
    def __init__(self):
        # We start by wrapping the deterministic static configuration
        self.specs: Dict[str, Any] = TABLE_SPECS

    def get_table_spec(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Return the metadata specification for a given table."""
        return self.specs.get(table_name)

    def get_all_tables(self) -> list[str]:
        """Return all tables registered in the metadata catalog."""
        return list(self.specs.keys())

    def explain_metadata_profile(self, table_profile: Dict[str, Any]) -> str:
        """Use Ollama LLM to explain the semantic intent of a table based on its deterministic profile.
        
        This method operates entirely outside the deterministic decision path.
        It generates a human-readable narrative explaining the candidate keys and column stats.
        """
        import json
        import requests
        
        profile_json = json.dumps(table_profile, indent=2)
        
        prompt = (
            "You are a Data Engineering Explanation AI. You have been provided with a deterministic "
            "statistical profile of a database table (which includes exact null counts, uniqueness percentages, "
            "and inferred candidate keys).\n\n"
            f"Profile:\n{profile_json}\n\n"
            "Based strictly on this data, provide a short 3-4 sentence business explanation of what this table represents, "
            "and explain why the candidate keys were chosen (e.g. they are 100% unique and non-null)."
        )
        
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3",  # default model, can be configured
                    "prompt": prompt,
                    "stream": False
                },
                timeout=180
            )
            response.raise_for_status()
            return response.json().get("response", "Could not generate explanation.")
        except Exception as e:
            return f"Explanation generation failed: {str(e)}"
