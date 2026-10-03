export type AuthRole = 'viewer' | 'operator' | 'admin';

export interface AuthConfig {
  authentication_required: boolean;
}

export interface AuthSession {
  name: string;
  role: AuthRole;
  namespaces: string[];
}
