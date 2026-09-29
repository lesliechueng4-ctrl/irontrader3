import { useMemo, useState, type ReactNode } from 'react';
import { Button, Input, Segmented, Table, Tooltip } from 'antd';
import type { ColumnsType, SortOrder } from 'antd/es/table/interface';
import { DownloadOutlined, FilterFilled, StarFilled, StarOutlined } from '@ant-design/icons';
import { useWatchlist } from '../utils/storage';

// Excel 式结果表：列排序 + 逐列筛选（数值列支持 >=5 / <3 这类条件）+ 全表搜索 + "只看近 N 天" + 导出 CSV + 自选星标。
// 所有扫描结果统一用它，旧版 mountInteractiveTable 的功能一项不少。

export type ColType = 'number' | 'string' | 'date';

export interface DataColumn<R> {
  key: string;
  title: string;
  value: (row: R) => unknown;
  render?: (row: R) => ReactNode;
  type?: ColType; // 不给则按数据自动判断
  width?: number;
  /** "距今(天)" 这类列：工具栏出现"近 3/7/15 天"快捷筛选 */
  recency?: boolean;
  /** 默认按此列排序 */
  defaultSort?: 'ascend' | 'descend';
  ellipsis?: boolean;
}

interface Props<R> {
  rows: R[];
  columns: DataColumn<R>[];
  codeOf: (row: R) => string;
  nameOf?: (row: R) => string | undefined;
  exportName: string;
  onOpen?: (code: string, name?: string) => void;
  /** 行首色条：用于区分"已确认 / 候选预警""低吸 / 观察"等 */
  rowTone?: (row: R) => 'buy' | 'ok' | 'warn' | 'crit' | 'none' | undefined;
  extraActions?: (row: R) => ReactNode;
}

const isEmpty = (v: unknown) => v === null || v === undefined || v === '';

export function numericOf(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (isEmpty(v)) return null;
  const n = parseFloat(String(v).replace(/[%,\s]/g, ''));
  return Number.isNaN(n) ? null : n;
}

export function formatCell(v: unknown): string {
  if (isEmpty(v)) return '-';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === 'boolean') return v ? '是' : '否';
  return String(v);
}

function detectType<R>(col: DataColumn<R>, rows: R[]): ColType {
  if (col.type) return col.type;
  const vals = rows.map(col.value).filter((v) => !isEmpty(v));
  if (!vals.length) return 'string';
  if (vals.every((v) => /^\d{4}-\d{2}-\d{2}/.test(String(v)))) return 'date';
  if (vals.every((v) => numericOf(v) !== null)) return 'number';
  return 'string';
}

function matches(raw: unknown, filter: string, type: ColType): boolean {
  const f = filter.trim();
  if (!f) return true;
  if (type === 'number') {
    const m = f.match(/^(>=|<=|>|<|=)\s*(-?\d+\.?\d*)$/);
    if (m) {
      const x = numericOf(raw);
      if (x === null) return false;
      const y = parseFloat(m[2]);
      return m[1] === '>' ? x > y : m[1] === '<' ? x < y : m[1] === '>=' ? x >= y : m[1] === '<=' ? x <= y : x === y;
    }
  }
  return formatCell(raw).toLowerCase().includes(f.toLowerCase());
}

function compare(a: unknown, b: unknown, type: ColType): number {
  if (type === 'number') return (numericOf(a) ?? 0) - (numericOf(b) ?? 0);
  if (type === 'date') return Date.parse(String(a)) - Date.parse(String(b));
  return String(a).localeCompare(String(b), 'zh');
}

