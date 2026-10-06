<script>
	import { SOURCES, shortDate } from '#lib/format.js';
	let { note, showTopic = true } = $props();
</script>

<a href="/n/{note.id}" class="list-item block rounded-lg px-3 py-3 hover:bg-hover">
	<div class="font-medium">{note.title || `Заметка #${note.id}`}</div>
	<div class="t-small mt-0.5 flex flex-wrap items-center gap-x-1.5">
		<span>{shortDate(note.created_at)}</span>
		{#if showTopic && note.topic}<span aria-hidden="true">·</span><span>{note.topic.emoji} {note.topic.name}</span>{/if}
		{#if note.source !== 'text'}<span aria-hidden="true">·</span><span>{SOURCES[note.source]}</span>{/if}
		{#each note.tags.slice(0, 3) as tag (tag)}<span aria-hidden="true">·</span><span>#{tag}</span>{/each}
	</div>
	{#if note.first_line}<div class="mt-1 line-clamp-1 text-[15px] text-muted">{note.first_line}</div>{/if}
</a>
