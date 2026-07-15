<script lang="ts">
	import { api, type Model } from '$lib/api';
	import { onMount } from 'svelte';

	let models = $state<Model[]>([]);
	let search = $state('');
	let providerFilter = $state('all');
	let visionFilter = $state<'all' | 'yes' | 'no'>('all');
	let freeFilter = $state<'all' | 'yes' | 'no'>('all');
	let sortBy = $state<'display_name' | 'speed_rating' | 'supports_coding_hint' | 'supports_reasoning_hint' | 'context_length'>('display_name');
	let sortOrder = $state<'asc' | 'desc'>('asc');

	onMount(async () => {
		try {
			models = await api.getModels();
		} catch (err) {
			console.error(err);
		}
	});

	// Get unique providers list
	let providers = $derived.by(() => {
		const names = new Set(models.map(m => m.provider_name));
		return ['all', ...Array.from(names)];
	});

	// Apply filtering and sorting dynamically
	let processedModels = $derived.by(() => {
		let result = [...models];

		// Apply search
		if (search.trim()) {
			const q = search.toLowerCase();
			result = result.filter(m => 
				m.display_name.toLowerCase().includes(q) || 
				m.model_id.toLowerCase().includes(q)
			);
		}

		// Apply provider filter
		if (providerFilter !== 'all') {
			result = result.filter(m => m.provider_name === providerFilter);
		}

		// Apply vision filter
		if (visionFilter !== 'all') {
			result = result.filter(m => m.supports_vision === (visionFilter === 'yes'));
		}

		// Apply free filter
		if (freeFilter !== 'all') {
			result = result.filter(m => m.free === (freeFilter === 'yes'));
		}

		// Apply sorting
		result.sort((a, b) => {
			let valA = a[sortBy] ?? 0;
			let valB = b[sortBy] ?? 0;

			if (typeof valA === 'string' && typeof valB === 'string') {
				return sortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
			}

			return sortOrder === 'asc' 
				? (valA as number) - (valB as number) 
				: (valB as number) - (valA as number);
		});

		return result;
	});

	function toggleSort(field: typeof sortBy) {
		if (sortBy === field) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortBy = field;
			sortOrder = 'desc'; // Default to highest/descending first
		}
	}
</script>

