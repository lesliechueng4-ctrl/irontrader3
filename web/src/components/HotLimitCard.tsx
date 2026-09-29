import { Card, Empty, Skeleton, Table } from 'antd';
import { useHotLimit } from '../api/hooks';
import { fmtYi } from '../theme';
import type { HotLimitStock } from '../api/types';
import Freshness from './Freshness';

interface Props {
  onOpenStock: (code: string, name?: string) => void;
}

// 涨停关注 Top20：封单额排序，带数据时效标识
export default function HotLimitCard({ onOpenStock }: Props) {
  const hot = useHotLimit();

  return (
    <Card
      title="涨停关注 Top20"
      extra={hot.data && <Freshness asOf={hot.data.asOf} stale={hot.data.stale} fetching={hot.isFetching} />}
    >
      {hot.isLoading && <Skeleton active />}
      {hot.isError && <Empty description={`加载失败：${(hot.error as Error)?.message ?? ''}`} />}
      {hot.data && (
        <Table<HotLimitStock>
          size="small"
          rowKey="code"
          className="num-table"
          dataSource={hot.data.stocks}
          pagination={false}
          scroll={{ y: 420 }}
          onRow={(r) => ({ onClick: () => onOpenStock(r.code, r.name), style: { cursor: 'pointer' } })}
          columns={[
            { title: '名称', dataIndex: 'name', width: 96, ellipsis: true },
            { title: '代码', dataIndex: 'code', width: 72 },
            {
              title: '封单额',
              dataIndex: 'seal_amount',
              align: 'right',
              width: 88,
              sorter: (a, b) => (a.seal_amount ?? 0) - (b.seal_amount ?? 0),
              render: (v) => fmtYi(v),
            },
            {
              title: '连板',
              dataIndex: 'limit_count',
              width: 64,
              align: 'center',
              sorter: (a, b) => (a.limit_count ?? 0) - (b.limit_count ?? 0),
              render: (v) => <span className={`board-badge ${v >= 3 ? 'is-high' : ''}`}>{v}板</span>,
            },
            { title: '题材', dataIndex: 'sector', ellipsis: true },
            {
              title: '首封',
              dataIndex: 'first_limit_time',
              width: 64,
              render: (v?: string) => (v ? String(v).slice(0, 5) : '--'),
            },
          ]}
        />
      )}
    </Card>
  );
}
