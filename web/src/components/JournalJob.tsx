import { useEffect, useRef, useState } from 'react';
import { App, Button, Card, InputNumber, Progress, Tooltip } from 'antd';
import { HistoryOutlined, SyncOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { get, postRaw } from '../api/client';
import { TERMINAL_JOB_STATUSES, type Job } from '../api/types-research';
import { C } from '../theme';

const KINDS = ['journal_backfill', 'journal_outcomes'];

/**
 * 复盘数据的后台任务（回补历史 / 更新后续表现）：信号复盘和回测实验室共用。
 * 任务状态以服务器为准：刷新页面后会通过 /api/scanners/jobs/current 接回正在跑的任务。
 */
export function useJournalJob(onDone: () => void) {
  const { message } = App.useApp();
  const [jobId, setJobId] = useState<string | null>(null);
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    Promise.all(KINDS.map((k) => get<Job | null>(`/api/scanners/jobs/current?kind=${k}`).catch(() => null))).then((jobs) => {
      const running = jobs.find((j) => j && !TERMINAL_JOB_STATUSES.includes(j.status));
      if (running) setJobId(running.id);
    });
  }, []);

  const job = useQuery({
    queryKey: ['journal-job', jobId],
    queryFn: () => get<Job>(`/api/scanners/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && TERMINAL_JOB_STATUSES.includes(q.state.data.status) ? false : 2000),
  });
  const data = job.data;
  useEffect(() => {
    if (!data || data.id !== jobId || !TERMINAL_JOB_STATUSES.includes(data.status)) return;
    if (data.status === 'completed') message.success(data.message ?? '已完成');
    else message.error(`任务${data.status === 'cancelled' ? '已取消' : '失败'}：${data.error ?? data.message ?? ''}`);
    setJobId(null);
    done.current();
  }, [data, jobId, message]);

  const start = async (url: string) => {
    const { status, body } = await postRaw<Job>(url);
    if (status === 409) {
      const running = (body.job as Job | undefined)?.id;
      if (running) setJobId(running);
      message.info('已有复盘数据任务在运行，已接上进度');
      return;
    }
    if (!body.success || !body.data) {
      message.error(String(body.error ?? '启动失败'));
      return;
    }
    setJobId(body.data.id);
  };
  return { running: !!jobId, job: data, start };
}

/** 管理员按钮：回补近 N 个交易日（含导入旧回测样本）/ 立即更新后续表现 */
export function JournalDataActions({ task }: { task: ReturnType<typeof useJournalJob> }) {
  const [days, setDays] = useState(20);
  return (
    <div className="journal-actions">
      <Tooltip title="用东财历史涨停池按同一套梯队规则重算（约能回溯 1 个月），并导入旧回测样本里更早的日期；已有的实盘记录不会被覆盖">
        <span className="journal-backfill">
          回补近
          <InputNumber size="small" min={1} max={40} value={days} onChange={(v) => setDays(Number(v) || 20)} />
          个交易日
          <Button size="small" icon={<HistoryOutlined />} disabled={task.running}
            onClick={() => task.start(`/api/journal/backfill/start?days=${days}`)}>
            回补
          </Button>
        </span>
      </Tooltip>
      <Button size="small" icon={<SyncOutlined />} disabled={task.running} onClick={() => task.start('/api/journal/outcomes/start')}>
        更新后续表现
      </Button>
    </div>
  );
}

export function JournalJobProgress({ task }: { task: ReturnType<typeof useJournalJob> }) {
  if (!task.running) return null;
  const j = task.job;
  return (
    <Card size="small" className="journal-job">
      <b>{j?.phase ?? '启动中'}</b>
      <span className="muted"> {j?.message ?? ''}</span>
      <Progress size="small" status="active" strokeColor={C.brand}
        percent={j?.total ? Math.round(((j.done ?? 0) / j.total) * 100) : 5} />
      <span className="muted small">在服务器后台运行，可以先离开页面。读日 K 较慢，几百只票要几分钟。</span>
    </Card>
  );
}
