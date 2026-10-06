<script>
	import { renderMarkdown } from '#lib/markdown.js';
	let { text } = $props();
</script>

<!-- Sanitised by DOMPurify in renderMarkdown -->
<div class="md">{@html renderMarkdown(text)}</div>
