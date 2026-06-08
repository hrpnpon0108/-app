import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import io
import os
import json
import requests
from functools import lru_cache
import warnings

warnings.filterwarnings('ignore')

# ===== 1. 初期設定 =====
st.set_page_config(
    page_title="デマーシア！！！",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== 2. スタイル設定と色定義 =====
# スコアに応じた色付け設定
def get_score_color(score):
    """スコアに応じた色を返す"""
    if score >= 80:
        return "#00d084"  # 鮮やかな緑
    elif score >= 50:
        return "#ff9900"  # 鮮やかなオレンジ
    else:
        return "#ff0000"  # 赤

def get_score_text_style(score):
    """スコアに応じたCSS的な表示を返す"""
    color = get_score_color(score)
    return f"<h2 style='color:{color};'>★ {score}/100点 ★</h2>"

# CSS/カスタムスタイル
st.markdown("""
    <style>
        .header-title {
            text-align: center;
            font-size: 2.5em;
            font-weight: bold;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            font-family: Arial, sans-serif;
        }
        .score-display {
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            font-weight: bold;
        }
        .metric-card {
            background-color: #f0f2f6;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
        }
        .positive {
            color: #00d084;
            font-weight: bold;
        }
        .negative {
            color: #ff0000;
            font-weight: bold;
        }
        .neutral {
            color: #ff9900;
            font-weight: bold;
        }
    </style>
""", unsafe_allow_html=True)

# ===== 3. セクター日本語マッピング =====
SECTOR_MAPPING = {
    'Technology': 'テクノロジー（IT・半導体）',
    'Financial Services': '金融（銀行・保険）',
    'Consumer Cyclical': '景気敏感消費財（自動車・アパレル等）',
    'Healthcare': '医療・ヘルスケア',
    'Industrials': '工業・製造業',
    'Communication Services': '通信・メディア',
    'Energy': 'エネルギー（石油・電力）',
    'Real Estate': '不動産',
    'Utilities': 'インフラ・公共',
    'Consumer Defensive': '生活必需品',
    'Materials': '素材・鉱物',
    'Financial': '金融',
    'Information Technology': 'テクノロジー（IT・半導体）',
    'Consumer': '消費者向け',
    None: '未分類',
    'nan': '未分類'
}

def get_sector_jp(sector):
    """英語セクター名を日本語に変換"""
    if pd.isna(sector) or sector is None:
        return '未分類'
    sector_str = str(sector).strip()
    return SECTOR_MAPPING.get(sector_str, sector_str)

# ===== 4. サンプルデータセット =====
SAMPLE_STOCKS_JP = [
    '7203',  # トヨタ
    '9432',  # NTT
    '8306',  # 三菱UFJ
    '9101',  # 日本郵船
    '8058',  # 共栄タンカー
    '8001',  # 伊藤忠
    '8031',  # 三井物産
    '8015',  #豊田通商
    '6902',  # 椿本チエイン
    '6954',  # ファナック
]

SAMPLE_STOCKS_US = [
    'AAPL',   # Apple
    'MSFT',   # Microsoft
    'GOOG',   # Google
    'AMZN',   # Amazon
    'NVDA',   # NVIDIA
    'TSLA',   # Tesla
    'META',   # Meta
    'NFLX',   # Netflix
    'ADBE',   # Adobe
    'CRM',    # Salesforce
]

# ===== 5. グローバル変数と状態管理 =====
FAVORITES_PATH = os.path.join(os.path.dirname(__file__), 'favorites.json')

def load_favorites():
    try:
        if os.path.exists(FAVORITES_PATH):
            with open(FAVORITES_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def save_favorites(favorites):
    try:
        with open(FAVORITES_PATH, 'w', encoding='utf-8') as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

if 'favorites' not in st.session_state:
    st.session_state.favorites = load_favorites()

if 'market_mode' not in st.session_state:
    st.session_state.market_mode = '日本株'

if 'preset_selected' not in st.session_state:
    st.session_state.preset_selected = None

if 'selected_ticker' not in st.session_state:
    st.session_state.selected_ticker = None

if 'per_max' not in st.session_state:
    st.session_state.per_max = 20.0

if 'pbr_max' not in st.session_state:
    st.session_state.pbr_max = 2.0

if 'dividend_min' not in st.session_state:
    st.session_state.dividend_min = 2.0

if 'market_cap_min' not in st.session_state:
    st.session_state.market_cap_min = 10.0

if 'revenue_growth_min' not in st.session_state:
    st.session_state.revenue_growth_min = 0.0

if 'equity_ratio_min' not in st.session_state:
    st.session_state.equity_ratio_min = 30.0

# チェックボックスの初期状態を追加
checkbox_defaults = {
    'per_check': True,
    'pbr_check': False,
    'div_check': False,
    'mcap_check': False,
    'revgrow_check': False,
    'equity_check': False,
    'sector_check': False
}
for key, default_value in checkbox_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# ===== 6. ユーティリティ関数 =====

@lru_cache(maxsize=128)
def get_exchange_rate():
    """
    USD/JPY為替レートを取得（キャッシュ付き）
    取得できない場合は150.0を返す
    """
    try:
        rate_data = yf.download('USDJPY=X', period='1d', progress=False)
        if len(rate_data) > 0:
            return float(rate_data['Close'].iloc[-1])
    except:
        pass
    return 150.0  # フォールバック値

def fetch_stock_data(ticker):
    """
    1つの銘柄のデータをyfinanceから取得
    日本株の場合は.Tを付与、米国株はそのまま使用
    """
    try:
        # ティッカーが数字のみの場合は日本株と判定
        if ticker.isdigit():
            ticker_with_suffix = f"{ticker}.T"
        else:
            ticker_with_suffix = ticker
        
        stock = yf.Ticker(ticker_with_suffix)
        info = stock.info
        
        # 配当利回りの取得（値が異常な場合の対応含む）
        div_yield = info.get('dividendYield', 0)
        if div_yield and not np.isnan(div_yield):
            # yfinanceが既に%形式で返している場合を想定
            if div_yield > 50:  # 50%以上は異常と判定
                div_yield = div_yield / 100
            elif div_yield < 1:  # 0.01未満なら*100する
                div_yield = div_yield * 100
            # それ以外は既に%形式と判定
        else:
            div_yield = 0
        
        # 売上高成長率の取得（値が異常な場合の対応含む）
        rev_growth = info.get('revenueGrowth', np.nan)
        if rev_growth and not np.isnan(rev_growth):
            # 異常な値は無視
            if rev_growth > 10:  # 1000%以上なら異常
                rev_growth = np.nan
            elif rev_growth < 1:  # 小数点なら*100する
                rev_growth = rev_growth * 100
        else:
            rev_growth = np.nan
        
        return {
            'ticker': ticker,
            'name': info.get('longName', '不明'),
            'sector': get_sector_jp(info.get('sector', 'N/A')),
            'price': info.get('currentPrice', np.nan),
            'per': info.get('trailingPE', np.nan),
            'pbr': info.get('priceToBook', np.nan),
            'dividend_yield': div_yield,
            'market_cap': info.get('marketCap', np.nan),
            'revenue_growth': rev_growth,
            'equity_ratio': info.get('bookValue', 0) / info.get('totalAssets', 1) * 100 if info.get('bookValue') and info.get('totalAssets') else np.nan,
            'stock_obj': stock
        }
    except Exception as e:
        st.warning(f"⚠️ {ticker}のデータ取得エラー: {str(e)}")
        return None

def safe_get(value, default='-'):
    """
    値の安全な取得（NaN、None対策）
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    return value

def format_price_jp(price, is_us=False, exchange_rate=None):
    """
    株価をフォーマット（日本円併記）
    """
    if price is None or (isinstance(price, float) and np.isnan(price)):
        return '-'
    
    if is_us and exchange_rate:
        jpy = price * exchange_rate
        return f"${price:.2f}（≈ ¥{jpy:,.0f}）"
    else:
        return f"¥{price:,.0f}"

def format_market_cap(market_cap, is_us=False, exchange_rate=None):
    """
    時価総額をフォーマット（日本円併記）
    """
    if market_cap is None or (isinstance(market_cap, float) and np.isnan(market_cap)):
        return '-'
    
    if is_us and exchange_rate:
        jpy = market_cap * exchange_rate
        # アメリカは10億ドル単位
        if market_cap >= 1e9:
            return f"${market_cap/1e9:.1f}B（≈ ¥{jpy/1e12:.1f}兆）"
        else:
            return f"${market_cap/1e6:.0f}M（≈ ¥{jpy/1e9:.0f}B）"
    else:
        # 日本は兆円単位
        if market_cap >= 1e12:
            return f"¥{market_cap/1e12:.1f}兆"
        else:
            return f"¥{market_cap/1e9:.0f}B"

# ===== 7. スコアリングロジック =====

def calculate_buy_timing_score(stock_data, market_mode):
    """
    買い時度スコアを計算（100点満点）
    
    - PER（30点満点）
    - PBR（20点満点）
    - 配当利回り（20点満点）
    - 成長性・安全性（30点満点）
    """
    score = 0
    max_score = 0
    
    # PER スコア（30点満点）
    per = stock_data.get('per')
    if per and not np.isnan(per) and per > 0:
        benchmark_per = 15 if market_mode == '日本株' else 22
        if per < benchmark_per:
            # PERが低いほど高得点
            per_score = min(30, 30 * (1 - (per / benchmark_per) * 0.8))
        else:
            per_score = max(0, 30 * (1 - (per / benchmark_per)))
        score += per_score
        max_score += 30
    
    # PBR スコア（20点満点）
    pbr = stock_data.get('pbr')
    if pbr and not np.isnan(pbr) and pbr > 0:
        benchmark_pbr = 1.0 if market_mode == '日本株' else 4.0
        if pbr < benchmark_pbr:
            pbr_score = min(20, 20 * (1 - (pbr / benchmark_pbr) * 0.6))
        else:
            pbr_score = max(0, 20 * (1 - (pbr / benchmark_pbr) * 0.5))
        score += pbr_score
        max_score += 20
    
    # 配当利回り（20点満点）
    div_yield = stock_data.get('dividend_yield', 0)
    if div_yield >= 3.5:
        div_score = 20
    elif div_yield >= 2.0:
        div_score = 15
    elif div_yield >= 1.0:
        div_score = 10
    elif div_yield > 0:
        div_score = 5
    else:
        div_score = 0
    score += div_score
    max_score += 20
    
    # 成長性・安全性（30点満点）
    revenue_growth = stock_data.get('revenue_growth')
    equity_ratio = stock_data.get('equity_ratio')
    growth_score = 0
    
    if revenue_growth and not np.isnan(revenue_growth):
        if revenue_growth > 0:
            growth_score += min(15, revenue_growth * 5)
        growth_score = min(15, max(0, growth_score))
    
    if equity_ratio and not np.isnan(equity_ratio):
        threshold = 50 if market_mode == '日本株' else 35
        if equity_ratio > threshold:
            growth_score += min(15, 15 * (equity_ratio / (threshold * 2)))
    
    score += growth_score
    max_score += 30
    
    # 最終スコア計算（取得できたデータだけで100点満点に正規化）
    if max_score > 0:
        final_score = (score / max_score) * 100
    else:
        final_score = 0
    
    return round(final_score, 1)

# ===== 8. スクリーニングロジック =====

def apply_screening(stocks_data, filters, market_mode):
    """
    フィルター条件に基づいてスクリーニングを実行
    """
    results = []
    exchange_rate = get_exchange_rate() if market_mode == '米国株' else 1.0
    
    for stock in stocks_data:
        if stock is None:
            continue
        
        # PER フィルター
        if filters['per_enabled']:
            per = stock.get('per')
            if per is None or np.isnan(per) or per > filters['per_max']:
                continue
        
        # PBR フィルター
        if filters['pbr_enabled']:
            pbr = stock.get('pbr')
            if pbr is None or np.isnan(pbr) or pbr > filters['pbr_max']:
                continue
        
        # 配当利回りフィルター
        if filters['dividend_enabled']:
            div = stock.get('dividend_yield', 0)
            if div < filters['dividend_min']:
                continue
        
        # 時価総額フィルター
        if filters['market_cap_enabled']:
            mcap = stock.get('market_cap')
            threshold = filters['market_cap_min'] * (1e9 if market_mode == '米国株' else 1e9)
            if mcap is None or np.isnan(mcap) or mcap < threshold:
                continue
        
        # 売上高成長率フィルター
        if filters['revenue_growth_enabled']:
            rev_growth = stock.get('revenue_growth')
            if rev_growth is None or np.isnan(rev_growth) or rev_growth < filters['revenue_growth_min']:
                continue
        
        # 自己資本比率フィルター
        if filters['equity_ratio_enabled']:
            equity = stock.get('equity_ratio')
            if equity is None or np.isnan(equity) or equity < filters['equity_ratio_min']:
                continue
        
        # セクターフィルター
        if filters['sector_enabled'] and len(filters['sectors']) > 0:
            if stock.get('sector') not in filters['sectors']:
                continue
        
        results.append(stock)
    
    return results, exchange_rate


def render_selected_stock_details(selected_stock, selected_code, market_mode, exchange_rate, results):
    tab1, tab2, tab3 = st.tabs(["📊 詳細分析", "📰 最新ニュース", "⭐ お気に入り"])

    with tab1:
        st.subheader(f"{selected_stock['name']} の詳細分析")

        score = calculate_buy_timing_score(selected_stock, market_mode)

        st.markdown(
            f"<div style='text-align: center; background-color: {get_score_color(score)}; "
            f"color: white; padding: 20px; border-radius: 10px; margin: 20px 0;'>"
            f"<h2>現在の買い時度</h2><h1>{score:.1f}/100点</h1>"
            f"<p>{'★' * int(score//20)}</p></div>",
            unsafe_allow_html=True
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "現在の株価",
                format_price_jp(selected_stock['price'], market_mode == '米国株', exchange_rate)
            )
        with col2:
            st.metric("PER", f"{safe_get(selected_stock['per'], '-')}")
        with col3:
            st.metric("PBR", f"{safe_get(selected_stock['pbr'], '-')}")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "配当利回り",
                f"{safe_get(selected_stock['dividend_yield'], '-'):.0f}%" if selected_stock.get('dividend_yield') not in [None, np.nan] else '-'
            )
        with col2:
            st.metric(
                "時価総額",
                format_market_cap(selected_stock['market_cap'], market_mode == '米国株', exchange_rate)
            )
        with col3:
            st.metric(
                "セクター",
                selected_stock['sector']
            )

        st.subheader("📊 割安・割高度メーター")
        if selected_stock.get('per') and not np.isnan(selected_stock['per']):
            benchmark_per = 15 if market_mode == '日本株' else 22
            ratio = selected_stock['per'] / benchmark_per
            per_ratio = min(max(ratio, 0.0), 1.0)
            if ratio < 0.5:
                meter_text = "割安"
            elif ratio < 1.0:
                meter_text = "適正"
            else:
                meter_text = "割高"
            st.write("<p>割安 ◀ ───────────────── ▶ 割高</p>", unsafe_allow_html=True)
            st.progress(per_ratio)
            st.caption(f"PER: {selected_stock['per']:.1f}倍（基準値: {benchmark_per}倍） - {meter_text}")

        st.subheader("📈 株価推移（直近1年）")
        with st.spinner("📉 チャートを取得中..."):
            try:
                if selected_code and selected_code.isdigit():
                    chart_ticker = f"{selected_code}.T"
                else:
                    chart_ticker = str(selected_code).upper() if selected_code else None

                hist = yf.download(
                    chart_ticker,
                    start=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
                    end=datetime.now().strftime('%Y-%m-%d'),
                    progress=False,
                    interval='1d',
                    auto_adjust=True
                )

                if (hist is None or len(hist) == 0):
                    try:
                        hist = yf.Ticker(chart_ticker).history(period='1y', interval='1d', auto_adjust=True)
                    except Exception:
                        pass

                close_series = None
                if hist is not None and len(hist) > 0:
                    def get_hist_column(df, col_name):
                        try:
                            if isinstance(df.columns, pd.MultiIndex):
                                for col in df.columns:
                                    if col_name == col[0] or col_name == col[-1] or col_name in col:
                                        try:
                                            return df.loc[:, col]
                                        except Exception:
                                            continue
                            elif col_name in df.columns:
                                return df[col_name]
                        except Exception:
                            pass
                        return None

                    if isinstance(hist, pd.DataFrame):
                        for col_name in ['Close', 'Adj Close']:
                            candidate = get_hist_column(hist, col_name)
                            if candidate is not None:
                                candidate_numeric = pd.to_numeric(candidate, errors='coerce').dropna()
                                if len(candidate_numeric) > 0:
                                    close_series = candidate_numeric
                                    break

                        if close_series is None:
                            for idx, col in enumerate(hist.columns):
                                try:
                                    candidate = pd.to_numeric(hist.iloc[:, idx], errors='coerce').dropna()
                                    if len(candidate) > 0:
                                        close_series = candidate
                                        break
                                except Exception:
                                    continue

                        if close_series is None and hist.shape[1] > 0:
                            try:
                                candidate = pd.to_numeric(hist.iloc[:, 0], errors='coerce').dropna()
                                if len(candidate) > 0:
                                    close_series = candidate
                            except Exception:
                                pass
                    else:
                        close_series = hist

                if close_series is not None and len(close_series) > 0:
                    try:
                        if isinstance(close_series, pd.DataFrame) and close_series.shape[1] >= 1:
                            close_series = close_series.iloc[:, 0]

                        close_series = pd.to_numeric(close_series, errors='coerce').dropna()
                        if close_series is None or len(close_series) == 0:
                            raise ValueError('no numeric data after coercion')

                        arr = np.asarray(close_series)
                        arr = np.squeeze(arr)
                        if arr.ndim == 2:
                            if arr.shape[1] == 1:
                                arr = arr[:, 0]
                            else:
                                arr = arr[:, 0]
                                st.warning('複数列のデータが見つかったため、最初の列を使用します。')

                        if arr.ndim == 1 and arr.size > 0:
                            try:
                                if isinstance(close_series, pd.Series):
                                    plot_values = pd.DataFrame(close_series.rename('Close'))
                                else:
                                    plot_values = pd.DataFrame(
                                        {'Close': np.asarray(arr).ravel()},
                                        index=getattr(close_series, 'index', None)
                                    )
                                st.line_chart(plot_values, use_container_width=True)
                            except Exception as e_inner:
                                raise ValueError(f'plot conversion failed: {e_inner}')
                        else:
                            raise ValueError('resulting array is not 1-d')
                    except Exception as e:
                        hist_info = None
                        try:
                            hist_info = {'shape': getattr(hist, 'shape', None), 'columns': getattr(hist, 'columns', None)}
                        except Exception:
                            hist_info = str(getattr(hist, '__class__', type(hist)))
                        st.warning(f"チャート取得エラー: {str(e)}")
                        st.info(f"hist info: {hist_info} | close_series type: {type(close_series)} | close_series shape: {getattr(close_series, 'shape', None)}")
                else:
                    st.warning("チャートデータが取得できませんでした")
            except Exception as e:
                st.warning(f"⚠️ チャート取得エラー: {str(e)}")

    with tab2:
        st.subheader(f"{selected_stock['name']} の最新ニュース")

        with st.spinner("📰 ニュースを取得中..."):
            try:
                stock_obj = selected_stock['stock_obj']
                news = stock_obj.news

                if news and len(news) > 0:
                    for idx, item in enumerate(news[:5]):
                        # yfinanceのニュース構造: {'id': '...', 'content': {...}}
                        title = '不明'
                        link = '#'

                        try:
                            if isinstance(item, dict):
                                # contentキーからデータ抽出
                                content = item.get('content', {})
                                if isinstance(content, dict):
                                    title = content.get('title', '不明')
                                    # clickThroughUrlからURLを取得
                                    ctu = content.get('clickThroughUrl', {})
                                    if isinstance(ctu, dict) and 'url' in ctu:
                                        link = ctu['url']
                        except Exception:
                            pass

                        # リンクが'#'の場合は不明と判定
                        if link == '#' or not link:
                            title_display = f"📰 {title}"
                        else:
                            title_display = f"📰 <a href='{link}' target='_blank'>{title}</a>"

                        negative_words = ['減益', '下落', 'Down', 'Drop', 'Loss', '赤字', '損失', '破産', '閉鎖']
                        positive_words = ['増益', '上昇', 'Up', 'Gain', 'Profit', '高成長', '買収', '拡大']

                        news_color = 'black'
                        if any(word in title for word in negative_words):
                            news_color = '#ff0000'
                        elif any(word in title for word in positive_words):
                            news_color = '#00d084'

                        st.markdown(
                            f"<p style='color: {news_color}; font-weight: bold;'>{title_display}</p>",
                            unsafe_allow_html=True
                        )
                else:
                    st.info("ℹ️ ニュース情報が取得できませんでした")
            except Exception as e:
                st.error(f"❌ ニュース取得エラー: {str(e)}")




    with tab3:
        st.subheader("⭐ お気に入り銘柄")
        col1, col2 = st.columns([1, 1])

        with col1:
            if st.button(
                "💕 お気に入りに追加",
                use_container_width=True,
                key='add_favorite'
            ):
                if selected_code not in st.session_state.favorites:
                    st.session_state.favorites.append(selected_code)
                    save_favorites(st.session_state.favorites)
                    st.success(f"✅ {selected_stock['name']}をお気に入りに追加しました！")
                else:
                    st.info(f"ℹ️ {selected_stock['name']}は既にお気に入りに入っています")

        with col2:
            if st.button(
                "🗑️ お気に入りから削除",
                use_container_width=True,
                key='remove_favorite'
            ):
                if selected_code in st.session_state.favorites:
                    st.session_state.favorites.remove(selected_code)
                    save_favorites(st.session_state.favorites)
                    st.success(f"✅ {selected_stock['name']}をお気に入りから削除しました！")

        if len(st.session_state.favorites) > 0:
            st.markdown("#### 保存済み銘柄")
            favorite_data = []
            for fav_code in st.session_state.favorites:
                fav_stock = next((s for s in results if s['ticker'] == fav_code), None)
                if fav_stock:
                    favorite_data.append({
                        'コード': fav_code,
                        '企業名': fav_stock['name'],
                        '現在の株価': format_price_jp(fav_stock['price'], market_mode == '米国株', exchange_rate),
                        'セクター': fav_stock['sector']
                    })

            if favorite_data:
                df_favorites = pd.DataFrame(favorite_data)
                st.dataframe(df_favorites, use_container_width=True, hide_index=True)
        else:
            st.info("💡 お気に入りの銘柄がまだありません。分析画面から追加しましょう！")

# ===== 9. UI - メインタイトル =====

# メイン画面の大見出しはサイドバーに移動しました。

st.markdown("---")

# ===== 10. UI - サイドバー設定 =====

with st.sidebar:
    st.markdown("### デマーシア！！！")
    st.header("⚙️ スクリーニング設定")
    
    # 市場選択
    market_mode = st.radio(
        "📍 **市場選択**",
        ('日本株', '米国株'),
        key='market_radio'
    )
    st.session_state.market_mode = market_mode
    
    st.markdown("---")
    
    # プリセットボタン
    st.subheader("🎯 オススメプリセット")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("手堅く配当狙い", key='preset1', use_container_width=True):
            st.session_state.preset_selected = 'dividend'
            if market_mode == '日本株':
                st.session_state.per_max = 14.0
                st.session_state.pbr_max = 0.9
                st.session_state.dividend_min = 3.8
                st.session_state.equity_ratio_min = 50.0
                st.session_state.revenue_growth_min = 0.0
                st.session_state.market_cap_min = 0.0
            else:
                st.session_state.per_max = 22.0
                st.session_state.pbr_max = 5.0
                st.session_state.dividend_min = 3.5
                st.session_state.equity_ratio_min = 35.0
                st.session_state.revenue_growth_min = 0.0
                st.session_state.market_cap_min = 20.0
            st.session_state.per_check = True
            st.session_state.pbr_check = True
            st.session_state.div_check = True
            st.session_state.equity_check = True
            st.session_state.revgrow_check = True
            st.session_state.mcap_check = False

    with col2:
        if st.button("割安成長株狙い", key='preset2', use_container_width=True):
            st.session_state.preset_selected = 'growth'
            if market_mode == '日本株':
                st.session_state.per_max = 15.0
                st.session_state.pbr_max = 1.5
                st.session_state.dividend_min = 1.0
                st.session_state.equity_ratio_min = 40.0
                st.session_state.revenue_growth_min = 5.0
                st.session_state.market_cap_min = 10.0
            else:
                st.session_state.per_max = 22.0
                st.session_state.pbr_max = 100.0
                st.session_state.dividend_min = 1.0
                st.session_state.equity_ratio_min = 35.0
                st.session_state.revenue_growth_min = 10.0
                st.session_state.market_cap_min = 20.0
            st.session_state.per_check = True
            st.session_state.pbr_check = False
            st.session_state.div_check = True
            st.session_state.equity_check = True
            st.session_state.revgrow_check = True
            st.session_state.mcap_check = True

    if st.session_state.preset_selected:
        with st.expander("プリセットの解説", expanded=False):
            if st.session_state.preset_selected == 'dividend':
                st.info(
                    "💡 **手堅く配当狙い**\n\n"
                    "割安で元本割れリスクが低く、高い配当を出し続ける"
                    "「倒産しにくい日本の優良大企業」をあぶり出します。"
                )
            else:
                st.info(
                    "💡 **王道の割安成長株**\n\n"
                    "世界でビジネスを拡大している企業の中から、実力に対して"
                    "まだ株価が高すぎない「お宝成長株」を探します。"
                )

    # サイドバーにお気に入り一覧を表示（登録済みがあれば）
    if len(st.session_state.favorites) > 0:
        with st.expander("⭐ お気に入り一覧", expanded=True):
            fav_rows = []
            for fav in st.session_state.favorites:
                try:
                    data = fetch_stock_data(fav)
                    if data:
                        fav_rows.append({
                            'コード': data['ticker'],
                            '企業名': data['name'],
                            '株価': format_price_jp(data['price'], st.session_state.market_mode == '米国株', get_exchange_rate()),
                        })
                except Exception:
                    continue
            if fav_rows:
                st.markdown("**コード / 企業名**")
                for fav in fav_rows:
                    display_name = fav['企業名']
                    if len(display_name) > 20:
                        display_name = display_name[:20] + '...'
                    cols = st.columns([1, 3, 1])
                    cols[0].write(fav['コード'])
                    cols[1].write(display_name)
                    if cols[2].button("詳細", key=f"fav_detail_{fav['コード']}"):
                        st.session_state.selected_ticker = fav['コード']
            else:
                st.info("お気に入り銘柄のデータを取得できませんでした")

    st.markdown("---")
    
    # スクリーニング条件
    st.subheader("🔍 詳細条件")
    
    # PER
    per_enabled = st.checkbox("PER制限", value=True, key='per_check')
    if per_enabled:
        per_max = st.slider(
            "PER上限（倍）",
            min_value=0.0,
            max_value=50.0,
            value=st.session_state.get('per_max', 20.0),
            step=0.5,
            key='per_slider'
        )
        st.session_state.per_max = per_max
    else:
        per_max = 999
    
    # PBR
    pbr_enabled = st.checkbox("PBR制限", value=False, key='pbr_check')
    if pbr_enabled:
        pbr_max = st.slider(
            "PBR上限（倍）",
            min_value=0.0,
            max_value=10.0,
            value=st.session_state.get('pbr_max', 2.0),
            step=0.1,
            key='pbr_slider'
        )
        st.session_state.pbr_max = pbr_max
    else:
        pbr_max = 999
    
    # 配当利回り
    dividend_enabled = st.checkbox("配当利回り制限", value=False, key='div_check')
    if dividend_enabled:
        dividend_min = st.slider(
            "配当利回り下限（%）",
            min_value=0.0,
            max_value=10.0,
            value=st.session_state.get('dividend_min', 2.0),
            step=0.1,
            key='div_slider'
        )
        st.session_state.dividend_min = dividend_min
    else:
        dividend_min = 0
    
    # 時価総額
    market_cap_enabled = st.checkbox("時価総額制限", value=False, key='mcap_check')
    if market_cap_enabled:
        market_cap_min = st.slider(
            "時価総額下限（十億" + ("ドル" if market_mode == '米国株' else "円") + "）",
            min_value=0.0,
            max_value=100.0,
            value=st.session_state.get('market_cap_min', 10.0),
            step=1.0,
            key='mcap_slider'
        )
        st.session_state.market_cap_min = market_cap_min
    else:
        market_cap_min = 0
    
    # 売上高成長率
    revenue_growth_enabled = st.checkbox("売上高成長率制限", value=False, key='revgrow_check')
    if revenue_growth_enabled:
        revenue_growth_min = st.slider(
            "売上高成長率下限（%）",
            min_value=-50.0,
            max_value=100.0,
            value=st.session_state.get('revenue_growth_min', 0.0),
            step=1.0,
            key='revgrow_slider'
        )
        st.session_state.revenue_growth_min = revenue_growth_min
    else:
        revenue_growth_min = -999
    
    # 自己資本比率
    equity_ratio_enabled = st.checkbox("自己資本比率制限", value=False, key='equity_check')
    if equity_ratio_enabled:
        equity_ratio_min = st.slider(
            "自己資本比率下限（%）",
            min_value=0.0,
            max_value=100.0,
            value=st.session_state.get('equity_ratio_min', 30.0),
            step=1.0,
            key='equity_slider'
        )
        st.session_state.equity_ratio_min = equity_ratio_min
    else:
        equity_ratio_min = 0
    
    # セクター選択
    sector_enabled = st.checkbox("業種制限", value=False, key='sector_check')
    sectors_selected = []
    if sector_enabled:
        available_sectors = list(set([
            'テクノロジー（IT・半導体）',
            '金融（銀行・保険）',
            '景気敏感消費財（自動車・アパレル等）',
            '医療・ヘルスケア',
            '工業・製造業',
            '通信・メディア',
            'エネルギー（石油・電力）',
            '不動産',
            'インフラ・公共',
            '生活必需品',
            '素材・鉱物'
        ]))
        sectors_selected = st.multiselect(
            "業種選択",
            available_sectors,
            default=[],
            key='sector_select'
        )
    
    st.markdown("---")
    
    # スクリーニング実行ボタン
    screening_button = st.button("🔎 スクリーニング実行", use_container_width=True, type="primary")

# ===== 11. メインエリア - スクリーニング実行 =====

if screening_button:
    with st.spinner("📊 データを取得中..."):
        # サンプルデータ取得
        sample_stocks = SAMPLE_STOCKS_JP if market_mode == '日本株' else SAMPLE_STOCKS_US
        stocks_data = [fetch_stock_data(ticker) for ticker in sample_stocks]
        
        # フィルター設定
        filters = {
            'per_enabled': per_enabled,
            'per_max': per_max,
            'pbr_enabled': pbr_enabled,
            'pbr_max': pbr_max,
            'dividend_enabled': dividend_enabled,
            'dividend_min': dividend_min,
            'market_cap_enabled': market_cap_enabled,
            'market_cap_min': market_cap_min,
            'revenue_growth_enabled': revenue_growth_enabled,
            'revenue_growth_min': revenue_growth_min,
            'equity_ratio_enabled': equity_ratio_enabled,
            'equity_ratio_min': equity_ratio_min,
            'sector_enabled': sector_enabled,
            'sectors': sectors_selected
        }
        
        # スクリーニング実行
        screening_results, exchange_rate = apply_screening(stocks_data, filters, market_mode)
        st.session_state.screening_results = screening_results
        st.session_state.current_exchange_rate = exchange_rate
        st.session_state.market_mode = market_mode

# スクリーニング結果表示
if 'screening_results' in st.session_state:
    results = st.session_state.screening_results
    exchange_rate = st.session_state.current_exchange_rate
    
    # 結果カウント表示
    total_count = len(SAMPLE_STOCKS_JP) if market_mode == '日本株' else len(SAMPLE_STOCKS_US)
    result_count = len(results)
    
    st.markdown(f"### 📋 全 {total_count} 銘柄中、条件に合う株が **{result_count}** 企業見つかりました！")
    
    if result_count > 0:
        # 結果をDataFrame化
        df_results = []
        for stock in results:
            is_us = market_mode == '米国株'
            row = {
                'コード/ティッカー': stock['ticker'],
                '企業名': stock['name'],
                '現在の株価': format_price_jp(stock['price'], is_us, exchange_rate),
                'PER': f"{safe_get(stock['per'], '-'):.1f}" if stock['per'] and not np.isnan(stock['per']) else '-',
                'PBR': f"{safe_get(stock['pbr'], '-'):.2f}" if stock['pbr'] and not np.isnan(stock['pbr']) else '-',
                '配当利回り（%）': f"{safe_get(stock['dividend_yield'], '-'):.2f}" if stock['dividend_yield'] else '-',
                '時価総額': format_market_cap(stock['market_cap'], is_us, exchange_rate),
                '売上高成長率（%）': f"{safe_get(stock['revenue_growth'], '-'):.1f}" if stock['revenue_growth'] and not np.isnan(stock['revenue_growth']) else '-',
                '自己資本比率（%）': f"{safe_get(stock['equity_ratio'], '-'):.1f}" if stock['equity_ratio'] and not np.isnan(stock['equity_ratio']) else '-',
                'セクター': stock['sector'],
            }
            df_results.append(row)
        
        df_display = pd.DataFrame(df_results)

        # カスタム表示: テーブル形式で各行に「詳細表示」ボタンを追加
        st.markdown("### 抽出結果")
        # CSV ダウンロードボタン
        csv_buffer = io.StringIO()
        df_display.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        csv_data = csv_buffer.getvalue().encode('utf-8-sig')

        col_dl, _ = st.columns([1, 9])
        with col_dl:
            st.download_button(
                label="📥 CSVダウンロード",
                data=csv_data,
                file_name=f"screening_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        st.markdown("---")

        # ヘッダー表示（列幅は比率で調整）
        header_cols = st.columns([1.0, 2.4, 1.0, 0.7, 0.7, 0.9, 1.0, 0.9, 0.9, 1.6, 0.8])
        headers = list(df_display.columns) + ['操作']
        for c, h in zip(header_cols, headers):
            c.markdown(f"**{h}**")

        # 行ごとに表示して最後の列にボタンを配置
        for stock in results:
            cols = st.columns([1.0, 2.4, 1.0, 0.7, 0.7, 0.9, 1.0, 0.9, 0.9, 1.6, 0.8])
            cols[0].write(stock['ticker'])
            cols[1].write(stock['name'])
            cols[2].write(format_price_jp(stock['price'], market_mode == '米国株', exchange_rate))
            cols[3].write(f"{safe_get(stock['per'], '-'):.1f}" if stock['per'] and not np.isnan(stock['per']) else '-')
            cols[4].write(f"{safe_get(stock['pbr'], '-'):.2f}" if stock['pbr'] and not np.isnan(stock['pbr']) else '-')
            cols[5].write(f"{safe_get(stock['dividend_yield'], '-'):.2f}" if stock['dividend_yield'] else '-')
            cols[6].write(format_market_cap(stock['market_cap'], market_mode == '米国株', exchange_rate))
            cols[7].write(f"{safe_get(stock['revenue_growth'], '-'):.1f}" if stock['revenue_growth'] and not np.isnan(stock['revenue_growth']) else '-')
            cols[8].write(f"{safe_get(stock['equity_ratio'], '-'):.1f}" if stock['equity_ratio'] and not np.isnan(stock['equity_ratio']) else '-')
            cols[9].write(stock['sector'])
            if cols[10].button("詳細表示", key=f"detail_{stock['ticker']}"):
                st.session_state.selected_ticker = stock['ticker']

        selected_code = st.session_state.selected_ticker or (results[0]['ticker'] if len(results) > 0 else None)
        selected_stock = next((s for s in results if s['ticker'] == selected_code), None)

        if selected_stock is None and selected_code is not None:
            fetched = fetch_stock_data(selected_code)
            if fetched:
                selected_stock = fetched

        if selected_stock:
            render_selected_stock_details(selected_stock, selected_code, market_mode, exchange_rate, results)


elif st.session_state.selected_ticker:
    selected_code = st.session_state.selected_ticker
    selected_stock = fetch_stock_data(selected_code)
    if selected_stock:
        exchange_rate = get_exchange_rate() if market_mode == '米国株' else 1.0
        render_selected_stock_details(selected_stock, selected_code, market_mode, exchange_rate, [])
