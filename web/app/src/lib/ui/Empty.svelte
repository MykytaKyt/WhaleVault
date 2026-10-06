<script>
	/** An honest empty or error state: what happened and what to do */
	let { icon: Icon = null, title, children = null, tone = 'muted' } = $props();
</script>

<div class="flex flex-col items-center px-4 py-12 text-center">
	{#if Icon}<Icon size={28} class={tone === 'error' ? 'text-error' : 'text-muted'} aria-hidden="true" />{/if}
	<p class="mt-3 font-medium">{title}</p>
	{#if children}<div class="t-small mt-1 max-w-sm">{@render children()}</div>{/if}
</div>
