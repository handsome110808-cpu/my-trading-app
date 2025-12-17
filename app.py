import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

# --- 1. 頁面設定 (台灣看盤風格) ---
st.set_page_config(
    page_title="台股智庫 - Pro Trader Terminal",
    page_icon="🇹🇼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定義 CSS (深色模式優化 + 台灣紅漲綠跌)
st.markdown("""
<style>
    .big-font { font-size: 24px !important; font-weight: bold; }
    .up-color { color: #ff3b30 !important; }
    .down-color { color: #30d158 !important; }
    div.stButton > button { width: 100%; }
</style>
""", unsafe_allow_html=True)

# --- 2. 核心數據與策略函數 ---
@st.cache_data(ttl=300)
def get_tw_stock_data(ticker):
    # 台股代號需加上 .TW
    stock_id = f"{ticker}.TW"
    
    # 抓取 1 年數據以計算長均線
    # 針對剛上市或數據較少的 ETF，加入錯誤處理
    try:
        df = yf.download(stock_id, period="1y", interval="1d", progress=False)
    except Exception:
        return None
    
    # 處理 yfinance 可能回傳 MultiIndex 的情況
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if df.empty:
        return None
    
    # --- 計算台股關鍵指標 ---
    # 1. 均線系統 (MA)
    df['MA_5'] = ta.sma(df['Close'], length=5)   # 週線
    df['MA_20'] = ta.sma(df['Close'], length=20) # 月線 (生命線)
    df['MA_60'] = ta.sma(df['Close'], length=60) # 季線 (趨勢線)

    # 2. MACD (動能)
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    # 確保 MACD 計算成功再合併
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        # 重新命名欄位以利識別
        df.rename(columns={
            df.columns[-3]: 'MACD_Line',
            df.columns[-2]: 'MACD_Hist',
            df.columns[-1]: 'MACD_Signal'
        }, inplace=True)
    else:
        # 若數據太少無法計算 MACD，補 0 避免報錯
        df['MACD_Line'] = 0
        df['MACD_Hist'] = 0
        df['MACD_Signal'] = 0

    # 3. 籌碼/量能分析
    df['Vol_MA_5'] = ta.sma(df['Volume'], length=5)
    
    return df

def analyze_strategy(df):
    if df is None or len(df) < 60:
        return "數據不足", "gray", ["新上市或數據過少，無法計算技術指標"], 0

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    score = 0
    signals = []
    
    # --- 經理人邏輯判定 ---
    
    # 1. 趨勢判定 (權重 40%)
    if curr['Close'] > curr['MA_20'] and curr['MA_20'] > curr['MA_60']:
        score += 40
        signals.append("✅ 多頭排列 (站穩月季線)")
    elif curr['Close'] < curr['MA_20']:
        score -= 20
        signals.append("⚠️ 跌破月線 (短線轉弱)")
    else:
        signals.append("⚪ 均線糾結或盤整")
        
    # 2. 動能判定 (權重 30%)
    if curr['MACD_Hist'] > 0 and curr['MACD_Hist'] > prev['MACD_Hist']:
        score += 30
        signals.append("✅ MACD 動能增強 (紅柱放大)")
    elif curr['MACD_Hist'] < 0:
        score -= 20
        signals.append("🔴 MACD 空方控盤")
        
    # 3. 量能判定 (權重 30%)
    if curr['Vol_MA_5'] > 0 and curr['Volume'] > curr['Vol_MA_5'] * 1.3:
        score += 30
        signals.append("🔥 爆量攻擊 (資金進場)")
    elif curr['Vol_MA_5'] > 0 and curr['Volume'] < curr['Vol_MA_5'] * 0.7:
        signals.append("⚪ 量縮整理")

    # 綜合建議
    if score >= 70:
        action = "積極買進 (Strong Buy)"
        color = "red"
    elif score >= 30:
        action = "區間操作 / 續抱 (Hold)"
        color = "orange"
    else:
        action = "減碼 / 觀望 (Sell/Avoid)"
        color = "green"
        
    return action, color, signals, score

# --- 新增功能：發送 LINE 通知 ---
def send_line_notify(token, message):
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": "Bearer " + token}
    data = {"message": message}
    try:
        r = requests.post(url, headers=headers, data=data)
        return r.status_code == 200
    except Exception:
        return False

# --- 3. UI 介面設計 ---

# 側邊欄
with st.sidebar:
    st.title("🇹🇼 台股戰情室")
    st.markdown("---")
    
    # 【更新重點】這裡加入了您要求的股票清單
    stock_options = [
        "0050 元大台灣50", 
        "0056 元大高股息", 
        "00737 國泰AI+Robo", 
        "2330 台積電"
    ]
    
    target = st.radio("選擇標的", stock_options)
    ticker = target.split(" ")[0]
    
    st.markdown("---")
    st.header("🔔 LINE 通知設定")
    line_token = st.text_input("輸入 LINE Notify Token", type="password", help="請至 LINE Notify 官網申請權杖")
    
    st.info("""
    **經理人觀點：**
    * 0050/2330：看外資動向與季線
    * 0056：看殖利率與月線支撐
    * 00737：看AI產業動能與美股連動
    """)

# 主畫面
st.header(f"📊 {target} 專業技術分析")

# 獲取數據
df = get_tw_stock_data(ticker)

if df is None:
    st.error(f"❌ 無法取得 {ticker} 數據，請確認代號是否正確或檢查網路連線。")
else:
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # 計算漲跌
    change = last_row['Close'] - prev_row['Close']
    pct_change = (change / prev_row['Close']) * 100
    price_color = "#ff3b30" if change >= 0 else "#30d158" # 紅漲綠跌
    arrow = "▲" if change >= 0 else "▼"

    # 顯示價格看板
    col1, col2, col3 = st.columns([1.5, 2, 1.5])

    with col1:
        st.markdown(f"""
        <div style='text-align: center; border: 1px solid #ddd; padding: 10px; border-radius: 10px;'>
            <div style='font-size: 16px; color: gray;'>目前股價</div>
            <div style='font-size: 36px; font-weight: bold; color: {price_color};'>
                {last_row['Close']:.2f} <span style='font-size: 20px;'>{arrow} {abs(change):.2f} ({pct_change:.2f}%)</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 執行策略分析
    action, action_color, reasons, total_score = analyze_strategy(df)

    # 定義 CSS 顏色變數供 f-string 使用
    css_color = "red" if action_color == "red" else "orange" if action_color == "orange" else "green"

    with col2:
        st.markdown(f"""
        <div style='text-align: center; background-color: #f0f2f6; padding: 10px; border-radius: 10px;'>
            <div style='font-size: 16px; color: gray;'>AI 經理人建議</div>
            <div style='font-size: 28px; font-weight: bold; color: {css_color};'>{action}</div>
            <div style='font-size: 14px;'>綜合評分: {total_score}/100</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.metric("月線 (生命線)", f"{last_row['MA_20']:.2f}", delta=f"{last_row['Close'] - last_row['MA_20']:.2f}")
        st.metric("季線 (趨勢線)", f"{last_row['MA_60']:.2f}")

    # LINE 發送按鈕
    st.markdown("---")
    if st.button("📲 發送 LINE 戰報", type="primary", disabled=not line_token):
        if not line_token:
            st.error("請先在側邊欄輸入 LINE Token")
        else:
            msg = f"\n【台股戰情室】\n標的：{target}\n現價：{last_row['Close']:.2f}\n建議：{action}\n評分：{total_score}\n關鍵：\n"
            for r in reasons:
                msg += f"• {r}\n"
            
            if send_line_notify(line_token, msg):
                st.toast("✅ 戰報已發送！", icon="🚀")
            else:
                st.error("發送失敗")

    st.markdown("---")

    # --- 4. 繪製 K 線圖 (Plotly) ---
    tab1, tab2 = st.tabs(["📈 K線主圖", "📊 MACD 動能"])

    with tab1:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_heights=[0.7, 0.3],
                            subplot_titles=('股價 & 均線', '成交量'))

        # K棒
        candlestick = go.Candlestick(
            x=df.index,
            open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name='K線',
            increasing_line_color='#ff3b30', decreasing_line_color='#30d158'
        )
        fig.add_trace(candlestick, row=1, col=1)

        # 均線
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_5'], line=dict(color='orange', width=1), name='5日線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_20'], line=dict(color='purple', width=2), name='20日線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_60'], line=dict(color='blue', width=2), name='60日線'), row=1, col=1)

        # 成交量
        colors = ['#ff3b30' if row['Open'] < row['Close'] else '#30d158' for index, row in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
        
        fig.update_layout(height=600, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("MACD 動能分析")
        fig_macd = make_subplots(rows=1, cols=1)
        colors_macd = ['#ff3b30' if val >= 0 else '#30d158' for val in df['MACD_Hist']]
        fig_macd.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=colors_macd, name='柱狀體'), row=1, col=1)
        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Line'], line=dict(color='orange'), name='DIF'), row=1, col=1)
        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='blue'), name='DEM'), row=1, col=1)
        
        fig_macd.update_layout(height=300)
        st.plotly_chart(fig_macd, use_container_width=True)
