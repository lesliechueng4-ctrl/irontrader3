// 交易时段判断（A 股 09:15-11:30 / 13:00-15:00，周一至周五，按北京时间）
// 用于轮询降级：非交易时段拉长轮询间隔，减少无意义请求。
// 注意：不含法定节假日，节假日按"非交易日"的判断以后端 market-state 为准。

const SH_PARTS = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Shanghai',
  hour12: false,
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

function shanghaiClock(now: Date): { weekday: string; minutes: number } {
  const parts = Object.fromEntries(SH_PARTS.formatToParts(now).map((p) => [p.type, p.value]));
  const hour = Number(parts.hour) % 24; // 某些环境午夜返回 "24"
  return { weekday: parts.weekday, minutes: hour * 60 + Number(parts.minute) };
}

export function isTradingTime(now = new Date()): boolean {
  const { weekday, minutes } = shanghaiClock(now);
  if (weekday === 'Sat' || weekday === 'Sun') return false;
  const morning = minutes >= 9 * 60 + 15 && minutes <= 11 * 60 + 30;
  const afternoon = minutes >= 13 * 60 && minutes <= 15 * 60;
  return morning || afternoon;
}

/** 盘中返回 fast 间隔，非盘中返回 slow 间隔（false = 不轮询） */
export function pollInterval(trading: number, idle: number | false = 120_000): number | false {
  return isTradingTime() ? trading : idle;
}

const SH_DATE = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }); // YYYY-MM-DD

/** 北京时间的今天 YYYY-MM-DD */
export function shanghaiToday(now = new Date()): string {
  return SH_DATE.format(now);
}
