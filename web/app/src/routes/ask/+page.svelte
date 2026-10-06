<script>
	import { tick } from 'svelte';
	import { api, ask } from '#lib/api.js';

	let history = $state([]);
	let question = $state('');
	let current = $state(null); // { question, answer, status, sources, cited, error }
	let bottom = $state();
	let controller;

	api.get('/asks?limit=20').then((h) => (history = h.reverse()));

	// [#12] in answers become links to the notes
	function parts(text) {
		return text.split(/(\[#\d+\])/g).map((p) => {
			const m = p.match(/^\[#(\d+)\]$/);
			return m ? { id: Number(m[1]) } : { text: p };
		});
	}

	async function send(e) {
		e?.preventDefault();
		const q = question.trim();
		if (!q || current) return;
		question = '';
		current = { question: q, answer: '', status: '', sources: [], cited: [], error: '' };
		controller = new AbortController();
		await tick();
		bottom?.scrollIntoView({ behavior: 'smooth' });
		try {
			await ask(
				q,
				{
					status: (d) => (current.status = d.text),
					sources: (d) => (current.sources = d),
					token: (d) => {
						current.status = '';
						current.answer += d.t;
					},
					done: (d) => (current.cited = d.cited),
					error: (d) => (current.error = d.text)
				},
				controller.signal
			);
		} catch (err) {
			if (err.name !== 'AbortError') current.error = 'Связь прервалась';
		}
		history = [...history, { question: current.question, answer: current.answer, note_ids: current.cited }];
		current = null;
		await tick();
		bottom?.scrollIntoView({ behavior: 'smooth' });
	}
</script>

<svelte:head><title>Спросить · WhaleVault</title></svelte:head>
<h1 class="text-[32px] leading-tight font-bold">Спросить</h1>
<p class="mt-1 text-muted">Ответы только по вашим заметкам, со ссылками на источники</p>

{#snippet answer(text)}
	<div class="prose-note">
		{#each parts(text) as p, i (i)}{#if p.id}<a href="/notes/{p.id}" class="text-accent">#{p.id}</a>{:else}{p.text}{/if}{/each}
	</div>
{/snippet}

<div class="mt-8 space-y-8">
	{#each history as h, i (i)}
		<div>
			<div class="mb-1 font-medium">{h.question}</div>
			{@render answer(h.answer)}
		</div>
	{/each}
	{#if current}
		<div>
			<div class="mb-1 font-medium">{current.question}</div>
			{#if current.status}<div class="text-[14px] text-faint">{current.status}</div>{/if}
			{@render answer(current.answer)}
			{#if current.error}<div class="text-danger">{current.error}</div>{/if}
		</div>
	{/if}
	<div bind:this={bottom}></div>
</div>

<form onsubmit={send} class="sticky bottom-4 mt-8 flex gap-2 rounded-xl bg-bg p-1 shadow-[0_0_0_1px_var(--line),0_4px_16px_rgba(0,0,0,0.08)]">
	<textarea
		bind:value={question}
		onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && send(e)}
		rows="1"
		placeholder="Что я записывал про…"
		class="field-sizing-content max-h-40 flex-1 resize-none bg-transparent px-3 py-2 outline-none placeholder:text-faint"
	></textarea>
	{#if current}
		<button type="button" class="px-3 text-muted" onclick={() => controller?.abort()}>Стоп</button>
	{:else}
		<button disabled={!question.trim()} class="rounded-lg bg-accent px-4 font-medium text-white disabled:opacity-40">→</button>
	{/if}
</form>
