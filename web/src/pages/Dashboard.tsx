import CyclePanel from '../components/CyclePanel';
import KpiStrip from '../components/KpiStrip';
import EmotionGateCard from '../components/EmotionGateCard';
import WorkbenchCard from '../components/WorkbenchCard';
import LadderPanel from '../components/LadderPanel';
import HotLimitCard from '../components/HotLimitCard';
import SectorFlowCard from '../components/SectorFlowCard';
import type { StockTarget } from '../App';

interface Props {
  onOpenStock: (code: string, name?: string) => void;
}

// 信息层级（对齐短线使用节奏）：
// 1. 三个周期并列（情绪 / 接力 / 低吸，各注依据与用途）+ 市场广度 KPI —— 一眼扫读
// 2. 行动摘要（能不能做、做多少）+ 今日作战台候选（做什么）
// 3. 龙头梯队（主线是谁、龙头几板、买点/卖点信号）
// 4. 涨停Top20 / 板块资金
// 宽屏（≥1600px）三栏一屏看完；中屏两栏；窄屏单栏。见 index.css .dash-grid
export default function Dashboard({ onOpenStock }: Props) {
  return (
    <>
      <CyclePanel />
      <KpiStrip />
      <div className="dash-grid">
        <div className="dash-left">
          <EmotionGateCard />
          <WorkbenchCard onOpenStock={onOpenStock} />
        </div>
        <div className="dash-center">
          <LadderPanel onOpenStock={onOpenStock} />
        </div>
        <div className="dash-right">
          <HotLimitCard onOpenStock={onOpenStock} />
          <SectorFlowCard />
        </div>
      </div>
    </>
  );
}

export type { StockTarget };
