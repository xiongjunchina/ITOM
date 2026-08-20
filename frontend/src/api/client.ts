import axios from 'axios';
import type { AxiosError, AxiosRequestConfig } from 'axios';
import { message } from 'antd';
import { useAuthStore } from '../stores/auth';
import { useLangStore } from '../i18n/store';
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
  // 当前显示语言：后端据此本地化 status_name 与错误消息
  config.headers['X-Lang'] = useLangStore.getState().lang;
  return config;
});

// 响应拦截：401 清 token 跳登录页；其余错误统一提示
http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<Envelope | Blob>) => {
    const status = error.response?.status;
    if (status === 401) {
      useAuthStore.getState().logout();
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    } else {
      let body = error.response?.data;
      // blob 请求（模板下载）出错时错误体是 Blob，需还原成 JSON 才能取到后端中文提示
      if (body instanceof Blob) {
        try {
          body = JSON.parse(await body.text()) as Envelope;
        } catch {
          body = undefined;
        }
      }
      const msg = body?.error?.message || error.message || '请求失败';
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

/** 从 Content-Disposition 解析下载文件名：优先 RFC 5987 的 filename*=UTF-8''，回退 filename= */
function parseDispositionFilename(disposition?: string): string | null {
  if (!disposition) return null;
  const star = /filename\*\s*=\s*utf-8''([^;]+)/i.exec(disposition);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''));
    } catch {
      // 编码异常时回退 filename=
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1].trim() : null;
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
  async delete<T = unknown>(url: string, data?: unknown): Promise<T> {
    const env = await request<T>({ method: 'delete', url, data });
    return env.data;
  },
  /** 下载二进制文件（如 Excel 模板）：从 Content-Disposition 解析文件名并触发浏览器保存 */
  async download(url: string): Promise<void> {
    const resp = await http.get<Blob>(url, { responseType: 'blob', timeout: 60000 });
    const headers = resp.headers as Record<string, string | undefined>;
    const filename = parseDispositionFilename(headers['content-disposition']) || 'download.xlsx';
    const blobUrl = URL.createObjectURL(resp.data);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(blobUrl);
  },
  /** multipart 上传单个文件（后端约定字段名 file），resolve data 层 */
  async upload<T>(url: string, file: File): Promise<T> {
    const fd = new FormData();
    fd.append('file', file);
    const env = await request<T>({ method: 'post', url, data: fd, timeout: 60000 });
    return env.data;
  },
};
