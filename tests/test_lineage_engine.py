import pytest
from src.engines.lineage_engine import LineageIntelligenceEngine
from src.contracts import PASS, FAIL, IMPACTED

def test_downstream_impact_bronze():
    engine = LineageIntelligenceEngine()
    impacted = engine.get_downstream_impact("bronze_orders")
    
    # Should include all silver and gold tables
    assert "silver_orders" in impacted
    assert "gold_metrics" in impacted
    assert "gold_country_revenue" in impacted
    assert "gold_product_sales" in impacted
    
    # Ordering shouldn't technically matter for a set, but let's check it captures them all
    assert len(impacted) == 4

def test_downstream_impact_silver():
    engine = LineageIntelligenceEngine()
    impacted = engine.get_downstream_impact("silver_orders")
    
    # Should only include gold tables
    assert "gold_metrics" in impacted
    assert "gold_country_revenue" in impacted
    assert "gold_product_sales" in impacted
    assert "silver_orders" not in impacted
    assert "bronze_orders" not in impacted

def test_downstream_impact_gold():
    engine = LineageIntelligenceEngine()
    impacted = engine.get_downstream_impact("gold_metrics")
    
    # Gold tables are terminal nodes
    assert len(impacted) == 0

def test_first_failed_layer_bronze_to_silver_bug():
    engine = LineageIntelligenceEngine()
    
    # This is the expected output for the demo bug
    # (Bronze passed perfectly, but the transformation from Bronze to Silver was flawed)
    layer_status = {
        "bronze": PASS,
        "silver": FAIL,
        "gold": IMPACTED
    }
    
    result = engine.first_failed_layer(layer_status)
    assert result == "Bronze \u2192 Silver"

def test_first_failed_layer_source_to_bronze():
    engine = LineageIntelligenceEngine()
    
    # If Bronze is failing, the failure happened between Source and Bronze
    layer_status = {
        "bronze": FAIL,
        "silver": IMPACTED,
        "gold": IMPACTED
    }
    
    result = engine.first_failed_layer(layer_status)
    assert result == "Source \u2192 Bronze"

def test_first_failed_layer_silver_to_gold():
    engine = LineageIntelligenceEngine()
    
    # If Bronze and Silver are fine, but Gold fails, it's a Silver->Gold transform issue
    layer_status = {
        "bronze": PASS,
        "silver": PASS,
        "gold": FAIL
    }
    
    result = engine.first_failed_layer(layer_status)
    assert result == "Silver \u2192 Gold"

def test_first_failed_layer_no_failure():
    engine = LineageIntelligenceEngine()
    
    layer_status = {
        "bronze": PASS,
        "silver": PASS,
        "gold": PASS
    }
    
    result = engine.first_failed_layer(layer_status)
    assert result is None
