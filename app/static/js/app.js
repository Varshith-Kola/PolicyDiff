/**
 * PolicyDiff — Frontend Application (v2.0)
 *
 * Alpine.js powered SPA with:
 *  - Authentication (API key / bearer token)
 *  - XSS prevention via DOMPurify on all rendered HTML
 *  - Hash-based SPA routing (#/dashboard, #/policies, #/policy/1, #/diff/1)
 *  - Search and filtering
 *  - CSV/JSON export
 *  - Mobile responsive sidebar
 *  - Loading skeleton states
 */

function policyDiffApp() {
    return {
        // ---- Navigation / Routing ----
        currentView: 'dashboard',
        selectedPolicyId: null,
        selectedDiffId: null,
        sidebarOpen: false,

        // ---- Auth ----
        authRequired: false,
        authenticated: false,
        apiKeyInput: '',
        authError: '',
        _authToken: null,
        googleEnabled: false,

        // ---- User Profile ----
        user: null,
        showUserMenu: false,
        showPrefsModal: false,
        followedPolicyIds: new Set(),

        // ---- Data ----
        stats: null,
        policies: [],
        snapshots: [],
        diffs: [],
        timeline: [],
        currentDiff: null,
        currentPolicy: null,
        currentSnapshot: null,

        // ---- Search / Filter ----
        policySearch: '',
        diffSeverityFilter: '',

        // ---- UI State ----
        loading: false,
        pageLoading: true,
        checking: {},
        seeding: {},
        showAddModal: false,
        showSeedModal: false,
        showEditModal: false,
        toasts: [],

        // ---- Form data ----
        newPolicy: {
            name: '',
            company: '',
            url: '',
            policy_type: 'privacy_policy',
            check_interval_hours: 24,
        },
        editPolicy: {
            id: null,
            name: '',
            company: '',
            url: '',
            policy_type: 'privacy_policy',
            check_interval_hours: 24,
            is_active: true,
        },
        seedContent: '',

        // ---- Computed: filtered policies ----
        get filteredPolicies() {
            if (!this.policySearch) return this.policies;
            const q = this.policySearch.toLowerCase();
            return this.policies.filter(p =>
                p.name.toLowerCase().includes(q) ||
                p.company.toLowerCase().includes(q) ||
                p.url.toLowerCase().includes(q)
            );
        },

        // ---- Lifecycle ----
        async init() {
            // Check for OAuth callback token in URL
            const params = new URLSearchParams(globalThis.location.search);
            const oauthToken = params.get('auth_token');
            if (oauthToken) {
                this._authToken = oauthToken;
                localStorage.setItem('pd_token', oauthToken);
                this.authenticated = true;
                // Clean up URL to remove token from browser history
                globalThis.history.replaceState({}, '', '/');
            } else {
                // Restore auth token from localStorage
                this._authToken = localStorage.getItem('pd_token');
                if (this._authToken) this.authenticated = true;
            }

            // Check if auth is required
            try {
                const status = await fetch('/api/auth/status').then(r => r.json());
                this.authRequired = status.auth_enabled;
                this.googleEnabled = status.google_enabled || false;
                if (!this.authRequired) this.authenticated = true;
            } catch (e) {
                console.debug('Auth status check skipped:', e);
                this.authRequired = false;
                this.authenticated = true;
            }

            if (this.authenticated) {
                await this._loadInitialData();
            }
        },

        async _loadInitialData() {
            this.pageLoading = true;
            await Promise.all([
                this.loadDashboard(),
                this.loadPolicies(),
                this._loadUserProfile(),
            ]);
            this.pageLoading = false;
            this.handleRoute();
        },

        async _loadUserProfile() {
            try {
                this.user = await this.api('GET', '/api/auth/me');
                if (this.user?.followed_policy_ids) {
                    this.followedPolicyIds = new Set(this.user.followed_policy_ids);
                }
            } catch (error_) {
                // User profile not available (API key auth or auth disabled)
                console.debug('User profile not available:', error_);
                this.user = null;
            }
        },

        // ---- Auth ----
        async loginWithKey() {
            this.authError = '';
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: this.apiKeyInput }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this.authError = err.detail || 'Authentication failed';
                    return;
                }
                const data = await res.json();
                this._authToken = data.token;
                localStorage.setItem('pd_token', data.token);
                this.authenticated = true;
                this.apiKeyInput = '';
                await this._loadInitialData();
            } catch (e) {
                console.debug('Login error:', e);
                this.authError = 'Connection error';
            }
        },

        loginWithGoogle() {
            globalThis.location.href = '/api/auth/google/login';
        },

        logout() {
            this._authToken = null;
            this.authenticated = false;
            this.user = null;
            this.followedPolicyIds = new Set();
            localStorage.removeItem('pd_token');
        },

        // ---- SPA Hash Routing ----
        handleRoute() {
            const hash = globalThis.location.hash || '#/dashboard';
            const parts = hash.replace('#/', '').split('/');
            const view = parts[0] || 'dashboard';
            const id = parts[1] ? Number.parseInt(parts[1], 10) : null;

            if (view === 'dashboard') {
                this.currentView = 'dashboard';
                this.loadDashboard();
            } else if (view === 'policies') {
                this.currentView = 'policies';
                this.loadPolicies();
            } else if (view === 'policy' && id) {
                this.currentView = 'policy-detail';
                this.selectedPolicyId = id;
                this.loadPolicyDetail(id);
            } else if (view === 'diff' && id) {
                this.currentView = 'diff-detail';
                this.selectedDiffId = id;
                this.loadDiffDetail(id);
            } else {
                this.currentView = 'dashboard';
            }
        },

        navigate(view, id = null) {
            this.sidebarOpen = false;
            if (view === 'dashboard') {
                globalThis.location.hash = '#/dashboard';
            } else if (view === 'policies') {
                globalThis.location.hash = '#/policies';
            } else if (view === 'policy-detail' && id) {
                globalThis.location.hash = `#/policy/${id}`;
            } else if (view === 'diff-detail' && id) {
                globalThis.location.hash = `#/diff/${id}`;
            }
        },

        // ---- API Helpers ----
        async api(method, path, body = null) {
            const headers = { 'Content-Type': 'application/json' };
            if (this._authToken) {
                headers['Authorization'] = `Bearer ${this._authToken}`;
            }
            const opts = { method, headers };
            if (body) opts.body = JSON.stringify(body);
            const res = await fetch(path, opts);

            // Handle auth failures
            if (res.status === 401) {
                this.authenticated = false;
                this._authToken = null;
                localStorage.removeItem('pd_token');
                throw new Error('Session expired. Please log in again.');
            }

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Request failed' }));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            if (res.status === 204) return null;
            return res.json();
        },

        // ---- Dashboard ----
        async loadDashboard() {
            try {
                this.stats = await this.api('GET', '/api/dashboard/stats');
            } catch (e) {
                console.error('Dashboard load error:', e);
                this.toast('Failed to load dashboard', 'error');
            }
        },

        // ---- Policies ----
        async loadPolicies() {
            try {
                this.policies = await this.api('GET', '/api/policies');
            } catch (e) {
                console.error('Policies load error:', e);
                this.toast('Failed to load policies', 'error');
            }
        },

        async addPolicy() {
            try {
                this.loading = true;
                await this.api('POST', '/api/policies', this.newPolicy);
                this.showAddModal = false;
                this.newPolicy = { name: '', company: '', url: '', policy_type: 'privacy_policy', check_interval_hours: 24 };
                await this.loadPolicies();
                await this.loadDashboard();
                this.toast('Policy added! Wayback Machine seeding started in background.', 'success');
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.loading = false;
            }
        },

        async deletePolicy(id) {
            if (!confirm('Delete this policy and all its history?')) return;
            try {
                await this.api('DELETE', `/api/policies/${id}`);
                await this.loadPolicies();
                await this.loadDashboard();
                if (this.currentView === 'policy-detail') this.navigate('policies');
                this.toast('Policy deleted', 'success');
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        async togglePolicy(id, active) {
            try {
                await this.api('PUT', `/api/policies/${id}`, { is_active: !active });
                await this.loadPolicies();
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        // ---- Edit Policy ----
        openEditModal(policy) {
            this.editPolicy = {
                id: policy.id,
                name: policy.name,
                company: policy.company,
                url: policy.url,
                policy_type: policy.policy_type,
                check_interval_hours: policy.check_interval_hours,
                is_active: policy.is_active,
            };
            this.showEditModal = true;
        },

        async savePolicy() {
            try {
                this.loading = true;
                const { id, ...data } = this.editPolicy;
                await this.api('PUT', `/api/policies/${id}`, data);
                this.showEditModal = false;
                await this.loadPolicies();
                if (this.currentView === 'policy-detail') {
                    await this.loadPolicyDetail(id);
                }
                this.toast('Policy updated', 'success');
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.loading = false;
            }
        },

        // ---- Check Now ----
        async checkNow(policyId) {
            this.checking[policyId] = true;
            try {
                const result = await this.api('POST', `/api/policies/${policyId}/check`);
                this.toast(result.message, result.status === 'error' ? 'error' : 'success');
                await this.loadPolicies();
                await this.loadDashboard();
                if (this.currentView === 'policy-detail') {
                    await this.loadPolicyDetail(policyId);
                }
                if (result.diff_id) {
                    this.navigate('diff-detail', result.diff_id);
                }
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.checking[policyId] = false;
            }
        },

        async checkAll() {
            this.loading = true;
            try {
                const result = await this.api('POST', '/api/check-all');
                const changes = result.results.filter(r => r.status === 'changed').length;
                this.toast(`Checked ${result.total} policies — ${changes} changes found`, 'success');
                await this.loadPolicies();
                await this.loadDashboard();
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.loading = false;
            }
        },

        // ---- Wayback Seed ----
        async seedWayback(policyId) {
            this.seeding[policyId] = true;
            try {
                const result = await this.api('POST', `/api/policies/${policyId}/seed-wayback`);
                this.toast(result.message, 'success');
                this._pollSeedStatus(policyId);
            } catch (e) {
                this.toast(e.message, 'error');
                this.seeding[policyId] = false;
            }
        },

        async _pollSeedStatus(policyId) {
            const poll = async () => {
                try {
                    const policy = await this.api('GET', `/api/policies/${policyId}`);
                    if (policy.seed_status === 'seeding') {
                        setTimeout(poll, 5000);
                    } else {
                        this.seeding[policyId] = false;
                        await this.loadPolicies();
                        if (this.currentView === 'policy-detail' && this.selectedPolicyId === policyId) {
                            await this.loadPolicyDetail(policyId);
                        }
                        if (policy.seed_status === 'seeded') {
                            this.toast('Wayback Machine seeding complete!', 'success');
                        } else {
                            this.toast('Wayback seeding finished (no new snapshots found)', 'info');
                        }
                    }
                } catch (e) {
                    console.debug('Seed poll error:', e);
                    this.seeding[policyId] = false;
                }
            };
            setTimeout(poll, 3000);
        },

        // ---- Policy Detail ----
        async loadPolicyDetail(id) {
            try {
                const [policy, snaps, dfs, tl] = await Promise.all([
                    this.api('GET', `/api/policies/${id}`),
                    this.api('GET', `/api/policies/${id}/snapshots`),
                    this.api('GET', `/api/policies/${id}/diffs`),
                    this.api('GET', `/api/policies/${id}/timeline`),
                ]);
                this.currentPolicy = policy;
                this.snapshots = snaps;
                this.diffs = dfs;
                this.timeline = tl;
            } catch (e) {
                console.error('Policy detail load error:', e);
                this.toast('Failed to load policy details', 'error');
            }
        },

        // ---- Diff Detail ----
        async loadDiffDetail(id) {
            try {
                this.currentDiff = await this.api('GET', `/api/diffs/${id}`);
            } catch (e) {
                console.error('Diff load error:', e);
                this.toast('Failed to load diff', 'error');
            }
        },

        // ---- Seed Snapshot ----
        async seedSnapshot(policyId) {
            if (!this.seedContent.trim()) {
                this.toast('Please paste the policy content', 'error');
                return;
            }
            try {
                this.loading = true;
                await this.api('POST', `/api/policies/${policyId}/snapshots/seed`, {
                    content: this.seedContent,
                });
                this.showSeedModal = false;
                this.seedContent = '';
                await this.loadPolicyDetail(policyId);
                this.toast('Historical snapshot seeded!', 'success');
            } catch (e) {
                this.toast(e.message, 'error');
            } finally {
                this.loading = false;
            }
        },

        // ---- View Snapshot ----
        async viewSnapshot(policyId, snapshotId) {
            try {
                this.currentSnapshot = await this.api('GET', `/api/policies/${policyId}/snapshots/${snapshotId}`);
            } catch (e) {
                console.error('Snapshot load error:', e);
                this.toast('Failed to load snapshot', 'error');
            }
        },

        closeSnapshot() {
            this.currentSnapshot = null;
        },

        // ---- Follow / Unfollow ----
        isFollowing(policyId) {
            return this.followedPolicyIds.has(policyId);
        },

        async toggleFollow(policyId) {
            if (!this.user) {
                this.toast('Sign in with Google to follow policies', 'info');
                return;
            }
            try {
                if (this.isFollowing(policyId)) {
                    await this.api('DELETE', `/api/auth/me/follow/${policyId}`);
                    this.followedPolicyIds.delete(policyId);
                    this.toast('Unfollowed policy', 'info');
                } else {
                    await this.api('POST', '/api/auth/me/follow', { policy_id: policyId });
                    this.followedPolicyIds.add(policyId);
                    this.toast('Following! You\'ll get email alerts for changes.', 'success');
                }
                // Force reactivity
                this.followedPolicyIds = new Set(this.followedPolicyIds);
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        // ---- Email Preferences ----
        async loadEmailPrefs() {
            if (!this.user) return;
            try {
                const prefs = await this.api('GET', '/api/auth/me/email-preferences');
                this.user.email_preferences = prefs;
            } catch (error_) {
                console.debug('Could not load email preferences:', error_);
            }
        },

        async saveEmailPrefs() {
            try {
                const prefs = this.user?.email_preferences || {};
                await this.api('PUT', '/api/auth/me/email-preferences', {
                    email_enabled: prefs.email_enabled,
                    frequency: prefs.frequency,
                    severity_threshold: prefs.severity_threshold,
                });
                this.toast('Email preferences saved', 'success');
                this.showPrefsModal = false;
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        async unsubscribeAll() {
            try {
                await this.api('POST', '/api/auth/me/unsubscribe');
                if (this.user?.email_preferences) {
                    this.user.email_preferences.email_enabled = false;
                }
                this.toast('Unsubscribed from all email notifications', 'info');
                this.showPrefsModal = false;
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        // ---- GDPR ----
        async exportMyData() {
            try {
                const data = await this.api('GET', '/api/auth/me/export');
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'policydiff_my_data.json';
                a.click();
                URL.revokeObjectURL(a.href);
                this.toast('Data exported', 'success');
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        async deleteMyAccount() {
            if (!confirm('Are you sure? This will permanently delete your account and all data. This cannot be undone.')) return;
            try {
                await this.api('DELETE', '/api/auth/me/account');
                this.toast('Account deleted', 'info');
                this.logout();
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        // ---- Export ----
        async exportDiffs(format = 'csv') {
            try {
                const headers = {};
                if (this._authToken) headers['Authorization'] = `Bearer ${this._authToken}`;

                let url = `/api/export/diffs?format=${format}`;
                if (this.selectedPolicyId) url += `&policy_id=${this.selectedPolicyId}`;
                if (this.diffSeverityFilter) url += `&severity=${this.diffSeverityFilter}`;

                const res = await fetch(url, { headers });
                if (!res.ok) throw new Error('Export failed');

                const blob = await res.blob();
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = `policydiff_export.${format}`;
                a.click();
                URL.revokeObjectURL(a.href);
                this.toast(`Exported as ${format.toUpperCase()}`, 'success');
            } catch (e) {
                this.toast(e.message, 'error');
            }
        },

        // ---- Utility ----
        toast(message, type = 'info') {
            const id = Date.now() + Math.random();
            this.toasts.push({ id, message, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 4000);
        },

        severityColor(severity) {
            const colors = {
                'informational': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
                'concerning': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
                'action-needed': 'bg-red-500/20 text-red-400 border-red-500/30',
            };
            return colors[severity] || colors['informational'];
        },

        severityDot(severity) {
            const colors = {
                'informational': 'bg-blue-400',
                'concerning': 'bg-amber-400',
                'action-needed': 'bg-red-400',
            };
            return colors[severity] || colors['informational'];
        },

        seedStatusColor(status) {
            const map = {
                'none': 'bg-slate-700 text-slate-400',
                'seeding': 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
                'seeded': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
                'seed_failed': 'bg-red-500/20 text-red-400 border-red-500/30',
            };
            return map[status] || map['none'];
        },

        seedStatusLabel(status) {
            const map = {
                'none': '',
                'seeding': 'Seeding...',
                'seeded': 'History Seeded',
                'seed_failed': 'Seed Failed',
            };
            return map[status] || '';
        },

        formatDate(dateStr) {
            if (!dateStr) return 'Never';
            const d = new Date(dateStr);
            return d.toLocaleString(undefined, {
                month: 'short', day: 'numeric', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
                timeZoneName: 'short',
            });
        },

        relativeTime(dateStr) {
            if (!dateStr) return 'Never';
            const d = new Date(dateStr);
            const now = new Date();
            const diff = now - d;
            const mins = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);
            if (mins < 1) return 'Just now';
            if (mins < 60) return `${mins}m ago`;
            if (hours < 24) return `${hours}h ago`;
            if (days < 30) return `${days}d ago`;
            return this.formatDate(dateStr);
        },

        policyTypeLabel(type) {
            return type === 'privacy_policy' ? 'Privacy Policy' : 'Terms of Service';
        },

        parseKeyChanges(json_str) {
            try { return JSON.parse(json_str || '[]'); } catch (error_) { console.debug('parseKeyChanges:', error_); return []; }
        },

        parseClauses(json_str) {
            try { return JSON.parse(json_str || '[]'); } catch (error_) { console.debug('parseClauses:', error_); return []; }
        },

        parseLinks(json_str) {
            try { return JSON.parse(json_str || '[]'); } catch (error_) { console.debug('parseLinks:', error_); return []; }
        },

        /**
         * Render markdown as sanitized HTML.
         * Uses marked.js for rendering and DOMPurify for XSS prevention.
         */
        renderMarkdown(text) {
            const raw = policyDiffRenderMarkdown(text);
            if (typeof DOMPurify !== 'undefined') {
                return DOMPurify.sanitize(raw, {
                    ADD_TAGS: ['table', 'thead', 'tbody', 'tr', 'th', 'td'],
                    ADD_ATTR: ['target', 'rel', 'id', 'class', 'style'],
                });
            }
            return raw;
        },

        /**
         * Sanitize arbitrary HTML (e.g. diff_html from the API).
         */
        sanitizeHtml(html) {
            if (typeof DOMPurify !== 'undefined') {
                return DOMPurify.sanitize(html || '', {
                    ADD_TAGS: ['table', 'thead', 'tbody', 'tr', 'th', 'td', 'del', 'ins'],
                    ADD_ATTR: ['class', 'style', 'id'],
                });
            }
            return html || '';
        },
    };
}
