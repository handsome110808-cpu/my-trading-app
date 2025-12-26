import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import datetime
import time
import pytz
import json
import os

# --- 1. 網頁設定 ---
st.set_page_config(
    page_title="AlphaTrader - AI 量化交易終端",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. 自定義 CSS ---
st.markdown("""
<style>
    .control-panel { background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 1px solid #ddd; margin-bottom: 20px; }
    .metric-card { background-color: #f0f2f6; border-radius: 10px; padding: 15px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
    div.stButton > button { height: 3em; width: 100%; }
    .countdown-box { position: fixed; bottom: 10px; right: 10px; background-color: #ffffff; border: 1px solid #ddd; padding: 5px 10px; border-radius: 5px; font-size: 12px; color: #666; z-index: 999; }
    .snapshot-badge { background-color: #e3f2fd; color: #1565c0; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; border: 1px solid #bbdefb; }
    
    /* 總表樣式優化 */
    .summary-header { font-size: 20px; font-weight: bold; margin-bottom: 10px; text-align: center; }
    .status-buy { color: #00c853; font-weight: bold; }
    .status-sell { color: #d50000; font-weight: bold; }
    .status-hold { color: #ffab00; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- 3. 資料存取與快照功能 ---
SNAPSHOT_FILE = 'options_history.json'
# 定義目標股票清單 (全域變數)
TARGET_TICKERS = sorted([
    "AAPL", "AMD", "APP", "ASML", "AVGO", "GOOG", "HIMS", "INTC",
    "LLY", "LRCX", "MSFT", "MU", "NBIS", "NVDA", "ORCL", "PLTR",
    "QQQ", "SPY", "XLV", "TEM", "TSLA", "TSM"
])

def load_snapshot(ticker):
    if not os.path.exists(SNAPSHOT_FILE): return None
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            data = json.load(f)
        return data.get(ticker)
    except: return None

def save_snapshot(ticker, price, pc_data):
    record = {
        "date": datetime.datetime.now().strftime('%Y-%m-%d'),
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "close_price": price,
        "pc_data": pc_data
    }
    all_data = {}
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f: all_data = json.load(f)
        except: pass
    all_data[ticker] = record
    with open(SNAPSHOT_FILE, 'w') as f: json.dump(all_data, f, indent=4)
    return True

# --- 4. 核心運算邏輯 (提取共用) ---
def calculate_technical_indicators(df, atr_mult):
    """共用的技術指標與訊號計算邏輯"""
    # 確保數據足夠
    if len(df) < 50: return df, "數據不足"
    
    # 填補空值以免計算錯誤
    df = df.ffill()

    # 計算指標
    df['EMA_8'] = ta.ema(df['Close'], length=8)
    df['EMA_21'] = ta.ema(df['Close'], length=21)
    
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        # 重新命名欄位
        cols = {df.columns[-3]: 'MACD_Line', df.columns[-2]: 'MACD_Hist', df.columns[-1]: 'MACD_Signal'}
        df.rename(columns=cols, inplace=True)

    df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)

    # 訊號判定邏輯
    # 1. 買進條件
    conditions = [
        (df['Close'] > df['EMA_8']) & 
        (df['EMA_8'] > df['EMA_21']) & 
        (df['MACD_Hist'] > 0) & 
        (df['MACD_Hist'] > df['MACD_Hist'].shift(1)) & 
        (df['Volume'] > df['Vol_SMA_10'] * 1.2)
    ]
    df['Signal'] = np.select(conditions, ['BUY'], default='HOLD')
    
    # 2. 賣出條件 (優先權高於 HOLD)
    sell_cond = (df['Close'] < df['EMA_21']) | (df['MACD_Hist'] < 0)
    df.loc[sell_cond, 'Signal'] = 'SELL'
    
    return df, None

@st.cache_data(ttl=60)
def get_signal(ticker, atr_mult):
    """單一股票詳細分析"""
    try:
        df = yf.download(ticker, period="6mo", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        if len(df) > 0:
            last_row = df.iloc[-1]
            if pd.isna(last_row['Close']) or pd.isna(last_row['Open']): df = df.iloc[:-1]

        # 呼叫共用邏輯
        df, err = calculate_technical_indicators(df, atr_mult)
        if err: return None, err
        
        return df, None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=60)
def scan_market_summary(tickers, atr_mult):
    """批次掃描全市場訊號 (總表用)"""
    summary = {"BUY": [], "HOLD": [], "SELL": []}
    
    try:
        # 批次下載，效能優化
        data = yf.download(tickers, period="3mo", group_by='ticker', progress=False, threads=True)
        
        for ticker in tickers:
            try:
                # 處理 MultiIndex 資料結構
                df_t = data[ticker].copy()
                
                # 簡單清洗
                if len(df_t) > 0:
                    last_row = df_t.iloc[-1]
                    if pd.isna(last_row['Close']): df_t = df_t.iloc[:-1]
                
                if df_t.empty: continue

                # 計算訊號 (使用相同的邏輯)
                df_t, err = calculate_technical_indicators(df_t, atr_mult)
                
                if err: continue
                
                last_sig = df_t.iloc[-1]['Signal']
                
                # 分類
                if last_sig == "BUY": summary["BUY"].append(ticker)
                elif last_sig == "SELL": summary["SELL"].append(ticker)
                else: summary["HOLD"].append(ticker)
            except:
                continue
                
    except Exception as e:
        return None
        
    return summary

@st.cache_data(ttl=300)
def get_advanced_pc_ratio(ticker, current_price):
    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations: return None, "無期權數據"

        today = datetime.date.today()
        valid_dates = []
        for date_str in expirations:
            try:
                exp_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                if 0 <= (exp_date - today).days <= 40: valid_dates.append(date_str)
            except: continue

        if not valid_dates: return None, "無 40 日內到期合約"

        total_call_vol = 0; total_put_vol = 0; details = []

        for date in valid_dates:
            try:
                opt = tk.option_chain(date)
                calls, puts = opt.calls, opt.puts
                if calls is None or puts is None or calls.empty or puts.empty: continue

                center_idx_c = (np.abs(calls['strike'] - current_price)).argmin()
                c_vol = calls.iloc[max(0,center_idx_c-5):min(len(calls),center_idx_c+6)]['volume'].fillna(0).sum()
                
                center_idx_p = (np.abs(puts['strike'] - current_price)).argmin()
                p_vol = puts.iloc[max(0,center_idx_p-5):min(len(puts),center_idx_p+6)]['volume'].fillna(0).sum()

                total_call_vol += c_vol; total_put_vol += p_vol
                details.append({"到期日": date, "Call": int(c_vol), "Put": int(p_vol)})
            except: continue
        
        ratio = total_put_vol / total_call_vol if total_call_vol > 0 else 2.0
        return {"ratio": ratio, "total_call": total_call_vol, "total_put": total_put_vol, "details": details}, None
    except Exception as e: return None, str(e)


# --- 5. 介面佈局 ---
st.title("AlphaTrader 量化終端")

# 時間與存檔檢查
est = pytz.timezone('US/Eastern')
now_est = datetime.datetime.now(est)
is_market_open = (now_est.weekday() < 5) and (9 <= now_est.hour < 16) or (now_est.hour == 16 and now_est.minute == 0)
is_closing_window = (now_est.hour == 15 and now_est.minute >= 55)

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        selected_ticker = st.selectbox("美股標的", TARGET_TICKERS, index=TARGET_TICKERS.index('TSLA') if 'TSLA' in TARGET_TICKERS else 0)
    with c2:
        atr_multiplier = st.slider("ATR 止損乘數", 1.5, 4.0, 2.5, 0.1)
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        auto_refresh = st.checkbox("每分刷新", value=True)
        if st.button("🔄 刷新"): st.rerun()
        
    time_str = now_est.strftime('%H:%M EST')
    if is_closing_window: st.caption(f"⚡ 收盤前黃金時段 ({time_str}) - 系統將自動存檔")
    elif not is_market_open: st.caption(f"🌑 非交易時段 ({time_str}) - 載入參考資料中...")
    else: st.caption(f"🟢 盤中即時 ({time_str})")
    st.markdown('</div>', unsafe_allow_html=True)

# === A. 單一股票詳細分析 ===
df, error = get_signal(selected_ticker, atr_multiplier)

if error:
    st.error(f"錯誤: {error}")
else:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    signal = last['Signal']
    
    # 期權與存檔邏輯
    pc_data, pc_error = get_advanced_pc_ratio(selected_ticker, last['Close'])
    data_source_badge = ""
    
    if is_closing_window and pc_data:
        saved = load_snapshot(selected_ticker)
        if not saved or saved.get('date') != now_est.strftime('%Y-%m-%d'):
            save_snapshot(selected_ticker, last['Close'], pc_data)
            st.toast(f"✅ {selected_ticker} 已自動存檔", icon="💾")

    if not pc_data: 
        snap = load_snapshot(selected_ticker)
        if snap:
            pc_data = snap['pc_data']
            data_source_badge = f'<span class="snapshot-badge">📁 歷史快照 ({snap.get("date")})</span>'

    # 頂部狀態
    if signal == 'BUY': st.success(f"🔥 {selected_ticker} 強力買進 (STRONG BUY)")
    elif signal == 'SELL': st.error(f"🛑 {selected_ticker} 離場/止損 (SELL/EXIT)")
    else: st.info(f"👀 {selected_ticker} 觀望/持有 (HOLD)")

    # KPI
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric("最新價格", f"${last['Close']:.2f}", f"{(last['Close']-prev['Close']):.2f}")
    with k2: st.metric("建議止損", f"${last['Stop_Loss']:.2f}")
    with k3: st.metric("風險/股", f"${(last['Close']-last['Stop_Loss']):.2f}")
    with k4:
        if pc_data:
            r = pc_data['ratio']
            lbl = "看多" if r < 0.7 else "看空" if r > 1.0 else "中性"
            st.metric("P/C Ratio", f"{r:.2f}", lbl, delta_color="inverse")
            if data_source_badge: st.markdown(data_source_badge, unsafe_allow_html=True)
        else: st.metric("P/C Ratio", "N/A", "無數據")

    st.markdown("---")

    # 圖表
    main_col, side_col = st.columns([2, 1])
    with main_col:
        st.subheader("📈 技術走勢")
        st.line_chart(df[['Close', 'EMA_8', 'EMA_21']].tail(60), color=["#000000", "#00ff00", "#ff0000"])
    with side_col:
        st.subheader("📊 籌碼分析")
        if pc_data:
            tot = pc_data['total_call'] + pc_data['total_put']
            c_p = (pc_data['total_call']/tot)*100 if tot>0 else 0
            p_p = (pc_data['total_put']/tot)*100 if tot>0 else 0
            st.caption("40日內，現價上下5檔")
            st.progress(int(c_p), text=f"Call: {int(pc_data['total_call']):,}")
            st.progress(int(p_p), text=f"Put: {int(pc_data['total_put']):,}")
            st.dataframe(pd.DataFrame(pc_data['details']).head(3), hide_index=True, use_container_width=True)
        else: st.warning("無資料")

    with st.expander("查看技術數據"):
        cols = ['Close', 'Volume', 'EMA_8', 'EMA_21', 'MACD_Hist', 'Signal', 'Stop_Loss']
        st.dataframe(df[cols].tail(5).style.format("{:.2f}"))

# === B. 全市場訊號彙整總表 ===
st.markdown("---")
st.subheader("🌍 全市場戰情總表 (Market Summary)")

with st.spinner("正在掃描市場訊號..."):
    # 執行批次掃描
    market_signals = scan_market_summary(TARGET_TICKERS, atr_multiplier)

if market_signals:
    # 整理資料為 DataFrame 格式以便顯示
    # 找出最大長度以填補空值
    max_len = max(len(market_signals["BUY"]), len(market_signals["HOLD"]), len(market_signals["SELL"]))
    
    # 補齊長度
    buy_list = market_signals["BUY"] + [""] * (max_len - len(market_signals["BUY"]))
    hold_list = market_signals["HOLD"] + [""] * (max_len - len(market_signals["HOLD"]))
    sell_list = market_signals["SELL"] + [""] * (max_len - len(market_signals["SELL"]))
    
    summary_df = pd.DataFrame({
        "BUY (強力買進)": buy_list,
        "HOLD (觀望持有)": hold_list,
        "SELL (離場止損)": sell_list
    })
    
    # 顯示總表
    st.dataframe(
        summary_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "BUY (強力買進)": st.column_config.TextColumn(help="動能強勁，符合所有買進條件"),
            "SELL (離場止損)": st.column_config.TextColumn(help="趨勢破壞，建議離場"),
            "HOLD (觀望持有)": st.column_config.TextColumn(help="盤整中或趨勢不明顯")
        }
    )
else:
    st.error("無法取得市場總覽數據")

# 自動刷新
if auto_refresh:
    placeholder = st.empty()
    for s in range(60, 0, -1):
        now_str = datetime.datetime.now(est).strftime('%H:%M:%S')
        placeholder.markdown(f'<div class="countdown-box">🕒 {now_str} | ⏳ {s}s 刷新</div>', unsafe_allow_html=True)
        time.sleep(1)
    placeholder.empty()
    st.rerun()