function downloadCsv(header: string[], lines: unknown[][], filename: string) {
  const esc = (v: unknown) => {
    const s = isEmpty(v) ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = '﻿' + [header, ...lines].map((l) => l.map(esc).join(',')).join('\r\n'); // BOM：Excel 正确识别中文
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${filename}_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function DataTable<R>({
  rows,
  columns,
  codeOf,
  nameOf,
  exportName,
  onOpen,
  rowTone,
  extraActions,
}: Props<R>) {
  const watch = useWatchlist();
  const types = useMemo(() => columns.map((c) => detectType(c, rows)), [columns, rows]);
  const recencyIdx = columns.findIndex((c) => c.recency);
  const rowIndex = useMemo(() => new Map(rows.map((r, i) => [r, i])), [rows]);

  const initialSort = (): { idx: number; order: SortOrder } => {
    if (recencyIdx >= 0) return { idx: recencyIdx, order: 'ascend' };
    const def = columns.findIndex((c) => c.defaultSort);
    return def >= 0 ? { idx: def, order: columns[def].defaultSort! } : { idx: -1, order: null };
  };

  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<Record<number, string>>({});
  const [sort, setSort] = useState(initialSort);
  const [recentDays, setRecentDays] = useState<number>(0);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    let out = rows.filter((r) => {
      if (q && !columns.some((c) => formatCell(c.value(r)).toLowerCase().includes(q))) return false;
      if (recencyIdx >= 0 && recentDays > 0) {
        const d = numericOf(columns[recencyIdx].value(r));
        if (d === null || d > recentDays) return false;
      }
      return columns.every((c, i) => matches(c.value(r), filters[i] ?? '', types[i]));
    });
    if (sort.idx >= 0 && sort.order) {
      const col = columns[sort.idx];
      const dir = sort.order === 'ascend' ? 1 : -1;
      out = [...out].sort((a, b) => {
        const av = col.value(a);
        const bv = col.value(b);
        if (isEmpty(av) && isEmpty(bv)) return 0;
        if (isEmpty(av)) return 1; // 空值永远排最后
        if (isEmpty(bv)) return -1;
        return compare(av, bv, types[sort.idx]) * dir;
      });
    }
    return out;
  }, [rows, columns, types, search, filters, sort, recencyIdx, recentDays]);

  const reset = () => {
    setSearch('');
    setFilters({});
    setRecentDays(0);
    setSort(initialSort());
  };

  const tableColumns: ColumnsType<R> = [
    {
      key: '__fav',
      title: <StarOutlined />,
      width: 36,
      fixed: 'left',
      align: 'center',
      render: (_, r) => {
        const code = codeOf(r);
        const on = watch.has(code);
        return (
          <Tooltip title={on ? '移出自选' : '加入自选'}>
            <button
              type="button"
              className={`fav-btn ${on ? 'is-on' : ''}`}
              aria-label={on ? '移出自选' : '加入自选'}
              onClick={(e) => {
                e.stopPropagation();
                watch.toggle(code, nameOf?.(r));
              }}
            >
              {on ? <StarFilled /> : <StarOutlined />}
            </button>
          </Tooltip>
        );
      },
    },
    ...columns.map((c, i) => ({
      key: c.key,
      title: c.title,
      width: c.width,
      ellipsis: c.ellipsis,
      align: (types[i] === 'number' ? 'right' : 'left') as 'right' | 'left',
      sorter: true,
      sortOrder: sort.idx === i ? sort.order : null,
      filteredValue: filters[i] ? [filters[i]] : null,
      filterIcon: (active: boolean) => <FilterFilled style={{ color: active ? 'var(--it-brand)' : undefined }} />,
      filterDropdown: ({ close }: { close: () => void }) => (
        <div className="col-filter" onKeyDown={(e) => e.stopPropagation()}>
          <Input
            size="small"
            autoFocus
            allowClear
            placeholder={types[i] === 'number' ? '如 >=5、<3、包含 12' : '包含…'}
            value={filters[i] ?? ''}
            onChange={(e) => setFilters((f) => ({ ...f, [i]: e.target.value }))}
            onPressEnter={close}
          />
        </div>
      ),
      render: (_: unknown, r: R) => (c.render ? c.render(r) : formatCell(c.value(r))),
    })),
    ...(extraActions
      ? [{ key: '__act', title: '', width: 64, fixed: 'right' as const, render: (_: unknown, r: R) => extraActions(r) }]
      : []),
  ];

  return (
    <div className="data-table">
      <div className="data-table-toolbar">
        <Input
          allowClear
          placeholder="全表搜索：代码 / 名称 / 任意列"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 260, maxWidth: '100%' }}
        />
        {recencyIdx >= 0 && (
          <Segmented
            size="small"
            value={recentDays}
            onChange={(v) => {
              setRecentDays(v as number);
              setSort({ idx: recencyIdx, order: 'ascend' });
            }}
            options={[
              { label: '全部', value: 0 },
              { label: '近3天', value: 3 },
              { label: '近7天', value: 7 },
              { label: '近15天', value: 15 },
            ]}
          />
        )}
        <span className="muted small num">
          显示 {visible.length} / {rows.length}
        </span>
        <span style={{ flex: 1 }} />
        <Button size="small" onClick={reset}>
          重置
        </Button>
        <Button
          size="small"
          icon={<DownloadOutlined />}
          onClick={() =>
            downloadCsv(
              columns.map((c) => c.title),
              visible.map((r) => columns.map((c) => c.value(r))),
              exportName,
            )
          }
        >
          导出CSV
        </Button>
      </div>
      <Table<R>
        size="small"
        rowKey={(r) => `${codeOf(r)}-${rowIndex.get(r)}`}
        columns={tableColumns}
        dataSource={visible}
        scroll={{ x: 'max-content' }}
        sticky={{ offsetHeader: 52 }}
        pagination={{ defaultPageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], hideOnSinglePage: true }}
        showSorterTooltip={false}
        onChange={(_p, _f, sorter) => {
          const s = Array.isArray(sorter) ? sorter[0] : sorter;
          const idx = columns.findIndex((c) => c.key === s?.columnKey);
          setSort({ idx: s?.order ? idx : -1, order: s?.order ?? null });
        }}
        rowClassName={(r) => {
          const tone = rowTone?.(r);
          return `${onOpen ? 'is-clickable' : ''} ${tone && tone !== 'none' ? `tone-${tone}` : ''}`;
        }}
        onRow={(r) => ({
          onClick: () => onOpen?.(codeOf(r), nameOf?.(r)),
        })}
      />
    </div>
  );
}
