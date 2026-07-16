// API Client for Omni AI Gateway
import { appState } from './state.svelte';

const API_BASE = 'http://localhost:8000'; // Default backend URL

// Types matching base.py and SPEC.md
export interface Model {
    id: string;
    provider_name: string;
    model_id: string;
    display_name: string;
    supports_vision: boolean;
    supports_coding_hint: number | null; // 1-5, null until benchmarked/curated
    supports_reasoning_hint: number | null; // 1-5, null until benchmarked/curated
    context_length: number | null;
    speed_rating: number | null; // 1-5, null until benchmarked
    free: boolean;
    quality_source: 'benchmarked' | 'curated' | 'unrated';
    enabled: boolean;
    last_scanned_at: string | null;
}

// Provider slugs the backend never names in a display-friendly way (Provider.name
// is just the slug, e.g. "groq") — this is the one piece /status and the admin
// toggle list need that the backend has no data for, so it's synthesized here.
const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
    groq: 'Groq',
    gemini: 'Google Gemini API',
    openrouter: 'OpenRouter',
    pollinations: 'Pollinations',
    huggingface: 'HuggingFace Inference',
    deepseek: 'DeepSeek Platform',
    ollama: 'Ollama (local)'
};

export interface ProviderStatus {
    name: string;
    healthy: boolean;
    remaining_today: number | null;
    limit: number | null;
    reset_at: string | null;
    status: 'green' | 'yellow' | 'red';
    cooling_down_until?: string | null;
}

export interface ProviderKey {
    id: string;
    provider_name: string;
    nickname: string;
    masked_key: string; // masked form (e.g. sk-...ab12) — matches backend's ProviderKeyResponse.masked_key
    is_shared: boolean;
    added_at: string;
    last_used_at: string | null;
    daily_usage_count: number;
    daily_limit: number | null;
    health_status: 'green' | 'yellow' | 'red';
    status: 'pending' | 'active' | 'invalid_key' | 'revoked';
}

export interface KeyStatusResponse {
    status: 'pending' | 'active' | 'invalid_key';
    step: 'verifying_key' | 'discovering_models' | 'benchmarking' | 'done' | 'failed';
    error: string | null;
    models_added: number;
}

// Raw shape of GET /providers/keys/{id}/status — see DiscoveryStatusResponse
// in backend/app/api/providers.py and the DiscoveryStepName/DiscoveryOutcome
// enums in backend/app/discovery/scanner.py. Deliberately more granular
// (per-step detail) than the UI needs — mapDiscoveryStatus() below collapses
// it into the single {status, step} the polling UI actually consumes.
type DiscoveryStepStatus = 'pending' | 'in_progress' | 'done' | 'failed';
interface DiscoveryStatusResponse {
    provider_key_id: number;
    outcome: 'running' | 'success' | 'invalid_key' | 'error';
    steps: Partial<Record<'verifying_key' | 'discovering_models' | 'benchmarking', DiscoveryStepStatus>>;
    models_added: number;
    error: string | null;
}

const DISCOVERY_STEP_ORDER = ['verifying_key', 'discovering_models', 'benchmarking'] as const;

function mapDiscoveryStatus(data: DiscoveryStatusResponse): KeyStatusResponse {
    let step: KeyStatusResponse['step'];
    if (data.outcome === 'success') {
        step = 'done';
    } else if (data.outcome === 'invalid_key' || data.outcome === 'error') {
        step = 'failed';
    } else {
        // Still running: report whichever step is in_progress, or the last
        // one that finished if none currently is (brief gap between steps).
        step =
            DISCOVERY_STEP_ORDER.find(s => data.steps[s] === 'in_progress') ??
            [...DISCOVERY_STEP_ORDER].reverse().find(s => data.steps[s] === 'done') ??
            'verifying_key';
    }

    const status: KeyStatusResponse['status'] =
        data.outcome === 'success' ? 'active' : data.outcome === 'invalid_key' ? 'invalid_key' : 'pending';

    return { status, step, error: data.error, models_added: data.models_added };
}

