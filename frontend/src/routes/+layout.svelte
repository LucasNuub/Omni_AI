<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { appState } from '$lib/state.svelte';
	import { onMount } from 'svelte';

	let { children } = $props();

	let mobileMenuOpen = $state(false);

	// Navigation links list
	const navLinks = [
		{ href: '/', label: 'Chat', icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 0 1-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' },
		{ href: '/compare', label: 'Compare', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2zM17 5h-2a2 2 0 00-2 2v12a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2z' },
		{ href: '/models', label: 'Model Registry', icon: 'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4' },
		{ href: '/providers', label: 'Provider Status', icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z' },
		{ href: '/settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065zM15 12a3 3 0 11-6 0 3 3 0 016 0z' }
	];

	// Auth check and redirection
	$effect(() => {
		if (appState.initialized) {
			const isAuthRoute = $page.url.pathname.startsWith('/login') || $page.url.pathname.startsWith('/invite');
			if (!appState.user && !isAuthRoute) {
				goto('/login');
			} else if (appState.user && isAuthRoute) {
				goto('/');
			}
		}
	});

	function handleLogout() {
		appState.logout();
		goto('/login');
	}
</script>

<svelte:head>
	<title>Omni AI Gateway</title>
	<meta name="description" content="One gateway, all free AI providers. Self-healing, resilient, OpenAI-compatible." />
	<link rel="icon" href={favicon} />
</svelte:head>

{#if appState.apiDegraded}
	<div class="fixed top-0 inset-x-0 z-[100] bg-amber-500 text-black text-sm font-semibold px-4 py-2 flex items-center justify-center gap-4 shadow-lg">
		<span>⚠ Live API unreachable (last failure: {appState.lastApiFailure}) — showing simulated/stub data, not a real response.</span>
		<button
			onclick={() => appState.clearApiFallback()}
			class="underline hover:no-underline shrink-0"
		>
			Dismiss
		</button>
	</div>
{/if}

{#if !appState.initialized}
	<div class="fixed inset-0 bg-[#0b0f19] flex items-center justify-center">
		<div class="flex flex-col items-center gap-4">
			<div class="w-12 h-12 rounded-full border-4 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
			<p class="text-indigo-400 font-medium tracking-wide animate-pulse">Initializing Gateway...</p>
		</div>
	</div>
{:else if !appState.user && (!$page.url.pathname.startsWith('/login') && !$page.url.pathname.startsWith('/invite'))}
	<div class="fixed inset-0 bg-[#0b0f19] flex items-center justify-center">
		<p class="text-slate-400">Redirecting to login...</p>
	</div>
{:else if !appState.user}
	<!-- Login/Invite Full-screen Routes -->
	<main class="min-h-screen flex items-center justify-center px-4 relative overflow-hidden">
		<!-- Background Glows -->
		<div class="absolute top-1/4 left-1/4 w-96 h-96 bg-indigo-500/10 rounded-full blur-[100px] pointer-events-none"></div>
		<div class="absolute bottom-1/4 right-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-[100px] pointer-events-none"></div>
		
		<div class="w-full max-w-md relative z-10">
			{@render children()}
		</div>
	</main>
{:else}
	<!-- Full Layout App Shell -->
	<div class="min-h-screen flex flex-col md:flex-row bg-[#080b11] relative overflow-hidden">
		<!-- Mesh background grid overlay -->
		<div class="absolute inset-0 bg-[linear-gradient(to_right,#0f172a_1px,transparent_1px),linear-gradient(to_bottom,#0f172a_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-40 pointer-events-none"></div>

		<!-- Mobile Header -->
		<header class="md:hidden flex items-center justify-between px-6 py-4 bg-[#0b0f19]/80 backdrop-blur-lg border-b border-slate-800/80 sticky top-0 z-50">
			<a href="/" class="flex items-center gap-2">
				<span class="p-2 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-500 text-white shadow-lg shadow-indigo-500/20">
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
				</span>
				<span class="font-bold text-lg bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">Omni AI</span>
			</a>
			<button class="text-slate-300 hover:text-white focus:outline-none p-1 rounded-lg hover:bg-slate-800/50" onclick={() => mobileMenuOpen = !mobileMenuOpen} id="mobile-menu-btn">
				<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					{#if mobileMenuOpen}
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
					{:else}
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
					{/if}
				</svg>
			</button>
		</header>

		<!-- Sidebar Container -->
		<aside class="fixed inset-y-0 left-0 transform md:relative md:translate-x-0 w-64 bg-[#0b0f19]/90 md:bg-[#0b0f19]/60 backdrop-blur-xl border-r border-slate-800/80 py-8 px-6 flex flex-col justify-between z-40 transition-transform duration-300 ease-in-out {mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'} md:flex">
			<div class="flex flex-col gap-8">
				<!-- Brand Header -->
				<a href="/" class="flex items-center gap-3 px-2">
					<span class="p-2.5 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-500 text-white shadow-lg shadow-indigo-500/20">
						<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
					</span>
					<div>
						<h1 class="font-extrabold text-xl bg-gradient-to-r from-indigo-200 via-indigo-400 to-purple-400 bg-clip-text text-transparent tracking-tight">Omni</h1>
						<p class="text-[10px] text-slate-500 tracking-wider font-semibold uppercase">AI Gateway</p>
					</div>
				</a>

				<!-- Navigation -->
				<nav class="flex flex-col gap-1.5" id="sidebar-nav">
					{#each navLinks as link}
						{@const isActive = $page.url.pathname === link.href}
						<a 
							href={link.href} 
							onclick={() => mobileMenuOpen = false}
							class="flex items-center gap-3 px-4 py-3 rounded-xl font-medium text-sm transition-all duration-200 {isActive ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}"
						>
							<svg class="w-5 h-5 opacity-80" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" d={link.icon} />
							</svg>
							{link.label}
						</a>
					{/each}

					<!-- Admin Panel Link (Conditional) -->
					{#if appState.user?.is_admin}
						{@const isActive = $page.url.pathname === '/admin'}
						<a 
							href="/admin" 
							onclick={() => mobileMenuOpen = false}
							class="flex items-center gap-3 px-4 py-3 rounded-xl font-medium text-sm transition-all duration-200 {isActive ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}"
						>
							<svg class="w-5 h-5 opacity-80" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
							</svg>
							Admin Panel
						</a>
					{/if}
				</nav>
			</div>

			<!-- User Footer -->
			<div class="border-t border-slate-800/60 pt-6 flex flex-col gap-4">
				<div class="flex items-center gap-3 px-2">
					<div class="w-9 h-9 rounded-full bg-slate-800 flex items-center justify-center text-xs font-semibold text-indigo-400 border border-slate-700/60">
						{appState.user?.email.slice(0, 2).toUpperCase()}
					</div>
					<div class="flex-1 min-w-0">
						<p class="text-xs font-medium text-slate-300 truncate">{appState.user?.email}</p>
						<p class="text-[10px] text-slate-500 font-semibold">{appState.user?.is_admin ? 'Administrator' : 'User'}</p>
					</div>
				</div>
				<button 
					onclick={handleLogout}
					class="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-slate-800 hover:border-red-500/30 text-slate-400 hover:text-red-400 hover:bg-red-500/5 text-xs font-medium transition-all duration-200"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
					Sign Out
				</button>
			</div>
		</aside>

		<!-- Mobile Backdrop -->
		{#if mobileMenuOpen}
			<button 
				class="fixed inset-0 bg-[#080b11]/60 backdrop-blur-sm z-30 md:hidden focus:outline-none"
				onclick={() => mobileMenuOpen = false}
			></button>
		{/if}

		<!-- Page Content -->
		<main class="flex-1 flex flex-col min-h-screen relative z-10 w-full overflow-y-auto">
			<div class="flex-1 px-4 py-6 md:p-8 max-w-7xl w-full mx-auto flex flex-col">
				{@render children()}
			</div>
		</main>
	</div>
{/if}
