<script>
	import { goto } from '$app/navigation';
	import { api } from '#lib/api.js';
	import { dayLabel } from '#lib/format.js';
	import { palette } from '#lib/state.svelte.js';

	let q = $state('');
	let results = $state([]);
	let selected = $state(0);
	let input = $state();
	let seq = 0;
	let timer;

	$effect(() => {
		if (palette.open) {
			q = '';
			results = [];
			selected = 0;
			queueMicrotask(() => input?.focus());
		}
	});

	function search() {
		clearTimeout(timer);
		const query = q.trim();
		if (!query) {
			results = [];
			return;
		}
		timer = setTimeout(async () => {
			const mine = ++seq;
			const r = await api.get(`/search?fast=1&limit=12&q=${encodeURIComponent(query)}`);
			if (mine === seq) {
				results = r;
				selected = 0;
			}
		}, 80);
	}

	function open(r) {
		palette.open = false;
		goto(`/notes/${r.id}`);
	}

	function key(e) {
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selected = Math.min(selected + 1, results.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selected = Math.max(selected - 1, 0);
		} else if (e.key === 'Enter' && results[selected]) {
			open(results[selected]);
		} else if (e.key === 'Escape') {
			palette.open = false;
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			palette.open = !palette.open;
		}
	}}
/>

{#if palette.open}
	<button class="fixed inset-0 z-50 bg-black/40" aria-label="Закрыть поиск" onclick={() => (palette.open = false)}
	></button>
	<div
		class="fixed top-[12vh] left-1/2 z-50 w-[min(640px,calc(100vw-24px))] -translate-x-1/2 overflow-hidden rounded-xl bg-bg shadow-2xl"
	>
		<input
			bind:this={input}
			bind:value={q}
			oninput={search}
			onkeydown={key}
			placeholder="Искать в заметках…"
			class="w-full border-b border-line bg-transparent px-4 py-3 text-[16px] outline-none placeholder:text-faint"
		/>
		<ul class="max-h-[60vh] overflow-y-auto py-1">
			{#each results as r, i (r.id)}
				<li>
					<button
						class="flex w-full flex-col px-4 py-2 text-left {i === selected ? 'bg-hover' : ''}"
						onmouseenter={() => (selected = i)}
						onclick={() => open(r)}
					>
						<span class="truncate font-medium">{r.title || `#${r.id}`}</span>
						<span class="truncate text-[13px] text-muted">
							{r.topic} · {dayLabel(r.created_at)} · {r.first_line}
						</span>
					</button>
				</li>
			{:else}
				{#if q.trim()}<li class="px-4 py-3 text-sm text-faint">Ничего не нашлось</li>{/if}
			{/each}
		</ul>
	</div>
{/if}