export interface UsageRow {
    email: string;
    request_count: number;
    last_active: string;
    total_latency_ms: number;
}

// Stub mock data for fallback
const STUB_MODELS: Model[] = [
    { id: '1', provider_name: 'groq', model_id: 'llama-3.3-70b-versatile', display_name: 'Llama 3.3 70B Versatile', supports_vision: false, supports_coding_hint: 4, supports_reasoning_hint: 4, context_length: 131072, speed_rating: 5, free: true, quality_source: 'curated', enabled: true, last_scanned_at: '2026-07-15T12:00:00Z' },
    { id: '2', provider_name: 'groq', model_id: 'llama-3.2-11b-vision-preview', display_name: 'Llama 3.2 11B Vision', supports_vision: true, supports_coding_hint: 3, supports_reasoning_hint: 3, context_length: 131072, speed_rating: 5, free: true, quality_source: 'curated', enabled: true, last_scanned_at: '2026-07-15T12:00:00Z' },
    { id: '3', provider_name: 'gemini', model_id: 'gemini-1.5-flash', display_name: 'Gemini 1.5 Flash', supports_vision: true, supports_coding_hint: 4, supports_reasoning_hint: 4, context_length: 1048576, speed_rating: 4, free: true, quality_source: 'curated', enabled: true, last_scanned_at: '2026-07-15T12:10:00Z' },
    { id: '4', provider_name: 'gemini', model_id: 'gemini-1.5-pro', display_name: 'Gemini 1.5 Pro', supports_vision: true, supports_coding_hint: 5, supports_reasoning_hint: 5, context_length: 2097152, speed_rating: 3, free: true, quality_source: 'curated', enabled: true, last_scanned_at: '2026-07-15T12:10:00Z' },
    { id: '5', provider_name: 'openrouter', model_id: 'google/gemma-2-9b-it:free', display_name: 'Gemma 2 9B IT (Free)', supports_vision: false, supports_coding_hint: 3, supports_reasoning_hint: 3, context_length: 8192, speed_rating: 4, free: true, quality_source: 'curated', enabled: true, last_scanned_at: '2026-07-15T12:15:00Z' },
    { id: '6', provider_name: 'pollinations', model_id: 'openai', display_name: 'Pollinations OpenAI Chat', supports_vision: false, supports_coding_hint: 4, supports_reasoning_hint: 3, context_length: 8192, speed_rating: 4, free: true, quality_source: 'unrated', enabled: true, last_scanned_at: '2026-07-15T12:20:00Z' },
    { id: '7', provider_name: 'huggingface', model_id: 'deepseek-ai/DeepSeek-R1', display_name: 'DeepSeek-R1 (HF)', supports_vision: false, supports_coding_hint: 5, supports_reasoning_hint: 5, context_length: 32768, speed_rating: 3, free: true, quality_source: 'curated', enabled: true, last_scanned_at: '2026-07-15T12:25:00Z' },
    { id: '8', provider_name: 'deepseek', model_id: 'deepseek-chat', display_name: 'DeepSeek V3 (Platform)', supports_vision: false, supports_coding_hint: 5, supports_reasoning_hint: 4, context_length: 64000, speed_rating: 4, free: true, quality_source: 'curated', enabled: true, last_scanned_at: '2026-07-15T12:30:00Z' },
    { id: '9', provider_name: 'ollama', model_id: 'llama3:latest', display_name: 'Llama 3 (Local)', supports_vision: false, supports_coding_hint: 3, supports_reasoning_hint: 3, context_length: 8192, speed_rating: 5, free: true, quality_source: 'benchmarked', enabled: true, last_scanned_at: '2026-07-15T12:35:00Z' }
];

