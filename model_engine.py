"""
IronTrader 2.0 - Module 3: ARGO Engine
实现滚动窗口 + Lasso回归的动态权重调整
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import Lasso
from sklearn.preprocessing import StandardScaler
from typing import Tuple, List
import warnings
warnings.filterwarnings('ignore')


from xgboost import XGBRegressor
import joblib

class IronTraderXGB:
    """
    IronTrader 3.0 Engine: XGBoost + Rolling Forecast
    """
    
    def __init__(self, window_size: int = 60):
        """
        Args:
            window_size: Minimum days to start training
        """
        self.window_size = window_size
        print(f"\n🚀 IronTrader XGB 引擎初始化")
        print(f"  - 最小窗口: {window_size} 交易日")
    
    def walk_forward_predict(
        self,
        X: np.ndarray,
        y: np.ndarray,
        dates: pd.DatetimeIndex,
        feature_names: List[str],
        verbose: bool = True
    ) -> Tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
        """
        严谨的滚动预测 (Expanding Window)
        对于时刻 t 的预测，只使用 0 到 t-1 的数据进行训练。
        """
        n_samples = len(X)
        if n_samples < self.window_size + 10:
            raise ValueError(f"数据不足，需要 {self.window_size} 天，仅有 {n_samples}")
            
        predictions = []
        feature_importances = []
        pred_dates = []
        
        # 批量训练优化：
        # 每天都重训太慢，我们每5天重训一次，或者使用增量学习（但XGBoost增量学习较复杂）
        # 这里为了严谨性，每 N 天重训一次，中间天数使用最近一次的模型
        retrain_step = 5 
        current_model = None
        
        if verbose: print(f"🚀 开始滚动预测 (Expanding Window)...")
        
        for t in range(self.window_size, n_samples):
            # 1. 预测时刻 t
            # 获取 t 时刻的特征 (这些特征是基于 t-1 及以前的数据计算的)
            X_current = X[t:t+1]
            
            # 定期重训模型 (或者第一轮)
            if (t - self.window_size) % retrain_step == 0:
                # 训练集: 0 到 t-1
                X_train = X[:t]
                y_train = y[:t]
                
                # 配置XGBoost
                model = XGBRegressor(
                    n_estimators=100,
                    learning_rate=0.05,
                    max_depth=3,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    objective='reg:squarederror',
                    n_jobs=-1,
                    random_state=42
                )
                
                model.fit(X_train, y_train)
                current_model = model
                
                if verbose and (t - self.window_size) % 50 == 0:
                     print(f"  📅 {dates[t].strftime('%Y-%m-%d')} | 重训模型 | 样本数: {len(y_train)}")

            # 预测
            pred = current_model.predict(X_current)[0]
            
            predictions.append(pred)
            feature_importances.append(current_model.feature_importances_)
            pred_dates.append(dates[t])
            
        predictions = np.array(predictions)
        feature_importances = np.array(feature_importances)
        pred_dates = pd.DatetimeIndex(pred_dates)
        
        # 统计特征重要性 (取最后一次模型的)
        avg_imp = np.mean(feature_importances, axis=0)
        top_idx = np.argsort(avg_imp)[-5:][::-1]
        
        if verbose:
            print(f"\n🏆 关键特征 (Top 5):")
            for idx in top_idx:
                print(f"  {feature_names[idx]}: {avg_imp[idx]:.4f}")
                
        return predictions, feature_importances, pred_dates

    def get_feature_importance_df(self, importances, feature_names, dates):
        return pd.DataFrame(importances, index=dates, columns=feature_names)


if __name__ == "__main__":
    # 测试
    from data_loader import load_and_process_data
    from features import generate_features
    
    print("\n" + "="*60)
    print("🧪 测试ARGO引擎")
    print("="*60)
    
    # 1. 加载数据
    df = load_and_process_data(
        ticker="600151",
        start_date="20230101",
        end_date="20241231"
    )
    
    # 2. 生成特征
    X, y, feature_names, scaler, clean_df = generate_features(df, verbose=False)
    
    # 3. 初始化ARGO引擎
    argo = IronTraderARGO(window_size=30, lasso_alpha=0.01)
    
    # 4. 运行预测
    predictions, weights_history, pred_dates = argo.walk_forward_predict(
        X=X,
        y=y,
        dates=clean_df.index,
        feature_names=feature_names,
        verbose=True
    )
    
    # 5. 查看特征权重DataFrame
    weights_df = argo.get_feature_importance_df(weights_history, feature_names, pred_dates)
    
    print("\n特征权重历史 (前5行):")
    print(weights_df.head())
    
    print("\n特征权重统计:")
    print(weights_df.describe())
