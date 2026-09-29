// 单票研报的地址：?code=600519&sname=贵州茅台
// 名称用 sname 而不是 name：name 已被日内抽屉（?stock=&name=）占用，两者可同时出现在地址栏。
export function researchSearch(code: string, name?: string) {
  const q = new URLSearchParams({ code });
  if (name) q.set('sname', name);
  return `?${q.toString()}`;
}
