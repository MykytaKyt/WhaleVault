<script>
	import { Users } from '@lucide/svelte';
	import { KINDS, plural } from '#lib/format.js';
	import Empty from '#lib/ui/Empty.svelte';
	import LoadError from '#lib/ui/LoadError.svelte';
	import Page from '#lib/ui/Page.svelte';

	let { data } = $props();
	const groups = $derived(
		Object.keys(KINDS)
			.map((kind) => ({ kind, items: (data.entities ?? []).filter((e) => e.kind === kind) }))
			.filter((g) => g.items.length)
	);
</script>

<Page title="Сущности">
	<h1 class="t-page">Сущности</h1>
	<p class="t-small mt-1">Люди, машины, проекты и места, о которых есть факты в заметках</p>
	{#if data.error}
		<LoadError {data} />
	{:else if data.entities}
		{#each groups as g (g.kind)}
			<h2 class="t-section mt-8 mb-3">{KINDS[g.kind]}</h2>
			<div class="grid gap-2 sm:grid-cols-2">
				{#each g.items as e (e.id)}
					<a href="/e/{e.id}" class="flex flex-col rounded-xl border border-line px-4 py-3 hover:bg-hover">
						<span class="flex items-center gap-2 font-medium">
							<span class="truncate">{e.name}</span>
							{#if e.to_check}<span class="badge badge-warn ml-auto shrink-0">уточнить {e.to_check}</span>{/if}
						</span>
						<span class="t-small truncate">
							{plural(e.facts_count, 'факт', 'факта', 'фактов')}{#if e.aliases.length} · {e.aliases.join(', ')}{/if}
						</span>
					</a>
				{/each}
			</div>
		{:else}
			<Empty icon={Users} title="Пока пусто">Сущности появятся, когда в заметках встретятся люди, машины, проекты или места.</Empty>
		{/each}
	{/if}
</Page>
