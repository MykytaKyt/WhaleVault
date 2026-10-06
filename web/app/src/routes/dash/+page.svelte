<script>
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { Brain, Cpu, HardDrive, ListTodo, Server, Sparkles, Thermometer, Zap } from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { ago, bytes, num, pct, shortDate } from '#lib/format.js';
	import BarChart from '#lib/dash/BarChart.svelte';
	import LineChart from '#lib/dash/LineChart.svelte';
	import Tile from '#lib/dash/Tile.svelte';
	import LoadError from '#lib/ui/LoadError.svelte';

	let { data } = $props();
	// Writable deriveds: reset from the load data on navigation, overwritten by the live poll / filter
	let live = $derived(data.live);
	let events = $derived(data.events ?? []);
	let kind = $state('');

	const s = $derived(data.summary);
	const h = $derived(s?.hardware ?? {});

	onMount(() => {
		// Live values every 30 s; history charts only when the period changes
		const timer = setInterval(async () => {
			try {
				live = await api.get('/metrics/live');
			} catch {}
		}, 30000);
		return () => clearInterval(timer);
	});

	async function filter(k) {
		kind = k;
		events = await api.get(`/metrics/events?limit=50${k ? `&kind=${k}` : ''}`);
	}

	const PERIODS = [['day', 'Сутки'], ['week', 'Неделя'], ['month', 'Месяц']];
	const KINDS = [['', 'Все'], ['model', 'Модели'], ['job', 'Задания'], ['note', 'Заметки'], ['error', 'Ошибки']];
	const gb = (x) => (x / 1024 ** 3).toFixed(1);
	const mb = (x) => (x >= 1024 ? `${(x / 1024).toFixed(1)}K` : x.toFixed(0));
	const loaded = $derived(
		!live?.llm_reachable ? 'llm недоступен' : live.models_loaded.length ? live.models_loaded.join(', ') : 'GPU пуст'
	);
	const time = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
</script>

<svelte:head><title>Дашборд · WhaleVault</title></svelte:head>

