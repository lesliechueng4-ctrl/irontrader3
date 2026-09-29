// 扫描任务的生命周期：启动 → 轮询进度 → 完成后落到"上次结果"。
// 任务状态以服务器为准（task_manager 持久化在 SQLite），所以刷新页面、换电脑打开，
// 都会通过 /api/scanners/jobs/current 接回正在跑的任务，不再依赖浏览器 sessionStorage。
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post, postRaw } from '../../api/client';
import { TERMINAL_JOB_STATUSES, type Job } from '../../api/types-research';
import { useStoredJson } from '../../utils/storage';
import { scannerOf, type ScannerKey, type ScanSettings } from './config';

export interface SavedScan {
  kind: ScannerKey;
  result: unknown;
  ts: number;
  params?: Record<string, unknown>;
}

const LAST_SCAN_KEY = 'irontrader.lastScan.v2';
const isTerminal = (job?: Job | null) => !!job && TERMINAL_JOB_STATUSES.includes(job.status);

export function useScanJob() {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [lastScan, setLastScan] = useStoredJson<SavedScan | null>(LAST_SCAN_KEY, null);
  const [endedJob, setEndedJob] = useState<Job | null>(null); // 失败 / 已停止，给出说明
  const [starting, setStarting] = useState<ScannerKey | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 首次进入：接回服务器上仍在运行的扫描
  const current = useQuery({
    queryKey: ['scan-current'],
    queryFn: () => get<Job | null>('/api/scanners/jobs/current'),
    staleTime: 0,
  });
  const settled = useRef(new Set<string>()); // 已处理完的任务，不再重复接管
  useEffect(() => {
    const job = current.data;
    if (job && scannerOf(job.kind) && !isTerminal(job) && !jobId && !settled.current.has(job.id)) setJobId(job.id);
  }, [current.data, jobId]);

  const failures = useRef(0);
  const poll = useQuery({
    queryKey: ['scan-job', jobId],
    queryFn: () => get<Job>(`/api/scanners/jobs/${jobId}`, 15_000),
    enabled: !!jobId,
    // 进度 1.2s 一次；连续失败时退避，最多 10s
    refetchInterval: (q) => (isTerminal(q.state.data) ? false : Math.min(10_000, 1200 * 2 ** failures.current)),
    retry: false,
  });

  useEffect(() => {
    if (!poll.isError) {
      if (poll.data) failures.current = 0;
      return;
    }
    failures.current += 1;
    const msg = (poll.error as Error)?.message ?? '';
    // 任务记录已不存在（被清理 / 数据库重建）：不再轮询
    if (/不存在|过期/.test(msg) && jobId) {
      settled.current.add(jobId);
      setEndedJob({ id: jobId, kind: '', status: 'failed', error: msg });
      setJobId(null);
    }
  }, [poll.isError, poll.error, poll.data, poll.errorUpdatedAt, poll.dataUpdatedAt, jobId]);

  const job = poll.data ?? null;

  // 结束：成功的结果保存下来（刷新后仍在），失败/取消的保留说明
  useEffect(() => {
    if (!job || !isTerminal(job) || job.id !== jobId) return;
    if (job.status === 'completed' || job.status === 'finished') {
      setLastScan({ kind: job.kind as ScannerKey, result: job.result, ts: Date.now(), params: job.params });
      setEndedJob(null);
    } else {
      setEndedJob(job);
    }
    settled.current.add(job.id);
    setJobId(null);
    qc.setQueryData(['scan-current'], null);
    qc.removeQueries({ queryKey: ['scan-job', job.id] });
  }, [job, jobId, qc, setLastScan]);

  const start = useCallback(
    async (key: ScannerKey, settings: ScanSettings) => {
      const def = scannerOf(key);
      if (!def || jobId) return;
      setStarting(key);
      setNotice(null);
      setEndedJob(null);
      try {
        const { status, body } = await postRaw<Job>(def.startUrl(settings));
        if (body.success && body.data) {
          setJobId((body.data as Job).id);
          return;
        }
        // 409：同类扫描已在跑 → 直接接管它的进度
        const running = body.job as Job | null | undefined;
        if (status === 409 && running?.id) {
          const wanted = def.params(settings);
          const differs = Object.entries(wanted).some(
            ([k, v]) => running.params && String(running.params[k] ?? '') !== String(v ?? ''),
          );
          setNotice(
            differs
              ? '同类扫描正以另一组参数运行，已接管它的进度；结束后可按新参数再扫一次。'
              : '检测到同类扫描正在运行，已接管进度。',
          );
          setJobId(running.id);
          return;
        }
        throw new Error(String(body.error ?? `启动失败（HTTP ${status}）`));
      } catch (err) {
        setEndedJob({ id: '', kind: key, status: 'failed', error: (err as Error).message });
      } finally {
        setStarting(null);
      }
    },
    [jobId],
  );

  const cancel = useCallback(async () => {
    if (!jobId) return;
    try {
      const j = await post<Job>(`/api/scanners/jobs/${jobId}/cancel`);
      qc.setQueryData(['scan-job', jobId], j);
    } catch (err) {
      setNotice(`停止失败：${(err as Error).message}；任务仍在运行`);
    }
  }, [jobId, qc]);

  return {
    job,
    jobId,
    running: !!jobId,
    pollError: poll.isError ? (poll.error as Error).message : null,
    starting,
    notice,
    endedJob,
    lastScan,
    clearLast: () => setLastScan(null),
    start,
    cancel,
  };
}
