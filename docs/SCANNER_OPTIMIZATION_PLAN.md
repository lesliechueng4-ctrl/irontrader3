# IronTrader 3.0 - 扫描器性能优化方案

## 📊 当前性能瓶颈分析

### 🔴 严重瓶颈：低吸扫描器

**当前流程**：
```
1. 获取全A股列表（5000+只）
2. 分10+批次获取实时行情（每批500只）
3. 筛选后仅用前40只进行精细评分
4. 每只股票调用5个独立评分器
```

**问题**：
- ❌ 获取5000只数据，实际只用40只（**浪费率 99%**）
- ❌ 5个维度重复获取K线数据（**网络请求 200次**）
- ❌ 无增量扫描，每次全量重新扫描
- ⏱️ **当前耗时：60-90秒**

### 🟡 中等瓶颈：洗盘形态扫描器

**当前流程**：
```
1. 对全A股逐一下载120天历史数据
2. 串行尝试多个数据源（akshare → yahoo → cache）
3. 每次重新计算MA和形态识别
```

**问题**：
- ❌ 无预筛选，扫描5000只股票
- ❌ 数据源回退慢，失败重试浪费时间
- ⏱️ **当前耗时：5-8分钟**

### 🟢 轻度瓶颈：扫描器路由

**问题**：
- ❌ 全局锁机制，同时只能运行1个任务
- ❌ 无任务队列，多请求直接返回 409

---

## 🚀 优化方案（按优先级）

### 🔴 **高优先级**（立即实施，收益最大）

#### 1. 低吸扫描：智能预筛选 ⭐⭐⭐⭐⭐

**问题**：获取5000只数据，只用40只

**解决方案**：使用轻量级 API 直接筛选
```python
def _pre_screen_optimized(self, progress_callback=None):
    """智能预筛选：减少90%数据获取量"""
    import akshare as ak
    
    # 1次API调用获取全市场实时行情（含涨跌幅、价格、成交额）
    df_spot = ak.stock_zh_a_spot_em()
    
    # 直接在DataFrame上过滤（向量化操作）
    filtered = df_spot[
        (df_spot['最新价'] > 3) &                    # 价格>3元
        (df_spot['涨跌幅'] >= -7) & 
        (df_spot['涨跌幅'] <= 0) &                   # 回调中（-7% ~ 0%）
        (df_spot['成交额'] > 20000000) &              # 成交额>2000万
        (~df_spot['名称'].str.contains('ST|退', na=False))
    ]
    
    # 按成交额排序，取前200只（预留缓冲）
    candidates = filtered.nlargest(200, '成交额')['代码'].tolist()
    
    logger.info(f"预筛选完成：从 {len(df_spot)} 只股票中筛选出 {len(candidates)} 只候选")
    return candidates[:40]  # 最终返回40只
```

**预期收益**：
- 数据获取量：5000只 → 1次API调用 ⬇️ **99%**
- 时间节省：30秒 → 5秒 ⬇️ **80%**
- 实施难度：⭐ 低（30分钟）

---

#### 2. 低吸扫描：数据批量预加载 ⭐⭐⭐⭐⭐

**问题**：5个维度重复获取K线，网络请求200次

**解决方案**：批量预加载共享数据
```python
class LowBuyEngine:
    def batch_analyze(self, stock_list: List[str]) -> List[dict]:
        """批量分析（优化版）"""
        # 🆕 批量预加载所有股票的共享数据
        self._preload_shared_data(stock_list)
        
        # 分析每只股票（现在会命中缓存）
        results = []
        for code in stock_list:
            result = self.analyze(code)
            results.append(result)
        return results
    
    def _preload_shared_data(self, stock_list: List[str]):
        """批量预加载，减少网络请求"""
        logger.info(f"开始批量预加载 {len(stock_list)} 只股票数据...")
        
        # 1. 批量获取实时行情（AKShare支持批量）
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            for code in stock_list:
                # 触发缓存
                self.fetcher._set_cache(f"realtime:{code}", 
                                       df[df['代码'] == code].to_dict('records')[0])
        except Exception as e:
            logger.warning(f"批量获取实时行情失败: {e}")
        
        # 2. 并发获取K线数据
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.fetcher.get_stock_hist, code, adjust='qfq'): code 
                for code in stock_list
            }
            for future in as_completed(futures):
                code = futures[future]
                try:
                    future.result()  # 触发缓存，不需要返回值
                except Exception as e:
                    logger.warning(f"预加载 {code} K线失败: {e}")
        
        logger.info("批量预加载完成")
```

**预期收益**：
- 网络请求：200次 → 40次 ⬇️ **80%**
- 时间节省：40秒 → 10秒 ⬇️ **75%**
- 实施难度：⭐⭐ 中（1小时）

---

#### 3. 洗盘扫描：快速预筛选 ⭐⭐⭐⭐

**问题**：对全A股5000只下载120天数据

