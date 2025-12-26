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
</style>
""", unsafe_allow_html=True)

# --- 3. 資料存取與快照功能 ---
SNAPSHOT_FILE = 'options_history.json'

def load_snapshot(ticker):
    """讀取歷史快照資料"""
    if not os.path.exists(SNAPSHOT_FILE):
        return None
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            data = json.load(f)
        return data.get(ticker)
    except:
        return None

def save_snapshot(ticker, price, pc_data):
    """將當下數據存為快照"""
    record = {
        "date": datetime.datetime.now().strftime('%Y-%m-%d'),
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "close_price": price,
        "pc_data": pc_data
    }
    
    all_data = {}
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                all_data = json.load(f)
        except:
            pass
            
    all_data[ticker] = record
    
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(all_data, f, indent=4)
    
    return True

# --- 4. 核心數據函數 ---
@st.cache_data(ttl=60)
def get_signal(ticker, atr_mult):
    try:
        df = yf.download(ticker, period="6mo", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # 非交易時段數據清洗
        if len(df) > 0:
            last_row = df.iloc[-1]
            if pd.isna(last_row['Close']) or pd.isna(last_row['Open']):
                df = df.iloc[:-1]

        if len(df) < 50: return None, "數據不足"

        df['EMA_8'] = ta.ema(df['Close'], length=8)
        df['EMA_21'] = ta.ema(df['Close'], length=21)
        
        macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
        if macd is not None:
            df = pd.concat([df, macd], axis=1)
            df.rename(columns={df.columns[-3]: 'MACD_Line', df.columns[-2]: 'MACD_Hist', df.columns[-1]: 'MACD_Signal'}, inplace=True)

        df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)

        conditions = [
            (df['Close'] > df['EMA_8']) & (df['EMA_8'] > df['EMA_21']) & 
            (df['MACD_Hist'] > 0) & (df['MACD_Hist'] > df['MACD_Hist'].shift(1)) & 
            (df['Volume'] > df['Vol_SMA_10'] * 1.2)
        ]
        df['Signal'] = np.select(conditions, ['BUY'], default='HOLD')
        sell_cond = (df['Close'] < df['EMA_21']) | (df['MACD_Hist'] < 0)
        df.loc[sell_cond, 'Signal'] = 'SELL'
        
        return df, None
    except Exception as e:
        return None, str(e)

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
                days_diff = (exp_date - today).days
                if 0 <= days_diff <= 40:
                    valid_dates.append(date_str)
            except: continue

        if not valid_dates: return None, "無 40 日內到期合約"

        total_call_vol = 0
        total_put_vol = 0
        details = []

        for date in valid_dates:
            try:
                opt = tk.option_chain(date)
                calls = opt.calls
                puts = opt.puts
                
                if calls is None or puts is None or calls.empty or puts.empty: continue

                center_idx_c = (np.abs(calls['strike'] - current_price)).argmin()
                start_c = max(0, center_idx_c - 5)
                end_c = min(len(calls), center_idx_c + 6)
                c_vol = calls.iloc[start_c:end_c]['volume'].fillna(0).sum()
                
                center_idx_p = (np.abs(puts['strike'] - current_price)).argmin()
                start_p = max(0, center_idx_p - 5)
                end_p = min(len(puts), center_idx_p + 6)
                p_vol = puts.iloc[start_p:end_p]['volume'].fillna(0).sum()

                total_call_vol += c_vol
                total_put_vol += p_vol
                
                details.append({"到期日": date, "Call成交量": int(c_vol), "Put成交量": int(p_vol)})
            except: continue
        
        if total_call_vol == 0:
            if total_put_vol > 0: ratio = 2.0 
            else: return None, "今日無成交量" 
        else:
            ratio = total_put_vol / total_call_vol

        return {
            "ratio": ratio,
            "total_call": total_call_vol,
            "total_put": total_put_vol,
            "details": details
        }, None

    except Exception as e:
        return None, str(e)


# --- 5. 介面佈局與主邏輯 ---
st.title("AlphaTrader 量化終端")

# 檢查時間與快照邏輯
est = pytz.timezone('US/Eastern')
now_est = datetime.datetime.now(est)
is_market_open = (now_est.weekday() < 5) and (9 <= now_est.hour < 16) or (now_est.hour == 16 and now_est.minute == 0)

# 收盤前 5 分鐘窗口 (15:55 - 16:00 EST)
is_closing_window = (now_est.hour == 15 and now_est.minute >= 55)

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        # 更新後的完整股票代碼清單
        target_tickers = [
            "AAPL", "AMD", "APP", "ASML", "AVGO", "GOOG", "HIMS", "INTC",
            "LLY", "LRCX", "MSFT", "MU", "NBIS", "NVDA", "ORCL", "PLTR",
            "QQQ", "SPY", "TEM", "TSLA", "TSM", "XLV"
        ]
        # 排序清單方便查找
        ticker_list = sorted(target_tickers)
        
        # 預設選擇 TSLA，如果不在清單中則選第一個
        default_index = ticker_list.index('TSLA') if 'TSLA' in ticker_list else 0
        selected_ticker = st.selectbox("美股標的", ticker_list, index=default_index)
        
    with c2:
        atr_multiplier = st.slider("ATR 止損乘數", 1.5, 4.0, 2.5, 0.1)
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        auto_refresh = st.checkbox("每分刷新", value=True)
        if st.button("🔄 刷新"): st.rerun()
        
    time_str = now_est.strftime('%H:%M EST')
    if is_closing_window:
        st.caption(f"⚡ 收盤前黃金時段 ({time_str}) - 系統將自動存檔")
    elif not is_market_open:
        st.caption(f"🌑 非交易時段 ({time_str}) - 載入參考資料中...")
    else:
        st.caption(f"🟢 盤中即時 ({time_str})")
        
    st.markdown('</div>', unsafe_allow_html=True)

df, error = get_signal(selected_ticker, atr_multiplier)

if error:
    st.error(f"錯誤: {error}")
else:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    signal = last['Signal']
    
    # --- 期權數據處理核心邏輯 ---
    pc_data, pc_error = get_advanced_pc_ratio(selected_ticker, last['Close'])
    data_source_badge = ""
    
    # 自動存檔邏輯
    if is_closing_window and pc_data:
        saved_snapshot = load_snapshot(selected_ticker)
        today_str = now_est.strftime('%Y-%m-%d')
        if not saved_snapshot or saved_snapshot.get('date') != today_str:
            save_snapshot(selected_ticker, last['Close'], pc_data)
            st.toast(f"✅ {selected_ticker} 收盤數據已自動存檔！", icon="💾")

    # 回充邏輯
    if not pc_data: 
        snapshot = load_snapshot(selected_ticker)
        if snapshot:
            pc_data = snapshot['pc_data']
            save_date = snapshot.get('date', '未知日期')
            data_source_badge = f'<span class="snapshot-badge">📁 使用歷史快照 ({save_date})</span>'

    # --- 頂部狀態 ---
    if signal == 'BUY': st.success(f"🔥 {selected_ticker} 強力買進 (STRONG BUY)")
    elif signal == 'SELL': st.error(f"🛑 {selected_ticker} 離場/止損 (SELL/EXIT)")
    else: st.info(f"👀 {selected_ticker} 觀望/持有 (HOLD)")

    # --- KPI 卡片 ---
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric("最新價格", f"${last['Close']:.2f}", f"{(last['Close']-prev['Close']):.2f}")
    with k2: st.metric("建議止損", f"${last['Stop_Loss']:.2f}")
    with k3: st.metric("風險/股", f"${(last['Close']-last['Stop_Loss']):.2f}")
    
    # P/C Ratio 卡片
    with k4:
        if pc_data:
            ratio_val = pc_data['ratio']
            delta_color = "inverse"
            label = "看多" if ratio_val < 0.7 else "看空" if ratio_val > 1.0 else "中性"
            st.metric("P/C Ratio", f"{ratio_val:.2f}", label, delta_color=delta_color)
            if data_source_badge:
                st.markdown(data_source_badge, unsafe_allow_html=True)
        else:
            st.metric("P/C Ratio", "N/A", "無數據")

    st.markdown("---")

    # --- 圖表與期權詳情 ---
    main_col, side_col = st.columns([2, 1])

    with main_col:
        st.subheader("📈 技術走勢")
        chart_data = df[['Close', 'EMA_8', 'EMA_21']].tail(60)
        st.line_chart(chart_data, color=["#000000", "#00ff00", "#ff0000"])

    with side_col:
        st.subheader("📊 籌碼分析")
        if pc_data:
            total_vol = pc_data['total_call'] + pc_data['total_put']
            c_pct = (pc_data['total_call'] / total_vol) * 100 if total_vol > 0 else 0
            p_pct = (pc_data['total_put'] / total_vol) * 100 if total_vol > 0 else 0
            
            st.caption(f"統計：40日內到期，現價上下 5 檔")
            st.progress(int(c_pct), text=f"Call: {int(pc_data['total_call']):,} ({c_pct:.1f}%)")
            st.progress(int(p_pct), text=f"Put: {int(pc_data['total_put']):,} ({p_pct:.1f}%)")
            
            st.write("---")
            st.write("**Top 3 合約分佈:**")
            det_df = pd.DataFrame(pc_data['details']).head(3)
            st.dataframe(det_df, hide_index=True, use_container_width=True)
        else:
            st.warning("暫無期權數據，請等待開盤")

    # --- 歷史數據表格 ---
    with st.expander("查看最近 5 日技術數據"):
        cols = ['Close', 'Volume', 'EMA_8', 'EMA_21', 'MACD_Hist', 'Signal', 'Stop_Loss']
        fmt = {'Close':'{:.2f}', 'Volume':'{:.0f}', 'EMA_8':'{:.2f}', 'EMA_21':'{:.2f}', 'MACD_Hist':'{:.2f}', 'Stop_Loss':'{:.2f}'}
        st.dataframe(df[cols].tail(5).style.format(fmt))

# --- 自動刷新與倒數 ---
if auto_refresh:
    placeholder = st.empty()
    for s in range(60, 0, -1):
        now_str = datetime.datetime.now(est).strftime('%H:%M:%S')
        placeholder.markdown(f'<div class="countdown-box">🕒 EST {now_str} | ⏳ {s}s 刷新</div>', unsafe_allow_html=True)
        time.sleep(1)
    placeholder.empty()
    st.rerun()