<div class="mx-auto max-w-[1008px]">
	<div class="flex flex-wrap items-center gap-3">
		<h1 class="t-page mr-auto">Дашборд</h1>
		<div class="flex rounded-lg bg-chip p-0.5 text-[14px]" role="group" aria-label="Период">
			{#each PERIODS as [p, label] (p)}
				<button
					class="min-h-9 rounded-md px-3 {data.period === p ? 'bg-bg font-medium' : 'text-muted'}"
					aria-pressed={data.period === p}
					onclick={() => goto(`/dash?p=${p}`, { noScroll: true, keepFocus: true })}>{label}</button
				>
			{/each}
		</div>
	</div>

	{#if data.error}
		<LoadError {data} />
	{:else if s}
		<!-- 1. Status right now -->
		<section aria-label="Состояние" class="mt-6">
			{#if live.stale}<p class="t-small mb-2 text-warn">Бот не присылал замеры больше 5 минут — он запущен?</p>{/if}
			<div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
				<Tile icon={Server} label="Сервер" value="онлайн" hint={live.sampled_at ? `замер ${ago(new Date(live.sampled_at * 1000).toISOString())}` : 'нет замеров'} level={live.stale ? 'warn' : 'ok'} />
				<Tile icon={Brain} label="В памяти" value={loaded} level={live.llm_reachable ? 'ok' : 'error'} />
				<Tile icon={Thermometer} label="GPU" value={live.gpu.temp != null ? `${num(live.gpu.temp)} °C` : '—'} hint={live.gpu.power != null ? `${num(live.gpu.power, 1)} Вт · P${num(live.gpu.pstate)}` : ''} level={live.levels.gpu_temp} />
				<Tile icon={ListTodo} label="Очередь" value={String(live.queue)} level={live.queue > 5 ? 'warn' : 'ok'} />
				<Tile icon={HardDrive} label="Диск свободно" value={pct(live.disk_free_share)} hint={live.disk_total ? `${bytes(live.disk_total - live.disk_used)} из ${bytes(live.disk_total)}` : ''} level={live.levels.disk} />
				<Tile icon={Sparkles} label="Уборка" value={live.last_cleanup ?? 'не было'} level={live.last_cleanup ? 'ok' : 'unknown'} />
			</div>
		</section>

		<!-- 2. Hardware -->
		<section aria-label="Железо" class="mt-10">
			<h2 class="t-section mb-3">Железо</h2>
			<div class="grid gap-3 md:grid-cols-2">
				<LineChart label="Температура GPU" unit="°C" t={h.gpu_temp.t} v={h.gpu_temp.v} />
				<LineChart label="Потребление GPU" unit="Вт" t={h.gpu_power.t} v={h.gpu_power.v} format={(x) => x.toFixed(1)} />
				<LineChart label="Занятая VRAM" unit="МБ" t={h.gpu_vram.t} v={h.gpu_vram.v} format={mb} />
				<LineChart label="ОЗУ сервера" unit="ГБ" t={h.ram_used.t} v={h.ram_used.v} format={gb} />
				<LineChart label="Диск занято" unit="ГБ" t={h.disk_used.t} v={h.disk_used.v} format={gb} />
				<LineChart label="Загрузка CPU" unit="%" t={h.cpu_load.t} v={h.cpu_load.v} />
			</div>
		</section>

		<!-- 3. Models -->
		<section aria-label="Модели" class="mt-10">
			<h2 class="t-section mb-3">Работа моделей</h2>
			<div class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
				<Tile icon={Cpu} label="Вызовов" value={String(s.models.total_calls)} level="ok" />
				<Tile icon={Zap} label="Холодные загрузки" value={pct(s.models.cold_share)} level={s.models.cold_share > 0.5 ? 'warn' : 'ok'} />
				<Tile icon={Brain} label="Ошибки JSON" value={pct(s.models.invalid_json_share, 1)} level={s.models.invalid_json_share > 0.05 ? 'warn' : 'ok'} />
				<Tile icon={Server} label="Ошибки вызова" value={pct(s.models.error_share, 1)} level={s.models.error_share > 0.05 ? 'error' : 'ok'} />
			</div>
			<BarChart label="Вызовы по типу задачи" days={s.models.calls.days} series={s.models.calls.tasks.map((x) => ({ label: x.label, values: x.values }))} />
			{#if s.models.per_model.length}
				<div class="mt-3 overflow-x-auto rounded-xl border border-line">
					<table class="w-full text-[14px]">
						<caption class="sr-only">Скорость моделей</caption>
						<thead class="t-small text-left">
							<tr><th class="px-3 py-2 font-medium">Модель</th><th class="px-3 font-medium">ток/с сред.</th><th class="px-3 font-medium">ток/с p95</th><th class="px-3 font-medium">1-й токен сред.</th><th class="px-3 font-medium">p95</th></tr>
						</thead>
						<tbody>
							{#each s.models.per_model as m (m.model)}
								<tr class="border-t border-line tabular-nums">
									<td class="px-3 py-2 font-medium">{m.model}</td><td class="px-3">{num(m.tps_avg, 1)}</td><td class="px-3">{num(m.tps_p95, 1)}</td>
									<td class="px-3">{m.ttft_avg != null ? `${num(m.ttft_avg, 2)} с` : '—'}</td><td class="px-3">{m.ttft_p95 != null ? `${num(m.ttft_p95, 2)} с` : '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<!-- 4. Pipeline -->
		<section aria-label="Пайплайн" class="mt-10">
			<h2 class="t-section mb-1">Пайплайн</h2>
			<p class="t-small mb-3">
				От приёма до отчёта: медиана {s.pipeline.latency_median_all != null ? `${num(s.pipeline.latency_median_all)} с` : '—'},
				95% быстрее {s.pipeline.latency_p95_all != null ? `${num(s.pipeline.latency_p95_all)} с` : '—'}
			</p>
			<div class="grid gap-3 md:grid-cols-2">
				<BarChart label="Медиана приём → отчёт" unit=" с" days={s.pipeline.days} series={[{ label: 'медиана', values: s.pipeline.latency_median.map((x) => x ?? 0) }]} />
				<BarChart
					label="Заметок в день"
					days={s.pipeline.days}
					series={[['text', 'текст'], ['voice', 'голос'], ['link', 'ссылки'], ['photo', 'фото'], ['forward', 'пересланные']]
						.filter(([k]) => s.pipeline.sources[k].some((x) => x))
						.map(([k, label]) => ({ label, values: s.pipeline.sources[k] }))}
				/>
				<BarChart label="Не разобрано" days={s.pipeline.days} series={[{ label: 'упало', values: s.pipeline.failed }]} />
			</div>
		</section>

		<!-- 5. Quality -->
		<section aria-label="Качество базы" class="mt-10">
			<h2 class="t-section mb-3">Качество базы</h2>
			<div class="grid gap-3 md:grid-cols-2">
				<BarChart
					label="Исправления темы по неделям (цель < 10%)"
					format={(x) => `${Math.round(x * 100)}%`}
					target={0.1}
					days={s.quality.corrections_by_week.map((w) => w.week)}
					series={[{ label: 'доля', values: s.quality.corrections_by_week.map((w) => w.share ?? 0) }]}
				/>
				<BarChart label="Заметок в базе" days={s.quality.days} series={[{ label: 'заметки', values: s.quality.notes }]} />
			</div>
			<div class="mt-3 grid gap-3 md:grid-cols-2">
				<div class="rounded-xl border border-line p-3">
					<div class="t-small mb-1">Темы без обновления сводки больше 30 дней</div>
					{#each s.quality.stale_topics.slice(0, 8) as t (t.slug)}
						<a href="/t/{t.slug}" class="block truncate py-0.5 hover:text-accent">{t.emoji} {t.name} <span class="t-small">{t.overview_updated_at ? shortDate(t.overview_updated_at) : 'сводки нет'}</span></a>
					{:else}<p class="text-success">Все сводки свежие</p>{/each}
					{#if s.quality.stale_topics.length > 8}<p class="t-small">и ещё {s.quality.stale_topics.length - 8}</p>{/if}
				</div>
				<div class="rounded-xl border border-line p-3">
					<div class="t-small mb-1">Противоречия в сущностях, не проверены</div>
					<p class="text-2xl font-semibold tabular-nums {s.quality.contradictions_to_check ? 'text-warn' : 'text-success'}">{s.quality.contradictions_to_check}</p>
					<p class="t-small"><a href="/e" class="text-accent">Открыть сущности</a></p>
				</div>
			</div>
		</section>

		<!-- 6. Energy -->
		<section aria-label="Энергия" class="mt-10">
			<h2 class="t-section mb-1">Энергия</h2>
			<p class="t-small mb-3">
				GPU пуст {pct(s.energy.gpu_empty_share)} времени{#if s.energy.priced} · за период {num(s.energy.cost.reduce((a, b) => a + b, 0), 2)} {s.energy.currency}{:else} · тарифы не заданы (ENERGY_PRICE_DAY / ENERGY_PRICE_NIGHT в .env){/if}
			</p>
			<div class="grid gap-3 md:grid-cols-2">
				<BarChart label="GPU, Вт·ч в день" days={s.energy.days} series={[{ label: 'Вт·ч', values: s.energy.wh }]} />
				{#if s.energy.priced}
					<BarChart label="Стоимость, {s.energy.currency}" days={s.energy.days} format={(x) => x.toFixed(2)} series={[{ label: s.energy.currency, values: s.energy.cost }]} />
				{/if}
			</div>
		</section>

		<!-- 7. Journal -->
		<section aria-label="Журнал" class="mt-10">
			<div class="mb-3 flex flex-wrap items-center gap-2">
				<h2 class="t-section mr-auto">Журнал</h2>
				{#each KINDS as [k, label] (k)}
					<button class="chip {kind === k ? 'chip-active' : ''}" aria-pressed={kind === k} onclick={() => filter(k)}>{label}</button>
				{/each}
			</div>
			<ul class="divide-y divide-line rounded-xl border border-line">
				{#each events as e (e.id)}
					<li class="flex gap-3 px-3 py-2 text-[14px]">
						<span class="t-small w-28 shrink-0 tabular-nums">{time.format(new Date(e.ts * 1000))}</span>
						<span class={e.kind === 'error' ? 'text-error' : ''}>{e.message}</span>
					</li>
				{:else}
					<li class="t-small px-3 py-3">Событий нет</li>
				{/each}
			</ul>
			<p class="t-small mt-2">Полный лог: <span class="t-mono">logs/bot.log</span> на сервере</p>
		</section>
	{/if}
</div>
