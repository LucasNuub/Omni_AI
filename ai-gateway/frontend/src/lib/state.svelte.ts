// App State Management using Svelte 5 Runes

export class AppState {
    user = $state<{ email: string; is_admin: boolean } | null>(null);
    token = $state<string | null>(null);
    initialized = $state<boolean>(false);

    constructor() {
        if (typeof window !== 'undefined') {
            const savedToken = localStorage.getItem('token');
            const savedUser = localStorage.getItem('user');
            if (savedToken && savedUser) {
                this.token = savedToken;
                try {
                    this.user = JSON.parse(savedUser);
                } catch {
                    this.user = null;
                }
            }
            this.initialized = true;
        }
    }

    login(user: { email: string; is_admin: boolean }, token: string) {
        this.user = user;
        this.token = token;
        localStorage.setItem('token', token);
        localStorage.setItem('user', JSON.stringify(user));
    }

    logout() {
        this.user = null;
        this.token = null;
        localStorage.removeItem('token');
        localStorage.removeItem('user');
    }
}

export const appState = new AppState();
