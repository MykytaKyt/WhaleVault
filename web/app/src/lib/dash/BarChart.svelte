<script>
	// Bars by day (plain HTML, so text and bars stay crisp at any width), optionally stacked by series;
	// a dashed target line for shares. Tooltip in the header on hover/focus.
	import { shortDate } from '#lib/format.js';

	let { days = [], series = [], label, unit = '', format = (x) => String(Math.round(x)), target = null, height = 120 } = $props();
	const COLORS = ['var(--accent)', 'var(--warn)', 'var(--success)', '#9a6fd6', 'var(--error)', '#3a9fae', 'var(--text-secondary)'];
	let active = $state(null);

	const totals = $derived(days.map((_, i) => series.reduce((s, x) => s + (x.values[i] ?? 0), 0)));
	const max = $derived(Math.max(target ?? 0, ...totals, 1e-9));
	const pctOf = (v) => `${(v / max) * 100}%`;
</script>

<figure class="min-w-0 rounded-xl border border-line p-3">
	<figcaption class="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
		<span class="t-small">{label}</span>
		{#if series.length > 1}
			{#each series as s, k (s.label)}
				<span class="t-small flex items-center gap-1"><span class="inline-block h-2 w-2 rounded-sm" style="background: {COLORS[k % COLORS.length]}"></span>{s.label}</span>
			{/each}
		{/if}
		<span class="ml-auto font-medium tabular-nums">
			{#if active != null}{shortDate(days[active])}: {format(totals[active])}{unit}{:else if days.length}{format(totals.at(-1))}{unit}{:else}—{/if}
		</span>
	</figcaption>
	{#if days.length}
		<!-- One pointer handler for the whole chart: per-day buttons would be far below 44 px touch targets -->
		<div
			class="relative flex items-end"
			style="height: {height}px"
			role="img"
			aria-label="{label}: {days.map((d, i) => `${shortDate(d)} ${format(totals[i])}${unit}`).join(', ')}"
			onpointermove={(e) => {
				const r = e.currentTarget.getBoundingClientRect();
				active = Math.min(days.length - 1, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * days.length)));
			}}
			onpointerleave={() => (active = null)}
		>
			{#if target != null}
				<div class="pointer-events-none absolute inset-x-0 border-t border-dashed border-error" style="bottom: {pctOf(target)}"></div>
			{/if}
			{#each days as d, i (d)}
				<div class="flex h-full min-w-0 flex-1 flex-col-reverse items-center rounded-sm {active === i ? 'bg-hover' : ''}">
					{#each series as s, k (s.label)}
						{#if (s.values[i] ?? 0) > 0}
							<div class="w-3/5 max-w-7 min-w-0.5 first:rounded-b-sm last:rounded-t-sm" style="height: {pctOf(s.values[i])}; background: {COLORS[k % COLORS.length]}"></div>
						{/if}
					{/each}
				</div>
			{/each}
		</div>
		<div class="t-small mt-1 flex justify-between text-[12px]"><span>{shortDate(days[0])}</span>{#if days.length > 1}<span>{shortDate(days.at(-1))}</span>{/if}</div>
	{:else}
		<div class="t-small flex items-center justify-center" style="height: {height}px">Нет данных за период</div>
	{/if}
</figure>
