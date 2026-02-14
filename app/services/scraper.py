"""Web scraping service for policy pages.

Strategy:
  1. httpx with rotating user-agents + exponential backoff retries (3 attempts)
  2. If httpx fails or content is too short (<200 chars), fall back to Playwright
     headless Chromium with cookie-banner dismissal.

Link awareness (Option C):
  - Preserves hyperlinks in extracted text as markdown [text](url)
  - Discovers internal policy-related links on the page and returns them
    as metadata so the user can see what subpages exist.
"""

import asyncio
import hashlib
import logging
import random
import re
import unicodedata
from typing import Tuple, Optional, List
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import html2text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User-Agent pool — rotated randomly per request
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

MIN_CONTENT_LENGTH = 200

REMOVE_TAGS = [
    "script", "style", "nav", "header", "footer", "aside",
    "noscript", "iframe", "svg", "canvas", "video", "audio",
    "picture", "source", "form", "button", "input", "select", "textarea",
]

# CSS classes whose elements should be removed (screen-reader-only text, etc.)
SR_ONLY_CLASSES = [
    "sr-only", "visually-hidden", "screen-reader-text",
    "screenreader", "a11y-hidden", "clip-hidden",
]

# Invisible Unicode characters that should be stripped from extracted text
INVISIBLE_CHARS = re.compile(
    '['
    '\u2060'   # Word joiner
    '\u200b'   # Zero-width space
    '\u200c'   # Zero-width non-joiner
    '\u200d'   # Zero-width joiner
    '\ufeff'   # Zero-width no-break space / BOM
    '\u00ad'   # Soft hyphen
    '\u2063'   # Invisible separator
    '\u2062'   # Invisible times
    ']'
)

# Regex for collapsing 3+ consecutive newlines (used in _clean_text)
_RE_MULTI_NEWLINE = re.compile(r'\n{3,}')

CONTENT_SELECTORS = [
    "article", "[role='main']", "main",
    ".policy-content", ".privacy-policy", ".terms-of-service", ".legal-content",
    "#content", "#main-content", ".content",
    ".entry-content", ".post-content", ".page-content", ".body-content",
]

COOKIE_BANNER_SELECTORS = [
    "#onetrust-accept-btn-handler", "#accept-cookies", ".cookie-accept",
    "[data-testid='cookie-accept']", ".cc-accept", ".cc-btn.cc-allow",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#gdpr-cookie-accept", ".js-cookie-consent-agree",
    "[data-cookiebanner='accept_button']",
]

COOKIE_BUTTON_TEXTS = [
    "Accept", "Accept all", "Accept All", "I agree",
    "Got it", "OK", "Allow all", "Allow All",
]

# Path patterns that suggest a page is policy/legal content
POLICY_PATH_PATTERNS = re.compile(
    r"/(privacy|policy|policies|legal|terms|tos|gdpr|ccpa|cookie|data-protection|"
    r"acceptable-use|community-guidelines|copyright|dmca|eula|sla|dpa|"
    r"data-processing|subprocessors|security|compliance)", re.IGNORECASE
)


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }


# ---------------------------------------------------------------------------
# HTML preprocessing — runs before html2text conversion
# ---------------------------------------------------------------------------

def _strip_sr_only(soup: BeautifulSoup) -> None:
    """Remove screen-reader-only and decorative aria-hidden elements."""
    for cls in SR_ONLY_CLASSES:
        for elem in soup.select(f".{cls}"):
            elem.decompose()
    for elem in soup.find_all(attrs={"aria-hidden": "true"}):
        if elem.name in ("span", "i", "svg", "img") or len(elem.get_text(strip=True)) < 3:
            elem.decompose()


def _resolve_relative_links(soup: BeautifulSoup, url: str) -> None:
    """Convert relative hrefs to absolute URLs."""
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith("/") or (
            not href.startswith(("http", "#", "mailto:"))
        ):
            a_tag["href"] = urljoin(url, href)


