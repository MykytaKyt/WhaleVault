<script>
	// Status tile: label, value, colour by level (ok / warn / error / unknown)
	let { icon: Icon, label, value, hint = '', level = 'ok' } = $props();
	const tone = { ok: 'text-success', warn: 'text-warn', error: 'text-error', unknown: 'text-muted' };
	const word = { warn: 'внимание', error: 'проблема' };
</script>

<div class="rounded-xl border border-line px-3 py-2.5">
	<div class="t-small flex items-center gap-1.5"><Icon size={14} aria-hidden="true" />{label}</div>
	<div class="mt-0.5 flex items-baseline gap-1.5 font-semibold tabular-nums">
		<span class="h-2 w-2 shrink-0 self-center rounded-full bg-current {tone[level]}" aria-hidden="true"></span>
		<span class="truncate">{value}</span>
		{#if word[level]}<span class="sr-only">({word[level]})</span>{/if}
	</div>
	{#if hint}<div class="t-small truncate">{hint}</div>{/if}
</div>
