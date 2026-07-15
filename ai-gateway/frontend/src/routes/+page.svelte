<script lang="ts">
	import { api, type Model } from '$lib/api';
	import { onMount } from 'svelte';

	let profile = $state<'fast' | 'balanced' | 'quality'>('balanced');
	let models = $state<Model[]>([]);
	let selectedModelId = $state<string>('');
	
	let messages = $state<Array<{ role: 'user' | 'assistant'; content: string; image?: string | null }>>([]);
	let inputText = $state('');
	let imageFile = $state<File | null>(null);
	let imagePreview = $state<string | null>(null);
	let chatContainer = $state<HTMLDivElement | null>(null);
	let loading = $state(false);

	// Load models and set defaults
	onMount(async () => {
		try {
			models = await api.getModels();
			if (models.length > 0) {
				// Select first active model as default
				const active = models.find(m => m.enabled);
				selectedModelId = active ? active.model_id : models[0].model_id;
			}
		} catch (err) {
			console.error(err);
		}
	});

	// Derived list of models for the active selection
	let filteredModels = $derived.by(() => {
		if (!models) return [];
		return models.filter(m => m.enabled);
	});

	// Trigger scroll to bottom on new messages
	$effect(() => {
		if (messages.length && chatContainer) {
			chatContainer.scrollTop = chatContainer.scrollHeight;
		}
	});

	function handleImageChange(e: Event) {
		const target = e.target as HTMLInputElement;
		if (target.files && target.files[0]) {
			const file = target.files[0];
			imageFile = file;

			const reader = new FileReader();
			reader.onload = (event) => {
				imagePreview = event.target?.result as string;
			};
			reader.readAsDataURL(file);
		}
	}

	function clearImage() {
		imageFile = null;
		imagePreview = null;
	}

	async function handleSend(e: Event) {
		e.preventDefault();
		if (!inputText.trim() && !imagePreview) return;

		const userText = inputText.trim();
		const userImage = imagePreview;

		// Add message to chat list
		messages = [...messages, { role: 'user', content: userText, image: userImage }];
		
		inputText = '';
		clearImage();
		loading = true;

		// Prepare payload messages
		const apiMessages: any[] = [];
		for (const msg of messages) {
			if (msg.image) {
				apiMessages.push({
					role: msg.role,
					content: [
						{ type: 'text', text: msg.content },
						{ type: 'image_url', image_url: msg.image }
					]
				});
			} else {
				apiMessages.push({
					role: msg.role,
					content: msg.content
				});
			}
		}

		// Add empty assistant response to stream into
		messages = [...messages, { role: 'assistant', content: '' }];
		const assistantIndex = messages.length - 1;

		try {
			await api.chatCompletion(
				apiMessages,
				selectedModelId,
				profile,
				(chunk) => {
					messages[assistantIndex].content += chunk;
					// Re-trigger Svelte state reactivity for elements in array
					messages = [...messages];
				}
			);
		} catch (err) {
			messages[assistantIndex].content = '⚠️ Error generating response. Please check gateway connection.';
			messages = [...messages];
		} finally {
			loading = false;
		}
	}

	// Handles Enter key without Shift for form submit
	function handleKeyDown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSend(e);
		}
	}
</script>

