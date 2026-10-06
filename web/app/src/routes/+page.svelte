<script>
	import { LayoutGrid, Search } from '@lucide/svelte';
	import Empty from '#lib/ui/Empty.svelte';
	import LoadError from '#lib/ui/LoadError.svelte';
	import Page from '#lib/ui/Page.svelte';
	import TopicCard from '#lib/ui/TopicCard.svelte';
	import { openPalette } from '#lib/state.svelte.js';

	let { data } = $props();
	const fresh = $derived((data.topics ?? []).filter((t) => t.new_today).length);
</script>

<Page title="Темы">
	<h1 class="t-page">Темы</h1>
	<button
		class="mt-5 flex h-12 w-full items-center gap-3 rounded-xl border border-line bg-field px-4 text-left text-muted hover:bg-hover"
		onclick={() => openPalette()}
	>
		<Search size={18} aria-hidden="true" />Найти или спросить…
	</button>

	{#if data.error}
		<LoadError {data} />
	{:else if data.topics}
		{#if data.topics.length}
			<p class="t-small mt-6 mb-3">
				{#if fresh}Новое за сутки в {fresh} {fresh === 1 ? 'теме' : 'темах'}{:else}За сутки новых заметок не было{/if}
			</p>
			<div class="grid gap-3 sm:grid-cols-2">
				{#each data.topics as topic (topic.slug)}<TopicCard {topic} />{/each}
			</div>
		{:else}
			<Empty icon={LayoutGrid} title="Тем пока нет">Пришлите боту в Telegram первую заметку — модель сама разложит её по теме.</Empty>
		{/if}
	{/if}
</Page>
