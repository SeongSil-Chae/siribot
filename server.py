from fastapi import FastAPI, Request
from datetime import datetime
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import quote
import yfinance as yf
import FinanceDataReader as fdr

app = FastAPI()

print("종목 리스트 불러오는 중...")

KRX = fdr.StockListing("KRX")

try:
    NASDAQ = fdr.StockListing("NASDAQ")
except Exception:
    NASDAQ = None

try:
    NYSE = fdr.StockListing("NYSE")
except Exception:
    NYSE = None

try:
    AMEX = fdr.StockListing("AMEX")
except Exception:
    AMEX = None

print(f"KRX {len(KRX)}개 로드 완료")

ALIAS = {
    "삼전": "삼성전자",
    "하닉": "SK하이닉스",
    "sk하이닉스": "SK하이닉스",
    "슼스퀘어": "SK스퀘어",
    "sk스퀘어": "SK스퀘어",
    "네이버": "NAVER",

    "테슬라": "TSLA",
    "애플": "AAPL",
    "엔비디아": "NVDA",
    "마소": "MSFT",
    "마이크로소프트": "MSFT",
    "구글": "GOOGL",
    "알파벳": "GOOGL",
    "아마존": "AMZN",
    "메타": "META",
    "페이스북": "META",
    "브로드컴": "AVGO",
    "넷플릭스": "NFLX",
    "코카콜라": "KO",
    "버크셔": "BRK-B",
    "스페이스x": "SPCX",
    "spacex": "SPCX",
}

INDEX_MAP = {
    "코스피": "^KS11",
    "kospi": "^KS11",
    "코스닥": "^KQ11",
    "kosdaq": "^KQ11",
    "나스닥": "^IXIC",
    "nasdaq": "^IXIC",
    "다우": "^DJI",
    "dow": "^DJI",
    "s&p500": "^GSPC",
    "sp500": "^GSPC",
    "에스앤피": "^GSPC",
    "환율": "USDKRW=X",
    "달러": "USDKRW=X",
    "usd": "USDKRW=X",
}

FUTURES_MAP = {
    "S&P 500 선물": "ES=F",
    "나스닥 100 선물": "NQ=F",
    "러셀 2000 선물": "RTY=F",
    "S&P 500 VIX": "^VIX",
}

def get_futures_message():
    lines = []

    for name, ticker in FUTURES_MAP.items():
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")

        if hist.empty:
            continue

        price = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2] if len(hist) >= 2 else price
        diff = price - prev
        rate = diff / prev * 100 if prev else 0

        lines.append(f"🇺🇸 {name}\n{price:,.2f}p ({rate:+.2f}%)")

    return "\n\n".join(lines)

@app.get("/debug-html")
def debug_html():
    url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, timeout=5)

    text = res.text

    keywords = ["상승", "보합", "하락", "개인", "외국인", "기관", "프로그램"]
    result = {}

    for keyword in keywords:
        idx = text.find(keyword)
        if idx == -1:
            result[keyword] = "못 찾음"
        else:
            result[keyword] = text[max(0, idx-500):idx+1000]

    return result

@app.get("/debug")
def debug():
    return get_naver_index_extra("KOSPI")

@app.get("/")
def root():
    return {"message": "시리봇 준비 완료"}

def format_market_cap(value):
    if not value:
        return "-"

    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}조"

    if value >= 1_000_000:
        return f"{value / 1_000_000:,.0f}백만"

    return f"{value:,}"


def normalize(text: str) -> str:
    return text.strip().replace(" ", "").lower()


def search_krx(text: str):
    key = normalize(text)

    # 종목코드 6자리
    if text.isdigit() and len(text) == 6:
        matched = KRX[KRX["Code"] == text]
        name = matched.iloc[0]["Name"] if not matched.empty else text
        return f"{text}.KS", name

    # 정확히 일치
    exact = KRX[KRX["Name"].apply(lambda x: normalize(str(x)) == key)]
    if not exact.empty:
        row = exact.iloc[0]
        market = row.get("Market", "")
        suffix = ".KQ" if market == "KOSDAQ" else ".KS"
        return f"{row['Code']}{suffix}", row["Name"]

    # 부분 검색
    contains = KRX[KRX["Name"].apply(lambda x: key in normalize(str(x)))]
    if len(contains) == 1:
        row = contains.iloc[0]
        market = row.get("Market", "")
        suffix = ".KQ" if market == "KOSDAQ" else ".KS"
        return f"{row['Code']}{suffix}", row["Name"]

    if len(contains) > 1:
        candidates = []
        for _, row in contains.head(5).iterrows():
            candidates.append(f"- {row['Name']} ({row['Code']})")
        return None, "검색 결과가 여러 개 있어요.\n\n" + "\n".join(candidates)

    return None, None


