import { App, Button, Card, Collapse, Empty, Skeleton, Tag } from 'antd';
import { NotificationOutlined, ReloadOutlined, RightOutlined } from '@ant-design/icons';
import { useIsOwner, useNewsRadar, useRebuildWorkbench, useWorkbench } from '../api/hooks';
import { directionMeta } from './news/shared';
import type { WorkbenchStock } from '../api/types';

interface Props {
  onOpenStock: (code: string, name?: string) => void;
}

// 今日作战台：三层候选池（优先 ≤3 / 观察 ≤10 / 风险排除）
export default function WorkbenchCard({ onOpenStock }: Props) {
  const wb = useWorkbench();
  const rebuild = useRebuildWorkbench();
  const { message } = App.useApp();

  const refresh = () =>
    rebuild.mutate(undefined, {
      onSuccess: () => message.success('候选池已重建'),
      onError: (err) => message.error(`重建失败：${(err as Error).message}`),
    });

  const isOwner = useIsOwner();
  // 重建候选会拉取大量行情，只给管理员；普通成员看共享结果即可
  const refreshButton = !isOwner ? null : (
    <Button
      size="small"
      icon={<ReloadOutlined />}
      loading={rebuild.isPending}
      onClick={refresh}
      title="强制重建候选（后端需数十秒）"
    >
      {rebuild.isPending ? '重建中' : '重建'}
    </Button>
  );

  if (wb.isLoading) {
    return (
      <Card title="今日作战台 · 候选池">
        <Skeleton active />
      </Card>
    );
  }

  if (wb.isError || !wb.data) {
    return (
      <Card title="今日作战台 · 候选池" extra={refreshButton}>
        <Empty description={`候选预检暂不可用：${(wb.error as Error)?.message ?? '未知错误'}。当前不要据此执行。`} />
      </Card>
    );
  }

  const data = wb.data;
  const primary = data.primary ?? [];
  const watch = data.watch ?? [];
  const excluded = data.risk_excluded ?? [];
  const deep = data.deep_precheck;
  const deepSummary = deep
    ? `深检 ${deep.reviewed ?? 0} · 通过 ${deep.passed ?? 0} · 排除 ${deep.excluded ?? 0}`
    : '深检状态待确认';

  return (
    <Card title="今日作战台 · 候选池" extra={refreshButton}>
      <div className="wb-summary">
        <span>
          优先关注 <b className="num">{primary.length}</b>/3
        </span>
        <span>{deepSummary}</span>
        {data.cached && <Tag bordered={false}>缓存</Tag>}
        <span className="muted">仍须进入个股完整研究</span>
      </div>
      {primary.length === 0 && <Empty description="当前没有通过预检的标的" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      {primary.map((s) => (
        <Candidate key={s.code} stock={s} onOpen={onOpenStock} />
      ))}
      <Collapse
        ghost
        size="small"
        className="wb-collapse"
        items={[
          {
            key: 'watch',
            label: `观察池 ${watch.length}/10 · 查看降级原因`,
            children: watch.length ? (
              watch.map((s) => <Candidate key={s.code} stock={s} onOpen={onOpenStock} />)
            ) : (
              <span className="muted">当前没有观察池标的</span>
            ),
          },
          ...(excluded.length
            ? [
                {
                  key: 'excluded',
                  label: `风险排除 ${excluded.length} 只 · 只读记录`,
                  children: excluded.map((s) => (
                    <div key={s.code} className="candidate-item is-excluded">
                      <span className="candidate-rank">×</span>
                      <span className="candidate-main">
                        <b>{s.name ?? s.code}</b>
                        <small>
                          {s.sector ?? '未知题材'} · {s.limit_count ?? 0}板
                        </small>
                        <div className="candidate-veto">
                          {s.risk_precheck?.veto_reason ?? s.blockers?.[0] ?? '触发个股风险否决'}
                        </div>
                      </span>
                    </div>
                  )),
                },
              ]
            : []),
        ]}
      />
      {(data.warnings ?? []).slice(0, 2).map((w, i) => (
        <div key={i} className="wb-warning">
          {w}
        </div>
      ))}
    </Card>
  );
}

function Candidate({
  stock: s,
  onOpen,
}: {
  stock: WorkbenchStock;
  onOpen: (code: string, name?: string) => void;
}) {
  const open = () => s.code && onOpen(s.code, s.name);
  // 重大消息雷达命中这只候选时提示一句（观察用，不改变候选排序）
  const radar = useNewsRadar();
  const news = (radar.data?.data.events ?? []).find((e) => e.code === s.code);
  const newsDir = news ? directionMeta(news.direction) : null;
  return (
    <div
      className="candidate-item"
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), open())}
    >
      <span className="candidate-rank num">{s.rank ?? ''}</span>
      <span className="candidate-main">
        <b>{s.name ?? s.code ?? '未知标的'}</b>
        <small>
          {s.sector ?? '未知题材'} · {s.limit_count ?? 0}板 · 预检 {s.precheck_score ?? 0}
        </small>
        <div className="candidate-reasons">{(s.reasons ?? []).slice(0, 3).join(' · ') || '等待进一步验证'}</div>
        {s.blockers?.length ? <div className="candidate-blocker">{s.blockers[0]}</div> : null}
        {news && newsDir && (
          <div className="candidate-news" style={{ color: newsDir.color }} title={news.title}>
            <NotificationOutlined /> {news.level_label}
            {newsDir.text}：{news.type_label}
          </div>
        )}
      </span>
      <span className="candidate-go">
        分时 <RightOutlined />
      </span>
    </div>
  );
}
