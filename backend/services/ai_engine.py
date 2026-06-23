import json
import logging
import hashlib
import time
from typing import List, Dict, Any, Tuple, Optional
import asyncio
from openai import AsyncOpenAI
from backend.config import settings
from backend.models.schemas import PRSummary, ChangeItem, WorkflowImpact, ChangeType, Severity
from backend.database import insert

logger = logging.getLogger("capsule.ai_engine")

class AIEngine:
    def __init__(self):
        # Initialize AsyncOpenAI client pointing to NVIDIA NIM
        self.client = AsyncOpenAI(
            base_url=settings.NVIDIA_NIM_BASE_URL,
            api_key=settings.NVIDIA_NIM_API_KEY
        )
        self.model = settings.NVIDIA_NIM_MODEL

    def _parse_diff_files(self, diff: str) -> List[str]:
        """
        Parses a unified diff and returns a list of all files that were added, modified, or deleted.
        """
        changed_files = set()
        for line in diff.splitlines():
            if line.startswith("--- a/"):
                file_path = line[6:].strip()
                if file_path and file_path != "/dev/null":
                    # Split on space or tab to clean up any additional headers
                    file_path = file_path.split(" ")[0].split("\t")[0]
                    changed_files.add(file_path)
            elif line.startswith("+++ b/"):
                file_path = line[6:].strip()
                if file_path and file_path != "/dev/null":
                    file_path = file_path.split(" ")[0].split("\t")[0]
                    changed_files.add(file_path)
        return list(changed_files)

    def cross_validate_output(self, ai_output: Dict[str, Any], actual_files: List[str]) -> Dict[str, Any]:
        """
        Strict anti-hallucination check: validates that all file paths mentioned in the AI output
        are physically present in the actual diff files list. Removes any fabricated references.
        """
        changes = ai_output.get("changes", [])
        validated_changes = []
        removed_count = 0

        for change in changes:
            file_path = change.get("file", "").strip().replace("\\", "/")
            if not file_path:
                continue
                
            is_valid = False
            # Check for exact or suffix match to accommodate relative paths
            for actual in actual_files:
                if file_path == actual or actual.endswith("/" + file_path) or file_path.endswith("/" + actual):
                    is_valid = True
                    # Normalize to actual repo filepath
                    change["file"] = actual
                    break

            if is_valid:
                validated_changes.append(change)
            else:
                logger.warning(f"HALLUCINATION SHIELD: File '{file_path}' not in PR diff. Removing from output changes.")
                removed_count += 1

        ai_output["changes"] = validated_changes
        
        # Penalize confidence score if files were fabricated
        orig_confidence = float(ai_output.get("confidence_score", 1.0))
        if changes:
            penalty = (removed_count / len(changes)) * 0.5
            new_confidence = max(0.0, orig_confidence - penalty)
            ai_output["confidence_score"] = round(new_confidence, 2)
        else:
            ai_output["confidence_score"] = 0.0

        return ai_output

    def _build_system_prompt(self, brd_content: str) -> str:
        """
        Builds the grounded system prompt with BRD context and anti-hallucination guidelines.
        """
        return f"""You are Antigravity Capsule, an elite code change analysis AI. Your job is to analyze code diffs against a Business Requirement Document (BRD) and output a structured analysis.

=== CRITICAL ANTI-HALLUCINATION INSTRUCTIONS ===
1. ONLY list file paths, line numbers, or code changes that exist inside the provided Pull Request Diff.
2. NEVER speculate, infer, or assume changes. If a file is not in the diff, it MUST NOT appear in your output.
3. Compare the technical changes in the diff against the Business Requirement Document (BRD) below.
4. Detect if the diff changes, violates, or implements any business workflows, state transitions, or processes described in the BRD.
5. Provide a confidence rating (0.0 to 1.0) for every change item and the overall analysis. If you are uncertain, rate it low.

=== BUSINESS REQUIREMENT DOCUMENT (BRD) ===
{brd_content}
=== END OF BRD ===

You MUST output your response as a valid JSON object matching this schema:
{{
  "summary": "High-level summary of the overall changes and workflow impact",
  "changes": [
    {{
      "file": "path/to/file.py",
      "line_range": "12-25",
      "change_type": "added|modified|deleted",
      "description": "Specific code change details",
      "confidence": 0.95
    }}
  ],
  "workflow_impact": {{
    "has_impact": true|false,
    "severity": "none|minor|major",
    "impact_description": "Explanation of how the code changes impact the BRD workflows",
    "affected_workflows": ["Order Processing Workflow", "User Registration"],
    "before_state": "Step A -> Step B",
    "after_state": "Step A -> Step C -> Step B"
  }},
  "confidence_score": 0.98
}}
"""

    async def _log_audit(self, pr_number: int, input_hash: str, output: Dict[str, Any], tokens: int, latency_ms: float, model: str):
        """
        Logs the transaction to the database audit trail.
        """
        try:
            audit_data = {
                "pr_number": pr_number,
                "input_hash": input_hash,
                "output_json": json.dumps(output),
                "model": model,
                "tokens": tokens,
                "latency_ms": latency_ms
            }
            await insert("audit_log", audit_data)
        except Exception as e:
            logger.error(f"Failed to log audit details: {e}")

    async def _analyze_chunk(self, chunk: str, brd_content: str, model: str) -> Dict[str, Any]:
        """Analyze a single diff chunk and return the raw JSON output from the LLM."""
        system_prompt = self._build_system_prompt(brd_content)
        user_prompt = f"Analyze the following unified diff chunk:\n\n{chunk}"
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
        content = response.choices[0].message.content
        return json.loads(content)

    def _chunk_diff(self, diff: str, max_lines: int = 300) -> List[str]:
        """Split a unified diff into chunks limited by max_lines, grouping by file boundaries."""
        lines = diff.splitlines(keepends=True)
        chunks: List[str] = []
        current_chunk: List[str] = []
        line_count = 0
        for line in lines:
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                # If starting new file and current chunk would exceed size, flush
                if line_count >= max_lines and current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
                    line_count = 0
            current_chunk.append(line)
            line_count += 1
            if line_count >= max_lines:
                chunks.append("".join(current_chunk))
                current_chunk = []
                line_count = 0
        if current_chunk:
            chunks.append("".join(current_chunk))
        # Ensure each chunk ends with a newline for proper reconstruction
        chunks = [c if c.endswith("\n") else c + "\n" for c in chunks]
        return chunks

    async def _critic_review(self, combined_output: Dict[str, Any], diff: str, model: str) -> Dict[str, Any]:
        """Run a critic LLM pass to verify combined output against the raw diff, removing hallucinatory entries."""
        system_prompt = "You are a critic reviewing AI analysis of a PR. Ensure that every file listed in the JSON output actually exists in the provided diff. Remove any entries that are not present. Return a cleaned JSON matching the original schema."
        user_prompt = f"Diff:\n{diff}\n\nCombined Output:\n{json.dumps(combined_output, indent=2)}"
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
        return json.loads(response.choices[0].message.content)

    async def analyze_pr(self, pr_number: int, repo: str, pr_title: str, diff: str, brd_content: str, branch_name: Optional[str] = None, model: str = None) -> PRSummary:
        """Perform Map-Reduce PR analysis with chunking and a critic loop."""
        target_model = model or self.model
        logger.info(f"Analyzing PR #{pr_number} on {repo} using model {target_model}")
        start_time = time.time()
        input_hash = hashlib.sha256((diff + brd_content).encode()).hexdigest()

        # Map phase: chunk diff and analyze each chunk concurrently
        chunks = self._chunk_diff(diff)
        # Create coroutine tasks for each chunk
        tasks = [self._analyze_chunk(chunk, brd_content, target_model) for chunk in chunks]
        map_results = await asyncio.gather(*tasks)

        # Reduce phase: aggregate results
        combined: Dict[str, Any] = {"summary": "", "changes": [], "workflow_impact": {}, "confidence_score": 1.0}
        for part in map_results:
            # Append summaries
            if part.get("summary"):
                combined["summary"] += part["summary"] + "\n"
            # Merge changes
            combined["changes"].extend(part.get("changes", []))
            # Merge workflow impact (simple union, keep first non-empty)
            if not combined["workflow_impact"] and part.get("workflow_impact"):
                combined["workflow_impact"] = part["workflow_impact"]
        # Average confidence scores if multiple parts
        scores = [p.get("confidence_score", 0) for p in map_results if isinstance(p.get("confidence_score"), (int, float))]
        if scores:
            combined["confidence_score"] = round(sum(scores) / len(scores), 2)

        # Critic loop to ensure no hallucinations
        critic_output = await self._critic_review(combined, diff, target_model)
        actual_files = self._parse_diff_files(diff)
        validated_data = self.cross_validate_output(critic_output, actual_files)

        latency_ms = (time.time() - start_time) * 1000
        tokens = 0  # Token counting would require aggregating from all calls; omitted for brevity
        await self._log_audit(pr_number, input_hash, validated_data, tokens, latency_ms, target_model)

        # Map to schemas
        changes = [
            ChangeItem(
                file=c.get("file", ""),
                line_range=c.get("line_range", ""),
                change_type=ChangeType(c.get("change_type", "modified").lower()),
                description=c.get("description", ""),
                confidence=float(c.get("confidence", 1.0)),
            )
            for c in validated_data.get("changes", [])
        ]
        wf_data = validated_data.get("workflow_impact", {})
        workflow_impact = WorkflowImpact(
            has_impact=bool(wf_data.get("has_impact", False)),
            severity=Severity(wf_data.get("severity", "none").lower()),
            impact_description=wf_data.get("impact_description", ""),
            affected_workflows=wf_data.get("affected_workflows", []),
            before_state=wf_data.get("before_state", ""),
            after_state=wf_data.get("after_state", ""),
        )
        return PRSummary(
            pr_number=pr_number,
            repo=repo,
            branch=branch_name,
            title=pr_title,
            summary=validated_data.get("summary", "").strip(),
            changes=changes,
            workflow_impact=workflow_impact,
            confidence_score=float(validated_data.get("confidence_score", 1.0)),
            analyzed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        )
