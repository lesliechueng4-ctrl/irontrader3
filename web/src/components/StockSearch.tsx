import { useEffect, useRef, useState } from 'react';
import { AutoComplete, Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { searchStocks } from '../api/hooks';

interface Option {
  value: string;
  label: string;
  name: string;
}

interface Props {
  onPick: (code: string, name?: string) => void;
  placeholder?: string;
  size?: 'middle' | 'large';
  autoFocus?: boolean;
  style?: React.CSSProperties;
}

/** 代码 / 名称搜索框：输入即联想（250ms 防抖），回车时若是 6 位代码直接打开 */
export default function StockSearch({ onPick, placeholder, size = 'middle', autoFocus, style }: Props) {
  const [text, setText] = useState('');
  const [options, setOptions] = useState<Option[]>([]);
  const timer = useRef<number>();
  const seq = useRef(0);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const onSearch = (q: string) => {
    setText(q);
    window.clearTimeout(timer.current);
    const query = q.trim();
    if (!query) {
      setOptions([]);
      return;
    }
    timer.current = window.setTimeout(async () => {
      const mine = ++seq.current;
      try {
        const results = await searchStocks(query);
        if (mine !== seq.current) return; // 丢弃过期的响应
        setOptions(
          results
            .filter((r) => /^\d{6}$/.test(String(r.code)))
            .slice(0, 10)
            .map((r) => ({ value: r.code, label: `${r.name}  ${r.code}`, name: r.name })),
        );
      } catch {
        if (mine === seq.current) setOptions([]);
      }
    }, 250);
  };

  const pick = (code: string, name?: string) => {
    setText('');
    setOptions([]);
    onPick(code, name);
  };

  return (
    <AutoComplete
      options={options}
      value={text}
      onSearch={onSearch}
      onChange={setText}
      onSelect={(value: string, opt: Option) => pick(value, opt.name)}
      style={style}
      autoFocus={autoFocus}
    >
      <Input
        size={size}
        prefix={<SearchOutlined />}
        placeholder={placeholder ?? '输入代码或名称（如 600519 / 茅台）'}
        allowClear
        onPressEnter={() => {
          const code = text.trim();
          // 下拉里有高亮项时由 onSelect 处理；这里只兜底"直接敲了 6 位代码"
          if (/^\d{6}$/.test(code) && !options.length) pick(code);
        }}
      />
    </AutoComplete>
  );
}
