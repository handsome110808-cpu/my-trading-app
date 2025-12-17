import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

# --- 1. 頁面設定 (亮色清爽模式) ---
st.set_page_config(
    page_title="US Market Alpha Terminal",
    page_icon="🇺🇸",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 自定義 CSS (亮色主題優化) ---
st.markdown("""
<style>
    /* 全局背景 - 純白 */
    .stApp {
        background-color: #FFFFFF;
        color: #31333F; /* 深灰字體 */
    }
    
    /* 頂部控制列 - 淺灰底 */
    .control-panel {
        background-color: #F8F9FA;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #DEE2E6;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }

    /* 數據卡片 - 白底卡片風格 */
    .metric-card {
        background-color: #FFFFFF;
        border: 1px solid #E0E0E0;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: center;
    }
    
    /* 美股顏色 (綠漲紅跌) */
    .up-color { color: #008000 !important; }
    .down-color { color: #D32F2F !important; }
    
    /* 按鈕樣式 */
    div.stButton > button { border-radius: 5px; height: 3em; }
</style>
""", unsafe_allow_html=True)

# --- 2. 核心數據函數 ---
@st.cache_data(ttl=60)
def get_us_stock_data(ticker, atr_mult):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) < 50: return None

        # 計算指標
        df['EMA_8'] = ta.ema(df['Close'], length=8)
        df['EMA_21'] = ta.ema(df['Close'], length=21)
        
        macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
        if macd is not None:
            df = pd.concat([df, macd], axis=1)
            df.rename(columns={
                df.columns[-3]: 'MACD_Line',
                df.columns[-2]: 'MACD_Hist',
                df.columns[-1]: 'MACD_Signal'
            }, inplace=True)

        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)
        df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
        
        return df
    except Exception:
        return None

def analyze_us_strategy(df):
    if df is None: return "N/A", "gray", [], 0
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    signals = []  # 變數定義在這裡叫 signals
    
    # 策略邏輯
    if curr['Close'] > curr['EMA_8'] and curr['EMA_8'] > curr['EMA_21']:
        score += 40
        signals.append("✅ 強勢多頭 (價格 > EMA8 > EMA21)")
    elif curr['Close'] < curr['EMA_21']:
        score -= 30
        signals.append("⚠️ 跌破 EMA21 (動能消失)")
    else:
        signals.append("⚪ 震盪整理中")

    if curr['MACD_Hist'] > 0 and curr['MACD_Hist'] > prev['MACD_Hist']:
        score += 30
        signals.append("✅ MACD 動能加速 (紅柱變長)")
    elif curr['MACD_Hist'] < 0:
        score -= 20
        signals.append("🔴 MACD 空方主導")

    vol_ratio = curr['Volume'] / curr['Vol_SMA_10']
    if vol_ratio > 1.2:
        score += 30
        signals.append(f"🔥 爆量攻擊 (量增 {vol_ratio:.1f}x)")
    
    # 【修正重點】：這裡原本錯誤寫成 reasons，現在改回 signals
    if score >= 70:
        return "STRONG BUY (積極買進)", "#008000", signals, score
    elif score <= 20:
        return "SELL / EXIT (止損離場)", "#D32F2F", signals, score
    else:
        return "HOLD (續抱/觀望)", "#FF8C00", signals, score

def send_line_notify(token, message):
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": "Bearer " + token}
    data = {"message": message}
    try:
        requests.post(url, headers=headers, data=data)
        return True
    except:
        return False

# --- 3. UI 佈局 ---
st.title("🇺🇸 US Market Alpha Terminal")

# Top Control Bar
with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 2])
    
    with c1:
        ticker_list = sorted([
            "AAPL", "AMD", "AVGO", "APP", "ASML", "GOOG", "HIMS", "INTC", 
            "LLY", "LRCX", "MSFT", "TSM", "NVDA", "ORCL", "PLTR", 
            "QQQ", "SPY", "TEM", "TSLA", "XLV"
        ])
        selected_ticker = st.selectbox("選擇股票 (Symbol)", ticker_list)
        
    with c2:
        atr_mult = st.slider("ATR 止損係數", 1.5, 4.0, 2.5, 0.1)
        
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
    
    change = last_row['Close'] - prev_row['Close']
    pct_change = (change / prev_row['Close']) * 100
    price_color = "#008000" if change >= 0 else "#D32F2F"
    
    # 這裡現在會正確接收到 signals
    action, action_color, reasons, score = analyze_us_strategy(df)
    
    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    
    with m1:
        st.markdown(f"""
        <div class="metric-card">
            <div style="color:#666; font-size:14px;">Current Price</div>
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
            <div style="color:#666; font-size:14px;">AI Signal</div>
            <div style="font-size:24px; font-weight:bold; color:{action_color};">
                {action.split(' ')[0]}
            </div>
            <div style="color:#888; font-size:14px;">Score: {score}/100</div>
        </div>
        """, unsafe_allow_html=True)

    with m3:
        risk = last_row['Close'] - last_row['Stop_Loss']
        st.markdown(f"""
        <div class="metric-card">
            <div style="color:#666; font-size:14px;">Stop Loss (ATR)</div>
            <div style="font-size:28px; font-weight:bold; color:#D32F2F;">
                ${last_row['Stop_Loss']:.2f}
            </div>
            <div style="color:#888; font-size:14px;">Risk: ${risk:.2f}/share</div>
        </div>
        """, unsafe_allow_html=True)

    with m4:
        st.write("") 
        if st.button("📲 發送訊號到 LINE", type="primary", use_container_width=True, disabled=not line_token):
            if not line_token:
                st.error("Missing Token")
            else:
                msg = f"\n🇺🇸【美股快訊】\n標的：{selected_ticker}\n現價：${last_row['Close']:.2f}\n訊號：{action}\n止損：${last_row['Stop_Loss']:.2f}"
                if send_line_notify(line_token, msg):
                    st.toast("Sent successfully!", icon="✅")

    st.write("") 

    # --- 5. 專業圖表 (Plotly White) ---
    tab1, tab2 = st.tabs(["📈 Price & EMA", "📊 Momentum (MACD)"])
    
    with tab1:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name='OHLC',
            increasing_line_color='#008000', decreasing_line_color='#D32F2F'
        ), row=1, col=1)
        
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_8'], line=dict(color='#FFA500', width=1), name='EMA 8'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_21'], line=dict(color='#007BFF', width=2), name='EMA 21'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Stop_Loss'], line=dict(color='#D32F2F', width=1, dash='dot'), name='ATR Stop'), row=1, col=1)

        colors_vol = ['#008000']

