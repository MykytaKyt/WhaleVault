<script>
	import { page } from '$app/state';
	import { api } from '#lib/api.js';
	import { byDay, KINDS } from '#lib/format.js';

	let entity = $state(null);
	let error = $state('');
	$effect(() => {
		entity = null;
		api.get(`/entities/${page.params.id}`).then((e) => (entity = e), (e) => (error = e.message));
	});
</script>

<svelte:head><title>{entity?.name ?? 'Сущность'} · WhaleVault</title></svelte:head>

{#if error}
	<p class="text-muted">Сущность не найдена.</p>
{:else if entity}
	<p class="text-[13px] text-faint"><a href="/entities" class="hover:text-fg">Сущности</a> / {KINDS[entity.kind]}</p>
	<h1 class="mt-1 text-[32px] leading-tight font-bold">{entity.name}</h1>
	{#if entity.aliases.length}<p class="mt-1 text-muted">Также: {entity.aliases.join(', ')}</p>{/if}

	{#if entity.page}<div class="prose-note mt-6">{entity.page}</div>{/if}

	{#each byDay(entity.facts) as g (g.label)}
		<h2 class="mt-8 mb-2 text-[13px] font-medium text-faint">{g.label}</h2>
		<ul class="space-y-2">
			{#each g.items as f (f.id)}
				<li>
					<span class={f.superseded_by ? 'text-faint line-through' : ''}>{f.text}</span>
					{#if f.note_id}<a href="/notes/{f.note_id}" class="ml-1 text-[13px] text-accent">#{f.note_id}</a>{/if}
					{#if f.superseded_by}
						<div class="mt-0.5 ml-4 text-[14px] text-muted">↳ заменено: {f.superseded_text}</div>
					{/if}
				</li>
			{/each}
		</ul>
	{:else}
		<p class="mt-8 text-muted">Фактов пока нет.</p>
	{/each}
{/if}
