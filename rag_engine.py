"""
IronTrader 3.0 - Module 4: RAG Engine
Retrieval-Augmented Generation for Stock Analysis
"""
import akshare as ak
import requests
import json
import traceback
from datetime import datetime

class IronRAG:
    """
    RAG Logic:
    1. Retrieve: Get News from Akshare
    2. Augment: Combine with Technical Data
    3. Generate: Call SiliconFlow LLM
    """
    
    def __init__(self):
        self.api_key = "sk-qwwbmcoborsxuhnqnsgmwytzhcogevtzewuaiaonqlqmyvni"
        self.api_url = "https://api.siliconflow.com/v1/chat/completions"
        self.model = "deepseek-ai/DeepSeek-V3" # Fallback to V3 if 3.2 not found, usually V3 is stable
        
    def get_market_news(self, ticker: str):
        """Retrieve recent news for a specific stock"""
        try:
            print(f"🔍 RAG: Retrieving news for {ticker}...")
            # Use Akshare to get individual stock news
            news_df = ak.stock_news_em(symbol=ticker)
            
            # Take top 5 most recent
            news_items = []
            for _, row in news_df.head(5).iterrows():
                news_items.append(f"- [{row['发布时间']}] {row['新闻标题']}: {row['新闻内容'][:100]}...")
            
            return "\n".join(news_items)
        except Exception as e:
            print(f"⚠ News Retrieval Phase Failed: {e}")
            return "No recent news available (API Error)."

    def generate_report(self, ticker: str, technical_summary: dict):
        """
        Orchestrate the RAG flow
        """
        # 1. Retrieve
        news_context = self.get_market_news(ticker)
        
        # 2. Augment (Construct Prompt)
        prompt = f"""
你是一名资深金融分析师，请根据以下[技术面]和[消息面]数据，为股票 {ticker} 生成一份简短的投资分析报告。

[技术面分析]
- 预测引擎: IronTrader XGBoost
- 未来5天预测收益: {technical_summary.get('prediction', 0)*100:.2f}%
- 当前趋势: {'看涨' if technical_summary.get('prediction', 0) > 0 else '看跌'}
- 关键特征: {', '.join(list(technical_summary.get('feature_importance', {}).keys())[:3])}

[最新消息面]
{news_context}

[分析要求]
1. 结合消息面和技术面，判断二者由于共振还背离？
2. 给出明确的操作建议（买入/持有/卖出）。
3. 如果有重大风险（如立案、减持），请高亮警告。
4. 输出格式为Markdown，字数控制在300字以内。
        """
        
        # 3. Generate
        print("🧠 RAG: Calling LLM for generation...")
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a helpful financial assistant."},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "temperature": 0.7
            }
            
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                return content
            else:
                return f"LLM Generation Failed: {response.status_code} - {response.text}"
                
        except Exception as e:
            traceback.print_exc()
            return f"RAG System Error: {str(e)}"

# Singleton
rag_engine = IronRAG()
