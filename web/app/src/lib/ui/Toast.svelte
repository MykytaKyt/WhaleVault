<script>
	import { hideToast, toast } from '#lib/state.svelte.js';
</script>

<div aria-live="polite" class="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-4">
	{#if toast.text}
		<div class="pointer-events-auto flex items-center gap-4 rounded-xl bg-[#2f2e2b] px-4 py-3 text-[14px] text-white">
			<span>{toast.text}</span>
			{#if toast.action}
				<button
					class="min-h-8 font-semibold text-[#8db8f7]"
					onclick={() => {
						toast.action();
						hideToast();
					}}>{toast.actionLabel}</button
				>
			{/if}
		</div>
	{/if}
</div>
