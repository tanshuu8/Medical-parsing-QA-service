import abc
import json
import logging
from typing import Any, Dict, List, Optional
import google.generativeai as genai
from app.core.exceptions import ExternalServiceException
from app.models.node import Node

logger = logging.getLogger("app.llm_service")


class LLMServiceInterface(abc.ABC):
    """
    Abstract interface for interacting with LLM APIs (Google Gemini).
    """
    @abc.abstractmethod
    def reconstruct_source_text(self, nodes: List[Node]) -> str:
        """
        Reconstructs the original document text blocks chronologically from SQL Nodes.
        """
        pass

    @abc.abstractmethod
    def generate_qa_test_cases(self, nodes: List[Node]) -> Dict[str, Any]:
        """
        Generates 3-5 QA Test Cases from document nodes context.
        Validates schema structure, performs a single retry on parsing failures,
        and throws an exception if the retry fails.
        """
        pass


class GeminiLLMService(LLMServiceInterface):
    """
    Concrete service wrapper using google-generativeai client SDK to run structured JSON prompts.
    """
    def __init__(self, api_key: Optional[str] = None, default_model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.default_model = default_model
        
        # Configure Gemini API if key is available
        if self.api_key:
            genai.configure(api_key=self.api_key)

    def reconstruct_source_text(self, nodes: List[Node]) -> str:
        """
        Chronologically orders nodes by page number and levels, then concatenates content blocks.
        Enforces a maximum safety characters count limit to prevent context window overflow.
        """
        if not nodes:
            return ""
            
        # Sort nodes chronologically by page and hierarchical depth level
        sorted_nodes = sorted(nodes, key=lambda n: (n.page_number, n.level))
        
        text_blocks = []
        for node in sorted_nodes:
            indent = "  " * node.level
            header_prefix = "#" * (node.level + 1)
            
            block_text = f"{indent}{header_prefix} {node.title}\n{indent}{node.body}"
            text_blocks.append(block_text)
            
        full_text = "\n\n".join(text_blocks)
        
        # Prevent context window overflow (e.g. max 50k characters safety boundary)
        MAX_CHARS = 50000
        if len(full_text) > MAX_CHARS:
            logger.warning(f"Reconstructed source text size ({len(full_text)} chars) exceeds safety threshold of {MAX_CHARS}. Truncating payload.")
            full_text = full_text[:MAX_CHARS] + "\n\n... [TRUNCATED DUE TO CONTEXT SIZE LIMITATIONS] ..."
            
        return full_text

    def _validate_json_response(self, raw_text: str) -> Dict[str, Any]:
        """
        Checks if the response conforms to the strict QA Test Cases JSON schema.
        Expected format:
        {
          "test_cases": [
            {
              "title": "Title",
              "precondition": "Precondition text",
              "steps": ["Step 1", "Step 2"],
              "expected_result": "Expected outcome text",
              "traceability": "Node reference"
            }
          ]
        }
        """
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as je:
            raise ValueError(f"Invalid JSON format. Decoder error: {je}")

        if not isinstance(data, dict) or "test_cases" not in data:
            raise ValueError("Root element must be a JSON object containing a 'test_cases' list key.")

        test_cases = data["test_cases"]
        if not isinstance(test_cases, list):
            raise ValueError("'test_cases' must be a JSON array.")

        if not (3 <= len(test_cases) <= 5):
            raise ValueError(f"Generations count constraint violation: must contain between 3 and 5 test cases, got {len(test_cases)}.")

        required_keys = {"title", "precondition", "steps", "expected_result", "traceability"}
        for idx, tc in enumerate(test_cases):
            if not isinstance(tc, dict):
                raise ValueError(f"Test case index {idx} must be a JSON object.")
                
            missing_keys = required_keys - set(tc.keys())
            if missing_keys:
                raise ValueError(f"Test case index {idx} is missing required fields: {missing_keys}")
                
            if not isinstance(tc["steps"], list) or not all(isinstance(s, str) for s in tc["steps"]):
                raise ValueError(f"Test case index {idx} 'steps' attribute must be an array of strings.")

        return data

    def _call_gemini_api(self, prompt: str) -> str:
        """Runs the generation call against Google Gemini model API."""
        if not self.api_key or self.api_key == "mock_key" or self.api_key.startswith("YOUR_"):
            # Safe mock return when API key is missing or dummy (e.g. testing environments)
            logger.warning("Gemini API key is not configured or dummy. Returning dummy mock payload.")
            return json.dumps({
                "test_cases": [
                    {
                        "title": "Verification of clinical display range",
                        "precondition": "The device clinical display unit is connected and operational.",
                        "steps": ["Navigate to display settings.", "Select oncology threshold range options."],
                        "expected_result": "The screen updates displaying oncology range markers.",
                        "traceability": "Mock Node Reference"
                    },
                    {
                        "title": "Validation of chemotherapy alarms configuration",
                        "precondition": "Alarm threshold parameters are configured to default ranges.",
                        "steps": ["Manually inject a mock high-flow volume trigger.", "Check visual alerts warning indicator displays."],
                        "expected_result": "Red flashing alarm indicator activates within 2 seconds.",
                        "traceability": "Mock Node Reference"
                    },
                    {
                        "title": "Confirmation of document version match checks",
                        "precondition": "V1 manual and V2 updates are loaded in SQLite.",
                        "steps": ["Initialize version comparison alignments trigger.", "Query changes status listings."],
                        "expected_result": "Matching alignments write a diff status logs summary inside MongoDB.",
                        "traceability": "Mock Node Reference"
                    }
                ]
            })

        try:
            model = genai.GenerativeModel(self.default_model)
            
            # Configure response schema constraints to force structured outputs
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API request failed: {e}")
            raise ExternalServiceException(f"Google Gemini service failed to process request: {e}")

    def generate_qa_test_cases(self, nodes: List[Node]) -> Dict[str, Any]:
        """
        Performs source text reconstruction, structured prompt generation,
        JSON schema validations, and triggers a single retry on failures.
        """
        source_text = self.reconstruct_source_text(nodes)
        
        # Professional system prompt specifying the generation rules
        system_instruction = (
            "You are a Senior Medical Device Quality Assurance Verification Engineer.\n"
            "Analyze the medical device documentation source text provided below and generate between 3 and 5 professional QA Test Cases.\n"
            "Each test case must verify safety, functionality, or user interface constraints documented in the text.\n\n"
            "You MUST output exactly a JSON object matching this schema:\n"
            "{\n"
            "  \"test_cases\": [\n"
            "    {\n"
            "      \"title\": \"Descriptive verification title\",\n"
            "      \"precondition\": \"Necessary system preconditions before test execution\",\n"
            "      \"steps\": [\"Step 1 description\", \"Step 2 description\"],\n"
            "      \"expected_result\": \"Expected outcome of the verification steps\",\n"
            "      \"traceability\": \"Provide reference to the section title or context of origin\"\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "1. Generate between 3 and 5 test cases. No more, no less.\n"
            "2. Do NOT wrap the JSON inside markdown blocks or add extra explanations.\n"
            "3. Ensure strict adherence to the schema keys.\n"
        )
        
        prompt = f"{system_instruction}\n\nSource Medical Document Content:\n{source_text}"
        
        # --- Attempt 1 ---
        logger.info("Submitting Test Cases generation request to Gemini (Attempt 1).")
        raw_output = self._call_gemini_api(prompt)
        
        try:
            validated_data = self._validate_json_response(raw_output)
            logger.info("Successfully generated and validated QA Test Cases (Attempt 1).")
            return validated_data
        except Exception as err:
            logger.warning(f"Attempt 1 failed JSON validation: {err}. Retrying call once.")
            
            # --- Attempt 2 (Retry) ---
            # Append parsing error instructions to force correction
            retry_prompt = (
                f"{prompt}\n\n"
                f"WARNING: Your previous response failed validation with error: '{err}'.\n"
                f"Previous Response Output:\n{raw_output}\n\n"
                f"Please correct the error, ensure all keys ('title', 'precondition', 'steps', 'expected_result', 'traceability') exist, "
                f"and output strict compliant JSON."
            )
            
            raw_output_retry = self._call_gemini_api(retry_prompt)
            try:
                validated_data = self._validate_json_response(raw_output_retry)
                logger.info("Successfully generated and validated QA Test Cases on Retry (Attempt 2).")
                return validated_data
            except Exception as retry_err:
                logger.error(f"Retry (Attempt 2) failed JSON validation: {retry_err}")
                # Save failure metadata details in exception payload so router can log it in MongoDB
                error_payload = {
                    "prompt": prompt,
                    "attempt_1_response": raw_output,
                    "attempt_1_error": str(err),
                    "attempt_2_response": raw_output_retry,
                    "attempt_2_error": str(retry_err)
                }
                raise ExternalServiceException(
                    message=f"Structured QA Test Cases generation failed. Details: {retry_err}",
                    details=error_payload
                ) from retry_err