def _strip_invisible_unicode(soup: BeautifulSoup) -> None:
    """Remove invisible Unicode characters from all text nodes."""
    for text_node in soup.find_all(string=True):
        original = str(text_node)
        cleaned = INVISIBLE_CHARS.sub("", original)
        if cleaned != original:
            text_node.replace_with(cleaned)


def _remove_empty_headings(soup: BeautifulSoup) -> None:
    """Remove headings with no visible text content."""
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if not h.get_text(strip=True):
            h.decompose()


def _promote_table_headers(soup: BeautifulSoup) -> None:
    """Promote first-row <td> cells styled as bold to <th> for proper markdown."""
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if not first_row:
            continue
        cells = first_row.find_all("td")
        if not cells:
            continue
        all_bold = all(
            any(kw in " ".join(cell.get("class", [])) for kw in ("font-semibold", "font-bold"))
            for cell in cells
        )
        if all_bold:
            for cell in cells:
                cell.name = "th"


def _flatten_complex_tables(soup: BeautifulSoup) -> None:
    """Convert tables with rich cell content into structured sections.

    Markdown tables only support single-line cell content. When a table cell
    contains block elements (lists, multiple paragraphs), we replace the
    entire table with a column-per-section layout that html2text can handle.
    This is generalised: any table with block content in its cells triggers
    the conversion.
    """
    from bs4 import Tag

    for table in soup.find_all("table"):
        # Check if any data cell contains block elements
        data_rows = table.find_all("tr")[1:]  # skip header row
        has_block = any(
            cell.find(["ul", "ol", "p", "blockquote", "pre"])
            for row in data_rows
            for cell in row.find_all(["td", "th"])
        )
        if not has_block:
            continue  # simple table — leave for normal markdown conversion

        # Extract header labels
        header_row = table.find("tr")
        headers = []
        if header_row:
            for cell in header_row.find_all(["th", "td"]):
                headers.append(cell.get_text(strip=True))

        # Build replacement: one section per column, each data row stacked
        replacement = Tag(name="div")

        for row in data_rows:
            cells = row.find_all(["td", "th"])
            for ci, cell in enumerate(cells):
                header_label = headers[ci] if ci < len(headers) else f"Column {ci+1}"
                # Create a subsection heading
                heading = Tag(name="h4")
                heading.string = header_label
                replacement.append(heading)
                # Move cell contents into the replacement div
                # list() is required: extract() mutates the tree during iteration
                for child in list(cell.children):
                    replacement.append(child.extract())

        table.replace_with(replacement)