<div class="flex-1 flex flex-col gap-6">
	<!-- Page Header -->
	<div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
		<div>
			<h2 class="text-xl font-bold text-white tracking-tight">Model Registry Catalog</h2>
			<p class="text-xs text-slate-400 mt-0.5 font-sans">Curated database of active model capabilities, speed ratings, and metadata</p>
		</div>
		<span class="text-xs text-slate-500 font-semibold bg-slate-900 px-3 py-1.5 rounded-xl border border-slate-800/80">
			Active Models: {processedModels.length}
		</span>
	</div>

	<!-- Filter Controls Bar -->
	<div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 p-5 rounded-2xl bg-slate-900/40 border border-slate-800/80">
		<!-- Search -->
		<div class="flex flex-col gap-1.5">
			<label for="search" class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Search</label>
			<input
				type="text"
				id="search"
				bind:value={search}
				placeholder="Model name or ID..."
				class="w-full px-3 py-2 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
			/>
		</div>

		<!-- Provider Filter -->
		<div class="flex flex-col gap-1.5">
			<label for="provider" class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Provider</label>
			<select
				id="provider"
				bind:value={providerFilter}
				class="w-full px-3 py-2 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
			>
				{#each providers as prov}
					<option value={prov}>{prov === 'all' ? 'All Providers' : prov.toUpperCase()}</option>
				{/each}
			</select>
		</div>

		<!-- Vision Filter -->
		<div class="flex flex-col gap-1.5">
			<label for="vision" class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Vision Support</label>
			<select
				id="vision"
				bind:value={visionFilter}
				class="w-full px-3 py-2 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
			>
				<option value="all">All Models</option>
				<option value="yes">Has Vision</option>
				<option value="no">No Vision</option>
			</select>
		</div>

		<!-- Free Filter -->
		<div class="flex flex-col gap-1.5">
			<label for="free" class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Cost Type</label>
			<select
				id="free"
				bind:value={freeFilter}
				class="w-full px-3 py-2 rounded-xl bg-slate-950/40 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
			>
				<option value="all">All Models</option>
				<option value="yes">Free Tier Only</option>
				<option value="no">Paid Tier Only</option>
			</select>
		</div>
	</div>

	<!-- Catalog Grid Table -->
	<div class="border border-slate-800/80 rounded-2xl overflow-hidden bg-slate-900/40 backdrop-blur-lg">
		<div class="overflow-x-auto">
			<table class="w-full text-left border-collapse">
				<thead>
					<tr class="bg-slate-950/40 border-b border-slate-800/60 text-slate-400 text-[10px] font-bold uppercase tracking-wider">
						<th class="py-4 px-6">Model ID / Name</th>
						<th class="py-4 px-4">Provider</th>
						<th class="py-4 px-4 cursor-pointer hover:text-white transition-colors" onclick={() => toggleSort('context_length')}>
							Context Length {sortBy === 'context_length' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="py-4 px-4 cursor-pointer hover:text-white transition-colors" onclick={() => toggleSort('speed_rating')}>
							Speed Rating {sortBy === 'speed_rating' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="py-4 px-4 cursor-pointer hover:text-white transition-colors" onclick={() => toggleSort('supports_coding_hint')}>
							Coding {sortBy === 'supports_coding_hint' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="py-4 px-4 cursor-pointer hover:text-white transition-colors" onclick={() => toggleSort('supports_reasoning_hint')}>
							Reasoning {sortBy === 'supports_reasoning_hint' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="py-4 px-6 text-center">Tags</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-slate-800/60 text-xs">
					{#if processedModels.length === 0}
						<tr>
							<td colspan="7" class="py-12 text-center text-slate-500 font-medium">
								No models match the active filters.
							</td>
						</tr>
					{/if}
					{#each processedModels as model}
						<tr class="hover:bg-slate-800/20 transition-colors">
							<!-- Name -->
							<td class="py-4 px-6">
								<div class="flex flex-col">
									<span class="font-bold text-white text-sm">{model.display_name}</span>
									<span class="font-mono text-[10px] text-slate-500 mt-0.5">{model.model_id}</span>
								</div>
							</td>
							<!-- Provider -->
							<td class="py-4 px-4">
								<span class="px-2 py-1 rounded bg-slate-800 text-[10px] font-bold text-slate-300 border border-slate-700/40 uppercase">
									{model.provider_name}
								</span>
							</td>
							<!-- Context -->
							<td class="py-4 px-4 text-slate-300 font-mono">
								{model.context_length ? `${model.context_length.toLocaleString()} tokens` : 'Unknown'}
							</td>
							<!-- Speed Star Rating -->
							<td class="py-4 px-4">
								<div class="flex items-center text-amber-500 gap-0.5">
									{#each Array(5) as _, i}
										<svg class="w-3.5 h-3.5" fill={i < model.speed_rating ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.907c.961 0 1.36 1.25.588 1.81l-3.97 2.88a1 1 0 00-.364 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.97-2.88a1 1 0 00-1.176 0l-3.97 2.88c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.364-1.118l-3.97-2.88c-.78-.57-.38-1.81.588-1.81h4.907a1 1 0 00.95-.69l1.519-4.674z"/>
										</svg>
									{/each}
								</div>
							</td>
							<!-- Coding Rating -->
							<td class="py-4 px-4 text-indigo-400 font-semibold">
								{model.supports_coding_hint}/5
							</td>
							<!-- Reasoning Rating -->
							<td class="py-4 px-4 text-purple-400 font-semibold">
								{model.supports_reasoning_hint}/5
							</td>
							<!-- Tags -->
							<td class="py-4 px-6 text-center">
								<div class="flex items-center justify-center gap-1.5">
									{#if model.supports_vision}
										<span class="px-2 py-0.5 text-[9px] font-bold rounded bg-teal-500/10 text-teal-400 border border-teal-500/20">Vision</span>
									{/if}
									{#if model.free}
										<span class="px-2 py-0.5 text-[9px] font-bold rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Free</span>
									{/if}
									<span class="px-2 py-0.5 text-[9px] font-bold rounded bg-slate-800/80 text-slate-500 border border-slate-700/30 capitalize">
										{model.quality_source}
									</span>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>
