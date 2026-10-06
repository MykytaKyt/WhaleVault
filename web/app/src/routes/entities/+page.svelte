<script>
	import { api } from '#lib/api.js';
	import { KINDS } from '#lib/format.js';

	let entities = $state(null);
	api.get('/entities').then((e) => (entities = e));
	const groups = $derived(
		Object.keys(KINDS)
			.map((kind) => ({ kind, items: (entities ?? []).filter((e) => e.kind === kind) }))
			.filter((g) => g.items.length)
	);
</script>

<svelte:head><title>Сущности · WhaleVault</title></svelte:head>
<h1 class="text-[32px] leading-tight font-bold">Сущности</h1>
<p class="mt-1 text-muted">Люди, машины, проекты и места из заметок</p>

{#each groups as g (g.kind)}
	<h2 class="mt-8 mb-1 px-2 text-[13px] font-medium text-faint">{KINDS[g.kind]}</h2>
	{#each g.items as e (e.id)}
		<a href="/entities/{e.id}" class="flex items-baseline gap-2 rounded-md px-2 py-2 hover:bg-hover">
			<span class="font-medium">{e.name}</span>
			{#if e.aliases.length}<span class="truncate text-[13px] text-faint">{e.aliases.join(', ')}</span>{/if}
			<span class="ml-auto shrink-0 text-[13px] text-muted">{e.facts_count} фактов</span>
		</a>
	{/each}
{:else}
	{#if entities}<p class="mt-8 text-muted">Пока пусто: сущности появятся из заметок про людей, машины и проекты.</p>{/if}
{/each}
