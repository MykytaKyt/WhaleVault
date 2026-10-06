<script>
	// Notes grouped by day with cursor pagination; loads the next page when the end scrolls into view.
	import { untrack } from 'svelte';
	import { api } from '#lib/api.js';
	import { byDay } from '#lib/format.js';
	import NoteCard from './NoteCard.svelte';

	let { topicId = null } = $props();
	let items = $state([]);
	let next = $state(null);
	let loading = $state(false);
	let done = $state(false);
	let sentinel = $state();

	async function load(reset = false) {
		if (loading) return;
		loading = true;
		const params = new URLSearchParams({ limit: '40' });
		if (topicId) params.set('topic_id', topicId);
		if (!reset && next) params.set('cursor', next);
		const r = await api.get(`/notes?${params}`);
		items = reset ? r.items : [...items, ...r.items];
		next = r.next;
		done = !r.next;
		loading = false;
	}

	$effect(() => {
		topicId; // the only dependency: reload when the topic changes
		untrack(() => {
			// load() reads `loading` and `next`; untracked, so its own state changes don't re-run this effect
			items = [];
			next = null;
			done = false;
			load(true);
		});
	});

	$effect(() => {
		if (!sentinel) return;
		const io = new IntersectionObserver((e) => e[0].isIntersecting && !done && load());
		io.observe(sentinel);
		return () => io.disconnect();
	});
</script>

{#each byDay(items) as g (g.label)}
	<h2 class="mt-8 mb-1 px-2 text-[13px] font-medium text-faint">{g.label}</h2>
	{#each g.items as note (note.id)}<NoteCard {note} showTopic={!topicId} />{/each}
{:else}
	{#if done}<p class="px-2 text-muted">Заметок пока нет. Пришлите что-нибудь боту в Telegram.</p>{/if}
{/each}
<div bind:this={sentinel} class="h-8"></div>
{#if loading}<p class="px-2 text-sm text-faint">Загружаю…</p>{/if}
