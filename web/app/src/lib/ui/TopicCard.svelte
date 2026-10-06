<script>
	import { ago, plural } from '#lib/format.js';
	let { topic } = $props();
</script>

<a href="/t/{topic.slug}" class="flex flex-col rounded-xl border border-line p-4 hover:bg-hover">
	<div class="flex items-start gap-2">
		<span class="text-[22px] leading-7" aria-hidden="true">{topic.emoji || '📁'}</span>
		<span class="min-w-0 flex-1 text-[17px] leading-7 font-semibold">{topic.name}</span>
		{#if topic.new_today}<span class="badge badge-new shrink-0">новое</span>{/if}
	</div>
	{#if topic.preview}
		<p class="mt-2 line-clamp-3 text-[15px] leading-6 text-fg/85">{topic.preview}</p>
	{:else}
		<p class="mt-2 text-[15px] leading-6 text-muted">Сводки пока нет</p>
	{/if}
	<div class="t-small mt-auto flex gap-1.5 pt-3">
		<span>{plural(topic.notes_count, 'заметка', 'заметки', 'заметок')}</span>
		{#if topic.overview_updated_at}<span aria-hidden="true">·</span><span>сводка {ago(topic.overview_updated_at)}</span>{/if}
	</div>
</a>
