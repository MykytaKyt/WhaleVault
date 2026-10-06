<script>
	// One metric over time (uPlot, canvas). The hover value shows in the header, uPlot's legend is off.
	import { onMount } from 'svelte';
	import 'uplot/dist/uPlot.min.css';

	let { t = [], v = [], label, unit = '', format = (x) => x.toFixed(0), height = 120 } = $props();
	let el = $state();
	let hover = $state(null);
	let plot;

	const last = $derived(v.length ? v[v.length - 1] : null);
	const shown = $derived(hover ?? (last != null ? { v: last, t: t[t.length - 1] } : null));
	const timeFmt = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

	function css(name) {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

	onMount(() => {
		let uPlot;
		let ro;
		(async () => {
			uPlot = (await import('uplot')).default;
			build(uPlot);
			ro = new ResizeObserver(() => plot?.setSize({ width: el.clientWidth, height }));
			ro.observe(el);
		})();
		return () => {
			ro?.disconnect();
			plot?.destroy();
		};
	});

	// 24-hour Russian ticks: hours within two days, dates beyond
	const hhmm = new Intl.DateTimeFormat('ru', { hour: '2-digit', minute: '2-digit' });
	const dm = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short' });
	function timeTicks(u, ticks) {
		const span = (u.scales.x.max ?? 0) - (u.scales.x.min ?? 0);
		const f = span > 2 * 86400 ? dm : hhmm;
		return ticks.map((x) => f.format(new Date(x * 1000)));
	}

	function build(uPlot) {
		plot?.destroy();
		const axis = { stroke: css('--text-secondary'), grid: { stroke: css('--line'), width: 1 }, ticks: { show: false }, font: '11px system-ui' };
		plot = new uPlot(
			{
				width: el.clientWidth,
				height,
				legend: { show: false },
				cursor: { points: { size: 6 }, drag: { x: false, y: false } },
				scales: { x: { time: true } },
				axes: [{ ...axis, space: 60, values: timeTicks }, { ...axis, size: 44, values: (_, ticks) => ticks.map((x) => format(x)) }],
				series: [{}, { stroke: css('--accent'), width: 1.5, fill: css('--accent-soft'), points: { show: false } }],
				hooks: {
					setCursor: [
						(u) => {
							const i = u.cursor.idx;
							hover = i == null || u.data[1][i] == null ? null : { v: u.data[1][i], t: u.data[0][i] };
						}
					]
				}
			},
			[t, v],
			el
		);
	}

	$effect(() => {
		// New data from the period switch or a live refresh
		if (plot) plot.setData([t, v]);
	});
</script>

<figure class="min-w-0 rounded-xl border border-line p-3">
	<figcaption class="mb-1 flex items-baseline gap-2">
		<span class="t-small">{label}</span>
		<span class="ml-auto font-medium tabular-nums">{shown ? `${format(shown.v)}${unit ? ` ${unit}` : ''}` : '—'}</span>
	</figcaption>
	<div class="t-small mb-1 h-4 text-right">{hover ? timeFmt.format(new Date(hover.t * 1000)) : ''}</div>
	{#if v.length}
		<div bind:this={el} role="img" aria-label="{label}: последнее значение {last != null ? format(last) : '—'} {unit}"></div>
	{:else}
		<div bind:this={el} class="t-small flex items-center justify-center" style="height: {height}px">Нет данных за период</div>
	{/if}
</figure>
