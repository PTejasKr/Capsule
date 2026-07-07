import json
import logging
import hashlib
import time
from typing import List, Dict, Any, Tuple, Optional
import asyncio
from backend.config import settings
from backend.models.schemas import PRSummary, ChangeItem, WorkflowImpact, ChangeType, Severity
from backend.database import insert
from backend.services.routing_service import router_service

logger = logging.getLogger("capsule.ai_engine")

class AIEngine:
    def __init__(self):
        # We store a mock client for testing compatibility (e.g. DummyClient)
        self.client = None

    async def _chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        response_format: Optional[Dict[str, str]] = None,
        max_tokens: int = 2000,
        specific_provider: Optional[str] = None
    ) -> str:
        if self.client:
            response = await self.client.chat.completions.create(
                model="dummy",
                messages=messages,
                temperature=temperature,
                response_format=response_format,
                max_tokens=max_tokens
            )
            if hasattr(response.choices[0].message, "content"):
                return response.choices[0].message.content
            return response.choices[0].message["content"]
        return await router_service.chat_completion(
            messages=messages,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
            specific_provider=specific_provider
        )

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
        return f"""You are Capsule, an elite code change analysis AI. Your job is to analyze code diffs against a Business Requirement Document (BRD) and output a structured analysis.

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
  "brd_comparison": "Detailed comparison and direct analysis of how the changes map to the initial BRD.",
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

    async def _analyze_chunk(self, chunk: str, brd_content: str, model: str = None) -> Dict[str, Any]:
        """Analyze a single diff chunk and return the raw JSON output from the LLM."""
        system_prompt = self._build_system_prompt(brd_content)
        user_prompt = f"Analyze the following unified diff chunk:\n\n{chunk}"
        
        content = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=2000
        )
        return json.loads(content)

    async def _reduce_overall(self, combined: Dict[str, Any], brd_content: str, model: str = None) -> Dict[str, Any]:
        """Holistic reduce pass: re-send the merged per-chunk results to the LLM so
        cross-file / cross-chunk relationships (renames, shared helpers, workflow
        transitions) are captured in the final summary instead of being lost per chunk."""
        system_prompt = (
            "You are a senior engineer performing a holistic review of a Pull Request. "
            "You are given the merged analysis produced from individual diff chunks. "
            "Your job is to produce a coherent, de-duplicated overall analysis that "
            "captures relationships and impacts that span multiple files.\n\n"
            "=== CRITICAL ANTI-HALLUCINATION INSTRUCTIONS ===\n"
            "1. ONLY keep file paths, line numbers, or code changes that already appear "
            "in the provided merged analysis. NEVER invent new files or changes.\n"
            "2. Consolidate duplicate changes that reference the same file or logic.\n"
            "3. Write a single high-level summary that reflects the PR as a whole, "
            "including cross-file workflow impact.\n\n"
            "=== BUSINESS REQUIREMENT DOCUMENT (BRD) ===\n"
            f"{brd_content}\n"
            "=== END OF BRD ===\n\n"
            "You MUST output your response as a valid JSON object matching this schema:\n"
            "{\n"
            '  "summary": "High-level summary of the overall changes and workflow impact",\n'
            '  "changes": [ { "file": "path/to/file.py", "line_range": "12-25", "change_type": "added|modified|deleted", "description": "...", "confidence": 0.95 } ],\n'
            '  "workflow_impact": { "has_impact": true|false, "severity": "none|minor|major", "impact_description": "...", "affected_workflows": ["..."], "before_state": "...", "after_state": "..." },\n'
            '  "confidence_score": 0.98\n'
            "}\n"
        )
        user_prompt = f"Merged per-chunk analysis:\n{json.dumps(combined, indent=2)}"

        content = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=2000,
            specific_provider=model,
        )
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

    async def _critic_review(self, combined_output: Dict[str, Any], diff: str, model: str = None) -> Dict[str, Any]:
        """Run a critic LLM pass to verify combined output against the raw diff, removing hallucinatory entries."""
        system_prompt = "You are a critic reviewing AI analysis of a PR. Ensure that every file listed in the JSON output actually exists in the provided diff. Remove any entries that are not present. Return a cleaned JSON matching the original schema."
        user_prompt = f"Diff:\n{diff}\n\nCombined Output:\n{json.dumps(combined_output, indent=2)}"
        
        content = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=2000
        )
        return json.loads(content)

    async def compare_summaries(self, original_summary: str, edited_summary: str) -> Dict[str, Any]:
        """
        Uses OpenRouter (free tier) to compare the initial AI summary with the Admin's edited summary.
        """
        system_prompt = "You are a senior tech lead. Compare the original PR summary generated by the AI with the updated summary edited by an Admin. Highlight what was changed, added, or removed. Format your response in JSON with fields: 'differences_detected', 'recommendation', 'reasoning'."
        user_prompt = f"Original AI Summary:\n{original_summary}\n\nAdmin Edited Summary:\n{edited_summary}\n\nPlease analyze the differences."
        
        content = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1000,
            specific_provider="openrouter"
        )
        return json.loads(content)

    async def analyze_pr(self, pr_number: int, repo: str, pr_title: str, diff: str, brd_content: str, branch_name: Optional[str] = None, model: str = None) -> PRSummary:
        """Perform Map-Reduce PR analysis with chunking and a critic loop."""
        target_model = model or "multi-provider"
        logger.info(f"Analyzing PR #{pr_number} on {repo} using adaptive router")
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

        # Holistic reduce pass: capture cross-chunk relationships lost during map phase.
        # Skipped when GLOBAL_REDUCE_ENABLED is false (falls back to merged chunks).
        if getattr(settings, "GLOBAL_REDUCE_ENABLED", True):
            try:
                combined = await self._reduce_overall(combined, brd_content, target_model)
            except Exception as e:
                logger.warning(f"Global reduce pass failed, falling back to merged chunks: {e}")

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

    async def _architect_mode(self, summary: str, files_metadata: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Architect Mode: Analyzes the PR summary and file diffs to generate a structured execution plan.
        """
        logger.info("[Capsule] Orchestrator invoking Architect Mode")
        system_prompt = (
            "You are the Architect Mode agent in the Capsule orchestration loop. "
            "Your job is to analyze the PR summary and the provided file contents, and create a structured execution plan. "
            "You must map out what needs to change in which files, identify dependencies, and detail the specific logic to be altered. "
            "Output your response as a valid JSON object with keys: 'execution_plan' (a step-by-step list of instructions), 'target_files' (list of file paths to modify), and 'architectural_notes'."
        )
        
        user_prompt = f"PR Analysis Summary with issues to fix:\n{summary}\n\n"
        for f in files_metadata:
            patch = f.get("patch", "")
            if patch:
                user_prompt += f"File: {f['filename']}\nCurrent Patch Diff:\n{patch}\n\n"
                
        content = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=2000
        )
        return json.loads(content)

    async def _coder_mode(self, architect_plan: Dict[str, Any], files_metadata: List[Dict[str, Any]], previous_feedback: str = "") -> Dict[str, Any]:
        """
        Coder Mode: Implements the code changes based on the Architect's plan and any Debugger feedback.
        """
        logger.info("[Capsule] Orchestrator invoking Coder Mode")
        system_prompt = (
            "You are the Coder Mode agent in the Capsule orchestration loop. "
            "Your job is to write the actual code modifications based on the Architect's execution plan. "
            "Output a JSON object with a 'files' array containing the full 'path' and 'new_content' (the complete, fixed file content), and a 'message' string for the commit."
        )
        
        user_prompt = f"Architect Execution Plan:\n{json.dumps(architect_plan, indent=2)}\n\n"
        
        if previous_feedback:
            user_prompt += f"CRITICAL DEBUGGER FEEDBACK (Fix these issues in your new code!):\n{previous_feedback}\n\n"
            
        for f in files_metadata:
            patch = f.get("patch", "")
            if patch:
                user_prompt += f"File: {f['filename']}\nCurrent Patch Diff:\n{patch}\n\n"
                
        content = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=4000
        )
        return json.loads(content)

    async def _debugger_mode(self, generated_code: Dict[str, Any], architect_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Debugger Mode: Statically verifies the generated code against the Architect's plan.
        """
        logger.info("[Capsule] Orchestrator invoking Debugger Mode")
        system_prompt = (
            "You are the Debugger Mode agent in the Capsule orchestration loop. "
            "Your job is to statically verify the code generated by the Coder Mode agent against the Architect's execution plan. "
            "Ensure the Coder followed all instructions, didn't introduce syntax errors, and solved the original issue. "
            "Output a JSON object with keys: 'is_valid' (boolean), 'feedback' (string detailing any issues found, or empty if valid)."
        )
        
        user_prompt = f"Architect Execution Plan:\n{json.dumps(architect_plan, indent=2)}\n\n"
        user_prompt += f"Generated Code from Coder Mode:\n{json.dumps(generated_code, indent=2)}\n\n"
        
        content = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=2000
        )
        return json.loads(content)

    async def auto_repair_code(self, summary: str, files_metadata: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        The Agentic Execution Loop (Capsule Architecture).
        Takes the AI analysis summary and the PR diff files, uses a multi-agent orchestration loop
        to plan, code, and verify the replacement contents for the files that need fixing.
        """
        logger.info("[Capsule] Starting Agentic Execution Loop for Auto-Repair")
        
        # 1. Context Gathering & Task Planning (Architect Mode)
        architect_plan = await self._architect_mode(summary, files_metadata)
        
        max_retries = 2
        attempt = 0
        feedback = ""
        final_code = None
        
        while attempt <= max_retries:
            # 2. Code Generation & Implementation (Coder Mode)
            generated_code = await self._coder_mode(architect_plan, files_metadata, feedback)
            
            # 3. Automated Verification & Failure Recovery (Debugger Mode)
            verification = await self._debugger_mode(generated_code, architect_plan)
            
            if verification.get("is_valid", False):
                logger.info("[Capsule] Debugger Mode verified code successfully.")
                final_code = generated_code
                break
            else:
                feedback = verification.get("feedback", "Unknown error in code generation.")
                logger.warning(f"[Capsule] Debugger Mode found issues: {feedback}. Retrying... ({attempt+1}/{max_retries})")
                attempt += 1
                
        if not final_code:
            logger.error("[Capsule] Execution loop exhausted retries. Returning last generated code with warnings.")
            final_code = generated_code # Return the last attempt even if flawed
            final_code["message"] = "[WARNING: Verification Failed] " + final_code.get("message", "Auto-Repair")
            
        return final_code