<div class="flex-1 flex flex-col h-[calc(100vh-8rem)] md:h-[calc(100vh-4rem)]">
	<!-- Top Bar / Routing Profiles -->
	<div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800/60">
		<div>
			<h2 class="text-xl font-bold text-white tracking-tight">AI Chat Gateway</h2>
			<p class="text-xs text-slate-400 mt-0.5">Route requests dynamically through free provider tiers</p>
		</div>

		<!-- Routing Profiles Picker -->
		<div class="flex items-center gap-1.5 p-1 rounded-xl bg-slate-900/60 border border-slate-800/80">
			<button 
				onclick={() => profile = 'fast'}
				class="px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition-all duration-200 {profile === 'fast' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}"
			>
				⚡ Fast
			</button>
			<button 
				onclick={() => profile = 'balanced'}
				class="px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition-all duration-200 {profile === 'balanced' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}"
			>
				⚖️ Balanced
			</button>
			<button 
				onclick={() => profile = 'quality'}
				class="px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition-all duration-200 {profile === 'quality' ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}"
			>
				💎 Best
			</button>
		</div>
	</div>

	<!-- Active Model Picker -->
	<div class="py-3 flex items-center gap-3">
		<label for="model-select" class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Target Model:</label>
		<select 
			id="model-select" 
			bind:value={selectedModelId}
			class="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
		>
			{#if filteredModels.length === 0}
				<option value="">No models available</option>
			{/if}
			{#each filteredModels as model}
				<option value={model.model_id}>
					{model.display_name} ({model.provider_name.toUpperCase()})
				</option>
			{/each}
		</select>
	</div>

	<!-- Chat Conversation Logs -->
	<div 
		bind:this={chatContainer}
		class="flex-1 overflow-y-auto py-6 space-y-6 px-2 pr-4 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent"
	>
		{#if messages.length === 0}
			<div class="h-full flex flex-col items-center justify-center text-center gap-3">
				<div class="p-4 rounded-3xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
					<svg class="w-8 h-8" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 0 1-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>
				</div>
				<h3 class="text-white font-bold text-base mt-2">Start a new conversation</h3>
				<p class="text-xs text-slate-500 max-w-sm">Enter a prompt below. Your message will be routed to the selected model using the **{profile}** profile.</p>
			</div>
		{/if}

		{#each messages as msg}
			<div class="flex gap-4 items-start {msg.role === 'user' ? 'justify-end' : ''}">
				<!-- Avatar Left -->
				{#if msg.role === 'assistant'}
					<div class="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-purple-500 flex items-center justify-center text-white text-[10px] font-bold shrink-0 shadow shadow-indigo-500/20">
						AI
					</div>
				{/if}

				<!-- Message Box -->
				<div class="max-w-[85%] rounded-2xl py-3 px-4 text-sm leading-relaxed border {msg.role === 'user' ? 'bg-indigo-600/90 border-indigo-500 text-white rounded-tr-none' : 'bg-slate-900/60 backdrop-blur border-slate-800/80 text-slate-200 rounded-tl-none'}">
					<!-- Multimodal Image Attachment -->
					{#if msg.image}
						<div class="mb-3 rounded-lg overflow-hidden border border-indigo-500/30 max-h-48">
							<img src={msg.image} alt="User attachment" class="w-full h-full object-cover" />
						</div>
					{/if}

					<!-- Text Content -->
					{#if msg.content === ''}
						<div class="flex items-center gap-1.5 py-1">
							<span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce" style="animation-delay: 0ms"></span>
							<span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce" style="animation-delay: 150ms"></span>
							<span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce" style="animation-delay: 300ms"></span>
						</div>
					{:else}
						<p class="whitespace-pre-wrap">{msg.content}</p>
					{/if}
				</div>

				<!-- Avatar Right -->
				{#if msg.role === 'user'}
					<div class="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-300 text-[10px] font-bold shrink-0">
						ME
					</div>
				{/if}
			</div>
		{/each}
	</div>

	<!-- Form inputs -->
	<div class="pt-4 border-t border-slate-800/60 flex flex-col gap-3">
		<!-- Image preview area -->
		{#if imagePreview}
			<div class="flex items-center gap-2 p-2 rounded-xl bg-slate-900/40 border border-slate-800/60 w-fit">
				<div class="w-12 h-12 rounded-lg overflow-hidden border border-slate-800 relative">
					<img src={imagePreview} alt="Upload preview" class="w-full h-full object-cover" />
					<button 
						onclick={clearImage}
						class="absolute top-0.5 right-0.5 p-0.5 rounded-full bg-black/60 hover:bg-black text-slate-400 hover:text-white"
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
					</button>
				</div>
				<span class="text-xs text-slate-400 truncate max-w-xs">{imageFile?.name}</span>
			</div>
		{/if}

		<!-- Input Box -->
		<form onsubmit={handleSend} class="flex items-end gap-3 bg-slate-900/40 border border-slate-800/80 rounded-2xl p-2 focus-within:border-indigo-500/50 transition-all duration-200">
			<!-- Image upload icon -->
			<label class="p-2.5 rounded-xl hover:bg-slate-800/50 text-slate-400 hover:text-slate-200 cursor-pointer transition-all duration-200 shrink-0">
				<input 
					type="file" 
					accept="image/*"
					class="hidden" 
					onchange={handleImageChange}
				/>
				<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
			</label>

			<!-- Textarea input -->
			<textarea 
				bind:value={inputText}
				onkeydown={handleKeyDown}
				placeholder="Message gateway..."
				rows="1"
				class="flex-1 max-h-32 min-h-[2.5rem] bg-transparent text-sm text-slate-100 placeholder-slate-600 focus:outline-none resize-none py-2 px-2"
			></textarea>

			<!-- Send button -->
			<button 
				type="submit"
				disabled={loading || (!inputText.trim() && !imagePreview)}
				id="chat-send-btn"
				class="p-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white disabled:text-slate-600 transition-all duration-200 shrink-0"
			>
				<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>
			</button>
		</form>
	</div>
</div>
