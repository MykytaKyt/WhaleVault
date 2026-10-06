<script>
	import { invalidateAll } from '$app/navigation';
	import { SquareCheck } from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { due } from '#lib/format.js';
	import { showToast } from '#lib/state.svelte.js';
	import Empty from '#lib/ui/Empty.svelte';
	import LoadError from '#lib/ui/LoadError.svelte';
	import Page from '#lib/ui/Page.svelte';

	let { data } = $props();
	let showDone = $state(false);
	const groups = $derived((data.tasks?.groups ?? []).filter((g) => g.items.length));

	async function patch(task, body) {
		try {
			await api.patch(`/tasks/${task.id}`, body);
			await invalidateAll();
		} catch (e) {
			showToast(e.message, { tone: 'error' });
		}
	}
	const toggle = (t) => patch(t, { status: t.status === 'done' ? 'open' : 'done' });
	const setDue = (t, v) => patch(t, v ? { due_at: v } : { clear_due: true });
</script>

{#snippet row(t)}
	<div class="list-item flex items-start gap-3 rounded-lg px-3 py-2 hover:bg-hover">
		<input
			type="checkbox"
			checked={t.status === 'done'}
			onchange={() => toggle(t)}
			aria-label="Выполнено: {t.text}"
			class="mt-1.5 h-4 w-4 shrink-0 accent-[var(--accent)] max-md:h-5 max-md:w-5"
		/>
		<div class="min-w-0 flex-1">
			{#if t.note_id}
				<a href="/n/{t.note_id}" class="block {t.status === 'done' ? 'text-muted line-through' : ''}">{t.text}</a>
			{:else}
				<span class={t.status === 'done' ? 'text-muted line-through' : ''}>{t.text}</span>
			{/if}
			{#if t.note_title}<span class="t-small block truncate">{t.note_title}</span>{/if}
		</div>
		{#if t.status !== 'done'}
			<label class="t-small relative shrink-0 cursor-pointer rounded-md px-2 py-1 hover:bg-chip {t.due_at && t.due_at.slice(0, 10) < data.tasks.today ? 'text-error' : ''}">
				{t.due_at ? due(t.due_at) : '+ срок'}
				<input
					type="date"
					value={t.due_at?.slice(0, 10) ?? ''}
					onchange={(e) => setDue(t, e.currentTarget.value)}
					aria-label="Срок: {t.text}"
					class="absolute inset-0 cursor-pointer opacity-0"
				/>
			</label>
		{/if}
	</div>
{/snippet}

<Page title="Задачи">
	<h1 class="t-page">Задачи</h1>
	{#if data.error}
		<LoadError {data} />
	{:else if data.tasks}
		{#each groups as g (g.key)}
			<h2 class="t-section mt-8 mb-2 {g.key === 'overdue' ? 'text-error' : ''}">{g.label}</h2>
			{#each g.items as t (t.id)}{@render row(t)}{/each}
		{:else}
			<Empty icon={SquareCheck} title="Открытых задач нет">Задачи появляются сами, когда в заметке есть что сделать.</Empty>
		{/each}
		{#if data.tasks.done.length}
			<button class="btn btn-ghost mt-8" aria-expanded={showDone} onclick={() => (showDone = !showDone)}>
				{showDone ? '▾' : '▸'} Сделано недавно ({data.tasks.done.length})
			</button>
			{#if showDone}{#each data.tasks.done as t (t.id)}{@render row(t)}{/each}{/if}
		{/if}
	{/if}
</Page>
