<script>
	let { note, showTopic = true } = $props();
</script>

<a href="/notes/{note.id}" class="block rounded-md px-2 py-2.5 hover:bg-hover">
	<div class="font-medium">{note.title || `Заметка #${note.id}`}</div>
	<div class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted">
		{#if showTopic && note.topic}<span>{note.topic.emoji} {note.topic.name}</span>{/if}
		{#each note.tags as tag (tag)}<span class="rounded bg-chip px-1.5 text-[12px]">{tag}</span>{/each}
	</div>
	{#if note.preview}
		<div class="mt-1 truncate text-[14px] text-muted">{note.preview.split('\n')[0]}</div>
	{/if}
</a>
