/**
 * Navigation registry. Each feature module owns one entry keyed by its permission area
 * (the same keys as AREAS in backend/app/security.py). When a module is built, its entry gets
 * `ready: true` and its own route; until then the menu shows a placeholder so permissions can be tested.
 */
export interface NavItem {
  area: string;
  label: string;
  icon: string;
  section: 'Sales' | 'Delivery' | 'Money' | 'Team' | 'Admin';
  ready?: boolean;
  path?: string;
}

export const NAV: NavItem[] = [
  { area: 'leads', label: 'Leads & pipeline', icon: 'pi pi-bullseye', section: 'Sales' },
  { area: 'contacts', label: 'Contacts', icon: 'pi pi-id-card', section: 'Sales', ready: true, path: '/app/contacts' },
  { area: 'proposals', label: 'Proposals & estimates', icon: 'pi pi-file-edit', section: 'Sales' },
  { area: 'projects', label: 'Projects', icon: 'pi pi-building', section: 'Delivery', ready: true, path: '/app/projects' },
  { area: 'documents', label: 'Documents & drawings', icon: 'pi pi-folder-open', section: 'Delivery' },
  { area: 'selections', label: 'Selections', icon: 'pi pi-palette', section: 'Delivery' },
  { area: 'site', label: 'Site reports', icon: 'pi pi-camera', section: 'Delivery' },
  { area: 'change_orders', label: 'Change orders', icon: 'pi pi-sync', section: 'Delivery' },
  { area: 'procurement', label: 'Procurement', icon: 'pi pi-truck', section: 'Money' },
  { area: 'finance', label: 'Finance', icon: 'pi pi-wallet', section: 'Money' },
  { area: 'reports', label: 'Reports', icon: 'pi pi-chart-bar', section: 'Money' },
  { area: 'followups', label: 'Follow-ups', icon: 'pi pi-bell', section: 'Team' },
  { area: 'messages', label: 'Inbox', icon: 'pi pi-comments', section: 'Team' },
  { area: 'users', label: 'Users & roles', icon: 'pi pi-users', section: 'Admin', ready: true, path: '/app/users' },
  { area: 'settings', label: 'Company settings', icon: 'pi pi-cog', section: 'Admin', ready: true, path: '/app/settings' },
];

export const SECTIONS: NavItem['section'][] = ['Sales', 'Delivery', 'Money', 'Team', 'Admin'];
