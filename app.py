Python

import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import datetime

# --- 網頁設定 (配置為寬屏模式) ---
st.set_page_config(
    page_title="AlphaTrader - AI 量化交易終端",
    page_icon="📈",
    layout="wide",  # 寬屏模式，更有專業感
    initial_sidebar_state="expanded"
)

# --- 自定義 CSS (讓介面更像專業軟體) ---
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
    }
    .stAlert {
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


# --- 核心邏輯函數 ---
@st.cache_data(ttl=60)  # 數據快取 60秒，確保數據不過舊但也不會頻繁請求
def get_signal(ticker, atr_mult):
    try:
        # 下載數據
        df = yf.download(ticker, period="6mo", progress=False)

        # 處理 yfinance 格式問題
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if len(df) < 50:
            return None, "數據不足，無法計算指標"

        # 計算指標
        df['EMA_8'] = ta.ema(df['Close'], length=8)
        df['EMA_21'] = ta.ema(df['Close'], length=21)

        macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        # 欄位重新命名以防萬一
        df.rename(columns={
            df.columns[-3]: 'MACD_Line',
            df.columns[-2]: 'MACD_Hist',
            df.columns[-1]: 'MACD_Signal'
        }, inplace=True)

        df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

        # 計算 ATR 止損價
        df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)

        # 訊號邏輯
        conditions = [
            (df['Close'] > df['EMA_8']) &
            (df['EMA_8'] > df['EMA_21']) &
            (df['MACD_Hist'] > 0) &
            (df['MACD_Hist'] > df['MACD_Hist'].shift(1)) &
            (df['Volume'] > df['Vol_SMA_10'] * 1.2)
        ]

        choices = ['BUY']
        df['Signal'] = np.select(conditions, choices, default='HOLD')

        # 賣出條件
        sell_cond = (df['Close'] < df['EMA_21']) | (df['MACD_Hist'] < 0)
        df.loc[sell_cond, 'Signal'] = 'SELL'

        return df, None
    except Exception as e:
        return None, str(e)


# --- 側邊欄：控制台 ---
with st.sidebar:
    st.title("🎛️ 交易控制台")
    st.markdown("---")

    # 股票選擇
    ticker_list = ['TSLA', 'NVDA', 'AVGO', 'MU', 'ORCL', 'AMD', 'PLTR']
    selected_ticker = st.selectbox("選擇標的 (Ticker)", ticker_list, index=0)

    # 參數微調
    st.subheader("參數設定")
    atr_multiplier = st.slider("ATR 止損乘數", 1.5, 4.0, 2.5, 0.1, help="數值越大，止損越寬，適合高波動股票")

    st.markdown("---")
    st.caption(f"系統時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    st.caption("Designed for Alpha Generation")

# --- 主頁面 ---
st.title(f"📊 {selected_ticker} 量化分析儀表板")

# 執行分析
df, error = get_signal(selected_ticker, atr_multiplier)

if error:
    st.error(f"發生錯誤: {error}")
else:
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    signal = last_row['Signal']

    # --- 1. 頂部狀態橫幅 (Hero Section) ---
    if signal == 'BUY':
        st.success(f"🔥 交易訊號：強力買進 (STRONG BUY) - 動能爆發中")
    elif signal == 'SELL':
        st.error(f"🛑 交易訊號：離場/止損 (SELL/EXIT) - 趨勢破壞")
    else:
        st.info(f"👀 交易訊號：觀望/持有 (HOLD) - 等待機會")

    # --- 2. 核心數據 (KPIs) ---
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("最新價格", f"${last_row['Close']:.2f}", f"{(last_row['Close'] - prev_row['Close']):.2f}")
    with col2:
        st.metric("建議止損 (Stop Loss)", f"${last_row['Stop_Loss']:.2f}", delta_color="off")
    with col3:
        risk = last_row['Close'] - last_row['Stop_Loss']
        st.metric("單股風險 (Risk)", f"${risk:.2f}", help="每買一股可能虧損的最大金額")
    with col4:
        vol_ratio = last_row['Volume'] / last_row['Vol_SMA_10']
        st.metric("相對量能 (RVol)", f"{vol_ratio:.1f}x", delta="爆量" if vol_ratio > 1.2 else "縮量")

    st.markdown("---")

    # --- 3. 詳細技術分析 (分欄顯示) ---
    c1, c2 = st.columns([1, 2])  # 左窄右寬

    with c1:
        st.subheader("🛠️ 技術診斷")
        # 趨勢
        if last_row['EMA_8'] > last_row['EMA_21']:
            st.markdown("✅ **趨勢：** 短線多頭排列 (EMA8 > EMA21)")
        else:
            st.markdown("⚠️ **趨勢：** 趨勢偏弱或整理中")

        # MACD
        if last_row['MACD_Hist'] > 0 and last_row['MACD_Hist'] > prev_row['MACD_Hist']:
            st.markdown("✅ **動能：** 加速度增強 (紅柱變長)")
        elif last_row['MACD_Hist'] > 0:
            st.markdown("⚠️ **動能：** 上漲力道減弱")
        else:
            st.markdown("🔴 **動能：** 空頭動能主導")

        # 成交量
        if last_row['Volume'] > last_row['Vol_SMA_10'] * 1.2:
            st.markdown("✅ **資金：** 機構資金進場 (爆量)")
        else:
            st.markdown("⚪ **資金：** 交易清淡")

    with c2:
        st.subheader("📈 價格與趨勢線圖")
        # 繪製圖表 (包含價格與兩條均線)
        chart_data = df[['Close', 'EMA_8', 'EMA_21']].tail(60)
        st.line_chart(chart_data, color=["#ffffff", "#00ff00", "#ff0000"])  # 白=價, 綠=短均, 紅=長均

    # --- 4. 歷史數據表格 (可展開) ---
    with st.expander("查看最近 5 日詳細數據"):
        cols_to_show = ['Close', 'Volume', 'EMA_8', 'EMA_21', 'MACD_Hist', 'Signal', 'Stop_Loss']
        st.dataframe(df[cols_to_show].tail(5).style.format("{:.2f}"))