"""LLM-powered analysis service for policy diffs.

Improvements:
  - Retry logic with exponential backoff (3 attempts) for transient OpenAI failures
  - Increased truncation limits for better analysis of large policy changes
"""

import asyncio
import json
import logging
import random
from typing import Dict, Optional

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Maximum retries for LLM API calls
LLM_MAX_RETRIES = 3

SYSTEM_PROMPT = """You are PolicyDiff, an expert analyst specializing in privacy policies and terms of service agreements. Your job is to analyze changes between two versions of a policy document and explain what changed in plain language that a non-lawyer can understand.

You must respond with valid JSON matching this exact schema:
{
  "summary": "A 2-4 sentence plain-language summary of what changed and why it matters to the user.",
  "severity": "informational | concerning | action-needed",
  "severity_score": 0.0 to 1.0,
  "key_changes": [
    "First key change described in plain language",
    "Second key change described in plain language"
  ],
  "recommendation": "What the user should do about these changes (1-2 sentences)."
}

Severity guide:
- "informational" (0.0-0.3): Minor wording changes, formatting, clarifications that don't affect user rights
- "concerning" (0.3-0.7): Changes that expand data collection, modify user rights, alter sharing practices, or weaken protections
- "action-needed" (0.7-1.0): Major changes requiring user action — new data selling, removed opt-out rights, mandatory arbitration, significant privacy erosion

Always be specific about WHAT changed and WHY it matters. Avoid legal jargon. Write as if explaining to a friend."""


ANALYSIS_PROMPT_TEMPLATE = """Analyze the following changes to the {policy_type} for {company} ({policy_name}).

## Clauses Added ({added_count}):
{clauses_added}

## Clauses Removed ({removed_count}):
{clauses_removed}

## Clauses Modified ({modified_count}):
{clauses_modified}

## Raw Unified Diff (excerpt):
{diff_excerpt}

Provide your analysis as JSON."""


def _truncate(text: str, max_len: int = 5000) -> str:
    """Truncate text to fit within token limits."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... [truncated]"


async def analyze_diff(
    policy_name: str,
    company: str,
    policy_type: str,
    diff_text: str,
    clauses_added: str,
    clauses_removed: str,
    clauses_modified: str,
) -> Dict:
    """
    Use an LLM to analyze a policy diff and produce a plain-language summary.

    Retries up to 3 times with exponential backoff on transient failures.
    Returns dict with: summary, severity, severity_score, key_changes, recommendation
    """
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key configured — returning default analysis")
        return _fallback_analysis(clauses_added, clauses_removed, clauses_modified)

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    added = json.loads(clauses_added) if clauses_added else []
    removed = json.loads(clauses_removed) if clauses_removed else []
    modified = json.loads(clauses_modified) if clauses_modified else []

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        policy_type=policy_type.replace("_", " ").title(),
        company=company,
        policy_name=policy_name,
        added_count=len(added),
        removed_count=len(removed),
        modified_count=len(modified),
        clauses_added=_truncate(json.dumps(added, indent=2)) if added else "None",
        clauses_removed=_truncate(json.dumps(removed, indent=2)) if removed else "None",
        clauses_modified=_truncate(json.dumps(modified, indent=2)) if modified else "None",
        diff_excerpt=_truncate(diff_text, 3000),
    )

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)

            # Validate and normalize
            result["severity"] = result.get("severity", "informational").lower()
            if result["severity"] not in ("informational", "concerning", "action-needed"):
                result["severity"] = "informational"

            result["severity_score"] = max(0.0, min(1.0, float(result.get("severity_score", 0.0))))
            result["key_changes"] = json.dumps(result.get("key_changes", []))

            logger.info(f"LLM analysis complete for {policy_name}: severity={result['severity']}")
            return result

        except Exception as e:
            if attempt < LLM_MAX_RETRIES:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    f"LLM analysis attempt {attempt}/{LLM_MAX_RETRIES} failed for "
                    f"{policy_name}: {e}. Retrying in {wait:.1f}s..."
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    f"LLM analysis failed after {LLM_MAX_RETRIES} attempts for "
                    f"{policy_name}: {e}. Falling back to basic analysis."
                )

    return _fallback_analysis(clauses_added, clauses_removed, clauses_modified)


def _fallback_analysis(clauses_added: str, clauses_removed: str, clauses_modified: str) -> Dict:
    """Generate a basic analysis without LLM when API key is missing or call fails."""
    added = json.loads(clauses_added) if clauses_added else []
    removed = json.loads(clauses_removed) if clauses_removed else []
    modified = json.loads(clauses_modified) if clauses_modified else []

    total = len(added) + len(removed) + len(modified)

    if total == 0:
        severity = "informational"
        score = 0.1
    elif len(removed) > 0:
        severity = "concerning"
        score = 0.5
    elif total > 3:
        severity = "concerning"
        score = 0.4
    else:
        severity = "informational"
        score = 0.2

    changes = []
    for c in added:
        changes.append(f"New section added: {c.get('section', 'Unknown')}")
    for c in removed:
        changes.append(f"Section removed: {c.get('section', 'Unknown')}")
    for c in modified:
        changes.append(f"Section modified: {c.get('section', 'Unknown')}")

    return {
        "summary": f"Detected {total} changes: {len(added)} sections added, {len(removed)} removed, {len(modified)} modified. Configure an OpenAI API key for detailed plain-language analysis.",
        "severity": severity,
        "severity_score": score,
        "key_changes": json.dumps(changes[:10]),
        "recommendation": "Review the changes in the diff view to understand what was modified.",
    }
