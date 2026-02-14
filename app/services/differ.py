"""Diff computation service — clause-level parsing and HTML diff generation.

Improvements over the basic version:
  - Extended heading detection: dotted numbers (1.1, 1.1.1), lettered sub-
    sections (a), (b), Roman numerals (i, ii, iii), definition patterns
    ("Term" means...), and bold/emphasis markdown.
  - Fuzzy matching via SequenceMatcher (threshold 0.6) so renamed or
    reordered sections are detected as modifications, not remove+add.
  - Per-clause significance scoring based on privacy-sensitive keywords.
"""

import difflib
import json
import re
import html
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict, field


# ---------------------------------------------------------------------------
# Significance scoring — keywords that make a clause more important
# ---------------------------------------------------------------------------

SIGNIFICANCE_KEYWORDS: Dict[str, float] = {
    # High significance (0.3+ each)
    "sell": 0.35,
    "selling": 0.35,
    "sold": 0.35,
    "third party": 0.30,
    "third-party": 0.30,
    "third parties": 0.30,
    "arbitration": 0.35,
    "class action": 0.30,
    "waive": 0.30,
    "waiver": 0.30,
    "ai training": 0.35,
    "train our models": 0.35,
    "machine learning": 0.25,
    "law enforcement": 0.30,
    "government": 0.25,
    "subpoena": 0.25,
    # Medium significance (0.15-0.25 each)
    "opt-out": 0.25,
    "opt out": 0.25,
    "consent": 0.20,
    "withdraw consent": 0.25,
    "data sharing": 0.20,
    "share your": 0.20,
    "retention": 0.20,
    "retain": 0.15,
    "delete": 0.15,
    "deletion": 0.15,
    "advertising": 0.20,
    "profiling": 0.25,
    "automated decision": 0.25,
    "biometric": 0.25,
    "geolocation": 0.20,
    "tracking": 0.20,
    "cookie": 0.15,
    "transfer": 0.15,
    "cross-border": 0.20,
    "encrypt": 0.15,
    "security": 0.15,
    "breach": 0.25,
    "children": 0.20,
    "minor": 0.20,
    "sensitive": 0.20,
}


def _compute_significance(text: str) -> float:
    """Compute a significance score (0.0–1.0) for a clause based on keyword matches."""
    if not text:
        return 0.0
    lower = text.lower()
    score = 0.0
    for keyword, weight in SIGNIFICANCE_KEYWORDS.items():
        if keyword in lower:
            score += weight
    return min(1.0, round(score, 2))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ClauseChange:
    """Represents a single clause-level change."""
    section: str
    old_text: str
    new_text: str
    change_type: str  # "added" | "removed" | "modified"
    significance_score: float = 0.0


# ---------------------------------------------------------------------------
# Heading detection — extended patterns
# ---------------------------------------------------------------------------

# Precompiled regex for heading patterns
_RE_MARKDOWN_HEADING = re.compile(r'^#{1,6}\s+')
_RE_NUMBERED = re.compile(r'^\d+\.\s+[A-Z]')
_RE_DOTTED_NUMBERED = re.compile(r'^\d+(\.\d+)+\.?\s+\S')
_RE_LETTERED = re.compile(r'^\([a-z]\)\s+\S', re.IGNORECASE)
_RE_ROMAN = re.compile(r'^\((i{1,3}|iv|v|vi{0,3}|ix|x)\)\s+\S', re.IGNORECASE)
_RE_DEFINITION = re.compile(r'^["\u201c].+?["\u201d]\s+means\b', re.IGNORECASE)
_RE_BOLD_EMPHASIS = re.compile(r'^(\*\*|__).+?(\*\*|__)\s*$')


def _detect_heading(line: str) -> Optional[str]:
    """Detect if a line is a heading.  Returns the cleaned heading text or None."""
    stripped = line.strip()
    if not stripped:
        return None

    # 1. Markdown headings: # Title, ## Title, etc.
    if _RE_MARKDOWN_HEADING.match(stripped):
        return stripped.lstrip('#').strip()

    # 2. ALL-CAPS short lines (>3 chars, ≤100 chars, ≤10 words)
    if (
        len(stripped) > 3
        and len(stripped) < 100
        and stripped.isupper()
        and len(stripped.split()) <= 10
    ):
        return stripped

    # 3. Simple numbered: "1. Title"
    if _RE_NUMBERED.match(stripped):
        return stripped

    # 4. Dotted numbered: "1.1 Title", "1.1.1 Title"
    if _RE_DOTTED_NUMBERED.match(stripped):
        return stripped

    # 5. Lettered subsections: "(a) Title"
    if _RE_LETTERED.match(stripped) and len(stripped) < 150:
        return stripped

    # 6. Roman numeral subsections: "(i) Title", "(ii) Title"
    if _RE_ROMAN.match(stripped) and len(stripped) < 150:
        return stripped

    # 7. Definition-style: "Term" means...
    if _RE_DEFINITION.match(stripped):
        # Use just the defined term as heading
        match = re.match(r'^["\u201c](.+?)["\u201d]', stripped)
        if match:
            return f'Definition: {match.group(1)}'

    # 8. Bold/emphasis markdown as heading: **Heading** at line start
    if _RE_BOLD_EMPHASIS.match(stripped):
        cleaned = stripped.strip('*').strip('_').strip()
        if len(cleaned) > 2 and len(cleaned) < 100:
            return cleaned

    return None


