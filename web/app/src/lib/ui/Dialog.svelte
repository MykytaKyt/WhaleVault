<script>
	/** Modal dialog. Closes on Escape and on backdrop click. */
	let { open = $bindable(false), title, children, actions = null } = $props();
	let panel = $state();
	$effect(() => {
		if (open) queueMicrotask(() => panel?.querySelector('input,select,textarea,button')?.focus());
	});
</script>

{#if open}
	<div class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-start sm:pt-[12vh]">
		<button class="absolute inset-0 cursor-default" aria-label="Закрыть" onclick={() => (open = false)}></button>
		<div
			bind:this={panel}
			role="dialog"
			aria-modal="true"
			aria-label={title}
			tabindex="-1"
			onkeydown={(e) => e.key === 'Escape' && (open = false)}
			class="relative w-full rounded-t-2xl border border-line bg-bg p-5 sm:max-w-md sm:rounded-2xl"
		>
			<h2 class="t-section mb-3">{title}</h2>
			{@render children()}
			{#if actions}<div class="mt-5 flex justify-end gap-2">{@render actions()}</div>{/if}
		</div>
	</div>
{/if}
