import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

# --- 1. 頁面設定 (寬螢幕 + 深色模式) ---
st.set_page_config(
    page_title="US Market Alpha Terminal",
    page_icon="🇺🇸",
    layout="wide",
    initial_sidebar_state="collapsed" # 預設隱藏側邊欄
)

# --- 自定義 CSS (橫向佈局優化 & 深色護眼) ---
st.markdown("""
<style>
    /* 全局背景 - 深炭灰 */
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    
    /* 頂部控制列樣式 */
    .control-panel {
        background-color: #1E1E1E;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #333;
    }

    /* 數據卡片 */
    .metric-card {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.3);
        text-align: center;
    }
    
    /* 美股顏色 (綠漲紅跌) */
    .up-color { color: #00CC96 !important; }
    .down-color { color: #FF4B4B !important; }
    
    /* 調整按鈕樣式 */
    div.stButton > button { border-radius: 5px; height: 3em; }
</style>
""", unsafe_allow_html=True)

# --- 2. 核心數據函數 ---
@st.cache_data(ttl=60) # 美股盤中變動快，快取縮短為 60秒
def get_us_stock_data(ticker, atr_mult):
    try:
        # 抓取數據
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        if len(df) < 50: return None

        # 計算美股動能指標 (EMA 8/21)
        df['EMA_8'] = ta.ema(df['Close'], length=8)
        df['EMA_21'] = ta.ema(df['Close'], length=21)
        
        # MACD
        macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
        if macd is not None:
            df = pd.concat([df, macd], axis=1)
            df.rename(columns={
                df.columns[-3]: 'MACD_Line',
                df.columns[-2]: 'MACD_Hist',
                df.columns[-1]: 'MACD_Signal'
            }, inplace=True)

        # ATR 止損計算
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)
        
        # 成交量均線
        df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
        
        return df
    except Exception:
        return None

def analyze_us_strategy(df):
    if df is None: return "N/A", "gray", [], 0
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    score = 0
    signals = []
    
    # 1. EMA 趨勢 (美股動能核心)
    if curr['Close'] > curr['EMA_8'] and curr['EMA_8'] > curr['EMA_21']:
        score += 40
        signals.append("✅ 強勢多頭 (價格 > EMA8 > EMA21)")
    elif curr['Close'] < curr['EMA_21']:
        score -= 30
        signals.append("⚠️ 跌破 EMA21 (動能消失)")
    else:
        signals.append("⚪ 震盪整理中")

    # 2. MACD 動能
    if curr['MACD_Hist'] > 0 and curr['MACD_Hist'] > prev['MACD_Hist']:
        score += 30
        signals.append("✅ MACD 動能加速 (紅柱變長)")
    elif curr['MACD_Hist'] < 0:
        score -= 20
        signals.append("🔴 MACD 空方主導")

    # 3. 爆量突破
    vol_ratio = curr['Volume'] / curr['Vol_SMA_10']
    if vol_ratio > 1.2:
        score += 30
        signals.append(f"🔥 爆量攻擊 (量增 {vol_ratio:.1f}x)")
    
    # 綜合判定
    if score >= 70:
        return "STRONG BUY (積極買進)", "#00CC96" # 美股綠色是漲/買
    elif score <= 20:
        return "SELL / EXIT (止損離場)", "#FF4B4B" # 美股紅色是跌/賣
    else:
        return "HOLD (續抱/觀望)", "#FFA500"

def send_line_notify(token, message):
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": "Bearer " + token}
    data = {"message": message}
    try:
        requests.post(url, headers=headers, data=data)
        return True
    except:
        return False

# --- 3. UI 佈局：頂部橫向控制台 ---

st.title("🇺🇸 US Market Alpha Terminal")

# 使用 Container 包裹控制項，模擬 Top Bar
with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    
    # 分割為 4 欄：股票選擇 | ATR 設定 | Token 輸入 | 狀態顯示
    c1, c2, c3 = st.columns([1.5, 1.5, 2])
    
    with c1:
        # 整理後的股票清單 (已排序)
        ticker_list = sorted([
            "AAPL", "AMD", "AVGO", "APP", "ASML", "GOOG", "HIMS", "INTC", 
            "LLY", "LRCX", "MSFT", "TSM", "NVDA", "ORCL", "PLTR", 
            "QQQ", "SPY", "TEM", "TSLA", "XLV"
        ])
        selected_ticker = st.selectbox("選擇股票 (Symbol)", ticker_list)
        
    with c2:
        atr_mult = st.slider("ATR 止損係數", 1.5, 4.0, 2.5, 0.1, help="係數越大，止損越寬 (適合 TSLA/NVDA)")
        
    with c3:
        line_token = st.text_input("LINE Notify Token", type="password", placeholder="貼上 Token 以啟用通知")
    
    st.markdown('</div>', unsafe_allow_html=True)

