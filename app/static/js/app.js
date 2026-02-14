/**
 * PolicyDiff — Frontend Application
 * Alpine.js powered SPA with full dashboard functionality
 */

function policyDiffApp() {
    return {
        // Navigation
        currentView: 'dashboard',
        selectedPolicyId: null,
        selectedDiffId: null,

        // Data
        stats: null,
        policies: [],
        snapshots: [],
        diffs: [],
        timeline: [],
        currentDiff: null,
        currentPolicy: null,
        currentSnapshot: null,

        // UI State
        loading: false,
        checking: {},
        seeding: {},
        showAddModal: false,
        showSeedModal: false,
        showEditModal: false,
        toasts: [],

        // Form data
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

        // ---- Lifecycle ----
        async init() {
            await this.loadDashboard();
            await this.loadPolicies();
        },

        // ---- Navigation ----
        navigate(view, id = null) {
            this.currentView = view;
            if (view === 'dashboard') {
                this.loadDashboard();
            } else if (view === 'policies') {
                this.loadPolicies();
            } else if (view === 'policy-detail' && id) {
                this.selectedPolicyId = id;
                this.loadPolicyDetail(id);
            } else if (view === 'diff-detail' && id) {
                this.selectedDiffId = id;
                this.loadDiffDetail(id);
            }
        },

        // ---- API Helpers ----
        async api(method, path, body = null) {
            const opts = {
                method,
                headers: { 'Content-Type': 'application/json' },
            };
            if (body) opts.body = JSON.stringify(body);
            const res = await fetch(path, opts);
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
                this.toast('Failed to load dashboard', 'error');
            }
        },

        // ---- Policies ----
        async loadPolicies() {
            try {
                this.policies = await this.api('GET', '/api/policies');
            } catch (e) {
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
                // Poll for completion
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
                } catch {
                    this.seeding[policyId] = false;
                }
            };
            setTimeout(poll, 3000);
        },

        // ---- Policy Detail ----
        async loadPolicyDetail(id) {
            try {
                this.currentPolicy = await this.api('GET', `/api/policies/${id}`);
                this.snapshots = await this.api('GET', `/api/policies/${id}/snapshots`);
                this.diffs = await this.api('GET', `/api/policies/${id}/diffs`);
                this.timeline = await this.api('GET', `/api/policies/${id}/timeline`);
            } catch (e) {
                this.toast('Failed to load policy details', 'error');
            }
        },

        // ---- Diff Detail ----
        async loadDiffDetail(id) {
            try {
                this.currentDiff = await this.api('GET', `/api/diffs/${id}`);
            } catch (e) {
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
                this.toast('Failed to load snapshot', 'error');
            }
        },

        closeSnapshot() {
            this.currentSnapshot = null;
        },

        // ---- Utility ----
        toast(message, type = 'info') {
            const id = Date.now();
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
            return d.toLocaleDateString('en-US', {
                month: 'short', day: 'numeric', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
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
            try { return JSON.parse(json_str || '[]'); } catch { return []; }
        },

        parseClauses(json_str) {
            try { return JSON.parse(json_str || '[]'); } catch { return []; }
        },

        parseLinks(json_str) {
            try { return JSON.parse(json_str || '[]'); } catch { return []; }
        },

        /**
         * Render markdown text as rich HTML.
         * Delegates to the standalone markdown.js module (uses marked.js).
         */
        renderMarkdown(text) {
            return policyDiffRenderMarkdown(text);
        },
    };
}
