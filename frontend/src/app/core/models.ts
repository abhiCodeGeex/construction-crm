export type Level = 'r' | 'rw';
export type Permissions = Record<string, Level>;

export interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  kind: 'staff' | 'external';
  phone?: string;
  active?: boolean;
  whatsapp_only?: boolean;
  contact_id?: string;
  last_login?: string;
}

export interface Company {
  id: string;
  name: string;
  types: string[];
  modules: string[];
  plan_code: string;
  status: string;
  trial_ends?: string;
  branding?: { primary?: string; logo?: string | null };
}

export interface Limits {
  plan: string;
  users: number | null;
  projects: number | null;
  modules: number | null;
  whatsapp: number | null;
  storage_gb: number;
}

export interface Session {
  token: string;
  user: User;
  company: Company;
  permissions: Permissions;
  limits: Limits;
  roles: { internal: string[]; external: string[]; labels: Record<string, string> };
}

export interface SaSession {
  token: string;
  user: { id: string; name: string; email: string; role: string };
  permissions: Permissions;
}
