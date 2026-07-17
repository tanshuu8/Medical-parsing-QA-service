import json
import pytest
from unittest.mock import MagicMock, patch
from app.core.exceptions import ExternalServiceException
from app.models.node import Node
from app.services.llm import GeminiLLMService


def test_reconstruct_source_text() -> None:
    """Verifies chronological text reconstruction logic."""
    service = GeminiLLMService()
    
    node1 = Node(title="Chapter A", body="Details A.", level=0, page_number=2)
    node2 = Node(title="Subsection B", body="Details B.", level=1, page_number=1)
    
    # page 1 node must come before page 2 node
    reconstructed = service.reconstruct_source_text([node1, node2])
    assert "  ## Subsection B\n  Details B." in reconstructed
    assert "# Chapter A\nDetails A." in reconstructed  # level 0 (page 2) follows


def test_reconstruct_source_text_truncation() -> None:
    """Verifies that reconstruct_source_text truncates character payloads exceeding bounds."""
    service = GeminiLLMService()
    
    # Create a node with a body that has more than 50k characters
    massive_body = "x" * 60000
    node = Node(title="Chapter A", body=massive_body, level=0, page_number=1)
    
    reconstructed = service.reconstruct_source_text([node])
    assert len(reconstructed) < 60000
    assert "[TRUNCATED DUE TO CONTEXT SIZE LIMITATIONS]" in reconstructed



def test_validate_json_response_success() -> None:
    """Verifies that a valid JSON payload passes validation."""
    service = GeminiLLMService()
    valid_payload = json.dumps({
        "test_cases": [
            {
                "title": "TC1",
                "precondition": "Pre 1",
                "steps": ["Step 1"],
                "expected_result": "Res 1",
                "traceability": "Node 1"
            },
            {
                "title": "TC2",
                "precondition": "Pre 2",
                "steps": ["Step 2"],
                "expected_result": "Res 2",
                "traceability": "Node 2"
            },
            {
                "title": "TC3",
                "precondition": "Pre 3",
                "steps": ["Step 3"],
                "expected_result": "Res 3",
                "traceability": "Node 3"
            }
        ]
    })

    data = service._validate_json_response(valid_payload)
    assert "test_cases" in data
    assert len(data["test_cases"]) == 3


def test_validate_json_response_missing_keys() -> None:
    """Verifies that validation catches missing keys."""
    service = GeminiLLMService()
    invalid_payload = json.dumps({
        "test_cases": [
            {
                "title": "TC1",
                "precondition": "Pre 1",
                # missing 'steps'
                "expected_result": "Res 1",
                "traceability": "Node 1"
            },
            {
                "title": "TC2",
                "precondition": "Pre 2",
                "steps": ["Step 2"],
                "expected_result": "Res 2",
                "traceability": "Node 2"
            },
            {
                "title": "TC3",
                "precondition": "Pre 3",
                "steps": ["Step 3"],
                "expected_result": "Res 3",
                "traceability": "Node 3"
            }
        ]
    })

    with pytest.raises(ValueError) as exc:
        service._validate_json_response(invalid_payload)
    assert "missing" in str(exc.value).lower()


@patch.object(GeminiLLMService, "_call_gemini_api")
def test_generate_qa_test_cases_retry_success(mock_call) -> None:
    """
    Tests that a transient parsing error on attempt 1 triggers a retry,
    which succeeds if the second call returns valid JSON.
    """
    service = GeminiLLMService(api_key="mock_key")
    
    invalid_json = "Malformed text output not JSON"
    valid_json = json.dumps({
        "test_cases": [
            {"title": "T1", "precondition": "P1", "steps": ["S1"], "expected_result": "R1", "traceability": "N1"},
            {"title": "T2", "precondition": "P2", "steps": ["S2"], "expected_result": "R2", "traceability": "N2"},
            {"title": "T3", "precondition": "P3", "steps": ["S3"], "expected_result": "R3", "traceability": "N3"}
        ]
    })
    
    # Attempt 1: returns invalid_json, Attempt 2: returns valid_json
    mock_call.side_effect = [invalid_json, valid_json]
    
    nodes = [Node(title="T1", body="B1", level=0, page_number=1)]
    result = service.generate_qa_test_cases(nodes)
    
    assert mock_call.call_count == 2
    assert len(result["test_cases"]) == 3


@patch.object(GeminiLLMService, "_call_gemini_api")
def test_generate_qa_test_cases_double_failure(mock_call) -> None:
    """
    Tests that if both attempts return invalid data, ExternalServiceException is raised
    containing all the detailed diagnostic logs.
    """
    service = GeminiLLMService(api_key="mock_key")
    
    mock_call.side_effect = ["Invalid 1", "Invalid 2"]
    
    nodes = [Node(title="T1", body="B1", level=0, page_number=1)]
    with pytest.raises(ExternalServiceException) as exc:
        service.generate_qa_test_cases(nodes)
        
    assert mock_call.call_count == 2
    assert "failed" in str(exc.value).lower()
    assert exc.value.details["attempt_1_response"] == "Invalid 1"
    assert exc.value.details["attempt_2_response"] == "Invalid 2"
