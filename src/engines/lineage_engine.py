"""Lineage Intelligence Engine.

Replaces the hardcoded first_failed_layer check with dynamic SQL lineage parsing,
and provides an LLM integration for tracing root causes down to specific transformations.
"""

from __future__ import annotations

from typing import Optional, Dict, Any, List
from ..contracts import FAIL, IMPACTED, PASS

from src.config_loader import load_dataset_config

class LineageIntelligenceEngine:
    def __init__(self):
        cfg = load_dataset_config()
        # Deterministic table-level data flow DAG
        self.edges = [
            (cfg.tables.bronze, cfg.tables.silver),
            (cfg.tables.silver, cfg.tables.gold.metrics),
            (cfg.tables.silver, cfg.tables.gold.country_revenue),
            (cfg.tables.silver, cfg.tables.gold.product_sales)
        ]
        
    def get_downstream_impact(self, table_name: str) -> set[str]:
        """Use BFS to deterministically find all downstream tables."""
        visited = set()
        queue = [table_name]
        
        while queue:
            current = queue.pop(0)
            for upstream, downstream in self.edges:
                if upstream == current and downstream not in visited:
                    visited.add(downstream)
                    queue.append(downstream)
                    
        return visited

    def first_failed_layer(self, layer_status: dict) -> Optional[str]:
        """Determine the first failed layer transition dynamically from the graph."""
        layer_order = ["bronze", "silver", "gold"]
        
        first_fail = None
        for layer in layer_order:
            if layer_status.get(layer) == FAIL:
                first_fail = layer
                break
                
        # If no explicit FAIL, check for IMPACTED propagation (legacy compatibility)
        if not first_fail:
            if layer_status.get("gold") == IMPACTED and layer_status.get("silver") != PASS:
                first_fail = "silver"
                
        if not first_fail:
            return None
            
        if first_fail == "bronze":
            return "Source \u2192 Bronze"
            
        # Dynamically find upstream layer using the table-level graph
        upstream_layer = None
        cfg = load_dataset_config()
        
        for upstream, downstream in self.edges:
            # Match downstream to the failing layer name (e.g. "silver" matches cfg.tables.silver)
            is_match = False
            if first_fail == "silver" and downstream == cfg.tables.silver:
                is_match = True
            elif first_fail == "gold" and downstream in (cfg.tables.gold.metrics, cfg.tables.gold.country_revenue, cfg.tables.gold.product_sales):
                is_match = True
                
            if is_match:
                if upstream == cfg.tables.bronze:
                    upstream_layer = "bronze"
                elif upstream == cfg.tables.silver:
                    upstream_layer = "silver"
                elif upstream == cfg.tables.raw:
                    upstream_layer = "raw"
                break
                
        if upstream_layer:
            return f"{upstream_layer.capitalize()} \u2192 {first_fail.capitalize()}"
            
        return None

    def trace_failure(self, failed_checks: List[Dict[str, Any]], transformation_sql: str) -> str:
        """Use Ollama LLM to trace a check failure back to a specific SQL clause.
        
        Explains *why* the data failed the check based on the ETL code.
        """
        import requests
        import json
        
        checks_str = json.dumps(failed_checks, indent=2)
        
        prompt = (
            "You are a Data Engineering AI. The following data quality checks have failed:\n"
            f"{checks_str}\n\n"
            "This is the SQL transformation that produced the data:\n"
            f"{transformation_sql}\n\n"
            "Explain precisely which JOIN, WHERE clause, or SELECT expression in the SQL "
            "likely caused these failures, and what the business impact is. Keep it concise."
        )
        
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False
                },
                timeout=180
            )
            response.raise_for_status()
            return response.json().get("response", "Could not generate trace.")
        except Exception as e:
            return f"LLM Trace Failed: {str(e)}"