def search_us(text: str):
    query = text.strip()
    key = normalize(query)

    if query.isascii() and query.replace(".", "").replace("-", "").isalnum() and query.upper() == query and len(query) <= 8:
        return query.upper().replace(".", "-"), query.upper()

    markets = [NASDAQ, NYSE, AMEX]

    for market in markets:
        if market is None:
            continue

        # Symbol 정확히 일치
        if "Symbol" in market.columns:
            exact_symbol = market[market["Symbol"].str.upper() == query.upper()]
            if not exact_symbol.empty:
                row = exact_symbol.iloc[0]
                return row["Symbol"], row.get("Name", row["Symbol"])

        # Name 정확히/부분 일치
        if "Name" in market.columns:
            exact_name = market[market["Name"].apply(lambda x: normalize(str(x)) == key)]
            if not exact_name.empty:
                row = exact_name.iloc[0]
                return row["Symbol"], row["Name"]

            contains = market[market["Name"].apply(lambda x: key in normalize(str(x)))]
            if len(contains) == 1:
                row = contains.iloc[0]
                return row["Symbol"], row["Name"]

            if len(contains) > 1:
                candidates = []
                for _, row in contains.head(5).iterrows():
                    candidates.append(f"- {row.get('Name', '')} ({row.get('Symbol', '')})")
                return None, "미국주식 검색 결과가 여러 개 있어요.\n\n" + "\n".join(candidates)

    return query.upper(), query.upper()


def find_ticker(user_text: str):
    text = user_text.strip()
    key = normalize(text)

    if key in INDEX_MAP:
        return INDEX_MAP[key], text, None

    if key in ALIAS:
        text = ALIAS[key]

    if text.upper() in INDEX_MAP:
        return INDEX_MAP[text.upper()], text, None

    # 국내 먼저 검색
    ticker, result = search_krx(text)
    if ticker:
        return ticker, result, None

    if result:
        return None, None, result

    # 미국 검색
    ticker, result = search_us(text)
    if ticker:
        return ticker, result, None

    if result:
        return None, None, result

    return None, None, f"'{user_text}'에 맞는 종목을 찾지 못했어요."

def get_naver_index_extra(index_code: str):
    try:
        url = f"https://finance.naver.com/sise/sise_index.naver?code={index_code}"
        headers = {"User-Agent": "Mozilla/5.0"}

        res = requests.get(url, headers=headers, timeout=5)
        html = res.text

        result = {
            "personal": "-",
            "foreign": "-",
            "institution": "-",
            "program": "-",
            "up": "-",
            "flat": "-",
            "down": "-"
        }

        # 상승 / 보합 / 하락 종목수
        up = re.search(r'상승종목수.*?<span>([\d,]+)</span>', html, re.S)
        flat = re.search(r'보합종목수.*?<span>([\d,]+)</span>', html, re.S)
        down = re.search(r'하락종목수.*?<span>([\d,]+)</span>', html, re.S)

        if up:
            result["up"] = up.group(1)
        if flat:
            result["flat"] = flat.group(1)
        if down:
            result["down"] = down.group(1)

        # 개인 / 외국인 / 기관
        personal = re.search(r'개인<br><span class="[^"]+">([+-]?[\d,]+)<span>억</span>', html)
        foreign = re.search(r'외국인<br><span class="[^"]+">([+-]?[\d,]+)<span>억</span>', html)
        institution = re.search(r'기관<br><span class="[^"]+">([+-]?[\d,]+)<span>억</span>', html)

        if personal:
            result["personal"] = personal.group(1) + "억"
        if foreign:
            result["foreign"] = foreign.group(1) + "억"
        if institution:
            result["institution"] = institution.group(1) + "억"

        # 프로그램: 비차익 / 차익
        arbitrage = re.search(r'차익<br><span class="[^"]+">([+-]?[\d,]+)<span>억</span>', html)
        non_arbitrage = re.search(r'비차익<br><span class="[^"]+">([+-]?[\d,]+)<span>억</span>', html)

        if non_arbitrage and arbitrage:
            result["program"] = f'{non_arbitrage.group(1)} / {arbitrage.group(1)}억'

        return result

    except Exception as e:
        return {
            "personal": "-",
            "foreign": "-",
            "institution": "-",
            "program": "-",
            "up": "-",
            "flat": "-",
            "down": "-"
        }


