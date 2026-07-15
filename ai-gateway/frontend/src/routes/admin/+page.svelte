<script lang="ts">
	import { api, type UsageRow, type ProviderStatus } from '$lib/api';
	import { onMount } from 'svelte';

	let inviteCode = $state<string | null>(null);
	let inviteLink = $state<string | null>(null);
	let copying = $state(false);

	let usageData = $state<UsageRow[]>([]);
	let providerStatuses = $state<Record<string, ProviderStatus>>({});
	
	let loadingUsage = $state(true);
	let loadingProviders = $state(true);

	async function fetchAdminData() {
		try {
			usageData = await api.getAdminUsage();
		} catch (err) {
			console.error(err);
		} finally {
			loadingUsage = false;
		}

		try {
			providerStatuses = await api.getProviderStatuses();
		} catch (err) {
			console.error(err);
		} finally {
			loadingProviders = false;
		}
	}

	onMount(() => {
		fetchAdminData();
	});

	async function handleGenerateInvite() {
		try {
			const res = await api.generateInvite();
			inviteCode = res.code;
			inviteLink = res.invite_link;
		} catch (err) {
			console.error(err);
		}
	}

	async function copyLink() {
		if (!inviteLink) return;
		copying = true;
		try {
			await navigator.clipboard.writeText(inviteLink);
			setTimeout(() => copying = false, 1500);
		} catch {
			copying = false;
		}
	}

	async function toggleProviderState(name: string, currentHealthy: boolean) {
		const newEnabledState = !currentHealthy;
		try {
			await api.toggleProvider(name, newEnabledState);
			// Refresh provider statuses list locally
			providerStatuses = await api.getProviderStatuses();
		} catch (err) {
			console.error(err);
		}
	}
</script>

