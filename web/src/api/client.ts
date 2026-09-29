import axios, { AxiosError } from 'axios';

// 后端统一响应格式（见 api_response.py）：
//   成功 {success: true, data, meta?}   失败 {success: false, error, error_code?}
export interface ApiMeta {
  as_of?: string;
  stale?: boolean;
  cached?: boolean;
  count?: number;
  [key: string]: unknown;
}

interface Envelope<T> {
  success: boolean;
  data: T;
  meta?: ApiMeta;
  error?: string;
  error_code?: string;
}

const client = axios.create({ baseURL: '/', timeout: 30_000 });

// 登录过期（cookie 失效 / 密钥被停用）：刷新页面，由服务端返回登录页
client.interceptors.response.use(undefined, (err: AxiosError<{ error_code?: string }>) => {
  if (err.response?.status === 401 && err.response.data?.error_code === 'UNAUTHORIZED') {
    window.location.reload();
  }
  return Promise.reject(err);
});

function toError(err: unknown): Error {
  const ax = err as AxiosError<Partial<Envelope<unknown>>>;
  if (ax?.code === 'ECONNABORTED') return new Error('请求超时');
  const serverMsg = ax?.response?.data?.error;
  if (serverMsg) return new Error(serverMsg);
  if (ax?.response) return new Error(`请求失败（HTTP ${ax.response.status}）`);
  return err instanceof Error ? err : new Error(String(err));
}

function unwrap<T>(body: unknown): Envelope<T> {
  const env = body as Envelope<T>;
  if (!env || typeof env !== 'object' || !('success' in env)) {
    throw new Error('响应格式不正确');
  }
  if (!env.success) throw new Error(env.error || '请求失败');
  return env;
}

/** 返回 data 与 meta（数据时效等） */
export async function getWithMeta<T>(url: string, timeout = 30_000): Promise<{ data: T; meta: ApiMeta }> {
  try {
    const resp = await client.get(url, { timeout });
    const env = unwrap<T>(resp.data);
    return { data: env.data, meta: env.meta ?? {} };
  } catch (err) {
    throw toError(err);
  }
}

export async function get<T>(url: string, timeout = 30_000): Promise<T> {
  return (await getWithMeta<T>(url, timeout)).data;
}

export async function post<T>(url: string, body?: unknown): Promise<T> {
  try {
    const resp = await client.post(url, body ?? {});
    return unwrap<T>(resp.data).data;
  } catch (err) {
    throw toError(err);
  }
}

/** 不因业务失败抛错：返回 HTTP 状态与原始响应体，供需要读取失败详情的调用方（如 409 任务占用）使用 */
export async function postRaw<T = unknown>(
  url: string,
  body?: unknown,
): Promise<{ status: number; body: Partial<Envelope<T>> & Record<string, unknown> }> {
  try {
    const resp = await client.post(url, body ?? {});
    return { status: resp.status, body: resp.data };
  } catch (err) {
    const ax = err as AxiosError<Partial<Envelope<T>> & Record<string, unknown>>;
    if (ax?.response?.data && typeof ax.response.data === 'object') {
      return { status: ax.response.status, body: ax.response.data };
    }
    throw toError(err);
  }
}

/** PATCH / DELETE 等其它方法（账号管理用） */
export async function send<T>(method: 'patch' | 'delete' | 'put', url: string, body?: unknown): Promise<T> {
  try {
    const resp = await client.request({ method, url, data: body ?? {} });
    return unwrap<T>(resp.data).data;
  } catch (err) {
    throw toError(err);
  }
}
