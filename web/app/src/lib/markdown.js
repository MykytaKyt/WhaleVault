// Summaries and entity pages come from the database as markdown. Rendered with marked, sanitised with
// DOMPurify; [#123] becomes a link to the note.
import DOMPurify from 'dompurify';
import { marked } from 'marked';

marked.use({ gfm: true, breaks: false });

export function renderMarkdown(text) {
	const withRefs = (text ?? '').replace(/\[#(\d+)\]/g, (_, id) => `<a class="note-ref" href="/n/${id}">#${id}</a>`);
	return DOMPurify.sanitize(marked.parse(withRefs), { ALLOWED_ATTR: ['href', 'class'] });
}

/** Plain text with [#id] → [{text} | {id}] for answers rendered without HTML */
export function refParts(text) {
	return (text ?? '').split(/(\[#\d+\])/g).map((p) => {
		const m = p.match(/^\[#(\d+)\]$/);
		return m ? { id: Number(m[1]) } : { text: p };
	});
}