# ---------------------------------------------------------------------------
# Clause splitting
# ---------------------------------------------------------------------------

def _sanitize_preview(text: str, max_len: int = 500) -> str:
    """Sanitize text for display in clause previews."""
    text = ''.join(
        c for c in text
        if c.isprintable() or c in ('\n', '\t')
    )
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text)
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len] + '...'
    return text


def _split_into_clauses(text: str) -> List[Dict[str, str]]:
    """Split policy text into structured clauses/sections.

    Returns list of dicts with 'heading' and 'content' keys.
    """
    clauses = []
    current_heading = "Introduction"
    current_lines: List[str] = []

    for line in text.split("\n"):
        heading = _detect_heading(line)

        if heading and current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                clauses.append({"heading": current_heading, "content": content})
            current_heading = heading
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last section
    content = "\n".join(current_lines).strip()
    if content:
        clauses.append({"heading": current_heading, "content": content})

    return clauses


# ---------------------------------------------------------------------------
# Fuzzy matching for renamed / reordered sections
# ---------------------------------------------------------------------------

FUZZY_THRESHOLD = 0.6  # SequenceMatcher ratio threshold


def _find_best_match(
    heading: str,
    content: str,
    candidates: Dict[str, str],
) -> Optional[str]:
    """Find the best matching heading from candidates using fuzzy matching.

    Considers both heading similarity and content similarity.
    Returns the matched heading or None if no match exceeds the threshold.
    """
    best_heading = None
    best_score = 0.0

    for cand_heading, cand_content in candidates.items():
        # Heading similarity (weighted 40%)
        heading_sim = difflib.SequenceMatcher(
            None, heading.lower(), cand_heading.lower()
        ).ratio()

        # Content similarity (weighted 60%)
        content_sim = difflib.SequenceMatcher(
            None, content[:2000], cand_content[:2000]
        ).ratio()

        combined = 0.4 * heading_sim + 0.6 * content_sim

        if combined > best_score:
            best_score = combined
            best_heading = cand_heading

    if best_score >= FUZZY_THRESHOLD:
        return best_heading
    return None


# ---------------------------------------------------------------------------
# Core clause-change computation
# ---------------------------------------------------------------------------

def compute_clause_changes(
    old_text: str, new_text: str,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Compare two policy texts at the clause level with fuzzy matching.

    Returns (added, removed, modified) clause lists, each item including
    a significance_score field.
    """
    old_clauses = {c["heading"]: c["content"] for c in _split_into_clauses(old_text)}
    new_clauses = {c["heading"]: c["content"] for c in _split_into_clauses(new_text)}

    added = []
    removed = []
    modified = []

    matched_old: set = set()  # old headings that have been matched
    matched_new: set = set()  # new headings that have been matched

    # Pass 1: Exact heading matches
    for heading in list(old_clauses.keys()):
        if heading in new_clauses:
            matched_old.add(heading)
            matched_new.add(heading)
            if old_clauses[heading] != new_clauses[heading]:
                sig = max(
                    _compute_significance(old_clauses[heading]),
                    _compute_significance(new_clauses[heading]),
                )
                modified.append(ClauseChange(
                    section=heading,
                    old_text=_sanitize_preview(old_clauses[heading]),
                    new_text=_sanitize_preview(new_clauses[heading]),
                    change_type="modified",
                    significance_score=sig,
                ))

    # Pass 2: Fuzzy matching for unmatched sections
    unmatched_old = {h: c for h, c in old_clauses.items() if h not in matched_old}
    unmatched_new = {h: c for h, c in new_clauses.items() if h not in matched_new}

    # Try to match each unmatched old clause to an unmatched new clause
    for old_heading, old_content in list(unmatched_old.items()):
        if not unmatched_new:
            break
        best = _find_best_match(old_heading, old_content, unmatched_new)
        if best:
            sig = max(
                _compute_significance(old_content),
                _compute_significance(unmatched_new[best]),
            )
            section_label = (
                f"{old_heading} → {best}" if old_heading != best else old_heading
            )
            modified.append(ClauseChange(
                section=section_label,
                old_text=_sanitize_preview(old_content),
                new_text=_sanitize_preview(unmatched_new[best]),
                change_type="modified",
                significance_score=sig,
            ))
            matched_old.add(old_heading)
            matched_new.add(best)
            del unmatched_new[best]
            del unmatched_old[old_heading]

    # Pass 3: Remaining unmatched = pure additions and removals
    for heading, content in unmatched_old.items():
        if heading not in matched_old:
            removed.append(ClauseChange(
                section=heading,
                old_text=_sanitize_preview(content),
                new_text="",
                change_type="removed",
                significance_score=_compute_significance(content),
            ))

    for heading, content in unmatched_new.items():
        if heading not in matched_new:
            added.append(ClauseChange(
                section=heading,
                old_text="",
                new_text=_sanitize_preview(content),
                change_type="added",
                significance_score=_compute_significance(content),
            ))

    # Sort by significance (highest first)
    added.sort(key=lambda c: c.significance_score, reverse=True)
    removed.sort(key=lambda c: c.significance_score, reverse=True)
    modified.sort(key=lambda c: c.significance_score, reverse=True)

    return (
        [asdict(c) for c in added],
        [asdict(c) for c in removed],
        [asdict(c) for c in modified],
    )


# ---------------------------------------------------------------------------
# Unified diff
# ---------------------------------------------------------------------------

def compute_unified_diff(old_text: str, new_text: str) -> str:
    """Compute a unified diff between two texts."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="Previous Version",
        tofile="Current Version",
        lineterm="",
    )
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# HTML side-by-side diff (dark-theme custom table)
# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    """HTML-escape text for safe embedding."""
    return html.escape(text, quote=True)


