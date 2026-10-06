<script>
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import { Brain, MessageCircle, Send, Square } from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { ago, shortDate } from '#lib/format.js';
	import { refParts } from '#lib/markdown.js';
	import LoadError from '#lib/ui/LoadError.svelte';

	let { data } = $props();
	let question = $state('');
	let thinking = $state(false);
	let live = $state(null); // { question, answer, status, sources, error, done }
	let source = null; // EventSource
	let input = $state();

	const shown = $derived(live ?? (data.current ? { ...data.current, done: true, status: '' } : null));

	onMount(() => {
		const q = page.url.searchParams.get('q'); // from the palette: "Спросить у заметок"
		if (q) {
			question = q;
			ask();
		} else input?.focus();
		return () => source?.close();
	});

	async function ask(e) {
		e?.preventDefault();
		const q = question.trim();
		if (!q || (live && !live.done)) return;
		source?.close();
		live = { question: q, answer: '', status: 'Отправляю…', sources: [], error: '', done: false };
		const { id } = await api.post('/ask', { question: q, thinking });
		question = '';
		goto(`/ask?id=${id}`, { replaceState: true, noScroll: true, keepFocus: true, invalidateAll: false });
		source = new EventSource(`/api/ask/${id}/stream`);
		const on = (name, fn) => source.addEventListener(name, (ev) => fn(JSON.parse(ev.data)));
		on('status', (d) => (live.status = d.text));
		on('sources', (d) => (live.sources = d));
		on('token', (d) => {
			live.status = '';
			live.answer += d.t;
		});
		on('done', () => finish());
		on('error', (d) => finish(d.text));
		source.onerror = () => live && !live.done && finish('Связь прервалась. Ответ мог сохраниться — обновите страницу.');
	}

	async function finish(error = '') {
		source?.close();
		source = null;
		live.done = true;
		live.error = error;
		live.status = '';
		const history = await api.get('/ask/history');
		data.history = history;
		await tick();
		input?.focus();
	}

	function stop() {
		finish('Остановлено');
	}
</script>

<svelte:head><title>Спросить · WhaleVault</title></svelte:head>

{#if data.error}
	<LoadError {data} />
{:else}
	<div class="mx-auto max-w-[720px] lg:grid lg:max-w-[1008px] lg:grid-cols-[240px_minmax(0,720px)] lg:gap-12">
		<!-- History: left on desktop, a compact list on top on phones -->
		<nav aria-label="История вопросов" class="mb-6 lg:mb-0">
			<h2 class="t-small mb-2 font-medium">История</h2>
			<ul class="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:gap-0 lg:overflow-visible">
				{#each data.history ?? [] as h (h.id)}
					<li class="shrink-0 lg:shrink">
						<a
							href="/ask?id={h.id}"
							onclick={() => (live = null)}
							class="block max-w-60 truncate rounded-lg px-3 py-2 text-[14px] hover:bg-hover max-lg:bg-chip lg:max-w-none
								{shown && !live && data.current?.id === h.id ? 'bg-accent-soft text-accent' : ''}"
							title={h.question}
						>
							{h.question}
							<span class="t-small hidden lg:block">{ago(h.created_at)}</span>
						</a>
					</li>
				{:else}
					<li class="t-small">Вопросов пока не было</li>
				{/each}
			</ul>
		</nav>

		<div class="min-w-0">
			<h1 class="t-page">Спросить</h1>
			<p class="t-small mt-1">Ответ только по вашим заметкам, со ссылками на источники</p>

			<form onsubmit={ask} class="mt-5 rounded-xl border border-line bg-field p-2 focus-within:border-accent">
				<textarea
					bind:this={input}
					bind:value={question}
					onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && ask(e)}
					rows="2"
					placeholder="Что я записывал про…"
					aria-label="Вопрос"
					class="field-sizing-content max-h-48 w-full resize-none bg-transparent px-2 py-1 outline-none placeholder:text-muted"
				></textarea>
				<div class="flex items-center gap-2">
					<button type="button" role="switch" aria-checked={thinking} onclick={() => (thinking = !thinking)} class="btn {thinking ? 'bg-accent-soft text-accent' : 'btn-ghost'}">
						<Brain size={15} aria-hidden="true" />Думать дольше
					</button>
					{#if live && !live.done}
						<button type="button" class="btn btn-secondary ml-auto" onclick={stop}><Square size={14} aria-hidden="true" />Стоп</button>
					{:else}
						<button class="btn btn-primary ml-auto" disabled={!question.trim()}><Send size={15} aria-hidden="true" />Спросить</button>
					{/if}
				</div>
			</form>

			{#if shown}
				<article class="mt-8" aria-live="polite">
					<h2 class="font-semibold">{shown.question}</h2>
					{#if shown.status}<p class="t-small mt-2" role="status">{shown.status}</p>{/if}
					<div class="prose-plain mt-2">
						{#each refParts(shown.answer) as p, i (i)}{#if p.id}<a href="/n/{p.id}" class="t-mono text-accent">#{p.id}</a>{:else}{p.text}{/if}{/each}{#if live && !live.done && !live.status}<span class="animate-pulse">▍</span>{/if}
					</div>
					{#if shown.error}<p class="mt-2 text-error" role="alert">{shown.error}</p>{/if}
					{#if shown.done && shown.sources?.length}
						<h3 class="t-small mt-6 mb-2 font-medium">Источники</h3>
						<div class="grid gap-2 sm:grid-cols-2">
							{#each shown.sources as s (s.id)}
								<a href="/n/{s.id}" class="rounded-xl border border-line px-3 py-2 hover:bg-hover">
									<span class="t-mono text-accent">#{s.id}</span>
									<span class="block truncate font-medium">{s.title || 'Без заголовка'}</span>
									<span class="t-small block truncate">{s.topic} · {shortDate(s.created_at)}</span>
								</a>
							{/each}
						</div>
					{/if}
				</article>
			{:else}
				<div class="mt-12 flex flex-col items-center text-center text-muted">
					<MessageCircle size={28} aria-hidden="true" />
					<p class="mt-3 max-w-sm text-[15px]">Например: «сколько стоил ремонт катализатора?» или «что сказал научрук про введение?»</p>
				</div>
			{/if}
		</div>
	</div>
{/if}
