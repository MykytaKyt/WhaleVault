<script>
	/** Placeholder lines while a list loads */
	let { lines = 3, cards = 0 } = $props();
</script>

<div aria-busy="true" aria-label="Загрузка">
	{#if cards}
		<div class="grid gap-3 sm:grid-cols-2">
			{#each Array(cards) as _, i (i)}
				<div class="rounded-xl border border-line p-4">
					<div class="skeleton mb-3 h-5 w-1/2"></div>
					<div class="skeleton mb-2 h-3.5 w-full"></div>
					<div class="skeleton h-3.5 w-4/5"></div>
				</div>
			{/each}
		</div>
	{:else}
		{#each Array(lines) as _, i (i)}
			<div class="py-3">
				<div class="skeleton mb-2 h-4 w-2/5"></div>
				<div class="skeleton h-3.5 w-4/5"></div>
			</div>
		{/each}
	{/if}
</div>
