<script>
	import { api } from '#lib/api.js';
	import { due } from '#lib/format.js';
	import { refreshSidebar } from '#lib/state.svelte.js';

	let data = $state(null);
	let showDone = $state(false);
	let editing = $state(null);
	const load = async () => (data = await api.get('/tasks'));
	load();

	async function toggle(t) {
		await api.patch(`/tasks/${t.id}`, { status: t.status === 'done' ? 'open' : 'done' });
		await load();
		refreshSidebar();
	}
	async function setDue(t, value) {
		editing = null;
		await api.patch(`/tasks/${t.id}`, value ? { due_at: value } : { clear_due: true });
		await load();
	}
</script>

<svelte:head><title>Задачи · WhaleVault</title></svelte:head>
<h1 class="text-[32px] leading-tight font-bold">Задачи</h1>

{#snippet task(t)}
	<div class="group flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-hover">
		<input type="checkbox" checked={t.status === 'done'} onchange={() => toggle(t)} class="mt-1.5 accent-accent" />
		<div class="min-w-0 flex-1">
			<div class={t.status === 'done' ? 'text-faint line-through' : ''}>{t.text}</div>
			<div class="flex flex-wrap gap-x-3 text-[13px] text-muted">
				{#if editing === t.id}
					<input
						type="date"
						value={t.due_at?.slice(0, 10) ?? ''}
						onchange={(e) => setDue(t, e.currentTarget.value)}
						onblur={() => (editing = null)}
						class="rounded bg-field px-1 outline-none"
					/>
					<button class="text-faint" onmousedown={() => setDue(t, '')}>без срока</button>
				{:else if t.status !== 'done'}
					<button class="hover:text-fg" onclick={() => (editing = t.id)}>{t.due_at ? due(t.due_at) : '+ срок'}</button>
				{/if}
				{#if t.note_id}<a href="/notes/{t.note_id}" class="truncate hover:text-fg">{t.note_title || `#${t.note_id}`}</a>{/if}
			</div>
		</div>
	</div>
{/snippet}

{#if data}
	{#each data.groups.filter((g) => g.items.length) as g (g.key)}
		<h2 class="mt-8 mb-1 px-2 text-[13px] font-medium text-faint">{g.label}</h2>
		{#each g.items as t (t.id)}{@render task(t)}{/each}
	{:else}
		<p class="mt-8 text-muted">🎉 Открытых задач нет.</p>
	{/each}

	{#if data.done.length}
		<button class="mt-10 px-2 text-[13px] text-faint hover:text-fg" onclick={() => (showDone = !showDone)}>
			{showDone ? '▾' : '▸'} Сделано недавно ({data.done.length})
		</button>
		{#if showDone}{#each data.done as t (t.id)}{@render task(t)}{/each}{/if}
	{/if}
{/if}