const STUB_STATUS: Record<string, ProviderStatus> = {
    groq: { name: 'Groq', healthy: true, remaining_today: 12400, limit: 14400, reset_at: '2026-07-16T00:00:00Z', status: 'green' },
    gemini: { name: 'Google Gemini API', healthy: true, remaining_today: 950, limit: 1500, reset_at: '2026-07-16T00:00:00Z', status: 'green' },
    openrouter: { name: 'OpenRouter', healthy: true, remaining_today: 12, limit: 50, reset_at: '2026-07-16T00:00:00Z', status: 'yellow' },
    pollinations: { name: 'Pollinations', healthy: true, remaining_today: null, limit: null, reset_at: null, status: 'green' },
    huggingface: { name: 'HuggingFace Inference', healthy: true, remaining_today: 800, limit: 1000, reset_at: '2026-07-16T00:00:00Z', status: 'green' },
    deepseek: { name: 'DeepSeek Platform', healthy: false, remaining_today: 0, limit: 1000, reset_at: '2026-07-16T00:00:00Z', status: 'red', cooling_down_until: '2026-07-15T14:30:00Z' },
    ollama: { name: 'Ollama', healthy: true, remaining_today: null, limit: null, reset_at: null, status: 'green' }
};

let STUB_KEYS: ProviderKey[] = [
    { id: 'k1', provider_name: 'groq', nickname: 'Family Groq Key', masked_key: 'gsk_...ab12', is_shared: true, added_at: '2026-07-15T10:00:00Z', last_used_at: '2026-07-15T13:20:00Z', daily_usage_count: 2000, daily_limit: 14400, health_status: 'green', status: 'active' },
    { id: 'k2', provider_name: 'gemini', nickname: 'Personal AI Studio Key', masked_key: 'AIzaSy...cd34', is_shared: false, added_at: '2026-07-15T10:05:00Z', last_used_at: '2026-07-15T13:15:00Z', daily_usage_count: 550, daily_limit: 1500, health_status: 'green', status: 'active' },
    { id: 'k3', provider_name: 'openrouter', nickname: 'Shared OpenRouter Key', masked_key: 'sk-or-v1...ef56', is_shared: true, added_at: '2026-07-15T10:10:00Z', last_used_at: '2026-07-15T13:22:00Z', daily_usage_count: 38, daily_limit: 50, health_status: 'yellow', status: 'active' }
];

let STUB_USAGE: UsageRow[] = [
    { email: 'admin@ai-gateway.local', request_count: 1450, last_active: '2026-07-15T13:24:00Z', total_latency_ms: 652000 },
    { email: 'alice@example.com', request_count: 420, last_active: '2026-07-15T13:18:00Z', total_latency_ms: 210000 },
    { email: 'bob@example.com', request_count: 110, last_active: '2026-07-15T12:55:00Z', total_latency_ms: 98000 }
];

// Thrown when the backend was reached and responded with a real error (e.g.
// wrong password). Distinct from a network/CORS-level failure, so callers can
// tell "the server rejected this" apart from "the server was unreachable" —
// only the latter should trigger a stub-data fallback.
export class ApiHttpError extends Error {
    status: number;
    constructor(message: string, status: number) {
        super(message);
        this.name = 'ApiHttpError';
        this.status = status;
    }
}

// Helper to make fetch calls with headers
async function apiRequest<T>(
    endpoint: string,
    method: 'GET' | 'POST' | 'DELETE' = 'GET',
    body: any = null
): Promise<T> {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json'
    };
    if (appState.token) {
        headers['Authorization'] = `Bearer ${appState.token}`;
    }

    const options: RequestInit = {
        method,
        headers
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
        const raw = await response.text().catch(() => '');
        let message = raw || response.statusText;
        try {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed.detail === 'string') message = parsed.detail;
        } catch {
            // Body wasn't JSON — keep the raw text as the message.
        }
        throw new ApiHttpError(message, response.status);
    }
    return response.json();
}

