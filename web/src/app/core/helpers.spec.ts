import { rebootVerdict, throttleText } from './fleet';
import { newPasswordProblem } from '../pages/account.page';
import { matchesSearch } from '../pages/inventory.page';
import { num, statusColor, uptime } from './format';
import { PiSummary } from './models';
import { hasRole, usernameProblem } from './roles';
import { comparePositions, positionSortKey } from './sort';

describe('position sort (same rule as the TUI)', () => {
  it('parses numbers and legacy XX-XXX', () => {
    expect(positionSortKey('42')).toEqual([42]);
    expect(positionSortKey('01-003')).toEqual([1, 3]);
    expect(positionSortKey('')).toEqual([]);
    expect(positionSortKey(null)).toEqual([]);
  });

  it('sorts numerically', () => {
    const sorted = ['10', '9', '01-003', '2', '00-012', ''].sort(comparePositions);
    expect(sorted).toEqual(['', '00-012', '01-003', '2', '9', '10']);
  });
});

describe('hasRole', () => {
  it('ranks viewer < operator < admin', () => {
    expect(hasRole('admin', 'operator')).toBe(true);
    expect(hasRole('operator', 'operator')).toBe(true);
    expect(hasRole('viewer', 'operator')).toBe(false);
    expect(hasRole('operator', 'admin')).toBe(false);
  });

  it('rejects missing or unknown roles', () => {
    expect(hasRole(null, 'viewer')).toBe(false);
    expect(hasRole(undefined, 'viewer')).toBe(false);
    expect(hasRole('root', 'viewer')).toBe(false);
  });
});

describe('format helpers', () => {
  it('maps statuses to colours', () => {
    expect(statusColor('reachable')).toBe('success');
    expect(statusColor('partial_fail')).toBe('warning');
    expect(statusColor('interrupted')).toBe('danger');
    expect(statusColor('whatever')).toBe('medium');
  });

  it('reads numbers from health details', () => {
    expect(num({ cpu_1m: 12.5 }, 'cpu_1m')).toBe(12.5);
    expect(num({ cpu_1m: 'x' }, 'cpu_1m')).toBeNull();
    expect(num(null, 'cpu_1m')).toBeNull();
  });

  it('formats uptime', () => {
    expect(uptime(90)).toBe('1m');
    expect(uptime(3 * 3600 + 5 * 60)).toBe('3h 5m');
    expect(uptime(2 * 86400 + 3600)).toBe('2d 1h');
    expect(uptime(null)).toBe('—');
  });
});

describe('inventory search', () => {
  const pi: PiSummary = {
    mac: 'b8:27:eb:aa:bb:cc', hostname: 'kiosk-07', position: '07-001', ip: '10.10.20.57', pi_version: 4,
    status: 'reachable', last_seen: null, tags: ['lobby'], cpu_1m: null, cpu_5m: null, cpu_15m: null,
    mem_percent: null, temp_c: null,
  };

  it('matches position, hostname, IP, MAC and tags case-insensitively', () => {
    for (const q of ['07-001', 'KIOSK', '10.10.20.57', 'b8:27', 'Lobby', '  ']) {
      expect(matchesSearch(pi, q)).toBe(true);
    }
    expect(matchesSearch(pi, 'floor2')).toBe(false);
  });
});

describe('new password check (entered twice)', () => {
  it('requires 12 characters and matching entries', () => {
    expect(newPasswordProblem('short', 'short')).toContain('12');
    expect(newPasswordProblem('long-enough-pw', 'long-enough-px')).toContain('match');
    expect(newPasswordProblem('long-enough-pw', 'long-enough-pw')).toBeNull();
  });
});

describe('username check (same rule as the server)', () => {
  it('accepts valid names', () => {
    for (const name of ['alice', 'jan.novak', 'op_1', 'a1']) {
      expect(usernameProblem(name)).toBeNull();
    }
  });

  it('rejects invalid or reserved names', () => {
    for (const name of ['A', 'Alice', 'has space', '-lead', 'x'.repeat(33), 'local-tui', 'local-tui2']) {
      expect(usernameProblem(name)).not.toBeNull();
    }
  });
});

describe('fleet helpers', () => {
  it('throttle text', () => {
    expect(throttleText({ raw: '0x0', ok: true })).toBe('ok');
    expect(throttleText({ raw: '0x50005', ok: false, under_voltage_now: true, throttled_now: true,
      under_voltage_ever: true, throttled_ever: true })).toBe(
      'under-voltage now, throttled now, under-voltage since boot, throttled since boot');
    expect(throttleText(null)).toBe('—');
  });

  it('reboot verdict from server timestamps', () => {
    const reboot = '2026-09-24T12:00:00';
    const health = '2026-09-24T12:01:40'; // 100 s later
    expect(rebootVerdict(80, reboot, health)).toBe('rebooted');
    expect(rebootVerdict(150, reboot, health)).toBe('rebooted'); // within margin
    expect(rebootVerdict(86400, reboot, health)).toBe('not-rebooted');
    expect(rebootVerdict(null, reboot, health)).toBe('unknown');
  });
});
