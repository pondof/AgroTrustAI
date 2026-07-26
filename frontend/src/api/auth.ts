import axios from "axios";

import type { TokenResponse } from "@/types";

import { API_BASE } from "./client";

/**
 * Login (OAuth2 password flow). O gateway expõe POST /token (fora do prefixo /api),
 * aceitando form-urlencoded. Usamos um axios "cru" (sem o interceptor de Bearer),
 * pois ainda não há token nesta etapa.
 */
export async function login(username: string, password: string): Promise<TokenResponse> {
  const form = new URLSearchParams();
  form.append("username", username);
  form.append("password", password);

  const { data } = await axios.post<TokenResponse>(`${API_BASE}/token`, form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data;
}
