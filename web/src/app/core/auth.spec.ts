import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { authInterceptor } from './auth.interceptor';
import { API, AuthService } from './auth.service';
import { User } from './models';

const USER: User = {
  id: 1, username: 'alice', role: 'operator', is_active: true, must_change_password: false,
  created_at: '2026-09-24T08:00:00Z', last_login_at: null,
};

function setup() {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      provideHttpClient(withInterceptors([authInterceptor])),
      provideHttpClientTesting(),
    ],
  });
  const router = TestBed.inject(Router);
  const navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
  return {
    auth: TestBed.inject(AuthService),
    http: TestBed.inject(HttpClient),
    backend: TestBed.inject(HttpTestingController),
    navigate,
  };
}

async function logIn(auth: AuthService, backend: HttpTestingController, expiresInMs = 12 * 3600_000) {
  const done = auth.login('alice', 'correct-horse-battery');
  const req = backend.expectOne(`${API}/auth/login`);
  expect(req.request.headers.has('Authorization')).toBe(false);
  req.flush({ token: 'tok-123', expires_at: new Date(Date.now() + expiresInMs).toISOString(), user: USER });
  await done;
}

describe('AuthService + authInterceptor', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    vi.useRealTimers();
    TestBed.resetTestingModule();
  });

  it('stores the session in sessionStorage and exposes the user', async () => {
    const { auth, backend } = setup();
    await logIn(auth, backend);
    expect(auth.loggedIn()).toBe(true);
    expect(auth.user()?.username).toBe('alice');
    expect(auth.can('operator')).toBe(true);
    expect(auth.can('admin')).toBe(false);
    expect(sessionStorage.getItem('pic.session')).toContain('tok-123');
  });

  it('adds the Bearer token to API requests only', async () => {
    const { auth, http, backend } = setup();
    await logIn(auth, backend);

    void firstValueFrom(http.get(`${API}/pi/list`));
    expect(backend.expectOne(`${API}/pi/list`).request.headers.get('Authorization')).toBe('Bearer tok-123');

    void firstValueFrom(http.get('/assets/icon/favicon.png'));
    expect(backend.expectOne('/assets/icon/favicon.png').request.headers.has('Authorization')).toBe(false);
  });

  it('ends the session and goes to login on 401', async () => {
    const { auth, http, backend, navigate } = setup();
    await logIn(auth, backend);

    const failed = firstValueFrom(http.get(`${API}/pi/list`)).catch((e: unknown) => e);
    backend.expectOne(`${API}/pi/list`).flush({ detail: 'Session expired' }, { status: 401, statusText: 'Unauthorized' });
    await failed;

    expect(auth.loggedIn()).toBe(false);
    expect(sessionStorage.getItem('pic.session')).toBeNull();
    expect(navigate).toHaveBeenCalledWith(['/login'], { queryParams: { reason: 'expired' } });
  });

  it('a failed login (401) does not trigger the expired redirect', async () => {
    const { auth, backend, navigate } = setup();
    const attempt = auth.login('alice', 'wrong').catch((e: unknown) => e);
    backend.expectOne(`${API}/auth/login`).flush({ detail: 'Wrong username or password' },
      { status: 401, statusText: 'Unauthorized' });
    await attempt;
    expect(navigate).not.toHaveBeenCalled();
    expect(auth.loggedIn()).toBe(false);
  });

  it('logs out by itself when the 12 h are up', async () => {
    vi.useFakeTimers();
    const { auth, backend, navigate } = setup();
    await logIn(auth, backend, 5_000);
    vi.advanceTimersByTime(5_001);
    expect(auth.loggedIn()).toBe(false);
    expect(navigate).toHaveBeenCalledWith(['/login'], { queryParams: { reason: 'expired' } });
  });

  it('ignores an already-expired stored session', () => {
    sessionStorage.setItem('pic.session', JSON.stringify({
      token: 'old', expiresAt: new Date(Date.now() - 1000).toISOString(), user: USER,
    }));
    const { auth } = setup();
    expect(auth.loggedIn()).toBe(false);
    expect(sessionStorage.getItem('pic.session')).toBeNull();
  });

  it('logout calls the API and clears the session even if that fails', async () => {
    const { auth, backend, navigate } = setup();
    await logIn(auth, backend);
    const done = auth.logout();
    backend.expectOne(`${API}/auth/logout`).flush(null, { status: 500, statusText: 'Server Error' });
    await done;
    expect(auth.loggedIn()).toBe(false);
    expect(navigate).toHaveBeenCalledWith(['/login'], { queryParams: { reason: 'logged-out' } });
  });
});
