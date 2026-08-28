import { beforeEach, vi } from 'vitest';

import { getAuthConfig, getAuthSession } from '@/features/auth/api/authApi';
import { useAuth } from '@/features/auth/hooks/useAuth';

vi.mock('@/features/auth/api/authApi', () => ({
  getAuthConfig: vi.fn(),
  getAuthSession: vi.fn(),
}));

vi.mock('@/features/auth/hooks/useAuth', () => ({
  useAuth: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getAuthConfig).mockResolvedValue({
    ok: true,
    data: {
      authentication_required: false,
    },
  });
  vi.mocked(getAuthSession).mockResolvedValue({
    ok: false,
    error: {
      code: 'authentication_required',
      detail: 'A valid bearer token is required.',
      status: 401,
    },
  });
  vi.mocked(useAuth).mockReturnValue({
    authenticate: vi.fn(async () => false),
    error: null,
    lockedUntil: null,
    logout: vi.fn(),
    retryAccessPolicy: vi.fn(),
    session: null,
    status: 'disabled',
  });
});
