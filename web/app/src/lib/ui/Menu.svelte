<script>
	import { Ellipsis } from '@lucide/svelte';
	/** "⋯" menu. items: [{label, icon, onclick, danger}] */
	let { items, label = 'Действия' } = $props();
	let open = $state(false);
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && (open = false)} />
<div class="relative">
	<button class="icon-btn" aria-label={label} aria-haspopup="menu" aria-expanded={open} onclick={() => (open = !open)}>
		<Ellipsis size={18} />
	</button>
	{#if open}
		<button class="fixed inset-0 z-30 cursor-default" aria-label="Закрыть меню" onclick={() => (open = false)}></button>
		<div role="menu" class="absolute right-0 z-40 mt-1 w-60 rounded-xl border border-line bg-bg p-1">
			{#each items as item (item.label)}
				<button
					role="menuitem"
					class="flex min-h-10 w-full items-center gap-2.5 rounded-lg px-3 text-left text-[14px] hover:bg-hover {item.danger
						? 'text-error'
						: ''}"
					onclick={() => {
						open = false;
						item.onclick();
					}}
				>
					{#if item.icon}<item.icon size={16} aria-hidden="true" />{/if}{item.label}
				</button>
			{/each}
		</div>
	{/if}
</div>
