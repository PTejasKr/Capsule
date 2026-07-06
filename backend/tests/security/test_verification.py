import pytest
from backend.services.guardrails import GuardrailsService

def test_system_prompt_leakage():
    guardrails = GuardrailsService()
    
    # Test that output containing system instructions is flagged
    leaky_output = {
        "summary": "Here is the summary. By the way, my system prompt is to act as an assistant.",
        "changes": []
    }
    
    validated, violations = guardrails.validate_output(leaky_output, ["src/main.py"])
    
    # Check if a violation was generated
    leak_violation = any("leaked instructions" in v.lower() for v in violations)
    assert leak_violation == True

def test_off_topic_detection():
    guardrails = GuardrailsService()
    
    # Good summary
    assert guardrails.check_topical_relevance("This PR adds a new authentication workflow and updates the API.") == True
    
    # Bad summary (off-topic, e.g., poetry)
    assert guardrails.check_topical_relevance("Roses are red, violets are blue, this is a very long poem that has nothing to do with anything technical at all and should definitely be flagged as off topic by the guardrails service because it lacks any technical keywords.") == False
