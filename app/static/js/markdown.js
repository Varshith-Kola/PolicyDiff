/**
 * PolicyDiff — Markdown Rendering Module
 *
 * Configures marked.js v14 to render policy snapshots as clean, readable HTML.
 * All renderer methods receive a single token object (marked v14 API).
 */

(function () {
    'use strict';

    if (typeof marked === 'undefined') {
        console.warn('[PolicyDiff] marked.js not loaded');
        return;
    }

    /*
     * In marked v14, every renderer method receives a single token object.
     * Key token shapes:
     *   link:      { href, title, tokens }          — tokens are inline children
     *   heading:   { depth, tokens }                 — tokens are inline children
     *   paragraph: { tokens }                        — tokens are inline children
     *   listitem:  { tokens, task, checked, loose }  — tokens are inline children
     *   strong:    { tokens }
     *   em:        { tokens }
     *   codespan:  { text }
     *   hr:        {}
     *
     * Use this.parser.parseInline(token.tokens) to render child tokens.
     */

    /**
     * Generate a URL-friendly slug from heading text (for anchor IDs).
     */
    function slugify(text) {
        return text
            .toLowerCase()
            .replace(/<[^>]+>/g, '')          // strip HTML tags
            .replace(/^\d+\.\s*/, '')          // strip leading "1. "
            .replace(/[^\w\s-]/g, '')           // strip non-word chars
            .replace(/\s+/g, '-')               // spaces to hyphens
            .replace(/-+/g, '-')                // collapse hyphens
            .replace(/^-|-$/g, '');             // trim leading/trailing
    }

    const renderer = {

        // ---- Links ----
        link(token) {
            const href  = token.href || '';
            const title = token.title || '';
            // Render child tokens to get the display text
            const text  = this.parser.parseInline(token.tokens);
            const titleAttr = title ? ` title="${title}"` : '';

            if (href.startsWith('http://') || href.startsWith('https://')) {
                return `<a href="${href}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
            }
            // Anchor links — just render the text
            if (href.startsWith('#')) {
                return `<span>${text}</span>`;
            }
            // Relative links — styled but not clickable
            return `<span class="relative-link">${text}</span>`;
        },

        // ---- Headings (with anchor IDs for TOC navigation) ----
        heading(token) {
            const depth = token.depth || 2;
            const text  = this.parser.parseInline(token.tokens);
            const id    = slugify(text);
            const idAttr = id ? ` id="${id}"` : '';
            return `<h${depth}${idAttr}>${text}</h${depth}>\n`;
        },

        // ---- Paragraphs ----
        paragraph(token) {
            const text = this.parser.parseInline(token.tokens);
            return `<p>${text}</p>\n`;
        },

        // ---- List items ----
        listitem(token) {
            let body = '';
            if (token.tokens) {
                body = this.parser.parse(token.tokens, !!token.loose);
            }
            return `<li>${body}</li>\n`;
        },

        // ---- Tables ----
        table(token) {
            let head = '';
            if (token.header && token.header.length) {
                const cells = token.header.map((cell, i) => {
                    const align = token.align && token.align[i] ? ` style="text-align:${token.align[i]}"` : '';
                    const content = this.parser.parseInline(cell.tokens);
                    return `<th${align}>${content}</th>`;
                }).join('');
                head = `<thead><tr>${cells}</tr></thead>\n`;
            }
            let body = '';
            if (token.rows && token.rows.length) {
                const rows = token.rows.map(row => {
                    const cells = row.map((cell, i) => {
                        const align = token.align && token.align[i] ? ` style="text-align:${token.align[i]}"` : '';
                        const content = this.parser.parseInline(cell.tokens);
                        return `<td${align}>${content}</td>`;
                    }).join('');
                    return `<tr>${cells}</tr>`;
                }).join('\n');
                body = `<tbody>\n${rows}\n</tbody>\n`;
            }
            return `<table>\n${head}${body}</table>\n`;
        },

        // ---- Horizontal rules ----
        hr() {
            return '<hr>\n';
        },

        // ---- Strong/bold ----
        strong(token) {
            const text = this.parser.parseInline(token.tokens);
            return `<strong>${text}</strong>`;
        },

        // ---- Emphasis/italic ----
        // Detects label patterns like _Account Information:_ and renders as
        // inline labels (matching original page where <i> labels appear bold).
        em(token) {
            const text = this.parser.parseInline(token.tokens);
            // Label pattern: short italic text ending with colon, or a title-cased term
            const plain = text.replace(/<[^>]+>/g, '').trim();
            if (plain.endsWith(':') && plain.length < 60) {
                return `<strong class="policy-label">${text}</strong>`;
            }
            return `<em>${text}</em>`;
        },

        // ---- Code spans ----
        codespan(token) {
            return `<code>${token.text || ''}</code>`;
        },
    };

    marked.use({
        renderer: renderer,
        breaks: false,
        gfm: true,
    });

})();


/**
 * Render markdown text to HTML.
 * Called by the Alpine.js app via renderMarkdown().
 */
function policyDiffRenderMarkdown(text) {
    if (!text) return '';

    if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
        try {
            return marked.parse(text);
        } catch (e) {
            console.error('[PolicyDiff] marked.parse error:', e);
        }
    }

    // Fallback if marked.js is unavailable
    return _basicMarkdownRender(text);
}


/**
 * Minimal fallback renderer.
 */
function _basicMarkdownRender(text) {
    let h = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Headings
    h = h.replace(/^#{6}\s+(.+)$/gm, '<h6>$1</h6>');
    h = h.replace(/^#{5}\s+(.+)$/gm, '<h5>$1</h5>');
    h = h.replace(/^#{4}\s+(.+)$/gm, '<h4>$1</h4>');
    h = h.replace(/^#{3}\s+(.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^#{2}\s+(.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^#{1}\s+(.+)$/gm, '<h1>$1</h1>');

    // Bold then italic
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/__(.+?)__/g, '<strong>$1</strong>');
    h = h.replace(/_(.+?)_/g, '<em>$1</em>');

    // Links — external
    h = h.replace(
        /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );
    // Links — relative
    h = h.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g,
        '<span class="relative-link">$1</span>'
    );

    // Horizontal rules
    h = h.replace(/^[-*]{3,}$/gm, '<hr>');

    // Bullet lists
    h = h.replace(/^\s*\*\s+(.+)$/gm, '<li>$1</li>');
    h = h.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, '<ul>$&</ul>');

    // Paragraphs
    h = h.replace(/\n\n+/g, '</p><p>');
    h = '<p>' + h + '</p>';
    h = h.replace(/<p>\s*<\/p>/g, '');

    return h;
}
