<script lang="ts">
	import { api, type ProviderStatus } from '$lib/api';
	import { onMount } from 'svelte';

	let statuses = $state<Record<string, ProviderStatus>>({});
	let loading = $state(true);

	async function fetchStatuses() {
		try {
			statuses = await api.getProviderStatuses();
		} catch (err) {
			console.error(err);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchStatuses();
		// Poll every 10 seconds for traffic-light quota updates
		const interval = setInterval(fetchStatuses, 10000);
		return () => clearInterval(interval);
	});

	// Helper to format reset time
	function formatTime(isoStr: string | null | undefined): string {
		if (!isoStr) return '';
		const d = new Date(isoStr);
		return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

<div class="flex-1 flex flex-col gap-6">
	<!-- Page Header -->
	<div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
		<div>
			<h2 class="text-xl font-bold text-white tracking-tight">Provider Status Quotas</h2>
			<p class="text-xs text-slate-400 mt-0.5">Live traffic-light health metrics and circuit-breaker cooldown trackers</p>
		</div>
		<button
			onclick={fetchStatuses}
			class="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-white transition-all duration-200"
		>
			Refresh Metrics
		</button>
	</div>

	{#if loading && Object.keys(statuses).length === 0}
		<div class="flex-1 flex items-center justify-center py-12">
			<div class="w-8 h-8 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin"></div>
		</div>
	{:else}
		<!-- Status Grid Cards -->
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
			{#each Object.entries(statuses) as [key, prov]}
				{@const pct = prov.limit && prov.remaining_today !== null ? (prov.remaining_today / prov.limit) * 100 : 100}
				
				<div class="bg-slate-900/40 border border-slate-800/80 p-6 rounded-2xl relative overflow-hidden flex flex-col gap-4">
					<!-- Glow effect matching status -->
					{#if prov.status === 'green'}
						<div class="absolute top-0 right-0 w-24 h-24 bg-emerald-500/5 rounded-full blur-2xl pointer-events-none"></div>
					{:else}
						<div class="absolute top-0 right-0 w-24 h-24 bg-red-500/5 rounded-full blur-2xl pointer-events-none"></div>
					{/if}

					<!-- Title bar -->
					<div class="flex items-center justify-between gap-3">
						<div class="flex items-center gap-3">
							<!-- Traffic light status dot -->
							<span class="relative flex h-3 w-3">
								{#if prov.status === 'green' && prov.healthy}
									<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
									<span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
								{:else if prov.status === 'yellow'}
									<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
									<span class="relative inline-flex rounded-full h-3 w-3 bg-amber-500"></span>
								{:else}
									<span class="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
								{/if}
							</span>
							<h3 class="font-extrabold text-sm text-white tracking-tight">{prov.name}</h3>
						</div>

						<span class="px-2 py-0.5 text-[9px] font-bold rounded capitalize {prov.status === 'green' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : prov.status === 'yellow' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}">
							{prov.status === 'green' ? 'healthy' : prov.status === 'yellow' ? 'near limit' : 'offline / cooling'}
						</span>
					</div>

					<!-- Quota Meter -->
					<div class="flex flex-col gap-2">
						<div class="flex justify-between items-end">
							<span class="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Remaining Quota</span>
							<span class="text-xs font-mono font-semibold text-slate-200">
								{#if prov.limit}
									{prov.remaining_today?.toLocaleString()} / {prov.limit.toLocaleString()} RPD
								{:else}
									Unlimited
								{/if}
							</span>
						</div>
						<!-- Progress bar container -->
						{#if prov.limit}
							<div class="w-full h-2 rounded-full bg-slate-950 overflow-hidden border border-slate-900">
								<div 
									class="h-full rounded-full transition-all duration-500 {prov.status === 'green' ? 'bg-gradient-to-r from-emerald-500 to-teal-500' : prov.status === 'yellow' ? 'bg-gradient-to-r from-amber-500 to-orange-500' : 'bg-red-500'}" 
									style="width: {pct}%"
								></div>
							</div>
						{:else}
							<div class="w-full h-2 rounded-full bg-slate-950 border border-slate-900 flex">
								<div class="h-full w-full rounded-full bg-gradient-to-r from-indigo-500 to-purple-500 opacity-60"></div>
							</div>
						{/if}
					</div>

					<!-- Footer status notice -->
					<div class="border-t border-slate-800/40 pt-3 mt-1 flex justify-between items-center text-[10px] text-slate-500">
						{#if prov.cooling_down_until}
							<span class="text-red-400 font-semibold flex items-center gap-1">
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
								Cooldown until {formatTime(prov.cooling_down_until)}
							</span>
						{:else if prov.reset_at}
							<span>Quota resets at: <strong class="text-slate-400 font-semibold">{formatTime(prov.reset_at)}</strong></span>
						{:else}
							<span>Always Available Fallback</span>
						{/if}
						
						<span class="font-mono text-[9px] font-semibold text-slate-600 uppercase">
							{key}
						</span>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
