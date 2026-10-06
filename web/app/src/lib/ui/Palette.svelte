<script>
	import { goto } from '$app/navigation';
	import { MessageCircle, Search } from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { shortDate } from '#lib/format.js';
	import { palette } from '#lib/state.svelte.js';

	let results = $state([]);
	let selected = $state(0);
	let loading = $state(false);
	let input = $state();
	let seq = 0;
	let timer;

	// The last row is always "Спросить у заметок"
	const rows = $derived(palette.query.trim() ? [...results, { ask: true }] : results);

	$effect(() => {
		if (palette.open) {
			results = [];
			selected = 0;
			queueMicrotask(() => input?.focus());
			if (palette.query) search();
		}
	});

	function search() {
		clearTimeout(timer);
		const q = palette.query.trim();
		if (!q) {
			results = [];
			return;
		}
		timer = setTimeout(async () => {
			const mine = ++seq;
			loading = true;
			try {
				const r = await api.get(`/search?limit=10&q=${encodeURIComponent(q)}`);
				if (mine === seq) {
					results = r;
					selected = 0;
				}
			} finally {
				if (mine === seq) loading = false;
			}
		}, 70);
	}

	function choose(row) {
		palette.open = false;
		if (row.ask) goto(`/ask?q=${encodeURIComponent(palette.query.trim())}`);
		else goto(`/n/${row.id}`);
	}

	function key(e) {
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selected = Math.min(selected + 1, rows.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selected = Math.max(selected - 1, 0);
		} else if (e.key === 'Enter' && rows[selected]) {
			e.preventDefault();
			choose(rows[selected]);
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
	<div class="fixed inset-0 z-50 bg-black/40 sm:pt-[10vh]">
		<button class="absolute inset-0 cursor-default" aria-label="Закрыть поиск" onclick={() => (palette.open = false)}></button>
		<div
			role="dialog"
			aria-modal="true"
			aria-label="Поиск"
			class="relative mx-auto flex h-full w-full flex-col overflow-hidden bg-bg sm:h-auto sm:max-h-[70vh] sm:max-w-[640px] sm:rounded-2xl sm:border sm:border-line"
		>
			<div class="flex items-center gap-2 border-b border-line px-4">
				<Search size={18} class="text-muted" aria-hidden="true" />
				<input
					bind:this={input}
					bind:value={palette.query}
					oninput={search}
					onkeydown={key}
					role="combobox"
					aria-expanded="true"
					aria-controls="palette-results"
					aria-label="Найти или спросить"
					placeholder="Найти или спросить…"
					class="h-14 flex-1 bg-transparent text-[16px] outline-none placeholder:text-muted"
				/>
				<button class="btn btn-ghost sm:hidden" onclick={() => (palette.open = false)}>Отмена</button>
			</div>
			<ul id="palette-results" role="listbox" aria-label="Результаты" class="flex-1 overflow-y-auto p-1.5">
				{#each rows as r, i (r.ask ? 'ask' : r.id)}
					<li role="option" aria-selected={i === selected}>
						<button
							class="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left {i === selected ? 'bg-hover' : ''}"
							onmouseenter={() => (selected = i)}
							onclick={() => choose(r)}
						>
							{#if r.ask}
								<MessageCircle size={17} class="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
								<span>Спросить у заметок: <span class="font-medium">«{palette.query.trim()}»</span></span>
							{:else}
								<span class="min-w-0 flex-1">
									<span class="block truncate font-medium">
										{#each r.title_marked as s, j (j)}{#if s.hit}<mark class="rounded bg-accent-soft text-accent">{s.t}</mark>{:else}{s.t}{/if}{/each}
									</span>
									<span class="t-small line-clamp-2">
										{#each r.snippet as s, j (j)}{#if s.hit}<mark class="rounded bg-accent-soft px-0.5 text-fg">{s.t}</mark>{:else}{s.t}{/if}{/each}
									</span>
									<span class="t-small block">
										{r.topic || 'Без темы'} · {shortDate(r.created_at)}{#if r.by_meaning} · по смыслу{/if}
									</span>
								</span>
							{/if}
						</button>
					</li>
				{:else}
					<li class="t-small px-3 py-3">
						{loading ? 'Ищу…' : 'Найдёт по словам и по смыслу. Enter на последней строке — спросить у заметок.'}
					</li>
				{/each}
			</ul>
		</div>
	</div>
{/if}
