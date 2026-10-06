<script>
	import { invalidateAll } from '$app/navigation';
	import { Check } from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { byDay, date, KINDS } from '#lib/format.js';
	import { showToast } from '#lib/state.svelte.js';
	import LoadError from '#lib/ui/LoadError.svelte';
	import Markdown from '#lib/ui/Markdown.svelte';
	import Page from '#lib/ui/Page.svelte';

	let { data } = $props();
	const e = $derived(data.entity);
	const pending = $derived(new Set((e?.contradictions ?? []).flatMap((p) => [p.old.id, p.new.id])));

	async function save(body) {
		try {
			await api.patch(`/entities/${e.id}`, body);
			invalidateAll();
		} catch (err) {
			showToast(err.message, { tone: 'error' });
		}
	}
	async function resolve(fact) {
		await api.post(`/facts/${fact.id}/resolve`);
		showToast('Отмечено как актуальное');
		invalidateAll();
	}
</script>

{#if data.error}
	<Page><LoadError {data} what="Сущность" /></Page>
{:else if e}
	<Page title={e.name}>
		<p class="t-small"><a href="/e" class="hover:text-accent">Сущности</a> / {KINDS[e.kind]}</p>
		<h1><span class="sr-only">{e.name}</span>
			<input
				value={e.name}
				onblur={(ev) => ev.currentTarget.value.trim() && ev.currentTarget.value.trim() !== e.name && save({ name: ev.currentTarget.value.trim() })}
				onkeydown={(ev) => ev.key === 'Enter' && ev.currentTarget.blur()}
				aria-label="Название"
				class="t-page mt-1 w-full rounded-lg bg-transparent outline-none hover:bg-hover focus:bg-hover"
			/>
		</h1>
		<label class="t-small mt-1 flex items-center gap-2">
			<span class="shrink-0">Также:</span>
			<input
				value={e.aliases.join(', ')}
				onblur={(ev) => {
					const aliases = ev.currentTarget.value.split(',').map((a) => a.trim()).filter(Boolean);
					if (aliases.join(',') !== e.aliases.join(',')) save({ aliases });
				}}
				placeholder="другие написания через запятую"
				class="min-w-0 flex-1 rounded-md bg-transparent py-1 text-[14px] text-fg outline-none placeholder:text-muted hover:bg-hover focus:bg-hover"
			/>
		</label>

		{#if e.contradictions.length}
			<section class="mt-8" aria-label="Противоречия">
				<h2 class="t-section mb-1">Уточнить</h2>
				<p class="t-small mb-3">Модель нашла противоречия. Отметьте, что верно сейчас.</p>
				{#each e.contradictions as p (p.old.id)}
					<div class="mb-3 rounded-xl border border-line p-3">
						{#each [p.old, p.new] as f (f.id)}
							<div class="flex items-start gap-3 py-1.5">
								<div class="min-w-0 flex-1">
									<span class="t-small block">{date(f.created_at)}{#if f.note_id} · <a class="t-mono text-accent" href="/n/{f.note_id}">#{f.note_id}</a>{/if}</span>
									{f.text}
								</div>
								<button class="btn btn-secondary shrink-0" onclick={() => resolve(f)}><Check size={15} aria-hidden="true" />Верно</button>
							</div>
						{/each}
					</div>
				{/each}
			</section>
		{/if}

		{#if e.page}<div class="mt-8"><Markdown text={e.page} /></div>{/if}

		<section class="mt-8" aria-label="Факты">
			<h2 class="t-section mb-1">Факты</h2>
			{#each byDay(e.facts) as g (g.label)}
				<h3 class="t-small mt-4 mb-1">{g.label}</h3>
				<ul class="space-y-2">
					{#each g.items as f (f.id)}
						<li class={f.superseded_by && !pending.has(f.id) ? 'text-muted' : ''}>
							<span class={f.superseded_by ? 'line-through' : ''}>{f.text}</span>
							{#if f.note_id}<a href="/n/{f.note_id}" class="t-mono ml-1 text-accent">#{f.note_id}</a>{/if}
							{#if pending.has(f.id)}<span class="badge badge-warn ml-1">уточнить</span>{/if}
							{#if f.superseded_by && f.superseded_text}
								<div class="t-small mt-0.5 ml-4">→ {date(f.superseded_at)}: {f.superseded_text}</div>
							{/if}
						</li>
					{/each}
				</ul>
			{:else}
				<p class="text-muted">Фактов пока нет.</p>
			{/each}
		</section>
	</Page>
{/if}