def _preprocess_html(soup: BeautifulSoup, url: str = "") -> BeautifulSoup:
    """Pre-process the HTML DOM before markdown conversion.

    Fixes applied (generalised for all policy pages):
      1. Remove screen-reader-only elements (sr-only, visually-hidden, etc.)
      2. Resolve relative links to absolute URLs
      3. Strip invisible Unicode characters from text nodes
      4. Remove empty decorative headings
      5. Ensure table header rows use <th> for proper markdown conversion
      6. Flatten complex tables with block content into structured sections
    """
    _strip_sr_only(soup)
    if url:
        _resolve_relative_links(soup, url)
    _strip_invisible_unicode(soup)
    _remove_empty_headings(soup)
    _promote_table_headers(soup)
    _flatten_complex_tables(soup)
    return soup


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Normalize whitespace, strip non-printable chars, and clean extracted text."""
    # Strip invisible Unicode characters first
    text = INVISIBLE_CHARS.sub("", text)

    cleaned = []
    for char in text:
        if char in ('\n', '\t'):
            cleaned.append(char)
        elif unicodedata.category(char).startswith('C'):
            cleaned.append(' ')
        else:
            cleaned.append(char)
    text = ''.join(cleaned)

    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append("")
            continue
        if len(stripped) < 15:
            clean_lines.append(stripped)
            continue
        printable_ascii = sum(
            1 for c in stripped
            if (c.isascii() and c.isprintable()) or c in ('\n', '\t')
        )
        ratio = printable_ascii / len(stripped) if stripped else 1.0
        if ratio < 0.5:
            continue
        has_long_blob = any(
            len(word) > 100 and 'http' not in word
            for word in stripped.split()
        )
        if has_long_blob:
            continue
        clean_lines.append(stripped)

    text = "\n".join(clean_lines)
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)
    # Only strip very short/empty markdown links, keep real ones
    text = re.sub(r'\[]\([^)]*\)', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # Remove backslash-escaping of periods in numbered headings (e.g. "## 1\. Title")
    text = re.sub(r'^(#{1,6}\s+\d+)\\(\.)' , r'\1\2', text, flags=re.MULTILINE)
    # Remove standalone empty headings that may survive preprocessing
    text = re.sub(r'^#{1,6}\s*$', '', text, flags=re.MULTILINE)
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Link discovery — find related policy subpages
# ---------------------------------------------------------------------------

def _discover_policy_links(html: str, base_url: str) -> List[str]:
    """Extract internal links that look like related policy/legal pages.

    Returns a deduplicated list of absolute URLs.
    """
    soup = BeautifulSoup(html, "lxml")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    base_path = parsed_base.path.rstrip("/")

    discovered = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)

        # Must be same domain (or subdomain)
        link_domain = parsed.netloc.lower()
        if not (link_domain == base_domain or link_domain.endswith("." + base_domain)):
            continue

        # Skip the exact same page
        link_path = parsed.path.rstrip("/")
        if link_path == base_path:
            continue

        # Must look like a policy/legal page
        is_subpath = link_path.startswith(base_path + "/") if base_path else False
        matches_pattern = bool(POLICY_PATH_PATTERNS.search(link_path))

        if is_subpath or matches_pattern:
            # Normalize: strip fragment and query
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            clean_url = clean_url.rstrip("/")
            discovered.add(clean_url)

    return sorted(discovered)


# ---------------------------------------------------------------------------
# Content extraction — now preserves links
# ---------------------------------------------------------------------------

def extract_policy_text(html: str, url: str = "") -> str:
    """Extract the main policy text from an HTML string.

    Preserves hyperlinks as markdown [text](url) for context.
    Public so that the Wayback seeder can reuse the same extraction pipeline.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()

    main_content = None
    for selector in CONTENT_SELECTORS:
        found = soup.select_one(selector)
        if found and len(found.get_text(strip=True)) > 200:
            main_content = found
            break

    if main_content is None:
        main_content = soup.find("body") or soup

    # Pre-process HTML before conversion (sr-only removal, link resolution, etc.)
    main_content = _preprocess_html(main_content, url)

    h = html2text.HTML2Text()
    h.ignore_links = False          # CHANGED: preserve links
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0
    h.unicode_snob = False
    h.skip_internal_links = True     # Skip #anchor links
    h.inline_links = True            # [text](url) format
    h.protect_links = False
    h.wrap_links = False
    h.single_line_break = False
    h.base_url = url                 # Helps html2text resolve relative URLs

    text = h.handle(str(main_content))
    return _clean_text(text)


# Keep old name as alias
_extract_policy_text = extract_policy_text


def compute_hash(content: str) -> str:
    """Compute SHA-256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Strategy 1 — httpx with retries & exponential backoff
# ---------------------------------------------------------------------------

async def _scrape_httpx(url: str, timeout: float = 30.0, max_retries: int = 3) -> Optional[str]:
    """Attempt to fetch the page with httpx.  Returns HTML string or None."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        headers = _random_headers()
        try:
            logger.info(
                f"[httpx] attempt {attempt}/{max_retries} for {url} "
                f"(UA: ...{headers['User-Agent'][-30:]})"
            )
            async with httpx.AsyncClient(
                headers=headers, follow_redirects=True, timeout=timeout,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
            logger.info(f"[httpx] success for {url} ({len(response.text)} bytes)")
            return response.text
        except Exception as e:
            last_error = e
            wait = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                f"[httpx] attempt {attempt} failed for {url}: {e}. "
                f"Retrying in {wait:.1f}s..."
            )
            if attempt < max_retries:
                await asyncio.sleep(wait)

    logger.error(f"[httpx] all {max_retries} attempts failed for {url}: {last_error}")
    return None


