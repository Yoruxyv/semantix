import { request } from '@/shared/api/httpClient';
import type { ApiResult } from '@/shared/api/types';
import { createEnumGuard, isNonEmptyString, isRecord } from '@/shared/api/validators';

import type { AuthConfig, AuthRole, AuthSession } from '../types';

const AUTH_ROLES: readonly AuthRole[] = ['viewer', 'operator', 'admin'];
const isAuthRole = createEnumGuard(AUTH_ROLES);

function decodeAuthConfig(value: unknown): AuthConfig {
  if (!isRecord(value) || typeof value.authentication_required !== 'boolean') {
    throw new Error('Invalid authentication configuration response');
  }
  return { authentication_required: value.authentication_required };
}

function decodeAuthSession(value: unknown): AuthSession {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.name) ||
    !isAuthRole(value.role) ||
    !Array.isArray(value.namespaces) ||
    value.namespaces.length === 0 ||
    !value.namespaces.every(isNonEmptyString)
  ) {
    throw new Error('Invalid authentication session response');
  }
  return {
    name: value.name,
    role: value.role,
    namespaces: value.namespaces,
  };
}

export function getAuthConfig(): Promise<ApiResult<AuthConfig>> {
  return request('/api/v1/auth/config', decodeAuthConfig, { method: 'GET' });
}

export function getAuthSession(): Promise<ApiResult<AuthSession>> {
  return request('/api/v1/auth/session', decodeAuthSession, { method: 'GET' });
}