def compute_html_diff(old_text: str, new_text: str) -> str:
    """Generate a custom dark-theme side-by-side HTML diff."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    opcodes = sm.get_opcodes()

    rows = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
            lines = list(zip(old_lines[i1:i2], new_lines[j1:j2]))
            if len(lines) > 6:
                for idx, (ol, nl) in enumerate(lines[:3]):
                    rows.append(_diff_row(i1 + idx + 1, _escape(ol), j1 + idx + 1, _escape(nl), 'ctx'))
                rows.append(_diff_separator(f'... {len(lines) - 6} unchanged lines ...'))
                for idx, (ol, nl) in enumerate(lines[-3:]):
                    real_i = i2 - 3 + idx
                    real_j = j2 - 3 + idx
                    rows.append(_diff_row(real_i + 1, _escape(ol), real_j + 1, _escape(nl), 'ctx'))
            else:
                for idx, (ol, nl) in enumerate(lines):
                    rows.append(_diff_row(i1 + idx + 1, _escape(ol), j1 + idx + 1, _escape(nl), 'ctx'))

        elif tag == 'replace':
            max_len = max(i2 - i1, j2 - j1)
            for k in range(max_len):
                old_idx = i1 + k if k < (i2 - i1) else None
                new_idx = j1 + k if k < (j2 - j1) else None
                old_line = _escape(old_lines[old_idx]) if old_idx is not None else ''
                new_line = _escape(new_lines[new_idx]) if new_idx is not None else ''
                old_num = (old_idx + 1) if old_idx is not None else ''
                new_num = (new_idx + 1) if new_idx is not None else ''
                old_cls = 'del' if old_idx is not None else 'empty'
                new_cls = 'add' if new_idx is not None else 'empty'
                rows.append(_diff_row_split(old_num, old_line, old_cls, new_num, new_line, new_cls))

        elif tag == 'delete':
            for k in range(i1, i2):
                rows.append(_diff_row_split(k + 1, _escape(old_lines[k]), 'del', '', '', 'empty'))

        elif tag == 'insert':
            for k in range(j1, j2):
                rows.append(_diff_row_split('', '', 'empty', k + 1, _escape(new_lines[k]), 'add'))

    table_html = '\n'.join(rows)

    return f'''<table class="policydiff-table">
<thead>
<tr>
<th class="ln-col"></th>
<th class="content-col">Previous Version</th>
<th class="ln-col"></th>
<th class="content-col">Current Version</th>
</tr>
</thead>
<tbody>
{table_html}
</tbody>
</table>'''


def _diff_row(old_num, old_text, new_num, new_text, cls):
    return f'''<tr class="diff-{cls}">
<td class="ln">{old_num}</td>
<td class="code">{old_text}</td>
<td class="ln">{new_num}</td>
<td class="code">{new_text}</td>
</tr>'''


def _diff_row_split(old_num, old_text, old_cls, new_num, new_text, new_cls):
    return f'''<tr>
<td class="ln diff-{old_cls}-ln">{old_num}</td>
<td class="code diff-{old_cls}">{old_text}</td>
<td class="ln diff-{new_cls}-ln">{new_num}</td>
<td class="code diff-{new_cls}">{new_text}</td>
</tr>'''


def _diff_separator(message):
    return f'''<tr class="diff-sep">
<td colspan="4">{_escape(message)}</td>
</tr>'''


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_full_diff(old_text: str, new_text: str) -> Dict:
    """Compute all diff formats for a pair of snapshots.

    Returns a dict with all diff data.
    """
    added, removed, modified = compute_clause_changes(old_text, new_text)

    return {
        "diff_text": compute_unified_diff(old_text, new_text),
        "diff_html": compute_html_diff(old_text, new_text),
        "clauses_added": json.dumps(added),
        "clauses_removed": json.dumps(removed),
        "clauses_modified": json.dumps(modified),
        "change_summary": {
            "added_count": len(added),
            "removed_count": len(removed),
            "modified_count": len(modified),
        },
    }