# ---------------------------------------------------------------------------
# Strategy 2 — Playwright headless Chromium fallback
# ---------------------------------------------------------------------------

async def _scrape_playwright(url: str, timeout_ms: int = 30000) -> Optional[str]:
    """Fallback: fetch page with a real headless browser via Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning(
            "[playwright] playwright not installed — skipping browser fallback. "
            "Install with: pip install playwright && playwright install chromium"
        )
        return None

    logger.info(f"[playwright] launching headless Chromium for {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS), locale="en-US",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            await _dismiss_cookie_banners(page)
            await page.wait_for_timeout(1000)
            html = await page.content()
            await browser.close()

        logger.info(f"[playwright] success for {url} ({len(html)} bytes)")
        return html

    except Exception as e:
        logger.error(f"[playwright] failed for {url}: {e}")
        return None


async def _dismiss_cookie_banners(page) -> None:
    """Try to click common cookie-consent accept buttons."""
    for selector in COOKIE_BANNER_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=500):
                await btn.click(timeout=2000)
                logger.info(f"[playwright] dismissed cookie banner via selector: {selector}")
                return
        except Exception:
            continue

    for text in COOKIE_BUTTON_TEXTS:
        try:
            btn = page.get_by_role("button", name=text, exact=False).first
            if await btn.is_visible(timeout=500):
                await btn.click(timeout=2000)
                logger.info(f"[playwright] dismissed cookie banner via button text: {text!r}")
                return
        except Exception:
            continue
        try:
            link = page.get_by_role("link", name=text, exact=False).first
            if await link.is_visible(timeout=500):
                await link.click(timeout=2000)
                logger.info(f"[playwright] dismissed cookie banner via link text: {text!r}")
                return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scrape_policy(url: str, timeout: float = 30.0) -> Tuple[str, str, List[str]]:
    """
    Scrape a policy page and return (extracted_text, content_hash, discovered_links).

    discovered_links is a list of same-domain policy-related URLs found on the page.

    Strategy:
      1. Try httpx with 3 retries + exponential backoff.
      2. If httpx succeeds but extracted text < 200 chars, try Playwright.
      3. If httpx fails entirely, try Playwright.
      4. If both fail, raise ValueError.
    """
    logger.info(f"Scraping policy URL: {url}")

    # --- Strategy 1: httpx ---
    html = await _scrape_httpx(url, timeout=timeout)

    if html:
        text = extract_policy_text(html, url)
        discovered = _discover_policy_links(html, url)
        if len(text) >= MIN_CONTENT_LENGTH:
            content_hash = compute_hash(text)
            logger.info(
                f"[httpx] extracted {len(text)} chars from {url} "
                f"(hash: {content_hash[:12]}..., {len(discovered)} related links)"
            )
            return text, content_hash, discovered
        else:
            logger.warning(
                f"[httpx] extracted only {len(text)} chars (< {MIN_CONTENT_LENGTH}) "
                f"from {url} — trying Playwright fallback"
            )

    # --- Strategy 2: Playwright fallback ---
    html = await _scrape_playwright(url)

    if html:
        text = extract_policy_text(html, url)
        discovered = _discover_policy_links(html, url)
        if len(text) >= MIN_CONTENT_LENGTH:
            content_hash = compute_hash(text)
            logger.info(
                f"[playwright] extracted {len(text)} chars from {url} "
                f"(hash: {content_hash[:12]}..., {len(discovered)} related links)"
            )
            return text, content_hash, discovered
        else:
            logger.error(
                f"[playwright] extracted only {len(text)} chars from {url} "
                f"— page likely requires special handling"
            )

    raise ValueError(
        f"Failed to scrape {url}: both httpx (3 retries) and Playwright fallback "
        f"could not extract meaningful content (>= {MIN_CONTENT_LENGTH} chars)."
    )
