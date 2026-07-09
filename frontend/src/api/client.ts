import axios from 'axios';
import type { AxiosError, AxiosRequestConfig } from 'axios';
import { message } from 'antd';
import { useAuthStore } from '../stores/auth';
import type { Envelope } from './types';

const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
});

// 请求拦截：注入 token
http.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截：401 清 token 跳登录页；其余错误统一提示
http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<Envelope>) => {
    const status = error.response?.status;
    if (status === 401) {
      useAuthStore.getState().logout();
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    } else {
      const msg = error.response?.data?.error?.message || error.message || '请求失败';
      message.error(msg);
    }
    return Promise.reject(error);
  },
);

/** 发起请求并校验统一响应包 */
async function request<T>(config: AxiosRequestConfig): Promise<Envelope<T>> {
  const resp = await http.request<Envelope<T>>(config);
  const env = resp.data;
  if (!env || env.success === false) {
    const msg = env?.error?.message || '请求失败';
    message.error(msg);
    throw new Error(msg);
  }
  return env;
}

export interface ListResult<T> {
  items: T[];
  total: number;
}

/** 解包后的 API 客户端：直接 resolve data 层；列表接口用 getList 以保留 total */
export const api = {
  async get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    const env = await request<T>({ method: 'get', url, params });
    return env.data;
  },
  async getList<T>(url: string, params?: Record<string, unknown>): Promise<ListResult<T>> {
    const env = await request<T[]>({ method: 'get', url, params });
    const items = env.data ?? [];
    return { items, total: env.total ?? items.length };
  },
  async post<T>(url: string, data?: unknown): Promise<T> {
    const env = await request<T>({ method: 'post', url, data });
    return env.data;
  },
  async patch<T>(url: string, data?: unknown): Promise<T> {
    const env = await request<T>({ method: 'patch', url, data });
    return env.data;
  },
  async put<T>(url: string, data?: unknown): Promise<T> {
    const env = await request<T>({ method: 'put', url, data });
    return env.data;
  },
};
