import re
import json
import logging
from typing import List, Dict, Any, Tuple
from backend.middleware.security import sanitize_text

logger = logging.getLogger("capsule.guardrails")

class GuardrailsService:
    def __init__(self):
        pass

    def sanitize_input(self, content: str) -> str:
        """
        Cleans input content to prevent prompt injections, system overrides, and homoglyphs.
        """
        if not content:
            return ""
        return sanitize_text(content)

    def check_topical_relevance(self, summary: str) -> bool:
        """
        Verify that the output summary is about code analysis, workflows, or software changes.
        Flags if it looks off-topic (e.g. conversational chit-chat, poetry, unrelated fields).
        """
        if not summary:
            return True
            
        topic_keywords = [
            "code", "file", "change", "diff", "workflow", "process", 
            "function", "class", "variable", "database", "api", "query", 
            "version", "git", "pr", "pull request", "merge", "approval"
        ]
        
        summary_lower = summary.lower()
        matches = [kw for kw in topic_keywords if kw in summary_lower]
        
        # If it contains at least one topic keyword or is very short, consider it relevant
        if len(matches) > 0 or len(summary) < 50:
            return True
            
        logger.warning(f"Off-topic detection flag raised for summary: '{summary[:100]}...'")
        return False

    def validate_output(self, ai_output: Dict[str, Any], diff_files: List[str]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Validates the structure and consistency of the AI output.
        Returns a tuple of (validated_output_dict, list_of_violations).
        """
        violations = []
        validated = ai_output.copy()
        
        # 1. Enforce changes structure
        changes = validated.get("changes", [])
        if not isinstance(changes, list):
            violations.append("Changes field must be a list")
            validated["changes"] = []
            changes = []
            
        validated_changes = []
        for i, change in enumerate(changes):
            if not isinstance(change, dict):
                violations.append(f"Change item at index {i} is not a dictionary")
                continue
                
            file = change.get("file", "").strip()
            line_range = str(change.get("line_range", "")).strip()
            change_type = str(change.get("change_type", "")).strip().lower()
            description = change.get("description", "").strip()
            confidence = change.get("confidence", 1.0)
            
            # Plausibility check: file path must be non-empty
            if not file:
                violations.append(f"Change item {i} has an empty file reference")
                continue
                
            # Plausibility check: line range parsing
            if line_range:
                # Check for negative numbers or absurd values (e.g. > 100,000 lines)
                num_matches = re.findall(r"\d+", line_range)
                for num_str in num_matches:
                    val = int(num_str)
                    if val < 0 or val > 100000:
                        violations.append(f"Change item {i} has implausible line range: '{line_range}'")
                        line_range = "unknown"
                        break
            else:
                line_range = "unknown"

            # Enforce enum values
            if change_type not in ["added", "modified", "deleted"]:
                violations.append(f"Change item {i} has invalid change_type '{change_type}'")
                change_type = "modified"

            # Enforce confidence range
            try:
                conf_val = float(confidence)
                if conf_val < 0.0 or conf_val > 1.0:
                    violations.append(f"Change item {i} has confidence out of range: {confidence}")
                    confidence = min(max(conf_val, 0.0), 1.0)
            except (ValueError, TypeError):
                violations.append(f"Change item {i} has non-numeric confidence: {confidence}")
                confidence = 1.0
                
            # Check if file exists in diff
            normalized_file = file.replace("\\", "/")
            is_found = False
            for df in diff_files:
                if normalized_file == df or df.endswith("/" + normalized_file) or normalized_file.endswith("/" + df):
                    is_found = True
                    file = df  # Normalize to the actual file path
                    break
                    
            if not is_found:
                violations.append(f"Change item {i} references file not in diff: '{file}'")
                continue # Skip/remove this change item (hallucinated file)

            validated_changes.append({
                "file": file,
                "line_range": line_range,
                "change_type": change_type,
                "description": description,
                "confidence": confidence
            })
            
        validated["changes"] = validated_changes

        # 2. Enforce workflow_impact structure
        wf = validated.get("workflow_impact", {})
        if not isinstance(wf, dict):
            violations.append("workflow_impact must be a dictionary")
            wf = {}
            
        has_impact = bool(wf.get("has_impact", False))
        severity = str(wf.get("severity", "none")).strip().lower()
        if severity not in ["none", "minor", "major"]:
            violations.append(f"Workflow impact has invalid severity: '{severity}'")
            severity = "none"
            
        validated["workflow_impact"] = {
            "has_impact": has_impact,
            "severity": severity,
            "impact_description": wf.get("impact_description", ""),
            "affected_workflows": list(wf.get("affected_workflows", [])),
            "before_state": wf.get("before_state", ""),
            "after_state": wf.get("after_state", "")
        }

        # 3. Overall confidence validation
        conf_score = validated.get("confidence_score", 1.0)
        try:
            val = float(conf_score)
            validated["confidence_score"] = min(max(val, 0.0), 1.0)
        except (ValueError, TypeError):
            validated["confidence_score"] = 1.0

        # 4. Check for leaked system instructions
        output_str = json.dumps(validated).lower()
        leak_keywords = ["system prompt", "you are an ai", "developer instructions", "ignore previous"]
        for kw in leak_keywords:
            if kw in output_str:
                violations.append(f"Output contains potential leaked instructions: '{kw}'")

        return validated, violations

    def calculate_hallucination_risk(self, ai_output: Dict[str, Any], diff_content: str) -> float:
        """
        Calculates a risk score (0.0 to 1.0) representing the likelihood of hallucination.
        Risk is elevated by:
        - Changes referencing files not mentioned anywhere in the raw diff text.
        - Low confidence scores.
        - Highly inconsistent descriptions.
        """
        risk = 0.0
        changes = ai_output.get("changes", [])
        if not changes:
            return 0.0

        unreferenced_files = 0
        low_confidence_items = 0
        
        for change in changes:
            file = change.get("file", "")
            confidence = change.get("confidence", 1.0)
            
            # Simple string check: does the filename appear in the diff text?
            if file and file not in diff_content:
                unreferenced_files += 1
                
            if confidence < 0.7:
                low_confidence_items += 1
                
        # Calculate components
        file_risk = (unreferenced_files / len(changes)) * 0.7
        conf_risk = (low_confidence_items / len(changes)) * 0.3
        
        risk = file_risk + conf_risk
        
        # Overall confidence score adjustment
        overall_conf = ai_output.get("confidence_score", 1.0)
        if overall_conf < 0.8:
            risk = min(1.0, risk + (0.8 - overall_conf))
            
        return round(risk, 2)