<div class="flex-1 flex flex-col gap-8">
	<!-- Page Header -->
	<div>
		<h2 class="text-xl font-bold text-white tracking-tight">Admin Administration Dashboard</h2>
		<p class="text-xs text-slate-400 mt-0.5">Generate client invites, audit usage metrics, and disable/enable gateway providers</p>
	</div>

	<!-- Top Grid: Invite Generator & Provider Toggles -->
	<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
		<!-- Invite Code Generator -->
		<div class="bg-slate-900/40 border border-slate-800/80 p-6 rounded-2xl flex flex-col gap-5">
			<h3 class="text-sm font-extrabold text-white tracking-tight flex items-center gap-2">
				<span class="p-1 rounded-lg bg-indigo-500/10 text-indigo-400">
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
				</span>
				Generate Invite Link
			</h3>
			<p class="text-xs text-slate-500">Create a unique, single-use registration URL. Invites allow friends and family to sign up without open registration.</p>

			<div class="flex flex-col gap-4 mt-2">
				<button
					onclick={handleGenerateInvite}
					id="admin-generate-invite-btn"
					class="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm shadow-lg shadow-indigo-600/10 active:scale-[0.98] transition-all duration-200"
				>
					Generate Single-Use Link
				</button>

				{#if inviteCode}
					<div class="p-4 rounded-xl border bg-slate-950/20 border-slate-800 flex items-center justify-between gap-4">
						<div class="min-w-0 flex-1">
							<span class="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Invite Link:</span>
							<p class="text-xs text-indigo-400 font-mono font-medium truncate mt-0.5">{inviteLink}</p>
						</div>
						<button
							onclick={copyLink}
							class="px-3 py-1.5 rounded-lg border border-slate-800 hover:border-indigo-500/30 text-[10px] font-semibold text-slate-300 hover:text-indigo-400 transition-all duration-200 shrink-0"
						>
							{copying ? 'Copied!' : 'Copy'}
						</button>
					</div>
				{/if}
			</div>
		</div>

		<!-- Provider State Controllers -->
		<div class="bg-slate-900/40 border border-slate-800/80 p-6 rounded-2xl flex flex-col gap-4">
			<h3 class="text-sm font-extrabold text-white tracking-tight flex items-center gap-2">
				<span class="p-1 rounded-lg bg-indigo-500/10 text-indigo-400">
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/></svg>
				</span>
				Provider Override Controls
			</h3>
			<p class="text-xs text-slate-500">Manually disable providers to redirect gateway traffic elsewhere, bypassing automatic circuit breakers.</p>

			<div class="flex-1 overflow-y-auto space-y-2.5 max-h-56 pr-2 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent mt-2">
				{#if loadingProviders && Object.keys(providerStatuses).length === 0}
					<p class="text-xs text-slate-600 text-center py-6">Loading providers list...</p>
				{/if}
				{#each Object.entries(providerStatuses) as [key, prov]}
					<div class="flex items-center justify-between p-3 rounded-xl border bg-slate-950/10 border-slate-800/80">
						<div>
							<h4 class="text-xs font-bold text-white">{prov.name}</h4>
							<span class="text-[9px] font-semibold text-slate-500 uppercase tracking-wider">{key}</span>
						</div>
						<!-- Toggle Switch -->
						<button
							onclick={() => toggleProviderState(key, prov.healthy)}
							class="w-12 h-6 rounded-full p-0.5 transition-all duration-300 relative {prov.healthy ? 'bg-indigo-600' : 'bg-slate-800'}"
							aria-label="Toggle provider"
						>
							<div class="w-5 h-5 rounded-full bg-white shadow-md transition-transform duration-300 transform {prov.healthy ? 'translate-x-6' : 'translate-x-0'}"></div>
						</button>
					</div>
				{/each}
			</div>
		</div>
	</div>

	<!-- Bottom Section: User Usage analytics table -->
	<div class="bg-slate-900/40 border border-slate-800/80 rounded-2xl overflow-hidden flex flex-col">
		<div class="p-6 border-b border-slate-800/60 bg-slate-950/20">
			<h3 class="text-sm font-extrabold text-white tracking-tight flex items-center gap-2">
				<span class="p-1 rounded-lg bg-indigo-500/10 text-indigo-400">
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
				</span>
				Per-User Usage Metrics (Today)
			</h3>
		</div>

		<div class="overflow-x-auto">
			<table class="w-full text-left border-collapse">
				<thead>
					<tr class="bg-slate-950/20 border-b border-slate-800/60 text-slate-400 text-[10px] font-bold uppercase tracking-wider">
						<th class="py-4 px-6">User Account</th>
						<th class="py-4 px-4 text-center">Requests Today</th>
						<th class="py-4 px-4">Accumulated Latency</th>
						<th class="py-4 px-4">Average Latency (per Req)</th>
						<th class="py-4 px-6 text-right">Last Session Active</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-slate-800/60 text-xs">
					{#if loadingUsage && usageData.length === 0}
						<tr>
							<td colspan="5" class="py-12 text-center text-slate-500 font-medium">
								Retrieving gateway logs...
							</td>
						</tr>
					{:else if usageData.length === 0}
						<tr>
							<td colspan="5" class="py-12 text-center text-slate-500 font-medium">
								No user activity logged today.
							</td>
						</tr>
					{/if}
					{#each usageData as row}
						{@const avgLatency = row.request_count > 0 ? Math.round(row.total_latency_ms / row.request_count) : 0}
						<tr class="hover:bg-slate-800/10 transition-colors">
							<!-- Email -->
							<td class="py-4 px-6 font-semibold text-white">
								{row.email}
							</td>
							<!-- Requests -->
							<td class="py-4 px-4 text-center font-mono text-slate-200">
								{row.request_count.toLocaleString()}
							</td>
							<!-- Latency -->
							<td class="py-4 px-4 font-mono text-slate-400">
								{(row.total_latency_ms / 1000).toFixed(2)}s
							</td>
							<!-- Avg Latency -->
							<td class="py-4 px-4 font-mono text-slate-400">
								{avgLatency}ms
							</td>
							<!-- Last Active -->
							<td class="py-4 px-6 text-right text-slate-500">
								{new Date(row.last_active).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} ({new Date(row.last_active).toLocaleDateString()})
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>