# --- 4. 主數據顯示 ---

df = get_us_stock_data(selected_ticker, atr_mult)

if df is None:
    st.error(f"❌ 無法取得 {selected_ticker} 數據，請稍後再試。")
else:
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    # 計算美股漲跌 (綠漲紅跌)
    change = last_row['Close'] - prev_row['Close']
    pct_change = (change / prev_row['Close']) * 100
    price_color = "#00CC96" if change >= 0 else "#FF4B4B"
    
    # 策略運算
    action, action_color, reasons, score = analyze_us_strategy(df)
    
    # --- 數據儀表板 (Metrics) ---
    m1, m2, m3, m4 = st.columns(4)
    
    with m1:
        st.markdown(f"""
        <div class="metric-card">
            <div style="color:#aaa; font-size:14px;">Current Price</div>
            <div style="font-size:28px; font-weight:bold; color:{price_color};">
                ${last_row['Close']:.2f}
            </div>
            <div style="color:{price_color}; font-size:16px;">
                {change:+.2f} ({pct_change:+.2f}%)
            </div>
        </div>
        """, unsafe_allow_html=True)
        
    with m2:
         st.markdown(f"""
        <div class="metric-card">
            <div style="color:#aaa; font-size:14px;">AI Signal</div>
            <div style="font-size:24px; font-weight:bold; color:{action_color};">
                {action.split(' ')[0]}
            </div>
            <div style="color:#ccc; font-size:14px;">Score: {score}/100</div>
        </div>
        """, unsafe_allow_html=True)

    with m3:
        risk = last_row['Close'] - last_row['Stop_Loss']
        st.markdown(f"""
        <div class="metric-card">
            <div style="color:#aaa; font-size:14px;">Stop Loss (ATR)</div>
            <div style="font-size:28px; font-weight:bold; color:#FF4B4B;">
                ${last_row['Stop_Loss']:.2f}
            </div>
            <div style="color:#aaa; font-size:14px;">Risk: ${risk:.2f}/share</div>
        </div>
        """, unsafe_allow_html=True)

    with m4:
        # 發送按鈕區塊
        st.write("") # Spacer
        if st.button("📲 發送訊號到 LINE", type="primary", use_container_width=True, disabled=not line_token):
            if not line_token:
                st.error("Missing Token")
            else:
                msg = f"\n🇺🇸【美股快訊】\n標的：{selected_ticker}\n現價：${last_row['Close']:.2f}\n訊號：{action}\n止損：${last_row['Stop_Loss']:.2f}\n理由：{', '.join([r.split(' ')[1] for r in reasons])}"
                if send_line_notify(line_token, msg):
                    st.toast("Sent successfully!", icon="✅")
                else:
                    st.error("Failed to send")

    st.write("") # Spacer

    # --- 5. 專業圖表 (Plotly Dark) ---
    tab1, tab2 = st.tabs(["📈 Price & EMA", "📊 Momentum (MACD)"])
    
    with tab1:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        
        # K線 (美股顏色)
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name='OHLC',
            increasing_line_color='#00CC96', decreasing_line_color='#FF4B4B'
        ), row=1, col=1)
        
        # EMA 線 (8=黃, 21=紫)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_8'], line=dict(color='#FFD700', width=1), name='EMA 8'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_21'], line=dict(color='#9370DB', width=2), name='EMA 21'), row=1, col=1)
        
        # 止損線 (紅虛線)
        fig.add_trace(go.Scatter(x=df.index, y=df['Stop_Loss'], line=dict(color='#FF4B4B', width=1, dash='dot'), name='ATR Stop'), row=1, col=1)

        # 成交量
        colors_vol = ['#00CC96' if row['Close'] >= row['Open'] else '#FF4B4B' for i, row in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors_vol, name='Volume'), row=2, col=1)
        
        fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True)
        
    with tab2:
        fig_macd = make_subplots(rows=1, cols=1)
        colors_macd = ['#00CC96' if val >= 0 else '#FF4B4B' for val in df['MACD_Hist']]
        
        fig_macd.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=colors_macd, name='Histogram'), row=1, col=1)
        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Line'], line=dict(color='#FFD700'), name='MACD'), row=1, col=1)
        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='#00BFFF'), name='Signal'), row=1, col=1)
        
        fig_macd.update_layout(height=350, template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_macd, use_container_width=True)

    # 顯示分析理由
    with st.expander("查看詳細 AI 分析邏輯 (Analysis Details)", expanded=True):
        for signal in reasons:
            st.write(signal)
