export type Role = 'read' | 'developer' | 'admin';
export interface Session { role: Role; csrf_token: string }
export interface Artifact { image: string; scanned_image_id: string | null; reported_high_critical: number | null; refs: Record<string, string> }
export interface Build { id: string; job: string; number: number; source_commit: string; result: string; artifact?: Artifact | null }
export interface Metric { name: string; phase: string; measurements?: { phase?: string; value?: string; message?: string }[] }
export interface Analysis { id: string; name: string; phase: string; data: { metrics?: Metric[] } }
export interface Observation { id: string; quality: string; stable_requests: number; stable_non_200: number; data: { observed_at?: string; stable_revision?: string; stable_hash?: string; exclusion_reason?: string; availability_boundary?: string; raw_trial?: string; artifacts?: Record<string, string> } }
export interface Release { id: string; status: string; candidate_hash: string | null; environment_commit: string; observed_at: string; promoted_at?: string | null; recovery_id?: string | null; build: Build; artifact: Artifact; analyses: Analysis[]; observations: Observation[] }
export interface Environment { project: string; name: string; job: string; version: number; freshness: string; last_observed_at: string | null; detail: string | null; desired: Release | null; stable: Release | null; stable_revision: string | null; stable_hash: string | null; stable_image: string | null }
export interface Audit { id: number; action: string; version: number; created_at: string; data: { actor?: string; source?: string; detail?: string; changes?: { build?: number; status?: string; quality?: string; state_applied?: boolean; reason?: string }[] } }
export interface Recovery { id: string; phase: string; policy: string; base_commit: string; recovery_commit: string | null; outcome: string | null; created_at: string; updated_at: string; origin: Release; target: Release | null; trigger: { windows: { window_end: string; data: { requests: number; errors: number; p95_seconds: number } }[] }; events: { id: string; phase: string; created_at: string; data: { outcome?: string | null } }[] }
export interface Data { environment: Environment; releases: Release[]; builds: Build[]; recoveries: Recovery[]; audit: Audit[]; auditAllowed: boolean; loadedAt: string }
