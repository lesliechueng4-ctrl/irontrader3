"""
IronTrader 2.1 - 未来预测引擎
基于最新数据预测未来N天的走势
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from data_loader import load_and_process_data, load_stock_data
from features import generate_features
from model_engine import IronTraderXGB
from strategy_enhancements import StockClassifier
from xgboost import XGBRegressor

class FuturePredictor:
    """
    未来预测器：使用训练好的模型预测未来走势 (XGBoost Edition)
    """
    
    def __init__(self, ticker: str, lookback_days: int = 730):
        self.ticker = ticker
        self.lookback_days = lookback_days
        self.model = None
        self.scaler = None
        self.feature_names = None
        self.stock_type = None
        self.latest_data = None
        
    def train(self, force_retrain: bool = False):
        """
        使用最新历史数据训练模型
        """
        # (Cache loading logic omitted for brevity, assuming similar)

        # 计算日期范围
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%Y%m%d")
        
        print(f"📊 加载训练数据 (XGBoost): {self.ticker}")
        
        # 加载数据
        df = load_and_process_data(self.ticker, start_date, end_date, include_sentiment=True)
        
        # 特征工程 (Now uses TA-Lib)
        X, y, feature_names, scaler, clean_df = generate_features(df, verbose=False)
        
        self.feature_names = feature_names
        self.scaler = scaler
        self.latest_data = clean_df
        
        # 训练最终模型 (用于预测未来)
        # 我们使用全部数据训练一个XGBoost，用于预测明天
        print(f"🤖 训练最终XGBoost模型...")
        
        final_model = XGBRegressor(
            n_estimators=150,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.8,
            colsample_bytree=0.8,
            objective='reg:squarederror',
            n_jobs=-1,
            random_state=42
        )
        
        # 使用全部数据
        final_model.fit(X, y)
        
        self.model = final_model
        
        # 计算特征重要性
        feature_importance = final_model.feature_importances_
        active_features = np.sum(feature_importance > 1e-4)
        
        print(f"✓ 模型训练完成 (XGBoost)")
        print(f"   活跃特征数: {active_features}/{len(feature_names)}")
        
        return self
        
        # 保存模型到缓存
        try:
            from data_cache import get_cache
            cache = get_cache()
            model_data = {
                'model': self.model,
                'scaler': self.scaler,
                'feature_names': self.feature_names,
                'stock_type': self.stock_type,
                'latest_data': self.latest_data
            }
            cache.save_to_cache(self.ticker, 'model_predictor', model_data)
        except Exception as e:
            print(f"⚠ 模型缓存保存失败: {e}")
        
        return self
    
    def predict_future(self, n_days: int = 5):
        """
        预测未来N天的走势
        
        Args:
            n_days: 预测天数
            
        Returns:
            DataFrame with predictions
        """
        if self.model is None:
            raise ValueError("模型未训练，请先调用train()")
        
        print(f"\n🔮 预测未来 {n_days} 个交易日...")
        
        # 获取最新特征 (使用训练时的adjusted数据)
        latest_features = self.latest_data[self.feature_names].iloc[-1:].values
        
        # 预测
        latest_scaled = self.scaler.transform(latest_features)
        prediction = self.model.predict(latest_scaled)[0]
        
        # 获取当前价格 (优先使用实时Spot数据)
        try:
            import akshare as ak
            spot_df = ak.stock_zh_a_spot_em()
            spot_row = spot_df[spot_df['代码'] == self.ticker]
            if not spot_row.empty:
                current_price = float(spot_row['最新价'].values[0])
                # 使用当前日期
                current_date = pd.Timestamp(datetime.now().date())
                print(f"✓ 使用实时Spot价格: {current_price}")
            else:
                raise ValueError("Spot data not found")
        except Exception as e:
            print(f"⚠ 获取实时价格失败，尝试使用历史数据: {e}")
            # 回退到历史数据
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            try:
                raw_df = load_stock_data(self.ticker, start_date, end_date, adjust="")
                current_price = raw_df['Close'].iloc[-1]
                current_date = raw_df.index[-1]
            except Exception as e2:
                print(f"⚠ 获取历史不复权价格失败，使用复权价格: {e2}")
                current_price = self.latest_data['Close'].iloc[-1]
                current_date = self.latest_data.index[-1]
        
        # 生成预测结果
        predictions = []
        cumulative_return = 0
        
        for day in range(1, n_days + 1):
            daily_return = prediction
            cumulative_return += daily_return
            
            predicted_price = current_price * (1 + cumulative_return)
            
            # 预测日期（跳过周末）
            pred_date = current_date + timedelta(days=day)
            while pred_date.weekday() >= 5:
                pred_date += timedelta(days=1)
            
            predictions.append({
                'date': pred_date,
                'day': day,
                'predicted_return': daily_return,
                'cumulative_return': cumulative_return,
                'predicted_price': predicted_price,
                'confidence': abs(prediction) * 100,
                'signal': '做多' if daily_return > 0.002 else ('观望' if daily_return > -0.002 else '做空')
            })
        
        pred_df = pd.DataFrame(predictions)
        
        print(f"✓ 预测完成")
        print(f"   当前价格: {current_price:.2f}")
        print(f"   预测收益: {prediction*100:.2f}%")
        
        # 添加当前信息
        self.current_info = {
            'ticker': self.ticker,
            'stock_type': self.stock_type,
            'current_price': float(current_price),
            'current_date': current_date.strftime('%Y-%m-%d'),
            'prediction': float(prediction),
            'feature_importance': {
                name: float(imp) 
                for name, imp in zip(self.feature_names, self.model.feature_importances_)
                if imp > 1e-4
            }
        }
        
        return pred_df
    
    def get_historical_performance(self, days: int = 60):
        """
        获取最近N天的历史表现（用于图表）
        返回OHLCV数据用于K线图 (使用不复权数据以匹配用户看到的行情)
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d") # 多取一些保证够用
        
        try:
            # 加载不复权数据
            raw_df = load_stock_data(self.ticker, start_date, end_date, adjust="")
            recent_data = raw_df.tail(days)[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            recent_data['Date'] = recent_data.index
            return recent_data
        except Exception as e:
            print(f"⚠ 获取历史K线失败，使用复权数据: {e}")
            if self.latest_data is None:
                return None
            recent_data = self.latest_data.tail(days)[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            recent_data['Date'] = recent_data.index
            return recent_data


def quick_predict(ticker: str, n_days: int = 5):
    """
    快速预测接口
    
    Returns:
        dict with predictions and info
    """
    predictor = FuturePredictor(ticker)
    predictor.train()
    pred_df = predictor.predict_future(n_days)
    historical = predictor.get_historical_performance(60)
    
    # 准备图表数据 (OHLC + Volume)
    chart_data = None
    if historical is not None:
        chart_data = []
        for _, row in historical.iterrows():
            chart_data.append({
                'date': row['Date'].strftime('%Y-%m-%d'),
                'open': float(row['Open']),
                'close': float(row['Close']),
                'low': float(row['Low']),
                'high': float(row['High']),
                'volume': float(row['Volume'])
            })
    
    return {
        'info': predictor.current_info,
        'predictions': pred_df.to_dict('records'),
        'historical': historical.to_dict('records') if historical is not None else [],
        'chart_data': chart_data
    }


if __name__ == "__main__":
    # 测试
    import sys
    
    ticker = sys.argv[1] if len(sys.argv) > 1 else "600151"
    
    print(f"\n{'='*60}")
    print(f"测试未来预测功能: {ticker}")
    print(f"{'='*60}")
    
    result = quick_predict(ticker, n_days=5)
    
    print(f"\n当前信息:")
    print(f"  股票: {result['info']['ticker']}")
    print(f"  类型: {result['info']['stock_type']}")
    print(f"  当前价格: {result['info']['current_price']:.2f}")
    print(f"  预测收益: {result['info']['prediction']*100:.2f}%")
    
    print(f"\n未来5天预测:")
    for pred in result['predictions']:
        print(f"  Day {pred['day']}: "
              f"{pred['predicted_price']:.2f} "
              f"({pred['cumulative_return']*100:+.2f}%) "
              f"[{pred['signal']}]")
    
    print(f"\n重要特征:")
    for feat, weight in sorted(
        result['info']['feature_importance'].items(),
        key=lambda x: abs(x[1]),
        reverse=True
    )[:5]:
        print(f"  {feat}: {weight:.4f}")