**解决方案**：增加预筛选层
```python
def _pre_screen_wash_candidates(stock_pool='all_a') -> List[str]:
    """快速预筛选：仅保留符合基础条件的股票"""
    import akshare as ak
    
    logger.info("开始洗盘形态快速预筛选...")
    
    # 获取实时行情
    df = ak.stock_zh_a_spot_em()
    
    # 预筛选条件
    candidates = df[
        (df['最新价'] > 3) &                          # 价格>3元
        (df['涨跌幅'] > -8) &                         # 排除大跌股
        (df['成交额'] > 50000000) &                   # 成交额>5000万
        (df['换手率'] > 1) &                          # 有一定活跃度
        (~df['名称'].str.contains('ST|退', na=False))
    ]
    
    result = candidates['代码'].tolist()
    logger.info(f"预筛选完成：从 {len(df)} 只缩减至 {len(result)} 只")
    
    return result  # 返回约800-1500只
```

**在 wash_pattern_scanner.py 中集成**：
```python
def scan(cfg: ScanConfig, show_progress=True):
    """扫描入口（优化版）"""
    
    # 🆕 如果是全A股扫描，先预筛选
    if cfg.stock_pool == 'all_a':
        stocks = _pre_screen_wash_candidates()
        logger.info(f"预筛选后待扫描股票数: {len(stocks)}")
    else:
        stocks = get_stock_pool(cfg.stock_pool, cfg.pool_source)
    
    # 限制数量
    if cfg.max_stocks > 0:
        stocks = stocks[:cfg.max_stocks]
    
    # ... 后续扫描逻辑
```

**预期收益**：
- 扫描范围：5000只 → 800-1500只 ⬇️ **70%**
- 数据下载量：减少 70%
- 时间节省：8分钟 → 3分钟 ⬇️ **60%**
- 实施难度：⭐ 低（30分钟）

---

### 🟡 **中优先级**（近期实施）

#### 4. 任务队列替代全局锁 ⭐⭐⭐

**问题**：同时只能运行1个任务，多请求返回409

**解决方案**：
```python
import queue
from threading import Thread

# 任务队列（最多排队5个）
_SCAN_TASK_QUEUE = queue.Queue(maxsize=5)
_SCAN_WORKER_THREAD = None

def _scan_worker():
    """后台工作线程：串行处理扫描任务"""
    while True:
        job_id, task_func, task_args = _SCAN_TASK_QUEUE.get()
        try:
            logger.info(f"开始执行任务 {job_id}")
            task_func(job_id, *task_args)
        except Exception as e:
            logger.error(f"任务 {job_id} 执行失败: {e}")
        finally:
            _SCAN_TASK_QUEUE.task_done()

@scanner_bp.route("/api/scanners/wash-pattern/start", methods=["POST"])
def wash_pattern_scan_start():
    """启动洗盘扫描（队列版）"""
    global _SCAN_WORKER_THREAD
    
    # 启动工作线程（首次调用时）
    if _SCAN_WORKER_THREAD is None:
        _SCAN_WORKER_THREAD = Thread(target=_scan_worker, daemon=True)
        _SCAN_WORKER_THREAD.start()
    
    try:
        params = _wash_pattern_params_from_request()
        job = _create_scan_job("wash_pattern")
        
        # 加入队列（非阻塞）
        _SCAN_TASK_QUEUE.put_nowait((job["id"], _run_wash_pattern_job, (params,)))
        
        queue_size = _SCAN_TASK_QUEUE.qsize()
        return jsonify({
            "success": True, 
            "job_id": job["id"], 
            "job": job,
            "queue_position": queue_size  # 告诉用户排在第几位
        })
    except queue.Full:
        return jsonify({
            "success": False, 
            "error": "任务队列已满（最多5个），请稍后再试"
        }), 429
```

**预期收益**：
- 用户体验：拒绝 → 排队
- 并发能力：1任务 → 5任务排队
- 实施难度：⭐⭐ 中（1小时）

---

#### 5. 数据源智能选择 ⭐⭐⭐

**问题**：auto模式串行尝试多个数据源，失败慢

**解决方案**：
```python
class DataSourceRouter:
    """智能数据源路由"""
    
    def __init__(self):
        self.source_health = {
            "akshare": 100,  # 健康度评分
            "yahoo": 100,
            "cache": 50
        }
        self.last_check = time.time()
        self.lock = Lock()
    
    def get_best_source(self) -> str:
        """返回健康度最高的数据源"""
        # 每5分钟重新评估
        if time.time() - self.last_check > 300:
            self._health_check()
        
        return max(self.source_health, key=self.source_health.get)
    
    def _health_check(self):
        """并发测试各数据源响应时间"""
        with self.lock:
            logger.info("开始数据源健康检查...")
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(self._ping_source, "akshare"): "akshare",
                    executor.submit(self._ping_source, "yahoo"): "yahoo",
                }
                
                for future in as_completed(futures):
                    source = futures[future]
                    latency = future.result()
                    
                    # 更新健康度
                    if latency < 0:  # 失败
                        self.source_health[source] = 0
                    elif latency < 2:  # 快速
                        self.source_health[source] = 100
                    else:  # 慢
                        self.source_health[source] = 50
            
            self.last_check = time.time()
            logger.info(f"健康检查完成: {self.source_health}")
    
    def _ping_source(self, source: str) -> float:
        """测试数据源响应时间"""
        start = time.time()
        try:
            if source == "akshare":
                import akshare as ak
                ak.stock_zh_a_spot_em()  # 测试请求
            elif source == "yahoo":
                import yfinance as yf
                yf.download("000001.SZ", period="1d")
            
            return time.time() - start
        except Exception:
            return -1  # 失败
```

