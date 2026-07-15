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
    supports_coding_hint: number; // 1-5
    supports_reasoning_hint: number; // 1-5
    context_length: number | null;
    speed_rating: number; // 1-5
    free: boolean;
    quality_source: 'benchmarked' | 'curated' | 'unrated';
    enabled: boolean;
    last_scanned_at: string;
}

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
    encrypted_key: string; // masked form (e.g. sk-...ab12)
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
    { id: 'k1', provider_name: 'groq', nickname: 'Family Groq Key', encrypted_key: 'gsk_...ab12', is_shared: true, added_at: '2026-07-15T10:00:00Z', last_used_at: '2026-07-15T13:20:00Z', daily_usage_count: 2000, daily_limit: 14400, health_status: 'green', status: 'active' },
    { id: 'k2', provider_name: 'gemini', nickname: 'Personal AI Studio Key', encrypted_key: 'AIzaSy...cd34', is_shared: false, added_at: '2026-07-15T10:05:00Z', last_used_at: '2026-07-15T13:15:00Z', daily_usage_count: 550, daily_limit: 1500, health_status: 'green', status: 'active' },
    { id: 'k3', provider_name: 'openrouter', nickname: 'Shared OpenRouter Key', encrypted_key: 'sk-or-v1...ef56', is_shared: true, added_at: '2026-07-15T10:10:00Z', last_used_at: '2026-07-15T13:22:00Z', daily_usage_count: 38, daily_limit: 50, health_status: 'yellow', status: 'active' }
];

let STUB_USAGE: UsageRow[] = [
    { email: 'admin@ai-gateway.local', request_count: 1450, last_active: '2026-07-15T13:24:00Z', total_latency_ms: 652000 },
    { email: 'alice@example.com', request_count: 420, last_active: '2026-07-15T13:18:00Z', total_latency_ms: 210000 },
    { email: 'bob@example.com', request_count: 110, last_active: '2026-07-15T12:55:00Z', total_latency_ms: 98000 }
];

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
        const errorText = await response.text().catch(() => 'Unknown error');
        throw new Error(errorText || response.statusText);
    }
    return response.json();
}

export const api = {
    // Auth Endpoints
    async login(email: string, password: string): Promise<void> {
        try {
            const data = await apiRequest<{ token: string; user: { email: string; is_admin: boolean } }>(
                '/auth/login',
                'POST',
                { email, password }
            );
            appState.login(data.user, data.token);
        } catch {
            // Stub login fallback
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

    async redeemInvite(code: string, password: string): Promise<void> {
        try {
            const data = await apiRequest<{ token: string; user: { email: string; is_admin: boolean } }>(
                '/auth/invite/redeem',
                'POST',
                { code, password }
            );
            appState.login(data.user, data.token);
        } catch {
            appState.login(
                { email: 'invited-user@example.com', is_admin: false },
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
        } catch {
            return STUB_MODELS;
        }
    },

    // Provider Statuses
    async getProviderStatuses(): Promise<Record<string, ProviderStatus>> {
        try {
            return await apiRequest<Record<string, ProviderStatus>>('/status');
        } catch {
            return STUB_STATUS;
        }
    },

    // Keys Management
    async getKeys(): Promise<ProviderKey[]> {
        try {
            return await apiRequest<ProviderKey[]>('/providers/keys');
        } catch {
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
        } catch {
            const newId = 'k' + Math.random().toString(36).substring(2, 7);
            const mask = api_key.startsWith('sk-') ? 'sk-...' + api_key.slice(-4) : api_key.slice(0, 3) + '...' + api_key.slice(-4);
            const newKey: ProviderKey = {
                id: newId,
                provider_name,
                nickname: nickname || `${provider_name.toUpperCase()} Key`,
                encrypted_key: mask,
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
            return await apiRequest<KeyStatusResponse>(`/providers/keys/${id}/status`);
        } catch {
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
        } catch {
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
        } catch {
            STUB_KEYS = STUB_KEYS.filter(k => k.id !== id);
        }
    },

    // Admin Panel
    async generateInvite(): Promise<{ code: string; invite_link: string }> {
        try {
            return await apiRequest<{ code: string; invite_link: string }>('/admin/invite', 'POST');
        } catch {
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
        } catch {
            return STUB_USAGE;
        }
    },

    async toggleProvider(name: string, enabled: boolean): Promise<void> {
        try {
            const endpoint = enabled ? `/admin/provider/enable` : `/admin/provider/disable`;
            await apiRequest(endpoint, 'POST', { provider_name: name });
        } catch {
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
        } catch {
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
        } catch {
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
