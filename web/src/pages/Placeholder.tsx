import { Button, Result } from 'antd';

interface Props {
  title: string;
  anchor: string; // 旧版对应标签：/legacy#scanners 等
}

// 过渡期占位：指向旧版对应功能，随迭代逐个替换为原生 React 实现
export default function Placeholder({ title, anchor }: Props) {
  return (
    <div className="placeholder-panel">
      <Result
        status="info"
        title={`${title} · 重构进行中`}
        subTitle="该模块还在迁移到新版。迁移完成前，请在旧版界面中使用完整功能。"
        extra={
          <Button type="primary" href={`/legacy#${anchor}`} target="_blank">
            在旧版中打开{title}
          </Button>
        }
      />
    </div>
  );
}
