<script>
	/** One row of a Notion-like properties block: icon and name on the left, value on the right */
	let { icon: Icon, label, children } = $props();
</script>

<div class="flex min-h-9 items-start gap-3 py-1">
	<div class="t-small flex w-28 shrink-0 items-center gap-2 pt-0.5">
		<Icon size={15} aria-hidden="true" />{label}
	</div>
	<div class="min-w-0 flex-1 text-[15px]">{@render children()}</div>
</div>
