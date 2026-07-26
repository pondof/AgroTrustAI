import axios from "axios";

/**
 * Cliente HTTP (axios).
 *
 * O token JWT vive APENAS em memória (setado pelo AuthContext via setAuthToken) —
 * nunca em localStorage/sessionStorage/cookie. Por isso o token é injetado por um
 * interceptor que lê uma variável de módulo, não um storage persistente.
 *
 * Em 401 (token ausente/expirado) delegamos ao handler registrado pelo AuthProvider,
 * que faz logout e redireciona para /login (não há refresh token no ambiente dev).
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
export const API_BASE = RAW_BASE.replace(/\/$/, "");

let authToken: string | null = null;
let unauthorizedHandler: () => void = () => {};

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler;
}

/** Instância para os endpoints sob /api (o gateway serve /api/v1/*). */
export const api = axios.create({
  baseURL: `${API_BASE}/api`,
});

api.interceptors.request.use((config) => {
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      unauthorizedHandler();
    }
    return Promise.reject(error);
  },
);

/** Extrai uma mensagem legível de um erro do axios (para toasts/telas de erro). */
export function extractErrorMessage(error: unknown, fallback = "Ocorreu um erro."): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data as { detail?: unknown } | undefined;
    if (detail && typeof detail.detail === "string") return detail.detail;
    if (error.message) return error.message;
  }
  if (error instanceof Error) return error.message;
  return fallback;
}
