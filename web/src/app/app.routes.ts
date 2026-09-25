import { Routes } from '@angular/router';

import { authGuard, guestGuard, roleGuard } from './core/guards';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'inventory' },
  {
    path: 'login',
    canActivate: [guestGuard],
    loadComponent: () => import('./pages/login.page').then((m) => m.LoginPage),
  },
  {
    path: 'inventory',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/inventory.page').then((m) => m.InventoryPage),
  },
  {
    path: 'pi/:position',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/pi-detail.page').then((m) => m.PiDetailPage),
  },
  {
    path: 'actions/:id',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/action.page').then((m) => m.ActionPage),
  },
  {
    path: 'logs',
    canActivate: [authGuard, roleGuard('operator')],  // activity log: operator+
    loadComponent: () => import('./pages/logs.page').then((m) => m.LogsPage),
  },
  {
    path: 'users',
    canActivate: [authGuard, roleGuard('admin')],
    loadComponent: () => import('./pages/users.page').then((m) => m.UsersPage),
  },
  {
    path: 'account',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/account.page').then((m) => m.AccountPage),
  },
  {
    path: 'settings',
    canActivate: [authGuard, roleGuard('admin')],
    loadComponent: () => import('./pages/settings.page').then((m) => m.SettingsPage),
  },
  {
    path: 'execute',
    canActivate: [authGuard, roleGuard('admin')],
    loadComponent: () => import('./pages/execute-command.page').then((m) => m.ExecuteCommandPage),
  },
  { path: '**', redirectTo: 'inventory' },
];