**预期收益**：
- 失败场景时间：减少 50%
- 成功率：提升 20%
- 实施难度：⭐⭐ 中（1.5小时）

---

#### 6. 增量扫描 + 结果缓存 ⭐⭐⭐⭐

**问题**：每次全量扫描，未利用历史结果

**解决方案**：
```python
class IncrementalScanner:
    """增量扫描管理器"""
    
    def __init__(self, cache_dir="cache/scan_results"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True, parents=True)
    
    def scan_incremental(self, stock_list: List[str], scan_func, 
                        scan_type: str) -> pd.DataFrame:
        """增量扫描：仅扫描新增/变化的股票"""
        today = date.today().isoformat()
        cache_file = self.cache_dir / f"{scan_type}_{today}.pkl"
        
        # 加载今日缓存
        if cache_file.exists():
            logger.info(f"加载今日缓存: {cache_file}")
            cached_results = pd.read_pickle(cache_file)
            cached_codes = set(cached_results['代码'])
            logger.info(f"缓存中已有 {len(cached_codes)} 只股票")
        else:
            cached_results = pd.DataFrame()
            cached_codes = set()
        
        # 仅扫描未缓存的股票
        new_codes = [c for c in stock_list if c not in cached_codes]
        logger.info(f"需要扫描的新股票: {len(new_codes)} 只")
        
        if new_codes:
            new_results = scan_func(new_codes)
            all_results = pd.concat([cached_results, new_results], ignore_index=True)
            
            # 保存更新后的缓存
            all_results.to_pickle(cache_file)
            logger.info(f"缓存已更新: {len(all_results)} 只股票")
        else:
            all_results = cached_results
            logger.info("无新增股票，使用缓存结果")
        
        return all_results

# 使用示例
incremental_scanner = IncrementalScanner()

def scan_with_cache(stock_list):
    return incremental_scanner.scan_incremental(
        stock_list, 
        original_scan_function,
        "wash_pattern"
    )
```

**预期收益**：
- 重复扫描时间：减少 **90%**（命中缓存时）
- 每日首次扫描：无影响
- 实施难度：⭐⭐ 中（1小时）

---

### 🟢 **低优先级**（长期优化）

#### 7. Numba JIT 加速技术指标计算

```python
from numba import jit

@jit(nopython=True)
def fast_ma(prices, window):
    """JIT加速的移动平均计算"""
    result = np.empty(len(prices))
    for i in range(len(prices)):
        if i < window - 1:
            result[i] = np.nan
        else:
            result[i] = np.mean(prices[i-window+1:i+1])
    return result
```

**预期收益**：
- 计算速度：提升 2-3倍
- 实施难度：⭐ 低（30分钟）

---

## 📊 综合收益评估

### 实施高优先级后的效果

| 扫描器 | 优化前 | 优化后 | 提升 |
|--------|--------|--------|------|
| **低吸扫描** | 60-90秒 | 10-15秒 | ⬇️ **85%** |
| **洗盘扫描** | 5-8分钟 | 2-3分钟 | ⬇️ **60%** |
| **用户体验** | 拒绝请求 | 任务排队 | ⬆️ 显著 |

### 实施成本

| 优先级 | 工作量 | 预期时间 |
|--------|--------|----------|
| 🔴 高优先级 | 3个优化项 | 2-3小时 |
| 🟡 中优先级 | 3个优化项 | 3-4小时 |
| 🟢 低优先级 | 可选 | 0.5-1小时 |

---

## 🚀 快速实施路线

### Phase 1（本周，高优先级）
**时间**: 2-3小时  
**收益**: 性能提升 70-85%

1. ✅ 低吸智能预筛选（30分钟）
2. ✅ 洗盘快速预筛选（30分钟）
3. ✅ 数据批量预加载（1小时）

### Phase 2（下周，中优先级）
**时间**: 3-4小时  
**收益**: 用户体验显著提升

4. 任务队列机制（1小时）
5. 数据源智能选择（1.5小时）
6. 增量扫描缓存（1小时）

### Phase 3（可选）
7. Numba JIT 加速（30分钟）

---

## 📝 相关文件

- `low_buy_engine.py` - 低吸扫描器
- `wash_pattern_scanner.py` - 洗盘扫描器
- `scanner_routes.py` - 扫描器路由
- `data_fetcher.py` - 数据获取层

---

**建议立即开始实施高优先级优化！**  
**预计 2-3 小时即可完成，性能提升 70-85%！** 🚀

---

**文档生成时间**: 2026-06-10  
**分析来源**: Claude Agent 深度分析  
**版本**: IronTrader 3.0 Phase 3