// Every stub fallback below runs when a live call fails (network error, CORS
// rejection, non-2xx response, etc). Flag it visibly instead of silently
// serving mock data as if it were a real response.
function flagStubFallback(context: string, err: unknown): void {
    console.error(`[api] ${context} failed — falling back to stub data`, err);
    appState.flagApiFallback(context);
}

// The gateway's JWT carries user_id/is_admin/exp (see security.py
// create_access_token) but not email — the caller already knows the email
// from the form it just submitted, so no /auth/me round trip is needed.
// Decoding client-side is safe: the server verifies the signature on every
// subsequent request, this is purely for populating local UI state.
function decodeJwtPayload(token: string): { is_admin?: boolean } | null {
    try {
        const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
        const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
        return JSON.parse(atob(padded));
    } catch {
        return null;
    }
}

export const api = {
    // Auth Endpoints
    async login(email: string, password: string): Promise<void> {
        try {
            const data = await apiRequest<{ access_token: string; token_type: string }>(
                '/auth/login',
                'POST',
                { email, password }
            );
            const payload = decodeJwtPayload(data.access_token);
            appState.login({ email, is_admin: payload?.is_admin ?? false }, data.access_token);
        } catch (err) {
            if (err instanceof ApiHttpError) {
                // Backend was reached and rejected the credentials — a real
                // failure, not something to paper over with a stub session.
                throw new Error(err.message || 'Invalid email or password');
            }
            // Network/CORS-level failure — fall back to a local stub session for offline dev.
            flagStubFallback('login', err);
            if (email.includes('@') && password.length >= 6) {
                appState.login(
                    { email, is_admin: email.startsWith('admin') },
                    'mock-jwt-token-' + Math.random().toString(36).substring(2)
                );
            } else {
                throw new Error('Invalid credentials. Password must be >= 6 characters.');
            }
        }
    },

    async redeemInvite(code: string, email: string, password: string): Promise<void> {
        try {
            const data = await apiRequest<{ access_token: string; token_type: string }>(
                '/auth/invite/redeem',
                'POST',
                { code, email, password }
            );
            const payload = decodeJwtPayload(data.access_token);
            appState.login({ email, is_admin: payload?.is_admin ?? false }, data.access_token);
        } catch (err) {
            if (err instanceof ApiHttpError) {
                // Backend was reached and rejected the invite (bad code, already
                // used, expired, email taken) — a real failure, not a stub session.
                throw new Error(err.message || 'Failed to redeem invite.');
            }
            // Network/CORS-level failure — fall back to a local stub session for offline dev.
            flagStubFallback('redeemInvite', err);
            appState.login(
                { email, is_admin: false },
                'mock-jwt-token-' + Math.random().toString(36).substring(2)
            );
        }
    },

    logout(): void {
        appState.logout();
    },

    // Models Registry
    async getModels(): Promise<Model[]> {
        try {
            return await apiRequest<Model[]>('/models');
        } catch (err) {
            flagStubFallback('getModels', err);
            return STUB_MODELS;
        }
    },

    // Provider Statuses
    async getProviderStatuses(): Promise<Record<string, ProviderStatus>> {
        try {
            // Backend's ProviderStatusEntry has everything except a display
            // name (Provider.name is just the slug) — fill that in locally.
            const data = await apiRequest<Record<string, Omit<ProviderStatus, 'name'>>>('/status');
            const withNames: Record<string, ProviderStatus> = {};
            for (const [slug, entry] of Object.entries(data)) {
                withNames[slug] = { ...entry, name: PROVIDER_DISPLAY_NAMES[slug] ?? slug };
            }
            return withNames;
        } catch (err) {
            flagStubFallback('getProviderStatuses', err);
            return STUB_STATUS;
        }
    },

    // Keys Management
    async getKeys(): Promise<ProviderKey[]> {
        try {
            return await apiRequest<ProviderKey[]>('/providers/keys');
        } catch (err) {
            flagStubFallback('getKeys', err);
            return STUB_KEYS;
        }
    },

    async addKey(provider_name: string, api_key: string, nickname: string): Promise<{ id: string }> {
        try {
            return await apiRequest<{ id: string }>('/providers/keys', 'POST', {
                provider_name,
                api_key,
                nickname
            });
        } catch (err) {
            flagStubFallback('addKey', err);
            const newId = 'k' + Math.random().toString(36).substring(2, 7);
            const mask = api_key.startsWith('sk-') ? 'sk-...' + api_key.slice(-4) : api_key.slice(0, 3) + '...' + api_key.slice(-4);
            const newKey: ProviderKey = {
                id: newId,
                provider_name,
                nickname: nickname || `${provider_name.toUpperCase()} Key`,
                masked_key: mask,
                is_shared: false,
                added_at: new Date().toISOString(),
                last_used_at: null,
                daily_usage_count: 0,
                daily_limit: provider_name === 'openrouter' ? 50 : provider_name === 'gemini' ? 1500 : 1000,
                health_status: 'green',
                status: 'pending'
            };
            STUB_KEYS = [...STUB_KEYS, newKey];
            return { id: newId };
        }
    },

    // Polling discovery status
    async getKeyDiscoveryStatus(id: string): Promise<KeyStatusResponse> {
        try {
            const data = await apiRequest<DiscoveryStatusResponse>(`/providers/keys/${id}/status`);
            return mapDiscoveryStatus(data);
        } catch (err) {
            flagStubFallback('getKeyDiscoveryStatus', err);
            // Simulate a mock progression based on date difference
            const key = STUB_KEYS.find(k => k.id === id);
            if (!key) throw new Error('Key not found');

            const diffMs = Date.now() - new Date(key.added_at).getTime();
            if (diffMs < 2000) {
                return { status: 'pending', step: 'verifying_key', error: null, models_added: 0 };
            } else if (diffMs < 4000) {
                return { status: 'pending', step: 'discovering_models', error: null, models_added: 0 };
            } else if (diffMs < 7000) {
                return { status: 'pending', step: 'benchmarking', error: null, models_added: 3 };
            } else {
                key.status = 'active';
                return { status: 'active', step: 'done', error: null, models_added: 5 };
            }
        }
    },

    async rescanKey(id: string): Promise<void> {
        try {
            await apiRequest(`/providers/keys/${id}/rescan`, 'POST');
        } catch (err) {
            flagStubFallback('rescanKey', err);
            const key = STUB_KEYS.find(k => k.id === id);
            if (key) {
                key.added_at = new Date().toISOString();
                key.status = 'pending';
            }
        }
    },

    async deleteKey(id: string): Promise<void> {
        try {
            await apiRequest(`/providers/keys/${id}`, 'DELETE');
        } catch (err) {
            flagStubFallback('deleteKey', err);
            STUB_KEYS = STUB_KEYS.filter(k => k.id !== id);
        }
    },

    // Admin Panel
    async generateInvite(): Promise<{ code: string; invite_link: string }> {
        try {
            // Backend's InviteResponse only returns {code, expires_at} — it has
            // no notion of the frontend's own origin, so the link is built here.
            const data = await apiRequest<{ code: string; expires_at: string }>(
                '/admin/invite',
                'POST'
            );
            return {
                code: data.code,
                invite_link: `${window.location.origin}/invite/${data.code}`
            };
        } catch (err) {
            flagStubFallback('generateInvite', err);
            const code = Math.random().toString(36).substring(2, 8).toUpperCase();
            return {
                code,
                invite_link: `${window.location.origin}/invite/${code}`
            };
        }
    },

    async getAdminUsage(): Promise<UsageRow[]> {
        try {
            return await apiRequest<UsageRow[]>('/admin/usage');
        } catch (err) {
            flagStubFallback('getAdminUsage', err);
            return STUB_USAGE;
        }
    },

    async toggleProvider(name: string, enabled: boolean): Promise<void> {
        try {
            const endpoint = enabled ? `/admin/provider/enable` : `/admin/provider/disable`;
            await apiRequest(endpoint, 'POST', { provider_name: name });
        } catch (err) {
            flagStubFallback('toggleProvider', err);
            const prov = STUB_STATUS[name];
            if (prov) {
                prov.healthy = enabled;
                prov.status = enabled ? 'green' : 'red';
            }
        }
    },

    // Chat completion (streaming simulation/direct call)
    async chatCompletion(
        messages: { role: string; content: string | any[] }[],
        modelId: string,
        profile: 'fast' | 'balanced' | 'quality',
        onChunk: (chunk: string) => void
    ): Promise<void> {
        try {
            const response = await fetch(`${API_BASE}/v1/chat/completions`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(appState.token ? { 'Authorization': `Bearer ${appState.token}` } : {})
                },
                body: JSON.stringify({
                    messages,
                    model: modelId,
                    stream: true,
                    profile
                })
            });

            if (!response.ok) throw new Error('API completion error');
            const reader = response.body?.getReader();
            if (!reader) throw new Error('Response is not readable');

            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    const cleanLine = line.trim();
                    if (!cleanLine) continue;
                    if (cleanLine.startsWith('data: ')) {
                        const dataStr = cleanLine.slice(6);
                        if (dataStr === '[DONE]') break;
                        try {
                            const parsed = JSON.parse(dataStr);
                            const text = parsed.choices[0]?.delta?.content || '';
                            if (text) onChunk(text);
                        } catch {
                            // ignore malformed JSON
                        }
                    }
                }
            }
        } catch (err) {
            flagStubFallback('chatCompletion', err);
            // Rich fallback stream simulation
            const model = STUB_MODELS.find(m => m.model_id === modelId) || STUB_MODELS[0];
            const sampleResponses = [
                `This is a simulated streaming response from model **${model.display_name}** managed by **${model.provider_name.toUpperCase()}** using the **${profile}** routing profile. \n\nHere is an example list of key capabilities:\n1. Speed rating: ${model.speed_rating}/5\n2. Vision support: ${model.supports_vision ? 'Yes' : 'No'}\n3. Coding support: ${model.supports_coding_hint}/5\n\nHow else can I assist you today?`,
                `Hello! I am responding via the **${model.display_name}** adapter. The Omni Gateway successfully routed your request.\n\n\`\`\`python\n# Simulated code snippet\ndef greet_gateway():\n    print("Hello from ${model.provider_name} via Omni AI Gateway!")\n\ngreet_gateway()\n\`\`\`\nLet me know if you need anything else!`,
                `I can assist you with reasoning and coding queries. As a free model, I am subject to a default limit of ${STUB_STATUS[model.provider_name]?.limit || 'unbounded'} requests/day. Let's build something great together!`
            ];
            const responseText = sampleResponses[Math.floor(Math.random() * sampleResponses.length)];
            
            // Stream chunks slowly
            const words = responseText.split(' ');
            for (let i = 0; i < words.length; i++) {
                await new Promise(resolve => setTimeout(resolve, 30 + Math.random() * 50));
                onChunk(words[i] + ' ');
            }
        }
    },

    // Image generation endpoint
    async generateImage(prompt: string, modelId?: string): Promise<{ url: string; b64_data?: string }> {
        try {
            return await apiRequest<{ url: string; b64_data?: string }>('/v1/images/generations', 'POST', {
                prompt,
                model: modelId
            });
        } catch (err) {
            flagStubFallback('generateImage', err);
            // Wait to simulate image generation
            await new Promise(resolve => setTimeout(resolve, 2000));
            // Return Pollinations AI's direct generation URL as a premium working result!
            const encodedPrompt = encodeURIComponent(prompt);
            return {
                url: `https://gen.pollinations.ai/image/${encodedPrompt}?width=512&height=512&seed=${Math.floor(Math.random() * 100000)}`
            };
        }
    }
};
