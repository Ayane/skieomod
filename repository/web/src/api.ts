export interface SteamProfile {id: string; name: string; avatar_url: string | null; profile_url: string}
export interface User extends SteamProfile {admin?: boolean; csrf: string}
export interface Token {id: string; label: string; expires: number}

export async function api<T>(path: string, method = 'GET', body?: unknown, csrf?: string): Promise<T> {
  const response = await fetch('/api/v1' + path, {method, credentials: 'same-origin', headers: {...(body ? {'Content-Type': 'application/json'} : {}), ...(csrf ? {'X-CSRF-Token': csrf} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Erreur ${response.status}`);
  return result as T;
}