def get_index_message(display_name, ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="5d")

    if hist.empty:
        return f"{display_name} 조회 결과가 없습니다."

    price = hist["Close"].iloc[-1]
    prev = hist["Close"].iloc[-2] if len(hist) >= 2 else price

    diff = price - prev
    rate = diff / prev * 100 if prev else 0

    arrow = "▲" if diff >= 0 else "▼"
    color = "🔴" if diff >= 0 else "🔵"
    chart = "📈" if diff >= 0 else "📉"

    now = datetime.now().strftime("%H:%M")

    # 네이버 추가 데이터
    if ticker == "^KS11":
        naver_code = "KOSPI"
    elif ticker == "^KQ11":
        naver_code = "KOSDAQ"
    else:
        naver_code = None

    if naver_code:
        extra = get_naver_index_extra(naver_code)
    else:
        extra = {
            "personal": "-",
            "foreign": "-",
            "institution": "-",
            "program": "-",
            "up": "-",
            "flat": "-",
            "down": "-"
        }

    return f"""{chart} {display_name} ({now})
{color} {price:,.2f}p {arrow}{abs(diff):,.2f}p ({rate:+.2f}%)

 ➥ 개인 {extra["personal"]}
 ➥ 외인 {extra["foreign"]}
 ➥ 기관 {extra["institution"]}
 ➥ 비차익/차익 {extra["program"]}

상승 {extra["up"]} | 보합 {extra["flat"]} | 하락 {extra["down"]}"""

def get_market_name(ticker):
    if ticker.endswith(".KS"):
        return "코스피"
    if ticker.endswith(".KQ"):
        return "코스닥"
    return "미국"


def format_price(price, ticker):
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return f"{price:,.0f}원"
    return f"{price:,.2f}"

def get_news_message(keyword, limit=3):
    try:
        url = f"https://search.naver.com/search.naver?where=news&query={quote(keyword)}"

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        html = requests.get(url, headers=headers, timeout=5).text

        soup = BeautifulSoup(html, "html.parser")

        news = soup.select("a.news_tit")[:limit]

        if not news:
            return ""

        lines = ["", "📰 관련 뉴스"]

        for item in news:
            title = item.get("title", "").strip()

            if title:
                lines.append(f"• {title}")

        return "\n".join(lines)

    except Exception:
        return ""

def get_stock_message(user_text: str) -> str:
    ticker, display_name, error = find_ticker(user_text)

    if error:
        return error

    if ticker in ["^KS11", "^KQ11", "^IXIC", "^DJI", "^GSPC"]:
        return get_index_message(display_name, ticker)

    stock = yf.Ticker(ticker)

    try:
        info = stock.info
    except Exception:
        info = {}

    market_cap = info.get("marketCap")
    volume = info.get("volume", 0)
    per = info.get("trailingPE")
    pbr = info.get("priceToBook")
    sector = info.get("sector")
    foreign = info.get("heldPercentInstitutions")

    volume_text = f"{volume:,}" if volume else "-"
    per_text = f"{per:.2f}" if per else "-"
    pbr_text = f"{pbr:.2f}" if pbr else "-"
    sector_text = sector if sector else "-"

    if foreign is not None:
        foreign_text = f"{foreign * 100:.2f}%"
    else:
        foreign_text = "-"

    price = None
    prev_close = None

    try:
        fast_info = stock.fast_info
        price = fast_info.get("last_price")
        prev_close = fast_info.get("previous_close")
    except Exception:
        pass

    if price is None:
        hist = stock.history(period="5d")
        if hist.empty:
            return f"'{user_text}' 조회 결과가 없습니다.\n변환 티커: {ticker}"

        price = hist["Close"].iloc[-1]
        prev_close = hist["Close"].iloc[-2] if len(hist) >= 2 else price

    diff = price - prev_close if prev_close else 0
    rate = (diff / prev_close * 100) if prev_close else 0

    arrow = "▲" if diff >= 0 else "▼"
    color = "🔴" if diff >= 0 else "🔵"

    market_name = get_market_name(ticker)
    clean_ticker = ticker.replace(".KS", "").replace(".KQ", "")

    news_text = get_news_message(display_name)

    return f"""{display_name} ({clean_ticker}) {market_name}

{color} {format_price(price, ticker)} {arrow}{format_price(abs(diff), ticker)} ({rate:+.2f}%)

• 시가총액: {format_market_cap(market_cap)}
• 거래량: {volume_text}주
• PER: {per_text}
• PBR: {pbr_text}
• 업종: {sector_text}
• 외국인비중: {foreign_text}{news_text}"""
@app.get("/test/{keyword}")
def test_stock(keyword: str):
    return {
        "keyword": keyword,
        "result": get_stock_message(keyword)
    }


@app.post("/kakao")
async def kakao(request: Request):
    body = await request.json()
    user_text = body.get("userRequest", {}).get("utterance", "").strip()

    try:
        if user_text in ["ㅅㅁ", "선물", "미국선물"]:
            reply = get_futures_message()
        else:
            reply = get_stock_message(user_text)

    except Exception as e:
        reply = f"조회 중 오류가 발생했습니다.\n입력값: {user_text}\n오류: {str(e)}"

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": reply
                    }
                }
            ]
        }
    }